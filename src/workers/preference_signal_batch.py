"""사용자 브랜드 선호·비선호 신호 배치 — docs/사용자_선호비선호_기록_설계.md §5 (파이프라인 B).

engine.feedback_event(item_replaced)를 사용자·슬롯별로 모아, 브랜드를 바꾼 교체가 있으면
identity.preference_signal에 신호를 쌓는다. 부품을 빼기만 한 것(item_removed)은 세지 않는다(_observations 참고).

stage6_feedback.run_batch()(엔진 전체 가중치 재학습, 별도 승인 게이트)와는 범위가 다르다 — 이건
사용자 개인의 신호만 다루고, 추천 엔진의 전역 가중치는 건드리지 않는다.

멱등성: 매번 최근 WINDOW_DAYS 안의 이벤트로 (user, slot, brand)별 선호·비선호 횟수를 **처음부터 다시 세고**
그 순(net) 횟수를 그대로 기록한다(PreferenceRepo.set_inferred — 더하지 않는다). 그래서 몇 번을 다시 돌려도 같고,
바뀐 신호만 갱신 건수에 든다. 예전엔 새 이벤트만 더하는 방식이라 방향이 반대인 관측(A→B 뒤 B→A)이 한 행에서
방향을 덮고 횟수를 합쳤다 — 이제 교체 이벤트 하나는 넣은 브랜드에 선호 +1, 뺀 브랜드에 비선호 +1 이고, 두 방향은
서로 상쇄된다. 직접 말한 신호(explicit_chat)는 배치가 건드리지 않는다.

"패턴으로 볼지"(REPEAT_THRESHOLD)는 여기서 쌓기를 막는 문턱이 아니라, 신호를 화면에 보여줄지
결정하는 문턱이다(PreferenceRepo.list_active(min_confidence=...), session_service.preference_hint) —
그래야 이번 실행에서 새 이벤트가 1~2건만 있어도 confidence는 정확히 누적되고, 문턱을 넘는 순간
바로 되물을 수 있다(문턱 넘기 전 관측을 버리지 않는다)."""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from psycopg.rows import dict_row

from src.repo.preference_repo import PreferenceRepo

REPEAT_THRESHOLD = 3      # 이 이상이어야 화면에 보여준다 (설계 문서 §9, 임시값) — 쌓는 문턱이 아니다
WINDOW_DAYS = 90


def _replaced_brand_pairs(conn, user_id: UUID | None = None) -> list[dict]:
    """최근 item_replaced 이벤트에서 (user_id, slot, from_brand, to_brand, event_id)를 뽑는다.
    payload에 from_variant_id/to_variant_id/slot이 없는(구버전) 이벤트는 건너뛴다."""
    return conn.cursor(row_factory=dict_row).execute(
        """
        SELECT fe.id AS event_id, fe.user_id, fe.payload->>'slot' AS slot,
               fb.brand AS from_brand, tb.brand AS to_brand
        FROM engine.feedback_event fe
        JOIN catalog.product_variant fv ON fv.id = (fe.payload->>'from_variant_id')::uuid
        JOIN catalog.product fb ON fb.id = fv.product_id
        JOIN catalog.product_variant tv ON tv.id = (fe.payload->>'to_variant_id')::uuid
        JOIN catalog.product tb ON tb.id = tv.product_id
        WHERE fe.event_type = 'item_replaced'
          AND fe.user_id IS NOT NULL
          AND (%s::uuid IS NULL OR fe.user_id = %s::uuid)
          AND fe.payload ? 'from_variant_id' AND fe.payload ? 'to_variant_id'
          AND fe.occurred_at >= now() - (%s || ' days')::interval
        """,
        (user_id, user_id, WINDOW_DAYS),
    ).fetchall()


def _observations(conn, user_id: UUID | None = None) -> dict[tuple[UUID, str, str], dict]:
    """(user, slot, brand) → {"prefer": 횟수, "avoid": 횟수, "events": [id…], "last": 마지막 관측 방향}.
    교체 이벤트 하나는 넣은 브랜드에 prefer, 뺀 브랜드에 avoid 로 한 번씩 센다. 같은 브랜드끼리 바꾼 건 세지 않는다.

    부품을 빼기만 한 것(item_removed)은 세지 않는다 — 이미 갖고 있어서·예산 때문에·나중에 사려고 빼는 일이 많아
    브랜드에 대한 의사가 아니다. 추천 시스템에서 장바구니 제거 같은 암묵적 부정은 모호한 약한 신호로 다룬다
    (이유가 확인될 때만 쓰는 쪽은 이유 추출과 함께 검토). 교체는 같은 자리에 다른 브랜드를 고른 것이라 센다."""
    seen: dict[tuple[UUID, str, str], dict] = defaultdict(lambda: {"prefer": 0, "avoid": 0, "events": [], "last": None})

    def add(user_id, slot, brand, direction, event_id):
        obs = seen[(user_id, slot, brand)]
        obs[direction] += 1
        obs["events"].append(event_id)
        obs["last"] = direction

    for row in _replaced_brand_pairs(conn, user_id):
        if row["from_brand"] != row["to_brand"]:
            add(row["user_id"], row["slot"], row["to_brand"], "prefer", row["event_id"])
            add(row["user_id"], row["slot"], row["from_brand"], "avoid", row["event_id"])
    return seen


def run(conn, user_id: UUID | None = None) -> dict:
    """배치 1회 실행. 반환값은 몇 건의 신호가 실제로 바뀌었는지(로그·테스트용) — 다시 돌려 같으면 0.

    user_id 를 주면 그 사용자 것만 다시 센다 — 되묻기 조회(session_service.preference_hint)가 보여 주기 직전에
    부른다. 이 프로젝트엔 워커를 주기적으로 부르는 스케줄러가 없어서(price_poll_worker 주석), 전체 배치만 두면
    앱이 도는 동안 교체·제외에서 신호가 하나도 쌓이지 않았다. 매번 처음부터 세는 방식이라 언제 불러도 같다."""
    repo = PreferenceRepo(conn)
    updated = 0
    observations = _observations(conn, user_id)
    for (who, slot, brand), obs in observations.items():
        net = obs["prefer"] - obs["avoid"]
        # 같으면 방향은 마지막 관측을 따르고 횟수는 0 — 문턱 아래라 되묻지 않는다.
        direction = "prefer" if net > 0 else "avoid" if net < 0 else obs["last"]
        if repo.set_inferred(user_id=who, dimension="brand", slot=slot, value=brand,
                             direction=direction, confidence=abs(net), evidence_event_ids=obs["events"]):
            updated += 1
    # 이번에 관측되지 않은 추론 행은 0 으로 내린다 — 근거가 기간(WINDOW_DAYS) 밖으로 나갔거나, 예전 규칙(빼기도
    # 세던 때)으로 쌓인 행이다. 지우지 않고 0 으로 두어 거절(dismissed) 이력은 남긴다.
    for row in repo.inferred_rows(user_id):
        if (row["user_id"], row["slot"], row["value"]) in observations or not row["confidence"]:
            continue
        if repo.set_inferred(user_id=row["user_id"], dimension=row["dimension"], slot=row["slot"], value=row["value"],
                             direction=row["direction"], confidence=0, evidence_event_ids=[]):
            updated += 1
    return {"updated_signals": updated}

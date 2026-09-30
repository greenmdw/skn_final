"""사용자 브랜드 선호·비선호 신호 배치 — docs/사용자_선호비선호_기록_설계.md §5 (파이프라인 B).

engine.feedback_event(item_replaced/item_removed)를 사용자·슬롯별로 모아, 같은 브랜드 전환이나
같은 브랜드 반복 제거가 있으면 identity.preference_signal에 신호를 쌓는다.

stage6_feedback.run_batch()(엔진 전체 가중치 재학습, 별도 승인 게이트)와는 범위가 다르다 — 이건
사용자 개인의 신호만 다루고, 추천 엔진의 전역 가중치는 건드리지 않는다.

멱등성: 매번 최근 WINDOW_DAYS 안의 이벤트를 다시 스캔하지만, 각 (user, slot, brand) 신호가
이미 갖고 있는 evidence_event_ids(PreferenceRepo.get_signal로 조회)와 대조해 **아직 반영 안 한
이벤트만** confidence_delta로 넘긴다 — 그래서 몇 번을 다시 돌려도 confidence가 실제 관측 이벤트
개수 이상으로 부풀지 않는다.

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


def _replaced_brand_pairs(conn) -> list[dict]:
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
          AND fe.payload ? 'from_variant_id' AND fe.payload ? 'to_variant_id'
          AND fe.occurred_at >= now() - (%s || ' days')::interval
        """,
        (WINDOW_DAYS,),
    ).fetchall()


def _removed_brands(conn) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(
        """
        SELECT fe.id AS event_id, fe.user_id, fe.payload->>'slot' AS slot, p.brand AS brand
        FROM engine.feedback_event fe
        JOIN catalog.product_variant v ON v.id = (fe.payload->>'removed_variant_id')::uuid
        JOIN catalog.product p ON p.id = v.product_id
        WHERE fe.event_type = 'item_removed'
          AND fe.user_id IS NOT NULL
          AND fe.payload ? 'removed_variant_id'
          AND fe.occurred_at >= now() - (%s || ' days')::interval
        """,
        (WINDOW_DAYS,),
    ).fetchall()


def _new_event_ids(repo: PreferenceRepo, *, user_id: UUID, slot: str, value: str,
                    event_ids: list[UUID]) -> list[UUID]:
    """이 신호가 이미 반영한 이벤트를 빼고, 이번에 새로 반영할 것만 돌려준다."""
    existing = repo.get_signal(user_id=user_id, dimension="brand", slot=slot, value=value)
    seen = set(existing["evidence_event_ids"]) if existing else set()
    return [e for e in event_ids if e not in seen]


def run(conn) -> dict:
    """배치 1회 실행. 반환값은 몇 건의 신호를 새로 갱신했는지(로그·테스트용) — 이미 반영된
    이벤트만 있었던 신호는 세지 않는다(멱등)."""
    repo = PreferenceRepo(conn)
    updated = 0

    replaced = _replaced_brand_pairs(conn)
    by_pair: dict[tuple[UUID, str, str, str], list[UUID]] = defaultdict(list)
    for row in replaced:
        if row["from_brand"] == row["to_brand"]:
            continue
        by_pair[(row["user_id"], row["slot"], row["from_brand"], row["to_brand"])].append(row["event_id"])

    for (user_id, slot, from_brand, to_brand), event_ids in by_pair.items():
        new_prefer = _new_event_ids(repo, user_id=user_id, slot=slot, value=to_brand, event_ids=event_ids)
        new_avoid = _new_event_ids(repo, user_id=user_id, slot=slot, value=from_brand, event_ids=event_ids)
        if new_prefer:
            repo.upsert_signal(user_id=user_id, dimension="brand", slot=slot, value=to_brand,
                               direction="prefer", source="inferred_swap",
                               confidence_delta=len(new_prefer), evidence_event_ids=new_prefer)
            updated += 1
        if new_avoid:
            repo.upsert_signal(user_id=user_id, dimension="brand", slot=slot, value=from_brand,
                               direction="avoid", source="inferred_swap",
                               confidence_delta=len(new_avoid), evidence_event_ids=new_avoid)
            updated += 1

    removed = _removed_brands(conn)
    by_removed: dict[tuple[UUID, str, str], list[UUID]] = defaultdict(list)
    for row in removed:
        by_removed[(row["user_id"], row["slot"], row["brand"])].append(row["event_id"])

    for (user_id, slot, brand), event_ids in by_removed.items():
        new_ids = _new_event_ids(repo, user_id=user_id, slot=slot, value=brand, event_ids=event_ids)
        if not new_ids:
            continue
        repo.upsert_signal(user_id=user_id, dimension="brand", slot=slot, value=brand,
                           direction="avoid", source="inferred_swap",
                           confidence_delta=len(new_ids), evidence_event_ids=new_ids)
        updated += 1

    return {"updated_signals": updated}

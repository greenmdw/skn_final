"""리스트(계획) 서비스 — 사이드바 목록 · S5-a 확정 · S5-b 리포트 · 가격 알림 (§D-4-3).

확정 = plan_revision draft → confirmed (이름·구매예정일·목표가·메모). 비로그인은 로그인 요구.
확정 시점에 선택된 후보를 planning.purchase_line에 얼려서 남긴다 — 이후 추천 결과가 어떻게
바뀌어도(현재는 확정된 revision에 재추천을 막아 그럴 일이 없지만) 리포트는 확정 순간 그대로
보여준다. price_watch 생성은 확정 트랜잭션 이후, 확정된 target_amount를 기본값으로 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.auth.deps import Principal
from src.errors import Conflict, NotFound, ValidationFailed
from src.repo.engine_repo import EngineRepo
from src.repo.notification_repo import NotificationRepo
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import UserRepo
from src.services import auth_service, feedback_service, recommendation_service
from src.services.session_service import _owned, _token_hash

_DEFAULT_NAME_BY_CATEGORY = {"computer": "컴퓨터 장바구니"}
_PLACEHOLDER_NAMES = {"새 추천", ""}
_PRICE_WATCH_WINDOW_DAYS = 90


def _display_name(name: str, category: str | None) -> str:
    if name not in _PLACEHOLDER_NAMES:
        return name
    return _DEFAULT_NAME_BY_CATEGORY.get(category or "", name)


def _stage(row: dict) -> str:
    if row["state"] == "confirmed":
        return "report"
    if row["has_result"]:
        return "results"
    if row["has_category"]:
        return "conditions"
    return "category"


def _require_login(conn, principal: Principal) -> UUID:
    """단순 user_id 유무만이 아니라 계정이 여전히 active인지까지 확인한다(§A-3).

    JWT 자체는 유효 기간 안이어도 그 사이 탈퇴·정지된 계정일 수 있어서, principal.user_id가
    채워져 있다는 사실만으로는 로그인 요구 엔드포인트(확정·리포트·알림)를 통과시킬 수 없다.
    """
    return auth_service.require_active_user(conn, principal)["id"]


def _price_watch_out(nrepo: NotificationRepo, watch: dict | None, fallback_target_amount) -> dict:
    if watch is None:
        return {
            "enabled": False, "target_amount": fallback_target_amount,
            "status": "waiting", "latest_total": None, "observed_at": None,
        }
    target = int(watch["target_amount"]) if watch["target_amount"] is not None else fallback_target_amount
    if watch["state"] != "active":
        return {"enabled": False, "target_amount": target, "status": "waiting", "latest_total": None, "observed_at": None}
    status = {"unknown": "waiting", "above": "tracking", "reached": "reached"}.get(
        watch["last_condition_state"], "waiting"
    )
    # ACC-02: 판정 이력(notification.price_watch_evaluation)이 이제 생기므로, 그중 최신 값을 보여준다
    # (전엔 이 테이블이 없어 항상 None 이었다 — db/migrations/0004_notification_events.sql).
    latest = nrepo.latest_evaluation(watch["id"])
    return {
        "enabled": True, "target_amount": target, "status": status,
        "latest_total": int(latest["amount"]) if latest and latest["amount"] is not None else None,
        "observed_at": latest["evaluated_at"].isoformat() if latest else None,
    }


def confirmed_revision(conn, list_id: UUID, principal: Principal, revision_no: int | None = None) -> dict:
    """로그인한 소유자의 확정된 견적서(revision) 하나. 목록 하나에 견적서가 여러 개일 수 있다(10번 ③):
    번호를 주면 그 견적서, 안 주면 현재 revision 이 확정이면 그것, 새 견적서를 작성 중이면 가장 최근 확정본."""
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    current = _owned(prepo, list_id, principal)
    if current["owner_user_id"] != user_id:
        raise NotFound("확정된 목록을 찾을 수 없습니다.")
    if revision_no is not None:
        revision = prepo.get_revision_by_no(list_id, revision_no)
    elif current["state"] == "confirmed":
        revision = current
    else:
        latest = prepo.confirmed_revisions(list_id)
        revision = prepo.get_revision(latest[-1]["id"]) if latest else None
    if revision is None or revision["state"] != "confirmed":
        raise NotFound("확정된 목록을 찾을 수 없습니다.")
    return revision


def new_revision(conn, list_id: UUID, principal: Principal, *, from_revision_no: int | None = None) -> dict:
    """확정한 견적을 바탕으로 새 견적서를 쓴다 — 조건과 추천 결과(부품 구성)를 복사한 새 draft revision
    (개발요청 8번, `PlanRepo.clone_revision`)을 현재로 삼는다.

    `from_revision_no`를 안 주면(기본) 지금까지처럼 "현재(current) 견적서"를 복사한다 — 이미
    작성 중인 draft가 현재면 그대로 돌려준다(두 번 눌러도 새 견적서는 하나).

    개발요청 14번 — `from_revision_no`를 주면(한 대화에 견적서가 여러 개일 때, 최신이 아닌
    예전 견적서를 고치고 싶은 경우) 그 번호의 확정 견적서를 원본으로 복사한다. 이미 작성 중인
    draft가 있어도 **버리고 새로 복사한다**(문서 권장 동작) — 명시적으로 다른 견적서를
    고쳐달라는 요청이라 기존 두 번 눌러도 하나(idempotent) 규칙보다 우선한다."""
    from src.repo.user_repo import ConversationRepo
    from src.services import session_service

    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    current = _owned(prepo, list_id, principal)
    if current["owner_user_id"] != user_id:
        raise NotFound("목록을 찾을 수 없습니다.")

    if from_revision_no is not None:
        source = _owned_confirmed_report(prepo, list_id, principal, from_revision_no, user_id)
        new_id = prepo.clone_revision(list_id, source["id"])
        prepo.set_current_revision(list_id, new_id)
        ConversationRepo(conn).add_message(
            current["conversation_id"], "assistant",
            f"견적서 {source['revision_no']}의 조건으로 새 견적서를 시작했어요. "
            "바꾸고 싶은 조건을 말씀하시거나 바로 추천을 받아 보세요.")
        return session_service._state(conn, list_id, principal)

    if current["state"] == "confirmed":
        new_id = prepo.clone_revision(list_id, current["id"])
        prepo.set_current_revision(list_id, new_id)
        ConversationRepo(conn).add_message(
            current["conversation_id"], "assistant",
            f"견적서 {current['revision_no']}의 조건으로 새 견적서를 시작했어요. "
            "바꾸고 싶은 조건을 말씀하시거나 바로 추천을 받아 보세요.")
    return session_service._state(conn, list_id, principal)


def _owned_confirmed_report(prepo: PlanRepo, list_id: UUID, principal: Principal, revision_no: int,
                            user_id: UUID) -> dict:
    current = _owned(prepo, list_id, principal)
    if current["owner_user_id"] != user_id:
        raise NotFound("목록을 찾을 수 없습니다.")
    target = prepo.get_revision_by_no(list_id, revision_no)
    if target is None or target["state"] != "confirmed":
        raise NotFound("견적서를 찾을 수 없습니다.")
    return target


def delete_report(conn, list_id: UUID, principal: Principal, revision_no: int) -> dict:
    """견적서(확정된 revision) 하나만 지운다(개발요청 10번) — 대화·다른 견적서는 그대로 둔다.

    지금 작업 중인(current) revision이 바로 지우는 그 견적서면(확정 직후 "새 견적서 시작"을
    아직 안 누른 상태) current를 다른 곳으로 옮겨야 한다 — 남은 확정 견적서가 있으면 가장
    최근 것으로, 하나도 안 남으면 지우는 견적서의 조건·구성을 그대로 들고 초안으로 되돌린다
    (`clone_revision`, 8번과 같은 메커니즘 — "새 견적서 시작"을 자동으로 누른 것과 같다)."""
    from src.services import session_service

    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    target = _owned_confirmed_report(prepo, list_id, principal, revision_no, user_id)
    current = prepo.get_current_revision(list_id)

    if current is not None and current["id"] == target["id"]:
        remaining = [r for r in prepo.confirmed_revisions(list_id) if r["id"] != target["id"]]
        if remaining:
            prepo.set_current_revision(list_id, remaining[-1]["id"])
        else:
            new_id = prepo.clone_revision(list_id, target["id"])
            prepo.set_current_revision(list_id, new_id)

    prepo.soft_delete_revision(target["id"])
    return session_service._state(conn, list_id, principal)


def rename_report(conn, list_id: UUID, principal: Principal, revision_no: int, name: str) -> dict:
    """견적서 하나의 이름만 바꾼다(개발요청 10번) — 대화 이름(`PATCH /lists/{id}`)과는 별개로,
    확정 때 저장된 `name_snapshot`을 바꾼다."""
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    target = _owned_confirmed_report(prepo, list_id, principal, revision_no, user_id)
    prepo.rename_revision(target["id"], name)
    return get_report(conn, list_id, principal, revision_no)


def _reports_out(rows: list[dict]) -> list[dict]:
    return [{
        "revision_no": r["revision_no"], "name": r["name_snapshot"], "confirmed_at": r["confirmed_at"],
        "total": int(r["confirmed_total"]), "item_count": int(r["item_count"]),
        "peripheral_count": int(r.get("peripheral_count") or 0),
        "planned_purchase_at": r["planned_purchase_at"].date().isoformat() if r["planned_purchase_at"] else None,
    } for r in rows]


def _conditions_summary(prepo: PlanRepo, revision_id: UUID, category: str | None) -> str:
    if not category:
        return ""
    from src.categories import load_category
    from src.services.session_service import _current_values
    values, _ = _current_values(prepo, revision_id)
    try:
        return recommendation_service._conditions_summary(load_category(category), values)
    except Exception:       # 카테고리 정의가 바뀌어 요약을 못 만들어도 목록은 보여 준다
        return ""


def list_conversations(conn, principal: Principal, *, limit: int | None = None, offset: int = 0) -> list[dict]:
    """사이드바 "내 장바구니" — 로그인 사용자 또는 guest 쿠키 소유분(§D-4-3).

    limit=None(기본)이면 전량 — 기존 호출부 동작을 그대로 유지한다."""
    guest_hash = _token_hash(principal.browser_token) if principal.browser_token else None
    prepo = PlanRepo(conn)
    rows = prepo.list_owned(user_id=principal.user_id, guest_session_hash=guest_hash,
                            limit=limit, offset=offset)
    out = []
    for row in rows:
        reports = _reports_out(prepo.confirmed_revisions(row["list_id"]))
        latest = reports[-1] if reports else None
        first = " ".join((row["first_message"] or "").split())
        out.append({
            "list_id": str(row["list_id"]),
            "name": _display_name(row["name"], row["category"]),
            "category": row["category"],
            "stage": _stage(row),
            "updated_at": row["updated_at"],
            "last_active_at": row["last_active_at"],
            "first_message": first[:60] or None,
            "conditions_summary": _conditions_summary(prepo, row["revision_id"], row["category"]),
            # 가장 최근 확정 견적서 기준(6번: 목록마다 리포트를 따로 부르지 않게)
            "total": latest["total"] if latest else None,
            "planned_purchase_at": latest["planned_purchase_at"] if latest else None,
            "item_count": latest["item_count"] if latest else None,
            "reports": reports,
        })
    return out


def rename(conn, list_id: UUID, principal: Principal, *, name: str) -> dict:
    prepo = PlanRepo(conn)
    _owned(prepo, list_id, principal)
    prepo.rename(list_id, name)
    row = prepo.get_summary(list_id)
    return {
        "list_id": str(row["list_id"]), "name": name, "category": row["category"],
        "stage": _stage(row), "updated_at": row["updated_at"],
    }


def delete(conn, list_id: UUID, principal: Principal) -> None:
    prepo = PlanRepo(conn)
    _owned(prepo, list_id, principal)
    prepo.soft_delete(list_id)


def confirm(conn, list_id: UUID, principal: Principal, *, name: str, planned_purchase_at: str | None,
            target_amount: int | None, memo: str, if_match: int | None = None,
            peripherals: list[dict] | None = None) -> dict:
    user_id = _require_login(conn, principal)
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    if revision["owner_user_id"] != user_id:
        raise NotFound("목록을 찾을 수 없습니다.")
    if revision["state"] == "confirmed":
        return get_report(conn, list_id, principal)
    if if_match is not None and if_match != revision["lock_version"]:
        raise Conflict("목록이 다른 곳에서 변경되었습니다.", code="stale_revision")

    stored = recommendation_service.get_stored_result(conn, revision["id"])
    # 본체 추천이 없고 주변기기만 담았다면 "주변기기만" 확정한다 — 본체 없이 주변기기 추천만 받은 목록.
    # 본체 추천이 있으면(진행 중·실패 포함) 예전과 똑같이 검증한다: 주변기기만 확정해 본체를 조용히 버리지 않는다.
    peripheral_only = bool(peripherals) and (stored is None or not stored["items"])
    if not peripheral_only:
        if stored is None or stored["status"] != "done" or not stored["items"]:
            raise ValidationFailed("추천 결과가 아직 없습니다. 먼저 추천을 완료해 주세요.", code="no_items_selected")
        # 결과 항목이 있어도 전부 선택 해제했다면 확정할 것이 없다(빈 리스트·0원 리포트가 만들어지던 결함).
        if not stored["totals"].get("selected_units"):
            raise ValidationFailed("선택한 품목이 없습니다. 하나 이상 선택한 뒤 확정해 주세요.", code="no_items_selected")
        if stored["totals"]["over_budget"]:
            raise ValidationFailed("선택한 구성이 예산을 초과합니다.", code="over_budget")
        run = EngineRepo(conn).get_run(UUID(stored["run_id"]))
        full = prepo.load_full(revision["id"])
        current_values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
        if (run or {}).get("input_snapshot", {}).get("values", {}) != current_values:
            raise Conflict("조건이 바뀌어 추천을 다시 받아야 합니다.", code="stale_recommendation")

    # 개발요청 11번 — 가격은 클라이언트가 보낸 값을 안 믿고 variant_id로 카탈로그에서 다시 조회한다
    # (PC 쪽 stored가 서버에서 다시 읽는 것과 같은 원칙). 확정 전에 다 검증해, 실패하면 아무것도 안 남긴다.
    peripheral_picks: list[tuple[str, object, int]] = []
    if peripherals:
        from src.repo.catalog_repo import load_peripheral_candidates
        pool = load_peripheral_candidates(conn)
        for p in peripherals:
            kind, variant_id, qty = p["kind"], p["variant_id"], int(p.get("qty", 1))
            cand = next((c for c in pool.get(kind, []) if c.variant_id == variant_id), None)
            if cand is None:
                raise ValidationFailed(f"주변기기 후보를 찾을 수 없습니다: {kind}", code="peripheral_not_found")
            peripheral_picks.append((kind, cand, qty))
    peripheral_total = sum(c.price * qty for _, c, qty in peripheral_picks)

    purchase_at = None
    if planned_purchase_at:
        try:
            purchase_at = datetime.fromisoformat(planned_purchase_at)
        except ValueError:
            raise ValidationFailed("구매 예정일 형식이 올바르지 않습니다.", field="planned_purchase_at") from None

    body_total = 0 if peripheral_only else stored["totals"]["selected_price"]
    ok = prepo.confirm_revision(
        revision["id"], confirmed_total=body_total + peripheral_total,
        planned_purchase_at=purchase_at, target_amount=target_amount, memo=memo, name=name,
    )
    if not ok:
        raise Conflict("이미 확정된 목록입니다.")
    prepo.rename(list_id, name)

    # stored["items"]가 이미 리뷰 배지를 계산해 뒀다 — 상품키로 다시 찾지 않고 item_id로 재사용해
    # 결과 화면과 확정 스냅샷의 리뷰 표시가 어긋나지 않게 한다.
    review_by_item_id = {} if peripheral_only else {item["item_id"]: item["review"] for item in stored["items"]}

    # 확정 성공(state가 draft→confirmed로 바뀐 요청)만 후보를 얼린다 — confirm_revision이
    # 이미 원자적 UPDATE라 동시 확정 요청 중 단 하나만 여기 도달한다. 주변기기만 확정하면 얼릴 본체 후보가 없다.
    for row in ([] if peripheral_only else EngineRepo(conn).get_candidates(UUID(stored["run_id"]))):
        if not row["selected"]:
            continue
        if row["offer_id"] is None or row["offer_observation_id"] is None or row["price"] is None:
            continue  # 가격 관측이 없는 슬롯 — 구매 항목으로 얼릴 수 없다
        item_view = next((i for i in stored["items"] if i["item_id"] == str(row["id"])), None)
        # 결과 화면에서 바꾼 수량·구매 시점을 그대로 얼린다 — 예전엔 1개·"now"로 고정해서, 수량을 바꾸면 리포트의
        # 부품 금액 합이 확정 총액(단가 × 수량의 합)과 어긋났다.
        qty = int(row["qty"] or 1)
        snapshot = {
            "slot": row["slot"], "slot_label": (item_view or {}).get("slot_label") or row["slot_label"],  # 결과 화면과 같은 언어
            "qty": qty, "timing": row["timing"] or "now",
            "review": review_by_item_id.get(str(row["id"])), "evidence_text": row["reason"] or "",
            "review_detail": (item_view or {}).get("review_detail"),
            "original_review_detail": (item_view or {}).get("original_review_detail"),
            "product": {
                "product_key": (item_view or {}).get("product", {}).get("product_key") or row["product_key"],
                "name": row["product_name"],
                "image_url": row["image_url"], "purchase_url": row["purchase_url"],
            },
        }
        prepo.add_purchase_line(
            revision["id"], row["offer_id"], row["offer_observation_id"], int(row["price"]) * qty, snapshot,
            pack_count=qty,
        )

    for kind, cand, qty in peripheral_picks:
        snapshot = {
            "kind": kind,
            "product": {
                "product_key": cand.product_key, "name": cand.name, "brand": cand.brand,
                "image_url": cand.provenance.get("image_url"), "purchase_url": cand.provenance.get("product_url"),
            },
        }
        prepo.add_peripheral_line(
            revision["id"], kind, UUID(cand.variant_id), int(cand.price) * qty, snapshot, pack_count=qty,
        )

    # P8 FB03: draft→confirmed 전환에 성공한 요청만 여기 도달한다(위의 Conflict가 이미
    # 중복 확정을 막는다) — 실패한 확정 시도는 아무 것도 남기지 않는다.
    if not peripheral_only:   # 추천 실행(run)이 없으면 추천 확정 피드백 이벤트도 없다
        feedback_service.emit_confirmed(
            conn, plan_id=revision["plan_id"], revision_id=revision["id"],
            run_id=UUID(stored["run_id"]), version=revision["lock_version"], user_id=user_id,
        )
    return get_report(conn, list_id, principal)


def get_report(conn, list_id: UUID, principal: Principal, revision_no: int | None = None) -> dict:
    prepo = PlanRepo(conn)
    revision = confirmed_revision(conn, list_id, principal, revision_no)

    owner = UserRepo(conn).get(revision["owner_user_id"])
    items = []
    for line in prepo.list_purchase_lines(revision["id"]):
        snapshot = line["snapshot"] or {}
        items.append({
            "slot": snapshot.get("slot"), "slot_label": snapshot.get("slot_label"),
            "product": snapshot.get("product") or {},
            # price 는 단가(화면이 × qty 한다). line_amount 는 줄 합계라 수량으로 나눈다 — 수량이 1 이던 예전 확정본은 그대로다.
            "price": int(line["line_amount"]) // max(int(line["pack_count"]), 1), "qty": int(line["pack_count"]),
            "timing": snapshot.get("timing", "now"), "review": snapshot.get("review"),
            "review_detail": snapshot.get("review_detail") or {"status": "unavailable", "reason": "snapshot_missing"},
            "original_review_detail": snapshot.get("original_review_detail"),
            "evidence_text": snapshot.get("evidence_text", "") or "",
        })
    peripherals = []
    for line in prepo.list_peripheral_lines(revision["id"]):
        snapshot = line["snapshot"] or {}
        peripherals.append({
            "kind": snapshot.get("kind") or line["kind"],
            "product": snapshot.get("product") or {},
            "price": int(line["line_amount"]) // max(int(line["pack_count"]), 1), "qty": int(line["pack_count"]),
        })
    watch = NotificationRepo(conn).get_for_revision(revision["id"])
    return {
        "list_id": str(list_id),
        "revision_no": revision["revision_no"],
        # A confirmed report is a snapshot; later sidebar renames must not rewrite
        # the name shown on that historical purchase record.
        "name": _display_name(revision["name_snapshot"], revision["category"]),
        "category": revision["category"],
        "owner_display_name": owner["display_name"] if owner else "",
        "planned_purchase_at": revision["planned_purchase_at"].date().isoformat()
        if revision["planned_purchase_at"] else None,
        "target_amount": int(revision["target_amount"]) if revision["target_amount"] is not None else None,
        "memo": revision["memo"] or "",
        "total": int(revision["confirmed_total"]),
        "confirmed_at": revision["confirmed_at"].isoformat(),
        "items": items,
        "peripherals": peripherals,
        "price_watch": _price_watch_out(
            NotificationRepo(conn), watch, int(revision["target_amount"]) if revision["target_amount"] is not None else None
        ),
        "data_notice": ("PC 상품·가격은 수집 파일 기반으로 실시간 정보가 아닙니다. 리뷰 요약은 합성 데이터입니다."
                        if revision["category"] == "computer" else "상품·가격·리뷰는 합성 데이터입니다."),
    }


def get_history(conn, list_id: UUID, principal: Principal,
                revision_no: int | None = None) -> tuple[dict, dict]:
    """견적 리스트 히스토리의 단계·사건 — 리포트와 같게 로그인한 소유자의 확정된 목록만.
    요약 문장(LLM)은 트랜잭션 밖에서 만든다(`list_history.render`) — 연결을 LLM 대기 동안 붙잡지 않는다."""
    from src.services import list_history

    revision = confirmed_revision(conn, list_id, principal, revision_no)
    return revision, list_history.build(conn, revision)


def set_alert(conn, list_id: UUID, principal: Principal, *, enabled: bool, target_amount: int | None) -> dict:
    revision = confirmed_revision(conn, list_id, principal)

    nrepo = NotificationRepo(conn)
    existing = nrepo.get_for_revision(revision["id"])
    confirmed_target = int(revision["target_amount"]) if revision["target_amount"] is not None else None

    if not enabled:
        if existing is not None and existing["state"] == "active":
            nrepo.pause(existing["id"])
            existing = nrepo.get_for_revision(revision["id"])
        return {"price_watch": _price_watch_out(nrepo, existing, confirmed_target)}

    # target_amount 미지정 시 기존 watch에 이미 설정된 값 → 확정 스냅샷 목표가 순으로 fallback.
    amount = target_amount
    if amount is None and existing is not None:
        amount = existing["target_amount"]
    if amount is None:
        amount = revision["target_amount"]
    if amount is None:
        raise ValidationFailed("목표 금액을 입력해 주세요.", field="target_amount")
    ends_at = datetime.now(timezone.utc) + timedelta(days=_PRICE_WATCH_WINDOW_DAYS)
    watch = nrepo.upsert_active(revision["id"], target_amount=amount, ends_at=ends_at)
    return {"price_watch": _price_watch_out(nrepo, watch, confirmed_target)}

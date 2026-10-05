"""PC 견적 점검 — 타사 견적을 매칭하고 호환 검사한 결과를 세션에 저장한다 (CHK-04·CHK-09).

호환 검사는 추천엔진 7단계와 **같은 함수**(stage4_optimize.pc_compat_details / pc_link_check)를 부른다 —
검사 규칙을 여기서 다시 짜지 않는다. 이 모듈이 하는 일은 사용자가 적은 견적(current_specs)을 그 함수가 읽는
입력({슬롯: Candidate}, RequirementSpec)으로 바꿔 주는 것뿐이다. 카탈로그에 대응된 부품은 그 제품의 스펙을,
아니면 글에서 읽은 값(소켓·DDR·파워 용량)만 쓴다 — 모르는 값은 "확인 못 함"이고 비호환이 아니다.

결과는 리비전의 조건 `quote_review` 로 저장한다(plan_repo.QUOTE_REVIEW_KEY): 스키마 변경 없이 세션 단위로
남고, 추천 입력에는 섞이지 않으며 lock_version 도 올리지 않는다. 되묻기 채팅(CHAT-04)이 이 값을 근거로 읽는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from src.auth.deps import Principal
from src.categories import load_category
from src.dto import Candidate, RequirementSpec
from src.engine.owned_parts import preview_current_specs, resolve_owned_parts
from src.engine.compat_parse import parse_module_count
from src.engine.quote_price import compare_price, line_quantity, parse_price
from src.engine.stage2_requirement import load_computer_rules, normalize_pc_slot
from src.engine.stage3_0_candidates import load_pc_catalog
from src.engine.stage4_optimize import pc_compat_details, pc_link_check
from src.errors import NotFound, ServiceUnavailable, ValidationFailed
from src.repo.plan_repo import QUOTE_REVIEW_KEY, PlanRepo
from src.services import quote_balance, quote_compare, session_service

REVIEW_LIST_NAME = "받은 견적 점검"
SCHEMA_VERSION = 1
# pc_compat_details 의 skipped 문구는 "추천에서 안 바뀌는 부품" 기준이라 견적 점검에는 맞지 않는다.
_SKIPPED_DETAIL = "견적에 이 검사에 필요한 부품이 없어 확인하지 않았습니다."


def _normalise(current_specs: dict) -> dict[str, str]:
    """슬롯 이름을 정규화하고 빈 값은 뺀다 — 같은 견적이면 같은 해시가 나오게 한다."""
    out: dict[str, str] = {}
    for key, value in (current_specs or {}).items():
        text = str(value or "").strip()
        if text:
            out[normalize_pc_slot(key) or str(key).strip()] = text
    return out


def normalise_conditions(conditions: dict | None) -> dict:
    """용도·해상도·게임·예산만 남기고 빈 값은 뺀다. 조건이 없으면 {} — 용도 대비 균형은 판단하지 않는다."""
    out: dict = {}
    for key in ("purpose", "resolution", "priority", "budget_max"):
        value = (conditions or {}).get(key)
        if value not in (None, "", 0):
            out[key] = value
    games = [str(g).strip() for g in ((conditions or {}).get("games") or []) if str(g).strip()]
    if games:
        out["games"] = games
    return out


def _input_hash(specs: dict[str, str], conditions: dict) -> str:
    payload = {"specs": specs, "conditions": conditions}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _summary(checks: list[dict]) -> dict[str, int]:
    counts = {"ok": 0, "fail": 0, "unknown": 0, "skipped": 0}
    for row in checks:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return counts


def compat_for_quote(specs: dict[str, str], by_slot: dict[str, list[Candidate]], slot_structure: list[str],
                     owned: dict[str, dict] | None = None) -> dict:
    """견적에 적힌 부품들끼리의 호환 검사(CHK-04). DB·세션 없이 도는 순수 계산."""
    owned = owned if owned is not None else resolve_owned_parts(specs, by_slot, slot_structure)
    chosen = {
        slot: Candidate(product_key=f"quote:{slot}", slot=slot, name=info["name"], specs=dict(info.get("specs") or {}))
        for slot, info in owned.items()
    }
    spec = RequirementSpec(list_id="quote-review", category="computer", mode="build")
    rules = load_computer_rules()["verification"]
    checks = []
    for row in pc_compat_details(chosen, spec, rules):
        row = dict(row)
        if row["state"] == "skipped" and "바뀌는 부품이 아니라" in row["detail"]:
            row["detail"] = _SKIPPED_DETAIL
        checks.append({"axis": row["axis"], "label": row["label"], "state": row["state"], "detail": row["detail"]})
    link_check = pc_link_check(chosen, spec, rules)
    return {
        "checks": checks,
        "summary": _summary(checks),
        # 확정된 비호환(소켓·메모리·크기·전력 …)만 — "모름"은 들어가지 않는다.
        "incompatible": [c["axis"] for c in checks if c["state"] == "fail"],
        "link_check": link_check,
    }


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _price_row(slot: str, text: str, info: dict) -> dict:
    """부품 하나의 가격 비교 행. 같은 제품으로 확정된(카탈로그 대응) 부품만 비교하고, 아니면 이유를 적는다."""
    quoted = parse_price(text)
    source = info.get("source")
    catalog = info.get("catalog_price") if source == "catalog" else None
    # 카탈로그 가격은 상품 1개 기준이다 — 견적이 "16GB x2"·"2개"로 여러 개를 한 줄에 적었으면 같은 개수로 맞춰 견준다.
    # RAM 은 카탈로그 상품이 패키지("16GB × 2")일 수 있어 그 구성 수로 나눈 만큼만 곱한다.
    quantity = line_quantity(text)
    per_product = (parse_module_count((info.get("specs") or {}).get("module_config")) or 1) if slot == "RAM" else 1
    multiplier = quantity / per_product
    if catalog is not None and multiplier != 1:
        catalog = round(catalog * multiplier)
    row = {"part": slot, "matched": info.get("name") if source == "catalog" else None, "quoted": quoted,
           "catalog": catalog, "quantity": quantity}
    result = compare_price(quoted, catalog)
    row.update(result)
    if result["state"] == "no_quote_price":
        row["detail"] = "견적에 이 부품의 가격이 적혀 있지 않아 비교하지 않았습니다."
    elif result["state"] == "no_catalog":
        if source == "candidate":
            row["detail"] = f"카탈로그의 '{info.get('candidate')}'와 비슷하지만 같은 제품인지 확인되지 않아 비교하지 않았습니다."
        elif source == "catalog":
            row["detail"] = "용량·구성 변형이 카탈로그와 달라 어느 가격과 비교할지 정할 수 없습니다."
        else:
            row["detail"] = "카탈로그에서 같은 제품을 찾지 못해 비교하지 못했습니다."
    else:
        basis = f" ({quantity}개 기준)" if multiplier != 1 else ""
        row["detail"] = (f"견적 {_won(quoted)} · 카탈로그 {_won(catalog)}{basis} "
                         f"({result['diff']:+,}원, {result['diff_pct']:+.1f}%)")
    return row


def price_review(specs: dict[str, str], owned: dict[str, dict], slot_structure: list[str]) -> dict:
    """견적 가격 대 우리 카탈로그 가격(CHK-05). 견적에 가격이 하나도 없으면 비교하지 않는다(P10)."""
    quoted = {slot: parse_price(specs[slot]) for slot in slot_structure if specs.get(slot)}
    if not any(price is not None for price in quoted.values()):
        return {"available": False, "reason": "견적에 가격이 적혀 있지 않아 가격 비교를 하지 않았습니다.",
                "rows": [], "summary": {}}
    rows = [_price_row(slot, specs[slot], owned.get(slot, {})) for slot in quoted]
    compared = [r for r in rows if r["state"] in ("cheaper", "similar", "pricier")]
    quoted_sum = sum(r["quoted"] for r in compared)
    catalog_sum = sum(r["catalog"] for r in compared)
    summary = {
        "compared": len(compared), "pricier": sum(r["state"] == "pricier" for r in compared),
        "cheaper": sum(r["state"] == "cheaper" for r in compared), "similar": sum(r["state"] == "similar" for r in compared),
        "not_compared": len(rows) - len(compared),
        # 비교한 부품만의 합계 — 가격이 없거나 카탈로그에 없는 부품은 양쪽 합계에서 함께 빠져 서로 공정하다.
        "quoted_total": quoted_sum, "catalog_total": catalog_sum, "diff": quoted_sum - catalog_sum,
        "diff_pct": round((quoted_sum - catalog_sum) / catalog_sum * 100, 1) if catalog_sum else None,
        "quote_total_complete": all(price is not None for price in quoted.values()),
    }
    return {"available": True, "reason": None, "rows": rows, "summary": summary}


def analyze(current_specs: dict, conditions: dict | None = None, *,
            by_slot: dict[str, list[Candidate]] | None = None, conn=None) -> dict:
    """견적 하나를 분석한 결과(저장 형태): 매칭 표 · 호환 검사 · 가격 비교 · 용도 대비 균형 · 우리 추천과 비교."""
    specs = _normalise(current_specs)
    if not specs:
        raise ValidationFailed("분석할 부품이 없습니다. 견적을 붙여 넣거나 부품을 하나 이상 적어 주세요.", field="current_specs")
    by_slot = by_slot if by_slot is not None else load_pc_catalog(lambda _msg: None)
    slot_structure = load_category("computer")["slot_structure"]
    owned = resolve_owned_parts(specs, by_slot, slot_structure)
    if conn is not None:
        # 사용자가 "실시간으로 찾아볼까요?"로 이미 받아 둔 값만 읽어 쓴다 — 새로 검색하지 않는다(자동 실행 금지).
        from src.services.live_spec_lookup import cached_for_kept_parts
        cached_for_kept_parts(conn, owned, specs)
    conditions = normalise_conditions(conditions)
    prices = price_review(specs, owned, slot_structure)
    return {
        "version": SCHEMA_VERSION,
        "input": {"current_specs": specs, "conditions": conditions, "input_hash": _input_hash(specs, conditions)},
        "parts": preview_current_specs(specs, by_slot, slot_structure),
        "compat": compat_for_quote(specs, by_slot, slot_structure, owned),
        "prices": prices,
        "balance": quote_balance.assess(conditions, owned, prices),
        "compare": quote_compare.assess(conditions, owned, prices, by_slot, slot_structure),
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _save(repo: PlanRepo, revision_id: UUID, review: dict) -> None:
    # 분석 결과는 추천 입력이 아니다 — lock_version 을 올리지 않는다(끝난 추천을 stale 로 만들지 않는다).
    repo.upsert_condition(revision_id, QUOTE_REVIEW_KEY, {"value": review}, "extracted", bump_version=False)


def create_review(conn, principal: Principal, current_specs: dict, conditions: dict | None = None) -> tuple[dict, dict]:
    """새 세션을 만들고 그 안에 분석 결과를 저장한다. (세션 정보, 저장된 결과)."""
    review = analyze(current_specs, conditions, conn=conn)          # 분석이 실패하면 빈 세션을 만들지 않는다
    session = session_service.create_session(conn, principal)
    repo = PlanRepo(conn)
    list_id = UUID(session["list_id"])
    repo.rename(list_id, REVIEW_LIST_NAME)
    revision = repo.get_current_revision(list_id)
    _save(repo, revision["id"], review)
    return session, review


def update_review(conn, list_id: UUID, principal: Principal, current_specs: dict,
                  conditions: dict | None = None) -> dict:
    """사용자가 인식 결과를 고쳤을 때 — 같은 세션의 분석을 새로 계산해 덮는다(이전 결과는 superseded 로 남는다).

    conditions 를 안 보내면(None) 이전에 저장한 조건을 그대로 쓴다 — 견적 표만 고칠 때 조건이 사라지지 않게. 조건을
    지우려면 빈 값({})을 보낸다."""
    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    if conditions is None:
        previous = repo.active_condition(revision["id"], QUOTE_REVIEW_KEY)
        conditions = (((previous or {}).get("value") or {}).get("value") or {}).get("input", {}).get("conditions")
    review = analyze(current_specs, conditions, conn=conn)
    _save(repo, revision["id"], review)
    return review


def get_review(conn, list_id: UUID, principal: Principal) -> dict:
    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    row = repo.active_condition(revision["id"], QUOTE_REVIEW_KEY)
    if row is None:
        raise NotFound("이 목록에는 견적 점검 결과가 없습니다.")
    return row["value"]["value"]


# 카탈로그에서 확실히 찾지 못한 상태 — 대응 없음, 글에서 추정(inferred), 가장 비슷한 제품으로 대신 본 것(candidate).
# 추정·비슷한 제품은 점검이 그 값으로 이미 판단하고 있어 틀릴 수 있으니, 사용자가 정확한 값을 직접 확인해 볼 수 있게 연다.
LIVE_LOOKUP_STATUSES = ("unmatched", "inferred", "candidate")


def live_lookup_part(conn, list_id: UUID, principal: Principal, slot: str) -> dict:
    """저장된 견적 점검에서 "대응 안 됨"인 슬롯 하나를 실시간 검색+검증한다(개발요청 — 사용자가
    버튼을 눌렀을 때만, docs/미보유부품_실시간스펙검색_설계.md §2·§5). 저장하지 않는다 —
    같은 질의는 live_spec_lookup의 캐시(§4)가 재검색을 막아 주므로 다시 눌러도 비용이 없다."""
    from src.services import live_spec_lookup

    if not live_spec_lookup.available():
        raise ServiceUnavailable("지금은 실시간 검색을 쓸 수 없습니다.", code="live_part_lookup_unavailable")
    review = get_review(conn, list_id, principal)
    row = next((p for p in review.get("parts", []) if p["part"] == slot), None)
    if row is None:
        raise NotFound(f"그 슬롯을 찾을 수 없습니다: {slot}", field="slot")
    if row["match_status"] not in LIVE_LOOKUP_STATUSES:
        raise ValidationFailed("카탈로그에 이미 대응된 부품은 실시간 검색 대상이 아닙니다.", field="slot",
                               code="already_matched")
    outcome = live_spec_lookup.lookup_with_meta(conn, row["original"], slot=slot)
    iso = lambda dt: dt.isoformat(timespec="seconds") if dt else None          # noqa: E731
    return {"slot": slot, "query": row["original"], **outcome.result.model_dump(),
            "fetched_at": iso(outcome.fetched_at), "status": outcome.status, "cached": outcome.cached,
            "reference_price": outcome.reference_price,
            "reference_price_source_url": outcome.reference_price_source_url,
            "reference_price_at": iso(outcome.reference_price_at)}


def compare_part(conn, list_id: UUID, principal: Principal, slot: str, targets: list[str] | None = None,
                 direction: str | None = None) -> dict:
    """저장된 견적 점검의 부품 하나를 같은 부품군의 다른 제품과 나란히(CHK-10) — 저장하지 않고 그때그때 계산한다."""
    from src.services import quote_alternatives
    from src.engine.stage3_0_candidates import load_pc_catalog

    review = get_review(conn, list_id, principal)
    result = quote_alternatives.compare_parts(review, slot, load_pc_catalog(lambda _msg: None), targets or None, direction)
    if result.get("error"):
        raise ValidationFailed(result["error"], field="slot")
    return result

"""받은 견적 점검 — 여러 장 업로드 초안 (백엔드 개발요청서 BE-01~04·07·08, P0).

흐름: 이미지(최대 `QUOTE_DRAFT_MAX_FILES`장)·텍스트 → 파일별 인식 → 항목(item)으로 보존 → 항목 일괄 수정과 부품군별
분석 기준 선택 → 선택한 구성만 기존 점검(`quote_review_service.analyze`)에 넣는다. 점검 규칙은 새로 짜지 않는다.

- 초안은 세션(list)의 조건 `quote_review_draft`로 저장한다(스키마 변경 없음, 추천 입력이 아니라 lock_version을 올리지 않는다).
  `draft_id`는 세션의 `list_id`와 같다 — 분석이 같은 세션에 `quote_review`를 저장하고 `list_id`로 읽는다.
- 이미지 원본·base64는 저장하지 않는다. 파일명·순서·처리 상태·오류 코드만 남긴다.
- 파일 하나가 실패해도 성공한 파일의 항목은 유지한다(부분 성공). 같은 카탈로그 제품으로 확정된 항목만 합치고, 같은
  부품군의 다른 모델은 모두 항목으로 남긴다.
- match_status 는 기존 값(confirmed·ambiguous·candidate·inferred·unmatched)을 그대로 쓴다 — 화면과 실시간 검색 정책이
  이미 이 값에 기대고 있다(요청서의 exact·candidates 이름은 쓰지 않는다)."""
from __future__ import annotations

import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.agent import spec_extraction_agent
from src.auth.deps import Principal
from src.config import QUOTE_DRAFT_MAX_FILES, QUOTE_DRAFT_MAX_FILE_BYTES, QUOTE_DRAFT_MAX_TOTAL_BYTES
from src.engine.owned_parts import preview_current_specs, resolve_owned_parts
from src.engine.quote_items import default_selection, is_placeholder_line, merge_same_products, spec_text, split_line
from src.engine.spec_text import parse_spec_lines
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import Conflict, NotFound, ServiceUnavailable, TruefitError, ValidationFailed
from src.repo.plan_repo import QUOTE_DRAFT_KEY, PlanRepo
from src.services import quote_review_service, session_service

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
SUPPORTED_TYPES = ("image/png", "image/jpeg", "image/webp")
TEXT_MAX_CHARS = 20_000
_EXTRACT_WORKERS = 3
_SLOTS = ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러")


class NoRecognizedItems(TruefitError):
    code, http_status = "NO_RECOGNIZED_ITEMS", 400


class SourceTooLarge(TruefitError):
    code, http_status = "SOURCE_TOO_LARGE", 413


class TooManySources(TruefitError):
    code, http_status = "TOO_MANY_SOURCES", 422


class StaleReviewVersion(Conflict):
    code = "STALE_REVIEW_VERSION"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── BE-01 ────────────────────────────────────────────────────────────────────
def capabilities() -> dict:
    return {
        "image_extraction": bool(spec_extraction_agent.available()),
        "supported_types": list(SUPPORTED_TYPES),
        "max_files": QUOTE_DRAFT_MAX_FILES,
        "max_file_bytes": QUOTE_DRAFT_MAX_FILE_BYTES,
        "max_total_bytes": QUOTE_DRAFT_MAX_TOTAL_BYTES,
        "text_max_chars": TEXT_MAX_CHARS,
    }


# ── 입력 검증 ────────────────────────────────────────────────────────────────
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def _sniff(data: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_files(files: list[tuple[str, str | None, bytes]]) -> None:
    """개수·용량·형식. 형식은 선언된 content-type 과 실제 바이트(매직 넘버)가 모두 허용 형식이어야 한다."""
    if len(files) > QUOTE_DRAFT_MAX_FILES:
        raise TooManySources(f"이미지는 한 번에 {QUOTE_DRAFT_MAX_FILES}장까지 올릴 수 있습니다.", field="images")
    total = 0
    for name, content_type, data in files:
        total += len(data)
        if len(data) > QUOTE_DRAFT_MAX_FILE_BYTES:
            raise SourceTooLarge(f"파일 하나는 {QUOTE_DRAFT_MAX_FILE_BYTES // (1024 * 1024)}MB 이하여야 합니다: {name}", field="images")
        if (content_type or "").lower() not in SUPPORTED_TYPES or _sniff(data) not in SUPPORTED_TYPES:
            raise ValidationFailed(f"PNG·JPEG·WebP 이미지만 지원합니다: {name}", field="images")
    if total > QUOTE_DRAFT_MAX_TOTAL_BYTES:
        raise SourceTooLarge(f"전체 용량은 {QUOTE_DRAFT_MAX_TOTAL_BYTES // (1024 * 1024)}MB 이하여야 합니다.", field="images")


# ── 인식 ─────────────────────────────────────────────────────────────────────
def _data_url(content_type: str, data: bytes) -> str:
    import base64
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


def _extract_one(content_type: str, data: bytes) -> list[dict[str, str]]:
    return spec_extraction_agent.extract_items_from_image(_data_url(content_type, data))


def _text_items(text: str) -> list[dict[str, str]]:
    """텍스트 → 적힌 제품 전부(같은 부품군의 다른 제품도 따로). LLM 추출이 없거나 실패하면 "슬롯: 제품" 줄을 규칙으로 읽는다."""
    items: list[dict[str, str]] = []
    if spec_extraction_agent.available():
        try:
            items = spec_extraction_agent.extract_items(text)
        except Exception as exc:  # noqa: BLE001 — 모델·네트워크 오류는 규칙 파서로 이번 요청만 처리
            log.warning("quote draft: text extraction failed, using rules: %s", exc)
    if not items:
        items = [{"category": slot, "raw_text": value} for slot, value in parse_spec_lines(text)]
    return [i for i in items if i["category"] in _SLOTS and i["raw_text"].strip()]


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def _image_urls(conn, product_ids: list[str]) -> dict[str, str | None]:
    product_ids = [i for i in product_ids if _is_uuid(i)]          # 합성(mock) 카탈로그는 UUID가 아닌 ID를 쓴다
    if not product_ids:
        return {}
    from src.db.base import Repo
    rows = Repo(conn)._all("SELECT id::text AS id, image_url FROM catalog.product WHERE id = ANY(%s::uuid[])", (product_ids,))
    return {r["id"]: r["image_url"] for r in rows}


def _match(category: str, text: str, by_slot: dict) -> dict[str, Any]:
    """항목 하나를 카탈로그와 맞춘다 — 점검과 같은 함수(resolve_owned_parts·preview_current_specs). 확정된 경우에만 제품 ID."""
    row = preview_current_specs({category: text}, by_slot, [category])[0]
    info = resolve_owned_parts({category: text}, by_slot, [category])[category]
    status = row["match_status"]
    product_id = product_key = matched_name = None
    if status == "confirmed" and info.get("source") == "catalog":
        pool = {c.name: c for c in by_slot.get(category, [])}
        cand = pool.get(info["name"])
        product_id = cand.product_id if cand else None
        product_key = cand.product_key if cand else None
        matched_name = info["name"]
    elif status == "candidate":
        matched_name = info.get("candidate")
    return {"match_status": status, "candidate_count": row.get("candidate_count"),
            "matched_product_id": product_id, "matched_product_key": product_key, "matched_name": matched_name}


def _make_item(category: str, raw_text: str, source_id: str, by_slot: dict) -> dict[str, Any]:
    parts = split_line(raw_text)
    item = {"id": str(uuid.uuid4()), "category": category, "raw_text": raw_text, **parts,
            "image_url": None, "source_ids": [source_id], "selected_for_analysis": False, "user_edited": False}
    item.update(_match(category, spec_text(item), by_slot))
    return item


def recognize(files: list[tuple[str, str | None, bytes]], text: str | None, by_slot: dict) -> tuple[list[dict], list[dict]]:
    """(sources, items). 파일별 결과를 따로 거둔다 — 하나가 실패해도 나머지는 유지."""
    sources: list[dict] = []
    jobs: list[tuple[int, str, bytes]] = []
    for order, (name, content_type, data) in enumerate(files, start=1):
        sources.append({"id": f"source-{order}", "type": "image", "file_name": name, "sort_order": order,
                        "status": "completed", "error_code": None})
        jobs.append((order - 1, content_type or "image/png", data))
    raw_by_source: dict[int, list[dict]] = {}
    if jobs:
        if not spec_extraction_agent.available():
            raise ServiceUnavailable("지금은 이미지 인식을 쓸 수 없습니다.", code="IMAGE_EXTRACTION_UNAVAILABLE")

        def run(job):
            index, content_type, data = job
            try:
                return index, _extract_one(content_type, data), None
            except Exception as exc:  # noqa: BLE001 — 파일 하나의 실패. 나머지는 그대로 진행한다.
                log.warning("quote draft: image %s extraction failed: %s", index + 1, exc)
                return index, [], "IMAGE_EXTRACTION_FAILED"

        with ThreadPoolExecutor(max_workers=min(_EXTRACT_WORKERS, len(jobs))) as pool:
            for index, found, error in pool.map(run, jobs):
                raw_by_source[index] = found
                if error:
                    sources[index].update(status="failed", error_code=error)
    items: list[dict] = []
    for index, found in raw_by_source.items():
        for entry in found:
            if is_placeholder_line(entry["raw_text"]):      # "별도구매"·"기본 쿨러 장착" 같은 선택 안내 줄은 부품이 아니다
                continue
            items.append(_make_item(entry["category"], entry["raw_text"], sources[index]["id"], by_slot))
    if text and text.strip():
        sources.append({"id": "source-text", "type": "text", "file_name": None, "sort_order": len(sources) + 1,
                        "status": "completed", "error_code": None})
        for entry in _text_items(text):
            if is_placeholder_line(entry["raw_text"]):
                continue
            items.append(_make_item(entry["category"], entry["raw_text"], "source-text", by_slot))
    if jobs and all(s["status"] == "failed" for s in sources if s["type"] == "image") and not items:
        raise ServiceUnavailable("이미지 인식에 실패했습니다. 잠시 후 다시 시도해 주세요.", code="IMAGE_EXTRACTION_FAILED")
    if not items:
        raise NoRecognizedItems("인식된 제품이 없습니다. 견적이 잘 보이는 이미지나 텍스트를 올려 주세요.")
    return sources, merge_same_products(items)


def _attach_image_urls(conn, items: list[dict]) -> None:
    urls = _image_urls(conn, sorted({i["matched_product_id"] for i in items if i.get("matched_product_id")}))
    for item in items:
        item["image_url"] = urls.get(item["matched_product_id"]) if item.get("matched_product_id") else None


def _repair_selection(draft: dict) -> None:
    """항목을 지우거나 부품군을 바꾼 뒤 — 사라졌거나 다른 부품군이 된 항목을 가리키는 기준 선택은 버리고, 기준이 없어진
    부품군은 그 부품군의 첫 항목으로 채운다(없으면 그 부품군은 선택 없음)."""
    by_id = {i["id"]: i for i in draft["items"]}
    kept = {c: iid for c, iid in draft["selected_item_by_category"].items() if iid in by_id and by_id[iid]["category"] == c}
    for category, item_id in default_selection(draft["items"]).items():
        kept.setdefault(category, item_id)
    draft["selected_item_by_category"] = kept


def _apply_selection(draft: dict) -> None:
    selected = set(draft["selected_item_by_category"].values())
    for item in draft["items"]:
        item["selected_for_analysis"] = item["id"] in selected


# ── 저장·조회 ────────────────────────────────────────────────────────────────
def _revision_and_draft(conn, list_id: UUID, principal: Principal, *, lock: bool = False):
    repo = PlanRepo(conn)
    revision = session_service._owned(repo, list_id, principal)
    if lock:
        repo.lock_revision(revision["id"])
    row = repo.active_condition(revision["id"], QUOTE_DRAFT_KEY)
    if row is None:
        raise NotFound("이 목록에는 견적 초안이 없습니다.")
    return repo, revision, row["value"]["value"]


def _save(repo: PlanRepo, revision_id: UUID, draft: dict) -> None:
    repo.upsert_condition(revision_id, QUOTE_DRAFT_KEY, {"value": draft}, "extracted", bump_version=False)


def create_draft(conn, principal: Principal, files: list[tuple[str, str | None, bytes]], text: str | None,
                 question: str | None, conditions: dict | None) -> tuple[dict, dict]:
    """초안을 만들어 새 세션에 저장한다. (세션 정보, 초안). 인식이 실패하면 빈 세션을 만들지 않는다."""
    if text and len(text) > TEXT_MAX_CHARS:
        raise ValidationFailed(f"텍스트가 너무 깁니다({TEXT_MAX_CHARS:,}자 이하로 줄여주세요).", field="text")
    if not files and not (text and text.strip()):
        raise ValidationFailed("이미지나 텍스트를 하나 이상 올려 주세요.", field="images")
    validate_files(files)
    by_slot = load_pc_catalog(lambda _msg: None)
    sources, items = recognize(files, text, by_slot)
    _attach_image_urls(conn, items)
    draft = {
        "schema": SCHEMA_VERSION, "version": 1, "sources": sources, "items": items,
        "selected_item_by_category": default_selection(items),
        "conditions": quote_review_service.normalise_conditions(conditions), "question": (question or "").strip() or None,
        "partial_success": any(s["status"] == "failed" for s in sources), "created_at": _now(),
    }
    _apply_selection(draft)
    session = session_service.create_session(conn, principal)
    repo = PlanRepo(conn)
    list_id = UUID(session["list_id"])
    repo.rename(list_id, quote_review_service.REVIEW_LIST_NAME)
    revision = repo.get_current_revision(list_id)
    _save(repo, revision["id"], draft)
    return session, draft


def get_draft(conn, list_id: UUID, principal: Principal) -> dict:
    return _revision_and_draft(conn, list_id, principal)[2]


def groups(draft: dict) -> list[dict]:
    """견적 묶음 — 올린 이미지(또는 텍스트) 하나가 견적 하나다. 서로 다른 견적(A안·B안)을 올렸을 때 묶음별로 분석·비교하는 단위.
    항목이 두 견적에 모두 있으면(같은 제품으로 합쳐진 경우) 두 묶음에 모두 들어간다. 저장하지 않고 항상 항목에서 계산한다."""
    out = []
    for source in draft["sources"]:
        if source["type"] not in ("image", "text") or source["status"] != "completed":
            continue
        name = source["file_name"].rsplit(".", 1)[0] if source.get("file_name") else "붙여넣은 텍스트"
        out.append({"id": source["id"], "name": name, "source_ids": [source["id"]],
                    "item_ids": [i["id"] for i in draft["items"] if source["id"] in i["source_ids"]]})
    return out


def mark_live_values(conn, draft: dict) -> dict:
    """항목마다 "실시간 검색 값이 저장소에 있다"를 표시한다 — 응답을 만들 때만 읽어 채우고 저장하지 않는다.
    카탈로그와 확정 대응된 항목은 검색 값을 쓰지 않으므로 표시하지 않는다."""
    from src.services import live_spec_lookup

    for item in draft["items"]:
        item["live_value"] = item["match_status"] != "confirmed" and live_spec_lookup.has_stored_value(
            conn, item["normalized_name"], item["category"])
    return draft


def draft_out(list_id: str, draft: dict) -> dict:
    return {"draft_id": list_id, **draft, "groups": groups(draft)}


def items_for_sources(draft: dict, source_ids: list[str]) -> list[dict]:
    """주어진 견적(들)에 속한 항목에서 부품군마다 하나 — 분석 기준으로 고른 항목이 그 견적에 있으면 그것, 없으면 첫 항목."""
    known = {s["id"] for s in draft["sources"]}
    unknown = [s for s in source_ids if s not in known]
    if unknown or not source_ids:
        raise ValidationFailed(f"없는 견적입니다: {', '.join(unknown) or '(비어 있음)'}", field="source_ids")
    wanted, selected = set(source_ids), set(draft["selected_item_by_category"].values())
    chosen = []
    for category in _SLOTS:
        candidates = [i for i in draft["items"] if i["category"] == category and wanted & set(i["source_ids"])]
        if candidates:
            chosen.append(next((i for i in candidates if i["id"] in selected), candidates[0]))
    return chosen


# ── BE-04 ────────────────────────────────────────────────────────────────────
def patch_items(conn, list_id: UUID, principal: Principal, expected_version: int, edits: list[dict],
                selected: dict[str, str] | None) -> dict:
    """항목 일괄 수정 + 분석 기준 선택 — 요청 전체가 한 트랜잭션. 이름이 바뀐 항목만 다시 맞춘다. 전체 분석은 돌리지 않는다."""
    repo, revision, draft = _revision_and_draft(conn, list_id, principal, lock=True)
    if draft["version"] != expected_version:
        raise StaleReviewVersion("초안이 다른 곳에서 바뀌었습니다. 새로 불러온 뒤 다시 시도해 주세요.", field="expected_version")
    by_id = {item["id"]: item for item in draft["items"]}
    by_slot = None
    deleted: set[str] = set()
    for edit in edits:
        item = by_id.get(edit["id"])
        if item is None:
            raise ValidationFailed(f"없는 항목입니다: {edit['id']}", field="items")
        if edit.get("delete"):                              # 모델이 잘못 읽은(없는 제품을 읽은) 항목을 사용자가 지운다
            deleted.add(item["id"])
            continue
        renamed = False
        if edit.get("category") is not None and edit["category"] != item["category"]:   # 부품군을 잘못 읽었을 때
            if edit["category"] not in _SLOTS:
                raise ValidationFailed(f"부품군이 아닙니다: {edit['category']}", field="items")
            item["category"] = edit["category"]
            renamed = True                                  # 다른 부품군 카탈로그에서 다시 맞춘다
        if edit.get("normalized_name") is not None:
            name = str(edit["normalized_name"]).strip()
            if not name:
                raise ValidationFailed("제품명은 비울 수 없습니다.", field="items")
            renamed = renamed or name != item["normalized_name"]
            item["normalized_name"] = name
        if edit.get("quantity") is not None:
            item["quantity"] = int(edit["quantity"])
        if "quote_line_total" in edit:                      # null 로 보내면 가격을 지운다
            item["quote_line_total"] = edit["quote_line_total"]
        total, quantity = item["quote_line_total"], item["quantity"]
        item["quote_unit_price"] = round(total / quantity) if total else None
        item["quote_price_type"] = "unknown" if not total else "unit" if quantity == 1 else "line_total"
        item["user_edited"] = True
        if renamed:
            by_slot = by_slot or load_pc_catalog(lambda _msg: None)
            item.update(_match(item["category"], spec_text(item), by_slot))
            _attach_image_urls(conn, [item])
    if deleted:
        draft["items"] = [i for i in draft["items"] if i["id"] not in deleted]
    if selected is not None:
        for category, item_id in selected.items():
            item = by_id.get(item_id)
            if category not in _SLOTS or item is None or item["category"] != category or item_id in deleted:
                raise ValidationFailed(f"{category}의 분석 기준으로 고를 수 없는 항목입니다.", field="selected_item_by_category")
        draft["selected_item_by_category"] = {**draft["selected_item_by_category"], **selected}
    _repair_selection(draft)
    _apply_selection(draft)
    draft["version"] += 1
    _save(repo, revision["id"], draft)
    return draft


def add_item(conn, list_id: UUID, principal: Principal, expected_version: int, category: str, raw_text: str,
             source_id: str | None = None) -> dict:
    """모델이 못 읽은 부품을 사용자가 직접 적어 넣는다. `source_id`를 주면 그 견적(이미지)의 항목으로, 아니면 직접 추가 항목으로 —
    읽은 항목과 같은 방식(이름·코드·수량·가격 분리, 카탈로그 매칭)으로 처리한다."""
    repo, revision, draft = _revision_and_draft(conn, list_id, principal, lock=True)
    if draft["version"] != expected_version:
        raise StaleReviewVersion("초안이 다른 곳에서 바뀌었습니다. 새로 불러온 뒤 다시 시도해 주세요.", field="expected_version")
    if category not in _SLOTS:
        raise ValidationFailed(f"부품군이 아닙니다: {category}", field="category")
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValidationFailed("제품명을 입력해 주세요.", field="raw_text")
    if source_id is None:
        source_id = "manual"
        if not any(s["id"] == "manual" for s in draft["sources"]):
            draft["sources"].append({"id": "manual", "type": "manual", "file_name": None, "sort_order": len(draft["sources"]) + 1,
                                     "status": "completed", "error_code": None})
    elif not any(s["id"] == source_id for s in draft["sources"]):
        raise ValidationFailed(f"없는 견적입니다: {source_id}", field="source_id")
    item = _make_item(category, raw_text, source_id, load_pc_catalog(lambda _msg: None))
    item["user_edited"] = True
    _attach_image_urls(conn, [item])
    draft["items"].append(item)
    _repair_selection(draft)
    _apply_selection(draft)
    draft["version"] += 1
    _save(repo, revision["id"], draft)
    return draft


# ── BE-07·08 ─────────────────────────────────────────────────────────────────
def analyze_selected(conn, list_id: UUID, principal: Principal, source_ids: list[str] | None = None) -> dict:
    """선택한 항목만 기존 점검에 넣어 분석하고 같은 세션에 저장한다. source_ids 를 주면 그 견적(이미지)의 항목만 —
    서로 다른 견적을 올렸을 때 한 견적을 골라 분석한다(안 주면 부품군마다 고른 기준 제품 전체)."""
    repo, revision, draft = _revision_and_draft(conn, list_id, principal, lock=True)
    chosen = items_for_sources(draft, source_ids) if source_ids else \
        [i for i in draft["items"] if i["id"] in set(draft["selected_item_by_category"].values())]
    if not chosen:
        raise NoRecognizedItems("분석할 항목이 없습니다. 부품군마다 기준 제품을 골라 주세요.")
    specs = {item["category"]: spec_text(item) for item in chosen}
    review = quote_review_service.analyze(specs, draft.get("conditions"), conn=conn)
    quote_review_service._save(repo, revision["id"], review)
    rows = price_rows(chosen, review, load_pc_catalog(lambda _msg: None))
    excluded = [{"category": i["category"], "item_id": i["id"], "reason": "견적에 가격이 없어 합계에서 제외했습니다."}
                for i in chosen if i["quote_price_type"] == "unknown"]
    return {**review, "list_id": str(list_id), "used_items": chosen, "question": draft.get("question"),
            "draft_version": draft["version"], "price_excluded": excluded, "price_rows": rows}


# ── BE-08: 가격 필드(항목별) ─────────────────────────────────────────────────
def price_rows(chosen: list[dict], review: dict, by_slot: dict) -> list[dict]:
    """분석에 쓴 항목마다 견적 가격(단가·품목 합계·종류)과 카탈로그 가격(단가·품목 합계·확인 시각·상태)을 나란히.
    카탈로그 쪽은 점검의 가격 비교(`_price_row`)가 계산한 값을 그대로 쓴다 — 같은 제품으로 확정된 부품만 비교한다."""
    by_part = {r["part"]: r for r in ((review.get("prices") or {}).get("rows") or [])}
    out = []
    for item in chosen:
        row = by_part.get(item["category"])
        catalog_total = row.get("catalog") if row else None
        quantity = max(int(item["quantity"] or 1), 1)
        checked_at = None
        if catalog_total is not None and item.get("matched_name"):
            cand = next((c for c in by_slot.get(item["category"], []) if c.name == item["matched_name"]), None)
            checked_at = cand.price_observed_at if cand else None
        if catalog_total is not None:
            status = "available"
        elif item["match_status"] == "confirmed":
            status = "no_price"
        else:
            status = "unmatched"
        quoted_total = item["quote_line_total"]
        out.append({
            "category": item["category"], "item_id": item["id"], "quantity": quantity,
            "quote_unit_price": item["quote_unit_price"], "quote_line_total": quoted_total,
            "quote_price_type": item["quote_price_type"],
            "catalog_unit_price": round(catalog_total / quantity) if catalog_total is not None else None,
            "catalog_line_total": catalog_total, "catalog_checked_at": checked_at, "catalog_status": status,
            "diff_line_total": quoted_total - catalog_total if quoted_total is not None and catalog_total is not None else None,
        })
    return out


# ── 초안 → 점검 입력 ─────────────────────────────────────────────────────────
def _selected_items(draft: dict) -> list[dict]:
    chosen_ids = set(draft["selected_item_by_category"].values())
    return [i for i in draft["items"] if i["id"] in chosen_ids]


def _specs_for(draft: dict, *, baseline_item: dict | None = None) -> dict[str, str]:
    """분석 기준으로 고른 항목들의 점검 입력. baseline_item 을 주면 그 부품군은 그 항목으로 바꿔 본다."""
    specs = {i["category"]: spec_text(i) for i in _selected_items(draft)}
    if baseline_item is not None:
        specs[baseline_item["category"]] = spec_text(baseline_item)
    return specs


def _pool_by_product(by_slot: dict, category: str) -> dict[str, Any]:
    return {c.product_id: c for c in by_slot.get(category, []) if c.product_id}


def _item_card(item: dict, by_slot: dict) -> dict:
    """인식 항목 하나의 카드 — 가격·이미지·핵심 사양(점검과 같은 해석 결과)."""
    from src.services.quote_alternatives import _spec_rows

    info = resolve_owned_parts({item["category"]: spec_text(item)}, by_slot, [item["category"]]).get(item["category"]) or {}
    return {"item_id": item["id"], "product_id": item.get("matched_product_id"), "name": item.get("matched_name") or item["normalized_name"],
            "image_url": item.get("image_url"), "quantity": item["quantity"], "quote_line_total": item["quote_line_total"],
            "match_status": item["match_status"], "specs": _spec_rows(item["category"], {}, dict(info.get("specs") or {}))}


def _new_issue_replacements(category: str, changes: list[dict]) -> list[dict]:
    """이 교체 때문에 새로 비호환이 되는 검사에 걸린 **다른 부품군** — 같이 바꿔야 할 부품과 그 근거 문장."""
    from src.engine.stage3c_verify import AXIS_SLOTS

    out, seen = [], set()
    for ch in changes:
        if ch["to"] != "fail":
            continue
        for slot in AXIS_SLOTS.get(ch["axis"], ()):
            if slot != category and slot not in seen:
                seen.add(slot)
                out.append({"category": slot, "axis": ch["axis"], "reason": f"{ch['label']}: {ch['detail']}"})
    return out


def _reason_sentence(base_name: str | None, price_delta: int | None, new_fail: list[dict]) -> str:
    parts = []
    if price_delta is not None and base_name:
        parts.append(f"{base_name}보다 {abs(price_delta):,}원 {'저렴' if price_delta < 0 else '비싸' if price_delta > 0 else '같은 가격'}"
                     .replace("같은 가격", "가격이 같") + ("합니다" if price_delta else "습니다"))
    if new_fail:
        parts.append("바꾸면 " + ", ".join(c["label"] for c in new_fail) + " 문제가 새로 생깁니다")
    return ". ".join(parts) + "." if parts else "가격 차이를 계산할 수 없습니다."


# ── BE-05: 분석 전 제품 비교 ─────────────────────────────────────────────────
MAX_COMPARE_TARGETS = 4


def comparison(conn, list_id: UUID, principal: Principal, category: str, baseline_item_id: str | None,
               direction: str | None, target_product_ids: list[str]) -> dict:
    """분석 전에 한 부품군의 인식 제품들과 추천 제품을 나란히. 조회만 한다(초안·점검 결과를 바꾸지 않는다)."""
    from src.services import quote_alternatives

    draft = get_draft(conn, list_id, principal)
    if category not in _SLOTS:
        raise ValidationFailed(f"부품군이 아닙니다: {category}", field="category")
    if direction not in (None, "cheaper", "better"):
        raise ValidationFailed("direction은 cheaper 또는 better 여야 합니다.", field="direction")
    if len(target_product_ids) > MAX_COMPARE_TARGETS:
        raise ValidationFailed(f"비교 대상 제품은 {MAX_COMPARE_TARGETS}개까지입니다.", field="target_product_id")
    in_category = [i for i in draft["items"] if i["category"] == category]
    baseline = next((i for i in in_category if i["id"] == baseline_item_id), None) if baseline_item_id else \
        next((i for i in in_category if i["id"] == draft["selected_item_by_category"].get(category)), None)
    if baseline_item_id and baseline is None:
        raise ValidationFailed("그 부품군의 항목이 아닙니다.", field="baseline_item_id")
    if baseline is None:
        raise NoRecognizedItems(f"{category}로 인식된 항목이 없습니다.")
    by_slot = load_pc_catalog(lambda _msg: None)
    pool = _pool_by_product(by_slot, category)
    names = []
    for pid in target_product_ids:
        if pid not in pool:
            raise ValidationFailed(f"카탈로그에 없는 제품입니다: {pid}", field="target_product_id")
        names.append(pool[pid].name)
    review = {"input": {"current_specs": _specs_for(draft, baseline_item=baseline)}}
    result = quote_alternatives.compare_parts(review, category, by_slot, names or None, direction)
    if result.get("error"):
        raise ValidationFailed(result["error"], field="category")
    by_name = {c.name: c for c in by_slot[category]}
    urls = _image_urls(conn, [c.product_id for c in by_name.values() if c.product_id and c.name in {r["name"] for r in result["candidates"]}])
    recommended = []
    for row in result["candidates"]:
        cand = by_name.get(row["name"])
        new_fail = [c for c in row["compat_changes"] if c["to"] == "fail"]
        recommended.append({
            "product_id": cand.product_id if cand else None, "name": row["name"],
            "image_url": urls.get(cand.product_id) if cand and cand.product_id else None,
            "price": row["price"], "price_delta": row["price_delta"], "perf_tier": row["perf_tier"],
            "specs": row["specs"], "compat_changes": row["compat_changes"], "incompatible": row["incompatible"],
            "additional_replacements": _new_issue_replacements(category, row["compat_changes"]),
            "review": row["review"], "reason": _reason_sentence(result["baseline"].get("name"), row["price_delta"], new_fail),
        })
    notes = ([result["note"]] if result.get("note") else []) + [f"비교하지 못한 제품: {', '.join(result['unmatched_targets'])}"] * bool(result.get("unmatched_targets"))
    return {"category": category, "baseline_item_id": baseline["id"],
            "recognized": [_item_card(i, by_slot) for i in in_category], "recommended": recommended, "notes": notes}


# ── BE-06: 교체 영향 미리보기·적용 ────────────────────────────────────────────
def _resolve_replacements(draft: dict, replacements: list[dict], by_slot: dict) -> list[tuple[str, Any, dict]]:
    if not replacements:
        raise ValidationFailed("교체할 제품을 하나 이상 골라 주세요.", field="replacements")
    seen, out = set(), []
    selected = {i["category"]: i for i in _selected_items(draft)}
    for rep in replacements:
        category, pid = rep["category"], rep["candidate_product_id"]
        if category not in _SLOTS:
            raise ValidationFailed(f"부품군이 아닙니다: {category}", field="replacements")
        if category in seen:
            raise ValidationFailed(f"{category}는 한 번에 하나만 교체할 수 있습니다.", field="replacements")
        seen.add(category)
        cand = _pool_by_product(by_slot, category).get(pid)
        if cand is None:
            raise ValidationFailed(f"카탈로그에 없는 제품입니다: {pid}", field="replacements")
        out.append((category, cand, selected.get(category)))
    return out


def replacement_preview(conn, list_id: UUID, principal: Principal, replacements: list[dict]) -> dict:
    """여러 교체를 한꺼번에 적용했을 때 합계·호환이 어떻게 달라지는지. 조회만 한다 — 적용은 `replacement_apply`."""
    draft = get_draft(conn, list_id, principal)
    by_slot = load_pc_catalog(lambda _msg: None)
    resolved = _resolve_replacements(draft, replacements, by_slot)
    slot_structure = list(_SLOTS)
    specs = _specs_for(draft)
    owned_before = resolve_owned_parts(specs, by_slot, slot_structure)
    owned_after = dict(owned_before)
    for category, cand, _old in resolved:
        owned_after[category] = {"name": cand.name, "specs": dict(cand.specs), "source": "catalog"}
    before = quote_review_service.compat_for_quote(specs, by_slot, slot_structure, owned_before)
    after = quote_review_service.compat_for_quote(specs, by_slot, slot_structure, owned_after)
    changes = [c for c in _changes(before["checks"], after["checks"])]
    replaced = {category for category, _c, _o in resolved}
    before_total = after_total = 0
    excluded = []
    for item in _selected_items(draft):
        total = item["quote_line_total"]
        if item["category"] in replaced:
            cand = next(c for category, c, _o in resolved if category == item["category"])
            after_total += cand.price * max(int(item["quantity"] or 1), 1)
            if total is not None:
                before_total += total
            else:
                excluded.append({"category": item["category"], "item_id": item["id"], "reason": "견적에 가격이 없어 변경 전 합계에서 제외했습니다."})
        elif total is not None:
            before_total += total
            after_total += total
        else:
            excluded.append({"category": item["category"], "item_id": item["id"], "reason": "견적에 가격이 없어 합계에서 제외했습니다."})
    return {
        "before_total": before_total, "after_total": after_total, "total_diff": after_total - before_total,
        "new_issues": [c for c in changes if c["to"] == "fail"],
        "resolved_issues": [c for c in changes if c["from"] == "fail" and c["to"] != "fail"],
        "additional_replacements": [r for category, _c, _o in resolved
                                    for r in _new_issue_replacements(category, changes) if r["category"] not in replaced],
        "replaced_items": [{"category": category, "from_item_id": old["id"] if old else None,
                            "candidate_product_id": cand.product_id, "candidate_name": cand.name}
                           for category, cand, old in resolved],
        "price_excluded": excluded,
    }


def _changes(before_checks: list[dict], after_checks: list[dict]) -> list[dict]:
    from src.services.quote_alternatives import _compat_changes
    return _compat_changes(before_checks, after_checks)


def replacement_apply(conn, list_id: UUID, principal: Principal, expected_version: int, replacements: list[dict]) -> dict:
    """정확한 제품 ID로 초안의 항목을 교체한다 — 새 항목을 만들어 그 부품군의 분석 기준으로 삼는다(원래 항목은 남는다).
    교체 뒤 분석은 따로 요청한다(`analysis`)."""
    repo, revision, draft = _revision_and_draft(conn, list_id, principal, lock=True)
    if draft["version"] != expected_version:
        raise StaleReviewVersion("초안이 다른 곳에서 바뀌었습니다. 새로 불러온 뒤 다시 시도해 주세요.", field="expected_version")
    by_slot = load_pc_catalog(lambda _msg: None)
    resolved = _resolve_replacements(draft, replacements, by_slot)
    if not any(s["id"] == "replacement" for s in draft["sources"]):
        draft["sources"].append({"id": "replacement", "type": "replacement", "file_name": None,
                                 "sort_order": len(draft["sources"]) + 1, "status": "completed", "error_code": None})
    for category, cand, old in resolved:
        quantity = max(int(old["quantity"] or 1), 1) if old else 1
        total = cand.price * quantity
        item = {"id": str(uuid.uuid4()), "category": category, "raw_text": cand.name, "normalized_name": cand.name,
                "product_code": None, "quantity": quantity, "quote_unit_price": cand.price, "quote_line_total": total,
                "quote_price_type": "unit" if quantity == 1 else "line_total", "image_url": None,
                "source_ids": ["replacement"], "selected_for_analysis": True, "user_edited": True,
                "matched_product_id": cand.product_id, "matched_product_key": cand.product_key,
                "matched_name": cand.name, "match_status": "confirmed", "candidate_count": None}
        _attach_image_urls(conn, [item])
        draft["items"].append(item)
        draft["selected_item_by_category"][category] = item["id"]
    _apply_selection(draft)
    draft["version"] += 1
    _save(repo, revision["id"], draft)
    return draft


# ── 항목 단위 실시간 검색 ─────────────────────────────────────────────────────
def live_lookup_item(conn, list_id: UUID, principal: Principal, item_id: str) -> dict:
    """초안의 항목 하나를 실시간 검색+검증(사용자가 버튼을 눌렀을 때만). 카탈로그에서 확정된 항목은 대상이 아니다."""
    from src.services import live_spec_lookup

    if not live_spec_lookup.available():
        raise ServiceUnavailable("지금은 실시간 검색을 쓸 수 없습니다.", code="live_part_lookup_unavailable")
    draft = get_draft(conn, list_id, principal)
    item = next((i for i in draft["items"] if i["id"] == item_id), None)
    if item is None:
        raise NotFound("그 항목을 찾을 수 없습니다.", field="item_id")
    if item["match_status"] not in quote_review_service.LIVE_LOOKUP_STATUSES:
        raise ValidationFailed("카탈로그에 이미 대응된 부품은 실시간 검색 대상이 아닙니다.", field="item_id", code="already_matched")
    return {"item_id": item_id, **quote_review_service.live_lookup_text(conn, item["normalized_name"], item["category"])}

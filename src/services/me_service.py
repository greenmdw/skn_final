"""마이페이지 서버 저장 — 내 현재 PC(C-1), 사용자별 JSON 문서·견적서별 부가 정보(C-2).

C-2 는 "무엇을 서버에 둘지"를 정하는 대신 **화면 전용 값을 전부 담을 수 있게** 일반 JSON 문서로 받는다: 견적서마다 붙는 문서(조건 문장·책상 치수·
점검 스냅샷 …)와, 사용자별로 이름 붙인 문서(작성 중 상태·점검 세션 기록·초안 …). 서버는 내용의 모양을 모르고 크기·깊이·개수만 제한한다.
로그인한 계정만 쓴다(게스트는 브라우저에 그대로 둔다)."""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from src.auth.deps import Principal
from src.errors import Conflict, NotFound, ValidationFailed
from src.repo.me_repo import MeRepo
from src.repo.plan_repo import PlanRepo
from src.services import auth_service
from src.services.session_service import _owned

# 내 현재 PC 의 칸(프론트 기준). 서버 부품 종류 코드(cpu·gpu·ram·ssd·motherboard·psu·case·cooler)와 이름이 다른 칸은 아래 표로 이어 준다.
PC_FIELDS = ("cpu", "gpu", "ram", "storage", "board", "psu", "cooler", "case")
PC_FIELD_TO_PRODUCT_TYPE = {"cpu": "cpu", "gpu": "gpu", "ram": "ram", "storage": "ssd", "board": "motherboard",
                            "psu": "psu", "cooler": "cooler", "case": "case"}
PC_PART_MAX = 120
PC_SOURCE_MAX = 200
PC_TITLE_MAX = 100

DATA_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
DOC_MAX_BYTES = 256 * 1024          # 문서 하나(JSON 직렬화 크기)
DOC_MAX_DEPTH = 32
DATA_MAX_KEYS = 50                  # 사용자당 문서 개수
EXTRAS_LIST_LIMIT = 200


def _require_user(conn, principal: Principal) -> UUID:
    return auth_service.require_active_user(conn, principal)["id"]


def _check_document(value: Any, *, field: str) -> None:
    """JSON 문서의 크기·깊이를 제한한다(모양은 보지 않는다)."""
    def depth(node: Any, level: int) -> int:
        if level > DOC_MAX_DEPTH:
            return level
        if isinstance(node, dict):
            return max([level] + [depth(v, level + 1) for v in node.values()])
        if isinstance(node, list):
            return max([level] + [depth(v, level + 1) for v in node])
        return level

    if depth(value, 1) > DOC_MAX_DEPTH:
        raise ValidationFailed(f"JSON 중첩이 너무 깊습니다(최대 {DOC_MAX_DEPTH}단계).", field=field, code="document_too_deep")
    size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > DOC_MAX_BYTES:
        raise ValidationFailed(f"문서가 너무 큽니다({size:,}바이트, 최대 {DOC_MAX_BYTES // 1024}KB).", field=field, code="document_too_large")


# ── 내 현재 PC ──────────────────────────────────────────────────────────────────────
def _pc_out(row: dict) -> dict:
    parts = {key: row["parts"][key] for key in PC_FIELDS if row["parts"].get(key)}
    return {"parts": parts, "source": row["source"], "title": row["title"], "saved_at": row["saved_at"].isoformat()}


def get_pc(conn, principal: Principal) -> dict | None:
    user = _require_user(conn, principal)
    row = MeRepo(conn).get_pc(user)
    return _pc_out(row) if row else None


def put_pc(conn, principal: Principal, *, parts: dict, source: str, title: str) -> dict:
    user = _require_user(conn, principal)
    unknown = [key for key in parts if key not in PC_FIELDS]
    if unknown:
        raise ValidationFailed(f"알 수 없는 칸입니다: {', '.join(unknown)} (사용 가능: {', '.join(PC_FIELDS)})", field="parts", code="unknown_part")
    clean: dict[str, str] = {}
    for key in PC_FIELDS:
        text = re.sub(r"\s+", " ", str(parts.get(key) or "")).strip()
        if not text:
            continue
        if len(text) > PC_PART_MAX:
            raise ValidationFailed(f"{key} 값은 {PC_PART_MAX}자 이하로 적어 주세요.", field=f"parts.{key}")
        clean[key] = text
    if not clean:
        raise ValidationFailed("부품을 한 칸 이상 입력해 주세요.", field="parts")
    source, title = source.strip(), title.strip()
    if len(source) > PC_SOURCE_MAX:
        raise ValidationFailed(f"출처 문구는 {PC_SOURCE_MAX}자 이하로 적어 주세요.", field="source")
    if len(title) > PC_TITLE_MAX:
        raise ValidationFailed(f"제목은 {PC_TITLE_MAX}자 이하로 적어 주세요.", field="title")
    return _pc_out(MeRepo(conn).put_pc(user, parts=clean, source=source, title=title))


def delete_pc(conn, principal: Principal) -> None:
    user = _require_user(conn, principal)
    MeRepo(conn).delete_pc(user)                            # 이미 없어도 성공(멱등)


# ── 사용자별 JSON 문서 ───────────────────────────────────────────────────────────────
def _check_key(key: str) -> str:
    if not DATA_KEY_RE.match(key or ""):
        raise ValidationFailed("키는 영문 소문자·숫자·`.` `_` `:` `-` 로 64자 이하여야 합니다.", field="key", code="invalid_key")
    return key


def _doc_out(row: dict) -> dict:
    return {"key": row["key"], "value": row["value"], "updated_at": row["updated_at"].isoformat()}


def list_data(conn, principal: Principal) -> dict:
    user = _require_user(conn, principal)
    rows = MeRepo(conn).list_data(user)
    return {"items": [{"key": r["key"], "size_bytes": int(r["size_bytes"]), "updated_at": r["updated_at"].isoformat()} for r in rows],
            "limits": {"max_keys": DATA_MAX_KEYS, "max_bytes_per_document": DOC_MAX_BYTES, "max_depth": DOC_MAX_DEPTH}}


def get_data(conn, principal: Principal, key: str) -> dict:
    user = _require_user(conn, principal)
    row = MeRepo(conn).get_data(user, _check_key(key))
    if row is None:
        raise NotFound("저장된 문서가 없습니다.")
    return _doc_out(row)


def put_data(conn, principal: Principal, key: str, value: Any) -> dict:
    user = _require_user(conn, principal)
    key = _check_key(key)
    _check_document(value, field="value")
    repo = MeRepo(conn)
    if not repo.data_exists(user, key) and repo.count_data(user) >= DATA_MAX_KEYS:
        raise Conflict(f"저장할 수 있는 문서는 최대 {DATA_MAX_KEYS}개입니다. 안 쓰는 문서를 지운 뒤 다시 시도해 주세요.", code="too_many_documents")
    return _doc_out(repo.put_data(user, key, value))


def delete_data(conn, principal: Principal, key: str) -> None:
    user = _require_user(conn, principal)
    MeRepo(conn).delete_data(user, _check_key(key))        # 이미 없어도 성공(멱등)


# ── 견적서(목록)별 부가 정보 ─────────────────────────────────────────────────────────
def _own_plan(conn, principal: Principal, list_id: UUID) -> UUID:
    user = _require_user(conn, principal)
    plan = _owned(PlanRepo(conn), list_id, principal)
    if plan["owner_user_id"] != user:                       # 게스트가 만든 목록에는 붙이지 않는다(확정은 로그인 뒤에 한다)
        raise NotFound("목록을 찾을 수 없습니다.")
    return user


def _extras_out(list_id: UUID | str, row: dict) -> dict:
    return {"list_id": str(list_id), "extras": row["extras"], "updated_at": row["updated_at"].isoformat()}


def get_extras(conn, principal: Principal, list_id: UUID) -> dict:
    _own_plan(conn, principal, list_id)
    row = MeRepo(conn).get_extras(list_id)
    if row is None:
        return {"list_id": str(list_id), "extras": None, "updated_at": None}
    return _extras_out(list_id, row)


def put_extras(conn, principal: Principal, list_id: UUID, extras: dict) -> dict:
    _own_plan(conn, principal, list_id)
    _check_document(extras, field="extras")
    return _extras_out(list_id, MeRepo(conn).put_extras(list_id, extras))


def delete_extras(conn, principal: Principal, list_id: UUID) -> None:
    _own_plan(conn, principal, list_id)
    MeRepo(conn).delete_extras(list_id)


def list_extras(conn, principal: Principal) -> dict:
    user = _require_user(conn, principal)
    rows = MeRepo(conn).list_extras_for_user(user, EXTRAS_LIST_LIMIT)
    return {"items": {str(r["plan_id"]): {"extras": r["extras"], "updated_at": r["updated_at"].isoformat()} for r in rows}}

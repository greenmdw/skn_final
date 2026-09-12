"""세션 생성과 조건 수집 서비스."""
from __future__ import annotations
import hashlib, secrets
from uuid import UUID
import yaml
from src.auth.deps import Principal
from src.errors import NotFound, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import ConversationRepo
from src.config import CATEGORY_DIR

def _token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()
def _category(name: str) -> dict:
    path = CATEGORY_DIR / f"{name}.yaml"
    if not path.exists(): raise ValidationFailed("지원하지 않는 카테고리입니다.", field="category")
    return yaml.safe_load(path.read_text())
def _owned(repo: PlanRepo, list_id: UUID, principal: Principal) -> dict:
    revision = repo.get_current_revision(list_id)
    if revision is None: raise NotFound("목록을 찾을 수 없습니다.")
    user_ok = principal.user_id is not None and revision["user_id"] == principal.user_id
    guest_ok = principal.browser_token is not None and revision["guest_session_hash"] == _token_hash(principal.browser_token)
    if not (user_ok or guest_ok): raise NotFound("목록을 찾을 수 없습니다.")
    return revision

def create_session(conn, principal: Principal) -> dict:
    token = secrets.token_urlsafe(32)
    conversation_id = ConversationRepo(conn).create(user_id=principal.user_id, guest_session_hash=_token_hash(token))
    plan = PlanRepo(conn).create_plan(conversation_id, "새 추천", principal.user_id)
    version = PlanRepo(conn)._one("SELECT id FROM config.domain_version WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 1")
    if version is None: raise ValidationFailed("게시된 도메인 버전이 없습니다.")
    revision = PlanRepo(conn).new_revision(plan, version["id"], "새 추천")
    PlanRepo(conn).set_current_revision(plan, revision)
    return {"list_id": str(plan), "browser_token": token}

def choose_category(conn, list_id: UUID, category: str, mode: str | None, principal: Principal) -> dict:
    repo = PlanRepo(conn); current = _owned(repo, list_id, principal); config = _category(category)
    if mode is not None and mode not in config["modes"]: raise ValidationFailed("카테고리에 맞지 않는 mode입니다.", field="mode")
    repo.upsert_condition(current["id"], "category", {"value": category}, "explicit")
    repo.upsert_condition(current["id"], "mode", {"value": mode or config["modes"][0]}, "explicit")
    return condition_state(conn, list_id, principal)

def patch_slot(conn, list_id: UUID, field: str, value, principal: Principal) -> dict:
    repo = PlanRepo(conn); current = _owned(repo, list_id, principal)
    repo.upsert_condition(current["id"], field, {"value": value}, "explicit")
    return condition_state(conn, list_id, principal)

def condition_state(conn, list_id: UUID, principal: Principal) -> dict:
    current = _owned(PlanRepo(conn), list_id, principal); full = PlanRepo(conn).load_full(current["id"])
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    config = _category(values["category"]) if "category" in values else None
    required = config["required_inputs"] if config else []
    missing = [key for key in required if values.get(key) is None]
    return {"slots": values, "assumed": {}, "missing": missing, "next_questions": [], "can_recommend": not missing}

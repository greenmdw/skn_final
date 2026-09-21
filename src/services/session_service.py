"""세션 생성과 조건 대화 서비스 (계약: docs/frontend_외부수정요청.md §D-4-1)."""
from __future__ import annotations
import hashlib, logging, re, secrets
from uuid import UUID
from src.agent import conditions_agent
from src.auth.deps import Principal
from src.categories import available_categories, load_category
from src.engine import slot_rules
from src.errors import Conflict, FileTooLarge, NotFound, ValidationFailed
from src.repo.plan_repo import PlanRepo
from src.repo.user_repo import ConversationRepo

log = logging.getLogger(__name__)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _category(name: str) -> dict:
    try:
        return load_category(name)
    except FileNotFoundError:
        raise ValidationFailed("지원하지 않는 카테고리입니다.", field="category") from None


def _owned(repo: PlanRepo, list_id: UUID, principal: Principal) -> dict:
    revision = repo.get_current_revision(list_id)
    if revision is None:
        raise NotFound("목록을 찾을 수 없습니다.")
    user_ok = principal.user_id is not None and revision["owner_user_id"] == principal.user_id
    guest_ok = principal.browser_token is not None and revision["guest_session_hash"] == _token_hash(principal.browser_token)
    if not (user_ok or guest_ok):
        raise NotFound("목록을 찾을 수 없습니다.")
    return revision


def create_session(conn, principal: Principal) -> dict:
    token = principal.browser_token
    reused = False
    if principal.user_id is None:
        if token and ConversationRepo(conn).guest_identity_known(_token_hash(token)):
            reused = True
        else:
            token = secrets.token_urlsafe(32)
    conversation_id = ConversationRepo(conn).create(
        user_id=principal.user_id,
        guest_session_hash=None if principal.user_id is not None else _token_hash(token),
    )
    plan = PlanRepo(conn).create_plan(conversation_id, "새 추천", principal.user_id)
    version = PlanRepo(conn)._one(
        "SELECT dv.id FROM config.domain_version dv "
        "JOIN config.domain d ON d.id = dv.domain_id "
        "WHERE d.status = 'active' AND d.code = ANY(%s) ORDER BY d.code, dv.version_no DESC LIMIT 1",
        (available_categories(),),
    )
    if version is None:
        raise ValidationFailed("게시된 도메인 버전이 없습니다.")
    revision = PlanRepo(conn).new_revision(plan, version["id"], "새 추천")
    PlanRepo(conn).set_current_revision(plan, revision)
    return {"list_id": str(plan), "browser_token": None if principal.user_id is not None else token, "reused": reused}


def _field_value(meta: dict, values: dict):
    return values.get(meta["key"])


def _option_label_map(cat_def: dict, field: str) -> dict:
    question = next(
        (q for q in cat_def.get("question_sets", []) if q["maps_to"] == field),
        None,
    )
    if not question:
        return {}
    options = question.get("options") or []
    values = question.get("values") or options
    return {value: label for value, label in zip(values, options)}


def _display(
    meta: dict,
    value,
    option_labels: dict | None = None,
) -> str | None:
    if value in (None, ""):
        return None
    disp_map = meta.get("display")
    if disp_map:
        return disp_map.get(value, disp_map.get(str(value), str(value)))
    if isinstance(value, list):
        labels = option_labels or {}
        return " · ".join("없음" if v == "none" else str(labels.get(v, v)) for v in value)
    if isinstance(value, dict):
        return " · ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if meta["key"] == "budget_max" and isinstance(value, (int, float)):
        return f"{int(value):,}원"
    return str(value)


def _build_fields(cat_def: dict, values: dict) -> list[dict]:
    mode = values.get("mode")
    out = []
    for meta in cat_def.get("fields", []):
        if meta.get("mode_only") and meta["mode_only"] != mode:
            continue
        if meta.get("ask_when") and not _ask_applies(meta, values) and values.get(meta["key"]) is None:
            continue                       # 필요 없는 조건부 필드는 화면 목록에 안 낸다
        value = _field_value(meta, values)
        status = "confirmed" if meta["key"] in values and value is not None else "missing"
        out.append({
            "key": meta["key"], "label": meta.get("label"), "value": value,
            "display": _display(meta, value, _option_label_map(cat_def, meta["key"])),
            "status": status, "editable": True,
        })
    return out


def _ask_applies(meta: dict, values: dict) -> bool:
    """ask_when 조건: 이 질문/필드가 지금 필요한가. 없으면 항상 필요.
    - upgrade_parts_any: 고른 업그레이드 부품 중 하나라도 이 목록에 있을 때만
    - unless_current_specs_any: 사양 파일에 이 부품이 이미 적혀 있으면 다시 묻지 않는다"""
    cond = meta.get("ask_when")
    if not cond:
        return True
    from src.engine.stage2_requirement import normalize_pc_slot

    parts = {normalize_pc_slot(p) or str(p) for p in (values.get("upgrade_parts") or [])}
    wanted = cond.get("upgrade_parts_any")
    if wanted and not (parts & set(wanted)):
        return False
    known = values.get("current_specs")
    given = {normalize_pc_slot(k) or str(k) for k, v in (known.items() if isinstance(known, dict) else []) if v}
    return not (given & set(cond.get("unless_current_specs_any") or ()))


def _required_keys(cat_def: dict, values: dict) -> list[str]:
    req = list(cat_def.get("required_inputs", []))
    for mode, extra in (cat_def.get("required_inputs_by_mode") or {}).items():
        if values.get("mode") == mode:
            req += extra
    # 조건부 질문: 필요할 때만 필수가 된다("모르겠어요"도 답이라 채워지면 충족).
    for q in cat_def.get("question_sets", []):
        if q.get("ask_when") and (not q.get("mode_only") or q["mode_only"] == values.get("mode")) \
                and _ask_applies(q, values) and q["maps_to"] not in req:
            req.append(q["maps_to"])
    return req


def compute_missing(cat_def: dict, values: dict) -> list[str]:
    return [k for k in _required_keys(cat_def, values) if k not in values or values[k] is None]


def _next_question(cat_def: dict, values: dict) -> dict | None:
    mode = values.get("mode")
    missing = set(compute_missing(cat_def, values))
    for q in cat_def.get("question_sets", []):
        if q.get("mode_only") and q["mode_only"] != mode:
            continue
        if q["maps_to"] not in missing:
            continue
        options = q.get("options") or []
        qvalues = q.get("values") or options
        return {
            "id": q["id"], "field": q["maps_to"], "text": q["label"],
            "select": q["select"],
            "options": [{"value": v, "label": o} for o, v in zip(options, qvalues)],
        }
    return None


def _canonicalize_answer_values(question: dict, selected: list) -> list:
    """질문 선택지를 API에 정의된 원래 타입으로 되돌린다.

    HTML의 ``data-*`` 속성은 숫자와 불리언도 문자열로 만든다. ``values``가 있는
    선택지는 표시 라벨이나 문자열화된 값을 받아도 YAML의 원래 값으로 정규화한다.
    """
    options = question.get("options") or []
    values = question.get("values") or []
    if not values:
        return list(selected)

    normalized = []
    for item in selected:
        canonical = next(
            (value for option, value in zip(options, values)
             if item == option or item == value or str(item).casefold() == str(value).casefold()),
            item,
        )
        normalized.append(canonical)
    return normalized


def _messages_out(rows: list[dict]) -> list[dict]:
    return [
        {
            "id": str(row["id"]),
            "role": row["role"],
            "text": row["content"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


def _state(conn, list_id: UUID, principal: Principal) -> dict:
    prepo = PlanRepo(conn)
    revision = _owned(prepo, list_id, principal)
    full = prepo.load_full(revision["id"])
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    category = values.get("category")
    message_rows = ConversationRepo(conn).messages(revision["conversation_id"])
    if category is None:
        return {"list_id": str(list_id), "category": None, "mode": None,
                "messages": _messages_out(message_rows), "fields": [],
                "next_question": None, "can_recommend": False, "accepts_spec_file": False,
                "revision_id": str(revision["id"]), "lock_version": revision["lock_version"]}
    cat_def = _category(category)
    return {
        "list_id": str(list_id), "category": category, "mode": values.get("mode"),
        "messages": _messages_out(message_rows),
        "fields": _build_fields(cat_def, values),
        "next_question": _next_question(cat_def, values),
        "can_recommend": not compute_missing(cat_def, values),
        "accepts_spec_file": category == "computer" and values.get("mode") == "upgrade",
        "revision_id": str(revision["id"]), "lock_version": revision["lock_version"],
    }


def get_session_state(conn, list_id: UUID, principal: Principal) -> dict:
    return _state(conn, list_id, principal)


def choose_category(
    conn,
    list_id: UUID,
    category: str,
    mode: str | None,
    principal: Principal,
) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    cat_def = _category(category)
    if mode is not None and mode not in cat_def["modes"]:
        raise ValidationFailed("카테고리에 맞지 않는 mode입니다.", field="mode")
    # mode가 question_sets 안에 있으면(예: 컴퓨터의 q_mode) 챗봇이 직접 물어본다 —
    # 여기서 조용히 기본값을 채워버리면 그 질문이 영원히 안 나온다. 그런 질문이
    # 없는 카테고리만 이전처럼 첫 mode로 즉시 확정한다.
    mode_asked_in_chat = "mode" in cat_def.get("required_inputs", [])
    if mode is None and not mode_asked_in_chat:
        mode = cat_def["modes"][0]
    values, previous_category = _current_values(repo, current["id"])
    previous_mode = values.get("mode")
    # A draft pins its domain version on first category selection.  Re-selecting
    # the same category (for example to change mode) must not silently adopt a
    # version published after the conversation started.
    if previous_category != category:
        repo.bind_domain_version(current["id"], category)
    repo.upsert_condition(current["id"], "category", {"value": category}, "explicit")
    if mode is not None:
        repo.upsert_condition(current["id"], "mode", {"value": mode}, "explicit")
    if previous_category is not None and previous_category != category:
        for key in values:
            if key not in {"category", "mode"}:
                repo.clear_condition(current["id"], key)
    nq = _next_question(cat_def, {"mode": mode})
    if nq:
        ConversationRepo(conn).add_message(current["conversation_id"], "assistant", nq["text"])
    return _state(conn, list_id, principal)


def patch_slot(
    conn,
    list_id: UUID,
    field: str,
    value,
    principal: Principal,
) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    repo.upsert_condition(current["id"], field, {"value": value}, "explicit")
    return _state(conn, list_id, principal)


def _current_values(repo: PlanRepo, revision_id: UUID) -> tuple[dict, str | None]:
    full = repo.load_full(revision_id)
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    return values, values.get("category")


_ALL_SET = "필요한 조건을 모두 확인했어요. 이 조건으로 추천을 받아보세요."


def handle_message(
    conn,
    list_id: UUID,
    text: str,
    principal: Principal,
) -> dict:
    """자유 텍스트 한 턴. 에이전트가 있으면 도구 호출로 조건을 뽑고 답변 문장까지 만든다.

    에이전트가 없거나(MOCK_MODE·키 없음) 호출이 실패하면 규칙 추출(slot_rules)로 이번 턴을
    처리한다. 실패는 로그에만 남는다 — 화면에서는 규칙 경로와 구분되지 않는다.
    """
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    convo = ConversationRepo(conn)
    history = convo.messages(current["conversation_id"])     # 이번 메시지를 넣기 전
    msg_id = convo.add_message(current["conversation_id"], "user", text)

    reply: str | None = None
    extracted: dict = {}
    if conditions_agent.available():
        try:
            turn = conditions_agent.run_turn(
                category, cat_def, values, history, text,
                missing_fn=lambda v: compute_missing(cat_def, v),
                next_question_fn=lambda v: _next_question(cat_def, v))
            extracted, reply = turn.patches, turn.reply
            log.info("conditions agent [%s]: %s", list_id, " | ".join(turn.trace) or "(도구 호출 없음)")
        except Exception as exc:  # 모델·네트워크 오류 — 이번 턴만 규칙으로
            log.warning("conditions agent failed, falling back to slot_rules: %s", exc)
    if reply is None:
        extracted = slot_rules.extract(category, text)

    for key, value in extracted.items():
        repo.upsert_condition(current["id"], key, {"value": value}, "extracted", msg_id)
    values.update(extracted)

    nq = _next_question(cat_def, values)
    if reply is None:
        if nq:
            reply = nq["text"] if extracted else "죄송해요, 이해하지 못했어요. " + nq["text"]
        else:
            reply = _ALL_SET
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def handle_answer(
    conn,
    list_id: UUID,
    question_id: str,
    selected: list,
    principal: Principal,
) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    cat_def = _category(category)
    q = next((q for q in cat_def.get("question_sets", []) if q["id"] == question_id), None)
    if q is None:
        raise ValidationFailed("알 수 없는 질문입니다.", field="question_id")

    raw_selected = list(selected)
    selected = _canonicalize_answer_values(q, raw_selected)
    key = q["maps_to"]
    none_opt = q.get("none_option")
    if none_opt and list(selected) == [none_opt]:
        value = ["none"]
    elif q["select"] == "multi":
        value = list(selected)
    else:
        value = selected[0] if selected else None

    convo = ConversationRepo(conn)
    option_labels = _option_label_map(cat_def, key)
    user_text = ", ".join(str(option_labels.get(s, s)) for s in selected) if selected else "(선택 없음)"
    msg_id = convo.add_message(current["conversation_id"], "user", user_text)
    repo.upsert_condition(current["id"], key, {"value": value}, "explicit", msg_id)
    values[key] = value

    nq = _next_question(cat_def, values)
    reply = nq["text"] if nq else _ALL_SET
    convo.add_message(current["conversation_id"], "assistant", reply)
    return _state(conn, list_id, principal)


def reset_conditions(
    conn,
    list_id: UUID,
    principal: Principal,
) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    full = repo.load_full(current["id"])
    for row in full["conditions"]:
        if row["condition_key"] not in ("category", "mode"):
            repo.upsert_condition(current["id"], row["condition_key"], {"value": None}, "explicit")
    ConversationRepo(conn).add_message(current["conversation_id"], "system", "조건을 초기화했어요.")
    return _state(conn, list_id, principal)


# ── 업그레이드 사양 파일 첨부 (§D-4-1: current_specs · spec_file_name) ──
_ALLOWED_SPEC_EXTENSIONS = {"txt", "json", "csv", "md", "log", "nfo", "xml"}
_MAX_SPEC_FILE_BYTES = 1_000_000
_SPEC_LINE = re.compile(
    r"(?im)^\s*(cpu|프로세서|gpu|그래픽카드|그래픽|ram|메모리|메인보드|mainboard|motherboard|"
    r"파워|psu|케이스|case|쿨러|cooler)\s*[:=]\s*(.+?)\s*$")
_SPEC_KEY_MAP = {"cpu": "CPU", "프로세서": "CPU", "gpu": "GPU", "그래픽카드": "GPU", "그래픽": "GPU",
                 "ram": "RAM", "메모리": "RAM", "메인보드": "메인보드", "mainboard": "메인보드",
                 "motherboard": "메인보드", "파워": "파워", "psu": "파워", "케이스": "케이스", "case": "케이스",
                 "쿨러": "쿨러", "cooler": "쿨러"}


def _parse_spec_file(content: str) -> dict:
    """'CPU: i5-13600K' 같은 key: value 줄만 규칙 기반으로 뽑는다. 매칭 안 되면 빈 dict."""
    specs: dict[str, str] = {}
    for m in _SPEC_LINE.finditer(content):
        specs[_SPEC_KEY_MAP[m.group(1).lower()]] = m.group(2).strip()
    return specs


def attach_spec_file(
    conn,
    list_id: UUID,
    file_name: str,
    content: str,
    principal: Principal,
) -> dict:
    repo = PlanRepo(conn)
    current = _owned(repo, list_id, principal)
    values, category = _current_values(repo, current["id"])
    if category != "computer" or values.get("mode") != "upgrade":
        raise ValidationFailed("사양 파일은 PC 업그레이드에서만 첨부할 수 있습니다.", code="spec_file_not_accepted")
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext not in _ALLOWED_SPEC_EXTENSIONS:
        raise ValidationFailed("지원하지 않는 파일 형식입니다.", field="file_name", code="unsupported_file")
    if len(content.encode("utf-8")) > _MAX_SPEC_FILE_BYTES:
        raise FileTooLarge("파일이 너무 큽니다(1MB 이하).", field="content")
    specs = _parse_spec_file(content)
    repo.upsert_condition(current["id"], "spec_file_name", {"value": file_name}, "explicit")
    if specs:
        repo.upsert_condition(current["id"], "current_specs", {"value": specs}, "extracted")
    return _state(conn, list_id, principal)

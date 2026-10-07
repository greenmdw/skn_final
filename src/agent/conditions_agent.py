"""조건 대화 에이전트 — Strands Agents SDK.

`POST /session/{id}/message` 의 자유 텍스트를 처리한다. 규칙 추출(`slot_rules`)은 정해진
키워드만 잡아서 "추가 조건·변경 요청"이 조건에 안 실렸다(2026-09-13 회의). 여기서는 LLM 이
슬롯 스키마에 맞춰 **도구 호출**로 조건을 반영하고, 비어 있는 필수 항목을 이어서 묻는다.

경계 (§D-3 "판정·수치는 코드, LLM 은 서술" 유지):
- 쓸 수 있는 필드는 `config/categories/<cat>.yaml` 의 `slot_schema` 뿐이다. enum·타입·nullable 은
  코드(`ConditionDraft`)가 검사하고, 틀리면 도구가 오류 문장을 돌려줘 모델이 고쳐 부르게 한다.
- 에이전트는 DB 를 만지지 않는다. 도구는 `ConditionDraft.patches` 에 모으고 `session_service` 가
  `upsert_condition(origin="extracted")` 으로 적는다 — 규칙 경로와 같은 origin.
- 추천 실행·검증·순위·수치는 그대로 엔진이 한다. 에이전트는 조건 수집과 답변 문장만.
- `available()` 이 False(MOCK_MODE·키 없음·`CONDITIONS_AGENT=0`)면 만들지 않는다. 호출 실패는
  예외로 올리고, 규칙 경로로 바꿀지는 호출자(`session_service`)가 정한다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from src.engine.brands import canonical_slot, cpu_brand_pref
from src.config import CONDITIONS_AGENT, LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.engine.slot_rules import _parse_won
from src.errors import ServiceUnavailable

# 대화로 설정하지 않는 필드 — 사양 파일 첨부(/spec-file)가 채운다
_NOT_CONVERSATIONAL = {"current_specs", "spec_file_name"}
_HISTORY_LIMIT = 20


def available() -> bool:
    return (not MOCK_MODE and CONDITIONS_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


# ── 조건 초안: 도구가 쓰고 서비스가 읽는다 ──────────────────────────────────
MissingFn = Callable[[dict], list[str]]
NextQuestionFn = Callable[[dict], dict | None]


@dataclass
class ConditionDraft:
    category: str
    cat_def: dict
    values: dict                       # 현재 저장된 조건 (읽기 전용으로 취급)
    missing_fn: MissingFn              # 무엇이 필수인지는 규칙(session_service)이 정한다
    next_question_fn: NextQuestionFn
    patches: dict = field(default_factory=dict)   # 이번 턴에 바뀐 것만
    trace: list[str] = field(default_factory=list) # 도구 호출 기록 (로그·"추천 과정 보기" 용)
    preference_patches: list[dict] = field(default_factory=list)
    # 채팅에서 직접 말한 브랜드 선호·비선호(docs/사용자_선호비선호_기록_설계.md 파이프라인 A).
    # 에이전트는 DB를 안 만지므로 여기 모아만 두고, session_service가 로그인 사용자에 한해
    # identity.preference_signal에 반영한다(§7 — 게스트는 저장 안 함).
    conn: object = None            # 실시간 부품 검색 전용 — 읽기만 한다(카탈로그 조회·캐시), 조건은 여전히 안 쓴다
    search_confirmed: bool = False  # 직전 턴에 검색 동의를 구했고 이번 메시지가 동의인지(run_turn이 미리 판정)

    def question(self, key: str) -> dict | None:
        return next((q for q in self.cat_def.get("question_sets", []) if q["maps_to"] == key), None)

    def merged(self) -> dict:
        return {**self.values, **self.patches}

    def missing(self) -> list[str]:
        return self.missing_fn(self.merged())

    def next_question(self) -> dict | None:
        return self.next_question_fn(self.merged())

    def _status(self) -> str:
        """도구 결과 꼬리 — 모델이 다음에 무엇을 물을지 여기서 읽는다."""
        nq = self.next_question()
        if nq:
            return f" · 남은 필수 항목 {json.dumps(self.missing(), ensure_ascii=False)} · 다음 질문: \"{nq['text']}\""
        return " · 필수 항목 모두 채워짐 — 추천을 받아볼 수 있다고 안내"

    def schema(self) -> dict[str, dict]:
        mode = self.values.get("mode")
        # 다른 모드 전용 필드(업그레이드의 upgrade_parts·owned_*)는 열어 두지 않는다 — 열어 두면 새 조립 화면에서
        # "업그레이드로 반영했다"고 답하면서 엔진은 새 조립으로 계산하는 불일치가 생긴다. 모드를 아직 모르면 거르지 않는다.
        other_mode_only = {m["key"] for m in self.cat_def.get("fields", [])
                           if mode and m.get("mode_only") and m["mode_only"] != mode}
        return {k: v for k, v in (self.cat_def.get("slot_schema") or {}).items()
                if k not in _NOT_CONVERSATIONAL and k not in other_mode_only}

    def current(self, key: str):
        return self.patches[key] if key in self.patches else self.values.get(key)

    def _record(self, call: str, result: str) -> str:
        self.trace.append(f"{call} → {result}")
        return result

    def set(self, key: str, raw) -> str:
        call = f"set_condition({key!r}, {raw!r})"
        meta = self.schema().get(key)
        if meta is None:
            return self._record(call, f"오류: '{key}' 는 설정할 수 없는 필드입니다. 가능한 필드: {', '.join(self.schema())}")
        if key == "budget_max" and isinstance(raw, str) and raw.strip().lower() not in ("", "null", "none"):
            value = _parse_amount(raw)
            if value is None or value <= 0:
                return self._record(call, f"오류: {key} — 0보다 큰 금액으로 (예: 1500000 · 150만원)")
        else:
            try:
                value = _coerce(meta, raw)
            except ValueError as exc:
                return self._record(call, f"오류: {key} — {exc}")
        q = self.question(key)
        if meta.get("type") == "list" and q and q.get("none_option"):
            # 목록형 "없음" 은 ["none"] 하나로 — 규칙 경로(slot_rules)·칩 선택(handle_answer)과 같은 표현
            if any(str(x).lower() in ("none", q["none_option"], "없음", "없어요") for x in value):
                value = ["none"]
        self.patches[key] = value
        shown = json.dumps(value, ensure_ascii=False)
        return self._record(call, f"{key} = {shown} 반영" + self._status())

    def clear(self, key: str) -> str:
        call = f"clear_condition({key!r})"
        if key not in self.schema():
            return self._record(call, f"오류: '{key}' 는 설정할 수 없는 필드입니다.")
        self.patches[key] = None
        return self._record(call, f"{key} 비움" + self._status())

    def record_brand_preference(self, slot: str, brand: str, direction: str) -> str:
        call = f"record_brand_preference({slot!r}, {brand!r}, {direction!r})"
        if direction not in ("prefer", "avoid"):
            return self._record(call, "오류: direction 은 prefer 또는 avoid 여야 합니다.")
        if not slot.strip() or not brand.strip():
            return self._record(call, "오류: slot·brand 는 비울 수 없습니다.")
        self.preference_patches.append({"slot": slot.strip(), "value": brand.strip(), "direction": direction})
        pref = cpu_brand_pref(brand)
        if canonical_slot(slot) == "CPU" and direction == "prefer" and pref:
            # CPU는 기존 brand_pref 필드가 있다 — 이번 견적에도 바로 반영되게 같이 채운다. "인텔"·"라이젠"처럼
            # 한글·제품군 이름도 별칭으로 맞춘다(예전엔 "amd"·"intel" 글자 그대로만 담겼다).
            self.patches["brand_pref"] = pref
        return self._record(call, f"{slot} 브랜드 {direction} 기록: {brand}" + self._status())

    def search_unavailable_part(self, slot: str, product_text: str) -> str:
        """사용자가 조건 대화 중 구체적인 제품명을 말했는데 카탈로그에 없을 때
        (docs/미보유부품_실시간스펙검색_설계.md 확장). 이 에이전트는 부품을 직접 고르지
        않으므로(그건 추천 엔진 몫), 찾은 스펙은 extra 조건으로만 남긴다 — 판정 없이 기록."""
        from src.repo.catalog_repo import load_candidates_by_slot_from_db
        from src.engine.owned_parts import _match_catalog, catalog_family_matches
        call = f"search_unavailable_part({slot!r}, {product_text!r})"
        if self.conn is None:
            return self._record(call, "오류: 지금은 이 기능을 쓸 수 없습니다.")
        canon = canonical_slot(slot) or slot
        pool = load_candidates_by_slot_from_db(self.conn).get(canon, [])
        matches = _match_catalog(product_text, pool)
        if matches:
            names = ", ".join(c.name for c in matches[:3])
            return self._record(call, f"'{product_text}'는 실제로 카탈로그에 있습니다: {names}.")
        family = catalog_family_matches(product_text, pool)
        if family:       # "엔비디아 5070"처럼 시리즈 낱말이 빠졌을 뿐 카탈로그에 있는 제품 — 없다고 하면 안 된다
            names = ", ".join(c.name for c in family[:4])
            return self._record(call, f"'{product_text}'는 카탈로그에 있는 제품입니다: {names}. DB에 없는 상품이 아니니 외부 검색을 "
                                      "묻지 마세요. 어느 제품인지(예: Ti 여부)가 정해지지 않았으면 그것만 되물으세요.")
        if not self.search_confirmed:
            return self._record(call, f"'{product_text}'는 저희 DB에 없는 상품으로 확인됩니다. {SEARCH_PERMISSION_MARKER}")
        from src.services import live_spec_lookup
        if not live_spec_lookup.available():
            return self._record(call, "지금은 실시간 검색을 쓸 수 없습니다.")
        try:
            result = live_spec_lookup.lookup(self.conn, product_text, slot=canon)
        except ServiceUnavailable as exc:      # 검색이 몰려 있거나 연결 실패 — 대화를 끊지 않고 문장으로 알린다
            return self._record(call, f"{exc.message} 지금은 이 제품 정보를 가져오지 못했습니다.")
        if not result.relevant or not result.has_any_field():
            return self._record(call, f"'{product_text}'에 대한 정보를 실시간 검색으로도 찾지 못했습니다.")
        found = {k: v for k, v in result.supported_fields.model_dump().items() if v is not None}
        fields = ", ".join(f"{k}={v}" for k, v in found.items())
        src = f" · 출처: {result.source_url}" if result.source_url else ""
        self.add_extra(f"{slot} 희망: {product_text} ({fields}){src} · 카탈로그 정식 등재 값 아님")
        return self._record(call, f"실시간 검색 결과 — {fields}{src} · 카탈로그 정식 등재 값이 아니니 참고만 하세요. "
                                  "추가 조건으로 기록했습니다. " + self._wanted_part(canon, product_text, found, result.source_url)
                                  + self._status())

    def _wanted_part(self, slot: str, product_text: str, fields: dict, source_url: str | None) -> str:
        """원한 미보유 부품을 `wanted_parts` 조건에 남기고, 그것이 추천에 어떻게 반영되는지(또는 안 되는지) 알리는 문장.

        신규 조립만 호환 조건으로 쓰인다(소켓·메모리 규격 — engine/wanted_parts.py). 그 부품 자체는 가격·성능 점수가
        없어 견적에 넣을 수 없고, 같은 슬롯은 카탈로그에서 추천된다."""
        from src.engine.wanted_parts import describe_hints, platform_hints

        if "wanted_parts" not in self.schema():
            return ""
        wanted = dict(self.current("wanted_parts") or {})
        wanted[slot] = {"name": product_text, "fields": fields, "source_url": source_url}
        self.patches["wanted_parts"] = wanted
        if self.merged().get("mode") == "upgrade":
            return "업그레이드 모드에서는 이 부품으로 다른 부품을 맞추지 않고 기록만 합니다."
        conditions = describe_hints(platform_hints({slot: {"fields": fields}}))
        if conditions:
            return (f"이 부품 자체는 카탈로그에 없어 견적에 넣을 수 없지만, {conditions} 기준으로 나머지 부품을 맞춰 "
                    f"추천합니다. {slot}은 카탈로그의 비슷한 제품이 추천됩니다.")
        return ("이 부품은 소켓·메모리 규격 같은 호환 조건을 만들지 않아 추천은 달라지지 않습니다. "
                f"{slot}은 카탈로그의 제품이 추천됩니다.")

    def add_extra(self, text: str) -> str:
        call = f"add_extra_condition({text!r})"
        text = text.strip()
        if not text:
            return self._record(call, "오류: 빈 조건")
        if "extra" not in self.schema():
            return self._record(call, "오류: 이 카테고리는 자유 조건(extra)을 받지 않습니다.")
        items = list(self.current("extra") or [])
        if text not in items:
            items.append(text)
        self.patches["extra"] = items
        return self._record(call, f"extra 에 추가: {text}" + self._status())


# ── DB 미보유 부품 실시간 검색 — 동의 확인(conditions_agent·result_agent 공유) ─────────
# docs/미보유부품_실시간스펙검색_설계.md §2(자동 실행 금지)를 대화로 옮긴 것 — 직전 턴에
# 에이전트가 이 문구로 동의를 구했고, 이번 메시지가 동의로 읽히면 그 턴에서만 실제 검색을
# 허용한다. 동의 여부는 LLM 재량이 아니라 이 함수(코드)가 판정한다 — 문구를 고치면 여기도
# 같이 고쳐야 한다.
SEARCH_PERMISSION_MARKER = "외부 검색을 진행해도 될까요?"
_SEARCH_CONFIRM_RE = re.compile(
    r"^\s*(?:응|ㅇㅇ|ㅇㅋ|오케이|ok|okay|네|넵|예|그래|좋아|콜|부탁해|부탁|그렇게\s*해|해줘|해봐|찾아줘|검색해줘|진행해)"
    r"(?:\s|[.!~,?]|$)", re.IGNORECASE)


# 위 정규식은 "응/네/해줘…"로 시작하고 바로 끝나야 해서 "진행해줘"·"진행해 주세요"·"외부 검색 진행해줘"를 놓쳤다
# ("진행해" 뒤에 "줘"가 붙으면 경계 조건에 걸린다). 공백·문장부호를 걷어 낸 짧은 문장 전체가 "동의 어구"일 때만 동의로 본다.
# 새 요청이 섞인 문장("다른 부품으로 비교해줘")과 부정("진행하지마")은 전체가 이 모양이 아니라서 동의가 아니다.
_SEARCH_CONFIRM_LOOSE = re.compile(
    r"^(?:응|ㅇㅇ|ㅇㅋ|네|넵|예|그래|좋아|오케이|ok|okay)?"
    r"(?:외부)?(?:검색)?(?:진행|검색|찾아|해)(?:해)?"
    r"(?:줘|주세요|주세용|봐|봐요|보세요|하세요|할게|할게요|도돼|도돼요|도됩니다|부탁해|부탁해요|부탁드립니다)?(?:요|용)?$",
    re.IGNORECASE)
_PUNCT_AND_SPACE = re.compile(r"[\s.!~,?…]+")


def is_search_confirmation(last_reply: str | None, text: str) -> bool:
    """직전 턴의 에이전트 답변이 검색 동의를 구했고(SEARCH_PERMISSION_MARKER 포함) 이번
    사용자 메시지가 동의인지."""
    if not last_reply or SEARCH_PERMISSION_MARKER not in last_reply:
        return False
    clean = text.strip()
    if _SEARCH_CONFIRM_RE.search(clean):
        return True
    return bool(_SEARCH_CONFIRM_LOOSE.match(_PUNCT_AND_SPACE.sub("", clean.lower())))


def _parse_amount(text: str) -> int | None:
    """'1500000' · '1,500,000원' · '150만원' · '1.5억' · '삼백만원' → 원 단위 정수."""
    plain = text.replace(",", "").strip()
    if re.fullmatch(r"-?\d+", plain):
        return int(plain)
    won = _parse_won(text)                      # 만·억·원 (숫자 또는 한글 숫자 단어, 예: 삼백만원)
    if won:
        return won
    m = re.search(r"\d{4,}", plain)
    if m:
        return int(m.group(0))
    return None


def _coerce(meta: dict, raw):
    t = meta.get("type")
    s = raw.strip() if isinstance(raw, str) else raw
    if s in (None, "", "null", "none", "None") and meta.get("nullable"):
        return None
    if t == "enum":
        allowed = [v for v in meta.get("values", []) if v is not None]
        for v in allowed:
            if str(v).lower() == str(s).lower():
                return v
        raise ValueError(f"허용값은 {allowed} 중 하나")
    if t == "int":                     # 저장은 원 단위 정수
        if isinstance(s, bool):
            raise ValueError("정수가 필요")
        if isinstance(s, (int, float)):
            return int(s)
        amount = _parse_amount(str(s))
        if amount is not None:
            return amount
        raise ValueError("원 단위 정수로 (예: 1500000 · 150만원)")
    if t == "bool":
        if isinstance(s, bool):
            return s
        low = str(s).lower()
        if low in ("true", "yes", "1", "예", "네"):
            return True
        if low in ("false", "no", "0", "아니오", "아니요"):
            return False
        raise ValueError("true 또는 false")
    if t == "list":
        if isinstance(s, list):
            items = [str(x).strip() for x in s]
        else:
            text = str(s)
            if text.startswith("["):
                try:
                    items = [str(x).strip() for x in json.loads(text)]
                except json.JSONDecodeError as exc:
                    raise ValueError("JSON 배열 또는 쉼표 구분 목록") from exc
            else:
                items = [x.strip() for x in text.split(",")]
        items = [x for x in items if x]
        if not items:
            raise ValueError("빈 목록")
        return items
    if t == "str":
        return str(s)
    raise ValueError("이 필드는 대화로 설정하지 않습니다")


# ── 도구 ───────────────────────────────────────────────────────────────────
def make_tools(draft: ConditionDraft) -> list:
    from strands import tool

    @tool
    def set_condition(field: str, value: str) -> str:
        """조건 필드 하나를 설정한다. 사용자가 명시적으로 말한 값만 넣는다. 게임 제목은 games(쉼표 구분),
        "게임용 PC" 같은 용도 표현은 purpose 에도 반영한다.

        Args:
            field: 시스템 프롬프트의 필드 목록에 있는 키 (예: purpose, budget_max)
            value: 값. enum 은 허용값 코드 그대로, 금액은 사용자가 말한 그대로("150만원", "1,500,000원"),
                   목록은 쉼표로 구분, bool 은 true/false, 지우려면 "null".
        """
        return draft.set(field, value)

    @tool
    def add_extra_condition(text: str) -> str:
        """필드 목록에 없는 구체적 요구(예: "흰색 케이스", "RGB 없이", "무선 키보드 포함")를
        추가 조건으로 남긴다. 필드가 있는 값(게임 제목 → games, 해상도 → resolution 등)은
        여기가 아니라 set_condition 으로 넣는다. 판단·추천은 하지 않고 기록만 한다.

        Args:
            text: 사용자의 요구를 짧은 한 구절로
        """
        return draft.add_extra(text)

    @tool
    def clear_condition(field: str) -> str:
        """사용자가 조건을 취소·변경하려 할 때 필드를 비운다. 새 값이 있으면 set_condition 을 쓴다.

        Args:
            field: 비울 필드 키
        """
        return draft.clear(field)

    @tool
    def record_brand_preference(slot: str, brand: str, direction: str) -> str:
        """사용자가 특정 부품 브랜드를 좋아하거나("AMD가 좋아요") 싫어한다고("인텔은 별로예요")
        직접 말했을 때만 부른다 — 추측하지 않는다. set_condition 의 brand_pref(CPU 전용, 값 하나)와
        달리 어느 슬롯이든, 선호·비선호 둘 다 기록할 수 있다.

        Args:
            slot: 부품 슬롯 (예: CPU, GPU, RAM, 메인보드, 저장장치, 파워, 케이스, 쿨러)
            brand: 브랜드명 (예: AMD, Intel, NVIDIA)
            direction: "prefer"(선호) 또는 "avoid"(비선호)
        """
        return draft.record_brand_preference(slot, brand, direction)

    @tool
    def search_unavailable_part(slot: str, product_text: str) -> str:
        """사용자가 구체적인 제품명을 말했는데(예: "RTX 6090으로 해줘", "9950X3D 있어?") 그게
        지금 카탈로그에 있는지 확신이 안 설 때 부른다. 먼저 카탈로그 전체에서 코드가 다시
        확인하고, 정말 없으면 실시간 검색에 동의를 구하는 문장만 돌려준다(바로 검색하지 않는다)
        — 동의는 사용자의 다음 메시지로 받는다.

        Args:
            slot: 부품 슬롯 (예: CPU, GPU, RAM, 메인보드, 저장장치, 파워, 케이스, 쿨러)
            product_text: 사용자가 말한 제품명 원문(브랜드·모델 포함)
        """
        return draft.search_unavailable_part(slot, product_text)

    return [set_condition, add_extra_condition, clear_condition, record_brand_preference,
            search_unavailable_part]


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def _field_lines(draft: ConditionDraft) -> list[str]:
    """필드 한 줄씩: 키·타입·뜻, 그리고 질문 칩의 선택지→값 매핑 (모델이 코드값을 알게)."""
    labels = {f["key"]: f["label"] for f in draft.cat_def.get("fields", []) if "label" in f}
    lines = []
    for key, meta in draft.schema().items():
        q = draft.question(key)
        desc = f"{meta.get('type')}"
        if meta.get("type") == "enum":
            desc += " " + json.dumps([v for v in meta["values"] if v is not None], ensure_ascii=False)
        if meta.get("nullable"):
            desc += ", nullable"
        if meta.get("type") == "list":
            desc += " (항목 여러 개, 쉼표 구분)"
        label = labels.get(key) or (q["label"] if q else key)
        line = f"- {key}: {desc} — {label}"
        if q and q.get("options"):
            if q.get("values"):
                pairs = [f"{o}→{json.dumps(v, ensure_ascii=False)}" for o, v in zip(q["options"], q["values"]) if v is not None]
                line += ". 선택지: " + ", ".join(pairs)
                if meta.get("type") == "int":
                    line += " (정확한 값을 알면 그 값)"
            else:
                line += ". 선택지: " + ", ".join(q["options"])
            if q.get("none_option"):
                line += f'. "{q["none_option"]}" 이면 값은 none'
        lines.append(line)
    return lines


def system_prompt(
    draft: ConditionDraft,
    user_text: str = "",
    history: list[dict] = (),
) -> str:
    current = {k: draft.current(k) for k in draft.schema() if draft.current(k) not in (None, [], "")}
    # 턴 시작 시점의 '다음 질문' 을 여기 박으면 모델이 도구로 채운 뒤에도 그 질문을 또 붙인다(실측 2회).
    # 도구 결과에 다시 계산한 '다음 질문' 이 실리니 그것만 따르게 한다.
    ask = ("도구를 부른 뒤에는 **마지막 도구 결과의 '다음 질문'** 을 그대로 물어 답변을 맺습니다 (화면이 그 항목의 "
           "선택지를 함께 보여줍니다). 마지막 도구 결과가 '모두 채워짐' 이면 질문을 붙이지 않습니다. "
           "도구를 하나도 안 불렀으면 '비어 있는 필수 항목' 의 첫 번째를 묻습니다.")
    return "\n".join([
        f"당신은 TrueFit(목적성 쇼핑 플래너)의 조건 수집 도우미입니다. 카테고리: {draft.cat_def.get('label', draft.category)}.",
        "사용자의 말에서 아래 필드에 해당하는 값을 찾아 set_condition 으로 반영하고, 필드에 없는 구체적 요구는",
        "add_extra_condition 으로 남깁니다. 취소·변경 요청은 clear_condition 또는 새 값의 set_condition 으로 처리합니다.",
        "",
        "필드 (키: 타입 [허용값] — 뜻):",
        *_field_lines(draft),
        "",
        f"현재 값: {json.dumps(current, ensure_ascii=False)}",
        f"비어 있는 필수 항목: {json.dumps(draft.missing(), ensure_ascii=False)}",
        "",
        "규칙:",
        "1. 사용자가 말하지 않은 값을 추측해서 넣지 않습니다. 애매하면 되묻습니다. 도구가 '오류:' 를 돌려주면 값을 고쳐 다시 부릅니다.",
        "2. 필드에 맞는 값(예: 게임 제목 → games, 해상도 → resolution)은 add_extra_condition 이 아니라 그 필드에 넣습니다. "
        "'게임용'·'게임 위주'·'작업용'·'사무용' 처럼 용도가 드러나면 games 와 별개로 purpose 도 반드시 설정합니다.",
        "3. 답변은 2문장 이내. 반영한 내용을 짧게 확인합니다. " + ask,
        "4. 필수 항목이 모두 채워졌으면 '이 조건으로 추천을 받아볼 수 있다'고 안내하고 추가 조건이 있으면 말해 달라고 합니다.",
        "5. 값을 바꿀 때는 clear_condition 없이 set_condition 에 새 값만 넣습니다. clear 는 '취소'·'빼 주세요' 에만 씁니다.",
        "6. 제품 추천·가격·성능·호환성 판단을 하지 않습니다. 그건 다음 단계의 엔진이 합니다.",
        "7. 금액은 원화로만 씁니다. 금액을 새로 계산하지 않습니다.",
        "8. 사용자가 특정 부품 브랜드를 좋아하거나 싫어한다고 직접 말하면(예: \"인텔은 별로예요\", "
        "\"AMD가 좋아요\") record_brand_preference 로 기록합니다. 짐작해서 부르지 않습니다.",
        "9. 사용자가 구체적인 제품명을 말했으면(예: \"RTX 6090으로 해줘\", \"9950X3D 있어?\") "
        "search_unavailable_part(slot, product_text)를 부릅니다. 돌려준 문장을 그대로 전합니다 — "
        "동의를 구하는 문장이면 그걸로 끝내고, 검색 결과가 오면 '카탈로그 정식 등재 값이 아니다'는 "
        "부분까지 그대로 전합니다. 이 제품을 조건으로 확정하지 않습니다 — brand_pref·extra 외의 "
        "필드에 특정 제품명을 넣지 않습니다.",
        *_mode_rules(draft),
        "",
        "답변 언어: 한국어 존댓말.",
    ])


def _mode_rules(draft: ConditionDraft) -> list[str]:
    """새 조립 화면에서 기존 PC 업그레이드를 말했을 때 — 조건으로 받은 척하지 않고 이 화면의 범위를 알린다."""
    if draft.values.get("mode") != "build" or "upgrade" not in (draft.cat_def.get("modes") or []):
        return []
    return ["10. 이 화면은 새 컴퓨터 조립만 다룹니다. 사용자가 지금 쓰는 PC의 일부만 바꾸는 '업그레이드'를 원하면 "
            "그 내용을 조건으로 기록하거나 반영했다고 말하지 말고, 이 화면에서는 새 컴퓨터 조립만 가능하다고 "
            "안내한 뒤 새로 맞출 PC의 용도·예산을 묻습니다."]


def _history(rows: list[dict], limit: int = _HISTORY_LIMIT) -> list[dict]:
    """DB 대화 행 → Strands messages. 마지막 system 행(조건 초기화) 이후만, 같은 역할 연속은 합친다."""
    cut = 0
    for i, r in enumerate(rows):
        if r["role"] == "system":
            cut = i + 1
    msgs: list[dict] = []
    for r in rows[cut:]:
        if r["role"] not in ("user", "assistant"):
            continue
        if msgs and msgs[-1]["role"] == r["role"]:
            msgs[-1]["content"][0]["text"] += "\n" + r["content"]
        else:
            msgs.append({"role": r["role"], "content": [{"text": r["content"]}]})
    msgs = msgs[-limit:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


# ── 실행 ───────────────────────────────────────────────────────────────────
@dataclass
class TurnResult:
    reply: str
    patches: dict
    trace: list[str]
    preference_patches: list[dict] = field(default_factory=list)


def _model():
    from strands.models.openai import OpenAIModel
    # gpt-6-luna는 기본값(1) 외의 temperature를 거부하고(이 에이전트들처럼 도구 호출을 쓰는 경우)
    # reasoning_effort='none'을 명시해야 한다(실측, 2026-10-01) — 그 외 모델은 기존대로 0.2를 쓴다.
    if LLM_MODEL == "gpt-6-luna":
        params = {"reasoning_effort": "none"}
    else:
        params = {"temperature": 0.2}
    return OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL, params=params)


def run_turn(category: str, cat_def: dict, values: dict, history: list[dict], text: str,
             *, missing_fn: MissingFn, next_question_fn: NextQuestionFn, conn=None) -> TurnResult:
    """한 턴 실행. history 는 이번 사용자 메시지를 제외한 DB 대화 행.

    `missing_fn`·`next_question_fn` 은 규칙(`session_service`)이다 — 무엇이 필수이고 다음에 무엇을
    물을지는 에이전트가 정하지 않는다. 도구 결과마다 다시 계산해 모델에 돌려준다.

    `conn`은 실시간 부품 검색 전용(선택) — 이 에이전트는 여전히 조건 외에는 DB에 쓰지 않는다.
    """
    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    last_reply = next((r["content"] for r in reversed(history) if r["role"] == "assistant"), None)
    draft = ConditionDraft(category=category, cat_def=cat_def, values=dict(values),
                           missing_fn=missing_fn, next_question_fn=next_question_fn,
                           conn=conn, search_confirmed=is_search_confirmation(last_reply, text))
    agent = Agent(
        model=_model(),
        system_prompt=system_prompt(draft, text, history),
        tools=make_tools(draft),
        messages=_history(history),
        tool_executor=SequentialToolExecutor(),   # 도구들이 한 draft 를 순서대로 고친다
        callback_handler=None,          # 기본 핸들러는 stdout 에 스트리밍한다
    )
    result = agent(text)
    return TurnResult(reply=str(result).strip(), patches=dict(draft.patches), trace=list(draft.trace),
                      preference_patches=list(draft.preference_patches))

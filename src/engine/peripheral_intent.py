"""주변기기 견적 입력 해석 — 결과 모양, 정해진 목록 안으로 정리, 목적 풀이, 단어 규칙
(docs/local/견적_입력_설계.md 4·5장).

사용자가 한 문장으로 말한 것을 `Interpretation` 으로 읽는다. 값은 전부 `config/peripherals.yaml` 의
`purposes` · `situations` · `spec_conditions` 에 있는 이름뿐이고, 목록에 없는 값은 만들지 않는다.
이 모듈은 DB·언어 모델을 모른다. 언어 모델 호출은 `src/agent/peripheral_intent_agent.py`,
캐시·물러나기는 `src/services/peripheral_interpret_service.py` 가 맡는다.

## 경계

- **직접 말한 것과 풀어낸 것을 섞지 않는다.** `stated` 만 후보를 거를 수 있다(그것도 spec_conditions 의
  `filter: true` 인 조건만). 목적·상황에서 풀린 조건은 항상 선호다 — 해석이 틀려도 제품이 사라지지 않게 하려는 것이다.
- 성향 취향(`tastes`)은 아직 읽지 않는다. 성향 축과 쪽의 이름이 정해지는 체감 점수 단계(구현 순서 6)에서 더한다.
  지금 그런 말은 `unrecognized` 로 남는다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from src.dto import PERIPHERAL_KINDS, PeripheralKind
from src.engine import spec_rules
from src.engine.peripheral_rules import (
    conflicts, emphasis_cfg, kind_def, load_peripheral_rules, pc_purpose_map, peripheral_kinds, purpose_codes, purposes, ranking_def,
    situations, spec_conditions, split_purpose_codes,
)

Kind = PeripheralKind
HandSize = Literal["small", "medium", "large"]

BUDGET_MAX_WON = 10_000_000          # 이 값을 넘는 금액은 예산으로 읽지 않는다(오입력·오해석 방어)
UNRECOGNIZED_MAX_ITEMS = 5
UNRECOGNIZED_MAX_CHARS = 40

# 사용자 문장·사용기 본문에 섞인 "AI 에게 하는 지시문"이 반영하지 못한 말 목록으로 화면에 나가거나 글이 점수에 쓰이지 않게 거른다.
# 부품명·말투에는 나오지 않는 표현만 쓴다(src/agent/spec_extraction_agent.py 와 같은 원칙).
# 사용기에는 "무조건 편한 건 아니다", "AI가 추천해서 샀다" 같은 평범한 말이 흔하므로, 낱말 하나만으로는 걸지 않고
# "AI 를 부르는 말" 이나 "명령하는 어미" 와 함께 나올 때만 건다(예: 읽는 AI, AI는 … 추천하라, 무조건 … 해라).
_IMPERATIVE = (r"(?:(?:추천|출력|답변?|말|표시|인식|적|무시)\s*(?:하라|해라|해줘|해\s*주세요|하세요|하십시오)"
               r"|(?:하라|해라|하세요|하십시오|해\s*주세요|따르라|따라라))(?![가-힣])")
_INJECTION_CUES = re.compile(
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above)|disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above|instructions?)"
    r"|system\s*:|(?:system|developer)\s+prompt|(?:follow|obey|new|these|above|your)\s+instructions?"
    r"|이전\s*지시|지시(?:를|문|사항)?\s*(?:무시|따라)|읽는\s*AI|AI\s*(?:에게|야)"
    r"|AI\s*(?:는|가)[^.!?\n]{0,40}?" + _IMPERATIVE +
    r"|무조건[^.!?\n]{0,20}?" + _IMPERATIVE,
    re.IGNORECASE,
)


QUESTION_TYPES = ("term", "compat", "capabilities", "conditions", "compare", "why", "spec", "review", "other")
QUESTION_TOPIC_MAX_CHARS = 40


class Question(BaseModel):
    """이번 문장이 조건이 아니라 질문일 때의 종류(QA PQA-014). 조건과 달리 **이번 턴에만** 있다 — 이어 말해도 누적하지 않는다.

    type — term 용어 설명 · compat 내 PC와 맞는지 · capabilities 할 수 있는 일 · conditions 말할 수 있는 조건 · compare 1위와 다른
           선택지의 차이 · why 고른 이유 · spec 스펙 값 · review 사용기 근거 · other 위에 없는 질문(범위 밖)
    topic — term 은 용어 이름, spec·review 는 설정 chat.spec_topics·review_topics 의 이름. 없으면 None
    kinds — 질문이 가리키는 종류(문장에 이름이 나온 것). 비면 결과의 모든 종류
    """

    type: str
    topic: str | None = None
    kinds: list[Kind] = Field(default_factory=list)


class Interpretation(BaseModel):
    """문장 해석 결과(견적 입력 설계 4.1). 이어서 말하면 이전 결과에 더해진다(`merge`)."""

    kinds: list[Kind] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    situations: list[str] = Field(default_factory=list)
    stated: dict[Kind, list[str]] = Field(default_factory=dict)      # 직접 말한 스펙 조건(종류 → 조건 이름)
    hand_size: HandSize | None = None
    budget: dict[Kind, int] = Field(default_factory=dict)            # 종류별 예산 상한(원)
    budget_total: int | None = None                                   # 여러 종류를 합친 예산(원)
    emphasis: dict[Kind, list[str]] = Field(default_factory=dict)    # 강조한 축(종류 → 가격·리뷰·무상AS·브랜드·스펙 기준 이름)
    brand_like: dict[Kind, list[str]] = Field(default_factory=dict)  # 선호 브랜드(카탈로그 이름)
    brand_avoid: dict[Kind, list[str]] = Field(default_factory=dict)  # 기피 브랜드 — 후보에서 뺀다
    unrecognized: list[str] = Field(default_factory=list)
    question: Question | None = None                                  # 이번 문장이 질문이면 그 종류(누적하지 않는다)


class ResolvedCondition(BaseModel):
    condition: str
    label: str
    sources: list[str] = Field(default_factory=list)     # 이 조건을 풀어낸 목적·상황 코드. 직접 말했으면 ["stated"]
    prefs: list[dict[str, Any]] = Field(default_factory=list)


class ResolvedKind(BaseModel):
    """한 종류에 대한 풀이 결과. preferences 는 선호(순위만 바꾼다), filters 는 직접 말해서 거르는 조건이다."""

    kind: Kind
    label: str
    purposes: list[dict[str, str]] = Field(default_factory=list)     # [{code, label}]
    preferences: list[ResolvedCondition] = Field(default_factory=list)
    filters: list[ResolvedCondition] = Field(default_factory=list)
    feel: list[str] = Field(default_factory=list)
    taste: list[str] = Field(default_factory=list)
    # 함께 있을 수 없는 조건이 둘 다 풀린 경우(설정 conflicts). kept 가 None 이면 둘 다 뺐다 — 채팅에서 되묻는다.
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    def preference_prefs(self) -> list[dict[str, Any]]:
        return spec_rules.dedupe_prefs([p for c in self.preferences for p in c.prefs])

    def filter_prefs(self) -> list[dict[str, Any]]:
        return spec_rules.dedupe_prefs([p for c in self.filters for p in c.prefs])

    def stated_preference_prefs(self) -> list[dict[str, Any]]:
        """선호 중 사용자가 **직접 말한** 조건의 스펙 조건. 점수식이 이 조건을 속한 스펙 기준의 가중(×2)과 기준 값의 가중(2)에
        쓴다. 목적·상황에서 풀린 조건(`sources` 가 목적 코드뿐)은 여기 들어가지 않는다."""
        return spec_rules.dedupe_prefs([p for c in self.preferences if "stated" in c.sources for p in c.prefs])


def kinds_all_order(kinds: list[str]) -> list[str]:
    """화면과 결과에서 종류를 늘 같은 순서로 보여주기 위한 고정 순서."""
    return [k for k in PERIPHERAL_KINDS if k in kinds]


def _unique(values) -> list:
    return list(dict.fromkeys(values))


def squash_spaces(text: str | None) -> str:
    """연속 공백(줄바꿈 포함)을 한 칸으로, 앞뒤 공백은 없앤다."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_text(text: str) -> str:
    """같은 문장을 같은 열쇠로 보게 한다: 공백 정리, 소문자."""
    return squash_spaces(text).lower()


def looks_like_injected_instruction(text: str) -> bool:
    return bool(_INJECTION_CUES.search(text or ""))


# ── 정해진 목록 안으로 정리 ────────────────────────────────────────────────
def purpose_vocabulary(rules: dict | None = None) -> list[str]:
    """`purposes` 로 고를 수 있는 코드. 공통 상황과 이름이 같은 코드(quiet_place·portable·small_desk)는
    상황으로만 읽는다 — 같은 말이 두 목록에 중복으로 나오지 않게 한다. 풀이(`resolve`)는 둘을 같이 본다."""
    rules = rules or load_peripheral_rules()
    sit = set(situations(rules))
    return [c for c in purpose_codes(rules) if c not in sit]


def _positive_won(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    won = int(value)
    return won if 0 < won <= BUDGET_MAX_WON else None


def _question(raw: Any, kinds_all: list[str]) -> Question | None:
    """질문 종류는 정해진 목록 안의 값만 받는다. 모르는 종류·형식이면 질문이 아닌 것으로 본다."""
    if not isinstance(raw, dict) or raw.get("type") not in QUESTION_TYPES:
        return None
    topic = raw.get("topic")
    topic = topic.strip()[:QUESTION_TOPIC_MAX_CHARS] if isinstance(topic, str) and topic.strip() else None
    kinds = raw.get("kinds") if isinstance(raw.get("kinds"), list) else []
    return Question(type=raw["type"], topic=topic, kinds=kinds_all_order([k for k in kinds if k in kinds_all]))


def sanitize(raw: Any, rules: dict | None = None) -> Interpretation:
    """언어 모델이나 요청 바디의 dict 를 목록 안의 값만 남긴 `Interpretation` 으로 바꾼다.
    목록에 없는 값은 조용히 뺀다(만들어 넣지 않는다). 형식이 아예 맞지 않으면 빈 결과다."""
    rules = rules or load_peripheral_rules()
    data = raw if isinstance(raw, dict) else {}
    kinds_all = peripheral_kinds(rules)

    def _strings(value: Any) -> list[str]:
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    def _names(value: Any, allowed: set[str]) -> list[str]:
        return _unique(v for v in _strings(value) if v in allowed)

    stated: dict[str, list[str]] = {}
    raw_stated = data.get("stated") if isinstance(data.get("stated"), dict) else {}
    for kind, ids in raw_stated.items():
        if kind in kinds_all:
            kept = _names(ids, set(spec_conditions(kind, rules)))
            if kept:
                stated[kind] = kept

    raw_budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    budget = {k: w for k, v in raw_budget.items() if k in kinds_all and (w := _positive_won(v)) is not None}

    # 직접 말한 조건이나 예산이 있는 종류는 찾는 종류에도 넣는다(종류를 따로 적지 않은 모델 출력 보정).
    kinds = _unique([*_names(data.get("kinds"), set(kinds_all)), *stated, *budget])
    kinds = kinds_all_order(kinds)

    unrecognized: list[str] = []
    for item in data.get("unrecognized") if isinstance(data.get("unrecognized"), list) else []:
        if not isinstance(item, str):
            continue
        text = squash_spaces(item)[:UNRECOGNIZED_MAX_CHARS]
        if text and not looks_like_injected_instruction(text):
            unrecognized.append(text)

    brands = set(emphasis_cfg(rules)["brands"])

    def _per_kind(value: Any, allowed_for: Callable[[str], set[str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for kind, items in (value if isinstance(value, dict) else {}).items():
            if kind in kinds_all:
                kept = _names(items, allowed_for(kind))
                if kept:
                    out[kind] = kept
        return out

    emphasis = _per_kind(data.get("emphasis"), lambda k: {*_EMPHASIS_AXIS_NAMES, *ranking_def(k, rules)["criteria"]})
    brand_like = _per_kind(data.get("brand_like"), lambda k: brands)
    brand_avoid = _per_kind(data.get("brand_avoid"), lambda k: brands)
    for kind, liked in brand_like.items():                # 같은 브랜드를 선호이면서 기피로 둘 수 없다 — 기피가 이긴다
        brand_like[kind] = [b for b in liked if b not in brand_avoid.get(kind, [])]
    brand_like = {k: v for k, v in brand_like.items() if v}
    for kind in brand_like:                                # 선호 브랜드를 말했으면 브랜드 축을 강조한다(기획 3.3)
        emphasis[kind] = _unique([*emphasis.get(kind, []), "브랜드"])

    purpose_hits, situation_hits = split_purpose_codes(_strings(data.get("purposes")), _strings(data.get("situations")), rules)
    return Interpretation(
        kinds=kinds,
        purposes=purpose_hits,
        situations=situation_hits,
        stated=stated,
        hand_size=data.get("hand_size") if data.get("hand_size") in ("small", "medium", "large") else None,
        budget=budget,
        budget_total=_positive_won(data.get("budget_total")),
        emphasis=emphasis, brand_like=brand_like, brand_avoid=brand_avoid,
        unrecognized=_unique(unrecognized)[:UNRECOGNIZED_MAX_ITEMS],
        question=_question(data.get("question"), kinds_all),
    )


def _union_per_kind(a: dict[str, list[str]], b: dict[str, list[str]]) -> dict[str, list[str]]:
    return {kind: _unique([*a.get(kind, []), *b.get(kind, [])]) for kind in {*a, *b}}


def merge(previous: Interpretation | None, new: Interpretation) -> Interpretation:
    """문장을 이어서 말하면 이전 조건에 더한다(견적 입력 설계 3장). 조건을 빼려면 칩을 지운다."""
    if previous is None:
        return new
    stated: dict[str, list[str]] = {}
    for kind in {*previous.stated, *new.stated}:
        stated[kind] = _unique([*previous.stated.get(kind, []), *new.stated.get(kind, [])])
    return Interpretation(
        kinds=kinds_all_order(_unique([*previous.kinds, *new.kinds])),
        purposes=_unique([*previous.purposes, *new.purposes]),
        situations=_unique([*previous.situations, *new.situations]),
        stated=stated,
        hand_size=new.hand_size or previous.hand_size,
        budget={**previous.budget, **new.budget},
        budget_total=new.budget_total if new.budget_total is not None else previous.budget_total,
        emphasis=_union_per_kind(previous.emphasis, new.emphasis),
        brand_like=_union_per_kind(previous.brand_like, new.brand_like),
        brand_avoid=_union_per_kind(previous.brand_avoid, new.brand_avoid),
        unrecognized=_unique([*previous.unrecognized, *new.unrecognized])[:UNRECOGNIZED_MAX_ITEMS],
        question=new.question,                         # 질문은 이번 턴 것만 — 앞 턴의 질문을 다시 답하지 않는다
    )


# ── 목적 풀이 ──────────────────────────────────────────────────────────────
def resolve(interp: Interpretation, rules: dict | None = None) -> dict[str, ResolvedKind]:
    """찾는 종류마다 목적·상황·직접 말한 조건을 선호와 거르기 조건으로 푼다(견적 입력 설계 5.1).

    - 목적·상황: 그 종류의 `purposes` 표에 같은 코드가 있으면 `prefer` 의 조건을 **선호**로 더한다.
      같은 코드가 표에 없는 종류에는 아무 일도 하지 않는다("종류를 가리지 않은 말은 모든 종류에 적용").
    - 직접 말한 조건(`stated`): `filter: true` 인 조건만 거르기, 아니면 선호로 쓴다.
    - 같은 조건이 거르기에 있으면 선호에서는 뺀다(이미 통과한 후보만 남기 때문이다).
    """
    rules = rules or load_peripheral_rules()
    resolved: dict[str, ResolvedKind] = {}
    for kind in kinds_all_order(interp.kinds):
        table = purposes(kind, rules)
        conds = spec_conditions(kind, rules)
        applied = [c for c in _unique([*interp.purposes, *interp.situations]) if c in table]

        sources: dict[str, list[str]] = {}
        for code in applied:
            for cond_id in table[code]["prefer"]:
                sources.setdefault(cond_id, []).append(code)

        filter_ids: list[str] = []
        for cond_id in interp.stated.get(kind, []):
            if cond_id not in conds:
                continue
            if conds[cond_id]["filter"]:
                filter_ids.append(cond_id)
            else:
                sources.setdefault(cond_id, []).append("stated")

        dropped: list[dict[str, Any]] = []
        for a, b in conflicts(kind, rules):
            present = {c: c in filter_ids or c in sources for c in (a, b)}
            if not all(present.values()):
                continue
            stated = {c: c in filter_ids or "stated" in sources.get(c, []) for c in (a, b)}
            kept = a if stated[a] and not stated[b] else b if stated[b] and not stated[a] else None
            for c in (a, b):
                if c != kept:
                    sources.pop(c, None)
                    filter_ids = [f for f in filter_ids if f != c]
            dropped.append({"conditions": [a, b], "labels": [conds[a]["label"], conds[b]["label"]], "kept": kept})

        def _condition(cond_id: str, src: list[str], conds=conds) -> ResolvedCondition:
            cond = conds[cond_id]
            return ResolvedCondition(condition=cond_id, label=cond["label"], sources=src,
                                     prefs=[dict(p) for p in cond["prefs"]])

        resolved[kind] = ResolvedKind(
            kind=kind,
            label=kind_def(kind, rules)["label"],
            purposes=[{"code": c, "label": table[c]["label"]} for c in applied],
            preferences=[_condition(cid, src) for cid, src in sources.items() if cid not in filter_ids],
            filters=[_condition(cid, ["stated"]) for cid in filter_ids],
            feel=_unique(f for c in applied for f in table[c]["feel"]),
            taste=_unique(t for c in applied for t in table[c]["taste"]),
            conflicts=dropped,
        )
    return resolved


def from_pc_purpose(pc_purpose: str | None, rules: dict | None = None) -> list[str]:
    """PC 견적의 용도(game/creation/office/study/other)를 주변기기 목적 코드로 옮긴다."""
    rules = rules or load_peripheral_rules()
    return list(pc_purpose_map(rules).get(pc_purpose or "", []))


# ── 단어 규칙(언어 모델을 쓸 수 없을 때) ──────────────────────────────────
_KIND_WORDS: dict[str, tuple[str, ...]] = {
    "monitor": ("모니터", "monitor"),
    "keyboard": ("키보드", "keyboard"),
    "mouse": ("마우스", "mouse"),
    "speaker": ("스피커", "speaker"),
}
_TOTAL_HINT = re.compile(r"합쳐|합계|전부|전체|총\s*예산|다\s*해서")
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(만\s*원|만원|만)")
_HAND_SMALL = re.compile(r"손이?\s*작|작은\s*손")
_HAND_LARGE = re.compile(r"손이?\s*(?:크|큰)|큰\s*손")
_KIND_PROXIMITY = 15      # 금액 앞쪽 몇 글자 안의 종류 이름을 그 금액의 대상으로 본다


def _contains_any(text: str, words) -> bool:
    return any(w.lower() in text for w in words)


def _positions(text: str, words) -> list[tuple[int, int]]:
    out = []
    for w in words:
        start = text.find(w)
        while start >= 0:
            out.append((start, start + len(w)))
            start = text.find(w, start + 1)
    return out


def _near_hit(text: str, rule: dict, kind: str | None) -> bool:
    """feel 낱말과 target 낱말이 순서와 관계없이 window 글자 안에 함께 있는가. 둘 사이에 다른 종류 이름이 끼면
    그 종류를 꾸미는 말로 보고 읽지 않는다("묵직한 마우스랑 키보드" 의 "묵직" 은 키보드 키압이 아니다)."""
    others = [w for k, words in _KIND_WORDS.items() if k != kind for w in words]
    for fs, fe in _positions(text, rule["feel"]):
        for ts, te in _positions(text, rule["target"]):
            if abs(fs - ts) > rule["window"]:
                continue
            between = text[min(fe, te):max(fs, ts)]
            if not _contains_any(between, others):
                return True
    return False


def kinds_in_text(text: str) -> list[str]:
    """문장에 이름이 나온 종류(고정 순서)."""
    lowered = normalize_text(text)
    return kinds_all_order([kind for kind, words in _KIND_WORDS.items() if _contains_any(lowered, words)])


def near_reading(text: str, entry: dict, kind: str | None = None) -> str | None:
    """이 항목이 낱말(`words`)이 아니라 가까이 나온 두 낱말(`near`)로만 읽혔으면 그 느낌 낱말을 돌려준다. 아니면 None.
    채팅이 "'묵직한'을 키압이 묵직한 쪽으로 읽었어요"처럼 어떻게 읽었는지 말하는 데 쓴다."""
    lowered = normalize_text(text)
    for phrase in entry.get("exclude", ()):
        lowered = lowered.replace(phrase.lower(), " " * len(phrase))
    if _contains_any(lowered, entry["words"]):
        return None
    for rule in entry.get("near", ()):
        if _near_hit(lowered, rule, kind):
            return next((w for w in rule["feel"] if w in lowered), None)
    return None


def _entry_hits(text: str, entry: dict, kind: str | None = None) -> bool:
    """설정 항목 하나(목적·상황·스펙 조건)가 문장에 걸리는가. `exclude` 낱말은 지우고 본다("텐키리스" 안의 "텐키"),
    `near` 는 어순이 달라도 두 낱말이 가까이 있으면 걸린다."""
    for phrase in entry.get("exclude", ()):
        text = text.replace(phrase.lower(), " " * len(phrase))
    if _contains_any(text, entry["words"]):
        return True
    return any(_near_hit(text, rule, kind) for rule in entry.get("near", ()))


_EMPHASIS_AXIS_NAMES = ("가격", "리뷰", "무상AS", "브랜드")
_BRAND_AVOID_WINDOW = 8          # 브랜드 이름 뒤 몇 글자 안의 기피 낱말을 그 브랜드에 건 것으로 본다


def _alias_positions(lowered: str, alias: str) -> list[int]:
    """낱말 경계를 지킨 위치. "델"이 "모델" 안에서 잡히지 않게 앞 글자가 한글·영숫자이면 건너뛴다. 영문 별칭은 뒤 글자도 본다
    ("hp" 가 "hpc" 안에서 잡히지 않게). 한글 뒤의 조사("로지텍은")는 허용한다."""
    out, start = [], 0
    while True:
        pos = lowered.find(alias, start)
        if pos < 0:
            return out
        start = pos + 1
        before = lowered[pos - 1] if pos > 0 else " "
        after = lowered[pos + len(alias)] if pos + len(alias) < len(lowered) else " "
        if before.isalnum():
            continue
        if alias.isascii() and after.isascii() and after.isalnum():
            continue
        out.append(pos)


def _read_emphasis_and_brands(lowered: str, scope: list[str], rules: dict) -> tuple[dict, dict, dict]:
    """낱말 규칙으로 강조 축과 선호·기피 브랜드를 읽는다. 종류를 모르면(scope 가 비면) 붙일 곳이 없어 읽지 않는다."""
    cfg = emphasis_cfg(rules)
    if not scope:
        return {}, {}, {}
    axes = [axis for axis, words in cfg["words"].items() if _contains_any(lowered, words)]
    like: list[str] = []
    avoid: list[str] = []
    for brand, aliases in cfg["brands"].items():
        for alias in aliases:
            hits = _alias_positions(lowered, alias)
            if not hits:
                continue
            tail = lowered[hits[0] + len(alias): hits[0] + len(alias) + _BRAND_AVOID_WINDOW]
            (avoid if _contains_any(tail, cfg["brand_avoid_words"]) else like).append(brand)
            break
    like = [b for b in _unique(like) if b not in avoid]
    emphasis_axes = _unique([*axes, *(["브랜드"] if like else [])])
    emphasis = {k: list(emphasis_axes) for k in scope} if emphasis_axes else {}
    return (emphasis, {k: list(like) for k in scope} if like else {},
            {k: _unique(avoid) for k in scope} if avoid else {})


def interpret_by_words(text: str, rules: dict | None = None, kinds_hint: list[str] | None = None) -> Interpretation:
    """낱말 일치로만 읽는다. 언어 모델의 한도·실패·부재 때 물러나는 경로라 정확도보다 안전을 택한다:
    확신할 수 있는 말(종류 이름, 목록의 낱말, 금액)만 읽고, 못 읽은 말을 `unrecognized` 로 지어내지 않는다.

    `kinds_hint` 는 종류 카드로 이미 고른 종류다. 문장에 종류 이름이 없어도 그 종류에 직접 말한 조건과 금액을
    붙인다(카드를 고른 뒤 같은 문장을 다시 읽을 때 조건이 사라지지 않게 한다)."""
    rules = rules or load_peripheral_rules()
    lowered = normalize_text(text)
    kinds_all = peripheral_kinds(rules)

    positions: dict[str, int] = {}
    for kind, words in _KIND_WORDS.items():
        found = [lowered.find(w) for w in words if w in lowered]
        if found:
            positions[kind] = min(found)
    kinds = kinds_all_order([*positions, *(k for k in (kinds_hint or []) if k in kinds_all)])

    purpose_hits = []
    for code in purpose_vocabulary(rules):
        entries = [(kind, purposes(kind, rules)[code]) for kind in kinds_all if code in purposes(kind, rules)]
        if any(_entry_hits(lowered, entry, kind) for kind, entry in entries):
            purpose_hits.append(code)
    situation_hits = [code for code, entry in situations(rules).items() if _entry_hits(lowered, entry)]

    stated: dict[str, list[str]] = {}
    scope = kinds or kinds_all          # 종류를 가리지 않은 말은 모든 종류에 적용한다
    for kind in scope:
        ids = [cid for cid, cond in spec_conditions(kind, rules).items() if _entry_hits(lowered, cond, kind)]
        if ids:
            stated[kind] = ids
    if not kinds:
        stated = {}         # 종류를 모르면 직접 말한 조건도 붙일 곳이 없다(카드로 종류를 묻는다)

    budget: dict[str, int] = {}
    budget_total: int | None = None
    for match in _AMOUNT.finditer(lowered):
        won = int(float(match.group(1).replace(",", "")) * 10_000)
        if not 0 < won <= BUDGET_MAX_WON:
            continue
        before = [(pos, kind) for kind, pos in positions.items() if 0 <= match.start() - pos <= _KIND_PROXIMITY]
        if before and not _TOTAL_HINT.search(lowered):
            budget[max(before)[1]] = won          # 금액에 가장 가까이 앞선 종류 이름
        elif len(kinds) == 1 and not _TOTAL_HINT.search(lowered):
            budget[kinds[0]] = won
        elif kinds:
            budget_total = won
        # 종류를 모르는 금액은 버린다 — 어느 기기의 예산인지 가릴 수 없다

    hand = "small" if _HAND_SMALL.search(lowered) else "large" if _HAND_LARGE.search(lowered) else None
    emphasis, brand_like, brand_avoid = _read_emphasis_and_brands(lowered, scope if kinds else [], rules)
    return Interpretation(
        kinds=[k for k in kinds],
        purposes=purpose_hits,
        situations=situation_hits,
        stated=stated,
        hand_size=hand,
        budget=budget,
        budget_total=budget_total,
        emphasis=emphasis, brand_like=brand_like, brand_avoid=brand_avoid,
    )

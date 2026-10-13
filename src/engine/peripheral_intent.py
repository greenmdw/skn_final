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
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.engine import spec_rules
from src.engine.peripheral_rules import (
    kind_def, load_peripheral_rules, pc_purpose_map, peripheral_kinds, purpose_codes, purposes, situations,
    spec_conditions,
)

Kind = Literal["monitor", "keyboard", "mouse", "speaker"]
HandSize = Literal["small", "medium", "large"]

BUDGET_MAX_WON = 10_000_000          # 이 값을 넘는 금액은 예산으로 읽지 않는다(오입력·오해석 방어)
UNRECOGNIZED_MAX_ITEMS = 5
UNRECOGNIZED_MAX_CHARS = 40

# 사용자 문장에 섞인 "AI 에게 하는 지시문"이 반영하지 못한 말 목록으로 화면에 나가지 않게 거른다.
# 부품명·말투에는 나오지 않는 표현만 쓴다(src/agent/spec_extraction_agent.py 와 같은 원칙).
_INJECTION_CUES = re.compile(
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above)|disregard|system\s*:|(?:system|developer)\s+prompt|instructions?"
    r"|이전\s*지시|지시(?:를|문|사항)?\s*(?:무시|따라)|무조건|읽는\s*AI|AI\s*(?:는|가|에게|야)",
    re.IGNORECASE,
)


class Interpretation(BaseModel):
    """문장 해석 결과(견적 입력 설계 4.1). 이어서 말하면 이전 결과에 더해진다(`merge`)."""

    kinds: list[Kind] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    situations: list[str] = Field(default_factory=list)
    stated: dict[Kind, list[str]] = Field(default_factory=dict)      # 직접 말한 스펙 조건(종류 → 조건 이름)
    hand_size: HandSize | None = None
    budget: dict[Kind, int] = Field(default_factory=dict)            # 종류별 예산 상한(원)
    budget_total: int | None = None                                   # 여러 종류를 합친 예산(원)
    unrecognized: list[str] = Field(default_factory=list)


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

    def preference_prefs(self) -> list[dict[str, Any]]:
        return spec_rules.dedupe_prefs([p for c in self.preferences for p in c.prefs])

    def filter_prefs(self) -> list[dict[str, Any]]:
        return spec_rules.dedupe_prefs([p for c in self.filters for p in c.prefs])


def kinds_all_order(kinds: list[str]) -> list[str]:
    """화면과 결과에서 종류를 늘 같은 순서로 보여주기 위한 고정 순서."""
    order = ["monitor", "keyboard", "mouse", "speaker"]
    return [k for k in order if k in kinds]


def _unique(values) -> list:
    return list(dict.fromkeys(values))


def normalize_text(text: str) -> str:
    """같은 문장을 같은 열쇠로 보게 한다: 공백 정리, 소문자."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


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


def sanitize(raw: Any, rules: dict | None = None) -> Interpretation:
    """언어 모델이나 요청 바디의 dict 를 목록 안의 값만 남긴 `Interpretation` 으로 바꾼다.
    목록에 없는 값은 조용히 뺀다(만들어 넣지 않는다). 형식이 아예 맞지 않으면 빈 결과다."""
    rules = rules or load_peripheral_rules()
    data = raw if isinstance(raw, dict) else {}
    kinds_all = peripheral_kinds(rules)

    def _names(value: Any, allowed: set[str]) -> list[str]:
        return _unique(v for v in (value if isinstance(value, list) else []) if isinstance(v, str) and v in allowed)

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
        text = re.sub(r"\s+", " ", item).strip()[:UNRECOGNIZED_MAX_CHARS]
        if text and not looks_like_injected_instruction(text):
            unrecognized.append(text)

    sit_codes = set(situations(rules))
    purpose_hits = _names(data.get("purposes"), set(purpose_vocabulary(rules)) | sit_codes)
    return Interpretation(
        kinds=kinds,
        purposes=[c for c in purpose_hits if c not in sit_codes],
        situations=_unique([*_names(data.get("situations"), sit_codes), *(c for c in purpose_hits if c in sit_codes)]),
        stated=stated,
        hand_size=data.get("hand_size") if data.get("hand_size") in ("small", "medium", "large") else None,
        budget=budget,
        budget_total=_positive_won(data.get("budget_total")),
        unrecognized=_unique(unrecognized)[:UNRECOGNIZED_MAX_ITEMS],
    )


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
        unrecognized=_unique([*previous.unrecognized, *new.unrecognized])[:UNRECOGNIZED_MAX_ITEMS],
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

        def _condition(cond_id: str, src: list[str]) -> ResolvedCondition:
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
        words = [w for kind in kinds_all for w in purposes(kind, rules).get(code, {}).get("words", [])]
        if _contains_any(lowered, words):
            purpose_hits.append(code)
    situation_hits = [code for code, entry in situations(rules).items() if _contains_any(lowered, entry["words"])]

    stated: dict[str, list[str]] = {}
    scope = kinds or kinds_all          # 종류를 가리지 않은 말은 모든 종류에 적용한다
    for kind in scope:
        ids = [cid for cid, cond in spec_conditions(kind, rules).items() if _contains_any(lowered, cond["words"])]
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
    return Interpretation(
        kinds=[k for k in kinds],
        purposes=purpose_hits,
        situations=situation_hits,
        stated=stated,
        hand_size=hand,
        budget=budget,
        budget_total=budget_total,
    )

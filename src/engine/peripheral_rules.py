"""주변기기(모니터·키보드·마우스·스피커) 정의 로더 — 추천엔진 구현계획 §3.3 E8.

config/peripherals.yaml을 읽어 종류별 스펙 컬럼 매핑과 랭킹 가중치를 낸다.
stage2_requirement.py(PC 규칙 로더)와 같은 스타일로 로드 시 엄격 검증을 한다 — 잘못된
설정은 조용히 넘어가지 않고 즉시 PeripheralRuleError를 낸다.

requirements(E10)·verify(E12, 모니터↔PC 교차 검사)는 선택 절이고 있으면 여기서 검증한다.
hard_filters/preferences 는 이름만 예약돼 있고 실제 파일에는 없다(빈 자리를 만들지 않는다는 원칙).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.categories import load_category
from src.config import PERIPHERAL_RULES_PATH
from src.dto import PERIPHERAL_KINDS
from src.engine.peripheral_parse import PARSED_KEYS_BY_KIND

_PERIPHERAL_RULES_PATH = PERIPHERAL_RULES_PATH


class PeripheralRuleError(ValueError):
    """config/peripherals.yaml이 없거나 형식이 잘못됨."""


# 현재 필수 절. requirements(E10)·verify(E12)·parsing(E9)은 선택 절이다. hard_filters/preferences는
# 이름만 예약한다 — 파일에 없어도 되고, 있어도 최상위 키 오류가 나지 않는다.
# parsing 은 E9가 채운다(resolution_classes) — schema_version을 올리지 않고 기존 "알려진
# 선택 절" 자리를 그대로 쓴다(E8 테스트가 schema_version==1을 고정 기대하므로 건드리지 않는다).
_REQUIRED_TOP_KEYS = {"schema_version", "rule_set_version", "kinds", "ranking", "scoring"}
_KNOWN_TOP_KEYS = _REQUIRED_TOP_KEYS | {
    "requirements", "hard_filters", "preferences", "verify", "parsing",
    "spec_conditions", "purposes", "situations", "pc_purpose_map", "interpretation", "adjust_chips", "feel",
    "emphasis", "conflicts", "chat", "display",
}

_KINDS = PERIPHERAL_KINDS
_KIND_REQUIRED_KEYS = {"label", "product_type", "spec_table", "columns"}
# 스펙 기준(ranking.<kind>.criteria)과 별개로 모든 종류가 갖는 축. 가중치 축 = 스펙 기준 이름들 ∪ 이것들.
_FIXED_AXES = {"리뷰", "가격", "브랜드", "무상AS"}

# E10 — requirements 절 검증 상수.
_MONITOR_HARD_KEYS = {
    "resolution_class_by_res", "res_class_members",
    "refresh_min_hz_by_res", "refresh_min_hz_purpose_override",
}
# E11 이 읽을 선언형 평가기의 연산자 전체 집합(계획 §3.3 E10/E11).
SOFT_OPS = {"min", "max", "equals", "member_of", "contains_any"}

# [1]이 읽는 조건 이름. slot_schema에는 넣지 않는다(R-8 — 대화 노출은 범위 밖).
CONDITION_KEYS = ("peripherals", "peripheral_budget_max")


def _check_kind_def(kind: str, kdef: Any) -> None:
    if not isinstance(kdef, dict) or set(kdef) != _KIND_REQUIRED_KEYS:
        raise PeripheralRuleError(f"주변기기 종류 정의 키 오류: {kind}")
    if not isinstance(kdef["label"], str) or not kdef["label"].strip():
        raise PeripheralRuleError(f"주변기기 label 오류: {kind}")
    if not isinstance(kdef["product_type"], str) or not kdef["product_type"].strip():
        raise PeripheralRuleError(f"주변기기 product_type 오류: {kind}")
    if not isinstance(kdef["spec_table"], str) or not kdef["spec_table"].startswith("catalog."):
        raise PeripheralRuleError(f"주변기기 spec_table 오류: {kind}")
    columns = kdef["columns"]
    if not isinstance(columns, dict) or not columns:
        raise PeripheralRuleError(f"주변기기 columns 오류: {kind}")
    engine_keys: list[str] = []
    for db_col, engine_key in columns.items():
        if not isinstance(db_col, str) or not db_col.strip():
            raise PeripheralRuleError(f"주변기기 columns DB 컬럼명 오류: {kind}")
        if not isinstance(engine_key, str) or not engine_key.strip():
            raise PeripheralRuleError(f"주변기기 columns 엔진 키 오류: {kind}.{db_col}")
        engine_keys.append(engine_key)
    if len(engine_keys) != len(set(engine_keys)):
        raise PeripheralRuleError(f"주변기기 columns 엔진 키 중복: {kind}")


def _check_resolution_classes(value: Any) -> None:
    """parsing.resolution_classes — 해상도 (w,h) → 등급 이름 표(E9, peripheral_parse.py가 읽음).

    "OTHER"는 목록에 없는 해상도에 예약된 fallback 이름이라 등급 이름으로 쓸 수 없다
    (계획 §3.3 E9: "목록에 없으면 class 는 None이 아니라 OTHER"). 같은 (w,h) 가 두 등급에
    동시에 들어가면 분류가 모호해지므로 막는다.
    """
    if not isinstance(value, dict) or not value:
        raise PeripheralRuleError("주변기기 parsing.resolution_classes 형식 오류(빈 값)")
    seen: dict[tuple[int, int], str] = {}
    for name, pairs in value.items():
        if not isinstance(name, str) or not name.strip():
            raise PeripheralRuleError("주변기기 resolution_classes 등급 이름 오류")
        if name == "OTHER":
            raise PeripheralRuleError("주변기기 resolution_classes 등급 이름 'OTHER'는 예약어(미분류 fallback)")
        if not isinstance(pairs, list) or not pairs:
            raise PeripheralRuleError(f"주변기기 resolution_classes 값 오류: {name}")
        for pair in pairs:
            valid = (isinstance(pair, (list, tuple)) and len(pair) == 2
                     and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in pair))
            if not valid:
                raise PeripheralRuleError(f"주변기기 resolution_classes 좌표 오류: {name}={pair!r}")
            key = (int(pair[0]), int(pair[1]))
            if key in seen:
                raise PeripheralRuleError(
                    f"주변기기 resolution_classes 중복 해상도 {key}: {seen[key]} / {name}")
            seen[key] = name


def _check_parsing(data: Any) -> None:
    if not isinstance(data, dict) or set(data) != {"resolution_classes"}:
        raise PeripheralRuleError("주변기기 parsing 절 키 오류")
    _check_resolution_classes(data["resolution_classes"])


def _check_weights(kind: str, weights: Any, criteria: dict) -> None:
    axes = set(criteria) | _FIXED_AXES
    if not isinstance(weights, dict) or set(weights) != axes:
        raise PeripheralRuleError(f"주변기기 랭킹 가중치 축 오류: {kind} (기대: {sorted(axes)})")
    for axis, value in weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise PeripheralRuleError(f"주변기기 랭킹 가중치 음수/타입 오류: {kind}.{axis}")
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise PeripheralRuleError(f"주변기기 랭킹 가중치 합계가 1이 아님: {kind}")


def _check_criteria(kind: str, criteria: Any, allowed_keys: set[str]) -> None:
    """스펙 기준: 이름 → 스펙 키 목록. 키는 그 종류가 판정에 쓸 수 있는 키여야 하고 한 기준에만 속한다."""
    if not isinstance(criteria, dict) or not criteria:
        raise PeripheralRuleError(f"주변기기 ranking.{kind}.criteria 는 비어 있지 않은 표여야 함")
    seen: dict[str, str] = {}
    for name, keys in criteria.items():
        if not isinstance(name, str) or not name or name in _FIXED_AXES:
            raise PeripheralRuleError(f"주변기기 ranking.{kind}.criteria 이름 오류: {name!r}")
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
            raise PeripheralRuleError(f"주변기기 ranking.{kind}.criteria.{name} 는 스펙 키 목록이어야 함")
        for key in keys:
            if key not in allowed_keys:
                raise PeripheralRuleError(f"주변기기 ranking.{kind}.criteria.{name}: 판정에 쓸 수 없는 스펙 키 {key}")
            if key in seen:
                raise PeripheralRuleError(f"주변기기 ranking.{kind}: 스펙 키 {key} 가 두 기준({seen[key]}, {name})에 있음")
            seen[key] = name


_SCORING_KEYS = {
    "evidence_penalty", "evidence_min_n", "missing_key_penalty", "missing_key_penalty_max",
    "stated_criterion_boost", "emphasis_boost", "stated_pref_weight", "close_call_margin", "close_call_max_items",
    "price_weight_without_budget", "brand_like_weight", "review_spread_min_candidates", "review_spread_min_span", "review_unevidenced_quantile",
}


_EMPHASIS_AXES = {"가격", "리뷰", "무상AS"}


def _check_emphasis(data: dict) -> None:
    """강조 낱말·브랜드 표. 낱말은 소문자 문자열, 같은 낱말이 두 곳에 있으면 어느 쪽인지 알 수 없어 거절한다."""
    section = data.get("emphasis")
    if section is None:
        return
    if not isinstance(section, dict) or set(section) != {"words", "brand_avoid_words", "brands"}:
        raise PeripheralRuleError("주변기기 emphasis 절 키 오류(words·brand_avoid_words·brands)")
    words = section["words"]
    if not isinstance(words, dict) or not set(words) <= _EMPHASIS_AXES:
        raise PeripheralRuleError(f"주변기기 emphasis.words 축은 {sorted(_EMPHASIS_AXES)} 안이어야 함")
    seen: dict[str, str] = {}
    for axis, items in words.items():
        _check_word_list(f"emphasis.words.{axis}", items)
        for w in items:
            if w in seen:
                raise PeripheralRuleError(f"주변기기 emphasis.words 낱말 {w!r} 가 두 축({seen[w]}, {axis})에 있음")
            seen[w] = axis
    _check_word_list("emphasis.brand_avoid_words", section["brand_avoid_words"])
    brands = section["brands"]
    if not isinstance(brands, dict) or not brands:
        raise PeripheralRuleError("주변기기 emphasis.brands 는 비어 있지 않은 표여야 함")
    for brand, aliases in brands.items():
        if not isinstance(brand, str) or not brand.strip():
            raise PeripheralRuleError(f"주변기기 emphasis.brands 이름 오류: {brand!r}")
        _check_word_list(f"emphasis.brands.{brand}", aliases)


def _check_word_list(where: str, items: Any) -> None:
    if not isinstance(items, list) or not items or not all(isinstance(w, str) and w.strip() for w in items):
        raise PeripheralRuleError(f"주변기기 {where} 는 비어 있지 않은 낱말 목록이어야 함")
    if any(w != w.lower() for w in items):
        raise PeripheralRuleError(f"주변기기 {where} 의 낱말은 소문자여야 함(문장을 소문자로 바꿔 비교한다)")


def _check_criteria_cover_conditions(data: dict) -> None:
    """spec_conditions 의 조건이 겨냥하는 스펙 키는 모두 그 종류의 어떤 스펙 기준에 속해야 한다 — 아니면 그 조건은 순위에
    반영되지 않는다(조용히 빠진다)."""
    for kind, conds in (data.get("spec_conditions") or {}).items():
        covered = {key for keys in data["ranking"][kind]["criteria"].values() for key in keys}
        for cond_id, cond in (conds or {}).items():
            for pref in cond.get("prefs") or []:
                if pref["key"] not in covered:
                    raise PeripheralRuleError(
                        f"주변기기 spec_conditions.{kind}.{cond_id}: 스펙 키 {pref['key']} 가 어떤 ranking 스펙 기준에도 없음")


def _check_scoring(data: Any) -> None:
    if not isinstance(data, dict) or set(data) != _SCORING_KEYS:
        raise PeripheralRuleError(f"주변기기 scoring 절 키 오류(기대: {sorted(_SCORING_KEYS)})")
    for key, value in data.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise PeripheralRuleError(f"주변기기 scoring.{key} 는 0 이상의 숫자여야 함")
    if data["evidence_min_n"] <= 0:
        raise PeripheralRuleError("주변기기 scoring.evidence_min_n 은 0보다 커야 함")
    if data["stated_criterion_boost"] < 1 or data["emphasis_boost"] < 1:
        raise PeripheralRuleError("주변기기 scoring 의 배수는 1 이상이어야 함")
    if data["price_weight_without_budget"] > 1 or data["review_unevidenced_quantile"] > 1:
        raise PeripheralRuleError("주변기기 scoring.price_weight_without_budget·review_unevidenced_quantile 은 1 이하여야 함")


# ── E10 — requirements 절 검증 ────────────────────────────────────────────
def _condition_schema() -> dict:
    """조건 키·enum 값 대조표(computer.yaml slot_schema). requirements.monitor.hard 와 pc_purpose_map 이
    가리키는 PC 조건 이름·값은 반드시 여기 있어야 한다(§3.3 E10: "조건 키 이름·enum 값은 computer.yaml
    slot_schema와 일치해야 한다")."""
    return load_category("computer")["slot_schema"]


def _allowed_spec_keys(kind: str, rules: dict) -> set[str]:
    """kind 가 판정에 쓸 수 있는 spec 키 전체 = columns 의 엔진 키(원문 컬럼 포함) ∪
    peripheral_parse.PARSED_KEYS_BY_KIND(파서 산출 키). spec_conditions.*.*.prefs[].key 는
    이 안에 있어야 한다(§3.3 E10: "판정용 spec 키는 E9 파서/columns가 실제로 만드는 키만")."""
    columns = kind_def(kind, rules)["columns"]
    return set(columns.values()) | set(PARSED_KEYS_BY_KIND.get(kind, ()))


def _check_pref(kind: str, pref: Any, allowed_keys: set[str]) -> None:
    if not isinstance(pref, dict) or set(pref) != {"key", "op", "value"}:
        raise PeripheralRuleError(f"주변기기 평가 조건 항목 키 오류: {kind}")
    key, op, value = pref["key"], pref["op"], pref["value"]
    if not isinstance(key, str) or key not in allowed_keys:
        raise PeripheralRuleError(f"주변기기 평가 조건 판정 키 오류(알 수 없는 spec 키): {kind}.{key}")
    if op not in SOFT_OPS:
        raise PeripheralRuleError(f"주변기기 평가 조건 연산자 오류: {kind}.{key}.{op}")
    if op in ("min", "max"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PeripheralRuleError(f"주변기기 평가 조건 {op} 값은 숫자여야 함: {kind}.{key}")
    elif op in ("member_of", "contains_any"):
        if not isinstance(value, list) or not value:
            raise PeripheralRuleError(f"주변기기 평가 조건 {op} 값은 비지 않은 목록이어야 함: {kind}.{key}")


def _check_monitor_hard(hard: Any, rules: dict) -> None:
    """monitor.hard 전용 검증. resolution_class_by_res/refresh_min_hz_by_res 등은 일반
    {key,op,value} 평가기 형식이 아니라 E11 이 고정 의미로 읽는 표다(§3.3 E10 표) — 그래서
    _check_soft 와 다른 전용 검증을 쓴다."""
    if not isinstance(hard, dict) or not hard or set(hard) - _MONITOR_HARD_KEYS:
        raise PeripheralRuleError("주변기기 요구사양 monitor.hard 절 키 오류")
    schema = _condition_schema()
    res_values = set(schema["resolution"]["values"])
    purpose_values = set(schema["purpose"]["values"])
    classes = set(resolution_classes(rules))

    by_res = hard.get("resolution_class_by_res")
    if by_res is not None:
        if not isinstance(by_res, dict) or not by_res or set(by_res) - res_values:
            raise PeripheralRuleError("주변기기 요구사양 monitor.resolution_class_by_res 키 오류")
        if any(not isinstance(v, str) or v not in classes for v in by_res.values()):
            raise PeripheralRuleError("주변기기 요구사양 monitor.resolution_class_by_res 값 오류(알 수 없는 등급)")

    members = hard.get("res_class_members")
    if members is not None:
        if not isinstance(members, dict) or not members or set(members) - classes:
            raise PeripheralRuleError("주변기기 요구사양 monitor.res_class_members 키 오류")
        for cls, lst in members.items():
            if not isinstance(lst, list) or not lst or any(v not in classes for v in lst):
                raise PeripheralRuleError(f"주변기기 요구사양 monitor.res_class_members 값 오류: {cls}")

    def _check_positive_number_table(table: Any, name: str) -> None:
        if not isinstance(table, dict) or not table or set(table) - res_values:
            raise PeripheralRuleError(f"주변기기 요구사양 monitor.{name} 키 오류")
        for value in table.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise PeripheralRuleError(f"주변기기 요구사양 monitor.{name} 값 오류(양수 숫자 아님)")

    refresh = hard.get("refresh_min_hz_by_res")
    if refresh is not None:
        _check_positive_number_table(refresh, "refresh_min_hz_by_res")

    override = hard.get("refresh_min_hz_purpose_override")
    if override is not None:
        if not isinstance(override, dict) or not override or set(override) - res_values:
            raise PeripheralRuleError("주변기기 요구사양 monitor.refresh_min_hz_purpose_override 키 오류")
        for res, table in override.items():
            if not isinstance(table, dict) or not table or set(table) - purpose_values:
                raise PeripheralRuleError(f"주변기기 요구사양 monitor.refresh_min_hz_purpose_override 오류: {res}")
            for value in table.values():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                    raise PeripheralRuleError(
                        f"주변기기 요구사양 monitor.refresh_min_hz_purpose_override 값 오류: {res}")


def _check_requirements(data: dict) -> None:
    """requirements 절(선택) 검증. 하드 조건은 monitor 에만 있다(PC 견적과의 호환). 키보드·마우스·스피커의
    선호는 spec_conditions·purposes 가 맡는다. 없으면 통과한다."""
    requirements = data.get("requirements")
    if requirements is None:
        return
    if not isinstance(requirements, dict) or set(requirements) != {"monitor"}:
        raise PeripheralRuleError("주변기기 requirements 는 monitor 하나만 둘 수 있음")
    kdef = requirements["monitor"]
    if not isinstance(kdef, dict) or set(kdef) != {"hard"}:
        raise PeripheralRuleError("주변기기 requirements.monitor 절 키 오류(hard 만 허용)")
    _check_monitor_hard(kdef["hard"], data)


# ── 견적 입력(spec_conditions · purposes · situations · pc_purpose_map · interpretation) ──────────────
_LABEL_MSG = "주변기기 {where} label 오류"


def _check_name_list(where: str, value: Any, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise PeripheralRuleError(f"주변기기 {where} 는 문자열 목록이어야 함")
    if any(not isinstance(v, str) or not v.strip() for v in value) or len(set(value)) != len(value):
        raise PeripheralRuleError(f"주변기기 {where} 항목 오류(빈 문자열 또는 중복)")
    return value


_SPEC_CONDITION_KEYS = {"label", "words", "filter", "prefs", "exclude", "near"}
_PURPOSE_KEYS = {"label", "words", "prefer", "feel", "taste", "exclude"}


def _check_word_extras(where: str, entry: dict) -> None:
    """낱말 규칙의 선택 항목. exclude — 이 낱말이 문장에 있으면 그 부분을 지우고 words 를 본다("텐키리스" 안의 "텐키").
    near — feel 낱말과 target 낱말이 순서와 관계없이 window 글자 안에 함께 나오면 이 항목으로 읽는다("타건감이 묵직한")."""
    if "exclude" in entry:
        _check_name_list(f"{where}.exclude", entry["exclude"], allow_empty=False)
    if "near" in entry:
        rules = entry["near"]
        if not isinstance(rules, list) or not rules:
            raise PeripheralRuleError(f"주변기기 {where}.near 는 비지 않은 목록이어야 함")
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict) or set(rule) != {"feel", "target", "window"}:
                raise PeripheralRuleError(f"주변기기 {where}.near[{i}] 키 오류(feel, target, window)")
            _check_name_list(f"{where}.near[{i}].feel", rule["feel"], allow_empty=False)
            _check_name_list(f"{where}.near[{i}].target", rule["target"], allow_empty=False)
            window = rule["window"]
            if isinstance(window, bool) or not isinstance(window, int) or not 0 < window <= 30:
                raise PeripheralRuleError(f"주변기기 {where}.near[{i}].window 는 1~30 정수여야 함")


def _check_conflicts(data: dict) -> None:
    """함께 있을 수 없는 스펙 조건 쌍(종류별). 풀이(`peripheral_intent.resolve`)가 둘 다 풀리면 하나만 남기거나 둘 다 뺀다."""
    section = data.get("conflicts")
    if section is None:
        return
    if not isinstance(section, dict) or not set(section) <= set(_KINDS):
        raise PeripheralRuleError(f"주변기기 conflicts 는 {_KINDS} 중 종류를 열쇠로 가져야 함")
    for kind, pairs in section.items():
        known = set((data.get("spec_conditions") or {}).get(kind, {}))
        if not isinstance(pairs, list) or not pairs:
            raise PeripheralRuleError(f"주변기기 conflicts.{kind} 는 비지 않은 목록이어야 함")
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2 or len(set(pair)) != 2 or not set(pair) <= known:
                raise PeripheralRuleError(f"주변기기 conflicts.{kind} 항목은 spec_conditions 이름 두 개여야 함: {pair}")


def _check_spec_conditions(data: dict) -> None:
    section = data.get("spec_conditions")
    if section is None:
        return
    if not isinstance(section, dict) or set(section) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 spec_conditions 는 정확히 {_KINDS} 네 종류여야 함")
    for kind, conditions in section.items():
        if not isinstance(conditions, dict) or not conditions:
            raise PeripheralRuleError(f"주변기기 spec_conditions.{kind} 는 비지 않은 표여야 함")
        allowed_keys = _allowed_spec_keys(kind, data)
        for cond_id, cond in conditions.items():
            where = f"spec_conditions.{kind}.{cond_id}"
            if not isinstance(cond, dict) or not ({"label", "words", "filter", "prefs"} <= set(cond) <= _SPEC_CONDITION_KEYS):
                raise PeripheralRuleError(f"주변기기 {where} 키 오류(label, words, filter, prefs + 선택 exclude, near)")
            _check_name_list(f"{where}.words", cond["words"], allow_empty=False)
            _check_word_extras(where, cond)
            if not isinstance(cond["label"], str) or not cond["label"].strip():
                raise PeripheralRuleError(_LABEL_MSG.format(where=where))
            if not isinstance(cond["filter"], bool):
                raise PeripheralRuleError(f"주변기기 {where}.filter 는 true/false 여야 함")
            prefs = cond["prefs"]
            if not isinstance(prefs, list) or not prefs:
                raise PeripheralRuleError(f"주변기기 {where}.prefs 오류(빈 목록)")
            for pref in prefs:
                _check_pref(kind, pref, allowed_keys)


def _check_purposes(data: dict) -> None:
    section = data.get("purposes")
    if section is None:
        return
    if "spec_conditions" not in data:
        raise PeripheralRuleError("주변기기 purposes 는 spec_conditions 절이 있어야 함")
    if not isinstance(section, dict) or set(section) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 purposes 는 정확히 {_KINDS} 네 종류여야 함")
    for kind, purposes in section.items():
        if not isinstance(purposes, dict) or not purposes:
            raise PeripheralRuleError(f"주변기기 purposes.{kind} 는 비지 않은 표여야 함")
        known = set(data["spec_conditions"][kind])
        for code, entry in purposes.items():
            where = f"purposes.{kind}.{code}"
            if not isinstance(entry, dict) or not ({"label", "words", "prefer", "feel", "taste"} <= set(entry) <= _PURPOSE_KEYS):
                raise PeripheralRuleError(f"주변기기 {where} 키 오류(label, words, prefer, feel, taste + 선택 exclude)")
            _check_word_extras(where, entry)
            if not isinstance(entry["label"], str) or not entry["label"].strip():
                raise PeripheralRuleError(_LABEL_MSG.format(where=where))
            _check_name_list(f"{where}.words", entry["words"], allow_empty=False)
            prefer = _check_name_list(f"{where}.prefer", entry["prefer"], allow_empty=True)
            unknown = [c for c in prefer if c not in known]
            if unknown:
                raise PeripheralRuleError(f"주변기기 {where}.prefer 에 spec_conditions 에 없는 이름: {unknown}")
            _check_name_list(f"{where}.feel", entry["feel"], allow_empty=True)
            _check_name_list(f"{where}.taste", entry["taste"], allow_empty=True)


def _check_situations(data: dict) -> None:
    section = data.get("situations")
    if section is None:
        return
    if not isinstance(section, dict) or not section:
        raise PeripheralRuleError("주변기기 situations 는 비지 않은 표여야 함")
    for code, entry in section.items():
        where = f"situations.{code}"
        keys = set(entry) if isinstance(entry, dict) else set()
        if not {"label", "words", "same_condition_group"} <= keys <= {"label", "words", "same_condition_group", "exclude"}:
            raise PeripheralRuleError(f"주변기기 {where} 키 오류(label, words, same_condition_group + 선택 exclude)")
        if not isinstance(entry["label"], str) or not entry["label"].strip():
            raise PeripheralRuleError(_LABEL_MSG.format(where=where))
        _check_name_list(f"{where}.words", entry["words"], allow_empty=False)
        if not isinstance(entry["same_condition_group"], bool):
            raise PeripheralRuleError(f"주변기기 {where}.same_condition_group 은 true/false 여야 함")
        if "exclude" in entry:
            _check_name_list(f"{where}.exclude", entry["exclude"], allow_empty=False)


def _all_purpose_codes(data: dict) -> set[str]:
    return {code for kind_table in (data.get("purposes") or {}).values() for code in kind_table}


def _check_pc_purpose_map(data: dict) -> None:
    section = data.get("pc_purpose_map")
    if section is None:
        return
    if "purposes" not in data:
        raise PeripheralRuleError("주변기기 pc_purpose_map 은 purposes 절이 있어야 함")
    pc_values = set(_condition_schema()["purpose"]["values"])
    known = _all_purpose_codes(data)
    if not isinstance(section, dict) or not section or set(section) - pc_values:
        raise PeripheralRuleError("주변기기 pc_purpose_map 키 오류(PC 견적 용도에 없는 값)")
    for pc_purpose, codes in section.items():
        names = _check_name_list(f"pc_purpose_map.{pc_purpose}", codes, allow_empty=False)
        unknown = [c for c in names if c not in known]
        if unknown:
            raise PeripheralRuleError(f"주변기기 pc_purpose_map.{pc_purpose} 에 purposes 에 없는 이름: {unknown}")


def _check_adjust_chips(data: dict) -> None:
    section = data.get("adjust_chips")
    if section is None:
        return
    if "purposes" not in data or "situations" not in data:
        raise PeripheralRuleError("주변기기 adjust_chips 는 purposes·situations 절이 있어야 함")
    if not isinstance(section, dict) or not section or set(section) - set(_KINDS):
        raise PeripheralRuleError("주변기기 adjust_chips 종류 키 오류")
    for kind, chips in section.items():
        if not isinstance(chips, list) or not chips:
            raise PeripheralRuleError(f"주변기기 adjust_chips.{kind} 는 비지 않은 목록이어야 함")
        seen: set[str] = set()
        for chip in chips:
            where = f"adjust_chips.{kind}"
            if not isinstance(chip, dict) or set(chip) != {"id", "label", "add"}:
                raise PeripheralRuleError(f"주변기기 {where} 항목 키 오류(id, label, add)")
            if not isinstance(chip["id"], str) or not chip["id"] or chip["id"] in seen:
                raise PeripheralRuleError(f"주변기기 {where} id 오류(빈 값 또는 중복)")
            seen.add(chip["id"])
            if not isinstance(chip["label"], str) or not chip["label"].strip():
                raise PeripheralRuleError(_LABEL_MSG.format(where=f"{where}.{chip['id']}"))
            add = chip["add"]
            if not isinstance(add, dict) or not add or set(add) - {"purposes", "situations", "stated"}:
                raise PeripheralRuleError(f"주변기기 {where}.{chip['id']}.add 키 오류")
            purposes_ok = set(data["purposes"][kind])
            situations_ok = set(data["situations"])
            allowed = {"purposes": purposes_ok, "situations": situations_ok,
                       "stated": set(data["spec_conditions"][kind])}
            for key, names in add.items():
                listed = _check_name_list(f"{where}.{chip['id']}.add.{key}", names, allow_empty=False)
                unknown = [n for n in listed if n not in allowed[key]]
                if unknown:
                    raise PeripheralRuleError(f"주변기기 {where}.{chip['id']}.add.{key} 에 목록에 없는 이름: {unknown}")


_FEEL_SCALARS = {
    "k", "kb", "k0_default", "default_m", "purpose_boost", "split_ratio", "neutral_taste",
    "durability_min_months", "hand_small_below_cm", "hand_large_above_cm",
    "same_condition_many", "recent_months", "trending_margin", "quotes_per_attribute", "rrf_k", "search_limit",
    "post_max_chars", "post_max_items", "quote_similarity_max",
}
_FEEL_GROUPS = {"hand", "quiet", "bright", "none", "purpose"}
_FEEL_TYPES = {"rating", "taste"}
_FEEL_TAGS = {"sound"}
_FEEL_ONLY_WHEN = {"design"}


def _check_feel(data: dict) -> None:
    feel = data.get("feel")
    if feel is None:
        return
    if "purposes" not in data:
        raise PeripheralRuleError("주변기기 feel 은 purposes 절이 있어야 함")
    if not isinstance(feel, dict) or set(feel) != _FEEL_SCALARS | {"k0", "attributes"}:
        raise PeripheralRuleError(f"주변기기 feel 키 오류: {sorted(_FEEL_SCALARS | {'k0', 'attributes'})}")
    for key in _FEEL_SCALARS:
        value = feel[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise PeripheralRuleError(f"주변기기 feel.{key} 는 양수여야 함")
    for key in ("default_m", "split_ratio", "neutral_taste", "trending_margin", "quote_similarity_max"):
        if not 0 < feel[key] < 1:
            raise PeripheralRuleError(f"주변기기 feel.{key} 는 0과 1 사이여야 함")
    if feel["purpose_boost"] < 1:
        raise PeripheralRuleError("주변기기 feel.purpose_boost 는 1 이상이어야 함")
    if feel["hand_small_below_cm"] >= feel["hand_large_above_cm"]:
        raise PeripheralRuleError("주변기기 feel.hand_small_below_cm 는 hand_large_above_cm 보다 작아야 함")

    attributes = feel["attributes"]
    if not isinstance(attributes, dict) or set(attributes) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 feel.attributes 는 정확히 {_KINDS} 네 종류여야 함")
    k0 = feel["k0"]
    if not isinstance(k0, dict) or set(k0) - set(_KINDS):
        raise PeripheralRuleError("주변기기 feel.k0 종류 키 오류")
    for kind, table in k0.items():
        if not isinstance(table, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0 for v in table.values()
        ):
            raise PeripheralRuleError(f"주변기기 feel.k0.{kind} 값은 양수여야 함")

    for kind, table in attributes.items():
        if not isinstance(table, dict) or not table:
            raise PeripheralRuleError(f"주변기기 feel.attributes.{kind} 는 비지 않은 표여야 함")
        for code, entry in table.items():
            where = f"feel.attributes.{kind}.{code}"
            if not isinstance(entry, dict):
                raise PeripheralRuleError(f"주변기기 {where} 형식 오류")
            required = {"label", "type", "group", "aliases"} | ({"external"} if entry.get("type") == "rating" else {"sides", "taste_labels"})
            optional = {"tags", "only_when"}
            if not required <= set(entry) or set(entry) - required - optional:
                raise PeripheralRuleError(f"주변기기 {where} 키 오류(필수 {sorted(required)})")
            if not isinstance(entry["label"], str) or not entry["label"].strip():
                raise PeripheralRuleError(_LABEL_MSG.format(where=where))
            if entry["type"] not in _FEEL_TYPES or entry["group"] not in _FEEL_GROUPS:
                raise PeripheralRuleError(f"주변기기 {where} type/group 값 오류")
            _check_name_list(f"{where}.aliases", entry["aliases"], allow_empty=True)
            if set(entry.get("tags", [])) - _FEEL_TAGS:
                raise PeripheralRuleError(f"주변기기 {where}.tags 값 오류")
            if "only_when" in entry and entry["only_when"] not in _FEEL_ONLY_WHEN:
                raise PeripheralRuleError(f"주변기기 {where}.only_when 값 오류")
            if entry["type"] == "rating":
                if entry["external"] is not None and not isinstance(entry["external"], str):
                    raise PeripheralRuleError(f"주변기기 {where}.external 형식 오류")
            else:
                sides = entry["sides"]
                if not isinstance(sides, dict) or len(sides) != 2 or any(
                    not isinstance(v, str) or not v for v in sides.values()
                ):
                    raise PeripheralRuleError(f"주변기기 {where}.sides 는 쪽 두 개여야 함")
                labels = entry["taste_labels"]
                if not isinstance(labels, dict) or any(v not in sides for v in labels.values()):
                    raise PeripheralRuleError(f"주변기기 {where}.taste_labels 가 sides 에 없는 쪽을 가리킴")


_INTERPRETATION_KEYS = {"max_chars", "cache_size", "per_minute"}


def _check_interpretation(data: dict) -> None:
    section = data.get("interpretation")
    if section is None:
        return
    if not isinstance(section, dict) or set(section) != _INTERPRETATION_KEYS:
        raise PeripheralRuleError(f"주변기기 interpretation 키 오류: {sorted(_INTERPRETATION_KEYS)}")
    for key, value in section.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PeripheralRuleError(f"주변기기 interpretation.{key} 는 양의 정수여야 함")


_CHAT_KEYS = {"markers", "request_words", "types", "spec_topics", "spec_summary", "review_topics",
              "glossary", "unsupported", "answers", "examples", "chips", "commands"}
_CHAT_COMMANDS = {"reset", "remove", "swap", "cheaper", "budget_words"}
_CHAT_TYPES = ("term", "compat", "capabilities", "conditions", "compare", "why", "spec", "review")
_CHAT_ANSWERS = {"capabilities", "other", "no_result", "no_kind", "no_pc", "no_cross_check", "nothing_no_kind", "nothing_with_kind"}


def _text(where: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PeripheralRuleError(f"주변기기 {where} 는 비지 않은 문자열이어야 함")
    return value



_DISPLAY_KEYS = {"key_specs", "axis_labels", "requested_labels", "requested_feel"}
_KEY_SPEC_SOURCES = {"spec", "parts", "flags"}


def _check_display(data: dict) -> None:
    """display 절(결과 화면 표시 값) 검증: 가중치 축을 모두 덮는지, 속성·조건 이름이 실제 있는 것인지."""
    section = data.get("display")
    if section is None:
        return
    if not isinstance(section, dict) or set(section) != _DISPLAY_KEYS:
        raise PeripheralRuleError(f"주변기기 display 절 키 오류: {sorted(_DISPLAY_KEYS)}")
    key_specs = section["key_specs"]
    if not isinstance(key_specs, dict) or set(key_specs) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 display.key_specs 는 정확히 {_KINDS} 네 종류여야 함")
    for kind, entries in key_specs.items():
        if not isinstance(entries, list) or not entries:
            raise PeripheralRuleError(f"주변기기 display.key_specs.{kind} 는 비지 않은 목록이어야 함")
        seen: set[str] = set()
        for entry in entries:
            if (not isinstance(entry, dict) or not {"key", "label"} <= set(entry)
                    or len(_KEY_SPEC_SOURCES & set(entry)) != 1
                    or set(entry) - {"key", "label", "unit", "sep"} - _KEY_SPEC_SOURCES):
                raise PeripheralRuleError(f"주변기기 display.key_specs.{kind} 항목 모양 오류: {entry}")
            if entry["key"] in seen:
                raise PeripheralRuleError(f"주변기기 display.key_specs.{kind} 키 중복: {entry['key']}")
            seen.add(entry["key"])
            if "parts" in entry and not (isinstance(entry["parts"], list) and entry["parts"]):
                raise PeripheralRuleError(f"주변기기 display.key_specs.{kind}.{entry['key']}.parts 는 비지 않은 목록이어야 함")
            if "flags" in entry and not (isinstance(entry["flags"], dict) and entry["flags"]):
                raise PeripheralRuleError(f"주변기기 display.key_specs.{kind}.{entry['key']}.flags 는 비지 않은 표여야 함")
    labels = section["axis_labels"]
    for kind in _KINDS:
        axes = set((data.get("ranking") or {}).get(kind, {}).get("weights", {}))
        missing = axes - set(labels)
        if missing:
            raise PeripheralRuleError(f"주변기기 display.axis_labels 에 없는 {kind} 축: {sorted(missing)}")
    if not isinstance(section["requested_labels"], dict):
        raise PeripheralRuleError("주변기기 display.requested_labels 는 표여야 함")
    requested_feel = section["requested_feel"]
    if not isinstance(requested_feel, dict) or set(requested_feel) - set(_KINDS):
        raise PeripheralRuleError("주변기기 display.requested_feel 종류 키 오류")
    for kind, table in requested_feel.items():
        conds = set((data.get("spec_conditions") or {}).get(kind, {}))
        codes = set(feel_attributes(kind, data)) if "feel" in data else set()
        for cond_id, attr_codes in table.items():
            if cond_id not in conds:
                raise PeripheralRuleError(f"주변기기 display.requested_feel.{kind} 에 없는 조건: {cond_id}")
            unknown = [c for c in attr_codes if c not in codes]
            if "feel" in data and unknown:
                raise PeripheralRuleError(f"주변기기 display.requested_feel.{kind}.{cond_id} 에 없는 속성: {unknown}")


def _check_chat(data: dict) -> None:
    """chat 절(질문 답변) 검증: 스펙 키·체감 속성 코드·질문 종류가 실제 있는 이름인지, 낱말 목록·문구가 비지 않았는지."""
    section = data.get("chat")
    if section is None:
        return
    if not isinstance(section, dict) or set(section) != _CHAT_KEYS:
        raise PeripheralRuleError(f"주변기기 chat 절 키 오류: {sorted(_CHAT_KEYS)}")
    _check_name_list("chat.markers", section["markers"], allow_empty=False)
    commands = section["commands"]
    if not isinstance(commands, dict) or set(commands) != _CHAT_COMMANDS:
        raise PeripheralRuleError(f"주변기기 chat.commands 키 오류: {sorted(_CHAT_COMMANDS)}")
    for name, words in commands.items():
        _check_name_list(f"chat.commands.{name}", words, allow_empty=False)
    _check_name_list("chat.request_words", section["request_words"], allow_empty=False)

    types = section["types"]
    if not isinstance(types, dict) or set(types) != set(_CHAT_TYPES):
        raise PeripheralRuleError(f"주변기기 chat.types 는 정확히 {_CHAT_TYPES} 여야 함")
    for name, entry in types.items():
        if not isinstance(entry, dict) or set(entry) != {"words"}:
            raise PeripheralRuleError(f"주변기기 chat.types.{name} 키 오류(words)")
        _check_name_list(f"chat.types.{name}.words", entry["words"], allow_empty=False)

    spec_keys = set().union(*(_allowed_spec_keys(kind, data) for kind in _KINDS))
    topics = section["spec_topics"]
    if not isinstance(topics, dict) or not topics:
        raise PeripheralRuleError("주변기기 chat.spec_topics 는 비지 않은 표여야 함")
    for name, entry in topics.items():
        where = f"chat.spec_topics.{name}"
        if not isinstance(entry, dict) or not {"label", "words", "keys"} <= set(entry) <= {"label", "words", "keys", "unit"}:
            raise PeripheralRuleError(f"주변기기 {where} 키 오류(label, words, keys + 선택 unit)")
        _text(f"{where}.label", entry["label"])
        _check_name_list(f"{where}.words", entry["words"], allow_empty=False)
        unknown = [k for k in _check_name_list(f"{where}.keys", entry["keys"], allow_empty=False) if k not in spec_keys]
        if unknown:
            raise PeripheralRuleError(f"주변기기 {where}.keys 에 알 수 없는 spec 키: {unknown}")
    summary = section["spec_summary"]
    if not isinstance(summary, dict) or set(summary) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 chat.spec_summary 는 정확히 {_KINDS} 여야 함")
    for kind, names in summary.items():
        unknown = [n for n in _check_name_list(f"chat.spec_summary.{kind}", names, allow_empty=False) if n not in topics]
        if unknown:
            raise PeripheralRuleError(f"주변기기 chat.spec_summary.{kind} 에 spec_topics 에 없는 이름: {unknown}")

    feel_codes = {code for kind in _KINDS for code in feel_attributes(kind, data) } if "feel" in data else set()
    reviews = section["review_topics"]
    if not isinstance(reviews, dict) or not reviews:
        raise PeripheralRuleError("주변기기 chat.review_topics 는 비지 않은 표여야 함")
    for name, entry in reviews.items():
        where = f"chat.review_topics.{name}"
        if not isinstance(entry, dict) or set(entry) != {"label", "words", "attributes"}:
            raise PeripheralRuleError(f"주변기기 {where} 키 오류(label, words, attributes)")
        _text(f"{where}.label", entry["label"])
        _check_name_list(f"{where}.words", entry["words"], allow_empty=False)
        unknown = [c for c in _check_name_list(f"{where}.attributes", entry["attributes"], allow_empty=False)
                   if feel_codes and c not in feel_codes]
        if unknown:
            raise PeripheralRuleError(f"주변기기 {where}.attributes 에 feel.attributes 에 없는 코드: {unknown}")

    glossary = section["glossary"]
    if not isinstance(glossary, dict) or not glossary:
        raise PeripheralRuleError("주변기기 chat.glossary 는 비지 않은 표여야 함")
    for term, entry in glossary.items():
        where = f"chat.glossary.{term}"
        if not isinstance(entry, dict) or set(entry) != {"words", "text"}:
            raise PeripheralRuleError(f"주변기기 {where} 키 오류(words, text)")
        _check_name_list(f"{where}.words", entry["words"], allow_empty=False)
        _text(f"{where}.text", entry["text"])

    unsupported = section["unsupported"]
    if not isinstance(unsupported, list) or not unsupported:
        raise PeripheralRuleError("주변기기 chat.unsupported 는 비지 않은 목록이어야 함")
    for i, entry in enumerate(unsupported):
        if not isinstance(entry, dict) or set(entry) != {"words", "text"}:
            raise PeripheralRuleError(f"주변기기 chat.unsupported[{i}] 키 오류(words, text)")
        _check_name_list(f"chat.unsupported[{i}].words", entry["words"], allow_empty=False)
        _text(f"chat.unsupported[{i}].text", entry["text"])

    answers = section["answers"]
    if not isinstance(answers, dict) or set(answers) != _CHAT_ANSWERS:
        raise PeripheralRuleError(f"주변기기 chat.answers 키 오류: {sorted(_CHAT_ANSWERS)}")
    for name, text in answers.items():
        _text(f"chat.answers.{name}", text)

    examples = section["examples"]
    if not isinstance(examples, dict) or set(examples) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 chat.examples 는 정확히 {_KINDS} 여야 함")
    for kind, text in examples.items():
        _text(f"chat.examples.{kind}", text)

    chips = section["chips"]
    if not isinstance(chips, dict) or set(chips) != {"start", "after_result"}:
        raise PeripheralRuleError("주변기기 chat.chips 키 오류(start, after_result)")
    for name, items in chips.items():
        _check_name_list(f"chat.chips.{name}", items, allow_empty=False)


_VERIFY_GPU_KEYS = {"hdmi_version", "hdmi_ports", "dp_version", "dp_ports", "usb_c_video_out"}
_PORT_INTERFACES = {"hdmi", "dp"}


def _check_verify(verify: Any) -> None:
    """verify 절(E12) 검증. port_modes 의 등급 이름은 parsing.resolution_classes 와 같은 이름을
    쓰지만 모든 등급을 다 적을 필요는 없다 — 표에 없는 등급은 교차 검사에서 Pending이다."""
    if not isinstance(verify, dict) or set(verify) != {"gpu_keys", "port_modes"}:
        raise PeripheralRuleError("주변기기 verify 절 키 오류(gpu_keys, port_modes 필요)")
    gpu_keys = verify["gpu_keys"]
    if not isinstance(gpu_keys, dict) or set(gpu_keys) != _VERIFY_GPU_KEYS:
        raise PeripheralRuleError(f"주변기기 verify.gpu_keys 는 정확히 {sorted(_VERIFY_GPU_KEYS)} 여야 함")
    if any(not isinstance(v, str) or not v for v in gpu_keys.values()):
        raise PeripheralRuleError("주변기기 verify.gpu_keys 값 오류(빈 문자열)")
    modes = verify["port_modes"]
    if not isinstance(modes, dict) or not modes or set(modes) - _PORT_INTERFACES:
        raise PeripheralRuleError(f"주변기기 verify.port_modes 는 {sorted(_PORT_INTERFACES)} 만 허용")
    for iface, table in modes.items():
        if not isinstance(table, dict) or not table:
            raise PeripheralRuleError(f"주변기기 verify.port_modes.{iface} 오류(빈 표)")
        for version, row in table.items():
            try:
                major, minor = str(version).split(".")
                int(major), int(minor)
            except ValueError:
                raise PeripheralRuleError(
                    f"주변기기 verify.port_modes.{iface} 버전 형식 오류(주.부 문자열): {version!r}") from None
            if not isinstance(row, dict) or not row:
                raise PeripheralRuleError(f"주변기기 verify.port_modes.{iface}.{version} 오류(빈 행)")
            for hz in row.values():
                if isinstance(hz, bool) or not isinstance(hz, (int, float)) or hz <= 0:
                    raise PeripheralRuleError(f"주변기기 verify.port_modes.{iface}.{version} 값 오류(양수 아님)")


@lru_cache(maxsize=8)
def _load_peripheral_rules(path: Path) -> dict:
    if not path.is_file():
        raise PeripheralRuleError(f"주변기기 규칙 파일 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PeripheralRuleError("주변기기 규칙 파일 형식 오류")
    unknown = set(data) - _KNOWN_TOP_KEYS
    if unknown:
        raise PeripheralRuleError(f"주변기기 규칙 알 수 없는 최상위 키: {sorted(unknown)}")
    missing = _REQUIRED_TOP_KEYS - set(data)
    if missing:
        raise PeripheralRuleError(f"주변기기 규칙 필수 절 누락: {sorted(missing)}")
    if data["schema_version"] != 1:
        raise PeripheralRuleError("주변기기 규칙 schema_version 오류")
    if not data.get("rule_set_version"):
        raise PeripheralRuleError("주변기기 규칙 rule_set_version 없음")

    kinds = data["kinds"]
    if not isinstance(kinds, dict) or set(kinds) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 kinds는 정확히 {_KINDS} 네 종류여야 함")
    for kind, kdef in kinds.items():
        _check_kind_def(kind, kdef)

    ranking = data["ranking"]
    if not isinstance(ranking, dict) or set(ranking) != set(_KINDS):
        raise PeripheralRuleError(f"주변기기 ranking은 정확히 {_KINDS} 네 종류여야 함")
    for kind, rdef in ranking.items():
        if not isinstance(rdef, dict) or set(rdef) != {"criteria", "weights"}:
            raise PeripheralRuleError(f"주변기기 ranking 절 키 오류: {kind}")
        _check_criteria(kind, rdef["criteria"], _allowed_spec_keys(kind, data))
        _check_weights(kind, rdef["weights"], rdef["criteria"])
    _check_scoring(data.get("scoring"))

    if "parsing" in data:
        _check_parsing(data["parsing"])

    _check_requirements(data)
    _check_spec_conditions(data)
    _check_criteria_cover_conditions(data)
    _check_purposes(data)
    _check_conflicts(data)
    _check_situations(data)
    _check_pc_purpose_map(data)
    _check_adjust_chips(data)
    _check_feel(data)
    _check_interpretation(data)
    _check_emphasis(data)
    _check_chat(data)
    _check_display(data)

    if "verify" in data:
        _check_verify(data["verify"])

    return data


def load_peripheral_rules(path: Path | None = None) -> dict:
    """버전 있는 주변기기 규칙 문서. 테스트는 별도 경로를 넘겨 정책 변경/오류를 검증한다."""
    return _load_peripheral_rules(Path(path or _PERIPHERAL_RULES_PATH).resolve())


def peripheral_kinds(rules: dict | None = None) -> list[str]:
    """정의된 주변기기 종류 목록(고정 4종, 정렬)."""
    return sorted((rules or load_peripheral_rules())["kinds"])


def ranking_def(kind: str, rules: dict | None = None) -> dict:
    """종류 하나의 랭킹 정의 {criteria: 스펙 기준 → 스펙 키 목록, weights: 기본 축 가중치}."""
    rules = rules or load_peripheral_rules()
    try:
        return rules["ranking"][kind]
    except KeyError:
        raise PeripheralRuleError(f"알 수 없는 주변기기 종류: {kind}") from None


def emphasis_cfg(rules: dict | None = None) -> dict:
    """강조 축·브랜드를 문장에서 읽는 표. 절이 없으면 빈 표(아무것도 읽지 않는다)."""
    rules = rules or load_peripheral_rules()
    return rules.get("emphasis") or {"words": {}, "brand_avoid_words": [], "brands": {}}


def scoring_cfg(rules: dict | None = None) -> dict:
    """점수식 상수(근거 부족 감점, 스펙 결손 감점, 기준 가중 배수, 접전 기준)."""
    rules = rules or load_peripheral_rules()
    return rules["scoring"]


def kind_def(kind: str, rules: dict | None = None) -> dict:
    """종류 하나의 정의(label/product_type/spec_table/columns)."""
    rules = rules or load_peripheral_rules()
    try:
        return rules["kinds"][kind]
    except KeyError:
        raise PeripheralRuleError(f"알 수 없는 주변기기 종류: {kind}") from None


def resolution_classes(rules: dict | None = None) -> dict[str, list[tuple[int, int]]]:
    """parsing.resolution_classes를 (w,h) 정수쌍 표로 낸다(E9, peripheral_parse.parse_resolution이 읽음).

    절이 아직 없으면 빈 dict — 이때 parse_resolution은 파싱 가능한 모든 해상도를 "OTHER"로 분류한다
    (알 수 없음이 아니라 "분류되지 않음"이라는 뜻, 계획 §3.3 E9).
    """
    rules = rules or load_peripheral_rules()
    raw = (rules.get("parsing") or {}).get("resolution_classes") or {}
    return {name: [(int(w), int(h)) for w, h in pairs] for name, pairs in raw.items()}


def requested_kinds(values: dict, rules: dict | None = None) -> list[str]:
    """조건 values에서 peripherals 슬롯을 읽어 요청된 종류 목록을 낸다.

    없거나 빈 값이면 []. 리스트 또는 쉼표 구분 문자열을 받는다(다른 슬롯 파싱 관례와 동일,
    예: stage2_requirement.match_games). 모르는 종류는 조용히 무시하지 않고 ValueError —
    조건 입력 오류를 삼키면 사용자가 잘못 쓴 값이 "필요 없음"으로 오인된다.
    """
    raw = (values or {}).get("peripherals")
    if not raw:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    known = set(peripheral_kinds(rules))
    result: list[str] = []
    for item in items:
        kind = str(item).strip()
        if not kind:
            continue
        if kind not in known:
            raise ValueError(f"알 수 없는 주변기기 종류 조건: {kind}")
        if kind not in result:
            result.append(kind)
    return result


# ── 견적 입력 접근 함수 ──────────────────────────────────────────────────────
def spec_conditions(kind: str, rules: dict | None = None) -> dict[str, dict]:
    """종류의 스펙 조건 목록 {이름: {label, words, filter, prefs}}. 절이 없으면 빈 표."""
    rules = rules or load_peripheral_rules()
    return (rules.get("spec_conditions") or {}).get(kind, {})


def purposes(kind: str, rules: dict | None = None) -> dict[str, dict]:
    """종류의 목적 목록 {코드: {label, words, prefer, feel, taste}}. 절이 없으면 빈 표."""
    rules = rules or load_peripheral_rules()
    return (rules.get("purposes") or {}).get(kind, {})


def purpose_codes(rules: dict | None = None) -> list[str]:
    """모든 종류의 목적 코드(중복 없이, 처음 나온 순서). 문장 해석이 고르는 닫힌 목록이다."""
    rules = rules or load_peripheral_rules()
    seen: dict[str, None] = {}
    for kind in _KINDS:
        for code in (rules.get("purposes") or {}).get(kind, {}):
            seen.setdefault(code)
    return list(seen)


def situations(rules: dict | None = None) -> dict[str, dict]:
    """공통 상황 목록 {코드: {label, words, same_condition_group}}. 절이 없으면 빈 표."""
    rules = rules or load_peripheral_rules()
    return rules.get("situations") or {}


def conflicts(kind: str, rules: dict | None = None) -> list[tuple[str, str]]:
    """종류의 함께 있을 수 없는 스펙 조건 쌍. 절이 없으면 빈 목록."""
    rules = rules or load_peripheral_rules()
    return [tuple(pair) for pair in (rules.get("conflicts") or {}).get(kind, [])]


def split_purpose_codes(purposes: list[str], situation_codes: list[str], rules: dict | None = None) -> tuple[list[str], list[str]]:
    """목적 이름과 상황 이름을 목록 안의 값으로 정리하고 (목적, 상황)으로 나눈다. 목적 칸에 들어온 이름이 공통 상황 이름이면
    (quiet_place·portable·small_desk 등) 상황으로 옮긴다. 목록에 없는 이름은 버리고, 중복은 처음 나온 순서로 하나만 둔다."""
    rules = rules or load_peripheral_rules()
    sit = set(situations(rules))
    known = set(purpose_codes(rules)) | sit
    kept_purposes = dict.fromkeys(c for c in purposes if c in known and c not in sit)
    kept_situations = dict.fromkeys(c for c in [*situation_codes, *(c for c in purposes if c in sit)] if c in sit)
    return list(kept_purposes), list(kept_situations)


def pc_purpose_map(rules: dict | None = None) -> dict[str, list[str]]:
    rules = rules or load_peripheral_rules()
    return rules.get("pc_purpose_map") or {}


def interpretation_settings(rules: dict | None = None) -> dict[str, int]:
    rules = rules or load_peripheral_rules()
    return rules.get("interpretation") or {"max_chars": 300, "cache_size": 512, "per_minute": 20}


def chat_config(rules: dict | None = None) -> dict:
    """채팅 질문 답변 설정(chat 절). 절이 없으면 빈 표 — 질문을 가르지 않고 설명도 하지 않는다."""
    rules = rules or load_peripheral_rules()
    return rules.get("chat") or {}


def adjust_chips(kind: str, rules: dict | None = None) -> list[dict]:
    """종류의 "더 맞추기" 칩 후보 [{id, label, add}]. 절이 없으면 빈 목록."""
    rules = rules or load_peripheral_rules()
    return (rules.get("adjust_chips") or {}).get(kind, [])


def display_config(rules: dict | None = None) -> dict | None:
    """결과 화면 표시 설정(없으면 None — 표시 값을 만들지 않는다)."""
    rules = rules or load_peripheral_rules()
    return rules.get("display")


def feel_config(rules: dict | None = None) -> dict | None:
    """체감 점수 설정(없으면 None — 체감 점수를 계산하지 않는다)."""
    rules = rules or load_peripheral_rules()
    return rules.get("feel")


def feel_attributes(kind: str, rules: dict | None = None) -> dict[str, dict]:
    """종류의 세부 속성·성향 축 {코드: 정의}. 절이 없으면 빈 표."""
    feel = feel_config(rules)
    return (feel or {}).get("attributes", {}).get(kind, {})

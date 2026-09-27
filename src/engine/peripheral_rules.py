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
from src.engine.peripheral_parse import PARSED_KEYS_BY_KIND

_PERIPHERAL_RULES_PATH = PERIPHERAL_RULES_PATH


class PeripheralRuleError(ValueError):
    """config/peripherals.yaml이 없거나 형식이 잘못됨."""


# 현재 필수 절. requirements(E10)·verify(E12)·parsing(E9)은 선택 절이다. hard_filters/preferences는
# 이름만 예약한다 — 파일에 없어도 되고, 있어도 최상위 키 오류가 나지 않는다.
# parsing 은 E9가 채운다(resolution_classes) — schema_version을 올리지 않고 기존 "알려진
# 선택 절" 자리를 그대로 쓴다(E8 테스트가 schema_version==1을 고정 기대하므로 건드리지 않는다).
_REQUIRED_TOP_KEYS = {"schema_version", "rule_set_version", "kinds", "ranking"}
_KNOWN_TOP_KEYS = _REQUIRED_TOP_KEYS | {"requirements", "hard_filters", "preferences", "verify", "parsing"}

_KINDS = ("monitor", "keyboard", "mouse", "speaker")
_KIND_REQUIRED_KEYS = {"label", "product_type", "spec_table", "columns"}
_AXES = {"가격", "선호적합", "데이터충실", "리뷰"}

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


def _check_weights(kind: str, weights: Any) -> None:
    if not isinstance(weights, dict) or set(weights) != _AXES:
        raise PeripheralRuleError(f"주변기기 랭킹 가중치 축 오류: {kind}")
    for axis, value in weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise PeripheralRuleError(f"주변기기 랭킹 가중치 음수/타입 오류: {kind}.{axis}")
    if weights["리뷰"] != 0:
        raise PeripheralRuleError(f"주변기기 리뷰축 가중치는 항상 0이어야 함(대조군=PC 부품): {kind}")
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise PeripheralRuleError(f"주변기기 랭킹 가중치 합계가 1이 아님: {kind}")


# ── E10 — requirements 절 검증 ────────────────────────────────────────────
def _condition_schema() -> dict:
    """조건 키·enum 값 대조표(computer.yaml slot_schema). requirements.*.soft.when 이
    가리키는 조건은 반드시 여기 있어야 한다(§3.3 E10: "조건 키 이름·enum 값은 computer.yaml
    slot_schema와 일치해야 한다")."""
    return load_category("computer")["slot_schema"]


def _check_when(kind: str, when: Any, schema: dict) -> None:
    if not isinstance(when, dict) or not when:
        raise PeripheralRuleError(f"주변기기 요구사양 soft.when 오류: {kind}")
    for cond_key, cond_value in when.items():
        field = schema.get(cond_key)
        if not isinstance(field, dict):
            raise PeripheralRuleError(f"주변기기 요구사양 soft 조건 키 오류: {kind}.{cond_key}")
        if field.get("type") == "bool":
            valid_values: set = {True, False}
        elif field.get("type") == "enum":
            valid_values = set(field.get("values") or [])
        else:
            raise PeripheralRuleError(f"주변기기 요구사양 soft 조건 키 타입 미지원: {kind}.{cond_key}")
        if cond_value not in valid_values:
            raise PeripheralRuleError(f"주변기기 요구사양 soft 조건 값 오류: {kind}.{cond_key}={cond_value!r}")


def _allowed_spec_keys(kind: str, rules: dict) -> set[str]:
    """kind 가 판정에 쓸 수 있는 spec 키 전체 = columns 의 엔진 키(원문 컬럼 포함) ∪
    peripheral_parse.PARSED_KEYS_BY_KIND(파서 산출 키). requirements.*.soft.prefs[].key 는
    이 안에 있어야 한다(§3.3 E10: "판정용 spec 키는 E9 파서/columns가 실제로 만드는 키만")."""
    columns = kind_def(kind, rules)["columns"]
    return set(columns.values()) | set(PARSED_KEYS_BY_KIND.get(kind, ()))


def _check_pref(kind: str, pref: Any, allowed_keys: set[str]) -> None:
    if not isinstance(pref, dict) or set(pref) != {"key", "op", "value"}:
        raise PeripheralRuleError(f"주변기기 요구사양 soft.prefs 항목 키 오류: {kind}")
    key, op, value = pref["key"], pref["op"], pref["value"]
    if not isinstance(key, str) or key not in allowed_keys:
        raise PeripheralRuleError(f"주변기기 요구사양 soft 판정 키 오류(알 수 없는 spec 키): {kind}.{key}")
    if op not in SOFT_OPS:
        raise PeripheralRuleError(f"주변기기 요구사양 soft 연산자 오류: {kind}.{key}.{op}")
    if op in ("min", "max"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PeripheralRuleError(f"주변기기 요구사양 soft {op} 값은 숫자여야 함: {kind}.{key}")
    elif op in ("member_of", "contains_any"):
        if not isinstance(value, list) or not value:
            raise PeripheralRuleError(f"주변기기 요구사양 soft {op} 값은 비지 않은 목록이어야 함: {kind}.{key}")


def _check_soft(kind: str, soft: Any, schema: dict, rules: dict) -> None:
    if not isinstance(soft, list) or not soft:
        raise PeripheralRuleError(f"주변기기 요구사양 soft 절 오류(빈 목록): {kind}")
    allowed_keys = _allowed_spec_keys(kind, rules)
    for entry in soft:
        if not isinstance(entry, dict) or set(entry) != {"when", "prefs"}:
            raise PeripheralRuleError(f"주변기기 요구사양 soft 항목 키 오류: {kind}")
        _check_when(kind, entry["when"], schema)
        prefs = entry["prefs"]
        if not isinstance(prefs, list) or not prefs:
            raise PeripheralRuleError(f"주변기기 요구사양 soft.prefs 오류(빈 목록): {kind}")
        for pref in prefs:
            _check_pref(kind, pref, allowed_keys)


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
    """requirements 절(선택) 검증. 없으면 통과 — E10 이전 파일(hard_filters/preferences 등이
    아직 없는 상태)도 계속 로드돼야 한다."""
    requirements = data.get("requirements")
    if requirements is None:
        return
    if not isinstance(requirements, dict) or not requirements or set(requirements) - set(_KINDS):
        raise PeripheralRuleError("주변기기 requirements 최상위 키 오류")
    schema = _condition_schema()
    for kind, kdef in requirements.items():
        if not isinstance(kdef, dict) or not kdef or set(kdef) - {"hard", "soft"}:
            raise PeripheralRuleError(f"주변기기 requirements 절 키 오류: {kind}")
        if "hard" in kdef:
            if kind != "monitor":
                raise PeripheralRuleError(f"주변기기 requirements.hard 는 monitor 전용: {kind}")
            _check_monitor_hard(kdef["hard"], data)
        if "soft" in kdef:
            _check_soft(kind, kdef["soft"], schema, data)


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
        if not isinstance(rdef, dict) or set(rdef) != {"weights"}:
            raise PeripheralRuleError(f"주변기기 ranking 절 키 오류: {kind}")
        _check_weights(kind, rdef["weights"])

    if "parsing" in data:
        _check_parsing(data["parsing"])

    _check_requirements(data)

    if "verify" in data:
        _check_verify(data["verify"])

    return data


def load_peripheral_rules(path: Path | None = None) -> dict:
    """버전 있는 주변기기 규칙 문서. 테스트는 별도 경로를 넘겨 정책 변경/오류를 검증한다."""
    return _load_peripheral_rules(Path(path or _PERIPHERAL_RULES_PATH).resolve())


def peripheral_kinds(rules: dict | None = None) -> list[str]:
    """정의된 주변기기 종류 목록(고정 4종, 정렬)."""
    return sorted((rules or load_peripheral_rules())["kinds"])


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

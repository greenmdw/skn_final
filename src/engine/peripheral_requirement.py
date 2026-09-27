"""[2] 주변기기 요구사양 빌드 — 추천엔진 구현계획 §3.3 E10.

PC의 stage2_requirement.run(슬롯 → RequirementSpec)에 대응하는 주변기기 버전이다. 조건
(`values`, 예: `resolution`/`purpose`/`priority`/`noise_sensitive`)과
`config/peripherals.yaml`의 `requirements` 절을 합쳐 종류별 `PeripheralRequirement`
(hard/soft/assumed/notes)를 낸다.

이 모듈이 하지 않는 일(계획 §3.3 E10 경계):
- **후보 필터링을 하지 않는다.** hard/soft 조건에 맞는 후보가 있는지, 결과가 비는지는
  전혀 판단하지 않는다 — 그건 E11(`peripheral_filter`)의 몫이다.
- **조건을 완화하지 않는다.** 기본 해상도(FHD_144)에서 하드 조건을 만족하는 모니터가
  카탈로그에 0건이어도(계획 C6) 이 모듈은 조건을 그대로 낸다.
- **평가를 하지 않는다.** soft 선호는 `{key, op, value}` 형태로만 옮겨 담는다. 후보 스펙과
  비교해 적합/부적합을 매기는 것은 E11의 선언형 평가기가 한다.

## 병합 규칙 (여러 조건이 같은 키를 겨냥할 때)

`config/peripherals.yaml`의 `requirements.<kind>.soft`는 `when` 조건이 참일 때 `prefs`를
결과에 보탠다. **여러 `when`이 동시에 참이면, 뒤 항목이 앞 항목을 덮어쓰지 않고 둘 다
`preferences` 목록에 쌓인다** — 예를 들어 `priority=quiet`와 `noise_sensitive=true`가
둘 다 참이면 `switch_clicky: false` 선호가 두 번 들어간다. 이 모듈은 중복을 합치거나
가중치를 나누지 않는다(그 정책은 E11이 정한다). YAML 순서를 그대로 보존한다.

`monitor.hard`는 PC 조건 `resolution`(및 `4K`+`game`일 때 주사율 하한을 올리는
`purpose`) 하나로만 결정되고, 그 결과는 항상 최대 한 세트(`resolution_class`,
`refresh_min_hz`)라 병합 규칙이 적용될 여지가 없다.
"""
from __future__ import annotations

from typing import Any

from src.dto import PeripheralRequirement
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.stage2_requirement import load_computer_rules

_RESOLUTION_LABELS = {"FHD_144": "FHD 144Hz", "QHD_165": "QHD 165Hz", "4K": "4K 60Hz"}


def _resolution_label(resolution: str) -> str:
    """화면 안내 문구용 해상도 표시명. 표에 없는 값(방어적으로만 대비)은 코드 그대로 쓴다."""
    return _RESOLUTION_LABELS.get(resolution, str(resolution))


def _build_monitor_hard(hard_cfg: dict, resolution: str, purpose: Any) -> dict[str, Any]:
    """requirements.monitor.hard 표 + PC 조건(resolution, purpose) -> hard dict.

    resolution_class_by_res 에 없는 해상도(설정에 없는 값이 조건으로 들어온 경우, 정상
    경로에선 slot_schema enum이 이미 막지만 방어적으로)는 해당 키를 아예 만들지 않는다
    (조건을 지어내지 않는다 — 계획 §4 원칙 2).
    """
    hard: dict[str, Any] = {}

    by_res = hard_cfg.get("resolution_class_by_res") or {}
    members = hard_cfg.get("res_class_members") or {}
    primary_class = by_res.get(resolution)
    if primary_class is not None:
        hard["resolution_class"] = list(members.get(primary_class, [primary_class]))

    refresh_by_res = hard_cfg.get("refresh_min_hz_by_res") or {}
    override = hard_cfg.get("refresh_min_hz_purpose_override") or {}
    refresh_min = refresh_by_res.get(resolution)
    purpose_override = (override.get(resolution) or {}).get(purpose)
    if purpose_override is not None:
        refresh_min = purpose_override
    if refresh_min is not None:
        hard["refresh_min_hz"] = refresh_min

    return hard


def _build_soft(soft_cfg: list, values: dict) -> dict[str, Any]:
    """requirements.<kind>.soft(when/prefs 목록) + 조건 values -> {"preferences": [...]}.

    when 의 모든 (키, 값) 쌍이 values 와 일치하는 항목만 채택한다(부분 일치 없음, 전부 AND).
    일치하는 모든 항목의 prefs 를 설정 순서대로 이어 붙인다(위 모듈 docstring의 병합 규칙).
    맞는 항목이 하나도 없으면 빈 dict — soft 자체가 없다는 뜻과 "조건은 있었지만 해당 없음"을
    구분하지 않는다(둘 다 랭킹에서 선호 없음으로 같게 취급되므로 구분할 이유가 없다).
    """
    preferences: list[dict[str, Any]] = []
    for entry in soft_cfg:
        when = entry.get("when") or {}
        if all(values.get(cond_key) == cond_value for cond_key, cond_value in when.items()):
            preferences.extend(entry.get("prefs") or [])
    return {"preferences": preferences} if preferences else {}


def build_requirements(
    values: dict, kinds: list[str], rules: dict | None = None, computer_rules: dict | None = None,
) -> dict[str, PeripheralRequirement]:
    """요청된 종류(kinds)만 담아 PeripheralRequirement 를 낸다. 요청하지 않은 종류는 결과에
    아예 없다(존재하지 않는 조건을 만들지 않는다).

    resolution 조건이 없으면 PC 규칙의 기본 해상도(`load_computer_rules()["requirements"]
    ["default_resolution"]`, 지금은 FHD_144)를 쓰고, `assumed`에 `"resolution"`을,
    `notes`에 화면 안내 문장을 남긴다 — 이 표시는 monitor 요청에만 붙는다(다른 종류는
    해상도 조건을 쓰지 않는다).
    """
    rules = rules or load_peripheral_rules()
    computer_rules = computer_rules or load_computer_rules()
    default_resolution = computer_rules["requirements"]["default_resolution"]

    raw_resolution = values.get("resolution")
    resolution = raw_resolution or default_resolution
    resolution_assumed = not raw_resolution
    purpose = values.get("purpose")

    req_cfg = rules.get("requirements") or {}
    out: dict[str, PeripheralRequirement] = {}
    for kind in kinds:
        kind_cfg = req_cfg.get(kind) or {}
        hard: dict[str, Any] = {}
        assumed: list[str] = []
        notes: list[str] = []

        if kind == "monitor":
            hard = _build_monitor_hard(kind_cfg.get("hard") or {}, resolution, purpose)
            if resolution_assumed:
                assumed.append("resolution")
                notes.append(f"해상도를 말하지 않아 기본값({_resolution_label(default_resolution)})으로 골랐습니다")

        soft = _build_soft(kind_cfg.get("soft") or [], values)

        out[kind] = PeripheralRequirement(kind=kind, hard=hard, soft=soft, assumed=assumed, notes=notes)
    return out

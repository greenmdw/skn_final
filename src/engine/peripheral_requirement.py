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

## 선호와 거르기 (견적 입력 설계 5.1)

선호(`soft`)와 사용자가 직접 말한 거르기 조건(`filters`)은 이 모듈이 정하지 않는다. 문장 해석 결과를
`peripheral_intent.resolve()` 가 풀어 낸 값을 `values["peripheral_resolved"]`(종류 → `ResolvedKind`)로
받아 옮겨 담을 뿐이다. 같은 키를 겨냥한 선호가 여럿이어도 합치지 않는다 — 중복 제거는 평가기
(`spec_rules.dedupe_prefs`)가 한다. 목적에서 풀린 조건은 항상 선호이고, 거르는 것은 `filters` 와 monitor 의
PC 호환 `hard` 뿐이다.

`monitor.hard`는 PC 조건 `resolution`(및 `4K`+`game`일 때 주사율 하한을 올리는
`purpose`) 하나로만 결정되고, 그 결과는 항상 최대 한 세트(`resolution_class`,
`refresh_min_hz`)라 병합 규칙이 적용될 여지가 없다.
"""
from __future__ import annotations

from typing import Any

from src.dto import Candidate, PeripheralRequirement
from src.engine.peripheral_rules import load_peripheral_rules

# PC 해상도를 모를 때(PC 견적을 묶지 않은 단독 요청) 모니터 요구사양에 남기는 안내. 해상도·주사율로 거르지 않는다.
PC_UNKNOWN_NOTE = "PC 사양을 몰라 해상도·주사율로 거르지 않고 모든 모니터에서 골랐습니다"

_GAME_PURPOSES = {"game", "fps"}
_WIDE_PIXELS = 3440 * 1440          # 이 화소 수 이상이면 게임에서 그래픽카드 부담이 큰 편(QHD 와이드)
_SMOOTH_REFRESH_HZ = 144


def monitor_notices(cand: Candidate, requirement: PeripheralRequirement, values: dict) -> list[dict[str, str]]:
    """PC 견적 없이 고른 모니터 1위에 붙이는 채팅용 유의사항(QA PQA-001). 추천은 막지 않고 주의할 점만 알린다.

    PC 견적이 묶였으면(해상도 하드 조건이 있으면) 그 PC 에 맞춰 골랐으므로 내지 않는다. 문장은 서버가 만들고 화면은
    그대로 채팅에 보여 준다. 스펙 값이 없으면 그 유의사항은 내지 않는다(모르는 값으로 단정하지 않는다)."""
    if "resolution" not in requirement.assumed:
        return []
    notices = [{"kind": "monitor", "code": "pc_unknown",
                "text": "PC 사양을 모르는 상태로 골랐어요. 쓰시는 PC나 PC 견적을 알려 주시면 해상도·단자가 맞는지 확인해 드릴게요."}]
    resolved = (values.get("peripheral_resolved") or {}).get("monitor")
    codes = {p["code"] for p in resolved.purposes} if resolved is not None else set()
    if not (codes & _GAME_PURPOSES or values.get("purpose") == "game"):
        return notices
    width, height = cand.specs.get("resolution_w"), cand.specs.get("resolution_h")
    if height and height >= 2160:
        notices.append({"kind": "monitor", "code": "gpu_4k",
                        "text": "4K 모니터로 게임을 하려면 높은 그래픽카드 성능이 필요해요. 지금 PC가 4K를 감당하는지 먼저 확인해 주세요."})
    elif width and height and width * height >= _WIDE_PIXELS:
        notices.append({"kind": "monitor", "code": "gpu_high_res",
                        "text": "해상도가 높아 그래픽카드 부담이 커요. 게임용이면 PC 사양을 먼저 확인해 주세요."})
    refresh = cand.specs.get("refresh_hz")
    if refresh and refresh < _SMOOTH_REFRESH_HZ:
        notices.append({"kind": "monitor", "code": "low_refresh",
                        "text": f"이 모니터는 주사율이 {int(refresh)}Hz라 빠른 게임에서는 화면이 덜 부드러울 수 있어요."})
    return notices


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


def build_requirements(
    values: dict, kinds: list[str], rules: dict | None = None, computer_rules: dict | None = None,
) -> dict[str, PeripheralRequirement]:
    """요청된 종류(kinds)만 담아 PeripheralRequirement 를 낸다. 요청하지 않은 종류는 결과에
    아예 없다(존재하지 않는 조건을 만들지 않는다).

    resolution 조건(묶은 PC 견적의 해상도 또는 요청의 `resolution`)이 있으면 그 해상도로 모니터 하드 조건(해상도 등급·
    주사율 하한)을 건다 — PC 그래픽카드 목표에 맞추는 것이 설계 의도다. 없으면(PC 견적 없는 단독 요청) **하드 조건을
    걸지 않는다**: 4K 를 포함한 모든 모니터가 후보이고, 해상도·주사율은 목적에서 풀린 선호(game → 고주사율, docs·creative →
    고해상도)로만 순위에 들어간다. 이때 `assumed`에 `"resolution"`을, `notes`에 안내를 남기고, 1위에 따른 유의사항은
    `monitor_notices` 가 채팅용으로 만든다(QA PQA-001, 2026-10-15 결정 — 예전에는 QHD_165 로 걸러 33종 중 8종만 남았다).
    """
    rules = rules or load_peripheral_rules()

    resolution = values.get("resolution")
    resolution_assumed = not resolution
    purpose = values.get("purpose")

    req_cfg = rules.get("requirements") or {}
    out: dict[str, PeripheralRequirement] = {}
    for kind in kinds:
        kind_cfg = req_cfg.get(kind) or {}
        hard: dict[str, Any] = {}
        assumed: list[str] = []
        notes: list[str] = []

        if kind == "monitor":
            if resolution_assumed:
                assumed.append("resolution")
                notes.append(PC_UNKNOWN_NOTE)
            else:
                hard = _build_monitor_hard(kind_cfg.get("hard") or {}, resolution, purpose)

        resolved = (values.get("peripheral_resolved") or {}).get(kind)
        preferences = resolved.preference_prefs() if resolved is not None else []
        stated = resolved.stated_preference_prefs() if resolved is not None else []
        filters = resolved.filter_prefs() if resolved is not None else []
        soft: dict[str, Any] = {}
        if preferences:
            soft["preferences"] = preferences
            if stated:
                soft["stated"] = stated        # preferences 중 직접 말한 것(점수식의 조건 스펙 가중이 쓴다)

        out[kind] = PeripheralRequirement(
            kind=kind, hard=hard, soft=soft,
            filters=filters, assumed=assumed, notes=notes,
        )
    return out

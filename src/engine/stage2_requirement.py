"""[2] 요구사양 빌드.

슬롯(사용자 언어) → 기계 판정 가능한 목표사양(RequirementSpec).
100% 규칙·룩업. LLM은 extra 자유조건 파싱 / 업그레이드 현재구성 파싱에만 (데모 생략).
컴퓨터: game_requirements + perf_tier 사다리 + PSU 헤드룸 공식 + link_rules 기록.
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path

import yaml

from src.dto import RequirementSpec, Slots
from src.engine import LogFn

_COMPUTER_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "computer_verification_rules.yaml"
_TIMING_RANK = {"now": 0, "soon": 1, "later": 2}


class RequirementRuleError(ValueError):
    """config/computer_verification_rules.yaml 이 없거나 형식이 잘못됨."""


_PROFILE_KEYS = {"tier", "ram_type", "storage_protocol", "storage_capacity_gb_min", "psu_efficiency_min",
                 "estimated_power_w", "sockets_by_brand", "budget_allocation", "motherboard_form_factors",
                 "case_form"}


def _check_power_and_budget(req: dict, where: str = "") -> None:
    power = req.get("estimated_power_w") or {}
    watts = req.get("psu_standard_wattages") or []
    multiplier = req.get("psu_headroom_multiplier")
    if (not all(k in power for k in ("cpu", "gpu", "other")) or not isinstance(multiplier, (int, float))
            or multiplier <= 0 or not watts or watts != sorted(set(watts))
            or watts[-1] < int(sum(power[k] for k in ("cpu", "gpu", "other")) * multiplier)):
        raise RequirementRuleError(f"{where}PC PSU 요구/표준 용량 규칙 오류")
    if abs(sum((req.get("budget_allocation") or {}).values()) - 1) > 1e-9:
        raise RequirementRuleError(f"{where}PC 예산 배분 합계가 1이 아님")


def _check_ranking_priority(ranking: dict) -> None:
    axes = set(ranking.get("weights") or {})
    for name, weights in (ranking.get("priority_weights") or {}).items():
        if (not isinstance(weights, dict) or set(weights) != axes
                or any(not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 for v in weights.values())
                or abs(sum(weights.values()) - 1) > 1e-9):
            raise RequirementRuleError(f"PC 우선순위 가중치 오류: {name}")
    floor = ranking.get("noise_sensitive_min_weight", 0)
    if not isinstance(floor, (int, float)) or isinstance(floor, bool) or not 0 <= floor < 1:
        raise RequirementRuleError("PC 소음 민감 최소 가중치 오류")
    proxy = ranking.get("noise_proxy") or {}
    for key in ("cpu_tdp_w", "gpu_power_w"):
        if key in proxy:
            bounds = proxy[key]
            if not (isinstance(bounds, list) and len(bounds) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bounds)
                    and bounds[0] < bounds[1]):
                raise RequirementRuleError(f"PC 소음 대용값 범위 오류: {key}")
    table = proxy.get("cooler_type")
    if table is not None and (not isinstance(table, dict) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in table.values())):
        raise RequirementRuleError("PC 소음 대용값 표 오류: cooler_type")


def _check_purpose_profile(purpose: str, profile, req: dict, verification: dict) -> None:
    """용도 프로필은 기본 요구 위에 덮어쓰는 값이므로, 덮어쓴 결과가 그대로 유효한지 본다."""
    where = f"용도 프로필 {purpose}: "
    if not isinstance(profile, dict) or set(profile) - _PROFILE_KEYS:
        raise RequirementRuleError(f"{where}알 수 없는 키")
    tier = profile.get("tier")
    if not isinstance(tier, dict) or not all(
            isinstance(tier.get(k), (int, float)) and not isinstance(tier.get(k), bool)
            for k in ("gpu", "cpu", "ram_gb", "vram_gb")):
        raise RequirementRuleError(f"{where}tier(gpu/cpu/ram_gb/vram_gb) 오류")
    sockets = profile.get("sockets_by_brand")
    if sockets is not None and not (isinstance(sockets, dict) and all(sockets.get(b) for b in ("intel", "amd", "none"))):
        raise RequirementRuleError(f"{where}sockets_by_brand 는 intel/amd/none 이 모두 있어야 함")
    if "psu_efficiency_min" in profile and profile["psu_efficiency_min"] not in (
            verification.get("efficiency_order") or []):
        raise RequirementRuleError(f"{where}알 수 없는 파워 등급")
    _check_power_and_budget({**req, **{k: v for k, v in profile.items() if k != "tier"}}, where)


@lru_cache(maxsize=8)
def _load_computer_rules(path: Path) -> dict:
    if not path.is_file():
        raise RequirementRuleError(f"PC 규칙 파일 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RequirementRuleError("PC 규칙 schema_version 오류")
    if not data.get("rule_set_version"):
        raise RequirementRuleError("PC 규칙 rule_set_version 없음")
    req, verification, ranking = (data.get(k) for k in ("requirements", "verification", "ranking"))
    if not all(isinstance(v, dict) for v in (req, verification, ranking)):
        raise RequirementRuleError("PC 규칙 섹션 누락")
    if req.get("default_resolution") not in (req.get("game_tiers") or {}):
        raise RequirementRuleError("PC 기본 해상도 규칙 없음")
    if not verification.get("link_rules") or not 0 < verification.get("power", {}).get("psu_capacity_factor", 0) <= 1:
        raise RequirementRuleError("PC 호환성 규칙 오류")
    _check_power_and_budget(req)
    if abs(sum((ranking.get("weights") or {}).values()) - 1) > 1e-9:
        raise RequirementRuleError("PC 랭킹 가중치 합계가 1이 아님")
    _check_ranking_priority(ranking)
    for part, table in (req.get("lineup_perf_tier") or {}).items():
        if part not in ("cpu", "gpu") or not isinstance(table, dict) or not table or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 10 for v in table.values()):
            raise RequirementRuleError(f"PC 등급-티어 표 오류: {part}")
    for purpose, profile in (req.get("purpose_profiles") or {}).items():
        _check_purpose_profile(purpose, profile, req, verification)
    return data


def load_computer_rules(path: Path | None = None) -> dict:
    """버전 있는 PC 규칙 문서. 테스트는 별도 경로를 넘겨 정책 변경을 검증한다."""
    return _load_computer_rules(Path(path or _COMPUTER_RULES_PATH).resolve())


# 업그레이드 대상 부품 표기(칩 값·자유 표기)를 슬롯 이름으로. 표에 없으면 unresolved 로 남긴다.
_PC_SLOT_ALIASES = {
    "cpu": "CPU", "프로세서": "CPU",
    "gpu": "GPU", "그래픽카드": "GPU", "그래픽": "GPU", "vga": "GPU",
    "ram": "RAM", "메모리": "RAM",
    "메인보드": "메인보드", "보드": "메인보드", "mainboard": "메인보드", "motherboard": "메인보드",
    "저장장치": "저장장치", "ssd": "저장장치", "storage": "저장장치",
    "파워": "파워", "psu": "파워", "power": "파워",
    "케이스": "케이스", "case": "케이스",
    "쿨러": "쿨러", "cooler": "쿨러",
}


def normalize_pc_slot(raw) -> str | None:
    return _PC_SLOT_ALIASES.get(str(raw).strip().lower()) if raw is not None else None


def _upgrade_slots(raw) -> tuple[set[str], list[dict[str, str]]]:
    """upgrade_parts(리스트 또는 쉼표 문자열) -> (슬롯 집합, 알아듣지 못한 표기)."""
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    wanted: set[str] = set()
    unresolved: list[dict[str, str]] = []
    for item in items:
        slot = normalize_pc_slot(item)
        if slot:
            wanted.add(slot)
        elif str(item).strip():
            unresolved.append({"key": "upgrade_parts", "value": str(item).strip(), "reason": "알 수 없는 부품"})
    return wanted, unresolved


def _computer_build(slots: Slots, log: LogFn) -> RequirementSpec:
    rules = load_computer_rules()
    base = rules["requirements"]
    # 용도 프로필(사무·학습·창작)은 기본 요구를 덮어쓰고 해상도 대신 자기 tier 를 쓴다.
    # 프로필이 없는 용도(게임·기타·미지정)는 종전대로 해상도별 게임 요구를 따른다.
    profile = (base.get("purpose_profiles") or {}).get(slots.values.get("purpose")) or {}
    req = {**base, **{k: v for k, v in profile.items() if k != "tier"}}
    res = slots.values.get("resolution") or base["default_resolution"]
    tier = profile.get("tier") or base["game_tiers"].get(res, base["game_tiers"][base["default_resolution"]])
    gpu_t, cpu_t, ram_gb, vram = (tier[k] for k in ("gpu", "cpu", "ram_gb", "vram_gb"))
    brand = slots.values.get("brand_pref", "none")
    socket_in = req["sockets_by_brand"][brand]

    # PSU 헤드룸: (cpu_tdp + gpu_tgp + 표준부하) * K → 표준 용량
    power = req["estimated_power_w"]
    est_cpu_tdp, est_gpu_tgp = power["cpu"], power["gpu"]  # 후보 실측값은 [4]에서 확인
    required_w = int((est_cpu_tdp + est_gpu_tgp + power["other"]) * req["psu_headroom_multiplier"])
    wattage_min = next(w for w in req["psu_standard_wattages"] if w >= required_w)

    targets = {
        "CPU": {"perf_tier_min": cpu_t, "socket_in": socket_in, "tdp_budget_w": est_cpu_tdp},
        "GPU": {"perf_tier_min": gpu_t, "vram_gb_min": vram, "tgp_budget_w": est_gpu_tgp},
        "RAM": {"type": req["ram_type"], "capacity_gb_min": ram_gb},
        "메인보드": {"socket_in": socket_in, "form_in": req["motherboard_form_factors"], "mem_type": req["ram_type"]},
        "저장장치": {"interface": req["storage_protocol"], "capacity_gb_min": req["storage_capacity_gb_min"]},
        "파워": {"wattage_min": wattage_min, "plus_rating_min": req["psu_efficiency_min"]},
        "케이스": {"form": req["case_form"]},
        "쿨러": {"tdp_capacity_w_min": est_cpu_tdp},
    }
    link_rules = [rule.format(psu_capacity_factor=rules["verification"]["power"]["psu_capacity_factor"])
                  for rule in rules["verification"]["link_rules"]]
    budget_total = slots.values.get("budget_max") or 0
    alloc = dict(req["budget_allocation"])
    feasibility = "ok"  # TODO: est_total vs budget 예비 판정

    flags = []
    unresolved: list[dict[str, str]] = []
    if slots.mode == "upgrade":
        # 업그레이드: 고른 부품만 견적을 낸다. 예산은 그 부품들에 쓸 돈이라 배분도 그 안에서 다시 잡는다.
        wanted, unresolved = _upgrade_slots(slots.values.get("upgrade_parts"))
        targets = {s: t for s, t in targets.items() if s in wanted}
        kept = sum(alloc.get(s, 0) for s in targets)
        alloc = {s: alloc[s] / kept for s in targets} if kept else {}
        flags.append("upgrade")
        log(f"      업그레이드 대상: {', '.join(targets) or '(없음)'}")
    if "resolution" in slots.assumed_keys and not profile:
        flags.append("resolution_assumed")

    log(f"      {slots.values.get('purpose') if profile else '게임'} 요구: "
        f"GPU tier≥{gpu_t}, CPU tier≥{cpu_t}, RAM {ram_gb}GB, VRAM {vram}GB")
    log(f"      PSU 헤드룸: 필요 {required_w}W → 최소 {wattage_min}W (K={req['psu_headroom_multiplier']})")
    log(f"      link_rules {len(link_rules)}개 기록 · 예산배분 가이드 · feasibility={feasibility}")

    return RequirementSpec(
        list_id=str(uuid.uuid4()),
        category="computer",
        mode=slots.mode,
        targets=targets,
        link_rules=link_rules,
        budget={"total": budget_total, "alloc": alloc, "feasibility": feasibility},
        flags=flags,
        unresolved=unresolved,
    )


def run(slots: Slots, cat_def: dict, log: LogFn) -> RequirementSpec:
    log("[2] 요구사양 빌드 ...")
    if slots.category == "computer":
        return _computer_build(slots, log)
    raise NotImplementedError(f"stage2: 지원하지 않는 카테고리입니다: {slots.category}")

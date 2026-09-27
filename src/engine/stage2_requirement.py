"""[2] 요구사양 빌드.

슬롯(사용자 언어) → 기계 판정 가능한 목표사양(RequirementSpec).
100% 규칙·룩업. LLM은 extra 자유조건 파싱 / 업그레이드 현재구성 파싱에만 (데모 생략).
컴퓨터: game_requirements + perf_tier 사다리 + PSU 헤드룸 공식 + link_rules 기록.
"""
from __future__ import annotations

import re
import uuid
from functools import lru_cache
from pathlib import Path

import yaml

from src.categories import load_category
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


_TIER_KEYS = ("gpu", "cpu", "ram_gb", "vram_gb")


_GAME_TITLE_ENTRY_KEYS = {"aliases", "tier", "status", "source"}
_GAME_TITLE_STATUSES = {"provisional", "approved"}
_GAME_SOURCE_KEYS = {"url", "excerpt", "checked_at"}
_CHECKED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_game_title_source(key: str, status: str, source) -> None:
    """E7 — 출처·승인 상태. `source`는 선택이지만 `approved`면 url·checked_at이 있어야 한다.

    값 자체(URL이 실재하는지, 발췌가 정확한지)는 여기서 확인하지 않는다 — 수집·승인은 R-11.
    """
    if source is not None:
        if not isinstance(source, dict) or set(source) - _GAME_SOURCE_KEYS:
            raise RequirementRuleError(f"PC 게임 요구사양 출처 오류: {key}")
        for field in _GAME_SOURCE_KEYS:
            if field in source and not (isinstance(source[field], str) and source[field].strip()):
                raise RequirementRuleError(f"PC 게임 요구사양 출처 오류: {key}.{field}")
        checked_at = source.get("checked_at")
        if checked_at is not None and not _CHECKED_AT_RE.match(checked_at):
            raise RequirementRuleError(f"PC 게임 요구사양 확인일 형식 오류(YYYY-MM-DD): {key}")
    if status == "approved" and not (source and source.get("url") and source.get("checked_at")):
        raise RequirementRuleError(f"PC 게임 요구사양 승인(approved) 상태인데 출처가 없음: {key}")


def _check_game_titles(titles) -> None:
    if titles is None:
        return
    if not isinstance(titles, dict):
        raise RequirementRuleError("PC 게임 요구사양 표 오류")
    seen: dict[str, str] = {}
    for key, entry in titles.items():
        if not isinstance(entry, dict) or set(entry) - _GAME_TITLE_ENTRY_KEYS:
            raise RequirementRuleError(f"PC 게임 요구사양 오류: {key}")
        tier = entry.get("tier")
        aliases = entry.get("aliases")
        if (not isinstance(tier, dict) or set(tier) != set(_TIER_KEYS)
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in tier.values())
                or not aliases or not all(isinstance(a, str) and _norm_game(a) for a in aliases)):
            raise RequirementRuleError(f"PC 게임 요구사양 오류: {key}")
        status = entry.get("status", "provisional")
        if status not in _GAME_TITLE_STATUSES:
            raise RequirementRuleError(f"PC 게임 요구사양 상태(status) 오류: {key}")
        _check_game_title_source(key, status, entry.get("source"))
        for alias in aliases:
            other = seen.setdefault(_norm_game(alias), key)
            if other != key:
                raise RequirementRuleError(f"PC 게임 별칭 중복: {alias} ({other}, {key})")


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


_REVIEW_FOCUS_TOP_KEYS = {"priority", "purpose", "noise_sensitive", "assembly"}


def _check_review_focus(explanation: dict) -> None:
    """explanation.review_focus (F-1, src/engine/review_focus.py 가 읽는 절) 검증.

    선택 절이다 — 없으면 통과. 최상위 키는 slot_schema 의 조건 슬롯 이름 넷뿐이고, 하위 키는
    그 슬롯의 enum 값(bool 은 True/False, YAML 의 `true:`/`false:` 가 그렇게 파싱된다)이어야
    한다. 값은 비지 않은 문자열 리스트(리뷰 축 이름) — 정렬 순서만 바꾸므로 축 이름 자체가
    코퍼스에 실제로 있는지는 여기서 보지 않는다(테스트가 담당).
    """
    focus = explanation.get("review_focus")
    if focus is None:
        return
    if not isinstance(focus, dict) or not focus or set(focus) - _REVIEW_FOCUS_TOP_KEYS:
        raise RequirementRuleError("PC 리뷰 축 정렬 규칙(review_focus) 최상위 키 오류")
    schema = load_category("computer")["slot_schema"]
    for top_key, sub_table in focus.items():
        if not isinstance(sub_table, dict) or not sub_table:
            raise RequirementRuleError(f"PC 리뷰 축 정렬 규칙 오류: {top_key}")
        field = schema.get(top_key) or {}
        valid_keys: set = {True, False} if field.get("type") == "bool" else set(field.get("values") or [])
        for sub_key, axes in sub_table.items():
            if sub_key not in valid_keys:
                raise RequirementRuleError(f"PC 리뷰 축 정렬 규칙 오류: {top_key}.{sub_key}")
            if not isinstance(axes, list) or not axes or not all(isinstance(a, str) and a for a in axes):
                raise RequirementRuleError(f"PC 리뷰 축 정렬 규칙 오류: {top_key}.{sub_key} 축 목록")


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
    _check_game_titles(req.get("game_titles"))
    _check_review_focus(data.get("explanation") or {})
    return data


def load_computer_rules(path: Path | None = None) -> dict:
    """버전 있는 PC 규칙 문서. 테스트는 별도 경로를 넘겨 정책 변경을 검증한다."""
    return _load_computer_rules(Path(path or _COMPUTER_RULES_PATH).resolve())


def _norm_game(text) -> str:
    """게임 제목 비교용: 소문자로, 한글·영문·숫자만 남긴다(공백·구두점·'·' 무시)."""
    return re.sub(r"[^0-9a-z가-힣]", "", str(text).casefold())


def match_games(raw, rules: dict | None = None) -> tuple[list[str], list[dict], list[str]]:
    """games 조건(리스트 또는 쉼표 문자열) -> (인식한 표 키, 그 요구 tier 목록, 표에 없는 입력).

    2글자 이하 별칭은 완전 일치만, 그보다 길면 입력 안에 별칭이 들어 있으면 일치로 본다
    ("엘든링 하고 싶어요" → eldenring). 같은 게임을 두 번 말해도 한 번만 센다.
    """
    titles = ((rules or load_computer_rules())["requirements"].get("game_titles")) or {}
    items = re.split(r"[,\n]", raw) if isinstance(raw, str) else list(raw or [])
    keys: list[str] = []
    unknown: list[str] = []
    for item in items:
        text = _norm_game(item)
        if not text:
            continue
        hit = next((key for key, entry in titles.items()
                    if any(text == _norm_game(a) or (len(_norm_game(a)) > 2 and _norm_game(a) in text)
                           for a in entry["aliases"])), None)
        if hit is None:
            unknown.append(str(item).strip())
        elif hit not in keys:
            keys.append(hit)
    return keys, [titles[k]["tier"] for k in keys], unknown


def game_title_status(key: str, rules: dict | None = None) -> dict:
    """E7 — 표 키의 출처·승인 상태(D). 화면 문구가 "잠정값"과 "확인됨"을 구분하는 데 쓴다.

    표에 없는 키(방어적으로 대비 — 정상 경로에선 match_games가 이미 걸러낸 키만 온다)는
    출처가 없다는 뜻으로 provisional·source=None을 준다.
    """
    titles = ((rules or load_computer_rules())["requirements"].get("game_titles")) or {}
    entry = titles.get(key) or {}
    return {"status": entry.get("status", "provisional"), "source": entry.get("source")}


def game_title_label(key: str, rules: dict | None = None) -> str:
    """E7 — 화면에 보여줄 게임 표시명. 별칭 중 한글이 섞인 첫 별칭, 없으면 첫 별칭, 별칭 자체가
    없으면(표에 없는 키 방어) key 그대로. 내부 식별자(`lol`, `cyberpunk` 등)를 화면에 그대로
    노출하지 않기 위함이다.
    """
    titles = ((rules or load_computer_rules())["requirements"].get("game_titles")) or {}
    aliases = (titles.get(key) or {}).get("aliases") or []
    if not aliases:
        return key
    return next((a for a in aliases if re.search(r"[가-힣]", a)), aliases[0])


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
    # 게임 제목이 있으면(용도 프로필이 없을 때만) 해상도 요구와 요소별로 큰 값을 취한다.
    game_keys: list[str] = []
    unknown_games: list[str] = []
    if not profile and slots.values.get("games"):
        game_keys, game_tiers, unknown_games = match_games(slots.values["games"], rules)
        tier = {k: max([tier[k], *(t[k] for t in game_tiers)]) for k in _TIER_KEYS}
    gpu_t, cpu_t, ram_gb, vram = (tier[k] for k in _TIER_KEYS)
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
    games_list: list[dict] = []
    if game_keys:
        flags.append("games_applied")
        # E7 — 제목별 출처·승인 상태를 spec.games 에 구조화해 싣는다(서비스 쪽 _games_trace_row 가
        # 읽는다). 하나라도 아직 팀 확인 전(provisional)이면 games_provisional 을 세워 [5] caveat
        # 의 근거로 쓴다. games_applied/games_provisional 플래그는 기존 소비처
        # (stage3b_rank의 "games_applied" in spec.flags) 를 위해 그대로 유지한다.
        for key in game_keys:
            status_info = game_title_status(key, rules)
            games_list.append({"key": key, "label": game_title_label(key, rules), **status_info})
        if any(g["status"] != "approved" for g in games_list):
            flags.append("games_provisional")
    for name in unknown_games:
        unresolved.append({"key": "games", "value": name, "reason": "요구사양 표에 없는 게임"})

    log(f"      {slots.values.get('purpose') if profile else '게임'} 요구: "
        f"GPU tier≥{gpu_t}, CPU tier≥{cpu_t}, RAM {ram_gb}GB, VRAM {vram}GB")
    if game_keys or unknown_games:
        log(f"      게임 요구 반영: {', '.join(game_keys) or '(없음)'}"
            + (f" · 표에 없음: {', '.join(unknown_games)}" if unknown_games else ""))
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
        games=games_list,
    )


def run(slots: Slots, cat_def: dict, log: LogFn) -> RequirementSpec:
    log("[2] 요구사양 빌드 ...")
    if slots.category == "computer":
        return _computer_build(slots, log)
    raise NotImplementedError(f"stage2: 지원하지 않는 카테고리입니다: {slots.category}")

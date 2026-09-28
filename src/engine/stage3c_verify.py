"""[3-C] 검증 — 규칙 judge + 쟁점 문장화(+ 데모 경로에 한해 RAG).

세 갈래를 이 모듈이 낸다:

- **세트(컴퓨터, mode="set")** — 완성 세트 1건. 신뢰도 = 100 − Σ(쟁점 감점).
  CONFIDENCE_THRESHOLD 미만이면 재탐색한다(E1, `research_loop.run_set_with_research`가
  라운드마다 이 검증을 다시 부른다).
  - **데모 경로** — `verify_set`. 시나리오별 정답값 주입(기획서 §10-9 B안): tool 결과·
    신뢰도·회색축·문제 슬롯은 `scenario["verify"]["rounds"][i]`에서 그대로 가져오고, 쟁점
    문장만 LLM으로 실제 생성한다(MOCK_MODE면 목 문장). 근거는 `evidence_search`(시나리오가
    주입한 인메모리 미니 코퍼스, `src/rag/evidence_search.py`)를 축 단위로 찾는다.
  - **실경로** — `verify_build`. `link_check`/`budget` 값을 규칙이 그대로 판정·감점한다.
    `chosen`·`spec`·`rules`를 주면(E5) `stage4_optimize.pc_compat_details`를 다시 돌려 각
    쟁점의 근거를 **카탈로그 스펙 출처**(제품 페이지 URL·확인일, `_catalog_evidence`)로
    만든다 — 문서 검색(RAG)은 아직 연결하지 않아서(`src/rag/__init__.py` 참고) 회색축에
    "설명서·규격(RAG 미연결)"이 항상 남는다. `evidence_search`는 이 경로에서 안 쓰인다.
- **품목별(주변기기, mode="per_item")** — `verify_per_item`(E11). 완성 세트가 아니라 종류별로
  고른 후보 하나하나를 본다. hard 조건 미판정·소프트 선호 데이터 결손을 기본 쟁점으로 내고,
  `extra_issues`로 E12(모니터↔PC 교차 검사, `peripheral_cross.monitor_cross_checks` +
  `cross_issues`)가 낸 쟁점을 더 얹는다 — PC 세트 신뢰도와는 무관하다(`peripheral_select.
  run_peripherals`가 pc_context를 받았을 때만 채워 넘긴다).

검사AI↔변호인AI 디베이트는 걷어냈다(기획서 §10-12). 축마다 논증 2건을 만드는 대신
관측값·근거를 중립 서술한 쟁점 문장 1건만 만든다. 판정과 감점은 규칙이 정한다.
"""
from __future__ import annotations

from typing import Any

from src.clients.llm_client import call_llm
from src.config import CONFIDENCE_THRESHOLD
from src.dto import (BuildResult, Candidate, Issue, PeripheralPick, PeripheralRequirement, RequirementSpec,
                     VerificationResult, VerificationTarget)
from src.engine import LogFn, spec_rules
from src.engine.prompts import verify_issue_system
from src.rag.evidence_search import evidence_search

# 이 문장은 서술만 한다 — 판정이 섞이면 규칙이 정한 judge 와 화면에서 어긋난다.
_BANNED_KOREAN_VERDICTS = (
    "위반", "불합격", "부적합", "적합", "통과", "안전합니다", "위험합니다",
)


def _contains_verdict(text: str) -> bool:
    return any(word in text for word in _BANNED_KOREAN_VERDICTS)


# 화면에 나가는 축 이름. 엔진 내부 키(socket, gpu_len …)를 그대로 보이지 않는다.
_AXIS_LABEL = {
    "socket": "CPU·메인보드 소켓", "power": "파워 용량", "gpu_len": "그래픽카드 길이",
    "cooler_height": "쿨러 높이", "bios": "메인보드의 CPU 지원 계열(BIOS)", "budget": "예산", "예산": "예산",
    "set": "세트 구성", "memory": "메모리 규격", "form_factor": "메인보드·케이스 크기",
    "cooler_socket": "쿨러 소켓",
    "psu_form": "파워 크기와 케이스 지원 크기", "psu_length": "파워 길이와 케이스 허용 길이", "gpu_slots": "GPU 두께와 케이스 확장 슬롯",
    "radiator": "수랭 라디에이터와 케이스 장착 크기", "ram_slots": "RAM 개수·용량과 메인보드 슬롯",
    "ram_speed": "RAM 속도와 메인보드 지원 속도", "m2": "M.2 SSD와 메인보드 슬롯", "motherboard_case": "메인보드 크기와 케이스 지원 크기", "gpu_connector": "GPU 전원 커넥터와 파워 제공 커넥터",
    # E12 — 모니터↔PC 교차 검사(peripheral_cross.py)가 쓰는 축. verify_per_item의 extra_issues로
    # 들어가므로 다른 축과 같은 표에 등록해 화면·로그의 라벨 조회 경로를 하나로 유지한다.
    "monitor_resolution": "모니터 해상도와 PC 목표 해상도",
    "monitor_gpu_port": "모니터 입력 단자와 그래픽카드 출력 단자",
    "monitor_usb_c": "USB-C 영상 입력",
}


def axis_label(axis: str) -> str:
    return _AXIS_LABEL.get(axis, axis)


# 세트 검증 축([3-C] link_check 키 + 예산)이 어느 슬롯에 걸리는지. 검증은 세트 단위라 슬롯 정보가 없어서
# 화면의 "구매 전 확인"에 나눠 실을 때·재탐색 루프(E1)가 후보를 고를 때만 이 표를 쓴다 — 없는 축은 전 슬롯 공통으로 본다.
# recommendation_service._AXIS_SLOTS 였던 것을 엔진이 쓸 수 있게 여기로 옮겼다(E1).
AXIS_SLOTS: dict[str, tuple[str, ...]] = {
    "socket": ("CPU", "메인보드"), "bios": ("CPU", "메인보드"),
    "power": ("파워", "GPU", "CPU"), "gpu_len": ("GPU", "케이스"), "cooler_height": ("쿨러", "케이스"),
    "memory": ("RAM", "메인보드"), "motherboard_case": ("메인보드", "케이스"), "cooler_socket": ("CPU", "쿨러"),
    "psu_form": ("파워", "케이스"), "gpu_connector": ("GPU", "파워"), "psu_length": ("파워", "케이스"),
    "gpu_slots": ("GPU", "케이스"), "radiator": ("쿨러", "케이스"), "ram_slots": ("RAM", "메인보드"),
    "ram_speed": ("RAM", "메인보드"), "m2": ("저장장치", "메인보드"),
}


# E5 — pc_compat_details() 의 inputs 항목((slot, key) 쌍)을 사람이 읽는 이름으로. 기존 missing()/detail
# 문장에 쓰인 한국어 명칭과 맞췄다. 여기 없는 (slot, key) 는 "{slot} {key}" 로 대체된다.
_KEY_LABEL: dict[tuple[str, str], str] = {
    ("CPU", "socket"): "CPU 소켓", ("메인보드", "socket"): "메인보드 소켓",
    ("RAM", "mem_type"): "RAM 규격", ("메인보드", "mem_type"): "메인보드 메모리",
    ("메인보드", "form_factor"): "메인보드 크기", ("케이스", "supports_form_factors"): "케이스 지원 크기",
    ("GPU", "length_mm"): "GPU 길이", ("케이스", "max_gpu_len_mm"): "케이스 허용 길이",
    ("쿨러", "height_mm"): "쿨러 높이", ("케이스", "max_cooler_height_mm"): "케이스 허용 높이",
    ("쿨러", "supported_socket"): "쿨러 지원 소켓", ("메인보드", "supported_cpu_family"): "메인보드 지원 CPU 계열",
    ("CPU", "tdp_w"): "CPU 전력", ("CPU", "max_power_w"): "CPU 최대 전력", ("GPU", "power_w"): "GPU 전력",
    ("파워", "wattage_w"): "파워 용량", ("GPU", "recommended_psu_w"): "GPU 제조사 권장 파워",
    ("파워", "form_factor"): "파워 크기", ("케이스", "psu_form_factor"): "케이스 지원 파워",
    ("GPU", "power_connector"): "GPU 전원 커넥터", ("GPU", "aux_power"): "GPU 보조 전원 여부",
    ("파워", "gpu_power_connector"): "파워 제공 커넥터", ("파워", "pcie_8pin_count"): "파워 PCIe 8핀 개수",
    ("파워", "connector_12v2x6_count"): "파워 12V-2x6 커넥터 개수", ("파워", "length_mm"): "파워 길이",
    ("케이스", "max_psu_length_mm"): "케이스 허용 파워 길이", ("GPU", "slot_thickness"): "GPU 두께",
    ("케이스", "expansion_slots"): "케이스 확장 슬롯", ("쿨러", "radiator_mm"): "쿨러 라디에이터",
    ("케이스", "radiator_front_mm"): "케이스 라디에이터 지원(전면)", ("케이스", "radiator_top_mm"): "케이스 라디에이터 지원(상단)",
    ("케이스", "radiator_rear_mm"): "케이스 라디에이터 지원(후면)", ("RAM", "module_config"): "RAM 모듈 구성",
    ("RAM", "capacity_gb"): "RAM 총 용량", ("메인보드", "dimm_slots"): "메인보드 DIMM 슬롯",
    ("메인보드", "max_memory_gb"): "메인보드 최대 메모리 용량", ("RAM", "speed_mts"): "RAM 속도",
    ("메인보드", "max_memory_speed_mts"): "메인보드 최대 메모리 속도", ("저장장치", "form_factor"): "SSD 폼팩터",
    ("저장장치", "interface"): "SSD 인터페이스", ("메인보드", "m2_slots"): "메인보드 M.2 슬롯",
    ("메인보드", "m2_pcie_gen"): "메인보드 M.2 세대",
}


def _fmt_evidence_value(value: Any) -> Any:
    """Issue.evidence 는 jsonb 에 그대로 저장되므로 set 은 목록으로 바꿔 직렬화 가능하게 한다."""
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, tuple):
        return list(value)
    return value


def _catalog_evidence(row: dict | None, chosen: dict[str, "Candidate"]) -> list[dict[str, Any]]:
    """pc_compat_details 행의 inputs × 후보 provenance → 카탈로그 출처 근거(E5).

    inputs 의 key 가 후보 provenance.by_key 에 있으면 그 전용 출처 URL을, 없으면 후보의
    spec_url(제품 페이지)을 대신 쓴다 — "확실하지 않은 매핑은 넣지 말고 spec_url로 대체"(계획 §3.2 E5).
    출처 URL이 아예 없는 값은 항목을 만들지 않는다(근거가 없는데 있는 것처럼 쓰지 않는다).
    """
    out: list[dict[str, Any]] = []
    for inp in (row or {}).get("inputs") or []:
        slot, key, value = inp.get("slot"), inp.get("key"), inp.get("value")
        if value is None or value == "":
            continue
        cand = chosen.get(slot)
        if cand is None:
            continue
        prov = getattr(cand, "provenance", None) or {}
        source_url = (prov.get("by_key") or {}).get(key) or prov.get("spec_url")
        if not source_url:
            continue
        checked_at = prov.get("checked_at")
        label = _KEY_LABEL.get((slot, key), f"{slot} {key}")
        shown = _fmt_evidence_value(value)
        confirmed = f", {checked_at} 확인" if checked_at else ""
        text = f"{cand.name} — {label} {_show(shown)} (제조사 사양{confirmed})"
        out.append({
            "kind": "catalog_spec", "slot": slot, "name": cand.name, "key": key,
            "value": shown, "source_url": source_url, "checked_at": checked_at, "text": text,
        })
    return out


def _show(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " / ".join(str(v) for v in value)
    return str(value)


def _rule_sentence(axis: str, tool_result: str) -> str:
    """LLM 없이 쓰는 기본 문장. 관측값만 옮기고 해석하지 않는다."""
    if tool_result:
        return f"{axis_label(axis)}: 관측값 {tool_result}"
    return f"{axis_label(axis)}: 관측값이 기록되지 않았습니다"


def _approx_sentence(axis: str) -> str:
    """정밀 검사를 못 한 축("ok (근사)")의 안내 문장.

    실호출에서 이 축들을 LLM 에 맡기면 "근거는 제공되지 않았습니다" 만 되풀이하는 문장이 나왔다.
    서술할 내용이 "부품 스펙 데이터가 없어 정확히 확인하지 못했다" 하나뿐이라 코드가 쓴다.
    """
    if axis == "bios":
        return ("메인보드의 CPU 지원 계열(BIOS): 선택한 CPU의 세대·계열이 메인보드의 지원 목록에 있는지 확인하지 못했습니다. "
                "구매 전 메인보드 제조사의 CPU 지원 목록을 확인해 주세요.")
    return (f"{axis_label(axis)}: 부품 스펙 데이터가 부족해 정확히 확인하지 못했습니다. "
            "구매 전 제조사 스펙으로 확인해 주세요.")


def _issue_sentence(axis: str, tool_result: str, evidence: list[dict]) -> str:
    """쟁점 1건을 중립 문장으로.

    판정어가 섞이면 1회 재생성하고, 그래도 섞이거나 호출이 실패하면 규칙 템플릿으로
    내려간다. 문장화 실패는 신뢰도 점수에 영향을 주지 않는다 (기획서 §10-11 E4).
    """
    snippets = "\n".join(f"- {e.get('text', '')}" for e in evidence) or "- (없음)"
    prompt = f"축: {axis}\n관측값: {tool_result or '(기록 없음)'}\n근거:\n{snippets}"
    for _attempt in range(2):
        try:
            text = (call_llm(prompt, system=verify_issue_system()).get("text") or "").strip()
        except Exception:
            break
        if text and not _contains_verdict(text):
            return text
    return _rule_sentence(axis, tool_result)


def verify_set(
    build: BuildResult,
    scenario: dict,
    round_index: int,
    log: LogFn,
) -> VerificationResult:
    """세트 검증 1라운드. 정답값은 scenario['verify']['rounds'][round_index]."""
    log(f"[3-C] 세트 검증 (규칙 judge + 쟁점 문장화) ... (라운드 {round_index + 1})")
    vspec = scenario["verify"]
    rounds = vspec["rounds"]
    rspec = rounds[min(round_index, len(rounds) - 1)]
    domain = scenario["category"]

    log(f"      [MOCK] 시나리오 정답값 주입: {scenario['scenario']}  라운드 {round_index + 1}/{len(rounds)}")

    issues: list[Issue] = []
    for iss in rspec.get("issues", []):
        axis = iss["axis"]
        tool_result = iss.get("tool_result", "")
        ev = evidence_search(domain, f"{axis} 조합 이슈", filters={"axis": axis}, log=log)
        issues.append(Issue(
            axis=axis,
            text=_issue_sentence(axis, tool_result, ev),
            tool_result=tool_result,
            evidence=ev,
            judge=iss.get("judge", ""),
            penalty=int(iss.get("penalty", 0)),
        ))

    confidence = int(rspec["confidence"])           # judge 집계 결과 (데모는 주입값)
    passed = confidence >= CONFIDENCE_THRESHOLD
    gray = list(rspec.get("gray_axes", []))

    for iss in issues:
        log(f"      · {iss.axis}: 감점 {iss.penalty}  ({iss.judge})  근거 {len(iss.evidence)}건")
        log(f"        {iss.text}")
    if gray:
        log(f"      회색축(근거 0건 → 검증 불가): {gray}")
    log(f"      신뢰도 {confidence} → {'통과' if passed else '기준 미달 → 재탐색'}")

    tgt = VerificationTarget(
        subject="세트 전체", confidence=confidence, passed=passed,
        rounds=round_index + 1, issues=issues, gray_axes=gray,
        transcript=[{"round": round_index + 1,
                     "issues": [i.model_dump() for i in issues]}],
    )
    return VerificationResult(list_id=build.list_id, category=domain, mode="set", targets=[tgt])


def verify_build(
    build: BuildResult,
    category: str,
    log: LogFn = lambda _m: None,
    *,
    chosen: dict[str, "Candidate"] | None = None,
    spec: "RequirementSpec | None" = None,
    rules: dict | None = None,
) -> VerificationResult:
    """DB 경로([추천 실행])의 세트 검증 — 규칙 judge + 쟁점 문장화.

    chosen/spec/rules 를 주면(E5) `stage4_optimize.pc_compat_details`를 다시 돌려 각 쟁점의
    inputs 를 후보 provenance 와 엮어 Issue.evidence(카탈로그 출처)를 만든다. 셋 중 하나라도
    없으면 기존과 똑같이 근거 없이 관측값만으로 문장을 만든다(하위 호환) — 문서 검색(RAG) 연결은
    범위 밖이라 여전히 없다.
    """
    log("[3-C] 세트 검증 (규칙 스캐폴드) ...")
    rows_by_axis: dict[str, dict] = {}
    have_provenance = chosen is not None and spec is not None and rules is not None
    if have_provenance:
        from src.engine.stage4_optimize import pc_compat_details
        rows_by_axis = {row["axis"]: row for row in pc_compat_details(chosen, spec, rules)}

    issues: list[Issue] = []
    penalty = 0
    link_check = build.link_check or {}
    for axis, state in link_check.items():
        if axis in ("budget", "예산"):
            continue  # 예산은 아래에서 한 건으로 합쳐 처리한다(중복 쟁점 정리)
        s = str(state).lower()
        if "fail" in s or "미충족" in s or "over" in s:
            ev = _catalog_evidence(rows_by_axis.get(axis), chosen) if have_provenance else []
            issues.append(Issue(axis=axis, text=_issue_sentence(axis, state, ev),
                                tool_result=state, evidence=ev, judge="위반", penalty=_FAIL_ISSUE_PENALTY))
            penalty += _FAIL_ISSUE_PENALTY
        elif "pending" in s or "근사" in s:
            ev = _catalog_evidence(rows_by_axis.get(axis), chosen) if have_provenance else []
            issues.append(Issue(axis=axis, text=_approx_sentence(axis),
                                tool_result=state, evidence=ev, judge="확인 필요", penalty=6))
            penalty += 6

    # 예산 초과 — link_check["budget"]="fail"(build_computer가 총액>예산일 때 세팅) 과
    # used_pct>110 이 전에는 쟁점 2건(축 budget·예산)으로 화면에 중복으로 나갔다(추가 작업 A).
    # 두 원인이 겹칠 때만 한 건(축 budget, 초과, 35)으로 합친다 — 감점 합계·단일 원인일 때의
    # 축·판정은 옛 동작과 같다(리뷰 지적: "감점 합계를 그대로" 가 목적이지 값을 바꾸는 게 아니다).
    budget = build.budget or {}
    used_pct = budget.get("used_pct")
    if used_pct is None and budget.get("max"):
        used_pct = round(budget.get("used", 0) / budget["max"] * 100, 1)
    budget_fail = link_check.get("budget") == "fail"
    over_110 = bool(used_pct and used_pct > 110)
    budget_penalty = (20 if budget_fail else 0) + (15 if over_110 else 0)
    if budget_penalty > 0:
        if budget_fail and over_110:
            budget_axis, budget_judge, budget_tool_result = "budget", "초과", f"{used_pct}%"
        elif budget_fail:
            budget_axis, budget_judge, budget_tool_result = "budget", "위반", "fail"
        else:
            budget_axis, budget_judge, budget_tool_result = "예산", "초과", f"{used_pct}%"
        ev = _catalog_evidence(rows_by_axis.get(budget_axis), chosen) if have_provenance else []
        issues.append(Issue(axis=budget_axis, text=_issue_sentence(budget_axis, budget_tool_result, ev),
                            tool_result=budget_tool_result, evidence=ev, judge=budget_judge, penalty=budget_penalty))
        penalty += budget_penalty

    # 회색축 = 이 경로에서 실제로 검사하지 못한 것. 화면 caveats 에 "<축> 근거는 확인되지 않았습니다" 로 나간다
    # (결정 0003 — 화면에는 나가지 않고 로그에만). chosen/spec/rules 가 없으면(하위 호환) 근거 인프라를
    # 전혀 시도하지 않은 것이므로 옛 고정 목록을 그대로 낸다.
    if have_provenance:
        gray = list(dict.fromkeys(axis_label(i.axis) for i in issues if not i.evidence))
        if any(i.judge == "확인 필요" for i in issues):
            gray.append("호환성 정밀 검사(소켓·전력·크기는 근사값)")
        if not any(i.evidence for i in issues):
            gray.append("설명서·규격(RAG 미연결)")
    else:
        gray = ["설명서·규격(RAG 미연결)",
                "호환성 정밀 검사(소켓·전력·크기는 근사값)"]
    confidence = max(0, 100 - penalty)
    passed = confidence >= CONFIDENCE_THRESHOLD
    log(f"      신뢰도 {confidence} · 회색축 {gray} · {'통과' if passed else '기준 미달'}")

    tgt = VerificationTarget(
        subject="세트 전체",
        confidence=confidence, passed=passed,
        issues=issues, gray_axes=gray,
        transcript=[{"round": 1, "issues": [i.model_dump() for i in issues]}],
    )
    return VerificationResult(list_id=build.list_id, category=category, mode="set", targets=[tgt])


def verification_issue_payload(row: dict) -> dict[str, Any]:
    """검증 쟁점 1건(engine.validation_result 행 — EngineRepo.get_validations 형태) → 공개 계약 모양(R-6).

    severity 매핑은 `recommendation_service.get_stored_result`와 동일하게 맞춘다. 아직 어디에도
    연결하지 않는다(R-6 노출 전까지 §0.3) — 이 함수는 계약 모양을 미리 만들어 두는 순수 함수다.
    """
    measured = row.get("measured_values") or {}
    evidence = [
        {"text": e.get("text", ""), "source_url": e.get("source_url"), "checked_at": e.get("checked_at")}
        for e in (measured.get("evidence") or [])
    ]
    return {
        "axis": row["rule_key"],
        "severity": "major" if row["severity"] in ("warning", "critical") else "minor",
        "text": row["message"],
        "evidence": evidence,
    }


def problem_slot(scenario: dict, round_index: int) -> str | None:
    """이번 라운드가 지목한 재탐색 대상 슬롯."""
    rounds = scenario["verify"]["rounds"]
    return rounds[min(round_index, len(rounds) - 1)].get("problem_slot")


# verify_build의 link_check fail 쟁점(judge="위반") 감점. E12(peripheral_cross.cross_issues)의
# fail 쟁점도 "같은 무게의 확정 비호환"이라 이 값을 그대로 재사용한다 — 매직넘버를 두 곳에
# 따로 두지 않는다.
_FAIL_ISSUE_PENALTY = 20

# ── [3-C] 주변기기 품목별 검증 — 추천엔진 구현계획 §3.3 E11 ─────────────────
# "확인 필요" 쟁점 1건의 감점. PC verify_build의 근사 쟁점(judge="확인 필요")과 같은 값을
# 쓴다 — 같은 성격(정밀 판정을 못 함)의 쟁점이라 감점 크기를 다르게 둘 이유가 없다.
_PERIPHERAL_ISSUE_PENALTY = 6


def _peripheral_hard_pending_sentence(kind_label: str, reasons: list[str]) -> str:
    """LLM 없이 쓰는 규칙 템플릿(§3.3 E11 — "규칙 템플릿, LLM 호출 금지"). 판정어는 넣지
    않는다 — reasons는 spec_rules.evaluate가 만든 관측값 서술이다."""
    detail = "; ".join(reasons) if reasons else "값이 확인되지 않았습니다"
    return f"{kind_label} — 필수 조건({detail})을 판정하지 못했습니다. 구매 전 제조사 스펙으로 확인해 주세요."


def _peripheral_data_gap_sentence(kind_label: str, missing_keys: list[str]) -> str:
    return (f"{kind_label} — 선호 조건 판정에 쓰는 스펙이 카탈로그에 없습니다: {', '.join(missing_keys)}. "
            "참고용 순위이니 구매 전 실제 스펙으로 확인해 주세요.")


def verify_per_item(
    picks: dict[str, PeripheralPick],
    requirements: dict[str, PeripheralRequirement],
    log: LogFn,
    *,
    extra_issues: dict[str, list[Issue]] | None = None,
    rules: dict | None = None,
) -> VerificationResult:
    """[3-C] 주변기기 품목별 검증(계획 §3.3 E11). 대상이 완성 세트 1건(mode="set")이 아니라
    고른 품목 각각(mode="per_item")이라는 점만 다르고, 감점 방식(신뢰도 = 100 − Σ감점,
    `CONFIDENCE_THRESHOLD` 기준 통과 판정)은 `verify_build`와 같다.

    품목마다 쟁점 두 가지만 본다:
    1. hard 조건이 있는데(현재 monitor만) [3-A]가 Pending으로 넘긴 축 — 판정을 못 했다는 뜻.
    2. 소프트 선호 판정에 쓰는 스펙 중 이 후보가 값을 안 가진 것(데이터 결손) — 여러 키가
       비어 있어도 한 건으로 묶는다(계획 §3.3: "데이터 결손 ... 쟁점 1건으로 묶어 감점 6").

    `extra_issues`는 E12(모니터↔PC 교차 검사, `peripheral_cross.monitor_cross_checks` +
    `cross_issues`)가 쟁점을 얹는 확장 지점이다 — `peripheral_select.run_peripherals`가
    `pc_context`를 받았고 모니터를 골랐을 때만 `{"monitor": [...]}`로 채워 넘긴다. 비워
    두면(기본 None, 또는 pc_context가 없을 때) 위 두 가지만 쟁점이 된다.
    """
    from src.engine.peripheral_rules import kind_def, load_peripheral_rules

    log("[3-C] 주변기기 품목별 검증 ...")
    rules = rules or load_peripheral_rules()
    targets: list[VerificationTarget] = []
    for kind, pick in picks.items():
        cand = pick.candidate
        req = requirements.get(kind)
        label = kind_def(kind, rules)["label"]
        issues: list[Issue] = []
        penalty = 0

        if req is not None and req.hard and cand.verdict == "Pending":
            text = _peripheral_hard_pending_sentence(label, cand.reasons)
            issues.append(Issue(axis=f"{kind}_hard", text=text, tool_result="; ".join(cand.reasons),
                                judge="확인 필요", penalty=_PERIPHERAL_ISSUE_PENALTY))
            penalty += _PERIPHERAL_ISSUE_PENALTY

        soft_prefs = spec_rules.dedupe_prefs((req.soft or {}).get("preferences") or []) if req else []
        missing_keys = sorted({p["key"] for p in soft_prefs if cand.specs.get(p["key"]) is None})
        if missing_keys:
            text = _peripheral_data_gap_sentence(label, missing_keys)
            issues.append(Issue(axis=f"{kind}_data_gap", text=text, tool_result=", ".join(missing_keys),
                                judge="확인 필요", penalty=_PERIPHERAL_ISSUE_PENALTY))
            penalty += _PERIPHERAL_ISSUE_PENALTY

        for extra in (extra_issues or {}).get(kind, []):
            issues.append(extra)
            penalty += extra.penalty

        confidence = max(0, 100 - penalty)
        passed = confidence >= CONFIDENCE_THRESHOLD
        log(f"      [P] {label}: 신뢰도 {confidence} · 쟁점 {len(issues)}건 · {'통과' if passed else '기준 미달'}")
        targets.append(VerificationTarget(
            subject=label, confidence=confidence, passed=passed, issues=issues,
            transcript=[{"kind": kind, "issues": [i.model_dump() for i in issues]}],
        ))
    return VerificationResult(list_id="peripherals", category="computer", mode="per_item", targets=targets)


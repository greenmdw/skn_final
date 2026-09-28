"""모니터↔PC 교차 검사 — 추천엔진 구현계획 §3.3 E12.

`stage3c_verify.verify_per_item`의 모니터 대상에 쟁점(`extra_issues`)으로 들어간다.
**PC 세트의 신뢰도에는 영향을 주지 않는다** — 여기서 만든 쟁점은 `verify_per_item`이 만드는
`VerificationResult(mode="per_item")`에만 더해지고, `verify_build`(PC 세트 검증)는 이 모듈을
전혀 모른다.

세 축을 본다(계획 §3.3 E12 표):
  - `monitor_resolution` — 고른 모니터의 해상도 등급이 [2]가 정한 PC 목표 해상도 등급과
    같은가. [3-A](`peripheral_select.filter_candidates`)가 이미 하드 조건으로 한 번 걸렀지만,
    여기서는 **PC 쪽 목표**(`pc_resolution`)를 기준으로 독립적으로 다시 확인한다.
  - `monitor_gpu_port` — 모니터가 필요로 하는 대역폭(해상도 등급 × 목표 주사율)을 만족하는
    공통 단자(HDMI/DP)가 모니터·그래픽카드 양쪽에 있는가. `config/peripherals.yaml`의
    `verify.port_modes`(잠정값, 출처 확인 필요)로 버전별 최대 주사율을 찾는다.
  - `monitor_usb_c` — HDMI·DP가 전혀 없고 USB-C/Thunderbolt 영상 입력만 있는 모니터에 한해,
    그래픽카드의 USB-C 영상 출력 여부를 본다.

`gpu_spec`에 단자 컬럼이 아직 없다(R-1 전). 그래서 `monitor_gpu_port`/`monitor_usb_c`는
`gpu_specs`가 없거나 단자 키가 없으면 **항상 Pending("확인 필요")** 이고, R-1이 반영돼
`gpu_specs`에 값이 들어오는 순간 이 코드 변경 없이 ok/fail로 바뀐다(계획 §3.3 E12
"단자 규칙은 데이터가 있을 때 자동으로 켜지게 구현한다").

## 모르는 것은 Pending(계획 §4 원칙 2)

fail은 **양쪽 데이터가 다 있고, 표가 실제로 "안 된다"고 말할 때만** 낸다. 버전·포트 수가
하나라도 없으면(파싱 실패·컬럼 없음·해상도 등급이 대역폭 표에 없음) unknown이다. 버전이
표의 가장 낮은 버전보다도 낮아 `mode_row`가 None을 내는 경우(예: HDMI 1.3처럼 잠정 표에
아예 없는 구형 버전)도 마찬가지로 unknown이다 — 그건 우리 잠정 표의 빈 구간이지, 실제로
대역폭이 부족하다고 증명된 게 아니다(계획 §4 원칙 2, "모르는 것은 Pending"). 포트가 아예
없다는 것("없음"/개수 0)은 "모름"이 아니라 "확인된 부재"이므로 그 자체로는 fail 판정
재료가 되지만(공통 단자가 없다는 뜻), 다른 단자 쪽 데이터가 없으면 전체 판정은 여전히
unknown으로 내려간다 — 한쪽이라도 "혹시 될 수도 있는" 여지가 있으면 fail로 단정하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from src.dto import Candidate, Issue
from src.engine.stage3c_verify import _FAIL_ISSUE_PENALTY, _PERIPHERAL_ISSUE_PENALTY, axis_label

# 그래픽카드 출력 단자 정보가 없을 때 쓰는 고정 문장(계획 §3.3 E12 표에 그대로 명시된 문구).
# monitor_gpu_port·monitor_usb_c 둘 다 "GPU 쪽 데이터가 없다"는 같은 이유일 때 이 문장을 쓴다.
_GPU_PORT_DATA_MISSING = "그래픽카드 출력 단자 정보가 없어 확인하지 못했습니다"

_IFACES: tuple[str, ...] = ("hdmi", "dp")

PortVersion = tuple[int, int]

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


# ── 버전 문자열 파싱 ─────────────────────────────────────────────────────
def parse_port_version(raw: Any) -> PortVersion | None | Literal["absent"]:
    """단자 버전 원문 -> (major, minor) | "absent"(단자 없음) | None(모름/파싱 실패).

    - "없음" -> "absent" — 단자 자체가 없다는 뜻(모름이 아니라 확인된 부재).
    - "미표기"/빈 문자열/None -> None — 있는지 없는지조차 모른다는 뜻.
    - "2" -> (2, 0), "2.0b" -> (2, 0), "1.2a" -> (1, 2) — 접미사 문자는 버린다.
    - 숫자(int/float/Decimal)도 받는다 — R-1 반영 후 GPU 스펙이 문자열이 아닐 수 있어서다.
    - 그 외 형식은 파싱 실패로 보고 None(추측해서 채우지 않는다, 계획 §4 원칙 2).
    """
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text == "없음":
        return "absent"
    if text == "미표기":
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) else 0
    return (major, minor)


def mode_row(iface: str, version: PortVersion, rules: dict) -> dict[str, float] | None:
    """`verify.port_modes.<iface>`에서 `version` 이하인 표 중 가장 높은 버전의 행을 낸다.

    실제 버전이 표에 없으면(예: GPU가 "2.0b"인데 표에는 "2.0"만 있음) 그 이하 중 가장 높은
    버전을 쓴다(계획 §3.3 E12 표 주석과 동일 규칙). `version`보다 낮은 버전이 표에 하나도
    없으면(예: 표가 "2.0"부터 시작하는데 버전이 "1.4") None — 대역폭을 낼 수 없다는 뜻이다.
    """
    table = ((rules.get("verify") or {}).get("port_modes") or {}).get(iface) or {}
    best: tuple[PortVersion, dict[str, float]] | None = None
    for version_str, row in table.items():
        parsed = parse_port_version(version_str)
        if not isinstance(parsed, tuple) or parsed > version:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, row)
    return best[1] if best is not None else None


def _allowed_port_classes(rules: dict) -> set[str]:
    """port_modes 표에 실제로 등장하는 해상도 등급 전체(FHD/QHD/UHD, 잠정값). 모니터 등급이
    여기 없으면(QHD_WIDE/OTHER) 애초에 판정할 표가 없다는 뜻이라 unknown으로 내려간다."""
    modes = (rules.get("verify") or {}).get("port_modes") or {}
    classes: set[str] = set()
    for table in modes.values():
        for row in table.values():
            classes.update(row)
    return classes


def _check(axis: str, state: str, detail: str) -> dict[str, Any]:
    return {"axis": axis, "label": axis_label(axis), "state": state, "detail": detail}


# ── monitor_resolution ───────────────────────────────────────────────────
def _monitor_resolution_check(monitor: Candidate, pc_resolution: str, rules: dict) -> dict[str, Any]:
    """[3-A]와 독립적으로 다시 확인한다(계획 §3.3 E12) — 같은 표(requirements.monitor.hard)를
    읽지만 [3-A]는 하드 필터 단계에서 이미 확정된 후보만 보고, 여기서는 그 결과와 무관하게
    PC 쪽 목표 해상도(pc_resolution) 하나만으로 다시 판정한다."""
    axis = "monitor_resolution"
    hard = ((rules.get("requirements") or {}).get("monitor") or {}).get("hard") or {}
    by_res = hard.get("resolution_class_by_res") or {}
    members = hard.get("res_class_members") or {}

    primary_class = by_res.get(pc_resolution)
    if primary_class is None:
        return _check(axis, "unknown", f"PC 목표 해상도({pc_resolution})의 등급 대응표를 찾지 못해 확인하지 못했습니다")

    allowed = members.get(primary_class) or [primary_class]
    monitor_class = monitor.specs.get("resolution_class")
    if monitor_class is None:
        return _check(axis, "unknown", "모니터 해상도 등급을 확인하지 못했습니다")
    allowed_text = "/".join(allowed)
    if monitor_class in allowed:
        return _check(axis, "ok", f"모니터 해상도 등급({monitor_class})이 PC 목표 해상도 등급({allowed_text})과 같습니다")
    return _check(axis, "fail", f"모니터 해상도 등급({monitor_class})이 PC 목표 해상도 등급({allowed_text})과 다릅니다")


# ── monitor_gpu_port ─────────────────────────────────────────────────────
def _gpu_has_port_data(gpu_specs: dict, gpu_keys: dict) -> bool:
    version_keys = (gpu_keys.get("hdmi_version"), gpu_keys.get("dp_version"))
    return any(k and gpu_specs.get(k) is not None for k in version_keys)


def _iface_state(
    iface: str, monitor: Candidate, gpu_specs: dict, gpu_keys: dict,
    resolution_class: str, required_hz: float, rules: dict,
) -> tuple[str, str]:
    """단자 하나(hdmi/dp)의 판정. state ∈ {"ok", "fail", "unknown", "absent"}.

    "absent"(단자 자체가 없음)는 "모름"이 아니라 "확인된 부재"라 fail과 같은 무게로
    취급한다(호출부가 합산할 때 둘 다 "판정 가능"으로 묶는다) — 다만 그 자체가 unknown인
    다른 단자를 이기지 못하게, 최종 fail 판정은 두 단자 모두 판정 가능할 때만 나간다.

    `mode_row`가 None(버전이 `verify.port_modes` 표의 가장 낮은 버전보다도 낮음)이면
    fail이 아니라 unknown이다 — 표에 없는 구간일 뿐, 실제로 대역폭이 부족하다고 확인된
    게 아니다(계획 §4 원칙 2).
    """
    m_ver = parse_port_version(monitor.specs.get(f"{iface}_version_raw"))
    m_ports = monitor.specs.get(f"{iface}_ports")
    g_ver = parse_port_version(gpu_specs.get(gpu_keys[f"{iface}_version"]))
    g_ports = gpu_specs.get(gpu_keys[f"{iface}_ports"])

    if m_ver == "absent" or m_ports == 0 or g_ver == "absent" or g_ports == 0:
        return "absent", "모니터 또는 그래픽카드 쪽에 단자가 없습니다"
    if not isinstance(m_ver, tuple) or not isinstance(g_ver, tuple):
        return "unknown", "버전 정보가 모니터 또는 그래픽카드 쪽에서 확인되지 않았습니다"

    effective = min(m_ver, g_ver)
    version_text = f"{effective[0]}.{effective[1]}"
    row = mode_row(iface, effective, rules)
    if row is None:
        return "unknown", f"{version_text} 버전은 단자 대역폭 표에 없어 확인하지 못했습니다"
    max_hz = row.get(resolution_class)
    if max_hz is None:
        return "unknown", f"{version_text} 버전의 {resolution_class} 등급 최대 주사율이 표에 없습니다"
    if max_hz >= required_hz:
        return "ok", f"{version_text} 버전이 {resolution_class} {int(required_hz)}Hz까지 지원합니다(표상 최대 {int(max_hz)}Hz)"
    return "fail", f"{version_text} 버전은 {resolution_class}에서 최대 {int(max_hz)}Hz까지 지원해 목표 {int(required_hz)}Hz에 못 미칩니다"


def _monitor_gpu_port_check(
    monitor: Candidate, gpu_specs: dict | None, target_refresh_hz: float | None, rules: dict,
) -> dict[str, Any]:
    axis = "monitor_gpu_port"
    gpu_keys = (rules.get("verify") or {}).get("gpu_keys") or {}

    if gpu_specs is None or not gpu_keys or not _gpu_has_port_data(gpu_specs, gpu_keys):
        return _check(axis, "unknown", _GPU_PORT_DATA_MISSING)

    resolution_class = monitor.specs.get("resolution_class")
    if resolution_class is None:
        return _check(axis, "unknown", "모니터 해상도 등급을 확인하지 못해 필요 대역폭을 계산하지 못했습니다")
    if resolution_class not in _allowed_port_classes(rules):
        return _check(axis, "unknown", f"{resolution_class} 등급은 단자 대역폭 표에 없어 확인하지 못했습니다")

    required_hz = target_refresh_hz if target_refresh_hz is not None else monitor.specs.get("refresh_hz")
    if required_hz is None:
        return _check(axis, "unknown", "목표 주사율을 확인하지 못해 필요 대역폭을 계산하지 못했습니다")

    results = {iface: _iface_state(iface, monitor, gpu_specs, gpu_keys, resolution_class, required_hz, rules)
               for iface in _IFACES}
    states = [state for state, _ in results.values()]
    if "ok" in states:
        state = "ok"
    elif "unknown" in states:
        state = "unknown"
    else:
        state = "fail"   # 두 단자 모두 판정 가능(fail/absent)했는데 어느 쪽도 되지 않음
    detail = "; ".join(f"{iface.upper()}: {d}" for iface, (_, d) in results.items())
    return _check(axis, state, detail)


# ── monitor_usb_c ────────────────────────────────────────────────────────
def _monitor_usb_c_applicable(monitor: Candidate) -> bool:
    """HDMI·DP 단자가 전혀 없고 USB-C/Thunderbolt 영상 입력만 있는 모니터에만 해당한다
    (계획 §3.3 E12). 그 외에는 이 축 자체를 내지 않는다 — HDMI/DP가 있으면 그쪽으로 이미
    monitor_gpu_port가 판정하므로 USB-C 여부는 화면에 낼 쟁점이 아니다."""
    usb_c = monitor.specs.get("usb_c_video_input_raw")
    hdmi_ports = monitor.specs.get("hdmi_ports") or 0
    dp_ports = monitor.specs.get("dp_ports") or 0
    return usb_c in ("USB-C", "Thunderbolt") and hdmi_ports == 0 and dp_ports == 0


def _monitor_usb_c_check(monitor: Candidate, gpu_specs: dict | None, rules: dict) -> dict[str, Any] | None:
    if not _monitor_usb_c_applicable(monitor):
        return None
    axis = "monitor_usb_c"
    gpu_keys = (rules.get("verify") or {}).get("gpu_keys") or {}
    usb_key = gpu_keys.get("usb_c_video_out")
    if gpu_specs is None or not usb_key or gpu_specs.get(usb_key) is None:
        return _check(axis, "unknown", _GPU_PORT_DATA_MISSING)
    if gpu_specs[usb_key]:
        return _check(axis, "ok", "그래픽카드가 USB-C/Thunderbolt 영상 출력을 지원합니다")
    return _check(axis, "fail", "그래픽카드가 USB-C/Thunderbolt 영상 출력을 지원하지 않습니다")


# ── 진입점 ───────────────────────────────────────────────────────────────
def monitor_cross_checks(
    monitor: Candidate, *, pc_resolution: str, gpu_specs: dict | None,
    target_refresh_hz: float | None, rules: dict,
) -> list[dict[str, Any]]:
    """모니터 하나에 대한 교차 검사 결과 목록(계획 §3.3 E12).

    `peripheral_payload().items[].checks`(E13)와 어휘를 맞춘 `{"axis", "label", "state",
    "detail"}` 사전을 낸다. `monitor_usb_c`는 해당하지 않으면 목록에서 아예 빠진다
    (`_monitor_usb_c_applicable` 참고).
    """
    checks = [
        _monitor_resolution_check(monitor, pc_resolution, rules),
        _monitor_gpu_port_check(monitor, gpu_specs, target_refresh_hz, rules),
    ]
    usb_c_check = _monitor_usb_c_check(monitor, gpu_specs, rules)
    if usb_c_check is not None:
        checks.append(usb_c_check)
    return checks


def cross_issues(checks: list[dict[str, Any]]) -> list[Issue]:
    """검사 결과 -> Issue 목록. ok는 쟁점을 내지 않는다.

    unknown -> judge="확인 필요", 감점 `_PERIPHERAL_ISSUE_PENALTY`(stage3c_verify와 공유 —
    같은 성격의 "정밀 판정 불가" 쟁점이라 감점을 따로 두지 않는다).
    fail -> judge="위반", 감점 `_FAIL_ISSUE_PENALTY`(stage3c_verify에서 그대로 가져온 값 —
    PC verify_build의 link_check "위반" 감점과 같은 상수를 공유한다).
    `Issue.text`는 관측 사실만 서술하고 판정어를 넣지 않는다(`_BANNED_KOREAN_VERDICTS` 참고
    — "위반"은 judge 필드에만 쓰고 text에는 쓰지 않는다).
    """
    issues: list[Issue] = []
    for check in checks:
        state = check["state"]
        if state == "ok":
            continue
        judge = "확인 필요" if state == "unknown" else "위반"
        penalty = _PERIPHERAL_ISSUE_PENALTY if state == "unknown" else _FAIL_ISSUE_PENALTY
        issues.append(Issue(
            axis=check["axis"], text=f"{check['label']}: {check['detail']}",
            tool_result=check["detail"], judge=judge, penalty=penalty,
        ))
    return issues

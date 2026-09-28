"""주변기기 원문 스펙 텍스트 파서 — 추천엔진 구현계획 §3.3 E9.

data/peripherals/*_processed.csv 는 사람이 정리한 원문이라 형식이 들쭉날쭉하다(예: DPI
범위가 "200–8,000 DPI (기본값 1,000 DPI)" 처럼 괄호 안에 기본값 주석이 붙거나, 폴링레이트가
"1,000Hz (HyperPolling 동글 사용 시 8,000Hz)" 처럼 별매 액세서리를 쓸 때만 나오는 조건부
최댓값을 담기도 한다). 이 모듈은 그 원문을 판정용 값으로 바꾼다.

**파싱 실패는 예외가 아니라 None이다** — [3-A]/[3-B]는 None을 "모름"으로 보고 Pending
처리한다(추측해서 채우지 않는다는 계획 §4 원칙 2). 숫자 최댓값 계열(DPI·폴링레이트)은
"괄호 밖 텍스트에서 찾은 숫자의 최댓값"이라는 하나의 규칙으로 통일한다 — 괄호 안 내용은
전부 버린다. 이렇게 하면 "기본값 1,000 DPI" 같은 주석이 최댓값으로 오인되는 일과, "동글
사용 시 8,000Hz" 같은 조건부(별매 액세서리 필요) 보너스가 기본 스펙인 것처럼 섞이는 일을
같은 규칙으로 막는다. 대신 "옵션 동글 사용 시 최대 8,000Hz"처럼 조건부 값이 괄호 밖에 있는
경우까지는 걸러내지 못한다 — 원문 자체가 모호한 사례이고, 계획이 요구하는 정확도(괄호 안
기본값 함정 회피, 공란→None)를 넘어서는 완전한 자연어 이해는 범위 밖이다.

## 판정용 키 이름 규칙

파서가 만드는 값은 CSV/DB의 `_raw` 원문 컬럼과 겹치지 않는 새 이름을 쓴다. 이름은
Candidate.specs 에 그대로 들어간다(값이 없으면 키 자체를 넣지 않는다 — PC 로더
`_specs_from_row` 관례와 동일, src/engine/peripheral_catalog.py 가 이 규칙으로 조립한다).

| 원문 컬럼(`_raw`)                  | 파서 함수                | 판정용 키                                              |
|-----------------------------------|--------------------------|--------------------------------------------------------|
| `resolution_raw`                  | `parse_resolution`       | `resolution_w`, `resolution_h`, `resolution_class`      |
| `dpi_range_raw`                   | `parse_dpi_max`          | `dpi_max`                                               |
| `polling_rate_raw`                | `parse_polling_hz_max`   | `polling_hz_max`                                        |
| `switch_kind_raw` + `switch_method_raw` | `parse_switch`     | `switch_clicky`, `switch_magnetic`, `switch_low_profile`|
| `channels_raw`                    | `parse_channels`         | `channels`                                              |
| `output_power_raw`                | `parse_output_w`         | `output_w`                                              |
| `connectivity` + `connectivity_interface` (이미 배열) | `parse_connectivity` | `connectivity_wired`, `connectivity_wireless`, `connectivity_bluetooth` |

해상도 등급(`resolution_class`) 분류표는 코드가 아니라 `config/peripherals.yaml`의
`parsing.resolution_classes` 절에 있다(`src/engine/peripheral_rules.resolution_classes()`가
로드 시 형식을 검증한다) — 목록에 없는 (w, h) 조합은 파싱 실패가 아니라 `"OTHER"`다.
"""
from __future__ import annotations

import re
from typing import Any

# E10(peripheral_requirement.py)·로더 검증(peripheral_rules.py)이 참조하는 "이 모듈이 실제로
# 만들어낼 수 있는 판정용 키" 목록 — 위 표를 코드로 공개한 것이다. 종류별로 다르다(스위치
# 파서는 keyboard 전용, 채널/출력 파서는 speaker 전용 등). connectivity 파서는 keyboard·
# mouse·speaker 세 종류가 공유한다(모니터는 유선 연결만 있어 대상이 아니다).
PARSED_KEYS_BY_KIND: dict[str, frozenset[str]] = {
    "monitor": frozenset({"resolution_w", "resolution_h", "resolution_class"}),
    "keyboard": frozenset({
        "switch_clicky", "switch_magnetic", "switch_low_profile",
        "connectivity_wired", "connectivity_wireless", "connectivity_bluetooth",
    }),
    "mouse": frozenset({
        "dpi_max", "polling_hz_max",
        "connectivity_wired", "connectivity_wireless", "connectivity_bluetooth",
    }),
    "speaker": frozenset({
        "channels", "output_w",
        "connectivity_wired", "connectivity_wireless", "connectivity_bluetooth",
    }),
}

_PAREN_RE = re.compile(r"\([^()]*\)")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RESOLUTION_RE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")
_CHANNELS_RE = re.compile(r"^\d+(?:\.\d+)?$")
_OUTPUT_W_RE = re.compile(r"(\d+(?:\.\d+)?)\s*W", re.IGNORECASE)

_MAGNETIC_KEYWORDS = ("마그네틱", "magnetic", "hall effect", "홀 이펙트", "홀이펙트")
_NONMAGNETIC_METHOD_HINTS = ("기계식", "광학식", "정전용량", "팬터그래프", "scissor", "시저")
_LOW_PROFILE_KEYWORDS = ("로우프로파일", "저상형", "low-profile", "low profile", "scissor", "팬터그래프")
_TYPE_KEYWORDS = {
    "clicky": ("clicky", "클릭"),
    "tactile": ("tactile", "택타일"),
    "linear": ("linear", "리니어"),
}


def _clean(value: Any) -> str | None:
    """None/빈 문자열/공백만 있는 값을 None으로. 그 외는 앞뒤 공백만 정리한 문자열."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _max_number_outside_parens(text: str) -> float | None:
    """괄호 안 내용을 지우고 남은 텍스트에서 숫자를 전부 찾아 최댓값을 낸다.

    "200–8,000 DPI (기본값 1,000 DPI)" -> "200–8,000 DPI" -> 8000.0
    "최대 1,000Hz (1ms)" -> "최대 1,000Hz" -> 1000.0
    """
    stripped = _PAREN_RE.sub(" ", text)
    numbers = [float(n.replace(",", "")) for n in _NUMBER_RE.findall(stripped)]
    return max(numbers) if numbers else None


def parse_resolution(raw: Any, resolution_classes: dict[str, list[tuple[int, int]]] | None = None) -> dict | None:
    """"2560x1440" -> {"w": 2560, "h": 1440, "class": "QHD"}. 형식이 다르면 None.

    resolution_classes 는 config/peripherals.yaml 의 parsing.resolution_classes
    (src/engine/peripheral_rules.resolution_classes())를 그대로 받는다. 목록에 없는
    (w, h) 는 class="OTHER"(파싱 자체는 성공했으나 미분류라는 뜻 — None과 다르다).
    """
    text = _clean(raw)
    if text is None:
        return None
    match = _RESOLUTION_RE.match(text)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    classes = resolution_classes or {}
    cls = "OTHER"
    for name, pairs in classes.items():
        if any(int(w) == width and int(h) == height for w, h in pairs):
            cls = name
            break
    return {"w": width, "h": height, "class": cls}


def parse_dpi_max(raw: Any) -> float | None:
    """"200–8,000 DPI (기본값 1,000 DPI)" -> 8000.0. 공란/숫자 없음 -> None."""
    text = _clean(raw)
    if text is None:
        return None
    return _max_number_outside_parens(text)


def parse_polling_hz_max(raw: Any) -> float | None:
    """"125~2,000Hz" -> 2000.0, "최대 1,000Hz (1ms)" -> 1000.0, 공란 -> None."""
    text = _clean(raw)
    if text is None:
        return None
    return _max_number_outside_parens(text)


def parse_switch(kind_raw: Any, method_raw: Any) -> dict[str, bool | None]:
    """switch_kind_raw/switch_method_raw(축 종류/스위치 방식) -> 클릭형·마그네틱·로우프로파일 여부.

    항상 clicky/magnetic/low_profile 세 키를 다 낸다(형식은 peripheral_catalog.py 가
    None 이 아닌 것만 specs 에 옮긴다) — 판정 불가능한 축은 None.

    - magnetic: kind/method 어디든 "마그네틱"/"magnetic"/"hall effect" 가 있으면 True.
      스위치 방식이 채워져 있고(=기술 분류가 있고) 그런 낱말이 없으면 다른 알려진
      비마그네틱 기술(기계식/광학식/정전용량/시저 등)로 보고 False. 방식 자체가 없으면 None.
    - clicky: "clicky/tactile/linear" 중 정확히 하나만 언급되면 그 값(clicky 여부)을 쓴다.
      "GL Linear / GL Tactile / GL Clicky" 처럼 여러 방식을 나열한 원문은 실제로 어느
      쪽을 쓰는지 알 수 없어 None(0개 언급도 None).
    - low_profile: "로우프로파일"/"low-profile"/"저상형"/시저·팬터그래프 언급이 있으면 True.
      방식이 채워져 있는데 언급이 없으면 표준 높이로 보고 False. 방식이 없으면 None.
    """
    kind_text = _clean(kind_raw) or ""
    method_text = _clean(method_raw) or ""
    combined = f"{kind_text} {method_text}".lower()

    if any(keyword in combined for keyword in _MAGNETIC_KEYWORDS):
        magnetic: bool | None = True
    elif method_text and any(keyword in method_text.lower() for keyword in _NONMAGNETIC_METHOD_HINTS):
        magnetic = False
    else:
        magnetic = None

    present_types = [name for name, keywords in _TYPE_KEYWORDS.items() if any(k in combined for k in keywords)]
    clicky: bool | None = (present_types[0] == "clicky") if len(present_types) == 1 else None

    if any(keyword in combined for keyword in _LOW_PROFILE_KEYWORDS):
        low_profile: bool | None = True
    elif method_text:
        low_profile = False
    else:
        low_profile = None

    return {"clicky": clicky, "magnetic": magnetic, "low_profile": low_profile}


def parse_channels(raw: Any) -> float | None:
    """"2" -> 2.0, "2.1" -> 2.1. 숫자 형식이 아니면 None."""
    text = _clean(raw)
    if text is None or not _CHANNELS_RE.match(text):
        return None
    return float(text)


def parse_output_w(raw: Any) -> float | None:
    """"24W" -> 24.0, "10W (5Wx2)" -> 10.0(괄호 안 채널별 분배는 무시하고 총 출력만).

    괄호 안에 있는 숫자는 버리고(위 DPI/폴링레이트와 같은 규칙), 남은 텍스트에서 처음
    나오는 "<숫자>W" 하나만 총 출력으로 본다.
    """
    text = _clean(raw)
    if text is None:
        return None
    stripped = _PAREN_RE.sub(" ", text)
    match = _OUTPUT_W_RE.search(stripped)
    return float(match.group(1)) if match else None


def parse_connectivity(
    connectivity: list[str] | None, connectivity_interface: list[str] | None = None
) -> dict[str, bool | None]:
    """connectivity(유선/무선 배열) + connectivity_interface(USB/Bluetooth 등 배열) ->
    wired/wireless/bluetooth bool 세 개. connectivity 가 없으면(=값 자체가 없음) 셋 다 None
    — "무선이 아니다"를 추측하지 않는다."""
    if not connectivity:
        return {"wired": None, "wireless": None, "bluetooth": None}
    values = {str(v).strip() for v in connectivity if str(v).strip()}
    wired = "유선" in values
    wireless = "무선" in values
    interfaces = [str(v).strip().lower() for v in (connectivity_interface or []) if str(v).strip()]
    bluetooth: bool | None = any("bluetooth" in v for v in interfaces) if interfaces else None
    return {"wired": wired, "wireless": wireless, "bluetooth": bluetooth}

"""호환 검사용 표기 해석 — 카탈로그의 사람이 쓴 문자열을 비교 가능한 값으로 바꾼다.

두 가지를 다룬다.
- 쿨러의 지원 소켓("LGA1851/1700/1200/115x, AM5/AM4")을 소켓 목록으로. 약어("1700"은 앞의 LGA 를 이어받는다)와
  와일드카드("115x")를 풀지 않고 문자열 포함으로 비교하면 "LGA1851/1700" 안에서 "LGA1700"을 못 찾아
  LGA1700 CPU 와 맞는 쿨러가 비호환으로 판정됐다(2026-09-21, 조합 600개 중 150개가 오판).
- CPU 이름에서 세대·계열을 읽어 메인보드의 "지원 CPU 계열"과 비교(BIOS 축). 카탈로그의 계열 표기는
  "Ryzen 7000 / 8000G / 9000 계열", "Intel Core 12 / 13 / 14세대", "Intel Core Ultra 200S / Plus 계열" 이다.

읽지 못하면 None(모름)을 돌려준다 — 모르는 것을 비호환으로 단정하지 않는다(호출부가 "근사"로 남긴다).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any


# ── 소켓 ─────────────────────────────────────────────────────────────────────
def _norm_socket(text: str) -> str:
    return re.sub(r"[\s\-]", "", str(text)).upper()


@lru_cache(maxsize=512)
def _socket_patterns(text: str) -> tuple[str, ...]:
    patterns: list[str] = []
    for group in re.split(r"[,;]", text):
        prefix = ""
        for token in (t for t in re.split(r"/", group) if t.strip()):
            token = _norm_socket(token)
            m = re.match(r"[A-Z]+", token)
            if m:
                prefix = m.group(0)
            elif prefix:
                token = prefix + token
            else:
                continue
            patterns.append(token.replace("X", "."))
    return tuple(patterns)


def parse_socket_list(value: Any) -> list[str]:
    """지원 소켓 표기 → 정규식 패턴 목록(대문자, 공백·하이픈 없음, x 는 한 글자 와일드카드).

    "LGA1851/1700/1200/115x, AM5/AM4" → LGA1851, LGA1700, LGA1200, LGA115., AM5, AM4.
    슬래시로 이어진 뒤쪽 토큰이 숫자뿐이면 앞 토큰의 접두(LGA·AM)를 이어받는다. 리스트도 받는다."""
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [p for item in items for p in _socket_patterns(str(item or ""))]


def socket_supported(cpu_socket: str | None, supported: Any) -> bool | None:
    """쿨러(또는 보드)의 지원 소켓 표기에 cpu_socket 이 있는가. 어느 한쪽을 모르면 None."""
    if not cpu_socket or not supported:
        return None
    patterns = parse_socket_list(supported)
    if not patterns:
        return None
    socket = _norm_socket(cpu_socket)
    return any(re.fullmatch(p, socket) for p in patterns)


# ── CPU 계열(BIOS 축) ──────────────────────────────────────────────────────────
_RYZEN = re.compile(r"ryzen\s*(?:ai\s*)?(?:[3579]\s*)?(?:pro\s*)?(\d{4})\s*([a-z0-9]*)", re.IGNORECASE)
_CORE_I = re.compile(r"\bi[3579][\s-]*(\d{4,5})", re.IGNORECASE)
_ULTRA = re.compile(r"core\s*ultra\s*[3579]?\s*(\d{3})", re.IGNORECASE)


@lru_cache(maxsize=512)
def cpu_family(name: str | None) -> str | None:
    """CPU 이름 → 계열 키("ryzen:7000", "ryzen:8000G", "core:14", "ultra:200S", "ultra:PLUS"). 못 읽으면 None.

    Ryzen 은 첫 자리로 세대(7600 → 7000), 4000·8000 번대의 G 는 별도 계열(APU). Core 는 세대(14600K → 14),
    Core Ultra 는 3자리 모델의 첫 자리(265K → 200S). "Plus" 표기가 붙은 Ultra 는 Plus 계열."""
    text = str(name or "")
    m = _ULTRA.search(text)
    if m:
        return "ultra:PLUS" if re.search(r"\bplus\b", text, re.IGNORECASE) else f"ultra:{m.group(1)[0]}00S"
    m = _RYZEN.search(text)
    if m:
        series = m.group(1)[0] + "000"
        return f"ryzen:{series}G" if series in ("4000", "8000") and m.group(2).upper().startswith("G") else f"ryzen:{series}"
    m = _CORE_I.search(text)
    if m:
        digits = m.group(1)
        return f"core:{int(digits[:-3])}"
    return None


@lru_cache(maxsize=128)
def supported_families(text: str | None) -> set[str]:
    """메인보드의 "지원 CPU 계열" 표기 → 계열 키 집합. 읽지 못하면 빈 집합(모름)."""
    t = str(text or "")
    if re.search(r"ryzen", t, re.IGNORECASE):
        return {f"ryzen:{n}{g.upper()}" for n, g in re.findall(r"(\d{4})\s*(G?)", t, re.IGNORECASE)}
    if re.search(r"ultra", t, re.IGNORECASE):
        found = {f"ultra:{n}S" for n in re.findall(r"(\d{3})\s*S\b", t, re.IGNORECASE)}
        if re.search(r"\bplus\b", t, re.IGNORECASE):
            found.add("ultra:PLUS")
        return found
    if re.search(r"core", t, re.IGNORECASE):
        return {f"core:{n}" for n in re.findall(r"\d+", re.split(r"core", t, maxsplit=1, flags=re.IGNORECASE)[1])}
    return set()


def cpu_supported(cpu_name: str | None, board_supported_text: str | None) -> bool | None:
    """CPU 이름의 계열이 보드의 지원 계열 목록에 있는가. CPU 나 목록을 읽지 못하면 None(모름)."""
    family, allowed = cpu_family(cpu_name), supported_families(board_supported_text)
    if family is None or not allowed:
        return None
    return family in allowed


# ── 파워 폼팩터 ↔ 케이스 ───────────────────────────────────────────────────────
# 크기 순서: SFX < SFX-L < ATX. 케이스가 지원하는 것 중 가장 큰 것보다 파워가 크면 물리적으로 안 들어간다.
_PSU_FORM_RANK = {"TFX": 1, "FLEX": 1, "SFX": 2, "SFX-L": 3, "ATX": 4}


@lru_cache(maxsize=128)
def parse_psu_forms(text: Any) -> tuple[str, ...]:
    """"SFX / SFX-L", "ATX / SFX-L 확인" → ("SFX", "SFX-L") / ("ATX", "SFX-L"). 못 읽으면 빈 튜플."""
    found = re.findall(r"SFX[\s_-]*L|SFX|ATX|TFX|FLEX", str(text or "").upper())
    out: list[str] = []
    for token in found:
        token = "SFX-L" if token.startswith("SFX") and token.endswith("L") else token
        if token not in out:
            out.append(token)
    return tuple(out)


def psu_fits_case(psu_form: Any, case_forms: Any) -> str | None:
    """"ok"(케이스가 그 폼팩터를 지원) / "adapter"(더 작은 파워 — 어댑터 브래킷이 있어야 들어감) /
    "fail"(케이스가 지원하는 가장 큰 폼팩터보다 큼) / None(파워나 케이스 표기를 못 읽음)."""
    psu, case = parse_psu_forms(psu_form), parse_psu_forms(case_forms)
    if len(psu) != 1 or not case:
        return None
    if psu[0] in case:
        return "ok"
    return "fail" if _PSU_FORM_RANK[psu[0]] > max(_PSU_FORM_RANK[c] for c in case) else "adapter"


# ── GPU 전원 커넥터 ↔ 파워 ─────────────────────────────────────────────────────
_HAS_16 = re.compile(r"16\s*-?\s*pin|12V-?2X6|12VHPWR", re.IGNORECASE)
_HAS_PCIE = re.compile(r"(?<!\d)[68]\s*-?\s*pin|PCIe", re.IGNORECASE)


def gpu_connector_fit(gpu_connector: Any, gpu_aux: Any, psu_connector: Any) -> str | None:
    """GPU 가 요구하는 보조 전원 커넥터를 파워가 제공하는가.

    "ok" / "adapter"(GPU 는 16핀인데 파워는 PCIe 8핀뿐 — GPU 에 동봉되는 어댑터가 필요) / None(모름).
    파워의 표기에 16핀만 적혀 있어도 PCIe 8핀은 함께 있다고 본다(ATX 3.x 파워는 둘 다 제공). 케이블 개수는 데이터에 없어
    "2× 8-pin"이 요구하는 개수까지는 확인하지 못한다."""
    gpu = str(gpu_connector or "").strip()
    if not gpu:
        return None
    if str(gpu_aux or "").strip().upper() == "X" or "슬롯 전력" in gpu:
        return "ok"                                   # 보조 전원이 필요 없다
    psu = str(psu_connector or "")
    psu_16 = bool(_HAS_16.search(psu))
    psu_pcie = bool(_HAS_PCIE.search(psu)) or psu_16
    if not psu_16 and not psu_pcie:
        return None
    if _HAS_16.search(gpu):
        return "ok" if psu_16 else "adapter"
    if re.search(r"(?<!\d)[68]\s*-?\s*pin", gpu, re.IGNORECASE):
        return "ok" if psu_pcie else None
    return None


# ── GPU 전원 커넥터 개수 ↔ 파워 커넥터 개수 ───────────────────────────────────────
_CONN = re.compile(r"(?:(\d+)\s*[×xX]\s*)?(\d+)\s*-?\s*pin", re.IGNORECASE)


@lru_cache(maxsize=128)
def gpu_power_options(text: Any) -> tuple[tuple[int, int], ...] | None:
    """GPU 전원 커넥터 표기 → 선택지 목록, 선택지는 (PCIe 6/8핀 개수, 16핀 개수).

    "2× 8-pin" → ((2, 0),), "1× 8-pin + 1× 6-pin" → ((2, 0),), "1× 16-pin 또는 2× 8-pin" → ((0, 1), (2, 0)),
    "1× 8-pin 또는 16-pin" → ((1, 0), (0, 1)). 보조 전원이 필요 없거나("슬롯 전력") 읽지 못하면 None."""
    raw = str(text or "")
    if not raw.strip() or "슬롯" in raw:
        return None
    options: list[tuple[int, int]] = []
    for part in re.split(r"또는|\bor\b", raw, flags=re.IGNORECASE):
        pcie = sixteen = 0
        found = False
        for count, size in _CONN.findall(part):
            n = int(count) if count else 1
            found = True
            if size == "16":
                sixteen += n
            elif size in ("6", "8"):
                pcie += n
        if found and (pcie or sixteen):
            options.append((pcie, sixteen))
    return tuple(options) or None


def gpu_power_count_fit(gpu_connector: Any, gpu_aux: Any, psu_pcie: int | None,
                        psu_16: int | None) -> tuple[str | None, str]:
    """개수까지 본 판정 → ("ok" | "fail" | "adapter" | None, 설명). None 은 개수 데이터가 없어 판단 못 함(호출부가 표기 기반으로 되돌린다).

    - 선택지 중 하나라도 파워가 채우면 ok. 모든 선택지를 판정했는데 다 모자라면:
      16핀 선택지가 있고 PCIe 커넥터가 2개 이상이면 동봉 어댑터로 연결하는 경우(adapter), 아니면 fail.
    - 파워의 개수를 모르는 선택지가 있고 채워지는 선택지가 없으면 None."""
    if str(gpu_aux or "").strip().upper() == "X":
        return "ok", "보조 전원 불필요"
    options = gpu_power_options(gpu_connector)
    if not options:
        return None, ""
    unknown = False
    for pcie, sixteen in options:
        if pcie and not sixteen:
            if psu_pcie is None:
                unknown = True
            elif psu_pcie >= pcie:
                return "ok", f"필요 PCIe 커넥터 {pcie}개 ≤ 파워 제공 {psu_pcie}개"
        elif sixteen and not pcie:
            if psu_16 is None:
                unknown = True
            elif psu_16 >= sixteen:
                return "ok", f"필요 16핀 {sixteen}개 ≤ 파워 제공 {psu_16}개"
        else:
            unknown = True                        # 혼합 표기는 해석하지 않는다
    if unknown:
        return None, ""
    needs_pcie = min((p for p, s in options if p and not s), default=None)
    if any(s for _, s in options) and psu_pcie is None:
        return None, ""                       # 16핀이 없는데 어댑터로 연결할 PCIe 커넥터 수를 모르면 실패로 단정하지 않는다
    if any(s for _, s in options) and psu_pcie is not None and psu_pcie >= 2:
        return "adapter", f"16핀이 없어 PCIe 커넥터 {psu_pcie}개로 동봉 어댑터를 연결해야 합니다"
    want = "16핀" if needs_pcie is None else f"PCIe 커넥터 {needs_pcie}개"
    have = f"16핀 {psu_16}개 · PCIe {psu_pcie}개"
    return "fail", f"필요 {want} > 파워 제공 {have}"


# ── 수랭 라디에이터 ↔ 케이스, RAM 모듈 수, M.2 세대, GPU 슬롯 ─────────────────────────
def parse_size_list(text: Any) -> tuple[int, ...]:
    """'120;140;240;280' 또는 '360'(숫자) → (120, 140, 240, 280). 못 읽으면 빈 튜플."""
    return tuple(int(n) for n in re.findall(r"\d+", str(text or "")))


def parse_module_count(module_config: Any) -> int | None:
    """'16GB × 2' → 2. 못 읽으면 None."""
    m = re.search(r"[×xX]\s*(\d+)", str(module_config or ""))
    return int(m.group(1)) if m else None


def parse_pcie_gens(text: Any) -> tuple[float, ...]:
    """'PCIe 4.0 x4 / 5.0 x2' → (4.0, 5.0), '5;4;4' → (5.0, 4.0, 4.0). 세대로 읽히는 숫자만(레인 수 x4 는 제외)."""
    raw = str(text or "")
    if ";" in raw and re.fullmatch(r"[\d.;\s]+", raw):
        return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw))
    return tuple(float(n) for n in re.findall(r"(?<![xX\d.])(\d\.\d)(?!\d)", raw))


def slots_needed(thickness: Any) -> int | None:
    """GPU 슬롯 두께 2.5 → 3칸(올림). 못 읽으면 None."""
    try:
        return int(-(-float(thickness) // 1))
    except (TypeError, ValueError):
        return None

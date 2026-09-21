"""[업그레이드] 사용자가 그대로 쓰는 부품 -> 호환성 검사에 쓸 스펙.

사양 파일/조건의 current_specs 는 "i5-13600K", "RTX 3060", "DDR4 16GB" 같은 자유 표기다. 카탈로그
부품과 대응되면 그 스펙(소켓·메모리 타입·전력·길이 …)을, 아니면 글에서 확실히 읽히는 것만
(소켓·DDR 세대·파워 용량) 쓴다. 지어내지 않는다: 대응이 모호하면 후보들이 *모두 같은* 값만 남기고,
근거가 없으면 그 부품은 비워 둔다 — 호환 검사가 "모름"으로 넘기고 실패로 단정하지 않는다.
DB·LLM 없이 도는 순수 함수다."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from src.dto import Candidate
from src.engine.stage2_requirement import normalize_pc_slot

# 모델 식별에 도움이 안 되는 말 — 비교에서 뺀다.
_GENERIC = {"nvidia", "geforce", "amd", "radeon", "intel", "core", "ryzen", "gb", "tb", "mhz", "rgb", "ddr",
            "그래픽카드", "그래픽", "프로세서", "메모리"}
_SOCKET = re.compile(r"\b(AM[345]|LGA\s*-?\s*\d{3,4})\b", re.IGNORECASE)
_DDR = re.compile(r"\bDDR\s*([345])\b", re.IGNORECASE)
_WATT = re.compile(r"(\d{3,4})\s*W\b", re.IGNORECASE)
_MODEL_DIGITS = re.compile(r"\d{3,}")


def _tokens(text: str) -> list[str]:
    parts = (re.sub(r"[^0-9a-z가-힣]", "", p.lower()) for p in re.split(r"[\s,/()]+", str(text)))
    return [p for p in parts if p]


def _significant(tokens: Iterable[str]) -> list[str]:
    return [t for t in tokens if t not in _GENERIC and not re.fullmatch(r"\d+(gb|tb)", t)]


def _match_catalog(text: str, pool: list[Candidate]) -> list[Candidate]:
    """텍스트의 의미 있는 토큰이 전부 후보 이름의 토큰과 *정확히* 같고(부분 일치 아님 — 5600 은 5600X 가
    아니다), 모델 번호로 보이는 토큰(숫자 3자리 이상)이 하나는 있어야 대응으로 본다. 그중 군더더기 토큰이
    가장 적은 후보들만 남긴다(RTX 3060 과 RTX 3060 Ti 를 구분)."""
    wanted = _significant(_tokens(text))
    if not wanted or not any(_MODEL_DIGITS.search(t) for t in wanted):
        return []
    scored: list[tuple[int, Candidate]] = []
    for cand in pool:
        have = _significant(_tokens(cand.name))
        if all(t in have for t in wanted):
            scored.append((len(set(have) - set(wanted)), cand))
    if not scored:
        return []
    best = min(extra for extra, _ in scored)
    return [cand for extra, cand in scored if extra == best]


def _common_specs(matches: list[Candidate]) -> dict[str, Any]:
    """여러 후보에 걸리면 전부 같은 값만 남긴다 — 확실한 것만 쓴다."""
    first = dict(matches[0].specs)
    return {k: v for k, v in first.items() if all(m.specs.get(k) == v for m in matches[1:])}


# ── 모델명·칩셋 규칙으로 소켓 추론 ───────────────────────────────────────────────────────────
# 카탈로그에 없는 부품(단종·구형)은 DB 스펙이 없다. 다만 소켓은 제품명 자체가 알려 준다 — CPU 는 세대
# (i5-8400 = 8세대 = LGA1151, Ryzen 5 3600 = 3천번대 = AM4), 메인보드는 칩셋(B450 = AM4, B760 = LGA1700).
# 공개된 명명 관례라 규칙표로 충분하고, 읽지 못하면 "모름"으로 남긴다(노트북 접미사 H/U/G7 등은
# 데스크톱 소켓이 없어 추론하지 않는다). 전력(TDP)은 같은 세대 안에서도 모델마다 달라 규칙으로 못 읽는다.
_INTEL_GEN_SOCKET = {2: "LGA1155", 3: "LGA1155", 4: "LGA1150", 6: "LGA1151", 7: "LGA1151", 8: "LGA1151",
                     9: "LGA1151", 10: "LGA1200", 11: "LGA1200", 12: "LGA1700", 13: "LGA1700", 14: "LGA1700"}
_AMD_SERIES_SOCKET = {"1": "AM4", "2": "AM4", "3": "AM4", "4": "AM4", "5": "AM4", "7": "AM5", "8": "AM5", "9": "AM5"}
_INTEL_DESKTOP_SUFFIX = {"", "F", "K", "KF", "KS", "S", "T"}
_AMD_DESKTOP_SUFFIX = re.compile(r"(X3D2?|XT|X|GE|GT|G|F)?")
_CHIPSET_SOCKET = {
    **{c: "AM4" for c in ("A320", "B350", "X370", "B450", "X470", "A520", "B550", "X570")},
    **{c: "AM5" for c in ("A620", "B650", "B650E", "X670", "X670E", "B840", "B850", "X870", "X870E")},
    **{c: "LGA1151" for c in ("H110", "B150", "H170", "Z170", "B250", "H270", "Z270", "H310", "B360", "H370",
                             "Z370", "B365", "Z390")},
    **{c: "LGA1200" for c in ("H410", "B460", "H470", "Z490", "H510", "B560", "H570", "Z590")},
    **{c: "LGA1700" for c in ("H610", "B660", "H670", "Z690", "B760", "H770", "Z790")},
    **{c: "LGA1851" for c in ("H810", "B860", "Z890")},
}
_CHIPSET = re.compile(r"(?<![A-Z0-9])(" + "|".join(sorted(_CHIPSET_SOCKET, key=len, reverse=True)) + r")(?![0-9])")
# 소켓만으로 메모리 세대가 정해지는 경우만(LGA1700 은 보드마다 DDR4/DDR5 라서 모름).
_SOCKET_MEM = {"AM4": "DDR4", "AM5": "DDR5", "LGA1200": "DDR4", "LGA1851": "DDR5"}


def _normalise_name(text: str) -> str:
    t = str(text).upper()
    for korean, english in (("라이젠", "RYZEN"), ("코어 울트라", "CORE ULTRA"), ("코어울트라", "CORE ULTRA"),
                            ("인텔", "INTEL"), ("코어", "CORE")):
        t = t.replace(korean.upper(), english)
    return t


def infer_cpu_socket(text: str) -> str | None:
    t = _normalise_name(text)
    ultra = re.search(r"CORE\s*ULTRA\s*[3579]\s*(\d{3})([A-Z]*)", t)
    if ultra:
        # 데스크톱 Core Ultra 200S 는 2xx(+K/KF/F/PLUS). 1xx(+H/U/V)는 모바일이라 소켓이 없다.
        return "LGA1851" if ultra.group(1).startswith("2") and not ultra.group(2).startswith(("H", "U", "V")) else None
    intel = re.search(r"\bI[3579]\s*-?\s*(\d{4,5})([A-Z]*)\b", t)
    if intel:
        digits, suffix = intel.group(1), intel.group(2)
        if suffix not in _INTEL_DESKTOP_SUFFIX:
            return None
        gen = int(digits[:2]) if len(digits) == 5 else int(digits[0])
        return _INTEL_GEN_SOCKET.get(gen)
    amd = re.search(r"RYZEN\s*(?:AI\s*)?[3579]?\s*(\d{4})([A-Z0-9]*)", t)
    if amd and _AMD_DESKTOP_SUFFIX.fullmatch(amd.group(2)):
        return _AMD_SERIES_SOCKET.get(amd.group(1)[0])
    return None


def infer_board_socket(text: str) -> str | None:
    chipset = _CHIPSET.search(str(text).upper())
    return _CHIPSET_SOCKET.get(chipset.group(1)) if chipset else None


def _specs_from_text(slot: str, text: str) -> tuple[dict[str, Any], set[str]]:
    """카탈로그와 대응되지 않을 때 글에서 읽는다. (스펙, 규칙으로 *추정*한 키). 글에 그대로 적힌 값은 확정,
    모델명·칩셋 규칙으로 얻은 값은 추정으로 구분해 남긴다."""
    specs: dict[str, Any] = {}
    inferred: set[str] = set()
    if slot in ("CPU", "메인보드"):
        socket = _SOCKET.search(text)
        if socket:
            specs["socket"] = re.sub(r"[\s-]", "", socket.group(1)).upper()
        else:
            guess = infer_cpu_socket(text) if slot == "CPU" else infer_board_socket(text)
            if guess:
                specs["socket"], _ = guess, inferred.add("socket")
    if slot in ("메인보드", "RAM"):
        ddr = _DDR.search(text) or re.search(r"(?<![A-Z0-9])D([45])(?![A-Z0-9])", str(text).upper())
        if ddr:
            specs["mem_type"] = f"DDR{ddr.group(1)}"
        elif slot == "메인보드" and specs.get("socket") in _SOCKET_MEM:
            specs["mem_type"], _ = _SOCKET_MEM[specs["socket"]], inferred.add("mem_type")
    if slot == "파워":
        watt = _WATT.search(text)
        if watt:
            specs["wattage_w"] = int(watt.group(1))
    return specs, inferred


def resolve_owned_parts(current_specs: Any, by_slot: dict[str, list[Candidate]],
                        keep_slots: Iterable[str]) -> dict[str, dict[str, Any]]:
    """keep_slots(견적에서 빠지는 = 사용자가 그대로 쓰는 슬롯) 중 사용자가 적어 준 것만 해석한다.

    반환: slot -> {"name", "specs", "source"}. source 는 catalog(카탈로그 대응) / text(글에 적힌 값) /
    inferred(모델명·칩셋 규칙으로 추정한 값 포함 — "inferred" 키에 어느 스펙인지) /
    unverified(적었지만 검사에 쓸 값이 없음)."""
    if not isinstance(current_specs, dict):
        return {}
    given = {(normalize_pc_slot(k) or str(k).strip()): v for k, v in current_specs.items()}
    owned: dict[str, dict[str, Any]] = {}
    for slot in keep_slots:
        text = given.get(slot)
        if not text or not str(text).strip():
            continue
        text = str(text).strip()
        # RAM 은 용량("32GB")만으로는 제품을 특정할 수 없어 카탈로그 대응을 하지 않는다.
        matches = [] if slot == "RAM" else _match_catalog(text, by_slot.get(slot, []))
        if matches:
            owned[slot] = {"name": matches[0].name if len(matches) == 1 else text,
                           "specs": _common_specs(matches), "source": "catalog"}
            continue
        specs, inferred = _specs_from_text(slot, text)
        owned[slot] = {"name": text, "specs": specs,
                       "source": "unverified" if not specs else "inferred" if inferred else "text"}
        if inferred:
            owned[slot]["inferred"] = sorted(inferred)
    return owned


def constrain_targets(spec) -> None:
    """유지하는 부품이 정해 주는 플랫폼(소켓·메모리 타입)을 견적 대상 슬롯의 요구로 못 박는다.

    용도 프로필의 소켓·DDR 하한은 "새로 조립할 때의 기본"이라, AM4 보드를 그대로 쓰면서 CPU 만
    바꾸려는 사람에게 적용하면 후보가 전멸한다. 그 경우엔 유지 부품의 값이 하한을 대신한다.
    유지 부품을 모르면(키 없음) 건드리지 않는다."""
    def owned(slot: str, key: str):
        return ((spec.owned.get(slot) or {}).get("specs") or {}).get(key)

    board_socket, cpu_socket = owned("메인보드", "socket"), owned("CPU", "socket")
    board_mem, ram_mem = owned("메인보드", "mem_type"), owned("RAM", "mem_type")
    if "CPU" in spec.targets and board_socket:
        spec.targets["CPU"]["socket_in"] = [board_socket]
    if "메인보드" in spec.targets:
        if cpu_socket:
            spec.targets["메인보드"]["socket_in"] = [cpu_socket]
        if ram_mem:
            spec.targets["메인보드"]["mem_type"] = ram_mem
    if "RAM" in spec.targets and board_mem:
        spec.targets["RAM"]["type"] = board_mem


def owned_for_conditions(values: dict, by_slot: dict[str, list[Candidate]], target_slots: Iterable[str],
                         slot_structure: Iterable[str]) -> dict[str, dict[str, Any]]:
    """조건(values)에서 "견적 대상이 아닌 = 그대로 쓰는" 부품을 해석한다. 추천 실행과 대안 목록이
    같은 결과를 쓰도록 이 한 곳만 거친다. 신규 조립(build)에는 유지 부품이 없다."""
    if values.get("mode") != "upgrade":
        return {}
    targets = set(target_slots)
    keep = [slot for slot in slot_structure if slot not in targets]
    owned = resolve_owned_parts(values.get("current_specs"), by_slot, keep)
    _fill_platform(owned, values, targets, keep)
    return owned


def _ensure(owned: dict, slot: str, name: str) -> dict:
    return owned.setdefault(slot, {"name": name, "specs": {}, "source": "unverified"})


def _fill_platform(owned: dict[str, dict[str, Any]], values: dict, targets: set[str], keep: list[str]) -> None:
    """CPU·메인보드·RAM 은 한 플랫폼이라 하나를 알면 다른 쪽도 안다. 유지하는 부품에 빠진 값을 채운다.

    소켓 출처의 우선순위: (1) 사용자가 칩으로 답한 세대 (2) 유지하는 CPU/보드에서 이미 읽은 소켓
    (3) *교체하는* CPU/보드의 기존 모델(사양 파일) — 새 CPU 를 사려는 사람의 옛 CPU 소켓이 곧 유지하는
    보드의 소켓이다. 글에 적힌 값·카탈로그 값은 덮지 않는다(빠진 것만). (3)은 추정이라 근거를 남긴다.
    "unknown" 답은 아무것도 채우지 않는다."""
    slots = [s for s in ("CPU", "메인보드") if s in keep]
    socket, basis, from_answer = None, None, False
    answer = values.get("owned_platform")
    if answer and answer != "unknown":
        socket, from_answer = str(answer), True
    if socket is None:
        for slot in ("CPU", "메인보드"):
            known = ((owned.get(slot) or {}).get("specs") or {}).get("socket")
            if known:
                socket, basis = known, {"kind": "kept", "slot": slot, "model": (owned.get(slot) or {}).get("name", "")}
                break
    if socket is None:
        given = values.get("current_specs") if isinstance(values.get("current_specs"), dict) else {}
        for slot in ("CPU", "메인보드"):
            text = given.get(slot)
            if slot in targets and text:
                guess, _ = _specs_from_text(slot, str(text))
                if guess.get("socket"):
                    socket, basis = guess["socket"], {"kind": "replaced", "slot": slot, "model": str(text).strip()}
                    break
    if socket:
        for slot in slots:
            entry = _ensure(owned, slot, f"{socket} 플랫폼")
            if entry["specs"].get("socket"):
                continue
            entry["specs"]["socket"] = socket
            if from_answer:
                entry["source"] = "answer" if entry["source"] == "unverified" else entry["source"]
            else:
                entry["source"] = "inferred"
                entry["inferred"] = sorted(set(entry.get("inferred") or []) | {"socket"})
                entry["basis"] = basis
    ram = values.get("owned_ram_type")
    if ram and ram != "unknown":
        for slot in [s for s in ("RAM", "메인보드") if s in keep]:
            entry = _ensure(owned, slot, f"{ram} 메모리")
            if not entry["specs"].get("mem_type"):
                entry["specs"]["mem_type"] = str(ram)
                entry["source"] = "answer" if entry["source"] == "unverified" else entry["source"]
    psu = values.get("owned_psu_w")
    if psu and psu != "unknown" and "파워" in keep:
        entry = _ensure(owned, "파워", f"{psu}W 이상급")
        if not entry["specs"].get("wattage_w"):
            entry["specs"]["wattage_w"] = int(psu)
            entry["source"] = "answer" if entry["source"] == "unverified" else entry["source"]


# ── 안내 문장 ────────────────────────────────────────────────────────────────────────────────
# 업그레이드로 바꾸는 부품(키)이 호환을 보려면 유지 부품의 어떤 정보가 필요한가:
# (유지 슬롯, 정보 이름 ko/en, 그 정보를 담은 스펙 키 중 하나라도 있으면 충족)
UPGRADE_NEEDS: dict[str, tuple[tuple[str, tuple[str, str], tuple[str, ...]], ...]] = {
    "CPU": (("메인보드", ("소켓", "socket"), ("socket",)),),
    "메인보드": (("CPU", ("소켓", "socket"), ("socket",)), ("RAM", ("메모리 종류", "memory type"), ("mem_type",)),
             ("케이스", ("지원 보드 크기", "supported board sizes"), ("supports_form_factors",))),
    "RAM": (("메인보드", ("메모리 종류", "memory type"), ("mem_type",)),),
    "GPU": (("파워", ("정격 용량", "rated wattage"), ("wattage_w",)),
            ("케이스", ("GPU 장착 공간", "GPU clearance"), ("max_gpu_len_mm",))),
    "파워": (("GPU", ("권장 파워", "recommended PSU"), ("recommended_psu_w", "power_w")),),
    "쿨러": (("CPU", ("소켓", "socket"), ("socket",)), ("케이스", ("쿨러 높이 여유", "cooler clearance"), ("max_cooler_height_mm",))),
    "케이스": (("메인보드", ("보드 크기", "board size"), ("form_factor",)), ("GPU", ("길이", "length"), ("length_mm",))),
}
_EN_SLOT = {"CPU": "CPU", "GPU": "GPU", "RAM": "RAM", "메인보드": "motherboard", "저장장치": "storage",
            "파워": "power supply", "케이스": "case", "쿨러": "cooler"}


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침 유무로 조사를 고른다(소켓+을, 파워+를). 한글이 아니면 받침 없음으로 본다."""
    last = str(word).rstrip()[-1:]
    has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return word + (with_batchim if has else without)


def upgrade_scope_note(target_slots: Iterable[str], lang: str = "ko") -> str:
    """이번 견적에 무엇이 들어 있고 무엇이 빠졌는지 — 요약이 새 컴퓨터 한 대처럼 읽히지 않게."""
    slots = list(target_slots)
    if not slots:
        return ""
    if lang == "en":
        return (f" This quote covers only the {', '.join(_EN_SLOT.get(s, s) for s in slots)}; the rest of your PC"
                " is assumed to stay as it is.")
    return f" 이번 견적은 {', '.join(slots)}만 포함해요. 나머지 부품은 지금 쓰는 것을 그대로 쓰는 것으로 봤어요."


def upgrade_notes(target_slots: Iterable[str], owned: dict[str, dict[str, Any]], lang: str = "ko") -> list[str]:
    """유지 부품 정보가 부족해 호환을 다 확인하지 못한 곳을 문장으로 — "확인이 필요한 것"에 실린다.
    코드가 아는 사실(무엇을 못 읽었는지)만 적는다. 같은 (유지 부품, 정보)는 한 번만."""
    targets = set(target_slots)
    seen: set[tuple[str, str]] = set()
    notes: list[str] = []
    for target in target_slots:
        for kept, (aspect_ko, aspect_en), keys in UPGRADE_NEEDS.get(target, ()):
            if kept in targets or (kept, aspect_ko) in seen:
                continue
            seen.add((kept, aspect_ko))
            info = owned.get(kept)
            specs = (info or {}).get("specs") or {}
            hit = next((k for k in keys if k in specs), None)
            name = (info or {}).get("name")
            if hit and hit in ((info or {}).get("inferred") or []) and (info or {}).get("basis"):
                guess, basis = specs[hit], info["basis"]
                other, model = basis["slot"], basis["model"]
                if lang == "en":
                    source = (f"the model name of the {_EN_SLOT.get(other, other)} you are replacing ({model})"
                              if basis["kind"] == "replaced" else f"the {_EN_SLOT.get(other, other)} you keep")
                    notes.append(f"Your {_EN_SLOT.get(kept, kept)}: {aspect_en} assumed to be {guess} from {source} — check before buying.")
                else:
                    source = (f"교체하는 {other}({model})의 모델명으로 보아" if basis["kind"] == "replaced"
                              else f"유지하는 {other}와 같은 플랫폼이라고 보고")
                    notes.append(f"현재 {kept}의 {_josa(aspect_ko, '은', '는')} {source} {guess}일 것으로 추정했어요 — 구매 전 확인하세요.")
            elif hit and hit in ((info or {}).get("inferred") or []):
                guess = specs[hit]
                notes.append(
                    f"Your {_EN_SLOT.get(kept, kept)} ({name}): {aspect_en} assumed to be {guess} from the model name — "
                    "check the manufacturer's label before buying." if lang == "en" else
                    f"현재 {kept}({name})의 {_josa(aspect_ko, '은', '는')} 모델명으로 보아 {guess}일 것으로 추정했어요 — "
                    "구매 전 제조사 표기를 확인하세요.")
            elif hit:
                continue                                              # 글·카탈로그로 확인됨
            elif info:
                notes.append(
                    f"Could not read the {aspect_en} of your {_EN_SLOT.get(kept, kept)} ({name}) — check compatibility yourself."
                    if lang == "en" else
                    f"현재 {kept}({name})의 {_josa(aspect_ko, '을', '를')} 확인하지 못했어요 — 호환은 직접 확인이 필요해요.")
            else:
                notes.append(
                    f"No information on your {_EN_SLOT.get(kept, kept)}, so {aspect_en} compatibility was not checked."
                    if lang == "en" else
                    f"현재 {kept} 정보가 없어 {aspect_ko} 호환은 확인하지 못했어요.")
    return notes

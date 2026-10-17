"""결과 화면이 그대로 쓰는 표시 값(결과 화면 재설계, 요청서 S4~S7).

점수·순위는 바꾸지 않는다. 이미 계산된 값과 규칙 파일의 `display` 절만으로 만든다(DB·LLM 없음).

| 함수 | 내용 |
|---|---|
| `key_specs` | 카드에 한 줄로 보이는 필수 스펙(종류별 고정 순서). 값이 없는 항목은 넣지 않는다 |
| `requested_items` | 사용자가 말한 항목 목록 — 스펙으로 확인된 것, 연결된 사용기 속성·외부 리뷰 항목 |
| `price_position` | 통과한 후보 안에서 싼 순서 |
| `axis_label` | 점수 축의 사용자말 이름 |
| `review_quote` | 외부 리뷰 항목의 대표 문장(다수 방향) |
"""
from __future__ import annotations

import re
from typing import Any

from src.dto import Candidate
from src.engine import spec_rules
from src.engine.peripheral_rules import display_config, feel_attributes, purposes, situations, spec_conditions

# requirement[].label — hard(resolution_class/refresh_min_hz)와 config/peripherals.yaml
# spec_conditions 가 실제로 쓰는 pref 키만 담는다. 여기 없는 키는
# axis_label과 같은 원칙으로 키 이름을 그대로 라벨로 쓴다(모르는 키를 지어내지 않는다).
REQUIREMENT_KEY_LABEL: dict[str, str] = {
    "resolution_class": "요구 해상도 등급",
    "refresh_min_hz": "요구 최소 주사율(Hz)",
    "panel_raw": "패널",
    "switch_clicky": "클릭형 스위치",
    "switch_magnetic": "마그네틱 스위치",
    "rapid_trigger": "래피드 트리거",
    "polling_hz_max": "폴링레이트(Hz)",
    "connectivity_wireless": "무선 연결",
    "power_source_raw": "전원 방식",
    "channels": "채널 수",
    "connectivity_bluetooth": "블루투스 연결",
    "weight_g": "무게(g)",
    "size_longest_mm": "가장 긴 변(mm)",
    "size_height_mm": "높이(mm)",
    "button_count": "버튼 수",
    "form_factor_raw": "형태",
    "resolution_h": "세로 해상도(px)",
    "refresh_hz": "주사율(Hz)",
    "response_ms_gtg": "응답속도(ms)",
    "screen_size_inch": "화면 크기(인치)",
    "brightness_nit": "밝기(nit)",
    "usb_c_video": "USB-C 영상 입력",
    "usb_c_power_w": "USB-C 충전(W)",
    "output_w": "출력(W)",
    "speaker_form_raw": "스피커 형태",
}


def requirement_label(key: str) -> str:
    return REQUIREMENT_KEY_LABEL.get(key, key)


_UNIT = re.compile(r"^(?P<base>.*?)\((?P<unit>[^)]*)\)$")
_HANGUL = re.compile(r"[가-힣]")
# 외부 리뷰 항목에서 적은 쪽 의견이 전체의 이 비율 이상이면 "갈린다"(`dissent`)고 알린다.
_DISSENT_SHARE = 0.25
_QUOTE_MAX_CHARS = 120
_QUOTE_MIN_CHARS = 8
_NO_ITEM_SITUATIONS = {"trending"}          # 근거를 보일 속성이 따로 없는 상황은 요청 항목으로 만들지 않는다
_PLACEHOLDERS = {"", "—", "–", "-", "n/a"}  # 원본 표에서 "값 없음" 자리를 채운 표기


def _number(value: Any) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _unique(values) -> list:
    return list(dict.fromkeys(values))


# ── 필수 스펙 한 줄 ─────────────────────────────────────────────────────────
def _has_value(value: Any) -> bool:
    """값이 있는가. None·빈 문자열·"—"·"-"·"N/A" 같은 원본 자리표시는 값이 아니다."""
    if value is None:
        return False
    return not (isinstance(value, str) and value.strip().lower() in _PLACEHOLDERS)


def _key_spec_value(entry: dict, specs: dict[str, Any]) -> str | None:
    if "spec" in entry:
        value = specs.get(entry["spec"])
        if not _has_value(value):
            return None
        return f"{_number(value.strip() if isinstance(value, str) else value)}{entry.get('unit', '')}"
    if "parts" in entry:
        parts = [str(specs[k]).strip() for k in entry["parts"] if _has_value(specs.get(k))]
        return entry.get("sep", " · ").join(parts) or None
    flags = [text for key, text in entry["flags"].items() if specs.get(key) is True]
    return "·".join(flags) or None


def key_specs(kind: str, specs: dict[str, Any], rules: dict) -> list[dict[str, str]]:
    """종류별 필수 스펙 `[{key, label, value}]` (규칙 파일 `display.key_specs` 순서). 값이 없거나 "—"·"N/A" 같은 자리표시뿐이면 그 조각·항목은 뺀다."""
    out: list[dict[str, str]] = []
    for entry in (display_config(rules) or {}).get("key_specs", {}).get(kind, []):
        value = _key_spec_value(entry, specs or {})
        if value is not None:
            out.append({"key": entry["key"], "label": entry["label"], "value": value})
    return out


def axis_label(axis: str, rules: dict) -> str:
    """점수 축의 사용자말 이름. 표에 없으면 내부 이름을 그대로 쓴다(지어내지 않는다)."""
    return (display_config(rules) or {}).get("axis_labels", {}).get(axis, axis)


# ── 요청 항목 ───────────────────────────────────────────────────────────────
def spec_check(pref: dict[str, Any], specs: dict[str, Any]) -> dict[str, Any] | None:
    """스펙 조건 하나의 확인 결과 `{key, text, ok}`. 후보에 그 값이 없으면 None(확인했다고 말하지 않는다)."""
    key, op, value = pref["key"], pref["op"], pref["value"]
    verdict, _ = spec_rules.evaluate(pref, specs)
    if verdict == "Pending":
        return None
    label = requirement_label(key)
    match = _UNIT.match(label)
    base, unit = (match["base"], match["unit"]) if match else (label, "")
    actual = specs.get(key)
    if op in ("min", "max"):
        word = "이상" if op == "min" else "이하"
        text = f"{base} {_number(actual)}{unit} · {_number(value)}{unit} {word}"
    elif op == "equals" and value is True:
        text = base
    elif op == "equals" and value is False:
        text = f"{base} 아님"
    else:
        text = f"{base} {_number(actual)}{unit}"
    return {"key": key, "text": text, "ok": verdict == "Pass"}


def _feel_codes(kind: str, labels: list[str], taste_labels: list[str], rules: dict) -> list[str]:
    attrs = feel_attributes(kind, rules)
    codes = [code for code, entry in attrs.items() if any(label in entry.get("aliases", ()) for label in labels)]
    for code, entry in attrs.items():
        if entry["type"] == "taste" and any(label in entry.get("taste_labels", {}) for label in taste_labels):
            codes.append(code)
    return codes


def _external(kind: str, codes: list[str], rules: dict) -> list[str]:
    attrs = feel_attributes(kind, rules)
    return _unique(a for c in codes if (a := attrs.get(c, {}).get("external")))


def requested_items(kind: str, specs: dict[str, Any], interp, resolved, rules: dict,
                    pc_purposes: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """사용자가 말한 것(직접 말한 조건·상황·목적)마다 `{label, source, type, spec_checks, feel_codes, external_aspects}`.

    - 직접 말한 조건 먼저, 그다음 상황·목적을 말한 순서로.
    - 스펙 조건은 `resolved`(상충으로 빠진 조건은 이미 없다)에서 가져온다. 같은 조건이 직접 말한 것으로도 풀렸으면
      직접 말한 항목에만 둔다.
    - 연결된 사용기 속성: 목적·상황이 가리키는 체감 이름(`purposes.*.feel`·`taste`), 조용한 상황의 소리 속성,
      디자인의 외관·마감 속성, 직접 말한 조건의 `display.requested_feel`.
    - 스펙 조건도 연결 속성도 없는 항목은 만들지 않는다(보일 근거가 없다).
    - `type`: 스펙 조건만 있으면 "spec", 연결된 사용기·외부 리뷰 속성이 있으면 "evidence".
    - `pc_purposes`: 사용자가 말하지 않고 묶은 PC 견적의 용도에서만 온 목적 코드 — `source` 를 "pc_purpose" 로 둬서
      화면이 "요청하신"이라고 하지 않게 한다(QA 10/16 #16).
    """
    if resolved is None:
        return []
    cfg = display_config(rules) or {}
    labels = cfg.get("requested_labels", {})
    feel_map = cfg.get("requested_feel", {}).get(kind, {})
    attrs = feel_attributes(kind, rules)
    conds = spec_conditions(kind, rules)
    table = purposes(kind, rules)
    sit = situations(rules)
    by_cond = {c.condition: c for c in [*resolved.filters, *resolved.preferences]}

    def _checks(cond_ids: list[str]) -> list[dict[str, Any]]:
        prefs = spec_rules.dedupe_prefs([dict(p) for cid in cond_ids for p in conds[cid]["prefs"]])
        return [c for c in (spec_check(p, specs) for p in prefs) if c is not None]

    def _item(label: str, source: str, cond_ids: list[str], feel_codes: list[str]) -> dict[str, Any] | None:
        feel_codes = _unique(feel_codes)
        if not cond_ids and not feel_codes:
            return None
        return {"label": label, "source": source, "type": "spec" if cond_ids and not feel_codes else "evidence",
                "spec_checks": _checks(cond_ids), "feel_codes": feel_codes,
                "external_aspects": _external(kind, feel_codes, rules)}

    items: list[dict[str, Any]] = []
    for cid, cond in by_cond.items():
        if "stated" in cond.sources:
            item = _item(labels.get(cid, conds[cid]["label"]), "stated", [cid], feel_map.get(cid, []))
            if item:
                items.append(item)

    for code in _unique([*interp.purposes, *interp.situations]):
        if code in _NO_ITEM_SITUATIONS:
            continue
        in_table = code in table
        cond_ids = [cid for cid, c in by_cond.items()
                    if code in c.sources and "stated" not in c.sources] if in_table else []
        feel_codes: list[str] = []
        if in_table:
            feel_codes += _feel_codes(kind, table[code]["feel"], table[code]["taste"], rules)
        if code in ("quiet_place", "mic"):
            feel_codes += [c for c, e in attrs.items() if "sound" in e.get("tags", [])]
        if code == "design":
            feel_codes += [c for c, e in attrs.items() if e.get("only_when") == "design"]
            feel_codes += [c for c in ("build",) if c in attrs]
        label = labels.get(code) or (table[code]["label"] if in_table else sit.get(code, {}).get("label", code))
        source = "situation" if code in interp.situations else "pc_purpose" if code in pc_purposes else "purpose"
        item = _item(label, source, cond_ids, feel_codes)
        if item:
            items.append(item)
    return items


def price_position(cand: Candidate, pool: list[Candidate]) -> dict[str, int] | None:
    """통과한 후보(`pool`) 안에서 가격이 싼 순서. 후보가 하나뿐이면 None."""
    if len(pool) < 2:
        return None
    return {"rank": 1 + sum(1 for c in pool if c.price < cand.price), "of": len(pool)}


# ── 외부 리뷰 대표 문장 ─────────────────────────────────────────────────────
def review_quote(contribution: dict[str, Any]) -> tuple[dict[str, str] | None, bool]:
    """외부 리뷰 항목(`ReviewAspectContribution` 사전)의 `(quote, dissent)`.

    다수 방향(긍정 p ≥ 부정 n 이면 긍정, 아니면 부정, 둘 다 없으면 엇갈림)의 한글 문장 가운데 길이가
    적당한 것 중 가장 긴 것을 고른다(같으면 사전순). 길이가 맞는 문장이 하나도 없으면 가장 짧은
    문장을 고른다(같으면 사전순). 문장이 없으면 quote 는 None.
    `dissent` 는 적은 쪽 의견이 전체의 일정 비율 이상일 때 참이다."""
    p, n, mixed = contribution.get("p", 0), contribution.get("n", 0), contribution.get("mixed", 0)
    if p + n:
        direction = "positive" if p >= n else "negative"
    elif mixed:
        direction = "mixed"
    else:
        return None, False
    dissent = bool(p and n and min(p, n) / (p + n) >= _DISSENT_SHARE)
    sentences = [s.strip() for m in contribution.get("members", []) if m.get("direction") == direction
                 for s in m.get("evidence_sentences", []) if _HANGUL.search(s or "")]
    if not sentences:
        return None, dissent
    fitting = [s for s in sentences if _QUOTE_MIN_CHARS <= len(s) <= _QUOTE_MAX_CHARS]
    best = min(fitting, key=lambda s: (-len(s), s)) if fitting else min(sentences, key=lambda s: (len(s), s))
    return {"text": best, "direction": direction}, dissent

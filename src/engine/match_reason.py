"""인식한 부품이 왜 카탈로그 제품으로 확정되지 않았는지 — 화면이 "제품 확인 필요"의 이유를 구분해 보이게 하는 순수 함수.

이미 계산하는 매칭 결과(상태·후보·한정어 비교)를 이유 코드로 풀어 낼 뿐, 새 판정을 만들지 않는다. DB·LLM 없이 돈다.

코드(`code`):
- `not_in_catalog`    같은 부품군에 같은 모델이 없다(사진을 잘못 읽은 것이 아니다)
- `variant_mismatch`  같은 모델은 있지만 한정어·변형이 달라 같은 제품으로 확정하지 않았다(GRE↔일반, ARGB↔블랙)
- `ambiguous`         후보가 하나 이상 있어 사용자가 골라야 한다(가장 비슷한 제품 1개 포함)
- `insufficient_info` 모델 번호가 없어 제품을 특정할 수 없다
- `uncertain_reading` 모델이 글자를 확신하지 못했다
- `low_quality_photo` 사진이 작거나 흐려 자동으로 확정하지 않았다
확정된 항목(`confirmed`)은 이유가 없다(None)."""
from __future__ import annotations

from typing import Any

from src.engine.owned_parts import (
    _MODEL_QUALIFIERS, _SPEC_LABEL, _SPEC_ONLY, _is_model_token, _match_catalog, _match_by_model, _significant, _tokens,
    catalog_family_matches,
)
from src.engine.stage3_0_candidates import Candidate

_LABEL = {**_SPEC_LABEL, "vram_gb": "VRAM(GB)", "perf_tier": "성능 등급"}
_KEY_ORDER = ("socket", "mem_type", "form_factor", "interface", "capacity_gb", "speed_mts", "wattage_w", "vram_gb", "perf_tier")
_MAX_CANDIDATES = 3


def _key_specs(cand: Candidate) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _KEY_ORDER:
        value = (cand.specs or {}).get(key)
        if value in (None, "", []):
            continue
        out[_LABEL.get(key, key)] = "/".join(map(str, value)) if isinstance(value, (list, tuple)) else value
        if len(out) >= 4:
            break
    return out


def _candidate(cand: Candidate) -> dict[str, Any]:
    return {"name": cand.name, "product_key": cand.product_key, "key_specs": _key_specs(cand)}


def _word(tokens: set[str]) -> str:
    return ", ".join(sorted(tokens)) if tokens else "없음"


def _why_not(text_tokens: set[str], cand: Candidate) -> str:
    """읽은 글과 가장 가까운 제품이 다른 점 — 한정어가 다르면 그것을, 아니면 서로에게만 있는 낱말을 보인다."""
    have = set(_significant(_tokens(cand.name)))
    text_q, cand_q = text_tokens & _MODEL_QUALIFIERS, have & _MODEL_QUALIFIERS
    if text_q != cand_q:
        return f"한정어가 달라요(읽은 글 {_word(text_q)} ↔ 카탈로그 {_word(cand_q)})"
    only_text, only_cand = text_tokens - have, have - text_tokens
    return f"이름이 달라요(읽은 글에만 {_word(only_text)} · 카탈로그에만 {_word(only_cand)})"


def _closest(text_tokens: set[str], family: list[Candidate]) -> Candidate:
    def score(cand: Candidate) -> tuple[int, int]:
        have = set(_significant(_tokens(cand.name)))
        return (len(text_tokens & have), -len(have - text_tokens))
    return max(family, key=score)


def explain(slot: str, text: str, pool: list[Candidate], *, status: str, matched_name: str | None = None,
            candidate_count: int | None = None, uncertain: bool = False, low_quality: bool = False) -> dict[str, Any] | None:
    """`status` 는 매칭 결과(confirmed / ambiguous / candidate / inferred / unmatched). 확정이고 플래그가 없으면 None."""
    hint = [{"name": matched_name, "product_key": None, "key_specs": {}}] if matched_name else []
    if status != "confirmed":
        if uncertain:
            return {"code": "uncertain_reading", "message": "사진 글자가 확실하지 않아 다르게 읽었을 수 있어요. 이름을 확인해 주세요.",
                    "nearest": None, "candidates": hint}
        if low_quality:
            return {"code": "low_quality_photo", "message": "사진이 작거나 흐려서 자동으로 확정하지 않았어요. 이름을 확인해 주세요.",
                    "nearest": None, "candidates": hint}
    elif uncertain or low_quality:
        # 확정이었다가 글자 불확실로 낮춰진 항목 — 화면에는 이미 candidate 로 오지만 방어적으로 같은 코드를 쓴다.
        return explain(slot, text, pool, status="candidate", matched_name=matched_name, uncertain=uncertain, low_quality=low_quality)
    if status == "confirmed":
        return None

    if status == "ambiguous":
        matches = _match_catalog(text, pool) or _match_by_model(text, pool, slot)
        shown = [_candidate(c) for c in matches[:_MAX_CANDIDATES]]
        count = candidate_count or len(matches)
        return {"code": "ambiguous", "message": f"후보가 {count}개예요. 어느 제품인지 골라 주세요.", "nearest": None,
                "candidates": shown or hint}
    if status == "candidate":
        by_name = [c for c in pool if c.name == matched_name]
        shown = [_candidate(c) for c in by_name] or hint
        name = matched_name or "비슷한 제품"
        return {"code": "ambiguous", "message": f"카탈로그의 '{name}'와 가장 비슷해요. 같은 제품이 맞는지 확인해 주세요.",
                "nearest": None, "candidates": shown}

    # unmatched / inferred — 연결된 제품이 없다. 왜 없는지를 구분한다.
    text_tokens = set(_significant(_tokens(text)))
    models = {t for t in text_tokens if _is_model_token(t) and not _SPEC_ONLY.fullmatch(t)}
    inferred_note = " 글에서 읽은 값으로 점검해요." if status == "inferred" else ""
    if slot == "RAM":
        # RAM 은 용량·속도만으로 제품을 특정하지 않는다 — 브랜드 제품이 카탈로그에 없는 경우가 대부분이다.
        if models or text_tokens:
            return {"code": "not_in_catalog",
                    "message": f"카탈로그에 같은 브랜드의 RAM이 없어요. RAM은 용량·속도만으로 제품을 확정하지 않아요.{inferred_note}",
                    "nearest": None, "candidates": []}
    if not models:
        return {"code": "insufficient_info", "message": "모델 번호가 없어 어떤 제품인지 특정할 수 없어요. 모델 번호를 적어 주세요.",
                "nearest": None, "candidates": []}
    family = catalog_family_matches(text, pool)
    if family:
        near = _closest(text_tokens, family)
        return {"code": "variant_mismatch",
                "message": f"카탈로그의 '{near.name}'와 모델은 같지만 다른 제품이라 확정하지 않았어요.{inferred_note}",
                "nearest": {"name": near.name, "product_key": near.product_key, "why_not": _why_not(text_tokens, near),
                            "key_specs": _key_specs(near)},
                "candidates": [_candidate(c) for c in family[:_MAX_CANDIDATES]]}
    return {"code": "not_in_catalog",
            "message": f"카탈로그의 {slot} {len(pool)}개 중에 같은 모델이 없어요. 사진을 잘못 읽은 것은 아니에요.{inferred_note}",
            "nearest": None, "candidates": []}

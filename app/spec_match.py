"""
사양 매칭 — "LLM 추출 + 룰베이스 채점" (A안)

명세서 §2 "LLM + RAG(벡터화)"의 경량 구현.
진짜 RAG(임베딩+벡터DB)를 올리지 않고, 데모 규모(GPU 5종)에 맞춰:

  1. extract_spec_tags(text) : 지저분한 자연어 사양 → 구조화 태그 dict
        - NEGOTIATOR_MODE=llm + 키 있으면 LLM으로 추출
        - 아니면 정규식 폴백 (rule 모드 데모는 항상 동작)
        - 텍스트 해시로 캐시 → 반복 호출·비결정성 제거
  2. score_match(buyer_tags, seller_tags) : 속성별 룰 비교 → (0~1 유사도, 근거 dict)
        - 순수 룰, 결정론적 (NFR-02 만족)

나중에 진짜 RAG로 바꿀 때: register 시 태그 옆에 embedding을 같이 저장하고,
score_match 안의 속성 비교를 코사인 유사도로 교체하면 나머지 코드는 그대로다.
"""

from __future__ import annotations
import hashlib
import re
from typing import Any

# ── 태그 스키마 (GPU 도메인) ──
#   arch       : "ada lovelace" / "hopper" / "blackwell" / "ampere" ...
#   mem_type   : "gddr6" / "gddr7" / "hbm3" / "hbm2e" ...
#   mem_gb     : int
#   interface  : "pcie 4.0" / "pcie 5.0" ...
#   power_w    : int  (셀러=소비전력, 바이어=허용 상한)
#   ecc        : bool
#   nvlink     : bool
#   extras     : list[str]  (남은 토큰 — 키워드 겹침 보조 채점용)

_TAG_CACHE: dict[str, dict[str, Any]] = {}

_ARCH_WORDS = ["blackwell", "ada lovelace", "ada", "hopper", "ampere", "turing", "volta"]
_MEM_WORDS = ["gddr7", "gddr6", "gddr5", "hbm3e", "hbm3", "hbm2e", "hbm2"]

_WEIGHTS = {
    "arch": 0.20,
    "mem_type": 0.15,
    "mem_gb": 0.25,
    "interface": 0.10,
    "power_w": 0.15,
    "ecc": 0.05,
    "nvlink": 0.05,
    "extras": 0.05,
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# ────────────────────────── 추출 ──────────────────────────

def extract_spec_tags(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if key in _TAG_CACHE:
        return _TAG_CACHE[key]

    import os
    use_llm = (
        os.environ.get("NEGOTIATOR_MODE", "rule").lower() == "llm"
        and bool(os.environ.get("OPENAI_API_KEY"))
    )
    tags = _extract_llm(text) if use_llm else None
    if tags is None:
        tags = _extract_rule(text)
    _TAG_CACHE[key] = tags
    return tags


def _extract_rule(text: str) -> dict[str, Any]:
    """정규식·토큰 분해 폴백. LLM 없이도 같은 스키마의 dict를 만든다."""
    t = _norm(text)
    tags: dict[str, Any] = {}

    for w in _ARCH_WORDS:
        if w in t:
            tags["arch"] = "ada lovelace" if w == "ada" else w
            break
    for w in _MEM_WORDS:
        if w in t:
            tags["mem_type"] = w
            break

    m = re.search(r"(\d+)\s*gb", t)
    if m:
        tags["mem_gb"] = int(m.group(1))
    m = re.search(r"pcie\s*(\d\.\d)", t)
    if m:
        tags["interface"] = f"pcie {m.group(1)}"
    m = re.search(r"(\d+)\s*w\b", t)
    if m:
        tags["power_w"] = int(m.group(1))

    if "ecc" in t:
        tags["ecc"] = True
    if "nvlink" in t:
        tags["nvlink"] = True

    known = set()
    for v in (tags.get("arch"), tags.get("mem_type"), tags.get("interface")):
        if v:
            known.update(v.split())
    extras = []
    for chunk in re.split(r"[;,]", t):
        for tok in chunk.split():
            tok = tok.strip("()")
            if len(tok) >= 3 and tok not in known and tok not in _EXTRA_STOP and not tok.isdigit():
                extras.append(tok)
    if extras:
        tags["extras"] = sorted(set(extras))
    return tags


# 사양 문자열의 라벨/수식어 — 의미 없는 겹침을 만들어 extras 채점을 흐리므로 제외
_EXTRA_STOP = {
    "아키텍처", "최대", "소비전력", "지원", "구성", "대응", "폼팩터", "이하", "이상",
    "architecture", "max", "min", "the", "and", "with", "generation",
}


def _extract_llm(text: str) -> dict[str, Any] | None:
    """OpenAI 구조화 출력으로 태그 추출. 실패하면 None → 폴백."""
    try:
        from .llm_agents import _get_client, MODEL
    except Exception:
        return None

    schema = {
        "type": "object",
        "properties": {
            "arch": {"type": ["string", "null"]},
            "mem_type": {"type": ["string", "null"]},
            "mem_gb": {"type": ["integer", "null"]},
            "interface": {"type": ["string", "null"]},
            "power_w": {"type": ["integer", "null"]},
            "ecc": {"type": ["boolean", "null"]},
            "nvlink": {"type": ["boolean", "null"]},
            "extras": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["arch", "mem_type", "mem_gb", "interface", "power_w", "ecc", "nvlink", "extras"],
        "additionalProperties": False,
    }
    prompt = (
        "다음 GPU 사양 텍스트에서 속성을 뽑아 JSON으로 정규화하세요. "
        "값은 모두 소문자. 없으면 null. arch 예: 'ada lovelace','hopper','blackwell','ampere'. "
        "mem_type 예: 'gddr6','gddr7','hbm3','hbm2e'. interface 예: 'pcie 4.0'. "
        "mem_gb/power_w는 숫자만. extras에는 위로 분류되지 않은 의미있는 키워드만.\n\n"
        f"사양: {text}"
    )
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "spec_tags", "schema": schema, "strict": True},
            },
        )
        import json
        raw = json.loads(resp.choices[0].message.content)
    except Exception:
        return None

    tags: dict[str, Any] = {}
    for k in ("arch", "mem_type", "interface"):
        if raw.get(k):
            tags[k] = _norm(str(raw[k]))
    for k in ("mem_gb", "power_w"):
        if isinstance(raw.get(k), int):
            tags[k] = raw[k]
    for k in ("ecc", "nvlink"):
        if raw.get(k):
            tags[k] = True
    if raw.get("extras"):
        tags["extras"] = sorted({_norm(str(x)) for x in raw["extras"] if x})
    return tags


# ────────────────────────── 채점 ──────────────────────────

def score_match(buyer_tags: dict[str, Any], seller_tags: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """
    바이어가 명시한 속성만 채점한다. 아무것도 명시 안 했으면 (1.0, 사양 불문).
    반환: (0~1 가중 유사도, {속성: {"buyer","seller","score"}} 근거)
    """
    buyer_tags = buyer_tags or {}
    seller_tags = seller_tags or {}

    graded: list[tuple[float, float]] = []  # (weight, subscore)
    detail: dict[str, Any] = {}

    def put(attr: str, sub: float, b: Any, s: Any) -> None:
        graded.append((_WEIGHTS[attr], sub))
        detail[attr] = {"buyer": b, "seller": s, "score": round(sub, 2)}

    # 문자열 속성: 정규화 후 부분일치
    for attr in ("arch", "mem_type", "interface"):
        b = buyer_tags.get(attr)
        if not b:
            continue
        s = seller_tags.get(attr)
        if not s:
            put(attr, 0.5, b, None)  # 셀러 값 불명 → 절반
        elif b == s or b in s or s in b:
            put(attr, 1.0, b, s)
        elif set(str(b).split()) & set(str(s).split()):
            put(attr, 0.5, b, s)
        else:
            put(attr, 0.0, b, s)

    # 메모리 용량: 셀러가 요구치 이상이어야
    b = buyer_tags.get("mem_gb")
    if b:
        s = seller_tags.get("mem_gb")
        if s is None:
            put("mem_gb", 0.5, b, None)
        elif s >= b:
            put("mem_gb", 1.0, b, s)
        elif s >= 0.75 * b:
            put("mem_gb", 0.5, b, s)
        else:
            put("mem_gb", 0.0, b, s)

    # 소비전력: 바이어가 상한을 제시 → 셀러가 그 이하여야
    b = buyer_tags.get("power_w")
    if b:
        s = seller_tags.get("power_w")
        if s is None:
            put("power_w", 0.5, b, None)
        elif s <= b:
            put("power_w", 1.0, b, s)
        elif s <= 1.1 * b:
            put("power_w", 0.5, b, s)
        else:
            put("power_w", 0.0, b, s)

    # 불리언: 바이어가 요구(True)한 경우만
    for attr in ("ecc", "nvlink"):
        if buyer_tags.get(attr):
            s = bool(seller_tags.get(attr))
            put(attr, 1.0 if s else 0.0, True, s)

    # 나머지 키워드 겹침 (Jaccard)
    b_ex = set(buyer_tags.get("extras") or [])
    if b_ex:
        s_ex = set(seller_tags.get("extras") or [])
        j = len(b_ex & s_ex) / len(b_ex | s_ex) if (b_ex | s_ex) else 0.0
        put("extras", j, sorted(b_ex), sorted(s_ex))

    if not graded:
        return 1.0, {"note": "사양 불문 (바이어가 사양을 명시하지 않음)"}

    total_w = sum(w for w, _ in graded)
    score = sum(w * sub for w, sub in graded) / total_w
    return round(score, 3), detail

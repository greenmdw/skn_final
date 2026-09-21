"""시나리오(데모) 파이프라인의 근거 검색 — 시나리오 파일이 주입한 인메모리 미니 코퍼스만 검색한다."""

from __future__ import annotations

from typing import Any

# 시나리오 로더가 주입하는 미니 코퍼스 (list[dict]: {domain, axis, text, source_url, collected_at})
_MINI_CORPUS: list[dict[str, Any]] = []


def load_mini_corpus(chunks: list[dict[str, Any]]) -> None:
    """시나리오 파일의 corpus 배열을 인메모리 코퍼스로 적재 (데모 전용)."""
    global _MINI_CORPUS
    _MINI_CORPUS = list(chunks)


def evidence_search(
    domain: str, query: str, filters: dict | None = None, k: int = 3
) -> list[dict]:
    """근거 청크 검색.

    시나리오가 load_mini_corpus()로 주입한 코퍼스에서 축(axis) 단위로 찾는다
    (stage3c_verify.verify_set 의 _debate_lines 경로).

    Returns:
        각 dict: text(발췌 요약), source_url, collected_at, score. 0건이면 빈 리스트("회색").
    """
    filters = filters or {}
    axis = filters.get("axis", "")
    hits = [
        {
            "text": c["text"],
            "source_url": c.get("source_url", ""),
            "collected_at": c.get("collected_at", ""),
            "score": round(0.9 - i * 0.1, 2),
        }
        for i, c in enumerate(_MINI_CORPUS)
        if c.get("domain") == domain and (not axis or c.get("axis") == axis)
    ]
    print(f"[MOCK] evidence_search(domain={domain!r}, axis={axis!r}) → {len(hits)}건")
    return hits[:k]


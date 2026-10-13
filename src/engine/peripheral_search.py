"""사용기 문장 검색 — 목록에 없는 요구에 관련 문장을 찾아 보여 주기만 한다(개발_확정사양.md 6.6).

점수에는 넣지 않는다. 견적 입력에서 "반영하지 못한 말"(`unrecognized`)이 있을 때, 그 말과 가까운 사용기 문장을 설명으로
붙이는 데 쓴다. 대상은 속성이 붙은 근거 문장과, 맞는 속성이 없어 "기타"로 저장한 경험 문장이다.

순위는 단어 일치 순위와 임베딩 순위를 `1 / (rrf_k + 순위)` 의 합으로 합친다(역순위 결합). 임베딩 순위는 DB 의
벡터 검색이 만들므로 이 모듈은 이미 매겨진 순위 목록(`embedding_ranked`)을 받기만 한다 — 없으면 단어 일치만 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.engine.peripheral_rules import feel_config, load_peripheral_rules

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
# 조사·어미가 붙은 말도 잡도록 어간만 비교한다: 토큰의 앞 두 글자 이상이 문장 토큰의 앞부분과 같으면 일치로 본다.
_MIN_STEM = 2


@dataclass(frozen=True)
class Sentence:
    quote_id: str
    post_id: str
    text: str
    product_id: str | None = None
    attribute: str | None = None       # 속성 코드, 기타 문장이면 "other"
    is_example: bool = False


@dataclass(frozen=True)
class SearchHit:
    sentence: Sentence
    score: float


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def keyword_ranking(query: str, corpus: list[Sentence]) -> list[str]:
    """단어가 많이 일치하는 문장의 `quote_id` 순서. 하나도 일치하지 않는 문장은 뺀다."""
    q = [t for t in _tokens(query) if len(t) >= _MIN_STEM]
    if not q:
        return []
    scored: list[tuple[int, int, str]] = []
    for position, sentence in enumerate(corpus):
        words = _tokens(sentence.text)
        hits = sum(1 for t in q if any(w.startswith(t[:_MIN_STEM + 1] if len(t) > _MIN_STEM else t) or t.startswith(w)
                                       for w in words if len(w) >= _MIN_STEM))
        if hits:
            scored.append((-hits, position, sentence.quote_id))
    return [qid for _, _, qid in sorted(scored)]


def search_sentences(
    query: str, corpus: list[Sentence], embedding_ranked: list[str] | None = None,
    rules: dict | None = None, *, limit: int | None = None,
) -> list[SearchHit]:
    """`corpus` 에서 `query` 와 관련된 문장을 점수순으로 낸다. `embedding_ranked` 는 임베딩 유사도 순의 `quote_id`."""
    cfg = feel_config(rules or load_peripheral_rules())
    rrf_k = cfg["rrf_k"] if cfg else 60
    cap = limit if limit is not None else (cfg["search_limit"] if cfg else 5)
    by_id = {s.quote_id: s for s in corpus}

    scores: dict[str, float] = {}
    for ranking in (keyword_ranking(query, corpus), [q for q in (embedding_ranked or []) if q in by_id]):
        for rank, qid in enumerate(ranking, start=1):
            scores[qid] = scores.get(qid, 0.0) + 1.0 / (rrf_k + rank)
    order = sorted(scores, key=lambda qid: (-scores[qid], qid))
    return [SearchHit(sentence=by_id[qid], score=round(scores[qid], 6)) for qid in order[:cap]]


def evidence_for_unrecognized(
    phrases: list[str], corpus: list[Sentence], embedding_ranked_by_phrase: dict[str, list[str]] | None = None,
    rules: dict | None = None,
) -> dict[str, list[SearchHit]]:
    """반영하지 못한 말마다 관련 문장. 찾은 것이 없는 말은 결과에 넣지 않는다(화면은 말만 보여 준다)."""
    out: dict[str, list[SearchHit]] = {}
    for phrase in phrases:
        hits = search_sentences(phrase, corpus, (embedding_ranked_by_phrase or {}).get(phrase), rules)
        if hits:
            out[phrase] = hits
    return out

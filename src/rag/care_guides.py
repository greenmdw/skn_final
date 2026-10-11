"""부품 사용 가이드·주의 문구 RAG — [3-C] "구매 전 확인"(checks)이 인용하는 근거.

data/pc_care_guides.json(합성 작성, 18개)을 프로세스 시작 시 한 번 임베딩해서 들고 있다가,
품목별 질의(부품명 + 슬롯)로 가장 관련 있는 조각을 코사인 유사도로 찾는다. 문서가 이 정도
개수면 벡터DB 없이 인메모리 검색으로 충분하다 — 별도 서비스도, 스키마도 필요 없다.

검색은 슬롯→문서 고정 매핑이 아니라 실제 임베딩 유사도 비교다 — 같은 슬롯이어도 품목명·
브랜드에 따라 다른 조각이 뽑힐 수 있다. RAG_EMBEDDING_PROVIDER(bedrock, RAG 스키마 삭제로
현재 미사용)와는 무관한 별도 경로 — 이미 동작 확인된 OpenAI 키를 그대로 재사용한다.

MOCK_MODE=1(기본)에서는 실제 호출 없이 결정적 해시 임베딩으로 같은 인터페이스를 유지한다
(src.rag.embedding.LocalHashEmbedder와 같은 방식) — 테스트가 네트워크를 안 타게 한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from functools import lru_cache

from src.config import (CARE_GUIDE_EMBED_MAX_RETRIES, CARE_GUIDE_EMBED_TIMEOUT_S, CARE_GUIDE_EMBEDDING_MODEL,
                        CARE_GUIDES_JSON, MOCK_MODE, OPENAI_API_KEY)

_HASH_DIMENSIONS = 256


def _hash_embed(text: str) -> list[float]:
    """MOCK_MODE 전용 — 의미 유사도는 아니지만(어휘 겹침 기반) 같은 입력엔 항상 같은 벡터."""
    vec = [0.0] * _HASH_DIMENSIONS
    for token in text.split():
        idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % _HASH_DIMENSIONS
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=1)
def _openai_client():
    """클라이언트는 한 번 만들어 재사용한다(호출마다 새로 만들면 연결·TLS 를 매번 다시 맺는다). 제한 시간·재시도도 명시한다 —
    SDK 기본값(600초·2회)이면 응답이 멈췄을 때 견적 후처리가 수 분 매달린다."""
    from openai import OpenAI

    return OpenAI(api_key=OPENAI_API_KEY, timeout=CARE_GUIDE_EMBED_TIMEOUT_S, max_retries=CARE_GUIDE_EMBED_MAX_RETRIES)


def _openai_embed(texts: list[str]) -> list[list[float]]:
    response = _openai_client().embeddings.create(model=CARE_GUIDE_EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in response.data]


def _embed(texts: list[str]) -> list[list[float]]:
    if MOCK_MODE or not OPENAI_API_KEY:
        return [_hash_embed(t) for t in texts]
    return _openai_embed(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


@lru_cache(maxsize=1)
def _load_guides() -> tuple[tuple[dict, ...], tuple[tuple[float, ...], ...]]:
    """가이드 문서 + 임베딩을 프로세스당 한 번만 계산해 들고 있는다(반복 임베딩 호출 방지)."""
    docs = tuple(json.loads(CARE_GUIDES_JSON.read_text(encoding="utf-8")))
    embeddings = tuple(tuple(v) for v in _embed([d["text"] for d in docs]))
    return docs, embeddings


# 슬롯이 알려진 질의는 그 슬롯의 가이드 안에서만 고른다. 실제 임베딩으로 전 문서를 검색하면 부품명이
# 들어간 짧은 질의에서 유사도가 0.3~0.4대로 몰려 RAM 에 SSD 발열 가이드, GPU 에 케이스 여유 가이드가
# 붙었다(2026-09-21 실호출 확인). 슬롯 안에서는 의미 유사도로 고른다.
SLOT_GUIDE_IDS: dict[str, tuple[str, ...]] = {
    "CPU": ("cpu_cooler_socket", "cpu_thermal_paste"),
    "GPU": ("gpu_power", "gpu_thermal", "gpu_length_clearance"),
    "RAM": ("ram_dual_channel", "ram_xmp"),
    "메인보드": ("mainboard_bios", "mainboard_esd"),
    "저장장치": ("storage_thermal", "storage_backup"),
    "파워": ("psu_rating", "psu_cabling"),
    "케이스": ("case_airflow", "case_spec_clearance"),
    "쿨러": ("cooler_height_clearance", "cpu_cooler_socket"),
    # 주변기기 4종(계획 §3.3 E13) — 가이드 문서가 아직 없다(작성은 R-12). 여기 등록을
    # 빼면 slot이 SLOT_GUIDE_IDS에 없는 것으로 취급돼 allowed=None이 되고, 전 문서(PC용)를
    # 검색해 엉뚱한 PC 가이드가 모니터·키보드 등에 붙는다 — 빈 튜플로 명시해 그 폴백을 막는다.
    "monitor": (), "keyboard": (), "mouse": (), "speaker": (),
}


# 조립·설치 방법 문서(kind="install"). 조립 가이드 기능 자체는 삭제됐지만(개발요청 1번), 검색이
# care/install 종류를 섞지 않는다는 경계는 계속 검사한다(tests/test_assembly_guide_install.py).
INSTALL_GUIDE_IDS: dict[str, tuple[str, ...]] = {
    "CPU": ("install_cpu",),
    "GPU": ("install_gpu",),
    "RAM": ("install_ram",),
    "메인보드": ("install_mainboard",),
    "저장장치": ("install_storage",),
    "파워": ("install_psu",),
    "케이스": ("install_case",),
    "쿨러": ("install_cooler",),
}


def search_care_guide(query: str, k: int = 1, slot: str | None = None, kind: str | None = None) -> list[dict]:
    """query와 가장 관련 있는 가이드 k개. 각 dict: {id, kind, text, score}. 문서가 없으면 빈 리스트.

    slot 을 주면 그 슬롯의 가이드 안에서만 찾는다 — kind 가 "install" 이면 INSTALL_GUIDE_IDS, 아니면
    SLOT_GUIDE_IDS(구매 전 확인). kind 를 주면 그 종류의 문서만 대상이다("care"|"install"),
    안 주면(기본) 종류를 가리지 않는다.
    """
    docs, embeddings = _load_guides()
    if not docs:
        return []
    table = INSTALL_GUIDE_IDS if kind == "install" else SLOT_GUIDE_IDS
    allowed = table.get(slot) if slot else None
    q = _embed([query])[0]
    scored = sorted(
        ({"id": d["id"], "kind": d.get("kind", "care"), "text": d["text"], "score": round(_cosine(q, e), 4)}
         for d, e in zip(docs, embeddings)
         if (kind is None or d.get("kind", "care") == kind) and (allowed is None or d["id"] in allowed)),
        key=lambda h: h["score"], reverse=True,
    )
    return scored[:k]


# 질의 벡터 캐시 — 견적 후처리의 질의는 "{슬롯} {상품명} 사용 시 확인할 점"이라 같은 상품이면 매번 같다. 문서·모델은 프로세스 안에서
# 바뀌지 않으므로(바뀌면 재시작) 질의 문자열만 키로 둔다. 상품 수만큼만 쌓이지만 상한을 둔다.
_QUERY_VECTOR_CACHE_MAX = 4096
_query_vectors: dict[str, list[float]] = {}
_query_vectors_lock = threading.Lock()


def _query_vectors_for(queries: list[str]) -> list[list[float]]:
    """질의들의 벡터 — 캐시에 없는 것만 임베딩 요청 한 번으로 묶어 만든다."""
    with _query_vectors_lock:
        found = {q: _query_vectors[q] for q in queries if q in _query_vectors}
    missing = [q for q in dict.fromkeys(queries) if q not in found]
    if missing:
        vectors = _embed(missing)
        found.update(zip(missing, vectors))
        with _query_vectors_lock:
            if len(_query_vectors) + len(missing) > _QUERY_VECTOR_CACHE_MAX:
                _query_vectors.clear()
            _query_vectors.update(zip(missing, vectors))
    return [found[q] for q in queries]


def search_care_guides(requests: list[tuple[str, str | None]], k: int = 1) -> list[list[dict]]:
    """여러 (질의, 슬롯)의 구매 전 확인 가이드를 한꺼번에 찾는다 — 결과는 입력 순서대로, 각각 search_care_guide 와 같은 모양.

    견적 후처리가 부품마다 search_care_guide 를 따로 부르면 질의 임베딩 요청이 부품 수만큼(8번) 직렬로 나갔다. 여기서는 후보
    문서가 없는 슬롯(주변기기 등)은 임베딩 없이 빈 결과로 두고, 나머지 질의를 캐시에 없는 것만 한 번의 요청으로 묶는다.
    슬롯별 가이드 범위·유사도 정렬은 search_care_guide 와 같다."""
    allowed_by_index = [SLOT_GUIDE_IDS.get(slot) if slot else None for _query, slot in requests]
    wanted = [i for i, allowed in enumerate(allowed_by_index) if allowed is None or allowed]
    if not wanted:
        return [[] for _ in requests]
    docs, embeddings = _load_guides()
    if not docs:
        return [[] for _ in requests]
    vectors = dict(zip(wanted, _query_vectors_for([requests[i][0] for i in wanted])))
    results: list[list[dict]] = []
    for i, allowed in enumerate(allowed_by_index):
        if i not in vectors:
            results.append([])
            continue
        scored = sorted(
            ({"id": d["id"], "kind": d.get("kind", "care"), "text": d["text"], "score": round(_cosine(vectors[i], e), 4)}
             for d, e in zip(docs, embeddings)
             if allowed is None or d["id"] in allowed),
            key=lambda h: h["score"], reverse=True,
        )
        results.append(scored[:k])
    return results

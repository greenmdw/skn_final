"""Version 2 review retrieval: independent source groups and exact community citations."""
from __future__ import annotations

from uuid import UUID

from src import config
from src.errors import Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from src.services import review_search
from src.services.community_review_chunking import embedding_input
from src.services.community_review_search_index import repository_factory


def check_mode(corpus_mode):
    if corpus_mode not in ("real", "demo"):
        raise ValidationFailed("corpus_mode는 real 또는 demo여야 합니다.", field="corpus_mode")
    if not config.COMMUNITY_REVIEW_SEARCH_ENABLED:
        raise ServiceUnavailable("커뮤니티 리뷰 검색 기능이 비활성화되어 있습니다.", code="community_review_search_disabled")
    if corpus_mode == "demo" and not config.COMMUNITY_REVIEW_SEARCH_ALLOW_EXAMPLES:
        raise Forbidden("예시 사용기 검색이 허용되지 않습니다.", code="community_review_demo_disabled")


def citation_out(row, *, product_id=None):
    post_id, cid = str(row["post_id"]), str(row["id"])
    return {
        "source_type": "community", "document_id": post_id, "chunk_id": cid,
        "title": row["title"], "text": row["text"], "offset_basis": "normalized_body",
        "start_char": row["start_char"], "end_char": row["start_char"] + len(row["text"]),
        "posted_at": row["published_at"], "matched_product_id": str(product_id) if product_id else None,
        "linked_products": row["linked_products"], "association_scope": "post_link",
        "product_attribution": "unverified", "is_example": row["is_example"],
        "source_url": f"/community?view=post&post={post_id}",
        "citation_url": f"/reviews/chunks/{cid}" + ("?corpus_mode=demo" if row["is_example"] else ""),
    }


def community_search(open_repo, embedder, *, product_ids, query, limit, demo=False):
    with open_repo() as repo:
        coverage = repo.coverage(product_ids, demo=demo)
        if any(not row["exists"] for row in coverage.values()):
            raise NotFound("카탈로그에 없는 상품입니다.", field="product_id")
        searchable = [pid for pid in product_ids if coverage[pid]["indexed_documents"]]
        sample = repo.sample(searchable, demo=demo) if searchable else []
    hits = {pid: [] for pid in product_ids}
    if searchable:
        vectors = review_search._embed(embedder, [embedding_input(r["title"], r["text"]) for r in sample] + [query])
        with open_repo() as repo:
            review_search._check_index(repo, sample, vectors[:-1])
            rows = repo.nearest(vectors[-1], product_ids, limit=limit, demo=demo)
            coverage = repo.coverage(product_ids, demo=demo)  # changes during embedding take effect immediately
        for row in rows:
            if row["similarity"] >= config.COMMUNITY_REVIEW_SEARCH_MIN_SIMILARITY:
                hits[row["product_id"]].append({**citation_out(row, product_id=row["product_id"]),
                    "similarity": round(float(row["similarity"]), 4)})
    result = {}
    for pid in product_ids:
        cov = coverage[pid]
        result[pid] = {
            "status": review_search.product_status(cov["documents"], cov["indexed_documents"], len(hits[pid])),
            "min_similarity": config.COMMUNITY_REVIEW_SEARCH_MIN_SIMILARITY,
            "coverage": {k: cov[k] for k in ("documents", "indexed_documents", "chunks")}
                | {"index_complete": cov["documents"] == cov["indexed_documents"]},
            "hits": hits[pid],
        }
    return result


def search(*, product_ids, query, limit, sources=None, corpus_mode="real"):
    ids, q, limit = review_search._validated(product_ids, query, limit)
    sources = list(dict.fromkeys(sources if sources is not None else ("external_review", "community")))
    if not sources or any(s not in ("external_review", "community") for s in sources):
        raise ValidationFailed("검색 출처가 올바르지 않습니다.", field="sources")
    if corpus_mode not in ("real", "demo"):
        raise ValidationFailed("corpus_mode가 올바르지 않습니다.", field="corpus_mode")
    if "community" in sources:
        check_mode(corpus_mode)
    elif corpus_mode != "real":
        raise ValidationFailed("demo 모드는 커뮤니티 출처에만 적용됩니다.", field="corpus_mode")
    embedder = review_search.default_embedder()  # shared cache: the question is embedded at most once
    groups = {pid: {} for pid in ids}
    if "external_review" in sources:
        external = review_search.search_with(review_search._open_repo, embedder,
                    product_ids=ids, query=q, limit=limit)
        for product in external["products"]:
            cov = product["coverage"]
            groups[UUID(product["product_id"])]["external_review"] = {
                "status": product["status"], "min_similarity": external["min_similarity"],
                "coverage": {"documents": cov["reviews"], "indexed_documents": cov["embedded"],
                             "index_complete": cov["reviews"] == cov["embedded"]},
                "hits": [{"source_type": "external_review", "document_id": h["review_id"], "text": h["body"],
                          "posted_at": h["posted_at"], "similarity": h["similarity"]} for h in product["hits"]],
            }
    if "community" in sources:
        community = community_search(repository_factory(embedder), embedder, product_ids=ids,
                                     query=q, limit=limit, demo=corpus_mode == "demo")
        for pid in ids:
            groups[pid]["community"] = community[pid]
    return {"schema_version": 2, "query": q, "corpus_mode": corpus_mode,
            "products": [{"product_id": str(pid), "sources": {s: groups[pid][s] for s in sources}} for pid in ids]}


def citation(chunk_id, *, corpus_mode="real"):
    check_mode(corpus_mode)
    with repository_factory(review_search.default_embedder())() as repo:
        row = repo.citation(chunk_id, demo=corpus_mode == "demo")
    if not row:
        raise NotFound("현재 공개된 리뷰 구절을 찾을 수 없습니다.")
    return citation_out(row)

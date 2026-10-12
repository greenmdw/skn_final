"""[3-A] 사전 필터의 Pending 후보 정보 보완 — 정책 §5.3.

엔진(stage3a_hardfilter.run)이 넘긴 Pending 후보의 누락 키를 **저장소를 읽기만 해서** 채운다:
이미 있는 실시간 스펙 검색 결과(catalog.live_spec_lookup_cache, 만료 안·rejected 아님·relevant)만 쓴다.
웹 검색·LLM을 부르는 live_spec_lookup.lookup/lookup_with_meta는 부르지 않는다(추천 계산마다 검색이 자동으로 돌지 않게).
저장소가 다루지 않는 키(성능 등급·가격 등)는 조회하지 않고 no_path로 기록한다. 근거 없는 값은 만들지 않는다.
"""
from __future__ import annotations

from typing import Callable

from src.config import LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS, LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS
from src.dto import Candidate
from src.engine.stage3a_hardfilter import missing_keys
from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo
from src.services import live_spec_lookup

CACHE_SOURCE = "live_spec_lookup_cache"


def make_enricher(conn) -> Callable[[str, list[Candidate]], tuple[list[Candidate], list[dict]]]:
    """`stage3a_hardfilter.run(..., enrich=...)`에 넘길 보완 함수. 같은 실행 안에서 같은 키는 한 번만 조회한다."""
    repo = LiveSpecLookupRepo(conn)
    rows: dict[str, dict | None] = {}

    def _row(key: str) -> dict | None:
        if key not in rows:
            row = repo.get_fresh(key, found_ttl_days=LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS,
                                 notfound_ttl_days=LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS)
            usable = row and row["relevant"] and row["status"] != "rejected"
            rows[key] = row if usable else None
        return rows[key]

    def _fill_one(slot: str, cand: Candidate, keys: list[str]) -> tuple[Candidate, dict]:
        allowed = live_spec_lookup.SLOT_FIELDS.get(slot, frozenset())
        record = {"slot": slot, "product_key": cand.product_key, "missing_keys": keys,
                  "source": None, "status": "no_path", "detail": "저장소가 다루지 않는 항목입니다"}
        lookup_key = live_spec_lookup.normalize_lookup_key(cand.name)
        if not any(k in allowed for k in keys) or not lookup_key:
            return cand, record
        row = _row(lookup_key)
        if row is None:
            return cand, {**record, "source": CACHE_SOURCE, "status": "not_found",
                          "detail": "저장된 실시간 스펙 검색 결과가 없습니다"}
        fields = live_spec_lookup.clean_fields(slot, row["supported_fields"] or {})
        filled = {k: fields[k] for k in keys if k in allowed and fields.get(k) is not None}
        if not filled:
            return cand, {**record, "source": CACHE_SOURCE, "status": "not_found",
                          "detail": "저장된 검색 결과에 필요한 값이 없습니다"}
        source = row.get("source_url") or CACHE_SOURCE
        by_key = {**(cand.provenance.get("by_key") or {}), **{k: source for k in filled}}
        out = cand.model_copy(update={"specs": {**cand.specs, **filled},
                                      "provenance": {**cand.provenance, "by_key": by_key}})
        return out, {**record, "source": source, "status": "filled", "detail": "채움: " + ", ".join(sorted(filled))}

    def enrich(slot: str, pending: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
        results = [_fill_one(slot, cand, missing_keys(cand)) for cand in pending]
        return [c for c, _ in results], [a for _, a in results]

    def enrich_keys(slot: str, requests: list[tuple[Candidate, list[str]]]) -> tuple[list[Candidate], list[dict]]:
        """조합 단계 보완 — (후보, 모자란 spec 키 목록)마다 같은 저장소 경로로 그 키만 채운다. 사전 필터의 Pending 보완과
        조회 캐시(rows)를 공유한다. 웹 검색·LLM 은 부르지 않는다."""
        results = [_fill_one(slot, cand, list(keys)) for cand, keys in requests]
        return [c for c, _ in results], [a for _, a in results]

    enrich.for_keys = enrich_keys
    return enrich

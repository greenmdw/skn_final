"""catalog.live_spec_lookup_cache 저장소 — docs/미보유부품_실시간스펙검색_설계.md §4.

TTL 판단(며칠 지난 캐시를 못 쓰는지)은 여기서 SQL로 하지 않고 호출자가 ttl_days 를 넘긴다 —
config.LIVE_SPEC_LOOKUP_TTL_DAYS 를 repo 가 직접 import 하면 설정 주입 경로가 두 군데로
갈라진다(서비스 계층 하나로 모으기 위해)."""
from __future__ import annotations

from src.db.base import Repo


class LiveSpecLookupRepo(Repo):
    def get_fresh(self, query_text: str, *, ttl_days: int) -> dict | None:
        """ttl_days 안에 받아온 캐시만 반환한다. 오래됐으면 None — 재검색 대상이라는 뜻."""
        return self._one(
            "SELECT * FROM catalog.live_spec_lookup_cache WHERE query_text=%s "
            "AND fetched_at > now() - make_interval(days => %s)",
            (query_text, ttl_days),
        )

    def upsert(self, *, query_text: str, brand: str | None, model: str | None,
               relevant: bool, supported_fields: dict, source_url: str | None) -> dict:
        """relevant=False(검증 실패)도 그대로 캐싱한다 — 설계 문서 §4 참고."""
        from psycopg.types.json import Jsonb

        return self._one(
            "INSERT INTO catalog.live_spec_lookup_cache "
            "(query_text, brand, model, relevant, supported_fields, source_url, fetched_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (query_text) DO UPDATE SET "
            "brand=EXCLUDED.brand, model=EXCLUDED.model, relevant=EXCLUDED.relevant, "
            "supported_fields=EXCLUDED.supported_fields, source_url=EXCLUDED.source_url, "
            "fetched_at=now() "
            "RETURNING *",
            (query_text, brand, model, relevant, Jsonb(supported_fields), source_url),
        )

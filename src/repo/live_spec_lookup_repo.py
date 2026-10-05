"""catalog.live_spec_lookup_cache 저장소 — docs/미보유부품_실시간스펙검색_설계.md §4·§9.

TTL 값은 repo 가 config 를 직접 import 하지 않고 호출자가 넘긴다 — 설정 주입 경로를 서비스 계층
하나로 모으기 위해서다(만료 판단 자체는 여기 SQL 이 한다: 결과 종류마다 만료가 다르다)."""
from __future__ import annotations

from src.db.base import Repo

_VALID_STATUS = ("unreviewed", "confirmed", "rejected")


class LiveSpecLookupRepo(Repo):
    def get_fresh(self, lookup_key: str, *, found_ttl_days: int, notfound_ttl_days: int) -> dict | None:
        """아직 쓸 수 있는 행 하나. 없으면 None — 재검색 대상이라는 뜻이다.

        - confirmed(사람이 확인): 만료 없음
        - 찾음(relevant, rejected 아님): found_ttl_days 안
        - 못 찾음 또는 rejected: notfound_ttl_days 안 (rejected 는 호출자가 "못 찾음"으로 취급한다)"""
        return self._one(
            "SELECT * FROM catalog.live_spec_lookup_cache WHERE lookup_key=%s AND ("
            " status='confirmed'"
            " OR (status<>'rejected' AND relevant AND fetched_at > now() - make_interval(days => %s))"
            " OR ((NOT relevant OR status='rejected') AND fetched_at > now() - make_interval(days => %s)))",
            (lookup_key, found_ttl_days, notfound_ttl_days),
        )

    def upsert(self, *, lookup_key: str, query_text: str, brand: str | None, model: str | None,
               relevant: bool, supported_fields: dict, source_url: str | None,
               reference_price: int | None = None, reference_price_source_url: str | None = None) -> dict:
        """검색 결과 저장 — relevant=False(검증 실패)도 그대로 저장한다(§4). 같은 키가 이미 있으면
        새 결과로 덮고 status 를 unreviewed 로 되돌린다. 다만 confirmed 행은 덮지 않는다(사람이 확인한 값)."""
        from psycopg.types.json import Jsonb

        row = self._one(
            "INSERT INTO catalog.live_spec_lookup_cache "
            "(lookup_key, query_text, brand, model, relevant, supported_fields, source_url, fetched_at,"
            " reference_price, reference_price_source_url, reference_price_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, now(), %s, %s,"
            " CASE WHEN %s::integer IS NULL THEN NULL ELSE now() END) "
            "ON CONFLICT (lookup_key) DO UPDATE SET "
            "query_text=EXCLUDED.query_text, brand=EXCLUDED.brand, model=EXCLUDED.model, "
            "relevant=EXCLUDED.relevant, supported_fields=EXCLUDED.supported_fields, "
            "source_url=EXCLUDED.source_url, fetched_at=now(), status='unreviewed', reviewed_at=NULL, "
            "reference_price=EXCLUDED.reference_price, "
            "reference_price_source_url=EXCLUDED.reference_price_source_url, "
            "reference_price_at=EXCLUDED.reference_price_at "
            "WHERE catalog.live_spec_lookup_cache.status <> 'confirmed' "
            "RETURNING *",
            (lookup_key, query_text, brand, model, relevant, Jsonb(supported_fields), source_url,
             reference_price, reference_price_source_url, reference_price),
        )
        if row is None:       # 그 사이 confirmed 된 행 — 덮지 않고 그 행을 돌려준다
            row = self._one("SELECT * FROM catalog.live_spec_lookup_cache WHERE lookup_key=%s", (lookup_key,))
        return row

    def list_by_status(self, status: str = "unreviewed", *, limit: int = 50) -> list[dict]:
        return self._all(
            "SELECT * FROM catalog.live_spec_lookup_cache WHERE status=%s ORDER BY fetched_at DESC LIMIT %s",
            (status, limit))

    def set_status(self, row_id: str, status: str) -> dict | None:
        """id 앞부분(8자 이상)으로 행 하나를 찾아 검토 상태를 바꾼다. 정확히 하나가 아니면 None."""
        if status not in _VALID_STATUS:
            raise ValueError(f"status 는 {_VALID_STATUS} 중 하나여야 합니다: {status!r}")
        matches = self._all(
            "SELECT id, relevant FROM catalog.live_spec_lookup_cache WHERE id::text LIKE %s", (row_id + "%",))
        if len(matches) != 1:
            return None
        if status == "confirmed" and not matches[0]["relevant"]:
            raise ValueError("못 찾음(relevant=false) 행은 confirmed 할 수 없습니다 — 확인할 값이 없습니다.")
        return self._one(
            "UPDATE catalog.live_spec_lookup_cache SET status=%s, "
            "reviewed_at = CASE WHEN %s = 'unreviewed' THEN NULL ELSE now() END WHERE id=%s RETURNING *",
            (status, status, matches[0]["id"]))

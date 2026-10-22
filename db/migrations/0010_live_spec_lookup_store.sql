--
-- 0010_live_spec_lookup_store.sql
--
-- 미보유 부품 실시간 검색 캐시를 "임시 부품 저장소"로 확장한다
-- (docs/미보유부품_실시간스펙검색_설계.md §9, 2026-10-03 멘토링 반영).
--
-- 바뀌는 것
--   1. 조회 키를 query_text(견적 원문 + "정식 스펙")에서 lookup_key(가격·수량·상품코드를 뺀
--      정규화 이름)로 옮긴다. 원문에 붙은 가격이 키에 섞여 같은 제품이 가격이 다를 때마다
--      재검색되던 문제를 없앤다. query_text는 "실제로 검색에 보낸 질의" 기록으로 남긴다.
--   2. status — 사람이 확인했는지. unreviewed(기본) / confirmed(만료 없음) / rejected(못 찾음 취급).
--   3. 참고가 — 검색에서 얻은 금액을 후보·합계·비교와 분리해 따로 보관한다(기본 꺼짐,
--      LIVE_REFERENCE_PRICE=1일 때만 채운다). 카탈로그의 offer_observation과는 연결하지 않는다.
--
-- 기존 행은 마이그레이션에서 비운다. 파생 캐시라 다시 검색하면 되고, 키 형식이 달라 백필이
-- 의미가 없다. 만료(TTL)는 계속 앱 설정이 정한다(LIVE_SPEC_LOOKUP_*_TTL_DAYS).
--

DELETE FROM catalog.live_spec_lookup_cache;

ALTER TABLE catalog.live_spec_lookup_cache DROP CONSTRAINT live_spec_lookup_cache_query_text_key;

ALTER TABLE catalog.live_spec_lookup_cache
    ADD COLUMN lookup_key text NOT NULL,
    ADD COLUMN status text DEFAULT 'unreviewed' NOT NULL,
    ADD COLUMN reviewed_at timestamp with time zone,
    ADD COLUMN reference_price integer,
    ADD COLUMN reference_price_source_url text,
    ADD COLUMN reference_price_at timestamp with time zone;

ALTER TABLE catalog.live_spec_lookup_cache
    ADD CONSTRAINT live_spec_lookup_cache_lookup_key_key UNIQUE (lookup_key),
    ADD CONSTRAINT live_spec_lookup_cache_status_check
        CHECK (status IN ('unreviewed', 'confirmed', 'rejected')),
    ADD CONSTRAINT live_spec_lookup_cache_reference_price_check
        CHECK (reference_price IS NULL OR reference_price > 0),
    ADD CONSTRAINT live_spec_lookup_cache_reference_price_pair_check
        CHECK ((reference_price IS NULL) = (reference_price_at IS NULL));

CREATE INDEX live_spec_lookup_cache_status_idx ON catalog.live_spec_lookup_cache(status);

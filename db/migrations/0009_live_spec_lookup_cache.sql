--
-- 0009_live_spec_lookup_cache.sql
--
-- DB 미보유 부품·주변기기 실시간 스펙 검색 — 캐시 테이블 (docs/미보유부품_실시간스펙검색_설계.md §4).
-- 같은 질의를 볼 때마다 다시 검색+LLM 검증을 돌리면 느리고 비용도 쌓인다. query_text로 유일하게
-- 묶어 재검색을 막는다. relevant=false(검증 실패)도 그대로 캐시한다 — "이 질의는 못 찾았다"는
-- 결과 자체도 재확인할 가치가 있어 다시 캐싱한다(매번 똑같이 실패할 질의를 또 비용 들여 돌리지
-- 않는다).
--
-- 신선도(TTL)는 이 테이블에 안 둔다 — fetched_at만 저장하고, "며칠 지난 캐시는 못 쓴다"는 판단은
-- 애플리케이션이 LIVE_SPEC_LOOKUP_TTL_DAYS(기본 7일, src/config.py)로 한다. 스키마에 만료 시각을
-- 박아두면 TTL 정책을 바꿀 때마다 기존 행을 UPDATE해야 해서, 판단 기준만 코드에 두는 쪽이 더
-- 유연하다.
--

CREATE TABLE catalog.live_spec_lookup_cache (
    id               uuid DEFAULT gen_random_uuid() NOT NULL,
    query_text       text NOT NULL,
    brand            text,
    model            text,
    relevant         boolean NOT NULL,
    supported_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_url       text,
    fetched_at       timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT live_spec_lookup_cache_pkey PRIMARY KEY (id),
    CONSTRAINT live_spec_lookup_cache_query_text_key UNIQUE (query_text)
);

CREATE INDEX live_spec_lookup_cache_fetched_at_idx ON catalog.live_spec_lookup_cache(fetched_at);

-- 0008_review_aspect.sql: 리뷰 속성 분석·집계 및 pgvector 검색 저장 구조.
-- 트랜잭션은 마이그레이션 러너가 관리한다. 기존 리뷰 테이블 폐기는 후속 전환에서 수행한다.
-- 공통 임베딩 모델: OpenAI text-embedding-3-small, 기본 1536차원.
-- 리뷰 원문과 검색 질문 모두 같은 모델·차원을 사용한다.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- 상품은 카탈로그에 직접 연결하고 출처 코드는 리뷰에 저장한다.
CREATE TABLE evidence.review_document (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL REFERENCES catalog.product(id) ON DELETE RESTRICT,
    source_code text NOT NULL CHECK (btrim(source_code) <> ''),
    is_synthetic boolean NOT NULL,
    body text NOT NULL CHECK (btrim(body) <> ''),
    posted_at timestamptz
);

-- 검색 임베딩에는 합의한 두 컬럼만 둔다.
CREATE TABLE evidence.review_embedding (
    review_id uuid PRIMARY KEY REFERENCES evidence.review_document(id) ON DELETE CASCADE,
    embedding public.vector(1536) NOT NULL,
    CHECK (public.vector_norm(embedding) > 0)
);

-- 현재 분석 설정을 식별한다. 규칙 변경 시 전체 재분석하며 이전 결과는 유지하지 않는다.
CREATE TABLE evidence.review_aspect_rule (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_version text NOT NULL CHECK (btrim(analysis_version) <> ''),
    part_type text NOT NULL CHECK (btrim(part_type) <> ''),
    aspect_code text NOT NULL CHECK (btrim(aspect_code) <> ''),
    context_code text NOT NULL CHECK (btrim(context_code) <> ''),
    k numeric NOT NULL CHECK (k > 0 AND k < 'Infinity'::numeric),
    definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
    UNIQUE (analysis_version, part_type, aspect_code, context_code)
);

CREATE TABLE evidence.review_aspect_observation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES evidence.review_document(id) ON DELETE RESTRICT,
    rule_id uuid NOT NULL REFERENCES evidence.review_aspect_rule(id) ON DELETE RESTRICT,
    observation_text text NOT NULL CHECK (btrim(observation_text) <> ''),
    direction text NOT NULL CHECK (direction IN ('positive', 'negative', 'mixed')),
    evidence_sentences jsonb NOT NULL CHECK (
        jsonb_typeof(evidence_sentences) = 'array' AND jsonb_array_length(evidence_sentences) > 0),
    UNIQUE (document_id, rule_id)
);

CREATE TABLE evidence.review_aspect_aggregate (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL REFERENCES catalog.product(id) ON DELETE RESTRICT,
    rule_id uuid NOT NULL REFERENCES evidence.review_aspect_rule(id) ON DELETE RESTRICT,
    p integer NOT NULL CHECK (p >= 0),
    n integer NOT NULL CHECK (n >= 0),
    mixed integer NOT NULL CHECK (mixed >= 0),
    k numeric NOT NULL CHECK (k > 0 AND k < 'Infinity'::numeric),
    q numeric GENERATED ALWAYS AS (
        (p::numeric + k * 0.5) / (p::numeric + n::numeric + k)
    ) STORED,
    UNIQUE (product_id, rule_id)
);
CREATE TABLE evidence.review_aspect_aggregate_member (
    aggregate_id uuid NOT NULL REFERENCES evidence.review_aspect_aggregate(id) ON DELETE CASCADE,
    observation_id uuid NOT NULL REFERENCES evidence.review_aspect_observation(id) ON DELETE RESTRICT,
    PRIMARY KEY (aggregate_id, observation_id)
);

-- 요청 단위는 기존 recommendation_run을 사용한다. 후보 견적들은 같은 실행의 프로필을 공유한다.
CREATE TABLE engine.review_requirement_profile (
    run_id uuid PRIMARY KEY REFERENCES engine.recommendation_run(id) ON DELETE CASCADE,
    profile_version text NOT NULL CHECK (btrim(profile_version) <> ''),
    analysis_version text NOT NULL CHECK (btrim(analysis_version) <> ''),
    parts jsonb NOT NULL CHECK (jsonb_typeof(parts) = 'object')
);

CREATE INDEX review_observation_rule_idx ON evidence.review_aspect_observation(rule_id);
CREATE INDEX review_aggregate_rule_idx ON evidence.review_aspect_aggregate(rule_id);
CREATE INDEX review_document_product_idx ON evidence.review_document(product_id);
CREATE INDEX review_member_observation_idx
    ON evidence.review_aspect_aggregate_member(observation_id);
-- PK·UNIQUE가 제공하는 인덱스는 중복 생성하지 않는다. 벡터 검색은 정확 검색부터 시작한다.

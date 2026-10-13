--
-- 0015_peripheral_post_evidence.sql
--
-- 주변기기 사용기 분석 결과 저장 — 커뮤니티 글에서 뽑은 체감 근거를 주변기기 추천의 체감 점수가 읽는다.
-- 글을 읽는 쪽(community.*)과 외부 리뷰 집계(evidence.review_*)는 건드리지 않는다. 예시 글을 evidence.review_* 에 넣으면
-- 합성 문서 검사(review_aspect_aggregate)와 충돌하므로 별도 테이블로 둔다(개발요청 R-1 결정).
--
--  · peripheral_post_intake    — 분석 대기·상태(글 id 하나에 한 행). 글이 바뀌면 대기로 되돌린다.
--  · peripheral_post_analysis_log — 분석을 시작할 때마다 한 줄. 하루 분석 한도를 센다.
--  · peripheral_post_evidence  — 확정된 체감 문장(제품·속성·방향 또는 쪽·작성자 조건·원문 문장). 점수는 미리 집계하지 않고
--                                요청 때 이 행들로 계산한다. 글을 다시 분석하면 그 글의 행을 지우고 다시 넣는다.
--  · peripheral_post_evidence_embedding — 문장 하나당 벡터 하나(문장 검색 전용, 점수에는 쓰지 않는다).
--
-- community.post 에는 외래키를 걸지 않는다 — 삭제·숨김된 글도 처리해야 하고, 커뮤니티 테이블 변경이 이 쪽을 막으면 안 된다.
--

CREATE TABLE engine.peripheral_post_intake (
    post_id uuid PRIMARY KEY,
    status text NOT NULL DEFAULT 'pending',
    requested_at timestamp with time zone,
    started_at timestamp with time zone,
    processed_at timestamp with time zone,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    -- 마지막으로 분석한 본문·연결 제품의 해시. 같으면 다시 분석하지 않는다.
    analyzed_hash text,
    truncated boolean NOT NULL DEFAULT false,
    -- 이 글을 마지막으로 대기에 올릴 때 본 변경 신호(version·상태·연결 제품·이미지). NULL 이면 아직 본 적이 없다.
    change_signal text,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT peripheral_post_intake_status_check CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT peripheral_post_intake_attempts_check CHECK (attempts >= 0)
);
CREATE INDEX peripheral_post_intake_pending_idx ON engine.peripheral_post_intake (requested_at, post_id)
    WHERE status = 'pending';
CREATE TRIGGER set_updated_at BEFORE UPDATE ON engine.peripheral_post_intake
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE engine.peripheral_post_analysis_log (
    id bigserial PRIMARY KEY,
    post_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX peripheral_post_analysis_log_started_idx ON engine.peripheral_post_analysis_log (started_at);

CREATE TABLE engine.peripheral_post_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL,
    -- 글 안에서 이 문장을 가리키는 안정적인 id(글 id 와 문장 내용으로 정해진다). 인용 문장 이동에 쓴다.
    quote_id text NOT NULL,
    product_id uuid NOT NULL REFERENCES catalog.product(id) ON DELETE CASCADE,
    kind text NOT NULL,
    -- config/peripherals.yaml feel.attributes.<종류> 의 코드, 맞는 속성이 없는 직접 겪은 문장은 'other'
    attribute text NOT NULL,
    direction text,
    side text,
    author_id uuid NOT NULL,
    purposes text[] NOT NULL DEFAULT '{}',
    situations text[] NOT NULL DEFAULT '{}',
    hand_size text,
    evaluated_in text[] NOT NULL DEFAULT '{}',
    is_example boolean NOT NULL DEFAULT false,
    written_at timestamp with time zone,
    sentence text NOT NULL,
    photo_url text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT peripheral_post_evidence_kind_check CHECK (kind IN ('monitor', 'keyboard', 'mouse', 'speaker')),
    CONSTRAINT peripheral_post_evidence_direction_check CHECK (direction IS NULL OR direction IN ('good', 'bad', 'mixed')),
    CONSTRAINT peripheral_post_evidence_hand_check CHECK (hand_size IS NULL OR hand_size IN ('small', 'medium', 'large')),
    -- 평가 속성은 direction, 성향 축은 side 하나만 갖는다. 'other' 는 둘 다 없다.
    CONSTRAINT peripheral_post_evidence_value_check CHECK (
        (attribute = 'other' AND direction IS NULL AND side IS NULL)
        OR (attribute <> 'other' AND ((direction IS NOT NULL) <> (side IS NOT NULL)))),
    CONSTRAINT peripheral_post_evidence_sentence_check CHECK (btrim(sentence) <> '')
);
CREATE UNIQUE INDEX peripheral_post_evidence_key ON engine.peripheral_post_evidence (post_id, quote_id, product_id, attribute);
CREATE INDEX peripheral_post_evidence_product_idx ON engine.peripheral_post_evidence (product_id, attribute)
    WHERE attribute <> 'other';
CREATE INDEX peripheral_post_evidence_kind_idx ON engine.peripheral_post_evidence (kind);

-- 임베딩 행이 없는 문장은 임베딩이 필요하다(리뷰 임베딩과 같은 규칙). 문장 행이 지워지면 함께 지워진다.
CREATE TABLE engine.peripheral_post_evidence_embedding (
    evidence_id uuid PRIMARY KEY REFERENCES engine.peripheral_post_evidence(id) ON DELETE CASCADE,
    embedding public.vector(1536) NOT NULL,
    model text NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

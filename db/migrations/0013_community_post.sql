--
-- 0013_community_post.sql
--
-- 일반 커뮤니티(React /community) — 질문·사용기·정보·자유 게시글, 연결 제품, 댓글·답글, 추천, 조회.
-- 기존 community.review(상품 리뷰: 작성자 1명이 대상 1개에 리뷰 1개)와 성격이 달라 별도 테이블로 둔다.
-- 사용기·리뷰 글만 product_id 로 카탈로그와 연결한다(post_product).
--

CREATE TABLE community.post (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    author_user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE RESTRICT,
    board_type text NOT NULL,
    title text NOT NULL DEFAULT '',
    body text NOT NULL DEFAULT '',
    tags text[] NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'draft',
    is_example boolean NOT NULL DEFAULT false,
    view_count integer NOT NULL DEFAULT 0,
    version integer NOT NULL DEFAULT 1,
    -- 예시 글을 다시 적재해도 두 번 들어가지 않게 하는 외부 키(예: 'A1-1'). 일반 글은 NULL.
    external_id text,
    published_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT post_board_type_check CHECK (board_type IN ('question', 'review', 'tip', 'free')),
    CONSTRAINT post_status_check CHECK (status IN ('draft', 'published', 'hidden', 'deleted')),
    CONSTRAINT post_deleted_at_check CHECK ((status = 'deleted') = (deleted_at IS NOT NULL)),
    CONSTRAINT post_view_count_check CHECK (view_count >= 0),
    CONSTRAINT post_published_check CHECK (
        status NOT IN ('published', 'hidden') OR (btrim(title) <> '' AND btrim(body) <> '' AND published_at IS NOT NULL))
);
CREATE UNIQUE INDEX post_external_id_key ON community.post (external_id) WHERE external_id IS NOT NULL;
CREATE INDEX post_board_published_idx ON community.post (board_type, published_at DESC) WHERE status = 'published';
CREATE INDEX post_published_idx ON community.post (published_at DESC) WHERE status = 'published';
CREATE INDEX post_author_idx ON community.post (author_user_id, created_at DESC);
CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.post FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 글에 연결한 제품. 카탈로그에 없는 제품은 product_id = NULL + custom_product_name 으로 두고
-- match_status 로 정식 상품과 구분한다.
CREATE TABLE community.post_product (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    product_id uuid REFERENCES catalog.product(id) ON DELETE RESTRICT,
    product_kind text NOT NULL,
    custom_product_name text,
    selected_option text,
    match_status text NOT NULL,
    display_order integer NOT NULL DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT post_product_match_check CHECK (match_status IN ('matched', 'unmatched', 'review_needed')),
    CONSTRAINT post_product_identity_check CHECK (
        (product_id IS NOT NULL AND match_status = 'matched')
        OR (product_id IS NULL AND match_status <> 'matched' AND btrim(coalesce(custom_product_name, '')) <> '')),
    CONSTRAINT post_product_order_check CHECK (display_order >= 0)
);
CREATE INDEX post_product_post_idx ON community.post_product (post_id, display_order);
CREATE INDEX post_product_product_idx ON community.post_product (product_id) WHERE product_id IS NOT NULL;

-- 댓글과 한 단계 답글. 삭제는 소프트 삭제 — 답글이 남은 삭제 댓글은 "삭제된 댓글입니다"로 보인다.
CREATE TABLE community.post_comment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    parent_comment_id uuid REFERENCES community.post_comment(id) ON DELETE CASCADE,
    author_user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE RESTRICT,
    body text NOT NULL,
    status text NOT NULL DEFAULT 'published',
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT post_comment_status_check CHECK (status IN ('published', 'hidden', 'deleted')),
    CONSTRAINT post_comment_deleted_at_check CHECK ((status = 'deleted') = (deleted_at IS NOT NULL)),
    CONSTRAINT post_comment_body_check CHECK (btrim(body) <> '')
);
CREATE INDEX post_comment_post_idx ON community.post_comment (post_id, created_at);
CREATE INDEX post_comment_parent_idx ON community.post_comment (parent_comment_id) WHERE parent_comment_id IS NOT NULL;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.post_comment FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 추천: 사용자당 글 1회.
CREATE TABLE community.post_like (
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);
CREATE INDEX post_like_user_idx ON community.post_like (user_id);

-- 조회 이벤트: (글, 조회자, 한 시간 구간)당 한 번만 센다. 인기 점수의 '최근 조회수'도 여기서 센다.
CREATE TABLE community.post_view (
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    viewer_key text NOT NULL,
    bucket timestamp with time zone NOT NULL,
    PRIMARY KEY (post_id, viewer_key, bucket)
);
CREATE INDEX post_view_recent_idx ON community.post_view (post_id, bucket DESC);

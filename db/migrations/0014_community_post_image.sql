--
-- 0014_community_post_image.sql
--
-- 커뮤니티 글 이미지 첨부. 파일 본체는 서버 저장소(src/storage/community_images.py)에 두고 여기엔 위치(storage_key)와
-- 메타데이터만 둔다. 올릴 때는 post_id = NULL 인 임시 상태이고, 글에 연결되면 post_id 가 채워진다.
-- 연결되지 않은 임시 이미지는 일정 시간이 지나면 지운다(community_service.cleanup_orphan_images).
--

CREATE TABLE community.post_image (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE RESTRICT,
    post_id uuid REFERENCES community.post(id) ON DELETE CASCADE,
    storage_key text NOT NULL,
    content_type text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    byte_size integer NOT NULL,
    display_order integer NOT NULL DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT post_image_content_type_check CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
    CONSTRAINT post_image_size_check CHECK (width > 0 AND height > 0 AND byte_size > 0)
);
CREATE UNIQUE INDEX post_image_storage_key_key ON community.post_image (storage_key);
CREATE INDEX post_image_post_idx ON community.post_image (post_id, display_order) WHERE post_id IS NOT NULL;
CREATE INDEX post_image_orphan_idx ON community.post_image (created_at) WHERE post_id IS NULL;
CREATE INDEX post_image_owner_idx ON community.post_image (owner_user_id, created_at DESC);

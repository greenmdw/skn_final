--
-- 0017_community_activity.sql
--
-- 마이페이지 "나의 커뮤니티"(개발요청 A-4, A-5) — 글 저장(북마크)과 커뮤니티 알림.
--  · post_save     — 사용자가 글을 저장한 기록. 사용자당 글 1건 1회(멱등).
--  · notification  — 내 글에 새 댓글(new_comment), 내 댓글에 새 답글(new_reply). **읽기 전에는 같은 글·같은 종류를 한 건으로 묶는다**
--                    (event_count 가 늘고 latest_at 이 갱신된다). 읽으면 그 묶음은 닫히고, 다음 댓글부터 새 알림이 생긴다.
--

CREATE TABLE community.post_save (
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    saved_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);
CREATE INDEX post_save_user_idx ON community.post_save (user_id, saved_at DESC);

CREATE TABLE community.notification (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    type text NOT NULL,
    post_id uuid NOT NULL REFERENCES community.post(id) ON DELETE CASCADE,
    comment_id uuid REFERENCES community.post_comment(id) ON DELETE SET NULL,
    actor_user_id uuid REFERENCES identity.app_user(id) ON DELETE SET NULL,
    event_count integer NOT NULL DEFAULT 1,
    latest_at timestamp with time zone NOT NULL DEFAULT now(),
    read_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT notification_type_check CHECK (type IN ('new_comment', 'new_reply')),
    CONSTRAINT notification_event_count_check CHECK (event_count >= 1)
);
-- 읽기 전의 알림은 (받는 사람, 글, 종류)마다 하나 — 새 댓글이 오면 이 행을 갱신한다
CREATE UNIQUE INDEX notification_unread_group_key ON community.notification (user_id, post_id, type) WHERE read_at IS NULL;
CREATE INDEX notification_user_idx ON community.notification (user_id, latest_at DESC);

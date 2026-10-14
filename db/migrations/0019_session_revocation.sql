--
-- 0019_session_revocation.sql
--
-- 서버 쪽 로그아웃(세션 폐기).
--  · identity.revoked_session  — 로그아웃한 로그인 토큰의 jti. 토큰 만료 시각까지만 보관하고, 그 뒤에는 지워도 된다.
--  · identity.app_user.sessions_revoked_at — "모든 기기에서 로그아웃" 시각. 이 시각 이전에 발급된 토큰은 모두 무효(비밀번호 변경 시각과 같은 방식).
--

ALTER TABLE identity.app_user ADD COLUMN sessions_revoked_at timestamp with time zone;

CREATE TABLE identity.revoked_session (
    jti text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX revoked_session_expires_idx ON identity.revoked_session (expires_at);

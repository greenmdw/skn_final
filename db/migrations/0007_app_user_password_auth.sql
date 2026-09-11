-- 0007_app_user_password_auth.sql — 이메일+비밀번호 인증과 동의·탈퇴 상태
-- email_verified_at과 범용 updated_at은 두지 않는다. 인증/보안 사건은 전용 시각으로 기록한다.

ALTER TABLE identity.app_user
  ADD COLUMN password_hash        text,
  ADD COLUMN password_updated_at  timestamptz,
  ADD COLUMN failed_login_count   integer NOT NULL DEFAULT 0,
  ADD COLUMN locked_until         timestamptz,
  ADD COLUMN last_login_at        timestamptz,
  ADD COLUMN terms_version        text,
  ADD COLUMN terms_agreed_at      timestamptz,
  ADD COLUMN privacy_agreed_at    timestamptz,
  ADD COLUMN marketing_agreed_at  timestamptz,
  ADD COLUMN deleted_at           timestamptz;

-- 기존 소프트 탈퇴 행도 새 제약을 통과하도록 허용된 메타데이터로 보정한다.
UPDATE identity.app_user
SET deleted_at = created_at
WHERE status = 'deleted' AND deleted_at IS NULL;

ALTER TABLE identity.app_user
  ADD CONSTRAINT app_user_failed_login_count_check
    CHECK (failed_login_count >= 0),
  ADD CONSTRAINT app_user_deleted_at_check
    CHECK ((status = 'deleted') = (deleted_at IS NOT NULL)),
  ADD CONSTRAINT app_user_password_time_check
    CHECK (password_hash IS NULL OR password_updated_at IS NOT NULL),
  ADD CONSTRAINT app_user_terms_pair_check
    CHECK ((terms_version IS NULL) = (terms_agreed_at IS NULL));

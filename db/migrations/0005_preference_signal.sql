--
-- 0005_preference_signal.sql
--
-- 사용자 선호·비선호 신호 저장소 (docs/사용자_선호비선호_기록_설계.md).
-- 명시적 발언(explicit_chat)과 반복 교체 행동(inferred_swap)에서 뽑은 신호를 쌓는다.
--
-- 옛 identity.user_preference(가입 시 자동 생성되는 설정 1행, ui_settings로 병합·제거됨,
-- tests/test_schema_reduction.py REMOVED_TABLES)와는 목적·모양이 다르다 — 그건 계정당 1행짜리
-- 설정 블롭이었고, 이건 (user, dimension, slot, value)별로 쌓이는 append형 신호 로그다.
-- 이름을 겹치지 않게 잡아 REMOVED_TABLES 재생성 금지 테스트와도 충돌하지 않는다.
--

CREATE TABLE identity.preference_signal (
    id                  uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id             uuid NOT NULL,
    dimension           text NOT NULL,
    slot                text,
    value               text NOT NULL,
    direction           text NOT NULL,
    source              text NOT NULL,
    confidence          integer DEFAULT 1 NOT NULL,
    evidence_event_ids  uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    status              text DEFAULT 'active'::text NOT NULL,
    first_observed_at   timestamp with time zone DEFAULT now() NOT NULL,
    last_observed_at    timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT preference_signal_direction_check CHECK ((direction = ANY (ARRAY['prefer'::text, 'avoid'::text]))),
    CONSTRAINT preference_signal_source_check CHECK ((source = ANY (ARRAY['explicit_chat'::text, 'inferred_swap'::text]))),
    CONSTRAINT preference_signal_status_check CHECK ((status = ANY (ARRAY['active'::text, 'dismissed'::text])))
);

ALTER TABLE ONLY identity.preference_signal
    ADD CONSTRAINT preference_signal_pkey PRIMARY KEY (id);

ALTER TABLE ONLY identity.preference_signal
    ADD CONSTRAINT preference_signal_user_fk FOREIGN KEY (user_id) REFERENCES identity.app_user(id) ON DELETE CASCADE;

ALTER TABLE ONLY identity.preference_signal
    ADD CONSTRAINT preference_signal_unique UNIQUE (user_id, dimension, slot, value);

CREATE INDEX preference_signal_user_active_idx ON identity.preference_signal USING btree (user_id) WHERE (status = 'active'::text);

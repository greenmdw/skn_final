--
-- 0004_notification_events.sql
--
-- 2026-09-12 팀 결정으로 notification.price_watch_evaluation · notification.notification_event 는
-- "완전 제거" 대상이었다(schema reduction, tests/test_schema_reduction.py 의 REMOVED_TABLES 참고).
-- 2026-09-30 기획서(ACC-02)가 목표가 알림의 판정 이력·발송 관리를 다시 요구해, 팀 재확인(2026-09-27)
-- 뒤 되살린다. 정의는 이 스키마가 아직 있던 마지막 커밋(fc8f69d, db/migrations/0001_tables.sql 등)의
-- DDL을 그대로 옮겼다 — 새로 설계하지 않았다.
--
-- 베이스라인이 0000~0003(4개)에서 0000~0004(5개)로 바뀐다. tests/test_schema_reduction.py 의
-- EXPECTED_CHAIN·REMOVED_TABLES, AGENTS.md·docs/test_status.md 의 "정확히 4개" 문구를 함께 갱신한다.
--

--
-- Name: price_watch_evaluation; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.price_watch_evaluation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    watch_id uuid NOT NULL,
    evaluated_at timestamp with time zone NOT NULL,
    amount numeric(18,2),
    currency character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    status text NOT NULL,
    target_reached boolean,
    breakdown jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT price_watch_evaluation_status_check CHECK ((status = ANY (ARRAY['complete'::text, 'stale'::text, 'unavailable'::text]))),
    CONSTRAINT price_watch_evaluation_complete_check CHECK (((status <> 'complete'::text) OR ((amount IS NOT NULL) AND (target_reached IS NOT NULL))))
);


--
-- Name: notification_event; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.notification_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    evaluation_id uuid NOT NULL,
    user_id uuid NOT NULL,
    channel text DEFAULT 'email'::text NOT NULL,
    dedupe_key text NOT NULL,
    delivery_state text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    sent_at timestamp with time zone,
    read_at timestamp with time zone,
    payload_snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT notification_event_channel_check CHECK ((channel = ANY (ARRAY['email'::text]))),
    CONSTRAINT notification_event_delivery_state_check CHECK ((delivery_state = ANY (ARRAY['pending'::text, 'sent'::text, 'failed'::text])))
);


--
-- Name: price_watch_evaluation price_watch_evaluation_pkey; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.price_watch_evaluation
    ADD CONSTRAINT price_watch_evaluation_pkey PRIMARY KEY (id);

--
-- Name: notification_event notification_event_pkey; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notification_event
    ADD CONSTRAINT notification_event_pkey PRIMARY KEY (id);

--
-- Name: notification_event notification_event_dedupe_key; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notification_event
    ADD CONSTRAINT notification_event_dedupe_key UNIQUE (dedupe_key);

--
-- Name: price_watch_evaluation pwe_watch_fk; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.price_watch_evaluation
    ADD CONSTRAINT pwe_watch_fk FOREIGN KEY (watch_id) REFERENCES notification.price_watch(id) ON DELETE RESTRICT;

--
-- Name: notification_event notif_event_evaluation_fk; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notification_event
    ADD CONSTRAINT notif_event_evaluation_fk FOREIGN KEY (evaluation_id) REFERENCES notification.price_watch_evaluation(id) ON DELETE RESTRICT;

--
-- Name: notification_event notif_event_user_fk; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notification_event
    ADD CONSTRAINT notif_event_user_fk FOREIGN KEY (user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;

--
-- Name: pwe_watch_evaluated_idx; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX pwe_watch_evaluated_idx ON notification.price_watch_evaluation USING btree (watch_id, evaluated_at DESC);

--
-- Name: notif_event_delivery_created_idx; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX notif_event_delivery_created_idx ON notification.notification_event USING btree (delivery_state, created_at);

--
-- Name: notif_event_user_idx; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX notif_event_user_idx ON notification.notification_event USING btree (user_id);

--
-- Name: notification_event set_updated_at; Type: TRIGGER; Schema: notification; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON notification.notification_event FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

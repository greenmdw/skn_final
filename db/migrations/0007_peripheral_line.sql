--
-- 0007_peripheral_line.sql
--
-- 확정 견적서에 주변기기(모니터·키보드·마우스·스피커)를 저장한다 (개발요청 11번).
-- planning.purchase_line(본체 부품)은 offer_id/selected_observation_id가 NOT NULL인데,
-- 주변기기는 실제 offer가 없다(catalog.peripheral_price_snapshot 기반 참고가,
-- price_source는 항상 "reference_snapshot") — 그 제약을 풀기보다 별도 테이블을 둔다.
--

CREATE TABLE planning.peripheral_line (
    id            uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id   uuid NOT NULL,
    kind          text NOT NULL,
    variant_id    uuid NOT NULL,
    pack_count    integer DEFAULT 1 NOT NULL,
    line_amount   numeric(18,2) NOT NULL,
    currency      character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    snapshot      jsonb NOT NULL,
    created_at    timestamp with time zone DEFAULT now() NOT NULL,
    updated_at    timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT peripheral_line_pkey PRIMARY KEY (id),
    CONSTRAINT peripheral_line_revision_fkey FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id),
    CONSTRAINT peripheral_line_variant_fkey FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id),
    CONSTRAINT peripheral_line_kind_check CHECK (kind IN ('monitor', 'keyboard', 'mouse', 'speaker')),
    CONSTRAINT peripheral_line_check CHECK (pack_count > 0 AND line_amount >= 0)
);

CREATE INDEX peripheral_line_revision_idx ON planning.peripheral_line(revision_id);

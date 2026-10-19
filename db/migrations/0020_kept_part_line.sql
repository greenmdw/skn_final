--
-- 0020_kept_part_line.sql
--
-- 받은 견적 점검에서 "일부 교체 후 확정"한 견적서의 **유지한 부품**을 저장한다(재기획 3단계).
-- planning.purchase_line(교체한 부품)은 offer_id/selected_observation_id 가 NOT NULL 이라 판매 정보가 있는 제품만 담는다.
-- 유지 부품은 카탈로그에 없는 제품(국내 소형 브랜드 등)일 수 있고 가격도 모를 수 있어서, 견적에 적힌 그대로를 담는 별도 테이블을 둔다
-- (주변기기 때 0007_peripheral_line.sql 로 peripheral_line 을 따로 둔 것과 같은 이유).
--
-- line_amount 는 가격을 모르면 NULL — 모르는 값을 0원으로 저장하지 않는다.
--

CREATE TABLE planning.kept_part_line (
    id            uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id   uuid NOT NULL,
    slot          text NOT NULL,
    source_text   text NOT NULL,
    variant_id    uuid,
    pack_count    integer DEFAULT 1 NOT NULL,
    line_amount   numeric(18,2),
    currency      character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    snapshot      jsonb NOT NULL,
    created_at    timestamp with time zone DEFAULT now() NOT NULL,
    updated_at    timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT kept_part_line_pkey PRIMARY KEY (id),
    CONSTRAINT kept_part_line_revision_fkey FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id),
    CONSTRAINT kept_part_line_variant_fkey FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id),
    CONSTRAINT kept_part_line_check CHECK (pack_count > 0 AND (line_amount IS NULL OR line_amount >= 0))
);

CREATE INDEX kept_part_line_revision_idx ON planning.kept_part_line(revision_id);

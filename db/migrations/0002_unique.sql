-- 0002_unique.sql — UNIQUE 제약·인덱스
--   · 단순/복합 UNIQUE → ALTER TABLE ADD CONSTRAINT  (FK 타깃 가능)
--   · 부분/표현식/NULLS NOT DISTINCT → CREATE UNIQUE INDEX  (PG15+ 기능, RDS PG15+ OK)
--   · (id, xxx) 복합 UNIQUE 는 6절 복합 FK(C01~C12) 타깃

-- ── config ──
ALTER TABLE config.domain            ADD CONSTRAINT domain_code_key UNIQUE (code);
ALTER TABLE config.domain_version    ADD CONSTRAINT domain_version_domain_no_key UNIQUE (domain_id, version_no);

-- ── identity ──
ALTER TABLE identity.app_user        ADD CONSTRAINT app_user_email_key UNIQUE (email_normalized);
ALTER TABLE identity.app_user        ADD CONSTRAINT app_user_auth_subject_key UNIQUE (auth_subject);
ALTER TABLE identity.message         ADD CONSTRAINT message_conv_client_key UNIQUE (conversation_id, client_message_id);

-- ── planning ──
ALTER TABLE planning.plan            ADD CONSTRAINT plan_conversation_key UNIQUE (conversation_id);
ALTER TABLE planning.plan_revision   ADD CONSTRAINT plan_revision_plan_no_key UNIQUE (plan_id, revision_no);
ALTER TABLE planning.plan_revision   ADD CONSTRAINT plan_revision_id_plan_key UNIQUE (id, plan_id);          -- C01
ALTER TABLE planning.plan_node       ADD CONSTRAINT plan_node_id_rev_key UNIQUE (id, revision_id);            -- C02/C03
ALTER TABLE planning.requirement     ADD CONSTRAINT requirement_id_rev_key UNIQUE (id, revision_id);          -- C02
ALTER TABLE planning.purchase_line   ADD CONSTRAINT purchase_line_id_rev_key UNIQUE (id, revision_id);        -- C02

CREATE UNIQUE INDEX plan_condition_active_key
  ON planning.plan_condition (revision_id, condition_key) WHERE status = 'active';
-- ── catalog ──
ALTER TABLE catalog.product_variant  ADD CONSTRAINT product_variant_prod_key_key UNIQUE (product_id, variant_key);
ALTER TABLE catalog.product_variant  ADD CONSTRAINT product_variant_id_prod_key UNIQUE (id, product_id);     -- C05
ALTER TABLE catalog.product_category ADD CONSTRAINT product_category_code_key UNIQUE (code);
ALTER TABLE catalog.merchant         ADD CONSTRAINT merchant_platform_seller_key UNIQUE (platform, external_seller_id);
ALTER TABLE catalog.offer            ADD CONSTRAINT offer_merchant_ext_key UNIQUE (merchant_id, external_offer_id);
ALTER TABLE catalog.offer_observation ADD CONSTRAINT offer_obs_id_offer_key UNIQUE (id, offer_id);           -- C04

CREATE UNIQUE INDEX product_variant_gtin_key
  ON catalog.product_variant (gtin) WHERE gtin IS NOT NULL;

-- ── assets ──
ALTER TABLE assets.file_object       ADD CONSTRAINT file_object_bucket_key_ver_key UNIQUE (bucket, object_key, storage_version);
ALTER TABLE assets.material_revision ADD CONSTRAINT material_revision_mat_no_key UNIQUE (material_id, revision_no);
ALTER TABLE assets.material_revision ADD CONSTRAINT material_revision_id_mat_key UNIQUE (id, material_id);    -- C06

CREATE UNIQUE INDEX material_applicability_scope_key
  ON assets.material_applicability (revision_id, product_id, variant_id) NULLS NOT DISTINCT;

-- ── community ──
ALTER TABLE community.pc_build_version ADD CONSTRAINT pc_build_version_build_no_key UNIQUE (build_id, version_no);
ALTER TABLE community.pc_build_version ADD CONSTRAINT pc_build_version_id_build_key UNIQUE (id, build_id);    -- C10
ALTER TABLE community.pc_build_component ADD CONSTRAINT pc_build_component_slot_pos_key UNIQUE (build_version_id, slot_key, position);
ALTER TABLE community.review          ADD CONSTRAINT review_author_subject_key UNIQUE (author_user_id, subject_id);
ALTER TABLE community.review_revision ADD CONSTRAINT review_revision_review_no_key UNIQUE (review_id, revision_no);
ALTER TABLE community.review_revision ADD CONSTRAINT review_revision_id_review_key UNIQUE (id, review_id);    -- C12

-- ── evidence ──
CREATE UNIQUE INDEX review_subject_product_key    ON evidence.review_subject (product_id)       WHERE product_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_variant_key    ON evidence.review_subject (variant_id)       WHERE variant_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_offer_key      ON evidence.review_subject (offer_id)         WHERE offer_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_build_ver_key  ON evidence.review_subject (build_version_id) WHERE build_version_id IS NOT NULL;

CREATE UNIQUE INDEX review_summary_external_key
  ON evidence.review_summary (source_id, external_review_key, processing_version)
  WHERE external_review_key IS NOT NULL;
CREATE UNIQUE INDEX review_summary_internal_key
  ON evidence.review_summary (review_revision_id, processing_version)
  WHERE review_revision_id IS NOT NULL;

-- ── engine ──
ALTER TABLE engine.feedback_event    ADD CONSTRAINT feedback_event_key_key UNIQUE (event_key);

-- ── notification ──
CREATE UNIQUE INDEX price_watch_active_scope_key
  ON notification.price_watch (revision_id, purchase_line_id) NULLS NOT DISTINCT
  WHERE state = 'active';

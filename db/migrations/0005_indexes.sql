-- 0005_indexes.sql — 성능 인덱스 (명세서 각 테이블 "인덱스 제안" + FK 조인용)
-- PK/UNIQUE 선두 컬럼과 겹치는 것은 생략. 벡터 ANN 인덱스는 §10대로 초기엔 미적용.

-- ── identity ──
CREATE INDEX conversation_user_created_idx   ON identity.conversation (user_id, created_at DESC);
CREATE INDEX message_conv_created_idx        ON identity.message (conversation_id, created_at);

-- ── planning ──
CREATE INDEX plan_owner_updated_idx          ON planning.plan (owner_user_id, updated_at DESC);
CREATE INDEX plan_revision_plan_state_idx    ON planning.plan_revision (plan_id, state);
CREATE INDEX plan_revision_domain_ver_idx    ON planning.plan_revision (domain_version_id);
CREATE INDEX plan_condition_rev_status_idx   ON planning.plan_condition (revision_id, status);
CREATE INDEX plan_condition_message_idx      ON planning.plan_condition (source_message_id);
CREATE INDEX plan_node_rev_parent_pos_idx    ON planning.plan_node (revision_id, parent_id, position);
CREATE INDEX requirement_rev_status_idx      ON planning.requirement (revision_id, status);
CREATE INDEX requirement_node_idx            ON planning.requirement (node_id, revision_id);
CREATE INDEX purchase_line_rev_idx          ON planning.purchase_line (revision_id);
CREATE INDEX purchase_line_offer_idx        ON planning.purchase_line (offer_id);

-- ── catalog ──
CREATE INDEX product_brand_model_idx         ON catalog.product (brand, model);
CREATE INDEX product_type_status_idx         ON catalog.product (product_type, status);
CREATE INDEX product_category_parent_idx     ON catalog.product_category (parent_id);
CREATE INDEX product_fact_prod_attr_idx      ON catalog.product_fact (product_id, attribute_key, status);
CREATE INDEX product_fact_evidence_idx       ON catalog.product_fact (evidence_id);
CREATE INDEX offer_variant_status_idx        ON catalog.offer (variant_id, status);
CREATE INDEX offer_merchant_idx             ON catalog.offer (merchant_id);
CREATE INDEX offer_obs_offer_observed_idx    ON catalog.offer_observation (offer_id, observed_at DESC);
CREATE INDEX offer_obs_source_idx           ON catalog.offer_observation (source_id);

-- ── assets ──
CREATE INDEX file_object_sha256_idx          ON assets.file_object (sha256);
CREATE INDEX file_object_status_idx          ON assets.file_object (storage_status, scan_status);
CREATE INDEX product_material_source_idx     ON assets.product_material (source_id, material_type, status);
CREATE INDEX material_revision_mat_status_idx ON assets.material_revision (material_id, status);
CREATE INDEX material_revision_file_idx      ON assets.material_revision (file_object_id);
CREATE INDEX material_applicability_prod_idx ON assets.material_applicability (product_id, variant_id, verified);
CREATE INDEX material_applicability_rev_idx  ON assets.material_applicability (revision_id);

-- ── community ──
CREATE INDEX pc_build_owner_updated_idx      ON community.pc_build (owner_user_id, updated_at DESC);
CREATE INDEX pc_build_version_source_plan_idx ON community.pc_build_version (source_plan_revision_id);
CREATE INDEX pc_build_component_variant_idx  ON community.pc_build_component (variant_id, build_version_id);
CREATE INDEX review_subject_status_idx       ON community.review (subject_id, status, created_at DESC);
CREATE INDEX review_author_idx              ON community.review (author_user_id);
CREATE INDEX review_revision_review_no_idx   ON community.review_revision (review_id, revision_no DESC);
CREATE INDEX review_revision_domain_ver_idx  ON community.review_revision (domain_version_id);

-- ── evidence ──
CREATE INDEX evidence_source_idx             ON evidence.evidence (source_id);
CREATE INDEX evidence_retrieval_hit_idx      ON evidence.evidence (retrieval_hit_id);
CREATE INDEX evidence_review_aggregate_idx   ON evidence.evidence (review_aggregate_id);
CREATE INDEX evidence_status_valid_idx       ON evidence.evidence (status, valid_until);
CREATE INDEX review_summary_subject_idx      ON evidence.review_summary (subject_id, status, cleaning_status);
CREATE INDEX review_summary_source_idx       ON evidence.review_summary (source_id);
CREATE INDEX review_aggregate_subject_idx    ON evidence.review_aggregate (subject_id, source_scope, status, window_end DESC);
CREATE INDEX review_aggregate_domain_ver_idx ON evidence.review_aggregate (domain_version_id);
CREATE INDEX ram_summary_idx                 ON evidence.review_aggregate_member (summary_id);

-- ── engine ──
CREATE INDEX rec_run_revision_created_idx    ON engine.recommendation_run (revision_id, created_at DESC);
CREATE INDEX rec_run_domain_ver_idx          ON engine.recommendation_run (domain_version_id);
CREATE INDEX rec_cand_run_result_idx         ON engine.recommendation_candidate (run_id, result);
CREATE INDEX rec_cand_requirement_idx        ON engine.recommendation_candidate (requirement_id);
CREATE INDEX rec_cand_variant_idx            ON engine.recommendation_candidate (variant_id);
CREATE INDEX validation_result_run_status_idx ON engine.validation_result (run_id, status);
CREATE INDEX feedback_event_type_time_idx    ON engine.feedback_event (event_type, occurred_at);
CREATE INDEX feedback_event_plan_time_idx    ON engine.feedback_event (plan_id, occurred_at);
CREATE INDEX feedback_event_revision_idx     ON engine.feedback_event (revision_id);
CREATE INDEX feedback_event_rec_run_idx      ON engine.feedback_event (recommendation_run_id);

-- ── notification ──
CREATE INDEX price_watch_state_ends_idx      ON notification.price_watch (state, ends_at);
CREATE INDEX price_watch_revision_idx        ON notification.price_watch (revision_id);

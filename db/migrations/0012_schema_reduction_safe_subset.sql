-- 0012_schema_reduction_safe_subset.sql — 최종 축소 스키마 보강
-- 삭제 대상 객체는 초기 마이그레이션에서 만들지 않는다. 여기서는 최종 스키마에
-- 필요한 컬럼과 제약만 추가한다.

ALTER TABLE identity.app_user
  ADD COLUMN ui_settings           jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN notification_settings jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE catalog.product ADD COLUMN category_id uuid;
ALTER TABLE catalog.product
  ADD CONSTRAINT product_category_fk FOREIGN KEY (category_id)
  REFERENCES catalog.product_category (id) ON DELETE RESTRICT;

ALTER TABLE engine.recommendation_candidate
  ADD COLUMN evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE engine.validation_result
  ADD COLUMN issues jsonb NOT NULL DEFAULT '[]'::jsonb;

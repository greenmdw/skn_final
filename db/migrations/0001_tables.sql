-- 0001_tables.sql — 축소된 핵심 테이블 (컬럼 · PK · CHECK · DEFAULT). FK 없음.
-- FK/복합 UNIQUE → 0002, 0003. 트리거 → 0004. 성능 인덱스 → 0005.
-- 명세서: PlanBasket_테이블_명세서 v4. C## 는 6절 교차 무결성 항목.

-- ══════════════════════════════ config ══════════════════════════════
CREATE TABLE config.domain (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL,
  name        text NOT NULL,
  status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','disabled')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE config.domain_version (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id         uuid NOT NULL,
  version_no        integer NOT NULL CHECK (version_no > 0),
  definition        jsonb NOT NULL,
  attribute_schema  jsonb NOT NULL,
  content_hash      text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ identity ══════════════════════════════
CREATE TABLE identity.app_user (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email_normalized   text NOT NULL,
  auth_subject       text NOT NULL,
  display_name       text NOT NULL,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE identity.conversation (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid,
  guest_session_hash   text,
  expires_at           timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (user_id IS NOT NULL OR guest_session_hash IS NOT NULL)
);

CREATE TABLE identity.message (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id    uuid NOT NULL,
  role               text NOT NULL CHECK (role IN ('user','assistant','system')),
  content            text NOT NULL,
  client_message_id  text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ planning ══════════════════════════════
CREATE TABLE planning.plan (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id      uuid NOT NULL,
  owner_user_id        uuid,
  name                 text NOT NULL,
  current_revision_id  uuid,                         -- C01: 생성 시 NULL, 같은 트랜잭션에서 설정
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planning.plan_revision (
  id                   uuid NOT NULL DEFAULT gen_random_uuid(),
  plan_id              uuid NOT NULL,
  revision_no          integer NOT NULL,
  domain_version_id    uuid NOT NULL,
  state                text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','confirmed')),
  lock_version         integer NOT NULL DEFAULT 0,
  name_snapshot        text NOT NULL,
  confirmed_at         timestamptz,
  planned_purchase_at  timestamptz,
  confirmed_total      numeric(18,2),
  currency             char(3) NOT NULL DEFAULT 'KRW',
  pricing_policy       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (revision_no > 0 AND lock_version >= 0),
  CHECK (confirmed_total IS NULL OR confirmed_total >= 0),
  CHECK (state <> 'confirmed' OR (confirmed_at IS NOT NULL AND confirmed_total IS NOT NULL))
);

CREATE TABLE planning.plan_condition (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id        uuid NOT NULL,
  condition_key      text NOT NULL,
  value              jsonb NOT NULL,
  origin             text NOT NULL CHECK (origin IN ('explicit','extracted','inferred')),
  source_message_id  uuid,
  supersedes_id      uuid,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','deleted')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planning.plan_node (
  id            uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id   uuid NOT NULL,
  parent_id     uuid,
  node_type     text NOT NULL CHECK (node_type IN ('group','slot')),
  template_key  text NOT NULL,
  name          text NOT NULL,
  position      integer NOT NULL DEFAULT 0,
  context       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE planning.requirement (
  id              uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id     uuid NOT NULL,
  node_id         uuid NOT NULL,
  quantity        numeric(18,4) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_code       text NOT NULL DEFAULT 'each',
  required        boolean NOT NULL DEFAULT true,
  needed_at       timestamptz,
  timing_context  jsonb NOT NULL DEFAULT '{}'::jsonb,
  match_spec      jsonb NOT NULL DEFAULT '{}'::jsonb,
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','excluded')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE planning.purchase_line (
  id                       uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id              uuid NOT NULL,
  offer_id                 uuid NOT NULL,
  selected_observation_id  uuid NOT NULL,
  pack_count               integer NOT NULL DEFAULT 1,
  line_amount              numeric(18,2) NOT NULL,
  currency                 char(3) NOT NULL DEFAULT 'KRW',
  snapshot                 jsonb NOT NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (pack_count > 0 AND line_amount >= 0)
);

-- ══════════════════════════════ catalog ══════════════════════════════
CREATE TABLE catalog.product (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  brand         text NOT NULL,
  model         text NOT NULL,
  product_type  text NOT NULL,
  attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
  image_url     text,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','discontinued')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.product_variant (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  product_id     uuid NOT NULL,
  variant_key    text NOT NULL,
  gtin           text,
  attributes     jsonb NOT NULL DEFAULT '{}'::jsonb,
  pack_quantity  numeric(18,4) NOT NULL DEFAULT 1 CHECK (pack_quantity > 0),
  unit_code      text NOT NULL DEFAULT 'each',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE catalog.product_category (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   uuid,
  code        text NOT NULL,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.product_fact (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id     uuid NOT NULL,
  variant_id     uuid,
  attribute_key  text NOT NULL,
  value          jsonb NOT NULL,
  unit_code      text,
  evidence_id    uuid NOT NULL,
  observed_at    timestamptz NOT NULL,
  valid_until    timestamptz,
  status         text NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','verified','superseded','revoked')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.merchant (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform            text NOT NULL,
  external_seller_id  text NOT NULL,
  name                text NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.offer (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_id         uuid NOT NULL,
  merchant_id        uuid NOT NULL,
  external_offer_id  text NOT NULL,
  purchase_url       text NOT NULL,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','sold_out','expired')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.offer_observation (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  offer_id       uuid NOT NULL,
  source_id      uuid NOT NULL,
  observed_at    timestamptz NOT NULL,
  price          numeric(18,2),
  currency       char(3) NOT NULL DEFAULT 'KRW',
  stock_status   text NOT NULL CHECK (stock_status IN ('available','sold_out','unknown')),
  pricing_terms  jsonb NOT NULL DEFAULT '{}'::jsonb,
  quality_status text NOT NULL CHECK (quality_status IN ('valid','failed','stale')),
  valid_until    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (price IS NULL OR price >= 0),
  CHECK (quality_status <> 'valid' OR price IS NOT NULL)
);

-- ══════════════════════════════ assets ══════════════════════════════
CREATE TABLE assets.file_object (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket             text NOT NULL,
  object_key         text NOT NULL,
  storage_version    text NOT NULL,
  original_filename  text NOT NULL,
  mime_type          text NOT NULL,
  byte_size          bigint NOT NULL,
  sha256             text NOT NULL,
  access_scope       text NOT NULL DEFAULT 'internal' CHECK (access_scope IN ('public','internal')),
  use_policy         jsonb NOT NULL DEFAULT '{}'::jsonb,
  scan_status        text NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','rejected')),
  storage_status     text NOT NULL DEFAULT 'pending'
                     CHECK (storage_status IN ('pending','available','quarantined','purged')),
  uploaded_by        uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (byte_size > 0 AND length(sha256) = 64)
);

CREATE TABLE assets.product_material (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id            uuid NOT NULL,
  title                text NOT NULL,
  material_type        text NOT NULL
                       CHECK (material_type IN ('manual','spec_sheet','image','certification')),
  current_revision_id  uuid,
  status               text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assets.material_revision (
  id                    uuid NOT NULL DEFAULT gen_random_uuid(),
  material_id            uuid NOT NULL,
  revision_no            integer NOT NULL,
  file_object_id         uuid NOT NULL,
  source_url             text,
  language               text NOT NULL,
  issued_at              date,
  retrieved_at           timestamptz NOT NULL,
  active_ingestion_id    uuid,
  status                 text NOT NULL DEFAULT 'staged'
                         CHECK (status IN ('staged','published','superseded','revoked')),
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE assets.material_applicability (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id  uuid NOT NULL,
  product_id   uuid NOT NULL,
  variant_id   uuid,
  conditions   jsonb NOT NULL DEFAULT '{}'::jsonb,
  verified     boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ community ══════════════════════════════
CREATE TABLE community.pc_build (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id       uuid NOT NULL,
  name                text NOT NULL,
  current_version_id  uuid,
  visibility          text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','public')),
  status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE community.pc_build_version (
  id                        uuid NOT NULL DEFAULT gen_random_uuid(),
  build_id                  uuid NOT NULL,
  version_no                integer NOT NULL,
  source_plan_revision_id   uuid,
  state                     text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','published')),
  usage_status              text NOT NULL DEFAULT 'planned'
                            CHECK (usage_status IN ('planned','assembled_self_reported')),
  assembled_at              date,
  environment               jsonb NOT NULL DEFAULT '{}'::jsonb,
  configuration_hash        text,
  published_at              timestamptz,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE community.pc_build_component (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  build_version_id    uuid NOT NULL,
  slot_key            text NOT NULL,
  position            integer NOT NULL DEFAULT 0,
  variant_id          uuid NOT NULL,
  quantity            integer NOT NULL DEFAULT 1,
  component_snapshot  jsonb NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (quantity > 0 AND position >= 0)
);

CREATE TABLE community.review (
  id                   uuid NOT NULL DEFAULT gen_random_uuid(),
  author_user_id       uuid NOT NULL,
  subject_id           uuid NOT NULL,
  current_revision_id  uuid,
  status               text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft','published','hidden','deleted')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE community.review_revision (
  id                 uuid NOT NULL DEFAULT gen_random_uuid(),
  review_id          uuid NOT NULL,
  revision_no        integer NOT NULL,
  domain_version_id  uuid NOT NULL,
  rating             smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title              text NOT NULL,
  body               text NOT NULL,
  axis_scores        jsonb NOT NULL DEFAULT '{}'::jsonb,
  usage_context      jsonb NOT NULL DEFAULT '{}'::jsonb,
  moderation_status  text NOT NULL DEFAULT 'pending'
                     CHECK (moderation_status IN ('pending','approved','rejected','redacted')),
  published_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

-- ══════════════════════════════ evidence ══════════════════════════════
CREATE TABLE evidence.source (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL,
  source_type  text NOT NULL CHECK (source_type IN
               ('manufacturer','public_registry','merchant','external_review','first_party','derived')),
  base_url     text,
  rating_scale jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence.evidence (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id            uuid NOT NULL,
  kind                 text NOT NULL CHECK (kind IN ('material','review_aggregate','external_fact')),
  retrieval_hit_id     uuid,
  review_aggregate_id  uuid,
  source_url           text,
  facts                jsonb NOT NULL DEFAULT '{}'::jsonb,
  citation_snapshot    jsonb NOT NULL,
  retrieved_at         timestamptz NOT NULL,
  valid_until          timestamptz,
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','superseded','revoked')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (kind = 'material'         AND retrieval_hit_id IS NOT NULL AND review_aggregate_id IS NULL     AND source_url IS NULL)
 OR (kind = 'review_aggregate' AND review_aggregate_id IS NOT NULL AND retrieval_hit_id IS NULL     AND source_url IS NULL)
 OR (kind = 'external_fact'    AND source_url IS NOT NULL AND retrieval_hit_id IS NULL AND review_aggregate_id IS NULL)
  )
);

CREATE TABLE evidence.review_subject (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        uuid,
  variant_id        uuid,
  offer_id          uuid,
  build_version_id  uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(product_id, variant_id, offer_id, build_version_id) = 1)
);

CREATE TABLE evidence.review_summary (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id           uuid NOT NULL,
  source_id            uuid NOT NULL,
  origin               text NOT NULL CHECK (origin IN ('external','first_party')),
  external_review_key  text,
  original_url         text,
  review_revision_id   uuid,
  summary              text NOT NULL,
  normalized_rating    numeric(3,2),
  collected_at         timestamptz NOT NULL,
  processing_version   text NOT NULL,
  cleaning_status      text NOT NULL CHECK (cleaning_status IN ('retained','excluded','pending')),
  exclusion_reason     text,
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','superseded','revoked')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (origin = 'external'    AND external_review_key IS NOT NULL AND original_url IS NOT NULL AND review_revision_id IS NULL)
 OR (origin = 'first_party' AND review_revision_id IS NOT NULL AND external_review_key IS NULL)
  ),
  CHECK (normalized_rating IS NULL OR (normalized_rating >= 0 AND normalized_rating <= 5))
);

CREATE TABLE evidence.review_aggregate (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id         uuid NOT NULL,
  domain_version_id  uuid NOT NULL,
  source_scope       text NOT NULL CHECK (source_scope IN ('external','first_party','combined')),
  processing_version text NOT NULL,
  window_start       timestamptz NOT NULL,
  window_end         timestamptz NOT NULL,
  analyzed_count     integer NOT NULL DEFAULT 0,
  excluded_count     integer NOT NULL DEFAULT 0,
  retained_count     integer NOT NULL DEFAULT 0,
  ratings            jsonb NOT NULL DEFAULT '{}'::jsonb,
  axis_scores        jsonb NOT NULL DEFAULT '{}'::jsonb,
  status             text NOT NULL DEFAULT 'building'
                     CHECK (status IN ('building','ready','stale','revoked')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (analyzed_count = excluded_count + retained_count AND excluded_count >= 0 AND retained_count >= 0),
  CHECK (window_end >= window_start)
);

CREATE TABLE evidence.review_aggregate_member (
  aggregate_id  uuid NOT NULL,
  summary_id    uuid NOT NULL,
  disposition   text NOT NULL CHECK (disposition IN ('retained','excluded')),
  weight        numeric(8,4) NOT NULL DEFAULT 1 CHECK (weight > 0),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (aggregate_id, summary_id)
);

-- ══════════════════════════════ engine ══════════════════════════════
CREATE TABLE engine.recommendation_run (
  id                 uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id        uuid NOT NULL,
  domain_version_id  uuid NOT NULL,
  input_snapshot     jsonb NOT NULL,
  input_hash         text NOT NULL,
  draft_lock_version integer NOT NULL,
  engine_versions    jsonb NOT NULL,
  status             text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','running','completed','failed','stale')),
  completed_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE engine.recommendation_candidate (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                 uuid NOT NULL,
  requirement_id         uuid NOT NULL,
  variant_id             uuid NOT NULL,
  offer_observation_id   uuid,
  result                 text NOT NULL CHECK (result IN ('pending','passed','rejected','selected')),
  score                  numeric(8,4),
  score_method_version   text,
  reason                 text,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CHECK (score IS NULL OR score_method_version IS NOT NULL)
);

CREATE TABLE engine.validation_result (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            uuid NOT NULL,
  rule_key          text NOT NULL,
  rule_version      text NOT NULL,
  executor_version  text NOT NULL,
  status            text NOT NULL CHECK (status IN ('pass','fail','unknown','not_applicable')),
  severity          text NOT NULL CHECK (severity IN ('info','warning','critical')),
  measured_values   jsonb NOT NULL DEFAULT '{}'::jsonb,
  threshold         jsonb NOT NULL DEFAULT '{}'::jsonb,
  message           text NOT NULL,
  checked_at        timestamptz NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE engine.feedback_event (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id                uuid NOT NULL,
  revision_id            uuid NOT NULL,
  recommendation_run_id  uuid,
  user_id                uuid,
  event_type             text NOT NULL CHECK (event_type IN
                         ('recommendation_shown','item_replaced','item_removed','plan_confirmed')),
  event_key              text NOT NULL,
  payload                jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at            timestamptz NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  CHECK (event_type <> 'recommendation_shown' OR recommendation_run_id IS NOT NULL)
);

-- ══════════════════════════════ notification ══════════════════════════════
CREATE TABLE notification.price_watch (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id           uuid NOT NULL,
  purchase_line_id      uuid,
  target_amount         numeric(18,2) NOT NULL CHECK (target_amount >= 0),
  currency              char(3) NOT NULL DEFAULT 'KRW',
  pricing_policy        jsonb NOT NULL,
  state                 text NOT NULL DEFAULT 'active' CHECK (state IN ('active','paused','expired')),
  ends_at               timestamptz NOT NULL,
  last_condition_state  text NOT NULL DEFAULT 'unknown'
                        CHECK (last_condition_state IN ('unknown','above','reached')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- part_reference_draft.sql — 참조 스펙(가격 없는 부품의 스펙) 스키마 초안
--
-- 상태: **초안(팀 검토용)** — db/migrations 체인 밖(db/drafts)에 둔다. migrate.py 가 읽지 않고, 확정되면
-- 0017_*.sql 로 옮긴다. 설계 근거·결정 사항: docs/db/part_reference_schema_draft.md
--
-- 목적: 업그레이드 사용자가 "그대로 쓰는" 구형 부품(i5-8400, Ryzen 5 3600, GTX 1060 …)은 카탈로그(판매 후보)에
--   없어 스펙을 못 읽는다(소켓은 이름 규칙으로 추정하지만 전력·권장 파워는 데이터가 필요). 판매하지 않는 부품의
--   스펙만 담는다.
--
-- 설계 원칙
--   1) 새 스펙 테이블을 만들지 않는다 — 참조 부품도 catalog.product + 0015 의 cpu_spec/gpu_spec 를 그대로 쓴다.
--      (가격 없는 상품은 후보 로더가 variant·offer 를 조인하므로 자동으로 후보에서 빠진다.)
--   2) 그 위에 얹는 것은 셋뿐이다: part_reference(참조 메타 1:1), part_alias(이름 별칭), chipset_reference(칩셋 사전).
--   3) 참조 부품은 판매 후보가 될 수 없다 — variant/offer 를 붙이지 못하게 트리거로 막는다.
--   4) 모르는 것은 비워 둔다 — 수치는 근거(source_url)·확인일·신뢰도와 함께만 들어간다.

BEGIN;

-- ── 1) 참조 메타 (product 와 1:1) ────────────────────────────────────────────────────────────
CREATE TABLE catalog.part_reference (
  product_id       uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  reference_only   boolean NOT NULL DEFAULT true,          -- true: 가격·판매처가 없는 스펙 전용(추천 후보 아님)
  generation       text,                                    -- 표시·필터용: 'Intel 8th', 'Ryzen 3000', 'GeForce 10'
  release_year     smallint CHECK (release_year BETWEEN 2000 AND 2100),
  spec_confidence  text NOT NULL CHECK (spec_confidence IN ('verified', 'vendor_spec', 'estimated')),
                                                            -- verified: 실물·복수 출처 확인 / vendor_spec: 제조사 공개 사양 / estimated: 추정
  source_url       text NOT NULL,                           -- 스펙 근거(제조사 공개 사양 페이지 등)
  source_note      text,
  verified_at      date NOT NULL,
  verified_by      text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE catalog.part_reference IS
  '가격 없는 부품(단종·구형)의 스펙 참조 메타. product/cpu_spec/gpu_spec 를 재사용하고 출처·신뢰도만 더한다.
   GPU 길이는 제조사 카드마다 달라 gpu_spec.length_mm 에 "최대값(보수적)"을 넣고, 범위·근거는 기존 gpu_spec.spec_basis(자유 텍스트)에 적는다.';

-- ── 2) 이름 별칭 ─────────────────────────────────────────────────────────────────────────────
-- 사용자는 "GTX1060", "지포스 1060 6GB", "i5 8400" 처럼 쓴다. 기본 이름(brand+model)에 없는 표기를 등록한다.
CREATE TABLE catalog.part_alias (
  product_id  uuid NOT NULL REFERENCES catalog.product(id) ON DELETE CASCADE,
  alias       text NOT NULL,
  alias_norm  text GENERATED ALWAYS AS (lower(regexp_replace(alias, '[^0-9A-Za-z가-힣]', '', 'g'))) STORED,
  PRIMARY KEY (product_id, alias_norm),
  CHECK (length(alias) >= 3)
);
CREATE INDEX part_alias_norm_idx ON catalog.part_alias (alias_norm);
COMMENT ON COLUMN catalog.part_alias.alias_norm IS '소문자·영숫자·한글만 남긴 비교 키(자동 생성). 정확 일치 조회용.';

-- ── 3) 칩셋 사전 ─────────────────────────────────────────────────────────────────────────────
-- 메인보드는 SKU 가 너무 많아(수천) 참조 행을 만들지 않는다. 대신 칩셋(B450, B760 …)이 소켓·메모리를 정한다.
-- 지금은 코드(owned_parts._CHIPSET_SOCKET)에 박혀 있는 규칙표를 데이터로 옮겨 코드 수정 없이 갱신한다.
CREATE TABLE catalog.chipset_reference (
  chipset       text PRIMARY KEY,                           -- 'B450' (대문자)
  vendor        text NOT NULL CHECK (vendor IN ('AMD', 'Intel')),
  socket        text NOT NULL,
  memory_types  text[] NOT NULL,                            -- {'DDR4'} | {'DDR4','DDR5'}(보드마다 다름 -> 소켓만 확정)
  release_year  smallint,
  source_url    text NOT NULL,
  note          text,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ── 4) 무결성: 참조 전용 부품은 판매 후보가 될 수 없다 ────────────────────────────────────────────
CREATE FUNCTION catalog.guard_reference_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'product_variant' THEN
    IF EXISTS (SELECT 1 FROM catalog.part_reference r
               WHERE r.product_id = NEW.product_id AND r.reference_only) THEN
      RAISE EXCEPTION '참조 전용 부품(product %)에는 variant 를 만들 수 없다', NEW.product_id
        USING ERRCODE = 'check_violation';
    END IF;
  ELSE  -- part_reference: reference_only 로 표시하려면 이미 variant 가 없어야 한다
    IF NEW.reference_only AND EXISTS (SELECT 1 FROM catalog.product_variant v WHERE v.product_id = NEW.product_id) THEN
      RAISE EXCEPTION '이미 variant 가 있는 상품(product %)은 참조 전용으로 표시할 수 없다', NEW.product_id
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER part_reference_guard BEFORE INSERT OR UPDATE ON catalog.part_reference
  FOR EACH ROW EXECUTE FUNCTION catalog.guard_reference_only();
CREATE TRIGGER product_variant_reference_guard BEFORE INSERT ON catalog.product_variant
  FOR EACH ROW EXECUTE FUNCTION catalog.guard_reference_only();
CREATE TRIGGER part_reference_set_updated_at BEFORE UPDATE ON catalog.part_reference
  FOR EACH ROW EXECUTE FUNCTION shared.set_updated_at();

-- ── 5) 조회 뷰: 판매 후보 + 참조 부품을 한 모양으로 ──────────────────────────────────────────────────
-- 엔진(owned_parts.resolve_owned_parts)이 유지 부품 이름을 스펙으로 바꿀 때 이 뷰 하나만 읽는다.
-- 컬럼 이름은 catalog_repo._specs_from_row 가 읽는 이름과 같아(socket, tdp_w, memory_type, power_w,
-- recommended_psu_w, length_mm …) 로더 변경이 최소다. 참조 범위는 CPU·GPU 뿐이다(보드는 칩셋 사전).
CREATE VIEW catalog.part_lookup_v AS
SELECT p.id AS product_id, 'CPU'::text AS slot, p.brand, p.model, p.name, p.status,
       COALESCE(r.reference_only, false) AS reference_only, r.spec_confidence, r.generation,
       c.socket, c.memory_type, c.tdp_w, c.integrated_graphics, c.lineup,
       NULL::integer AS power_w, NULL::integer AS recommended_psu_w, NULL::integer AS length_mm
FROM catalog.product p
JOIN catalog.cpu_spec c ON c.product_id = p.id
LEFT JOIN catalog.part_reference r ON r.product_id = p.id
UNION ALL
SELECT p.id, 'GPU', p.brand, p.model, p.name, p.status,
       COALESCE(r.reference_only, false), r.spec_confidence, r.generation,
       NULL, g.memory_type, NULL::integer, NULL, g.lineup,
       g.power_w, g.recommended_psu_w, g.length_mm
FROM catalog.product p
JOIN catalog.gpu_spec g ON g.product_id = p.id
LEFT JOIN catalog.part_reference r ON r.product_id = p.id;
COMMENT ON VIEW catalog.part_lookup_v IS
  '유지 부품 이름 -> 스펙 조회용. 판매 후보(reference_only=false)와 참조 부품(true)을 같은 컬럼으로 낸다.';

-- ── 6) 점검 뷰: 규칙을 어긴 행 찾기 (비어 있어야 정상) ───────────────────────────────────────────────
CREATE VIEW catalog.part_reference_issues_v AS
SELECT r.product_id, p.brand, p.model, x.issue
FROM catalog.part_reference r
JOIN catalog.product p ON p.id = r.product_id
CROSS JOIN LATERAL (VALUES
  ('CPU 스펙 행 없음', p.product_type = 'cpu' AND NOT EXISTS (SELECT 1 FROM catalog.cpu_spec c WHERE c.product_id = p.id)),
  ('GPU 스펙 행 없음', p.product_type = 'gpu' AND NOT EXISTS (SELECT 1 FROM catalog.gpu_spec g WHERE g.product_id = p.id)),
  ('CPU 소켓 없음', p.product_type = 'cpu' AND EXISTS (SELECT 1 FROM catalog.cpu_spec c WHERE c.product_id = p.id AND c.socket IS NULL)),
  ('GPU 권장 파워·소비전력 둘 다 없음', p.product_type = 'gpu' AND EXISTS (
      SELECT 1 FROM catalog.gpu_spec g WHERE g.product_id = p.id AND g.power_w IS NULL AND g.recommended_psu_w IS NULL)),
  ('참조 범위 밖 유형(CPU·GPU 만)', p.product_type NOT IN ('cpu', 'gpu')),
  ('판매 후보인데 reference_only', r.reference_only AND EXISTS (SELECT 1 FROM catalog.product_variant v WHERE v.product_id = p.id))
) AS x(issue, violated)
WHERE x.violated;

COMMIT;

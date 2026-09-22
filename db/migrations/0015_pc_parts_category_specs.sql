-- 0015_pc_parts_category_specs.sql — PC 부품 카테고리별 스펙 테이블(JOIN 방식)
--
-- catalog.product_fact(EAV)는 그대로 둔다 — 이 마이그레이션은 그것을 대체하지 않고,
-- PC 부품 8종처럼 카테고리별 컬럼이 이미 고정돼 있고 호환성 판정(소켓 매칭, GPU 길이
-- vs 케이스 허용치, PSU 용량 vs 총 TDP 등)에 타입 안전한 컬럼 비교가 필요한 경우를 위해
-- 카테고리별 전용 테이블을 추가한다. 팀 논의 결론(2026-09-18): 카테고리 수가 고정돼
-- 있고 소스 데이터(data/parts_list_modify.xlsx)가 이미 카테고리별 고정 컬럼 표라서
-- EAV보다 JOIN이 맞다.
--
-- 각 테이블은 catalog.product(id)와 1:1 — product_id 가 PK 이자 FK. 상품 공통 정보
-- (브랜드·모델·image_url·status)는 기존 catalog.product 를 그대로 쓰고, 가격은 기존
-- catalog.offer/offer_observation 경로를 그대로 쓴다(다른 카테고리와 동일한 방식).
--
-- size_note/weight_note: 대부분 PC 부품에서는 의미 없는 값(NULL)이 정상이다 — 실제
-- 호환성 판정에 쓰는 치수는 각 테이블의 전용 컬럼(length_mm, height_mm 등)이 담당한다.
-- sale_status/status_checked_at/note: 원본 엑셀 시트마다 있거나 없어서, 없는 시트의
-- 행은 NULL로 남는다(정상).

CREATE TABLE catalog.cpu_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  socket               text,
  tdp_w                integer,
  memory_type          text,
  integrated_graphics  text,
  cooler_included      text,
  lineup               text,
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.mainboard_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  socket               text,
  chipset              text,
  form_factor          text,
  memory_type          text,
  board_size_mm        text,
  supported_cpu_family text,
  bios_note            text,
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.ram_spec (
  product_id             uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  memory_type            text,
  speed_mts              integer,
  total_capacity_gb      integer,
  module_config          text,
  capacity_per_module_gb integer,
  cas_latency            integer,
  form_factor            text,
  pin_count              integer,
  voltage_v              numeric(4,2),
  ecc                    text,
  buffer_type            text,
  oc_profile             text,
  heatsink               text,
  rgb                    text,
  size_note              text,
  weight_note            text,
  spec_url               text,
  sale_status            text,
  status_checked_at      date,
  note                   text,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.gpu_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  gpu_class            text,
  vram_gb              text,  -- "8 / 16"처럼 라인업 전체를 나타내는 행이 있어 단일 정수로 못 담음
  memory_type          text,
  pcie_interface       text,
  power_w              integer,
  recommended_psu_w    integer,
  length_mm            integer,
  height_mm            integer,
  slot_thickness       text,
  power_connector      text,
  aux_power            text,
  ecc                  text,
  lineup               text,
  spec_basis           text,
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.ssd_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  interface            text,
  protocol             text,
  form_factor          text,
  heatsink             text,
  capacity_options     text,
  nand_type            text,
  dram                 text,
  ps5_compat           text,
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.psu_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  wattage_w            integer,
  efficiency_rating    text,
  form_factor          text,
  cable_type           text,
  gpu_power_connector  text,
  atx_spec             text,
  modular              text,
  length_mm            integer,  -- 원본 엑셀엔 아직 없음(수집 예정) — 소형 케이스 장착 가능 여부 판정에 필요
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.case_spec (
  product_id            uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  supported_motherboard text,
  cpu_cooler_height_mm  integer,
  gpu_max_length_mm     integer,
  psu_form_factor       text,
  case_type             text,
  size_note             text,
  weight_note           text,
  spec_url              text,
  sale_status           text,
  status_checked_at     date,
  note                  text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.cooler_spec (
  product_id           uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  cooling_type         text,
  supported_socket     text,
  cooler_height_mm     integer,
  radiator_mm          integer,
  case_check_note      text,
  size_note            text,
  weight_note          text,
  spec_url             text,
  sale_status          text,
  status_checked_at    date,
  note                 text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'catalog.cpu_spec','catalog.mainboard_spec','catalog.ram_spec','catalog.gpu_spec',
    'catalog.ssd_spec','catalog.psu_spec','catalog.case_spec','catalog.cooler_spec'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format(
      'CREATE TRIGGER set_updated_at BEFORE UPDATE ON %s
         FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()', t);
  END LOOP;
END;
$$;

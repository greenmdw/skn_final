-- 0018_pc_parts_compat_columns.sql — 호환 검사 확장용 스펙 열 (data/parts_list_modify.xlsx 의 새 열)
--
-- 원본 엑셀에 추가된 열을 담는다. 값이 아직 비어 있는 열도 만들어 둔다 — 엔진은 NULL 을 "확인 못 함"으로
-- 처리하고, 값이 채워지는 만큼 검사가 켜진다. 가격·판매처·구매 URL 관련 새 열은 여기서 다루지 않는다.
--
-- *_source_url: 그 행의 새 값들을 확인한 출처(제조사 공식 페이지 우선). 값이 NULL 이면 출처도 NULL.
-- 멱등(ADD COLUMN IF NOT EXISTS)이라 다시 실행해도 안전하다.

ALTER TABLE catalog.cpu_spec
  ADD COLUMN IF NOT EXISTS max_power_w                 integer,   -- 최대 패키지 전력(Intel MTP/PL2, AMD PPT)
  ADD COLUMN IF NOT EXISTS family                      text,      -- 계열 정규 표기: 'Ryzen 7000', 'Core 14th', 'Core Ultra 200S' …
  ADD COLUMN IF NOT EXISTS power_family_source_url     text,
  ADD COLUMN IF NOT EXISTS perf_score                  numeric,   -- 벤치마크 점수(기준은 perf_score_source_url 참고)
  ADD COLUMN IF NOT EXISTS perf_score_source_url       text;

ALTER TABLE catalog.mainboard_spec
  ADD COLUMN IF NOT EXISTS dimm_slots                  integer,
  ADD COLUMN IF NOT EXISTS max_memory_gb               integer,
  ADD COLUMN IF NOT EXISTS max_memory_speed_mts        integer,   -- 제조사가 명시한 최대(오버클록 포함) 속도
  ADD COLUMN IF NOT EXISTS m2_slots                    integer,
  ADD COLUMN IF NOT EXISTS m2_pcie_gen                 text,      -- 슬롯별 세대, 세미콜론 구분: '5;4;4'
  ADD COLUMN IF NOT EXISTS sata_ports                  integer,
  ADD COLUMN IF NOT EXISTS min_bios                    text,      -- CPU 계열별 최소 BIOS: 'Ryzen 9000=2801;Ryzen 7000=1001'
  ADD COLUMN IF NOT EXISTS expansion_source_url        text;

ALTER TABLE catalog.ram_spec
  ADD COLUMN IF NOT EXISTS height_mm                   numeric,   -- 방열판 포함 높이
  ADD COLUMN IF NOT EXISTS height_source_url           text;

ALTER TABLE catalog.gpu_spec
  ADD COLUMN IF NOT EXISTS dimension_source_url        text,
  ADD COLUMN IF NOT EXISTS dimension_gap_reason        text,      -- 길이·높이를 못 채운 사유
  ADD COLUMN IF NOT EXISTS perf_score                  numeric,
  ADD COLUMN IF NOT EXISTS perf_score_source_url       text;

-- psu_spec.length_mm 은 0015 에서 이미 만들어져 있다(원본에 열이 없어 비어 있었다).
ALTER TABLE catalog.psu_spec
  ADD COLUMN IF NOT EXISTS pcie_8pin_count             integer,   -- PCIe 6+2핀 커넥터 총개수(케이블 수가 아님)
  ADD COLUMN IF NOT EXISTS connector_12v2x6_count      integer,
  ADD COLUMN IF NOT EXISTS dimension_source_url        text;

ALTER TABLE catalog.case_spec
  ADD COLUMN IF NOT EXISTS max_psu_length_mm           integer,
  ADD COLUMN IF NOT EXISTS expansion_slots             integer,
  ADD COLUMN IF NOT EXISTS radiator_front_mm           text,      -- 장착 가능 크기, 세미콜론 구분: '120;140;240;280'
  ADD COLUMN IF NOT EXISTS radiator_top_mm             text,
  ADD COLUMN IF NOT EXISTS radiator_rear_mm            text,
  ADD COLUMN IF NOT EXISTS color                       text,
  ADD COLUMN IF NOT EXISTS expansion_source_url        text;

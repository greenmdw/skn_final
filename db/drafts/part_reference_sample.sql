-- part_reference_sample.sql — 초안 검증용 예시 행 (실제 적재 대상 아님)
--
-- ⚠ 형식을 보여 주고 스키마·뷰가 동작하는지 확인하려는 예시다. 값은 제조사 공개 사양을 기억에서 옮긴 것이라
--   전부 spec_confidence='estimated' 로 두었다 — 실제 적재 전에 source_url 의 원문으로 한 행씩 검증해야 한다.
--   (GPU 길이는 제조사 카드마다 달라 대표 범위만 적었다. 이 역시 검증 전 값이다.)

BEGIN;

CREATE TEMP TABLE _ref_sample (
  ptype text, brand text, model text, name text, generation text, year int,
  socket text, mem text, tdp int, igpu text, power int, rec_psu int, len_min int, len_max int,
  source_url text, aliases text[]
) ON COMMIT DROP;

INSERT INTO _ref_sample VALUES
 ('cpu','Intel','Core i5-8400','Intel Core i5-8400','Intel 8th',2017,'LGA1151','DDR4',65,'O',NULL,NULL,NULL,NULL,
    'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', ARRAY['i5 8400','인텔 i5-8400']),
 ('cpu','Intel','Core i7-9700K','Intel Core i7-9700K','Intel 9th',2018,'LGA1151','DDR4',95,'O',NULL,NULL,NULL,NULL,
    'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', ARRAY['i7 9700K']),
 ('cpu','Intel','Core i5-10400F','Intel Core i5-10400F','Intel 10th',2020,'LGA1200','DDR4',65,'X',NULL,NULL,NULL,NULL,
    'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', ARRAY['i5 10400F']),
 ('cpu','AMD','Ryzen 5 3600','AMD Ryzen 5 3600','Ryzen 3000',2019,'AM4','DDR4',65,'X',NULL,NULL,NULL,NULL,
    'https://www.amd.com (EXAMPLE — 원문 확인 필요)', ARRAY['라이젠 5 3600','R5 3600']),
 ('cpu','AMD','Ryzen 5 5600','AMD Ryzen 5 5600','Ryzen 5000',2022,'AM4','DDR4',65,'X',NULL,NULL,NULL,NULL,
    'https://www.amd.com (EXAMPLE — 원문 확인 필요)', ARRAY['라이젠 5 5600','R5 5600']),
 ('gpu','NVIDIA','GeForce GTX 1060 6GB','NVIDIA GeForce GTX 1060 6GB','GeForce 10',2016,NULL,'GDDR5',NULL,NULL,120,400,190,290,
    'https://www.nvidia.com (EXAMPLE — 원문 확인 필요)', ARRAY['GTX1060','GTX 1060','지포스 GTX 1060']),
 ('gpu','NVIDIA','GeForce GTX 1650','NVIDIA GeForce GTX 1650','GeForce 16',2019,NULL,'GDDR5',NULL,NULL,75,300,150,230,
    'https://www.nvidia.com (EXAMPLE — 원문 확인 필요)', ARRAY['GTX1650','GTX 1650']),
 ('gpu','NVIDIA','GeForce RTX 2060','NVIDIA GeForce RTX 2060','GeForce 20',2019,NULL,'GDDR6',NULL,NULL,160,500,190,300,
    'https://www.nvidia.com (EXAMPLE — 원문 확인 필요)', ARRAY['RTX2060','RTX 2060']),
 ('gpu','AMD','Radeon RX 580','AMD Radeon RX 580','Radeon RX 500',2017,NULL,'GDDR5',NULL,NULL,185,500,200,290,
    'https://www.amd.com (EXAMPLE — 원문 확인 필요)', ARRAY['RX580','RX 580','라데온 RX 580']),
 ('gpu','AMD','Radeon RX 5700 XT','AMD Radeon RX 5700 XT','Radeon RX 5000',2019,NULL,'GDDR6',NULL,NULL,225,600,230,320,
    'https://www.amd.com (EXAMPLE — 원문 확인 필요)', ARRAY['RX5700XT','RX 5700 XT']);

INSERT INTO catalog.product (name, brand, model, product_type, status)
SELECT name, brand, model, ptype, 'discontinued' FROM _ref_sample;

INSERT INTO catalog.cpu_spec (product_id, socket, tdp_w, memory_type, integrated_graphics, spec_url, sale_status, status_checked_at, note)
SELECT p.id, s.socket, s.tdp, s.mem, s.igpu, s.source_url, '단종', CURRENT_DATE, '참조 전용(예시)'
FROM _ref_sample s JOIN catalog.product p ON p.brand = s.brand AND p.model = s.model AND p.product_type = s.ptype
WHERE s.ptype = 'cpu';

INSERT INTO catalog.gpu_spec (product_id, memory_type, power_w, recommended_psu_w, length_mm, spec_basis, spec_url, sale_status, status_checked_at, note)
SELECT p.id, s.mem, s.power, s.rec_psu, s.len_max,
       format('제조사 카드별 길이 상이(%s~%smm), 최대값 기재', s.len_min, s.len_max), s.source_url, '단종', CURRENT_DATE, '참조 전용(예시)'
FROM _ref_sample s JOIN catalog.product p ON p.brand = s.brand AND p.model = s.model AND p.product_type = s.ptype
WHERE s.ptype = 'gpu';

INSERT INTO catalog.part_reference (product_id, generation, release_year, spec_confidence, source_url, verified_at, verified_by)
SELECT p.id, s.generation, s.year, 'estimated', s.source_url, CURRENT_DATE, 'DRAFT-EXAMPLE'
FROM _ref_sample s JOIN catalog.product p ON p.brand = s.brand AND p.model = s.model AND p.product_type = s.ptype;

INSERT INTO catalog.part_alias (product_id, alias)
SELECT p.id, a
FROM _ref_sample s JOIN catalog.product p ON p.brand = s.brand AND p.model = s.model AND p.product_type = s.ptype
CROSS JOIN LATERAL unnest(s.aliases) AS a
ON CONFLICT (product_id, alias_norm) DO NOTHING;   -- 공백·하이픈만 다른 별칭('GTX1060'/'GTX 1060')은 같은 키라 하나로 합쳐진다

INSERT INTO catalog.chipset_reference (chipset, vendor, socket, memory_types, release_year, source_url, note) VALUES
 ('B450','AMD','AM4','{DDR4}',2018,'https://www.amd.com (EXAMPLE — 원문 확인 필요)', NULL),
 ('B550','AMD','AM4','{DDR4}',2020,'https://www.amd.com (EXAMPLE — 원문 확인 필요)', NULL),
 ('B650','AMD','AM5','{DDR5}',2022,'https://www.amd.com (EXAMPLE — 원문 확인 필요)', NULL),
 ('H310','Intel','LGA1151','{DDR4}',2018,'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', '8·9세대 전용(6·7세대 보드와 호환 안 됨)'),
 ('B460','Intel','LGA1200','{DDR4}',2020,'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', NULL),
 ('B760','Intel','LGA1700','{DDR4,DDR5}',2023,'https://ark.intel.com (EXAMPLE — 원문 확인 필요)', '보드마다 DDR4 또는 DDR5 — 소켓만 확정');

COMMIT;

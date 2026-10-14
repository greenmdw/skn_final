--
-- 0016_peripheral_spec_columns.sql
--
-- 주변기기 추천이 쓰는 두 스펙을 DB 에 둔다 (개발요청 B-8, B-9).
--  · B-9 GPU 출력 단자: 모니터↔PC 단자 검사(config/peripherals.yaml verify.gpu_keys)가 GPU 쪽 값을 읽는다.
--    값이 없으면 그 검사는 항상 "확인 불가"였다. 포트 개수는 조사하지 않았으므로 컬럼도 만들지 않는다.
--  · B-8 키보드 키압: 가벼운 키압(min <= 45g)·묵직한 키압(max >= 50g) 선호 판정에 쓴다. 값이 없는 상품은 NULL(모름).
--

ALTER TABLE catalog.gpu_spec
    ADD COLUMN hdmi_version text,
    ADD COLUMN dp_version text,
    ADD COLUMN usb_c_video_out boolean;

ALTER TABLE catalog.keyboard_spec
    ADD COLUMN key_force_min_g numeric(10,2),
    ADD COLUMN key_force_max_g numeric(10,2),
    ADD CONSTRAINT keyboard_spec_key_force_check CHECK (
        (key_force_min_g IS NULL OR key_force_min_g > 0)
        AND (key_force_max_g IS NULL OR key_force_max_g > 0)
        AND (key_force_min_g IS NULL OR key_force_max_g IS NULL OR key_force_min_g <= key_force_max_g));

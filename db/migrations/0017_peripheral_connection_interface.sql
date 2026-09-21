-- CSV의 연결 방식(유선/무선 분류)과 연결 인터페이스(USB·Bluetooth 등)를
-- 구분자 문자열이 아닌 배열로 분리 보존한다.
ALTER TABLE catalog.mouse_spec
  ALTER COLUMN connectivity TYPE text[] USING string_to_array(connectivity, '|');

ALTER TABLE catalog.speaker_spec
  ALTER COLUMN connectivity TYPE text[] USING string_to_array(connectivity, '|');

ALTER TABLE catalog.keyboard_spec
  ALTER COLUMN connectivity TYPE text[] USING string_to_array(connectivity, '|');

ALTER TABLE catalog.mouse_spec
  ADD COLUMN connectivity_interface text[];

ALTER TABLE catalog.speaker_spec
  ADD COLUMN connectivity_interface text[];

ALTER TABLE catalog.keyboard_spec
  ADD COLUMN connectivity_interface text[];

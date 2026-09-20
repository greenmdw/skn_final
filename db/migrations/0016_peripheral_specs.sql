-- 4종 부속기기 원본 스펙. 공통 식별자는 catalog.product, 옵션은 product_variant에 둔다.
-- 상품 URL은 규격/제조사 페이지일 수 있으므로 구매 offer로 간주하지 않는다.

CREATE TABLE catalog.mouse_spec (
  product_id         uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  model_number       text,
  category_label     text,
  form_factor        text,
  sensor             text,
  dpi_range          text,
  polling_rate       text,
  button_count       text,
  switch_click       text,
  connectivity       text,
  battery_power      text,
  color_options      text,
  software_url       text,
  weight_g           numeric(10,2),
  size_mm            text,
  product_url        text,
  manual_reference   text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.monitor_spec (
  product_id         uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  model_code         text,
  screen_size_inch   numeric(5,2),
  resolution         text,
  max_refresh_hz     numeric(7,2),
  panel              text,
  response_ms_gtg    numeric(7,2),
  brightness_nit     integer,
  curvature          text,
  hdmi_version       text,
  hdmi_ports         integer,
  dp_version         text,
  dp_ports           integer,
  dp_connector       text,
  usb_c_video_input  text,
  usb_c_power_w      integer,
  vesa_mount_mm      text,
  port_limits        text,
  note               text,
  weight_g           numeric(10,2),
  size_mm            text,
  product_url        text,
  manual_reference   text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (hdmi_ports IS NULL OR hdmi_ports >= 0),
  CHECK (dp_ports IS NULL OR dp_ports >= 0)
);

CREATE TABLE catalog.speaker_spec (
  product_id         uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  speaker_form       text,
  connectivity       text,
  channels           text,
  output_power       text,
  impedance          text,
  signal_noise_ratio text,
  sensitivity        text,
  power_source       text,
  enclosure          text,
  note               text,
  weight_g           numeric(10,2),
  size_mm            text,
  product_url        text,
  manual_reference   text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.keyboard_spec (
  product_id         uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  switch_kind        text,
  switch_method      text,
  rapid_trigger      boolean,
  connectivity       text,
  weight_g           numeric(10,2),
  size_mm            text,
  product_url        text,
  manual_reference   text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- 원본 CSV에는 가격 관측일과 판매처가 없다. 209개 숫자는 보존하되
-- catalog.offer_observation(구매 가능한 유효 가격)으로 승격하지 않는다.
CREATE TABLE catalog.peripheral_price_snapshot (
  product_id         uuid PRIMARY KEY REFERENCES catalog.product(id) ON DELETE CASCADE,
  price_krw          integer,
  price_observed_at  timestamptz,
  source_file        text NOT NULL,
  source_row         integer NOT NULL CHECK (source_row >= 2),
  source_sha256      char(64) NOT NULL,
  imported_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (price_krw IS NULL OR price_krw > 0)
);

"""주변기기 candidate specs/provenance 조립 + DB 없는 mock CSV 로더 — 계획 §3.3 E9.

DB 로더(src/repo/catalog_repo.py:load_peripheral_candidates)와 여기 mock CSV 로더
(load_peripheral_candidates_from_csv)가 "행 dict -> Candidate.specs/provenance" 변환을
build_peripheral_specs/build_peripheral_provenance 로 공유한다 — 그래서 두 경로가 같은
상품에 대해 같은 결과를 낸다(계획 §3.3 E9 테스트 요구사항).

행 dict 의 키는 DB 컬럼명(config/peripherals.yaml 의 kinds.<kind>.columns 딕셔너리 키)과
같다. 값 타입은 DB 로더는 psycopg가 반환한 실제 타입(Decimal/int/bool/list[str]/str/None),
mock CSV 로더는 아래 _convert_like_seed()가 db/seed_peripherals.py 의 변환 규칙과 같은
타입(Decimal/int/bool/list[str]/str/None)을 만든다 — 그래서 _cast_column() 이후에는 두
경로가 구분되지 않는다.
"""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.dto import Candidate
from src.engine import peripheral_parse as pp
from src.engine.peripheral_rules import kind_def, load_peripheral_rules, peripheral_kinds, resolution_classes

# DB 스키마(db/migrations/0000_schema.sql)에서 각 spec 테이블 컬럼의 실제 타입 — SELECT 할
# 컬럼 "이름 목록" 자체는 config/peripherals.yaml 의 kinds.<kind>.columns 에서 만들지만
# (하드코딩 금지 대상), Decimal/정수/불리언/배열 캐스팅에는 타입 정보가 필요해서 작은 표로
# 둔다. 여기 없는 컬럼은 전부 text 로 취급한다(PC 로더 _specs_from_row 와 같은 결의 결정).
_NUMERIC_COLUMNS: dict[str, set[str]] = {
    "monitor": {"screen_size_inch", "max_refresh_hz", "response_ms_gtg", "weight_g"},
    "keyboard": {"weight_g"},
    "mouse": {"weight_g"},
    "speaker": {"weight_g"},
}
_INTEGER_COLUMNS: dict[str, set[str]] = {
    "monitor": {"brightness_nit", "hdmi_ports", "dp_ports", "usb_c_power_w"},
    "keyboard": set(),
    "mouse": set(),
    "speaker": set(),
}
_BOOLEAN_COLUMNS: dict[str, set[str]] = {
    "monitor": set(),
    "keyboard": {"rapid_trigger"},
    "mouse": set(),
    "speaker": set(),
}
_ARRAY_COLUMNS: dict[str, set[str]] = {
    "monitor": set(),
    "keyboard": {"connectivity", "connectivity_interface"},
    "mouse": {"connectivity", "connectivity_interface"},
    "speaker": {"connectivity", "connectivity_interface"},
}

# 스펙이 아니라 출처 메타데이터인 컬럼 — Candidate.provenance 로만 간다(specs 에 섞으면
# [3-B] data_gap 감점이 메타데이터를 스펙 결손으로 셀 수 있다, config/peripherals.yaml 주석과 동일 원칙).
# image_url 은 여기 없다 — kind별 spec 테이블 컬럼이 아니라 catalog.product.image_url(모든
# 종류 공통)이라 아래 build_peripheral_provenance 에서 따로 다룬다(db/seed_peripherals.py 가
# image_url 을 _COMMON/_SPECS 밖에서 별도로 UPDATE catalog.product 하는 것과 같은 이유 —
# 종류마다 다시 나열하지 않는다).
_META_COLUMNS: dict[str, tuple[str, ...]] = {
    "monitor": ("product_url", "manual_reference"),
    "keyboard": ("product_url", "manual_reference"),
    "mouse": ("product_url", "manual_reference", "software_url"),
    "speaker": ("product_url", "manual_reference"),
}

# 계획 §3.3 — 참고가(peripheral_price_snapshot)는 판매처·관측일을 모른다. E13 payload가
# price_note 를 그대로 노출한다(R-3 전까지 고정 문구).
PRICE_NOTE = "판매처·관측일 미확인 참고가"


def _cast_column(kind: str, db_col: str, value: Any) -> Any:
    """DB 로더(psycopg 타입)와 mock CSV 로더(seed-호환 변환 결과) 양쪽에서 온 값을
    같은 파이썬 타입으로 정리한다. None 은 그대로 None(=값 없음, 호출부가 키를 안 넣는다)."""
    if value is None:
        return None
    if db_col in _NUMERIC_COLUMNS.get(kind, ()):
        return float(value)
    if db_col in _INTEGER_COLUMNS.get(kind, ()):
        return int(value)
    if db_col in _BOOLEAN_COLUMNS.get(kind, ()):
        return bool(value)
    if db_col in _ARRAY_COLUMNS.get(kind, ()):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items or None
    text = str(value).strip()
    return text or None


def build_peripheral_specs(kind: str, row: dict, rules: dict | None = None) -> dict:
    """행 dict -> Candidate.specs = columns 매핑 결과 + peripheral_parse 파서 결과.

    값이 없는 컬럼과 파싱 실패 키는 아예 넣지 않는다(PC 로더 _specs_from_row 관례와 동일 —
    "없는 정보"와 "실패해서 0/False 로 채운 정보"를 구분한다).
    """
    rules = rules or load_peripheral_rules()
    kdef = kind_def(kind, rules)
    specs: dict[str, Any] = {}
    for db_col, engine_key in kdef["columns"].items():
        value = _cast_column(kind, db_col, row.get(db_col))
        if value is not None:
            specs[engine_key] = value

    if kind == "monitor":
        resolution = pp.parse_resolution(specs.get("resolution_raw"), resolution_classes(rules))
        if resolution is not None:
            specs["resolution_w"] = resolution["w"]
            specs["resolution_h"] = resolution["h"]
            specs["resolution_class"] = resolution["class"]
    elif kind == "mouse":
        dpi_max = pp.parse_dpi_max(specs.get("dpi_range_raw"))
        if dpi_max is not None:
            specs["dpi_max"] = dpi_max
        polling_max = pp.parse_polling_hz_max(specs.get("polling_rate_raw"))
        if polling_max is not None:
            specs["polling_hz_max"] = polling_max
    elif kind == "keyboard":
        switch = pp.parse_switch(specs.get("switch_kind_raw"), specs.get("switch_method_raw"))
        for switch_key in ("clicky", "magnetic", "low_profile"):
            if switch[switch_key] is not None:
                specs[f"switch_{switch_key}"] = switch[switch_key]
    elif kind == "speaker":
        channels = pp.parse_channels(specs.get("channels_raw"))
        if channels is not None:
            specs["channels"] = channels
        output_w = pp.parse_output_w(specs.get("output_power_raw"))
        if output_w is not None:
            specs["output_w"] = output_w

    if kind in ("keyboard", "mouse", "speaker"):
        connectivity = pp.parse_connectivity(specs.get("connectivity"), specs.get("connectivity_interface"))
        for conn_key in ("wired", "wireless", "bluetooth"):
            if connectivity[conn_key] is not None:
                specs[f"connectivity_{conn_key}"] = connectivity[conn_key]

    return specs


def build_peripheral_provenance(kind: str, row: dict) -> dict:
    """행 dict -> Candidate.provenance. product_url/manual_reference/(mouse만) software_url/
    image_url 중 있는 것만 담고, price_note 는 항상 고정 문구로 붙인다(E13 payload 가 그대로
    쓴다). image_url 은 row["image_url"] 하나로 고정한다 — DB 로더는 catalog.product.image_url
    을(_build_peripheral_query 가 SELECT), mock CSV 로더는 "이미지 URL" 열을 같은 키로 옮겨서
    두 경로가 구분 없이 여기로 들어온다(E13 감사 지적 — image_url 컬럼은 실재하고 DB에도
    채워져 있다. specs 로는 안 보낸다: 상품별 값이지 스펙이 아니다)."""
    provenance: dict[str, Any] = {}
    for meta_col in _META_COLUMNS.get(kind, ()):
        value = row.get(meta_col)
        if value:
            provenance[meta_col] = value
    image_url = row.get("image_url")
    if image_url:
        provenance["image_url"] = image_url
    provenance["price_note"] = PRICE_NOTE
    return provenance


# ── mock CSV 로더(DB 없는 테스트용) ──────────────────────────────────────────
# 아래 헤더 표는 db/seed_peripherals.py 의 _COMMON/_SPECS 매핑을 그대로 옮긴 것이다(그 파일은
# db/ 최상위 디렉터리에 있고 src/db 와 이름이 겹쳐 PYTHONPATH=. 환경에서 "import db"가 항상
# src/db 로 해석되므로(실측 확인) 직접 import 할 수 없다 — 그리고 계획 지시상 그 파일 자체를
# 수정할 수도 없다). tests/test_peripheral_catalog.py 가 db/seed_peripherals.py 를 파일 경로로
# 동적 로드해 이 표가 표류하지 않았는지 대조한다.
_EMPTY_TOKENS = {"", "-", "미표기", "해당없음"}
_COMMON_HEADERS: dict[str, tuple[str, str]] = {
    "무게(g)": ("weight_g", "decimal"),
    "크기(mm)": ("size_mm", "text"),
    "상품 URL": ("product_url", "url"),
    "설명서 URL": ("manual_reference", "text"),
}
_KIND_HEADERS: dict[str, dict[str, tuple[str, str]]] = {
    "monitor": {
        "화면크기(inch)": ("screen_size_inch", "decimal"),
        "해상도": ("resolution", "text"),
        "최대주사율(Hz)": ("max_refresh_hz", "decimal"),
        "패널": ("panel", "text"),
        "응답속도(ms, GtG)": ("response_ms_gtg", "decimal"),
        "밝기(nit)": ("brightness_nit", "integer"),
        "곡률": ("curvature", "text"),
        "HDMI 버전": ("hdmi_version", "text"),
        "HDMI 개수": ("hdmi_ports", "port_count"),
        "DP 버전": ("dp_version", "text"),
        "DP 개수": ("dp_ports", "port_count"),
        "DP 커넥터": ("dp_connector", "text"),
        "USB-C 영상입력": ("usb_c_video_input", "text"),
        "USB-C 전력공급(W)": ("usb_c_power_w", "integer"),
        "VESA 규격(mm)": ("vesa_mount_mm", "text"),
        "포트별 제한": ("port_limits", "text"),
        "참고사항": ("note", "text"),
    },
    "mouse": {
        "폼팩터": ("form_factor", "text"),
        "센서": ("sensor", "text"),
        "DPI 범위": ("dpi_range", "text"),
        "폴링레이트": ("polling_rate", "text"),
        "버튼 수": ("button_count", "text"),
        "스위치/클릭 방식": ("switch_click", "text"),
        "연결 방식": ("connectivity", "connection_method"),
        "연결 인터페이스": ("connectivity_interface", "pipe_list"),
        "배터리/전원": ("battery_power", "text"),
        "색상": ("color_options", "text"),
        "드라이버/소프트웨어 URL": ("software_url", "url"),
    },
    "keyboard": {
        "축 종류": ("switch_kind", "text"),
        "스위치 방식": ("switch_method", "text"),
        "래피드 트리거": ("rapid_trigger", "rapid_trigger"),
        "연결 방식": ("connectivity", "connection_method"),
        "연결 인터페이스": ("connectivity_interface", "pipe_list"),
    },
    "speaker": {
        "스피커 형태": ("speaker_form", "text"),
        "연결 방식": ("connectivity", "connection_method"),
        "연결 인터페이스": ("connectivity_interface", "pipe_list"),
        "채널": ("channels", "text"),
        "출력(W)": ("output_power", "text"),
        "임피던스": ("impedance", "text"),
        "신호대잡음비(SNR)": ("signal_noise_ratio", "text"),
        "감도": ("sensitivity", "text"),
        "전원방식": ("power_source", "text"),
        "인클로저/구성": ("enclosure", "text"),
        "기타 상세/비고": ("note", "text"),
    },
}

_BRAND_HEADER = "제조사"
_MODEL_HEADER = "모델명"
_PRICE_HEADER = "가격(원)"
# db/seed_peripherals.py 처럼 "이미지 URL"도 _COMMON 밖에서 따로 읽는다(그 파일의
# load_rows()가 row["이미지 URL"]을 PeripheralRow.image_url로 직접 뽑는 것과 같은 자리) —
# _COMMON_HEADERS 에 넣으면 위 미러 드리프트 테스트(seed._COMMON 과 1:1 비교)가 깨진다.
_IMAGE_URL_HEADER = "이미지 URL"


def _convert_like_seed(value: str | None, kind: str) -> Any:
    """db/seed_peripherals.py:_convert() 와 같은 규칙(위 안내 참조 — 그 파일은 수정하지
    않고 표만 미러로 유지한다). 픽스처는 실제 CSV에서 그대로 복사한 값이라 형식 검증은
    하지 않는다(seed 원본은 잘못된 원본 데이터를 막으려는 용도라 여기선 불필요)."""
    raw = (value or "").strip()
    if kind == "port_count" and raw == "없음":
        return 0
    if raw in _EMPTY_TOKENS:
        return None
    if kind in ("text", "url"):
        return raw
    if kind == "decimal":
        return Decimal(raw)
    if kind in ("integer", "port_count"):
        return int(raw)
    if kind == "rapid_trigger":
        return raw == "O"
    if kind == "connection_method":
        return raw.split("|")
    if kind == "pipe_list":
        return [v.strip() for v in raw.split("|")]
    raise ValueError(f"지원하지 않는 변환: {kind}")


def _row_from_csv(kind: str, csv_row: dict[str, str]) -> dict[str, Any]:
    """CSV DictReader 행(한글 헤더) -> DB 컬럼명 keyed dict. build_peripheral_specs/
    build_peripheral_provenance 가 DB 로더 행과 구분 없이 읽을 수 있는 모양으로 만든다."""
    fields = {**_COMMON_HEADERS, **_KIND_HEADERS[kind]}
    row: dict[str, Any] = {
        "brand": (csv_row.get(_BRAND_HEADER) or "").strip(),
        "model": (csv_row.get(_MODEL_HEADER) or "").strip(),
        "price": _convert_like_seed(csv_row.get(_PRICE_HEADER), "integer"),
        "image_url": _convert_like_seed(csv_row.get(_IMAGE_URL_HEADER), "url"),
    }
    for header, (column, tag) in fields.items():
        row[column] = _convert_like_seed(csv_row.get(header), tag)
    return row


def load_peripheral_candidates_from_csv(
    directory: Path | str, rules: dict | None = None, filename_template: str = "{kind}.csv",
) -> dict[str, list[Candidate]]:
    """tests/fixtures/peripherals/{kind}.csv 를 읽는 DB 없는 대체 로더(E9).

    build_peripheral_specs/build_peripheral_provenance 를 DB 로더(catalog_repo.
    load_peripheral_candidates)와 공유해서 같은 원본 행에 같은 specs 를 낸다. 가격이 빈
    행은 후보에서 뺀다(DB 로더의 "가격 NULL이면 후보에서 뺀다"와 같은 원칙).

    `filename_template`은 `{kind}`를 종류 이름으로 치환해 파일명을 만든다. 기본값은
    테스트 픽스처(`tests/fixtures/peripherals/{kind}.csv`) 이름 규칙이다. 실제 데이터
    디렉터리(`data/peripherals/`)는 `db/seed_peripherals.py`와 같은 `{kind}_processed.csv`
    이름을 쓰므로, 호출부(`src/pipeline.py`)가 `filename_template="{kind}_processed.csv"`를
    넘긴다(계획 §3.3 E11 — 파일명이 다르다고 새 로더를 만들지 않고 이 함수를 그대로 쓴다).
    디렉터리 자체가 없거나 파일이 하나도 없으면 예외 없이 빈 dict를 낸다 — data/peripherals가
    없는 환경(수집 파일 미배포)에서도 데모가 죽지 않아야 한다(AGENTS.md "필수 시드 입력").
    """
    from src.repo.catalog_repo import pc_catalog_key  # 순환 import 회피용 지연 import

    rules = rules or load_peripheral_rules()
    directory = Path(directory)
    out: dict[str, list[Candidate]] = {}
    for kind in peripheral_kinds(rules):
        path = directory / filename_template.format(kind=kind)
        if not path.is_file():
            continue
        product_type = kind_def(kind, rules)["product_type"]
        with path.open(encoding="utf-8-sig", newline="") as f:
            for csv_row in csv.DictReader(f):
                row = _row_from_csv(kind, csv_row)
                if row["price"] is None or not row["brand"] or not row["model"]:
                    continue
                out.setdefault(kind, []).append(Candidate(
                    product_key=pc_catalog_key(product_type, row["brand"], row["model"]),
                    slot=kind,
                    name=f"{row['brand']} {row['model']}",
                    brand=row["brand"],
                    variant_id=f"mock-{kind}-{row['brand']}-{row['model']}".lower().replace(" ", "-"),
                    offer_observation_id=None,
                    price=int(row["price"]),
                    price_source="reference_snapshot",
                    price_observed_at=None,
                    specs=build_peripheral_specs(kind, row, rules),
                    provenance=build_peripheral_provenance(kind, row),
                ))
    return out

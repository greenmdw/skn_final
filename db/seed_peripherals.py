#!/usr/bin/env python3
"""전달받은 부속기기 CSV 4종을 catalog.product와 전용 스펙 테이블에 적재한다.

가격은 원본에 판매처·관측일이 없어 peripheral_price_snapshot에만 보존한다.
상품/규격 URL을 구매 offer로 만들거나 미검증 가격을 유효 관측가로 표시하지 않는다.

    python db/seed_peripherals.py --dry-run
    DATABASE_URL=... python db/seed_peripherals.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "peripherals"
_EMPTY = {"", "-", "미표기", "해당없음"}
_COMMON = {
    "무게(g)": ("weight_g", "decimal"),
    "크기(mm)": ("size_mm", "text"),
    "상품 URL": ("product_url", "url"),
    "설명서 URL": ("manual_reference", "text"),
}
_CONNECTION_METHODS = {"유선", "무선", "유선|무선"}
_SPECS: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    "mouse": ("catalog.mouse_spec", {
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
    }),
    "monitor": ("catalog.monitor_spec", {
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
    }),
    "speaker": ("catalog.speaker_spec", {
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
    }),
    "keyboard": ("catalog.keyboard_spec", {
        "축 종류": ("switch_kind", "text"),
        "스위치 방식": ("switch_method", "text"),
        "래피드 트리거": ("rapid_trigger", "rapid_trigger"),
        "연결 방식": ("connectivity", "connection_method"),
        "연결 인터페이스": ("connectivity_interface", "pipe_list"),
    }),
}


@dataclass(frozen=True)
class PeripheralRow:
    product_type: str
    brand: str
    model: str
    image_url: str | None
    spec_table: str
    specs: dict
    price_krw: int | None
    source_file: str
    source_row: int
    source_sha256: str


def _convert(value: str | None, kind: str):
    raw = (value or "").strip()
    if kind == "port_count" and raw == "없음":
        return 0
    if raw in _EMPTY:
        return None
    if kind == "text":
        return raw
    if kind == "url":
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"URL 형식 오류: {raw}")
        return raw
    if kind == "decimal":
        if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
            raise ValueError(f"숫자 형식 오류: {raw}")
        return Decimal(raw)
    if kind in {"integer", "port_count"}:
        if not re.fullmatch(r"\d+", raw):
            raise ValueError(f"정수 형식 오류: {raw}")
        return int(raw)
    if kind == "rapid_trigger":
        if raw not in {"O", "X"}:
            raise ValueError(f"래피드 트리거 값 오류: {raw}")
        return raw == "O"
    if kind == "connection_method":
        if raw not in _CONNECTION_METHODS:
            raise ValueError(f"연결 방식 값 오류: {raw} (허용: 유선, 무선, 유선|무선)")
        return raw.split("|")
    if kind == "pipe_list":
        values = raw.split("|")
        if not all(value.strip() for value in values):
            raise ValueError(f"'|'로 구분한 값 오류: {raw}")
        return [value.strip() for value in values]
    raise ValueError(f"지원하지 않는 변환: {kind}")


def load_rows(input_dir: Path = DATA_DIR) -> list[PeripheralRow]:
    """DB 연결 전에 4개 파일 전체를 검증한다. 일부만 적재되는 일을 막는다."""
    result: list[PeripheralRow] = []
    seen: set[tuple[str, str]] = set()
    for product_type, (table, fields) in _SPECS.items():
        path = input_dir / f"{product_type}_processed.csv"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            expected = {"제조사", "모델명", "가격(원)", "이미지 URL", *_COMMON, *fields}
            missing = expected - set(reader.fieldnames or ())
            if missing or len(reader.fieldnames or ()) != len(set(reader.fieldnames or ())):
                raise ValueError(f"{path.name}: 헤더 오류 (누락 {sorted(missing)})")
            count = 0
            for row_no, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(f"{path.name}:{row_no}: 열 수가 헤더보다 많음")
                brand, model = (row["제조사"] or "").strip(), (row["모델명"] or "").strip()
                if not brand or not model:
                    raise ValueError(f"{path.name}:{row_no}: 제조사/모델명 누락")
                identity = brand.casefold(), model.casefold()
                if identity in seen:
                    raise ValueError(f"{path.name}:{row_no}: 제조사/모델명 중복: {brand} {model}")
                seen.add(identity)
                try:
                    price = _convert(row["가격(원)"], "integer")
                    if price is not None and price <= 0:
                        raise ValueError("가격은 양수여야 함")
                    specs = {column: _convert(row[header], kind)
                             for header, (column, kind) in {**_COMMON, **fields}.items()}
                    image_url = _convert(row["이미지 URL"], "url")
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{row_no}: {exc}") from exc
                result.append(PeripheralRow(product_type, brand, model, image_url,
                                            table, specs, price, path.name, row_no, digest))
                count += 1
            if count == 0:
                raise ValueError(f"{path.name}: 상품 행 없음")
    return result


def _upsert_spec(conn, product_id, table: str, specs: dict) -> None:
    columns = ["product_id", *specs]
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{column}=EXCLUDED.{column}" for column in specs)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (product_id) DO UPDATE SET {assignments}, updated_at=now()",
        [product_id, *specs.values()],
    )


def seed(conn, rows: list[PeripheralRow]) -> dict[str, int]:
    repo = ProductRepo(conn)
    existing = repo._all("SELECT id, brand, model, product_type FROM catalog.product")
    by_identity: dict[tuple[str, str], dict] = {}
    for product in existing:
        identity = product["brand"].casefold(), product["model"].casefold()
        if identity in by_identity:
            raise ValueError(f"기존 카탈로그 제조사/모델명 중복: {identity}")
        by_identity[identity] = product
    for row in rows:
        previous = by_identity.get((row.brand.casefold(), row.model.casefold()))
        if previous and previous["product_type"] != row.product_type:
            raise ValueError(f"다른 상품 종류와 제조사/모델명 충돌: {row.brand} {row.model}")

    counts = {kind: 0 for kind in _SPECS}
    for row in rows:
        name = row.model if row.model.casefold().startswith(row.brand.casefold() + " ") else f"{row.brand} {row.model}"
        product_id = repo.upsert_product(name=name, brand=row.brand, model=row.model,
                                         product_type=row.product_type, attributes={})
        repo._exec("UPDATE catalog.product SET image_url=%s WHERE id=%s", (row.image_url, product_id))
        repo.upsert_variant(product_id, "default", attributes={})
        _upsert_spec(conn, product_id, row.spec_table, row.specs)
        conn.execute(
            """INSERT INTO catalog.peripheral_price_snapshot
               (product_id, price_krw, price_observed_at, source_file, source_row, source_sha256)
               VALUES (%s, %s, NULL, %s, %s, %s)
               ON CONFLICT (product_id) DO UPDATE SET
                 price_krw=EXCLUDED.price_krw, price_observed_at=NULL,
                 source_file=EXCLUDED.source_file, source_row=EXCLUDED.source_row,
                 source_sha256=EXCLUDED.source_sha256""",
            (product_id, row.price_krw, row.source_file, row.source_row, row.source_sha256),
        )
        counts[row.product_type] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--dry-run", action="store_true", help="파일 전체 검증만 하고 DB를 수정하지 않음")
    args = parser.parse_args()
    rows = load_rows(args.input_dir)
    priced = sum(row.price_krw is not None for row in rows)
    if args.dry_run:
        print(f"부속기기 CSV 검증: {len(rows)}개 상품, 가격 숫자 {priced}개, DB 변경 없음")
        return 0
    with get_conn() as conn:
        counts = seed(conn, rows)
    print(f"부속기기 DB 적재: {counts}, 가격 스냅샷 {priced}/{len(rows)}개 (관측일 미상·offer 미생성)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

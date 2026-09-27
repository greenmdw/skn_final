"""주변기기 후보 로더 + 텍스트 스펙 파서(E9) 테스트 — 추천엔진 구현계획 §3.3.

DB 통합 테스트(맨 아래, @pytest.mark.db) 를 빼고는 DB 가 필요 없다. mock CSV 로더는
tests/fixtures/peripherals/*.csv(실제 data/peripherals/*_processed.csv 에서 대표 행을
그대로 복사 — mouse.csv 마지막 행만 "가격 NULL 제외" 테스트용으로 가격을 지웠다)를 읽는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine import peripheral_catalog as pc
from src.engine import peripheral_parse as pp
from src.engine.peripheral_catalog import (
    PRICE_NOTE,
    build_peripheral_provenance,
    build_peripheral_specs,
    load_peripheral_candidates_from_csv,
)
from src.engine.peripheral_rules import load_peripheral_rules, resolution_classes
from src.repo.catalog_repo import pc_catalog_key

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_RES_CLASSES = {
    "FHD": [(1920, 1080)],
    "QHD": [(2560, 1440)],
    "QHD_WIDE": [(3440, 1440)],
    "UHD": [(3840, 2160)],
}


# ── parse_resolution ────────────────────────────────────────────────────
def test_parse_resolution_known_classes():
    assert pp.parse_resolution("2560x1440", _RES_CLASSES) == {"w": 2560, "h": 1440, "class": "QHD"}
    assert pp.parse_resolution("3440x1440", _RES_CLASSES) == {"w": 3440, "h": 1440, "class": "QHD_WIDE"}
    assert pp.parse_resolution("3840x2160", _RES_CLASSES) == {"w": 3840, "h": 2160, "class": "UHD"}
    assert pp.parse_resolution("1920x1080", _RES_CLASSES) == {"w": 1920, "h": 1080, "class": "FHD"}


def test_parse_resolution_unlisted_is_other_not_none():
    """계획 §3.3 E9: 목록에 없는 조합(5K 계열 등)은 파싱 실패(None)가 아니라 class="OTHER"."""
    assert pp.parse_resolution("5120x2880", _RES_CLASSES) == {"w": 5120, "h": 2880, "class": "OTHER"}
    assert pp.parse_resolution("6144x3456", _RES_CLASSES) == {"w": 6144, "h": 3456, "class": "OTHER"}


def test_parse_resolution_without_classes_table_is_other():
    assert pp.parse_resolution("2560x1440", {}) == {"w": 2560, "h": 1440, "class": "OTHER"}
    assert pp.parse_resolution("2560x1440") == {"w": 2560, "h": 1440, "class": "OTHER"}


@pytest.mark.parametrize("raw", [None, "", "   ", "해상도 없음", "2560×1440x60", "2560", "x1440"])
def test_parse_resolution_failure_is_none(raw):
    assert pp.parse_resolution(raw, _RES_CLASSES) is None


def test_parse_resolution_tolerates_spaces_around_x():
    assert pp.parse_resolution(" 1920 x 1080 ", _RES_CLASSES) == {"w": 1920, "h": 1080, "class": "FHD"}


# ── parse_dpi_max / parse_polling_hz_max ──────────────────────────────────
def test_parse_dpi_max_ignores_parenthetical_default():
    """"200–8,000 DPI (기본값 1,000 DPI)" 의 괄호 안 "기본값 1,000"을 최댓값으로 착각하지 않는다."""
    assert pp.parse_dpi_max("200–8,000 DPI (기본값 1,000 DPI)") == 8000.0


def test_parse_dpi_max_plain_max_phrase():
    assert pp.parse_dpi_max("최대 30,000") == 30000.0


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_dpi_max_blank_is_none(raw):
    assert pp.parse_dpi_max(raw) is None


def test_parse_polling_hz_max_tilde_range():
    assert pp.parse_polling_hz_max("125~2,000Hz") == 2000.0


def test_parse_polling_hz_max_paren_is_note_not_bonus():
    """"최대 1,000Hz (1ms)" -> 1000 (괄호는 단위 환산 메모일 뿐). 별매 액세서리로만 도달하는
    조건부 보너스("1,000Hz (HyperPolling 동글 사용 시 8,000Hz)")도 같은 규칙으로 괄호 밖 값만 쓴다."""
    assert pp.parse_polling_hz_max("최대 1,000Hz (1ms)") == 1000.0
    assert pp.parse_polling_hz_max("1,000Hz (HyperPolling 동글 사용 시 8,000Hz)") == 1000.0


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_polling_hz_max_blank_is_none(raw):
    assert pp.parse_polling_hz_max(raw) is None


# ── parse_switch ──────────────────────────────────────────────────────────
def test_parse_switch_magnetic_analog():
    assert pp.parse_switch("Logitech G Magnetic Analog Switch", "마그네틱 아날로그") == {
        "clicky": None, "magnetic": True, "low_profile": False,
    }


def test_parse_switch_low_profile_from_kind_text():
    """method 만으로는 로우프로파일 여부를 알 수 없어도 kind 텍스트에 "Low-profile"이 있으면 잡는다."""
    result = pp.parse_switch("Low-profile Magnetic Analog Switch", "마그네틱 아날로그")
    assert result == {"clicky": None, "magnetic": True, "low_profile": True}


def test_parse_switch_scissor_is_low_profile_non_magnetic():
    result = pp.parse_switch("", "Scissor / 팬터그래프")
    assert result == {"clicky": None, "magnetic": False, "low_profile": True}


def test_parse_switch_ambiguous_multi_type_kind_is_clicky_none():
    """"GL Linear / GL Tactile / GL Clicky" 처럼 여러 방식을 나열하면 실제 채택 방식을 모른다."""
    result = pp.parse_switch("GL Linear / GL Tactile / GL Clicky", "로우프로파일 기계식")
    assert result["clicky"] is None
    assert result["magnetic"] is False
    assert result["low_profile"] is True


def test_parse_switch_single_type_keyword_resolves_clicky():
    result = pp.parse_switch("CHERRY MX Ultra Low Profile Tactile", "초저상형 기계식")
    assert result == {"clicky": False, "magnetic": False, "low_profile": True}


def test_parse_switch_capacitive_non_magnetic_non_low_profile():
    result = pp.parse_switch("NIZ EC 35g", "정전용량 무접점")
    assert result == {"clicky": None, "magnetic": False, "low_profile": False}


def test_parse_switch_no_data_is_all_none():
    assert pp.parse_switch(None, None) == {"clicky": None, "magnetic": None, "low_profile": None}
    assert pp.parse_switch("", "") == {"clicky": None, "magnetic": None, "low_profile": None}


# ── parse_channels / parse_output_w ────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [("2", 2.0), ("2.1", 2.1)])
def test_parse_channels_numeric(raw, expected):
    assert pp.parse_channels(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "2채널", "2.1.1"])
def test_parse_channels_failure_is_none(raw):
    assert pp.parse_channels(raw) is None


def test_parse_output_w_simple():
    assert pp.parse_output_w("24W") == 24.0


def test_parse_output_w_ignores_channel_breakdown_in_parens():
    assert pp.parse_output_w("10W (5Wx2)") == 10.0
    assert pp.parse_output_w("150W (15Wx2+25Wx2+70W)") == 150.0


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_parse_output_w_blank_is_none(raw):
    assert pp.parse_output_w(raw) is None


# ── parse_connectivity ──────────────────────────────────────────────────
def test_parse_connectivity_wired_only():
    result = pp.parse_connectivity(["유선"], ["USB"])
    assert result == {"wired": True, "wireless": False, "bluetooth": False}


def test_parse_connectivity_wireless_with_bluetooth():
    result = pp.parse_connectivity(["무선"], ["USB 수신기", "Bluetooth"])
    assert result == {"wired": False, "wireless": True, "bluetooth": True}


def test_parse_connectivity_both():
    result = pp.parse_connectivity(["유선", "무선"], ["USB", "USB 수신기", "Bluetooth"])
    assert result == {"wired": True, "wireless": True, "bluetooth": True}


@pytest.mark.parametrize("connectivity", [None, []])
def test_parse_connectivity_missing_is_all_none(connectivity):
    assert pp.parse_connectivity(connectivity, ["USB"]) == {"wired": None, "wireless": None, "bluetooth": None}


def test_parse_connectivity_no_interface_list_is_bluetooth_none():
    result = pp.parse_connectivity(["유선"], None)
    assert result == {"wired": True, "wireless": False, "bluetooth": None}


# ── mock CSV 로더 ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mock_candidates():
    return load_peripheral_candidates_from_csv(_FIXTURES)


def test_mock_loader_counts_per_kind(mock_candidates):
    assert len(mock_candidates["monitor"]) == 6
    assert len(mock_candidates["keyboard"]) == 6
    assert len(mock_candidates["speaker"]) == 6
    # mouse.csv 는 6행이지만 마지막 행(ROG Harpe Mini Core)이 가격 NULL 이라 후보에서 빠진다.
    assert len(mock_candidates["mouse"]) == 5


def test_mock_loader_excludes_null_price_row(mock_candidates):
    keys = {c.product_key for c in mock_candidates["mouse"]}
    assert pc_catalog_key("mouse", "ASUS", "ROG Harpe Mini Core") not in keys


def test_mock_loader_price_source_is_reference_snapshot(mock_candidates):
    for cands in mock_candidates.values():
        for cand in cands:
            assert cand.price_source == "reference_snapshot"
            assert cand.price_observed_at is None
            assert cand.offer_observation_id is None
            assert cand.price > 0


def test_mock_loader_specs_have_no_url_or_meta_keys(mock_candidates):
    """provenance 로 가야 할 메타데이터(URL·참고문구)가 specs 에 섞이면 [3-B] data_gap 감점이
    메타데이터를 스펙 결손으로 잘못 센다(계획 §3.3 E9 columns 주석)."""
    forbidden = {"product_url", "manual_reference", "software_url", "price_note"}
    for cands in mock_candidates.values():
        for cand in cands:
            assert not (forbidden & set(cand.specs)), cand.specs


def test_mock_loader_provenance_has_price_note_and_urls(mock_candidates):
    monitor = next(c for c in mock_candidates["monitor"] if "va24dqsb" in c.product_key)
    assert monitor.provenance["price_note"] == PRICE_NOTE
    assert monitor.provenance["product_url"].startswith("https://")
    mouse = next(c for c in mock_candidates["mouse"] if "mx-master-3s" in c.product_key)
    assert "software_url" in mouse.provenance    # mouse 만 software_url 을 갖는다


def test_mock_loader_provenance_has_image_url_for_every_kind(mock_candidates):
    """catalog.product.image_url이 실재하고(E13 감사 정정) CSV "이미지 URL" 열도 모든
    픽스처 행에 채워져 있다 — provenance.image_url이 specs가 아니라 여기로 가야 한다."""
    for cands in mock_candidates.values():
        for cand in cands:
            assert cand.provenance.get("image_url", "").startswith("https://"), cand.product_key
            assert "image_url" not in cand.specs   # 메타데이터라 specs 에는 안 들어간다


def test_mock_loader_resolution_classes_present(mock_candidates):
    by_key = {c.product_key: c for c in mock_candidates["monitor"]}
    assert by_key[pc_catalog_key("monitor", "ASUS", "VA24DQSB")].specs["resolution_class"] == "FHD"
    assert by_key[pc_catalog_key("monitor", "LG", "UltraGear 27GP850")].specs["resolution_class"] == "QHD"
    assert by_key[pc_catalog_key("monitor", "ASUS", "ProArt PA279CRV")].specs["resolution_class"] == "UHD"
    assert by_key[pc_catalog_key("monitor", "ASUS", "ProArt PA34VCNV")].specs["resolution_class"] == "QHD_WIDE"
    assert by_key[pc_catalog_key("monitor", "Apple", "Studio Display (2026)")].specs["resolution_class"] == "OTHER"


def test_mock_loader_parse_failures_omit_keys_not_default_them(mock_candidates):
    """폴링레이트 공란(MX Master 3S)·출력(W) 공란(Nommo V2 Pro) 은 0 이 아니라 키 자체가 없어야 한다."""
    mouse_by_key = {c.product_key: c for c in mock_candidates["mouse"]}
    mx_master = mouse_by_key[pc_catalog_key("mouse", "Logitech", "MX Master 3S")]
    assert "polling_hz_max" not in mx_master.specs
    assert mx_master.specs["dpi_max"] == 8000.0

    speaker_by_key = {c.product_key: c for c in mock_candidates["speaker"]}
    nommo = speaker_by_key[pc_catalog_key("speaker", "Razer", "Nommo V2 Pro")]
    assert "output_w" not in nommo.specs
    assert nommo.specs["channels"] == 2.1


def test_mock_loader_keyboard_switch_classification(mock_candidates):
    by_key = {c.product_key: c for c in mock_candidates["keyboard"]}
    g915 = by_key[pc_catalog_key("keyboard", "Logitech", "G915 X LIGHTSPEED")]
    assert "switch_clicky" not in g915.specs             # GL Linear/Tactile/Clicky 나열 -> 판정 불가
    assert g915.specs["switch_magnetic"] is False
    assert g915.specs["switch_low_profile"] is True

    g515 = by_key[pc_catalog_key("keyboard", "Logitech", "G515 RAPID TKL")]
    assert g515.specs["switch_magnetic"] is True
    assert g515.specs["switch_low_profile"] is True      # kind 텍스트의 "Low-profile"

    corsair = by_key[pc_catalog_key("keyboard", "Corsair", "K100 AIR Wireless")]
    assert corsair.specs["switch_clicky"] is False
    assert corsair.specs["switch_low_profile"] is True


def test_mock_loader_missing_directory_file_is_skipped(tmp_path):
    """kind 파일이 없으면 조용히 건너뛴다(존재하는 종류만 낸다) — 예외로 전체를 막지 않는다."""
    result = load_peripheral_candidates_from_csv(tmp_path)
    assert result == {}


# ── 미러 표(_COMMON_HEADERS/_KIND_HEADERS) 드리프트 검증 ─────────────────────
# peripheral_catalog.py 의 _COMMON_HEADERS/_KIND_HEADERS 는 db/seed_peripherals.py 의
# _COMMON/_SPECS 를 손으로 옮겨 적은 미러다(운영 코드가 그 파일을 직접 import 할 수 없는 이유는
# peripheral_catalog.py 상단 주석 참고 — db/ 최상위 디렉터리가 src/db 와 이름이 겹쳐
# PYTHONPATH=. 환경에서 "import db.seed_peripherals" 가 항상 src/db 로 해석된다). 테스트에서만
# 파일 경로로 동적 로드해서 두 표가 갈라지지 않았는지(드리프트) 대조한다. db/seed_peripherals.py
# 는 이 테스트에서도 수정하지 않는다 — 읽기만 한다.
def _load_seed_peripherals_module():
    import importlib.util
    import sys

    from src.config import ROOT

    path = ROOT / "db" / "seed_peripherals.py"
    spec = importlib.util.spec_from_file_location("_truefit_seed_peripherals_file", path)
    module = importlib.util.module_from_spec(spec)
    # exec_module 전에 sys.modules 에 등록해야 한다 — seed_peripherals.py 의 @dataclass 가
    # cls.__module__ 로 sys.modules 를 찾는데, 미등록 상태면 AttributeError 로 죽는다.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — 실패 사유를 테스트 실패 메시지에 그대로 남긴다
        del sys.modules[spec.name]
        pytest.fail(
            f"db/seed_peripherals.py 동적 로드 실패({exc.__class__.__name__}: {exc}) — "
            "이 모듈 최상위의 import(예: from src.db import get_conn, "
            "from src.repo.product_repo import ProductRepo)가 이 환경에서 실패했을 수 있습니다."
        )
    return module


def _header_to_column(mapping: dict[str, tuple[str, str]]) -> dict[str, str]:
    """헤더 -> DB 컬럼명만 뽑는다(변환 kind 태그는 표현이 달라질 수 있어 따로 비교한다)."""
    return {header: column for header, (column, _tag) in mapping.items()}


def test_mirror_header_mapping_matches_seed_peripherals_source_of_truth():
    """_COMMON_HEADERS/_KIND_HEADERS 미러가 db/seed_peripherals.py 의 _COMMON/_SPECS 와
    갈라지지 않았는지 확인한다. seed 쪽 헤더/컬럼이 바뀌었는데 이 미러를 안 고치면(=mock
    로더가 DB 로더와 다른 specs 를 만들게 되는 드리프트) 이 테스트가 실패로 잡는다."""
    seed = _load_seed_peripherals_module()

    # 1) 헤더 -> DB 컬럼명 매핑 — 이게 갈라지면 mock/DB 로더가 다른 값을 읽게 되므로 필수 검사.
    assert _header_to_column(pc._COMMON_HEADERS) == _header_to_column(seed._COMMON)
    assert set(pc._KIND_HEADERS) == set(seed._SPECS), "종류(kind) 집합이 seed 와 다름"
    for kind, (_table, fields) in seed._SPECS.items():
        assert _header_to_column(pc._KIND_HEADERS[kind]) == _header_to_column(fields), (
            f"{kind}: 헤더->컬럼 매핑이 db/seed_peripherals.py 와 다름(드리프트)"
        )

    # 2) 변환 kind 태그 — 현재 두 표는 같은 문자열 태그(text/url/decimal/integer/port_count/
    #    rapid_trigger/connection_method/pipe_list)를 쓴다. 이 비교는 태그 표현이 같은 동안만
    #    유효하므로 1)과 분리해 둔다(표현이 달라지면 이 assert 만 걷어내면 된다).
    assert dict(pc._COMMON_HEADERS) == dict(seed._COMMON)
    for kind, (_table, fields) in seed._SPECS.items():
        assert dict(pc._KIND_HEADERS[kind]) == dict(fields), f"{kind}: 변환 kind 태그가 seed 와 다름"


# ── build_peripheral_specs / build_peripheral_provenance 직접 호출 ─────────
def test_build_peripheral_specs_omits_none_values():
    rules = load_peripheral_rules()
    row = {"resolution": None, "max_refresh_hz": 144, "panel": "IPS"}
    specs = build_peripheral_specs("monitor", row, rules)
    assert "resolution_raw" not in specs
    assert "resolution_w" not in specs
    assert specs["refresh_hz"] == 144.0
    assert specs["panel_raw"] == "IPS"


def test_build_peripheral_provenance_only_known_meta_columns():
    row = {"product_url": "https://example.com/p", "manual_reference": None, "software_url": "https://sw.example.com"}
    prov = build_peripheral_provenance("keyboard", row)   # keyboard 는 software_url 을 안 읽는다
    assert prov == {"product_url": "https://example.com/p", "price_note": PRICE_NOTE}


# ── DB 통합 ────────────────────────────────────────────────────────────
@pytest.fixture
def conn():
    import psycopg

    from src.config import DATABASE_URL

    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        ok = connection.execute("SELECT to_regclass('catalog.monitor_spec') IS NOT NULL").fetchone()[0]
        if not (ok and connection.execute("SELECT count(*) FROM catalog.monitor_spec").fetchone()[0] > 0):
            pytest.skip("주변기기 카탈로그가 seed 되지 않았습니다 — db/setup_all.py로 준비하세요.")
        yield connection
    finally:
        connection.close()


def _csv_priced_row_count(kind: str) -> int:
    import csv

    from src.config import DATA_DIR

    path = DATA_DIR / "peripherals" / f"{kind}_processed.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return sum(1 for row in rows if (row.get("가격(원)") or "").strip())


@pytest.mark.db
def test_db_loader_counts_match_priced_csv_rows(conn):
    from src.repo.catalog_repo import load_peripheral_candidates

    by_kind = load_peripheral_candidates(conn)
    for kind in ("monitor", "keyboard", "mouse", "speaker"):
        expected = _csv_priced_row_count(kind)
        assert len(by_kind.get(kind, [])) == expected, f"{kind}: DB 후보 수가 가격 있는 CSV 행 수와 다름"


@pytest.mark.db
def test_db_loader_all_reference_snapshot_no_offer(conn):
    from src.repo.catalog_repo import load_peripheral_candidates

    by_kind = load_peripheral_candidates(conn)
    all_candidates = [c for cands in by_kind.values() for c in cands]
    assert all_candidates, "주변기기 후보가 0건입니다 — seed 확인 필요"
    for cand in all_candidates:
        assert cand.offer_observation_id is None
        assert cand.price_source == "reference_snapshot"
        assert cand.price > 0


@pytest.mark.db
def test_db_loader_monitor_specs_have_resolution_class(conn):
    from src.repo.catalog_repo import load_peripheral_candidates

    by_kind = load_peripheral_candidates(conn)
    monitors = by_kind.get("monitor", [])
    assert monitors, "모니터 후보가 0건입니다"
    for cand in monitors:
        assert "resolution_class" in cand.specs
        assert "resolution_w" in cand.specs and "resolution_h" in cand.specs


@pytest.mark.db
def test_db_and_mock_loaders_agree_on_specs_for_same_model(conn):
    """계획 §3.3 E9: DB 경로와 mock 경로가 같은 행에 대해 같은 specs 를 만든다."""
    from src.repo.catalog_repo import load_peripheral_candidates

    key = pc_catalog_key("monitor", "ASUS", "ProArt PA279CRV")
    db_by_kind = load_peripheral_candidates(conn)
    db_cand = next((c for c in db_by_kind.get("monitor", []) if c.product_key == key), None)
    assert db_cand is not None, "seed 된 DB에 ASUS ProArt PA279CRV 가 없습니다"

    mock_by_kind = load_peripheral_candidates_from_csv(_FIXTURES)
    mock_cand = next(c for c in mock_by_kind["monitor"] if c.product_key == key)

    assert db_cand.specs == mock_cand.specs
    # specs 키 집합은 image_url 추가(E13 감사 정정) 전후로 그대로여야 한다 — image_url은
    # provenance로만 가고 specs에는 안 들어간다.
    assert set(db_cand.specs) == set(mock_cand.specs)
    assert "image_url" not in db_cand.specs and "image_url" not in mock_cand.specs


@pytest.mark.db
def test_db_and_mock_loaders_agree_on_provenance_image_url(conn):
    """DB 로더(catalog.product.image_url)와 mock CSV 로더("이미지 URL" 열)가 같은 상품에
    같은 image_url을 provenance에 담는다(E13 감사 — image_url 컬럼이 실재하고 seed 돼 있다)."""
    from src.repo.catalog_repo import load_peripheral_candidates

    key = pc_catalog_key("monitor", "ASUS", "ProArt PA279CRV")
    db_by_kind = load_peripheral_candidates(conn)
    db_cand = next((c for c in db_by_kind.get("monitor", []) if c.product_key == key), None)
    assert db_cand is not None, "seed 된 DB에 ASUS ProArt PA279CRV 가 없습니다"

    mock_by_kind = load_peripheral_candidates_from_csv(_FIXTURES)
    mock_cand = next(c for c in mock_by_kind["monitor"] if c.product_key == key)

    assert db_cand.provenance.get("image_url"), "DB provenance에 image_url이 없습니다 — seed 확인 필요"
    assert db_cand.provenance["image_url"] == mock_cand.provenance["image_url"]

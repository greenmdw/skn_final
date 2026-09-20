"""팀 전달 CSV 4종의 DB 적재 전 검증과 무손실 매핑."""
from collections import Counter

import pytest

from db.seed_peripherals import DATA_DIR, _convert, load_rows


def test_all_peripheral_rows_are_read_and_priced_only_when_present():
    rows = load_rows(DATA_DIR)
    assert Counter(row.product_type for row in rows) == {
        "mouse": 90, "monitor": 43, "speaker": 46, "keyboard": 42,
    }
    assert sum(row.price_krw is not None for row in rows) == 209
    assert len({(row.brand.casefold(), row.model.casefold()) for row in rows}) == 221
    assert all(len(row.source_sha256) == 64 and row.source_row >= 2 for row in rows)


def test_missing_values_and_source_ambiguity_are_not_invented_away():
    rows = load_rows(DATA_DIR)
    monitor = next(row for row in rows if row.model == "ASUS ProArt Display PA279CV")
    assert monitor.price_krw is None
    assert monitor.specs["weight_g"] is None
    assert monitor.specs["hdmi_version"] == "2"  # 2.0/2.1로 추정하지 않음
    keyboard = next(row for row in rows if row.model == "PRO X TKL RAPID")
    assert keyboard.specs["rapid_trigger"] is True
    speaker = next(row for row in rows if row.model == "브리츠인터내셔널 BA-R9")
    assert speaker.specs["manual_reference"] == "BA-R9 SoundBar_manual.jpg"
    assert speaker.specs["impedance"] == "4Ω"


def test_port_absence_is_zero_but_unknown_is_null():
    assert _convert("없음", "port_count") == 0
    assert _convert("미표기", "port_count") is None
    assert _convert("", "integer") is None
    assert _convert("X", "rapid_trigger") is False
    with pytest.raises(ValueError):
        _convert("maybe", "rapid_trigger")

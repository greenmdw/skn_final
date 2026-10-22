"""팀 전달 CSV 4종의 DB 적재 전 검증과 무손실 매핑."""
from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("seed_peripherals", ROOT / "db" / "seed_peripherals.py")
assert SPEC and SPEC.loader
seed_peripherals = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seed_peripherals
SPEC.loader.exec_module(seed_peripherals)
DATA_DIR, _convert, load_rows = (
    seed_peripherals.DATA_DIR, seed_peripherals._convert, seed_peripherals.load_rows,
)


@pytest.fixture(scope="module")
def source_rows():
    files = ("mouse_processed.csv", "monitor_processed.csv", "speaker_processed.csv", "keyboard_processed.csv")
    if not all((DATA_DIR / name).is_file() for name in files):
        pytest.skip("팀 전달 원본 CSV는 저장소에 포함되지 않습니다.")
    return load_rows(DATA_DIR)


def test_all_peripheral_rows_are_read_and_priced_only_when_present(source_rows):
    rows = source_rows
    assert Counter(row.product_type for row in rows) == {
        "mouse": 84, "monitor": 33, "speaker": 45, "keyboard": 41,
    }
    assert sum(row.price_krw is not None for row in rows) == 203
    assert len({(row.brand.casefold(), row.model.casefold()) for row in rows}) == 203
    assert all(len(row.source_sha256) == 64 and row.source_row >= 2 for row in rows)


def test_connection_method_and_interface_are_preserved_separately(source_rows):
    rows = source_rows
    mouse = next(row for row in rows if row.model == "MX Master 3S")
    assert mouse.specs["connectivity"] == ["무선"]
    assert mouse.specs["connectivity_interface"] == ["USB 수신기", "Bluetooth"]
    keyboard = next(row for row in rows if row.model == "G915 X LIGHTSPEED")
    assert keyboard.specs["connectivity"] == ["유선", "무선"]
    assert keyboard.specs["connectivity_interface"] == ["USB", "USB 수신기", "Bluetooth"]


def test_port_absence_is_zero_but_unknown_is_null():
    assert _convert("없음", "port_count") == 0
    assert _convert("미표기", "port_count") is None
    assert _convert("", "integer") is None
    assert _convert("X", "rapid_trigger") is False
    with pytest.raises(ValueError):
        _convert("maybe", "rapid_trigger")


def test_connection_method_and_pipe_delimited_interface_are_validated():
    assert _convert("유선|무선", "connection_method") == ["유선", "무선"]
    assert _convert("USB| Bluetooth ", "pipe_list") == ["USB", "Bluetooth"]
    with pytest.raises(ValueError, match="연결 방식"):
        _convert("Bluetooth", "connection_method")
    with pytest.raises(ValueError, match="구분한 값"):
        _convert("USB||Bluetooth", "pipe_list")

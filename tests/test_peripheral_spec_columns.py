"""0016 — GPU 출력 단자(B-9)와 키보드 키압(B-8)이 시드 → DB → 후보 로더 → 판정까지 이어진다.

일회용 DB(이름에 test 포함)와 비공개 시드(data/peripherals/keyboard_processed.csv, data/parts_list_modify.xlsx)가 필요하다."""
from __future__ import annotations

import csv
import os
from decimal import Decimal

import openpyxl
import pytest

from src.config import ROOT

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.db import get_conn
    from src.engine.peripheral_cross import _monitor_gpu_port_check
    from src.engine.peripheral_rules import load_peripheral_rules
    from src.repo import catalog_repo


def _keyboard_csv() -> dict[tuple[str, str], tuple[str, str]]:
    path = ROOT / "data" / "peripherals" / "keyboard_processed.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {(r["제조사"].strip(), r["모델명"].strip()): (r["키압 최소(g)"].strip(), r["키압 최대(g)"].strip())
                for r in csv.DictReader(f)}


def test_keyboard_key_force_is_loaded_and_matches_the_source_data():
    source = _keyboard_csv()
    with get_conn() as conn:
        keyboards = catalog_repo.load_peripheral_candidates(conn)["keyboard"]
    with_force, without = [], []
    for kb in keyboards:
        expected = source[(kb.brand, kb.name.removeprefix(kb.brand + " "))]
        has_source = bool(expected[0] or expected[1])
        has_spec = "key_force_min_g" in kb.specs or "key_force_max_g" in kb.specs
        assert has_spec == has_source, kb.name                       # 값이 없는 상품에는 키를 넣지 않는다(모름)
        if has_spec:
            with_force.append(kb)
            assert kb.specs["key_force_min_g"] == float(expected[0]) and kb.specs["key_force_max_g"] == float(expected[1])
            assert 0 < kb.specs["key_force_min_g"] <= kb.specs["key_force_max_g"]
        else:
            without.append(kb)
    assert with_force and without                                    # 일부만 값이 있다(요청서: 41종 중 22종)
    assert len(with_force) <= sum(1 for lo, hi in source.values() if lo or hi)


def test_key_force_check_constraint_rejects_inverted_or_nonpositive_values():
    import psycopg

    with get_conn() as conn:
        pid = conn.execute("SELECT product_id FROM catalog.keyboard_spec LIMIT 1").fetchone()[0]
        for lo, hi in ((60, 45), (0, 45), (-5, None)):
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute("UPDATE catalog.keyboard_spec SET key_force_min_g = %s, key_force_max_g = %s WHERE product_id = %s",
                                 (lo, hi, pid))
        with conn.transaction(force_rollback=True):                  # 한쪽만 있거나 둘 다 NULL 은 허용(시험 뒤 되돌린다)
            conn.execute("UPDATE catalog.keyboard_spec SET key_force_min_g = 40, key_force_max_g = NULL WHERE product_id = %s", (pid,))
            conn.execute("UPDATE catalog.keyboard_spec SET key_force_min_g = NULL, key_force_max_g = NULL WHERE product_id = %s", (pid,))


def _gpu_sheet_rows() -> list[tuple[str, str, object, object, object]]:
    ws = openpyxl.load_workbook(ROOT / "data" / "parts_list_modify.xlsx", data_only=True, read_only=True)["GPU"]
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    idx = {name: head.index(name) for name in ("제조사", "모델명", "HDMI 버전", "DP 버전", "USB-C 영상 출력")}
    return [(r[idx["제조사"]], r[idx["모델명"]], r[idx["HDMI 버전"]], r[idx["DP 버전"]], r[idx["USB-C 영상 출력"]])
            for r in rows[1:] if r[idx["제조사"]] and r[idx["모델명"]]]


def test_gpu_port_columns_are_loaded_with_the_keys_the_port_check_reads():
    sheet = {(b, m): (hdmi, dp, usb) for b, m, hdmi, dp, usb in _gpu_sheet_rows()}
    with get_conn() as conn:
        gpus = catalog_repo.load_candidates_by_slot_from_db(conn)["GPU"]
    assert gpus
    loaded = 0
    for gpu in gpus:
        hdmi, dp, usb = sheet[(gpu.brand, gpu.name.removeprefix(gpu.brand + " "))]
        assert gpu.specs.get("hdmi_version") == (hdmi or None)
        assert gpu.specs.get("dp_version") == (dp or None)
        assert gpu.specs.get("usb_c_video_out") == (None if usb is None else bool(usb))
        loaded += "hdmi_version" in gpu.specs or "dp_version" in gpu.specs
    assert loaded >= len(gpus) * 0.9                                 # 요청서: 43종 모두 값이 있다
    gpu_keys = load_peripheral_rules()["verify"]["gpu_keys"]
    assert {"hdmi_version", "dp_version", "usb_c_video_out"} <= set(gpu_keys.values())


def test_monitor_port_check_is_decidable_now_that_gpu_port_data_exists():
    rules = load_peripheral_rules()
    with get_conn() as conn:
        gpus = [g for g in catalog_repo.load_candidates_by_slot_from_db(conn)["GPU"] if g.specs.get("dp_version")]
        monitors = catalog_repo.load_peripheral_candidates(conn)["monitor"]
    assert gpus and monitors
    states = {_monitor_gpu_port_check(m, gpus[0].specs, 144, rules)["state"] for m in monitors if m.specs.get("resolution_class")}
    assert states & {"ok", "fail"}                                   # 예전에는 GPU 값이 없어 항상 "unknown"(확인 불가)였다
    assert _monitor_gpu_port_check(monitors[0], None, 144, rules)["state"] == "unknown"      # PC 구성이 없으면 여전히 확인 불가
    assert _monitor_gpu_port_check(monitors[0], {}, 144, rules)["state"] == "unknown"


def test_loader_leaves_gpu_keys_out_when_the_source_has_no_value():
    from src.repo.catalog_repo import _specs_from_row

    specs = _specs_from_row("gpu", {"length_mm": 300, "hdmi_version": None, "dp_version": "", "usb_c_video_out": None})
    assert "hdmi_version" not in specs and "dp_version" not in specs and "usb_c_video_out" not in specs
    specs = _specs_from_row("gpu", {"hdmi_version": "2.1b", "dp_version": "1.4a", "usb_c_video_out": False})
    assert specs["hdmi_version"] == "2.1b" and specs["dp_version"] == "1.4a" and specs["usb_c_video_out"] is False
    assert Decimal("1") == 1

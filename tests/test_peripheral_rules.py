"""주변기기 정의 로더(E8) 테스트 — config/peripherals.yaml + src/engine/peripheral_rules.py.

DB 불필요. 계획 §3.3 E8의 완료 기준: 4종 로드, 리뷰축 가중치 0, 가중치 합 1, 잘못된
설정은 PeripheralRuleError, columns의 DB 컬럼이 실제 스키마에 존재, requested_kinds
경계값, 기존 PC 후보 생성 경로(Candidate.price_source 기본값) 불변.
"""
from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.categories import available_categories
from src.config import ROOT
from src.dto import Candidate
from src.engine import peripheral_rules
from src.repo.catalog_repo import load_candidates_by_slot

_SCHEMA_SQL = (ROOT / "db" / "migrations" / "0000_schema.sql").read_text(encoding="utf-8")


def _schema_columns(table: str) -> set[str]:
    """0000_schema.sql에서 catalog.<table> 의 실제 컬럼명 집합을 뽑는다(오타 방지용)."""
    match = re.search(rf"CREATE TABLE catalog\.{re.escape(table)} \((.*?)\n\);", _SCHEMA_SQL, re.S)
    assert match, f"schema에서 catalog.{table} 을 찾지 못함"
    columns = set()
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith("CONSTRAINT"):
            continue
        columns.add(line.split()[0])
    return columns


def _write(tmp_path: Path, rules: dict, name: str = "peripherals.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ── 정상 로드 ────────────────────────────────────────────────────────────
def test_default_yaml_loads_four_kinds():
    rules = peripheral_rules.load_peripheral_rules()
    assert rules["schema_version"] == 1
    assert rules["rule_set_version"] == "peripheral-rules-v2"
    assert peripheral_rules.peripheral_kinds(rules) == ["keyboard", "monitor", "mouse", "speaker"]


def test_review_axis_weight_is_zero_and_weights_sum_to_one():
    rules = peripheral_rules.load_peripheral_rules()
    for kind in peripheral_rules.peripheral_kinds(rules):
        weights = rules["ranking"][kind]["weights"]
        assert weights["리뷰"] == 0
        assert abs(sum(weights.values()) - 1) < 1e-9


def test_kind_def_helper_returns_expected_shape():
    kdef = peripheral_rules.kind_def("monitor")
    assert kdef["label"] == "모니터"
    assert kdef["product_type"] == "monitor"
    assert kdef["spec_table"] == "catalog.monitor_spec"
    assert isinstance(kdef["columns"], dict) and kdef["columns"]


def test_kind_def_unknown_kind_raises():
    with pytest.raises(peripheral_rules.PeripheralRuleError):
        peripheral_rules.kind_def("toaster")


# ── 컬럼이 실제 스키마에 있는지(오타 방지) ─────────────────────────────────
@pytest.mark.parametrize("kind", ["monitor", "keyboard", "mouse", "speaker"])
def test_columns_reference_real_schema_columns(kind):
    kdef = peripheral_rules.kind_def(kind)
    table = kdef["spec_table"].split(".", 1)[1]
    real_columns = _schema_columns(table)
    for db_col in kdef["columns"]:
        assert db_col in real_columns, f"{kind}.{db_col} 은 {table} 의 실제 컬럼이 아님"


def test_columns_engine_keys_are_unique_per_kind():
    rules = peripheral_rules.load_peripheral_rules()
    for kind in peripheral_rules.peripheral_kinds(rules):
        engine_keys = list(rules["kinds"][kind]["columns"].values())
        assert len(engine_keys) == len(set(engine_keys))


# ── 잘못된 설정은 PeripheralRuleError ──────────────────────────────────────
def test_unknown_top_level_key_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["not_a_real_section"] = {}
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="알 수 없는 최상위 키"):
        peripheral_rules.load_peripheral_rules(path)


def test_missing_kind_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    del rules["kinds"]["mouse"]
    del rules["ranking"]["mouse"]
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="네 종류"):
        peripheral_rules.load_peripheral_rules(path)


def test_weights_sum_not_one_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["ranking"]["monitor"]["weights"]["가격"] = 0.9
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="합계가 1"):
        peripheral_rules.load_peripheral_rules(path)


def test_review_weight_nonzero_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    weights = rules["ranking"]["monitor"]["weights"]
    weights["리뷰"] = 0.1
    weights["가격"] -= 0.1
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="리뷰축"):
        peripheral_rules.load_peripheral_rules(path)


def test_duplicate_engine_key_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    columns = rules["kinds"]["monitor"]["columns"]
    first_two = list(columns)[:2]
    columns[first_two[1]] = columns[first_two[0]]
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="중복"):
        peripheral_rules.load_peripheral_rules(path)


def test_schema_version_mismatch_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["schema_version"] = 2
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="schema_version"):
        peripheral_rules.load_peripheral_rules(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="없음"):
        peripheral_rules.load_peripheral_rules(tmp_path / "nope.yaml")


# ── verify 절(E12) 검증 ─────────────────────────────────────────────────
def test_verify_bad_version_format_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["verify"]["port_modes"]["hdmi"]["2"] = {"FHD": 100}   # "주.부" 형식이 아님
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="버전 형식 오류"):
        peripheral_rules.load_peripheral_rules(path)


def test_verify_unknown_interface_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["verify"]["port_modes"]["usb"] = {"1.0": {"FHD": 60}}   # hdmi/dp 외 인터페이스
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="hdmi.*dp|dp.*hdmi"):
        peripheral_rules.load_peripheral_rules(path)


def test_verify_non_positive_hz_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    rules["verify"]["port_modes"]["hdmi"]["1.4"]["FHD"] = 0
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="양수 아님"):
        peripheral_rules.load_peripheral_rules(path)


def test_verify_gpu_keys_missing_key_raises(tmp_path):
    rules = deepcopy(peripheral_rules.load_peripheral_rules())
    del rules["verify"]["gpu_keys"]["dp_ports"]
    path = _write(tmp_path, rules)
    with pytest.raises(peripheral_rules.PeripheralRuleError, match="gpu_keys"):
        peripheral_rules.load_peripheral_rules(path)


# ── requested_kinds ─────────────────────────────────────────────────────
def test_requested_kinds_normal():
    assert peripheral_rules.requested_kinds({"peripherals": ["monitor", "mouse"]}) == ["monitor", "mouse"]
    assert peripheral_rules.requested_kinds({"peripherals": "monitor,mouse"}) == ["monitor", "mouse"]


def test_requested_kinds_empty_or_missing():
    assert peripheral_rules.requested_kinds({}) == []
    assert peripheral_rules.requested_kinds({"peripherals": []}) == []
    assert peripheral_rules.requested_kinds({"peripherals": None}) == []


def test_requested_kinds_unknown_kind_raises():
    with pytest.raises(ValueError, match="알 수 없는 주변기기 종류"):
        peripheral_rules.requested_kinds({"peripherals": ["monitor", "toaster"]})


# ── Candidate 기본값·기존 PC 후보 생성 경로 불변 ───────────────────────────
def test_candidate_default_price_source_is_observed():
    cand = Candidate(product_key="k", slot="CPU", name="n")
    assert cand.price_source == "observed"
    assert cand.price_observed_at is None


def test_existing_pc_candidate_loader_unaffected_by_new_fields():
    by_slot = load_candidates_by_slot()
    assert by_slot, "기존 목 카탈로그 로더가 후보를 내지 못함"
    for slot, cands in by_slot.items():
        for cand in cands:
            assert cand.slot == slot
            assert cand.price_source == "observed"
            assert cand.price_observed_at is None
            assert cand.verdict == "Pass"


# ── available_categories 는 그대로 computer 하나뿐 ─────────────────────────
def test_available_categories_still_only_computer():
    assert available_categories() == ["computer"]

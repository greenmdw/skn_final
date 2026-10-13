"""스펙 조건 임계값의 변별력 테스트 — config/peripherals.yaml `spec_conditions`.

선호 조건이 카탈로그의 거의 전부(≥95%)가 통과하거나 거의 아무도 통과하지 못하면(≤5%) 칩을 눌러도 순서가
바뀌지 않거나 후보가 사라진다. 실제 카탈로그(data/peripherals/*_processed.csv, DB 불필요)로 통과율을
계산해 그런 조건이 생기면 실패시킨다. 값이 없는(Pending) 제품은 통과율 계산에서 뺀다.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from src.config import ROOT
from src.engine import spec_rules
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_rules import load_peripheral_rules

_DATA_DIR = ROOT / "data" / "peripherals"
_MAX_PASS_RATE = 0.95
_MIN_PASS_RATE = 0.05
# 값이 있는 제품이 이 수보다 적으면 통과율이 의미가 없다(데이터 공백) — 별도 테스트로 드러낸다.
_MIN_KNOWN = 10


@pytest.fixture(scope="module")
def pass_rates():
    if not (_DATA_DIR / "monitor_processed.csv").is_file():
        pytest.skip("팀 전달 원본 CSV는 저장소에 포함되지 않습니다.")
    rules = load_peripheral_rules()
    cands = load_peripheral_candidates_from_csv(_DATA_DIR, filename_template="{kind}_processed.csv")
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for kind, conds in rules["spec_conditions"].items():
        for cid, cond in conds.items():
            verdicts = [spec_rules.evaluate_all(cond["prefs"], c.specs)[0] for c in cands.get(kind, [])]
            out[(kind, cid)] = (verdicts.count("Pass"), verdicts.count("Pass") + verdicts.count("Fail"))
    return out


def test_no_spec_condition_passes_almost_everything_or_nothing(pass_rates):
    bad = []
    for (kind, cid), (passed, known) in pass_rates.items():
        if known < _MIN_KNOWN:
            continue
        rate = passed / known
        if rate >= _MAX_PASS_RATE or rate <= _MIN_PASS_RATE:
            bad.append(f"{kind}.{cid}: {passed}/{known} = {rate:.0%}")
    assert not bad, "변별력이 없는 스펙 조건(임계값을 조정한다): " + "; ".join(bad)


def test_spec_conditions_with_too_few_known_values_are_listed(pass_rates):
    """값이 있는 제품이 적은 조건은 통과율로 검증할 수 없다. 데이터가 채워지면 위 테스트의 대상이 된다.
    이 목록이 바뀌면(늘거나 줄면) 알 수 있도록 현재 알려진 공백만 허용한다."""
    sparse = {f"{kind}.{cid}" for (kind, cid), (_, known) in pass_rates.items() if known < _MIN_KNOWN}
    assert sparse <= {"keyboard.quiet_switch"}, f"새로 값이 부족해진 조건: {sorted(sparse)}"

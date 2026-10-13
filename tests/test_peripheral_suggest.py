"""주변기기 "더 맞추기" 칩 제안(견적 입력 설계 6.2) — DB 없이 도는 테스트(CSV 픽스처 후보).

핵심 규칙: 눌렀을 때 지금 보이는 순서(1위 + 대안)가 바뀌는 칩만, 이미 말한 조건은 빼고, 최대 3개."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.dto import PeripheralResult
from src.engine import peripheral_intent as pi
from src.engine import peripheral_rules as pr
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_select import run_peripherals
from src.engine.peripheral_suggest import suggest_chips

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_NOLOG = lambda *_: None  # noqa: E731
_ALL = ["keyboard", "mouse", "monitor", "speaker"]


@pytest.fixture(scope="module")
def candidates():
    return load_peripheral_candidates_from_csv(_FIXTURES, pr.load_peripheral_rules())


def _run(candidates, kinds, **raw):
    interp = pi.sanitize({"kinds": kinds, **raw})
    values = {"peripherals": kinds, "peripheral_resolved": pi.resolve(interp)}
    return interp, values, run_peripherals(values, candidates, _NOLOG)


def test_chips_only_for_those_that_change_the_visible_order(candidates):
    interp, values, base = _run(candidates, ["keyboard"])
    chips = suggest_chips(values, interp, candidates, base)
    assert chips and all(c["moved"] > 0 for c in chips)
    # 눌러서 정말 순서가 바뀌는지 같은 입력으로 다시 확인한다 — 제안과 실제가 어긋나면 안 된다.
    for chip in chips:
        interp2 = pi.merge(interp, pi.sanitize({"kinds": ["keyboard"], **{
            k: v for k, v in chip["add"].items() if v}}))
        values2 = {**values, "peripheral_resolved": pi.resolve(interp2)}
        after = run_peripherals(values2, candidates, _NOLOG)
        before_order = [base.picks[0].candidate.product_key, *(c.product_key for c in base.picks[0].alternatives)]
        after_order = [after.picks[0].candidate.product_key, *(c.product_key for c in after.picks[0].alternatives)]
        assert before_order != after_order


def test_chip_shape_is_ready_to_add_to_the_next_request(candidates):
    interp, values, base = _run(candidates, ["keyboard"])
    chip = suggest_chips(values, interp, candidates, base)[0]
    assert set(chip) == {"kind", "id", "label", "add", "moved"}
    assert set(chip["add"]) == {"purposes", "situations", "stated"}
    assert chip["label"]


def test_at_most_three_chips_across_kinds(candidates):
    interp, values, base = _run(candidates, _ALL)
    chips = suggest_chips(values, interp, candidates, base)
    assert 0 < len(chips) <= 3
    assert [c["moved"] for c in chips] == sorted((c["moved"] for c in chips), reverse=True)


def test_already_said_condition_is_not_suggested_again(candidates):
    interp, values, base = _run(candidates, ["keyboard"], situations=["quiet_place"])
    ids = [c["id"] for c in suggest_chips(values, interp, candidates, base)]
    assert "quiet_place" not in ids


def test_no_chips_when_result_is_not_ready(candidates):
    interp = pi.sanitize({"kinds": ["keyboard"]})
    assert suggest_chips({"peripherals": ["keyboard"]}, interp, candidates, PeripheralResult(status="empty")) == []
    assert suggest_chips({}, interp, candidates, PeripheralResult(status="skipped")) == []


def test_kind_without_any_order_changing_chip_gets_none(candidates):
    """마우스는 지금 조용함이 스펙 선호를 만들지 않아 순서가 바뀌지 않는다 — 체감 점수 단계 전에는 칩이 없다."""
    interp, values, base = _run(candidates, ["mouse"])
    assert suggest_chips(values, interp, candidates, base) == []


# ── 설정 검증 ───────────────────────────────────────────────────────────────
def _write(tmp_path, rules):
    path = tmp_path / "peripherals.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_every_configured_chip_names_listed_values():
    rules = pr.load_peripheral_rules()
    for kind in _ALL:
        chips = pr.adjust_chips(kind, rules)
        assert len({c["id"] for c in chips}) == len(chips)
        for chip in chips:
            assert chip["label"] and chip["add"]


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r["adjust_chips"]["keyboard"][0]["add"].update(purposes=["no_such_purpose"]), "목록에 없는 이름"),
    (lambda r: r["adjust_chips"]["keyboard"][0].update(add={"colors": ["red"]}), "add 키 오류"),
    (lambda r: r["adjust_chips"]["keyboard"].append(deepcopy(r["adjust_chips"]["keyboard"][0])), "id 오류"),
    (lambda r: r["adjust_chips"]["mouse"][0]["add"].update(stated=["no_such_condition"]), "목록에 없는 이름"),
])
def test_invalid_adjust_chips_are_rejected(tmp_path, mutate, match):
    rules = deepcopy(pr.load_peripheral_rules())
    mutate(rules)
    with pytest.raises(pr.PeripheralRuleError, match=match):
        pr.load_peripheral_rules(_write(tmp_path, rules))

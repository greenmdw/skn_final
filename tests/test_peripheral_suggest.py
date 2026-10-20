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


# ── 칩 시험을 그 종류만 다시 돌려도 결과가 같다(성능 개선의 근거) ───────────────────────────────────
# 2026-10-19 부하 시험에서 주변기기 추천이 느려진 원인: 칩 11개를 시험할 때마다 네 종류를 전부 다시 계산했다. 전체 예산이 없으면 한 종류의
# 순위는 다른 종류와 무관해 그 종류만 돌려도 같아야 한다 — 전 종류를 돌리는 기준 경로(restrict_trials=False)와 칩 목록이 같은지 비교한다.
_SCENARIOS = [
    (["keyboard"], {}), (["mouse"], {}), (["monitor"], {}), (["speaker"], {}), (_ALL, {}),
    (_ALL, {"situations": ["quiet_place"]}), (_ALL, {"situations": ["small_desk", "trending"]}), (_ALL, {"situations": ["design"]}),
    (["keyboard", "mouse"], {"purposes": ["game"]}), (["keyboard", "mouse"], {"purposes": ["office"]}),
    (["monitor", "speaker"], {"purposes": ["game"], "situations": ["portable"]}),
    (_ALL, {"purposes": ["fps", "wrist"]}),
]


@pytest.mark.parametrize("kinds, raw", _SCENARIOS, ids=[f"{'+'.join(k)}:{sorted(r)}" for k, r in _SCENARIOS])
def test_restricted_trials_give_the_same_chips_as_running_every_kind(candidates, kinds, raw):
    interp, values, base = _run(candidates, kinds, **raw)
    fast = suggest_chips(values, interp, candidates, base, restrict_trials=True)
    reference = suggest_chips(values, interp, candidates, base, restrict_trials=False)
    assert fast == reference


def test_restricted_trials_keep_the_same_chips_with_a_pc_context_and_per_kind_budgets(candidates):
    interp, values, base = _run(candidates, _ALL)
    ctx = {"resolution": "QHD_165", "gpu_specs": None}
    values = {**values, "peripheral_kind_budget": {"mouse": 80_000, "keyboard": 150_000}}
    base = run_peripherals(values, candidates, _NOLOG, pc_context=ctx)
    assert (suggest_chips(values, interp, candidates, base, pc_context=ctx, restrict_trials=True)
            == suggest_chips(values, interp, candidates, base, pc_context=ctx, restrict_trials=False))


def test_with_a_total_budget_every_kind_is_still_rerun_because_picks_depend_on_each_other(candidates, monkeypatch):
    """전체 예산이 있으면 종류끼리 엮이므로(조합 선택) 빠른 경로를 쓰지 않는다 — 시험마다 후보 사전이 통째로 넘어간다."""
    from src.engine import peripheral_suggest as ps
    interp, values, _base = _run(candidates, _ALL)
    values = {**values, "peripheral_budget_max": 600_000}
    base = run_peripherals(values, candidates, _NOLOG)
    seen: list[set[str]] = []
    real = ps.run_peripherals

    def spy(v, cands, *a, **kw):
        seen.append(set(cands))
        return real(v, cands, *a, **kw)

    monkeypatch.setattr(ps, "run_peripherals", spy)
    assert (suggest_chips(values, interp, candidates, base, restrict_trials=True)
            == suggest_chips(values, interp, candidates, base, restrict_trials=False))
    assert seen and all(kinds == set(candidates) for kinds in seen)


def test_without_a_budget_each_trial_runs_only_its_own_kind(candidates, monkeypatch):
    from src.engine import peripheral_suggest as ps
    interp, values, base = _run(candidates, _ALL)
    seen: list[set[str]] = []
    real = ps.run_peripherals
    monkeypatch.setattr(ps, "run_peripherals", lambda v, cands, *a, **kw: (seen.append(set(cands)), real(v, cands, *a, **kw))[1])
    ps.suggest_chips(values, interp, candidates, base)
    assert seen and all(len(kinds) == 1 for kinds in seen)

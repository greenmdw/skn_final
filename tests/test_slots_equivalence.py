"""E3 — [1] 두 경로(시나리오·조건)의 Slots 등가성 테스트 (P5, C4).

`stage1_intent.run`(시나리오 + `mock_slot_fill`)과 `slots_from_conditions`(대화로 쌓인 조건
dict)가 [2] 이후에 같은 결과를 내는지 본다. LLM 슬롯필링은 만들지 않는다 — `src/CLAUDE.md`
§D-3, `docs/추천엔진_구현계획.md` C4 합의대로 `stage1_intent`의 `NotImplementedError`는 의도된
상태로 남겨 둔다. DB 불필요.
"""
from __future__ import annotations

import pytest

from src.categories import load_category
from src.engine import slot_rules, stage1_intent, stage2_requirement
from src.engine.slots import slots_from_conditions
from src.pipeline import load_scenario
from src.services import session_service

_SCENARIOS = ["computer_pass", "computer_research"]


def _noop(_msg: str) -> None:
    pass


def _conditions_values(scenario: dict) -> dict:
    """mock_slot_fill(confirmed + assumed) + mode → 조건 경로가 실제로 받는 값 dict.

    실제 `execute_recommendation`은 `revision`의 조건 행 전부(`mode` 포함)를 하나의 `values`
    dict로 모아 `slots_from_conditions`에 넘긴다(`recommendation_service.py`). 그 모양을 그대로
    흉내 낸다.
    """
    fill = scenario["mock_slot_fill"]
    return {**fill["confirmed"], **fill["assumed"], "mode": scenario["mode"]}


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
def test_slots_values_equal_once_mode_key_difference_is_set_aside(scenario_name):
    """두 경로의 `Slots.values`는 `mode` 키 하나를 빼면 같다.

    조건 경로의 입력 `values`에는 `mode`가 조건 행으로 이미 들어 있고, `slots_from_conditions`는
    이를 걸러내지 않고 그대로 `full`에 병합한다. 반면 `stage1_intent.run`은 `mode`를
    `Slots.mode` 필드에만 넣고 `Slots.values`에는 넣지 않는다. 그래서 조건 경로의
    `Slots.values`에만 `mode` 키가 남는다 — 아래 strict xfail 테스트가 그 차이 자체를 기록한다.
    """
    cat_def = load_category("computer")
    scenario = load_scenario(scenario_name)

    slots_stage1 = stage1_intent.run(scenario, cat_def, _noop)
    slots_cond = slots_from_conditions("computer", cat_def, _conditions_values(scenario))

    extra_in_cond = set(slots_cond.values) - set(slots_stage1.values)
    assert extra_in_cond == {"mode"}, (
        f"예상한 것(mode 하나만 조건 경로에만 있음)과 다른 차이: {extra_in_cond}"
    )
    cond_values_without_mode = {k: v for k, v in slots_cond.values.items() if k != "mode"}
    assert cond_values_without_mode == slots_stage1.values
    assert slots_cond.values["mode"] == slots_cond.mode == slots_stage1.mode


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "조건 경로의 Slots.values 에는 'mode' 키가 남아 있다 — 조건 revision 행에 mode 가 있고 "
        "slots_from_conditions 가 이를 걸러내지 않아서다(src/engine/slots.py). stage1_intent.run "
        "은 mode 를 Slots.mode 필드에만 두고 Slots.values 에는 넣지 않는다. 이 자체는 [2] 이후 "
        "결과에 영향이 없다(_computer_build 는 slots.values['mode'] 를 읽지 않고 slots.mode 만 "
        "쓴다 — 위 test_slots_values_equal_once_mode_key_difference_is_set_aside 로 확인). "
        "완전 동치를 요구하는 이 테스트만 그 차이를 정직하게 실패로 남긴다."
    ),
)
def test_slots_values_are_byte_for_byte_equal(scenario_name):
    cat_def = load_category("computer")
    scenario = load_scenario(scenario_name)

    slots_stage1 = stage1_intent.run(scenario, cat_def, _noop)
    slots_cond = slots_from_conditions("computer", cat_def, _conditions_values(scenario))

    assert slots_stage1.values == slots_cond.values


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
def test_stage2_targets_and_budget_alloc_equal_across_both_paths(scenario_name):
    """[2] 결과(`targets`, `budget.alloc`)는 두 경로가 완전히 같다.

    두 Slots 를 각각 stage2_requirement.run 에 넣어 비교한다 — `_computer_build`는
    `slots.mode`(필드)만 읽고 `slots.values['mode']`는 읽지 않으므로, 위에서 발견한
    'mode' 키 차이는 여기엔 영향을 주지 않는다.
    """
    cat_def = load_category("computer")
    scenario = load_scenario(scenario_name)

    slots_stage1 = stage1_intent.run(scenario, cat_def, _noop)
    slots_cond = slots_from_conditions("computer", cat_def, _conditions_values(scenario))

    spec_stage1 = stage2_requirement.run(slots_stage1, cat_def, _noop)
    spec_cond = stage2_requirement.run(slots_cond, cat_def, _noop)

    assert spec_stage1.targets == spec_cond.targets
    assert spec_stage1.budget["alloc"] == spec_cond.budget["alloc"]


def test_slot_rules_example_values_fit_slot_schema():
    """`slot_rules`가 내장 예시 대화(`scripts/compare_conditions_paths.EXAMPLES["computer"]`)에서
    뽑은 값이 전부 `computer.yaml`의 `slot_schema` 타입·enum 안에 있다."""
    from scripts.compare_conditions_paths import EXAMPLES

    cat_def = load_category("computer")
    schema = cat_def["slot_schema"]

    values: dict = {}
    for turn in EXAMPLES["computer"]:
        values.update(slot_rules.extract("computer", turn))

    assert values, "예시 대화에서 아무 것도 추출되지 않았다 — 테스트가 아무것도 검증하지 못함"

    for key, value in values.items():
        assert key in schema, f"slot_rules 가 slot_schema 에 없는 키를 뽑음: {key}"
        spec = schema[key]
        type_ = spec["type"]
        if type_ == "enum":
            assert value in spec["values"], f"{key}={value!r} 가 enum {spec['values']} 밖"
        elif type_ == "int":
            assert isinstance(value, int) and not isinstance(value, bool), f"{key}={value!r} 는 int 가 아님"
        elif type_ == "bool":
            assert isinstance(value, bool), f"{key}={value!r} 는 bool 이 아님"
        elif type_ == "list":
            assert isinstance(value, list), f"{key}={value!r} 는 list 가 아님"
        elif type_ == "str":
            assert isinstance(value, str), f"{key}={value!r} 는 str 이 아님"
        elif type_ == "object":
            assert isinstance(value, dict), f"{key}={value!r} 는 object 가 아님"
        else:
            pytest.fail(f"slot_schema 에 처리 안 한 type: {type_} ({key})")


def test_stage1_path_raises_runtime_error_when_required_input_missing():
    """[1] required_inputs 하나가 `missing`에 남으면 `stage1_intent.run`은 RuntimeError."""
    cat_def = load_category("computer")
    scenario = {
        "category": "computer",
        "mode": "build",
        "input_text": "테스트 — 필수 입력 누락",
        "mock_slot_fill": {
            "confirmed": {"budget_max": 1_000_000, "priority": "value"},
            "assumed": {},
            "assumed_reason": {},
            "missing": ["purpose"],
        },
    }
    with pytest.raises(RuntimeError, match="required_inputs 미충족"):
        stage1_intent.run(scenario, cat_def, _noop)


def test_conditions_path_is_blocked_before_recommendation_when_required_input_missing():
    """조건 경로는 `stage1_intent`처럼 예외로 막지 않는다 — 그 대신 `session_service.compute_missing`
    이 `start_recommendation`(recommendation_service.py)에서 추천 착수 전에 걸러낸다.
    `slots_from_conditions`(=[2] 진입점)까지 가지도 못한다. 여기서는 그 게이트가 실제로 쓰는
    함수(`compute_missing`)를 직접 불러 확인한다(session_service 코드는 읽기만, 수정하지 않는다).
    """
    cat_def = load_category("computer")
    values = {
        "category": "computer",
        "mode": "build",
        "budget_max": 1_000_000,
        "priority": "value",
        # "purpose" 가 없다 — required_inputs = [mode, purpose, budget_max, priority]
    }
    missing = session_service.compute_missing(cat_def, values)
    assert "purpose" in missing

    # 전부 채우면 더는 막히지 않는다(대조군).
    complete_values = {**values, "purpose": "game"}
    assert "purpose" not in session_service.compute_missing(cat_def, complete_values)

"""큰 파이프라인 점검(scripts/e2e_smoke.py)을 테스트로 — 조건 대화 → 추천 → 결과 → 교체 → 확정 → 리포트가 끊기지 않는다.

일회용 DB(TEST_DATABASE_URL, 이름에 test 포함)와 PC 카탈로그 시드가 필요하다. 없으면 skip 된다(tests/conftest.py 의 보호).
회귀 배경: 선택을 전부 해제한 리스트가 확정(200)되던 결함 — 결과 항목이 있으면 통과시키고 선택 개수는 안 봤다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import e2e_smoke  # noqa: E402


@pytest.fixture(scope="module")
def smoke():
    """세 흐름을 한 번씩만 돌려 결과를 모든 테스트가 공유한다(가입·세션이 필요 이상 쌓이지 않게)."""
    steps = e2e_smoke.run_smoke()
    if not steps or not steps[0].ok:
        pytest.skip("첫 단계(세션 생성)부터 실패 — DB 준비(db/setup_all.py) 여부를 확인하세요: "
                    + (steps[0].note if steps else "단계 없음"))
    return steps


def _labels(steps, flow_prefix):
    return [(s.flow, s.label) for s in steps if s.flow.startswith(flow_prefix)]


@pytest.mark.parametrize("flow_prefix", ["A ", "B ", "C "])
def test_every_step_of_each_flow_passes(smoke, flow_prefix):
    failed = [f"{s.label}: {s.note}" for s in smoke if s.flow.startswith(flow_prefix) and not s.ok]
    assert failed == [], "\n" + e2e_smoke.format_report([s for s in smoke if s.flow.startswith(flow_prefix)])


def test_the_flows_cover_the_whole_journey(smoke):
    labels = {s.label for s in smoke}
    for needed in ("세션 생성", "조건 입력", "추천 실행(202)", "결과 조회", "후보 교체", "결과 화면 대화",
                   "리스트 확정", "리포트 조회", "대화 질문 응답"):
        assert needed in labels, f"점검에 '{needed}' 단계가 없다"
    assert {"A 신규 조립", "B 업그레이드", "C 경계 상황"} <= {s.flow for s in smoke}


def test_confirming_with_nothing_selected_is_rejected(smoke):
    step = next(s for s in smoke if s.label == "선택 0개 확정 거절")
    assert step.ok, step.note
    assert "no_items_selected" in step.note


def test_over_budget_quote_cannot_be_confirmed(smoke):
    step = next(s for s in smoke if s.label == "예산 초과 견적 확정 거절")
    assert step.ok and "over_budget" in step.note, step.note


def test_the_whole_smoke_finishes_quickly(smoke):
    assert sum(s.seconds for s in smoke) < 30            # 모의 LLM 기준. 크게 느려지면 파이프라인에 병목이 생긴 것


def test_report_lists_every_step_with_a_verdict(smoke):
    text = e2e_smoke.format_report(smoke)
    assert text.count("PASS") + text.count("FAIL") >= len(smoke)
    assert f"합계: {sum(1 for s in smoke if s.ok)}/{len(smoke)}" in text

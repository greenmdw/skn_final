"""도메인 확장성 리팩터링(A안) 착수 전 골든 스냅샷 — [3-C] PC 검증(stage3c_verify.verify_build)의
현재(하드코딩) 동작을 고정한다.

목적: link_check/budget → confidence·issues·gray_axes 로 가는 계산을 선언적 규칙 엔진으로
옮긴 뒤, 이 파일이 그대로(숫자 하나 안 틀리고) 통과해야 "행동이 안 바뀌었다"고 말할 수 있다.
새 로직을 추가하려고 이 파일의 기댓값을 고치지 않는다 — 기댓값이 바뀌어야 한다면 그건 새
기능이지 리팩터링이 아니다.

"""
from __future__ import annotations

from src.config import CONFIDENCE_THRESHOLD
from src.dto import BuildResult
from src.engine import stage3c_verify as s3c

_noop = lambda _m: None  # noqa: E731


def _build(link_check: dict[str, str] | None = None, budget: dict | None = None) -> BuildResult:
    return BuildResult(list_id="golden", link_check=link_check or {}, budget=budget or {})


def test_all_pass_no_budget_gives_full_confidence():
    r = s3c.verify_build(_build(), "computer", _noop)
    t = r.targets[0]
    assert t.confidence == 100
    assert t.passed is True
    assert t.issues == []
    assert t.gray_axes == ["설명서·규격(RAG 미연결)", "호환성 정밀 검사(소켓·전력·크기는 근사값)"]


def test_fail_link_check_penalizes_20_and_judges_violation():
    r = s3c.verify_build(_build(link_check={"socket": "fail"}), "computer", _noop)
    t = r.targets[0]
    assert t.confidence == 80 and t.passed is True   # 80 == CONFIDENCE_THRESHOLD, 경계값 포함
    assert len(t.issues) == 1
    issue = t.issues[0]
    assert issue.axis == "socket" and issue.judge == "위반" and issue.penalty == 20


def test_pending_link_check_penalizes_6_and_judges_needs_review():
    r = s3c.verify_build(_build(link_check={"power": "pending (근사)"}), "computer", _noop)
    t = r.targets[0]
    assert t.confidence == 94
    issue = t.issues[0]
    assert issue.judge == "확인 필요" and issue.penalty == 6


def test_budget_over_110_percent_penalizes_15():
    r = s3c.verify_build(_build(budget={"used": 1_700_000, "max": 1_500_000}), "computer", _noop)
    t = r.targets[0]
    assert t.confidence == 85
    issue = t.issues[0]
    assert issue.axis == "예산" and issue.judge == "초과" and issue.penalty == 15


def test_combined_penalties_can_drop_below_threshold():
    r = s3c.verify_build(
        _build(link_check={"socket": "fail", "cooler_height": "근사"},
               budget={"used": 1_700_000, "max": 1_500_000}),
        "computer", _noop,
    )
    t = r.targets[0]
    assert t.confidence == 100 - (20 + 6 + 15) == 59
    assert t.passed is False and t.confidence < CONFIDENCE_THRESHOLD
    assert {i.axis for i in t.issues} == {"socket", "cooler_height", "예산"}



def test_approx_axis_uses_fixed_sentence_without_llm(monkeypatch):
    """근사 축은 LLM 을 부르지 않고 정해진 안내 문장을 쓴다(실호출에서 "근거는 제공되지 않았습니다"만 되풀이됨)."""
    def boom(*_a, **_k):
        raise AssertionError("근사 축 문장에 LLM 을 부르면 안 된다")
    monkeypatch.setattr(s3c, "call_llm", boom)
    r = s3c.verify_build(_build(link_check={"bios": "ok (근사)", "gpu_len": "ok (근사)"}), "computer", _noop)
    texts = {i.axis: i.text for i in r.targets[0].issues}
    assert "BIOS" in texts["bios"] and "확인하지 못했습니다" in texts["bios"]
    assert texts["gpu_len"].startswith("그래픽카드 길이:")
    assert all("근거는 제공되지" not in t and "gpu_len" not in t for t in texts.values())

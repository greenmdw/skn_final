"""엔진 파이프라인 스모크 테스트 (DB·네트워크 없이 목으로 end-to-end).

실제 로직 테스트는 각 stage 구현 시 tests/engine/ 아래 추가.
"""
from src.pipeline import run_pipeline


def test_computer_pass_runs_end_to_end(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    r = run_pipeline("computer_pass", on_log=lambda _m: None, catalog_source="mock")
    assert r.build is not None and len(r.build.items) == 8
    assert "cpu" in r.review_requirement_profiles and r.rank.slots["CPU"]["pool"][0]["review_detail"]
    assert r.verification.targets[0].passed is True
    # 옛 목업 값(가격41/성능33/호환성26)이 아니라 [3-B] 점수의 실제 축별 비율이어야 한다.
    assert {"가격", "성능", "밸런스", "리뷰", "호환여유"} <= set(r.explanation.contribution)
    assert sum(r.explanation.contribution.values()) == 100


def test_computer_research_triggers_retry_then_passes(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    r = run_pipeline("computer_research", on_log=lambda _m: None, catalog_source="mock")
    assert r.verification.targets[0].rounds == 2          # 1회 실패 후 재탐색
    assert r.review_requirement_profiles and all(
        item["review_detail"] for info in r.rank.slots.values() for item in info["pool"]
    )
    assert r.verification.targets[0].passed is True

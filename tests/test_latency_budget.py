"""응답 시간 상한 — LLM 을 부르지 않는 구간이 느려지지 않았는지 (2026-10-07).

실제 LLM 이 낀 시간(추천 설명 문장, 대화 답, 실시간 검색)은 scripts/measure_latency.py 로 실서버에서 잰다. 여기서는 모의 LLM 으로
**우리 코드와 DB 만의 시간**을 본다 — 사용자가 "결과가 안 나온다"고 느끼는 원인이 우리 쪽인지 LLM 쪽인지 가르는 기준선이다.

상한은 지금 측정값의 수 배로 넉넉하게 잡았다(느린 PC·동시에 도는 다른 작업에도 안 깨지게). 이 상한을 넘으면 "조금 느려졌다"가 아니라
쿼리 폭증·루프 같은 구조 문제일 가능성이 크다.
"""
from __future__ import annotations

import os
import time

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from tests.test_list_history_http import _recommended_list, _signed_up

    from src.agent import spec_extraction_agent
    from src.auth import ratelimit

# 초 단위 상한
LIMITS = {
    "세션 생성": 2.0,
    "목록 조회": 2.0,
    "조건 대화 한 턴(규칙)": 3.0,
    "추천 실행→결과(모의 LLM)": 20.0,
    "결과 화면 대화 한 턴(규칙)": 5.0,
    "리스트 확정": 5.0,
    "리포트 조회": 3.0,
    "주변기기 추천(4종)": 5.0,
    "견적 초안 만들기(텍스트 8줄)": 5.0,
    "견적 분석": 8.0,
    "견적 점검 되묻기(규칙)": 5.0,
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: False)
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


def _timed(label: str, fn):
    start = time.perf_counter()
    out = fn()
    elapsed = time.perf_counter() - start
    assert elapsed < LIMITS[label], f"{label}: {elapsed:.2f}s (상한 {LIMITS[label]}s)"
    return out


QUOTE_TEXT = "\n".join([
    "CPU: AMD Ryzen 7 9800X3D 720,000원", "메인보드: ASRock B650 PG Lighting 190,000원", "RAM: 삼성전자 DDR5-5600 (16GB) x 2",
    "GPU: NVIDIA GeForce RTX 5070 Ti 1,200,000원", "저장장치: Samsung 990 PRO 1TB", "파워: Corsair RM850e",
    "케이스: NZXT H5 Flow", "쿨러: Thermalright Peerless Assassin 120 SE"])


def test_the_main_user_journey_stays_within_its_time_budget():
    client = _signed_up()
    sid = _timed("세션 생성", lambda: client.post("/session").json())["list_id"]
    _timed("목록 조회", lambda: client.get("/lists"))

    client.post(f"/session/{sid}/category", json={"category": "computer", "mode": "build"})
    _timed("조건 대화 한 턴(규칙)", lambda: client.post(f"/session/{sid}/message", json={"text": "게임용 PC 예산 200만원 성능 위주"}))

    def recommend():
        assert client.post(f"/session/{sid}/recommend").status_code == 202
        data = client.get(f"/session/{sid}/result").json()
        assert data["status"] == "done", data
        return data

    result = _timed("추천 실행→결과(모의 LLM)", recommend)
    _timed("결과 화면 대화 한 턴(규칙)", lambda: client.post(f"/session/{sid}/result-message", json={"text": "CPU를 더 저렴한 걸로 바꿔줘"}))
    assert result["items"], "추천 항목이 없다"
    _timed("리스트 확정", lambda: client.post(f"/lists/{sid}/confirm", json={"name": "시간 측정"}))
    _timed("리포트 조회", lambda: client.get(f"/lists/{sid}/report"))


def test_peripherals_and_quote_review_stay_within_their_time_budget():
    client = _signed_up()
    sid = client.post("/session").json()["list_id"]
    _timed("주변기기 추천(4종)", lambda: client.post(
        f"/session/{sid}/peripherals/recommend", json={"kinds": ["monitor", "keyboard", "mouse", "speaker"]}))

    draft = _timed("견적 초안 만들기(텍스트 8줄)", lambda: client.post("/pc/review-drafts", data={"text": QUOTE_TEXT}).json())
    analysis = _timed("견적 분석", lambda: client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={}))
    assert analysis.status_code == 200, analysis.text

    created = client.post("/pc/reviews", json={"current_specs": {"CPU": "AMD Ryzen 7 9800X3D", "GPU": "NVIDIA GeForce RTX 5070 Ti"},
                                               "conditions": {"purpose": "game", "resolution": "QHD_165", "budget_max": 3_000_000}})
    assert created.status_code == 201, created.text
    list_id = created.json()["list_id"]
    _timed("견적 점검 되묻기(규칙)", lambda: client.post(f"/pc/reviews/{list_id}/messages", json={"text": "호환은 문제없어?"}))


def test_list_view_does_not_grow_with_the_number_of_saved_lists():
    """/lists 가 목록 수만큼 느려지면(N+1 쿼리) 사용자가 쌓일수록 첫 화면이 느려진다 — 5개와 15개의 시간 비가 크지 않아야 한다."""
    client = _signed_up()

    def make(n):
        for _ in range(n):
            client.post("/session")

    def measure():
        start = time.perf_counter()
        for _ in range(3):
            assert client.get("/lists").status_code == 200
        return (time.perf_counter() - start) / 3

    make(5)
    small = measure()
    make(10)
    large = measure()
    assert large < max(small * 4, 0.5), f"목록 5개 {small:.3f}s → 15개 {large:.3f}s"

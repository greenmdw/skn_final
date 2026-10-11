"""P2 — 가벼운 결과 상태 조회(GET /session/{id}/result/status), 조건 일괄 반영(PATCH /slots), 응답 압축.

결과 화면은 후처리(요약·이유·가이드)가 끝날 때까지 몇 초마다 다시 읽는다. 전체 결과(GET /result)는 후보·리뷰 스냅샷을 조립하는
무거운 응답(로컬 약 0.84MB)이라, 폴링은 상태만 묻고 result_version 이 바뀌었을 때만 전체를 받는다. 일회용 DB 가 필요하다.
"""
from __future__ import annotations

import gzip
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app
    from src.services import recommendation_service
    from tests.test_list_history_http import _recommended_list, _signed_up


def _status(c, lid) -> dict:
    r = c.get(f"/session/{lid}/result/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_status_is_small_and_its_version_matches_the_full_result():
    c = _signed_up()
    lid, _revision_id, data = _recommended_list(c)

    state = _status(c, lid)
    assert state["status"] == "done" and state["run_id"] == data["run_id"]
    assert state["explanation_status"] == "ready" and state["postprocess_pending"] is False
    assert state["result_version"] and state["result_version"] == data["result_version"]
    assert set(state) == {"run_id", "status", "explanation_status", "postprocess_pending", "result_version", "error"}
    # 같은 결과를 다시 읽으면 같은 버전이다
    assert c.get(f"/session/{lid}/result").json()["result_version"] == state["result_version"]


def test_version_changes_when_the_configuration_changes():
    c = _signed_up()
    lid, _revision_id, data = _recommended_list(c)
    before = _status(c, lid)["result_version"]
    item = next(i for i in data["items"] if i["selected"])

    updated = c.patch(f"/session/{lid}/items/{item['item_id']}", json={"qty": 2})
    assert updated.status_code == 200, updated.text
    after = _status(c, lid)
    assert after["result_version"] != before
    assert after["result_version"] == updated.json()["result_version"]          # 교체·수량 응답에도 같은 버전이 실린다


def test_postprocess_pending_follows_reason_explanation_and_guide_states():
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    items = [i for i in data["items"] if i["selected"]]
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("UPDATE engine.recommendation_candidate SET checks=NULL, checks_status='pending' WHERE id=%s",
                     (items[0]["item_id"],))
        assert _status(c, lid)["postprocess_pending"] is True               # 가이드가 아직 오는 중
        # 사용자가 바꾼 부품(score 없음)의 가이드는 후처리가 채우지 않으므로 기다리지 않는다
        conn.execute("UPDATE engine.recommendation_candidate SET score=NULL, score_method_version=NULL WHERE id=%s",
                     (items[0]["item_id"],))
        assert _status(c, lid)["postprocess_pending"] is False
        conn.execute("UPDATE engine.recommendation_candidate SET reason=NULL, reason_status='pending' WHERE id=%s",
                     (items[1]["item_id"],))
        pending = _status(c, lid)
        assert pending["postprocess_pending"] is True
        full = c.get(f"/session/{lid}/result").json()
        assert full["result_version"] == pending["result_version"]


def test_status_of_a_running_run_and_ownership():
    c = _signed_up()
    lid, revision_id, _data = _recommended_list(c)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("UPDATE engine.recommendation_run SET status='running' WHERE revision_id=%s", (revision_id,))
        running = _status(c, lid)
        assert running["status"] == "running" and running["postprocess_pending"] is False
        conn.execute("UPDATE engine.recommendation_run SET status='failed' WHERE revision_id=%s", (revision_id,))
        failed = _status(c, lid)
        assert failed["status"] == "failed" and failed["error"]["code"] == "recommend_failed"
    # 다른 사용자는 남의 목록 상태를 볼 수 없다(GET /result 와 같은 소유권 검사)
    other = _signed_up()
    assert other.get(f"/session/{lid}/result/status").status_code == other.get(f"/session/{lid}/result").status_code
    assert other.get(f"/session/{lid}/result/status").status_code in (403, 404)


def test_batch_slot_patch_matches_individual_patches_and_checks_the_budget_once(monkeypatch):
    calls: list = []
    real = recommendation_service.assess_budget_feasibility

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(recommendation_service, "assess_budget_feasibility", counting)
    slots = [("purpose", "game"), ("budget_max", 1_500_000), ("priority", "value"), ("resolution", "QHD_165")]

    c = TestClient(app)
    one_by_one = c.post("/session").json()["list_id"]
    c.post(f"/session/{one_by_one}/category", json={"category": "computer", "mode": "build"})
    calls.clear()
    for field, value in slots:
        r = c.patch(f"/session/{one_by_one}/slot", json={"field": field, "value": value})
        assert r.status_code == 200, r.text
    individual_state, individual_calls = r.json(), len(calls)

    batched = c.post("/session").json()["list_id"]
    c.post(f"/session/{batched}/category", json={"category": "computer", "mode": "build"})
    calls.clear()
    r = c.patch(f"/session/{batched}/slots", json={"slots": [{"field": f, "value": v} for f, v in slots]})
    assert r.status_code == 200, r.text
    batched_state = r.json()

    assert len(calls) == 1 < individual_calls
    keep = ("fields", "next_question", "can_recommend", "budget_warning", "category", "mode")
    assert {k: batched_state.get(k) for k in keep} == {k: individual_state.get(k) for k in keep}
    assert c.get(f"/session/{batched}").json()["can_recommend"] == individual_state["can_recommend"]


def test_batch_slot_patch_validation_and_ownership():
    c = TestClient(app)
    lid = c.post("/session").json()["list_id"]
    assert c.patch(f"/session/{lid}/slots", json={"slots": []}).status_code == 422
    too_many = [{"field": f"f{i}", "value": i} for i in range(21)]
    assert c.patch(f"/session/{lid}/slots", json={"slots": too_many}).status_code == 422
    stranger = TestClient(app)
    single = stranger.patch(f"/session/{lid}/slot", json={"field": "budget_max", "value": 1})
    batch = stranger.patch(f"/session/{lid}/slots", json={"slots": [{"field": "budget_max", "value": 1}]})
    assert batch.status_code == single.status_code and batch.status_code >= 400


def test_large_responses_are_gzip_compressed_when_the_client_accepts_it():
    c = _signed_up()
    lid, _revision_id, data = _recommended_list(c)
    with c.stream("GET", f"/session/{lid}/result", headers={"Accept-Encoding": "gzip"}) as r:
        raw = b"".join(r.iter_raw())
        assert r.headers.get("content-encoding") == "gzip"
    assert len(gzip.decompress(raw)) > len(raw) * 3                         # JSON 이라 크게 줄어든다
    with c.stream("GET", f"/session/{lid}/result", headers={"Accept-Encoding": "identity"}) as r:
        assert "content-encoding" not in r.headers
    # 작은 응답은 압축하지 않는다
    small = c.get(f"/session/{lid}/result/status", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers

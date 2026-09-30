"""개발요청 10번 — 대화 목록(GET /lists 보강)과 견적 1개 : 견적서 N개(POST /lists/{id}/revisions).

견적서 하나 = 확정된 plan_revision 하나. 확정 뒤 새 견적서를 시작하면 조건을 복사한 draft revision 이 현재가 되고,
앞 견적서의 리포트·히스토리·알림은 revision 번호로 그대로 열린다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from tests.test_list_history_http import _recommended_list, _signed_up


def _recommend(c, lid: str) -> dict:
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return data


def _list_item(c, lid: str) -> dict:
    r = c.get("/lists")
    assert r.status_code == 200, r.text
    return next(item for item in r.json()["items"] if item["list_id"] == lid)


def test_lists_carry_what_the_conversation_panel_needs():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    item = _list_item(c, lid)
    assert item["stage"] == "results"
    assert item["first_message"] == "게임용 PC 맞추고 싶어요"
    assert "게임" in item["conditions_summary"] and "5,000,000원" in item["conditions_summary"]
    assert item["last_active_at"] and item["total"] is None and item["reports"] == []

    report = c.post(f"/lists/{lid}/confirm", json={"name": "첫 견적서"}).json()
    item = _list_item(c, lid)
    assert item["stage"] == "report"
    assert item["total"] == report["total"] and item["item_count"] == len(report["items"])
    assert [(r["revision_no"], r["name"]) for r in item["reports"]] == [(1, "첫 견적서")]


def test_second_quote_sheet_keeps_the_first_and_opens_both_by_number():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    first = c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).json()
    assert first["revision_no"] == 1
    assert c.post(f"/lists/{lid}/alert", json={"enabled": True, "target_amount": 1_000_000}).status_code == 200

    r = c.post(f"/lists/{lid}/revisions")
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["can_recommend"] is True                     # 조건이 복사됐다
    assert "새 견적서를 시작했어요" in state["messages"][-1]["text"]
    again = c.post(f"/lists/{lid}/revisions").json()           # 두 번 눌러도 새 draft 는 하나
    assert again["revision_id"] == state["revision_id"]

    # 새 견적서를 쓰는 동안에도 첫 견적서의 리포트·알림은 그대로 열린다
    item = _list_item(c, lid)
    assert item["stage"] == "conditions" and len(item["reports"]) == 1
    assert c.get(f"/lists/{lid}/report").json()["name"] == "견적서 A"
    assert c.get(f"/lists/{lid}/alert").json()["target_amount"] == 1_000_000

    r = c.post(f"/session/{lid}/message", json={"text": "조용한 쪽으로 다시 볼게요"})
    assert r.status_code == 200, r.text
    _recommend(c, lid)
    second = c.post(f"/lists/{lid}/confirm", json={"name": "견적서 B"}).json()
    assert second["revision_no"] == 2

    item = _list_item(c, lid)
    assert [(r["revision_no"], r["name"]) for r in item["reports"]] == [(1, "견적서 A"), (2, "견적서 B")]
    assert c.get(f"/lists/{lid}/report").json()["name"] == "견적서 B"          # 기본은 최근 확정본
    assert c.get(f"/lists/{lid}/report", params={"revision": 1}).json()["name"] == "견적서 A"
    assert c.get(f"/lists/{lid}/report", params={"revision": 3}).status_code == 404

    # 히스토리는 그 견적서를 쓰던 동안의 대화만
    first_texts = [e["text"] for e in c.get(f"/lists/{lid}/history", params={"revision": 1}).json()["events"]]
    second_texts = [e["text"] for e in c.get(f"/lists/{lid}/history", params={"revision": 2}).json()["events"]]
    assert "게임용 PC 맞추고 싶어요" in first_texts and "조용한 쪽으로 다시 볼게요" not in first_texts
    assert "조용한 쪽으로 다시 볼게요" in second_texts and "게임용 PC 맞추고 싶어요" not in second_texts


def test_new_quote_sheet_needs_the_owner():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.post(f"/lists/{lid}/confirm", json={"name": "소유"}).status_code == 200
    assert TestClient(app).post(f"/lists/{lid}/revisions").status_code == 401
    assert _signed_up().post(f"/lists/{lid}/revisions").status_code == 404

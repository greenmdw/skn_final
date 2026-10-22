"""개발요청 10번 — 견적서(revision) 하나만 삭제·이름 바꾸기.

`DELETE /lists/{id}/reports/{revision_no}` · `PATCH /lists/{id}/reports/{revision_no}`.
대화(list) 전체나 다른 견적서는 그대로 두고, 지우는 게 지금 작업 중인(current) 견적서일 때만
current를 다른 곳(남은 확정본, 없으면 새 draft)으로 옮긴다. 일회용 DB 가 필요하다."""
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


def _confirm_second_report(c, lid: str, name: str) -> dict:
    """현재 확정본을 두고 새 견적서를 하나 더 확정한다."""
    assert c.post(f"/lists/{lid}/revisions").status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "다시 볼게요"})
    assert r.status_code == 200, r.text
    _recommend(c, lid)
    r = c.post(f"/lists/{lid}/confirm", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_rename_changes_only_that_reports_name():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "원래 이름"}).status_code == 200

    r = c.patch(f"/lists/{lid}/reports/1", json={"name": "바꾼 이름"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "바꾼 이름"

    # 대화 이름(plan.name)은 그대로 — 견적서 이름과 별개다.
    item = _list_item(c, lid)
    assert [(rr["revision_no"], rr["name"]) for rr in item["reports"]] == [(1, "바꾼 이름")]
    assert c.get(f"/lists/{lid}/report", params={"revision": 1}).json()["name"] == "바꾼 이름"


def test_rename_requires_the_owner_and_a_real_report():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.post(f"/lists/{lid}/confirm", json={"name": "소유"}).status_code == 200

    assert TestClient(app).patch(f"/lists/{lid}/reports/1", json={"name": "x"}).status_code == 401
    assert _signed_up().patch(f"/lists/{lid}/reports/1", json={"name": "x"}).status_code == 404
    assert owner.patch(f"/lists/{lid}/reports/99", json={"name": "x"}).status_code == 404


def test_delete_a_non_current_report_leaves_the_rest_untouched():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).status_code == 200
    second = _confirm_second_report(c, lid, "견적서 B")
    assert second["revision_no"] == 2

    # 지금 current는 견적서 B(2번) — A(1번)는 current가 아니므로 지워도 current는 안 바뀐다.
    before = c.get(f"/session/{lid}").json()["revision_id"]
    r = c.delete(f"/lists/{lid}/reports/1")
    assert r.status_code == 200, r.text
    assert r.json()["revision_id"] == before

    item = _list_item(c, lid)
    assert [rr["revision_no"] for rr in item["reports"]] == [2]
    assert item["stage"] == "report"          # current(견적서 B)는 그대로 확정 상태
    assert c.get(f"/lists/{lid}/report", params={"revision": 1}).status_code == 404
    assert c.get(f"/lists/{lid}/report", params={"revision": 2}).json()["name"] == "견적서 B"


def test_delete_the_current_report_falls_back_to_the_remaining_one():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).status_code == 200
    second = _confirm_second_report(c, lid, "견적서 B")
    assert second["revision_no"] == 2

    # current(견적서 B, 2번) 자체를 지운다 — 남은 A(1번)로 current가 넘어가야 한다.
    r = c.delete(f"/lists/{lid}/reports/2")
    assert r.status_code == 200, r.text

    item = _list_item(c, lid)
    assert [rr["revision_no"] for rr in item["reports"]] == [1]
    assert item["stage"] == "report"
    assert c.get(f"/lists/{lid}/report").json()["name"] == "견적서 A"   # 기본(revision 생략)이 이제 A
    assert c.get(f"/lists/{lid}/report", params={"revision": 2}).status_code == 404


def test_deleting_the_only_report_reverts_to_a_draft_with_the_same_build():
    c = _signed_up()
    lid, _revision_id, data = _recommended_list(c)
    confirmed = c.post(f"/lists/{lid}/confirm", json={"name": "유일한 견적서"})
    assert confirmed.status_code == 200

    r = c.delete(f"/lists/{lid}/reports/1")
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["can_recommend"] is True

    item = _list_item(c, lid)
    assert item["reports"] == []
    # 8번(clone_revision)과 같은 메커니즘 — 재추천 없이 바로 그 구성을 들고 있는 draft.
    assert item["stage"] == "results"
    result = c.get(f"/session/{lid}/result").json()
    assert result["status"] == "done"
    assert len(result["items"]) == len(data["items"])
    assert c.get(f"/lists/{lid}/report").status_code == 404


def test_delete_requires_the_owner_and_a_real_report():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.post(f"/lists/{lid}/confirm", json={"name": "소유"}).status_code == 200

    assert TestClient(app).delete(f"/lists/{lid}/reports/1").status_code == 401
    assert _signed_up().delete(f"/lists/{lid}/reports/1").status_code == 404
    assert owner.delete(f"/lists/{lid}/reports/99").status_code == 404


def test_deleted_report_cannot_be_deleted_or_renamed_again():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).status_code == 200
    _confirm_second_report(c, lid, "견적서 B")

    assert c.delete(f"/lists/{lid}/reports/1").status_code == 200
    assert c.delete(f"/lists/{lid}/reports/1").status_code == 404
    assert c.patch(f"/lists/{lid}/reports/1", json={"name": "다시"}).status_code == 404

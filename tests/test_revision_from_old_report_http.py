"""개발요청 14번 — 예전 견적서에서도 "견적 수정하기".

`POST /lists/{id}/revisions`에 `from_revision_no`를 주면 가장 최근(current)이 아니라 그
번호의 확정 견적서를 원본으로 새 draft를 만든다. 이미 작성 중인 draft가 있어도 버리고
새로 복사한다(문서 권장 동작). 일회용 DB 가 필요하다."""
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


def _confirm_another_report(c, lid: str, name: str, *, priority_text: str) -> dict:
    assert c.post(f"/lists/{lid}/revisions").status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": priority_text})
    assert r.status_code == 200, r.text
    _recommend(c, lid)
    r = c.post(f"/lists/{lid}/confirm", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_from_revision_no_copies_that_report_not_the_current_one():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    first = c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).json()
    assert first["revision_no"] == 1
    first_gpu_name = next(i["product"]["name"] for i in first["items"] if i["slot"] == "GPU")

    second = _confirm_another_report(c, lid, "견적서 B", priority_text="조용한 쪽으로 다시 볼게요")
    assert second["revision_no"] == 2

    # current는 지금 견적서 B(2번, confirmed) — from_revision_no=1 을 주면 A를 원본으로 삼아야 한다.
    r = c.post(f"/lists/{lid}/revisions", json={"from_revision_no": 1})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["can_recommend"] is True
    assert "견적서 1" in state["messages"][-1]["text"]

    result = c.get(f"/session/{lid}/result").json()
    assert result["status"] == "done"
    gpu_now = next(i["product"]["name"] for i in result["items"] if i["slot"] == "GPU")
    assert gpu_now == first_gpu_name          # A의 구성 그대로 — B가 아니다

    # 두 확정 견적서는 그대로 남아 있다.
    assert c.get(f"/lists/{lid}/report", params={"revision": 1}).json()["name"] == "견적서 A"
    assert c.get(f"/lists/{lid}/report", params={"revision": 2}).json()["name"] == "견적서 B"


def test_from_revision_no_discards_an_in_progress_draft_from_a_different_source():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    first = c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).json()
    second = _confirm_another_report(c, lid, "견적서 B", priority_text="조용한 쪽으로 다시 볼게요")

    # B를 원본으로 작성 중인 draft를 하나 만들어 둔다(아직 미확정).
    assert c.post(f"/lists/{lid}/revisions").status_code == 200
    draft_state = c.get(f"/session/{lid}").json()
    draft_revision_id = draft_state["revision_id"]

    # A(1번)를 원본으로 지정하면, B에서 만든 draft는 버려지고 A 기준 새 draft가 된다.
    r = c.post(f"/lists/{lid}/revisions", json={"from_revision_no": 1})
    assert r.status_code == 200, r.text
    new_state = r.json()
    assert new_state["revision_id"] != draft_revision_id

    gpu_a = next(i["product"]["name"] for i in first["items"] if i["slot"] == "GPU")
    result = c.get(f"/session/{lid}/result").json()
    gpu_now = next(i["product"]["name"] for i in result["items"] if i["slot"] == "GPU")
    assert gpu_now == gpu_a


def test_from_revision_no_rejects_unconfirmed_or_missing_or_unowned():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).status_code == 200

    # 존재하지 않는 번호
    assert owner.post(f"/lists/{lid}/revisions", json={"from_revision_no": 99}).status_code == 404
    # 확정 안 된 draft 번호(지금 current, revision_no=1 복사 뒤 새 draft는 2번이지만 미확정)
    assert owner.post(f"/lists/{lid}/revisions").status_code == 200
    assert owner.post(f"/lists/{lid}/revisions", json={"from_revision_no": 2}).status_code == 404
    # 소유자가 아니면 404
    assert _signed_up().post(f"/lists/{lid}/revisions", json={"from_revision_no": 1}).status_code == 404


def test_from_revision_no_on_a_deleted_report_is_not_found():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "견적서 A"}).status_code == 200
    _confirm_another_report(c, lid, "견적서 B", priority_text="조용한 쪽으로 다시 볼게요")

    assert c.delete(f"/lists/{lid}/reports/1").status_code == 200
    assert c.post(f"/lists/{lid}/revisions", json={"from_revision_no": 1}).status_code == 404

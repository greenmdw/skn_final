"""받은 견적 분석은 용도가 있어야 한다(게임이면 해상도도). 다른 테스트는 이 규칙을 끄고(conftest) 이 파일만 실제 규칙으로 돈다."""
from __future__ import annotations

import json
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.enforce_conditions, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from src.auth import ratelimit

TEXT = "CPU: AMD Ryzen 5 7500F 238,000원\nGPU: NVIDIA GeForce RTX 5060 Ti 8GB 560,000원"


@pytest.fixture()
def client():
    ratelimit.reset_all()
    with TestClient(app) as c:
        yield c


def _draft(client, conditions=None):
    data = {"text": TEXT, **({"conditions": json.dumps(conditions)} if conditions else {})}
    r = client.post("/pc/review-drafts", data=data)
    assert r.status_code == 201, r.text
    return r.json()


def test_analysis_needs_a_purpose(client):
    draft = _draft(client)
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "purpose_required"


def test_a_game_purpose_also_needs_a_resolution(client):
    draft = _draft(client, {"purpose": "game"})
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "resolution_required"
    patched = client.patch(f"/pc/review-drafts/{draft['draft_id']}/conditions", json={"expected_version": draft["version"], "conditions": {"resolution": "QHD_165"}})
    assert patched.status_code == 200
    assert client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={}).status_code == 200


def test_other_purposes_do_not_need_a_resolution_nor_a_priority(client):
    draft = _draft(client, {"purpose": "office"})
    assert client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis", json={}).status_code == 200


def test_creating_a_draft_without_conditions_is_still_allowed(client):
    """내 현재 PC 등록처럼 점검 없이 견적만 읽는 곳이 조건 없이 초안을 만든다 — 규칙은 분석에만 건다."""
    assert _draft(client)["conditions"] == {}


def test_chat_reanalysis_without_a_purpose_explains_instead_of_analysing(client):
    draft = _draft(client)
    r = client.post(f"/pc/reviews/{draft['draft_id']}/messages", json={"text": "다시 분석해줘"})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] is None and "용도" in body["reply"]

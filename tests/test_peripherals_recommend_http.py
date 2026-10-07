"""개발요청 6번 — 주변기기 추천 API (`POST /session/{id}/peripherals/recommend`).

C안(독립 엔드포인트) + 선택적 PC 맥락 결합: PC 견적 대화 없이 바로 호출할 수 있고,
`pc_list_id`를 주면 그 PC 견적의 해상도를 묶어 모니터 교차검사를 추가로 켠다. 추천
엔진(`run_peripherals`/`peripheral_payload`)은 이미 있는 걸 그대로 쓴다 — 이 테스트는
그 엔진을 세션 API로 잇는 얇은 서비스 계층만 검사한다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"peripherals-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "주변기기", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _new_session(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _pc_list(c, *, resolution: str = "QHD_165") -> str:
    """해상도까지 답한 완료된 PC(컴퓨터) 견적 — pc_context 테스트가 쓴다."""
    lid = _new_session(c)
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    for qid, value in (("q_purpose", "게임"), ("q_resolution", resolution),
                       ("q_budget_max", 2_000_000), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return lid


def test_standalone_recommend_needs_no_pc_quote():
    """ChoosePage "/peripherals" 입구 — PC 견적 없이 바로 추천받는다."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend",
               json={"kinds": ["keyboard"], "purpose": "game", "priority": "quiet"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] in ("ready", "empty")
    if data["status"] == "ready":
        item = next(i for i in data["items"] if i["kind"] == "keyboard")
        assert item["product"]["name"]
        assert item["reason"]["status"] == "ready"
        assert item["price"] > 0


def test_unknown_kind_is_rejected_by_schema():
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["gpu"]})
    assert r.status_code == 422


def test_empty_kinds_is_rejected():
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": []})
    assert r.status_code == 422


def test_monitor_without_pc_context_uses_default_resolution_and_may_be_empty():
    """pc_context 가 없으면 PC 쪽 정보 없이도 동작한다 — 카탈로그에 그 해상도 모니터가
    없으면(지금 FHD_144는 없다) 조용히 empty 로 답한다, 500이 아니다."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] in ("ready", "empty")
    assert all(i["checks"] == [] or all(c["axis"] != "monitor_resolution" for c in i["checks"])
               for i in data["items"])   # pc_context 없이는 교차검사 자체가 안 돈다


def test_monitor_without_resolution_defaults_to_qhd_and_is_not_empty():
    """해상도를 말하지 않아도 모니터가 빈 채로 나오지 않는다 — 기본값이 QHD_165라 카탈로그에 후보가 있다
    (FHD_144 기본값일 때는 맞는 모니터가 없어 첫 요청이 항상 비었다)."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready", data
    item = next(i for i in data["items"] if i["kind"] == "monitor")
    rows = {row["key"]: row["value"] for row in item["requirement"]}
    assert rows.get("resolution_class") == "QHD"
    assert "QHD" in rows.get("resolution_assumed", "")


def test_pc_context_adds_monitor_cross_check_and_reuses_its_resolution():
    """pc_list_id 를 주면: 1) 요청에 resolution 을 안 줘도 그 PC 견적의 해상도를 이어받고,
    2) monitor_resolution 교차검사가 추가된다(개발요청 6번 — C안 + 선택적 PC 맥락 결합)."""
    c = _signed_up()
    pc_lid = _pc_list(c, resolution="QHD_165")

    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend",
               json={"kinds": ["monitor"], "pc_list_id": pc_lid})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready", data   # QHD_165 는 카탈로그에 매칭 후보가 있다
    item = next(i for i in data["items"] if i["kind"] == "monitor")
    axes = {c["axis"]: c["state"] for c in item["checks"]}
    assert axes.get("monitor_resolution") == "ok"


def test_pc_context_is_ignored_when_pc_list_id_is_not_owned_by_caller():
    """다른 사람의 PC 견적을 pc_list_id 로 넣어도 에러 없이 조용히 무시한다 — 독립 추천처럼 동작."""
    owner = _signed_up()
    pc_lid = _pc_list(owner, resolution="QHD_165")

    stranger = _signed_up()
    lid = _new_session(stranger)
    r = stranger.post(f"/session/{lid}/peripherals/recommend",
                       json={"kinds": ["monitor"], "pc_list_id": pc_lid})
    assert r.status_code == 200, r.text
    data = r.json()
    for item in data["items"]:
        assert all(c["axis"] != "monitor_resolution" for c in item["checks"])


def test_explicit_resolution_overrides_pc_context():
    c = _signed_up()
    pc_lid = _pc_list(c, resolution="QHD_165")
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend",
               json={"kinds": ["monitor"], "pc_list_id": pc_lid, "resolution": "4K"})
    assert r.status_code == 200, r.text
    data = r.json()
    if data["status"] == "ready":
        item = next(i for i in data["items"] if i["kind"] == "monitor")
        axes = {c["axis"]: c["detail"] for c in item["checks"]}
        # PC는 QHD인데 모니터 요구사양은 명시한 4K로 갔다 — 둘이 다르면 fail, 교차검사 자체는 여전히 돈다.
        assert "monitor_resolution" in axes

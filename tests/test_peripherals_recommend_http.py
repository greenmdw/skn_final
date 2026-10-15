"""개발요청 6번 — 주변기기 추천 API (`POST /session/{id}/peripherals/recommend`).

C안(독립 엔드포인트) + 선택적 PC 맥락 결합: PC 견적 대화 없이 바로 호출할 수 있고,
`pc_list_id`를 주면 그 PC 견적의 해상도를 묶어 모니터 교차검사를 추가로 켠다. 추천
엔진(`run_peripherals`/`peripheral_payload`)은 이미 있는 걸 그대로 쓴다 — 이 테스트는
그 엔진을 세션 API로 잇는 얇은 서비스 계층만 검사한다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os
from uuid import UUID, uuid4

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
               json={"kinds": ["keyboard"], "purposes": ["game"], "situations": ["quiet_place"]})
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


def test_monitor_without_pc_context_skips_cross_check():
    """pc_context 가 없으면 PC 쪽 정보 없이도 동작하고(500 이 아니다), 모니터↔PC 교차검사는 돌지 않는다."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] in ("ready", "empty")
    assert all(i["checks"] == [] or all(c["axis"] != "monitor_resolution" for c in i["checks"])
               for i in data["items"])   # pc_context 없이는 교차검사 자체가 안 돈다


def test_monitor_without_pc_is_not_filtered_by_resolution_and_says_so():
    """PC 견적 없이 모니터를 고르면 해상도·주사율로 거르지 않고(4K 도 후보), 요구사양 행과 채팅 유의사항으로
    PC 사양을 모르고 골랐다고 알린다(QA PQA-001)."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready", data
    item = next(i for i in data["items"] if i["kind"] == "monitor")
    rows = {row["key"]: row["value"] for row in item["requirement"]}
    assert "resolution_class" not in rows and "refresh_min_hz" not in rows
    assert "PC" in rows.get("resolution_assumed", "")
    assert [n["code"] for n in data["notices"]][:1] == ["pc_unknown"]


def test_monitor_without_pc_can_recommend_4k_when_asked():
    """"4K 모니터"(고해상도)를 말하면 PC 견적이 없어도 해상도로 거르지 않은 채 고해상도 선호가 요구사양에 들어간다(QA PQA-001·007)."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend",
               json={"kinds": ["monitor"], "stated": {"monitor": ["high_resolution"]}})
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "monitor")
    assert item["requirement"] and any(row["key"] == "resolution_h" for row in item["requirement"])


def test_alternatives_carry_product_ids_for_choosing_them():
    """다른 선택지에도 제품 식별자·브랜드·이미지·링크가 실려 화면이 1위 대신 담을 수 있다(QA PQA-024)."""
    c = _signed_up()
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["mouse"]})
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "mouse")
    assert item["alternatives"], item
    assert all(alt["variant_id"] for alt in item["alternatives"])
    assert all(alt["brand"] for alt in item["alternatives"])


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


def test_pc_list_purpose_is_carried_into_the_peripheral_request(monkeypatch):
    """pc_list_id 를 주면 그 PC 견적의 용도("게임" → game)가 요청 바디의 purpose 없이도 이어진다."""
    from src.services import review_ranking

    seen: list[dict] = []
    original = review_ranking.score_peripheral_candidates

    def spy(conn, candidates, values, **kwargs):
        seen.append(dict(values))
        return original(conn, candidates, values, **kwargs)

    monkeypatch.setattr(review_ranking, "score_peripheral_candidates", spy)
    c = _signed_up()
    pc_lid = _pc_list(c, resolution="QHD_165")
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"], "pc_list_id": pc_lid})
    assert r.status_code == 200, r.text
    assert seen and seen[0]["purpose"] == "game"


def test_pc_context_carries_the_selected_gpu_specs(monkeypatch):
    """pc_list_id 를 주면 그 PC 견적에서 선택된 GPU 의 스펙(단자 값 포함)이 pc_context["gpu_specs"] 로 실린다(B-9)."""
    from src.db import get_conn
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.services import peripherals_service

    seen: list = []
    original = peripherals_service.recommend

    def spy(conn, body, pc_context):
        seen.append(pc_context)
        return original(conn, body, pc_context)

    monkeypatch.setattr(peripherals_service, "recommend", spy)
    c = _signed_up()
    pc_lid = _pc_list(c)
    lid = _new_session(c)
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": ["monitor"], "pc_list_id": pc_lid})
    assert r.status_code == 200, r.text
    gpu_specs = seen[0]["gpu_specs"]

    with get_conn() as conn:
        revision = PlanRepo(conn).get_current_revision(UUID(pc_lid))
        erepo = EngineRepo(conn)
        run = erepo.get_latest_run_state(revision["id"])
        gpu = next(x for x in erepo.get_candidates(run["id"]) if x["product_type"] == "gpu" and x["selected"])
    assert gpu_specs is not None
    assert gpu_specs.get("vram_gb") is not None   # GPU 스펙 행이 실렸다(다른 부품 스펙이 아니다)
    assert gpu["variant_id"]


def test_pc_context_gpu_specs_is_none_without_a_completed_recommendation():
    """추천을 아직 안 돌린 PC 견적은 gpu_specs 가 None 이다 — 단자 검사는 확인 불가로 남는다."""
    from src.db import get_conn
    from src.services import peripherals_service

    c = _signed_up()
    lid = _new_session(c)
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/answer", json={"question_id": "q_resolution", "selected": ["QHD_165"]})
    assert r.status_code == 200, r.text
    with get_conn() as conn:
        from src.repo.plan_repo import PlanRepo
        revision = PlanRepo(conn).get_current_revision(UUID(lid))
        assert peripherals_service._selected_gpu_specs(conn, revision["id"]) is None

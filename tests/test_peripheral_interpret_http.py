"""POST /peripherals/interpret — 견적 문장 해석 API(견적 입력 설계 4장)와, 그 결과가 추천에 연결되는지.

해석 API 자체는 DB 가 필요 없다. 추천 연결(`/session/{id}/peripherals/recommend`)은 일회용 DB 가 필요하다.
언어 모델은 부르지 않는다 — 에이전트가 꺼져 있어(기본값) 단어 규칙으로 읽는다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.auth import ratelimit
from src.engine import peripheral_rules as pr

DSN = os.getenv("DATABASE_URL")
needs_db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import app  # noqa: E402
from src.services import peripheral_interpret_service  # noqa: E402


@pytest.fixture()
def client():
    peripheral_interpret_service.clear_cache()
    ratelimit.reset_all()
    return TestClient(app)


def _interpret(client, text, **extra):
    r = client.post("/peripherals/interpret", json={"text": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_interpret_reads_sentence_into_listed_values(client):
    data = _interpret(client, "마우스 들고 다닐 때가 많고 사무용으로 쓰려고, 무선으로 5만원 이하")
    assert data["source"] == "rules" and data["needs_kind"] is False and data["truncated"] is False
    interp = data["interpretation"]
    assert interp["kinds"] == ["mouse"]
    assert interp["stated"] == {"mouse": ["wireless"]}
    assert interp["budget"] == {"mouse": 50000}
    resolved = data["resolved"]["mouse"]
    assert [c["condition"] for c in resolved["filters"]] == ["wireless"]
    assert {"office", "portable"} <= {p["code"] for p in resolved["purposes"]}
    assert all(c["label"] for c in resolved["preferences"])


def test_interpret_without_kind_asks_for_a_card_then_continues_with_it(client):
    first = _interpret(client, "조용한 걸로 블루투스 되는 거")
    assert first["needs_kind"] is True and first["resolved"] == {}
    second = _interpret(client, "조용한 걸로 블루투스 되는 거", previous=first["interpretation"], kinds=["keyboard"])
    assert second["needs_kind"] is False
    assert second["interpretation"]["kinds"] == ["keyboard"]
    assert second["interpretation"]["stated"] == {"keyboard": ["bluetooth"]}
    assert "quiet_place" in second["interpretation"]["situations"]


def test_interpret_adds_to_previous_interpretation(client):
    first = _interpret(client, "키보드 사무실에서 써요")
    second = _interpret(client, "블루투스도 되면 좋겠어요", previous=first["interpretation"])
    assert second["interpretation"]["kinds"] == ["keyboard"]            # 이전 종류가 남는다
    assert "quiet_place" in second["interpretation"]["situations"]


def test_interpret_ignores_values_outside_the_lists_in_previous(client):
    data = _interpret(client, "마우스", previous={"kinds": ["gpu"], "purposes": ["hack"], "stated": {"mouse": ["x"]}})
    assert data["interpretation"]["kinds"] == ["mouse"]
    assert data["interpretation"]["purposes"] == [] and data["interpretation"]["stated"] == {}


def test_interpret_rejects_empty_and_oversized_input(client):
    assert client.post("/peripherals/interpret", json={"text": ""}).status_code == 422
    assert client.post("/peripherals/interpret", json={"text": "가" * 2001}).status_code == 422
    assert client.post("/peripherals/interpret", json={"text": "마우스", "kinds": ["gpu"]}).status_code == 422


def test_interpret_truncates_sentences_over_the_configured_limit(client):
    limit = pr.interpretation_settings()["max_chars"]
    data = _interpret(client, "마우스 " + "가" * (limit + 50))
    assert data["truncated"] is True


def test_interpret_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(pr, "interpretation_settings", lambda rules=None: {"max_chars": 300, "cache_size": 8, "per_minute": 2})
    from src.routers import peripherals as router

    monkeypatch.setattr(router, "interpretation_settings", pr.interpretation_settings)
    statuses = [client.post("/peripherals/interpret", json={"text": "마우스"}).status_code for _ in range(4)]
    assert statuses[:2] == [200, 200]
    assert statuses[2:] == [429, 429]


# ── 추천 연결 ────────────────────────────────────────────────────────────
def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"intent-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "견적입력", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _recommend(c, **body):
    lid = c.post("/session").json()["list_id"]
    r = c.post(f"/session/{lid}/peripherals/recommend", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@needs_db
def test_recommend_stated_filter_removes_non_matching_products():
    c = _signed_up()
    data = _recommend(c, kinds=["mouse"], stated={"mouse": ["wireless"]})
    assert data["status"] == "ready", data
    item = data["items"][0]
    assert any(row["key"] == "connectivity_wireless" and row["value"] == "예" for row in item["requirement"])
    assert data["ignored_inputs"] == []


@needs_db
def test_recommend_purpose_changes_preferences_but_never_removes_products():
    c = _signed_up()
    plain = _recommend(c, kinds=["mouse"])
    portable = _recommend(c, kinds=["mouse"], purposes=["fps"], situations=["portable"])
    assert plain["status"] == portable["status"] == "ready"
    keys = {row["key"] for row in portable["items"][0]["requirement"]}
    assert {"polling_hz_max", "weight_g"} <= keys
    assert plain["items"][0]["requirement"] == []


@needs_db
def test_recommend_reports_ignored_inputs_instead_of_failing():
    c = _signed_up()
    data = _recommend(c, kinds=["mouse"], purposes=["office", "no_such_purpose"],
                      stated={"mouse": ["wireless", "no_such_condition"]})
    assert data["status"] == "ready"
    assert data["ignored_inputs"] == ["no_such_condition", "no_such_purpose"]


@needs_db
def test_recommend_kind_budget_filters_by_price_and_explains_when_nothing_fits():
    c = _signed_up()
    cheap = _recommend(c, kinds=["mouse"], kind_budget={"mouse": 60000})
    assert cheap["status"] == "ready"
    assert cheap["items"][0]["price"] <= 60000
    none = _recommend(c, kinds=["mouse"], kind_budget={"mouse": 1})
    assert none["status"] == "empty"
    assert "예산" in none["empty"][0]["reason"]


@needs_db
def test_recommend_legacy_inputs_still_map_to_quiet_preference():
    """화면이 새 입력으로 바뀌기 전까지 예전 입력(noise_sensitive, priority)도 같은 선호로 풀린다."""
    c = _signed_up()
    old = _recommend(c, kinds=["keyboard"], noise_sensitive=True)
    new = _recommend(c, kinds=["keyboard"], situations=["quiet_place"])
    assert old["items"][0]["requirement"] == new["items"][0]["requirement"] != []


@needs_db
def test_recommend_still_passes_pc_conditions_to_review_scoring(monkeypatch):
    """리뷰 점수는 PC 견적 조건(purpose·priority·noise_sensitive)을 읽는다. 견적 입력으로 바꾸면서 이 값이
    사라지면 리뷰 가중치가 조용히 달라진다 — 그대로 넘어가는지 고정한다."""
    from src import schemas
    from src.db import get_conn
    from src.services import peripherals_service, review_ranking

    seen: dict = {}
    original = review_ranking.score_peripheral_candidates

    def spy(conn, candidates, values, **kwargs):
        seen.update(values)
        return original(conn, candidates, values, **kwargs)

    monkeypatch.setattr(review_ranking, "score_peripheral_candidates", spy)
    body = schemas.PeripheralsRecommendIn(kinds=["keyboard"], purpose="game", priority="quiet", noise_sensitive=True)
    with get_conn() as conn:
        peripherals_service.recommend(conn, body, None)
    assert (seen["purpose"], seen["priority"], seen["noise_sensitive"]) == ("game", "quiet", True)


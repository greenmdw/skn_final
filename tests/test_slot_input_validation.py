"""U-05 — 슬롯/예산 입력 검증. 예산은 10만~2천만원, 알 수 없는 필드는 거절한다."""
from __future__ import annotations

import os

import pytest

from src.engine import slot_rules

DSN = os.getenv("DATABASE_URL")


@pytest.mark.parametrize("value, expected", [
    (100_000, 100_000), (20_000_000, 20_000_000), ("1,500,000", 1_500_000), (1_500_000.0, 1_500_000), (None, None),
])
def test_normalize_budget_accepts(value, expected):
    assert slot_rules.normalize_budget(value) == expected


@pytest.mark.parametrize("value", [-1, 0, 99_999, 20_000_001, 10**12, "많이", "", True, 1.5e6 + 0.5, float("nan"), [1]])
def test_normalize_budget_rejects(value):
    with pytest.raises(ValueError):
        slot_rules.normalize_budget(value)


def test_chat_extraction_drops_out_of_range_budget():
    assert "budget_max" not in slot_rules.extract("computer", "예산 1억원으로 게임용 PC")
    assert "budget_max" not in slot_rules.extract("computer", "예산 5만원")
    assert slot_rules.extract("computer", "예산 150만원 게임용")["budget_max"] == 1_500_000


def test_agent_tool_rejects_out_of_range_budget():
    from src.agent import conditions_agent as ca
    from src.categories import load_category
    cat_def = load_category("computer")
    state = ca.ConditionDraft("computer", cat_def, {}, lambda v: [], lambda v: None)
    assert "오류" in state.set("budget_max", "1억원")
    assert "budget_max" not in state.patches
    assert "반영" in state.set("budget_max", "150만원")


if DSN:
    from fastapi.testclient import TestClient
    from src.api import app

    @pytest.fixture()
    def client():
        with TestClient(app) as c:
            yield c

    def _session(client):
        lid = client.post("/session").json()["list_id"]
        assert client.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
        return lid

    @pytest.mark.db
    @pytest.mark.parametrize("value", [-5, 0, 50_000, 30_000_000, 10**15, "많이"])
    def test_patch_slot_rejects_bad_budget(client, value):
        lid = _session(client)
        r = client.patch(f"/session/{lid}/slot", json={"field": "budget_max", "value": value})
        assert r.status_code == 422, r.text
        # 거절됐으니 저장되지 않아 결과 조회도 깨지지 않는다
        assert client.get(f"/session/{lid}").status_code == 200

    @pytest.mark.db
    def test_patch_slot_rejects_unknown_field(client):
        lid = _session(client)
        r = client.patch(f"/session/{lid}/slot", json={"field": "evil_field", "value": 1})
        assert r.status_code == 422

    @pytest.mark.db
    @pytest.mark.parametrize("field, value", [
        ("budget_max", 100_000), ("budget_max", 2_000_000), ("budget_max", 20_000_000),
        ("purpose", "game"), ("priority", "value"),
    ])
    def test_patch_slot_accepts_valid(client, field, value):
        lid = _session(client)
        assert client.patch(f"/session/{lid}/slot", json={"field": field, "value": value}).status_code == 200

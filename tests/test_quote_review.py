"""견적 점검 — 타사 견적 호환 검사(CHK-04)와 비교 분석 결과 저장(CHK-09).

호환 검사는 추천엔진 7단계 함수(pc_compat_details)를 그대로 부르는지, 저장은 추천 입력·lock_version 을
건드리지 않는지, 소유자만 읽는지를 본다. 앞 절은 DB 없이, 뒤 절은 일회용 테스트 DB(HTTP)로 돈다.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.categories import load_category
from src.errors import ValidationFailed
from src.services import quote_review_service as qrs

SLOTS = load_category("computer")["slot_structure"]


@pytest.fixture(autouse=True)
def _synthetic_catalog(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")


def _compat(specs: dict) -> dict:
    return qrs.analyze(specs)["compat"]


def _by_axis(compat: dict) -> dict[str, dict]:
    return {c["axis"]: c for c in compat["checks"]}


# ── CHK-04: 7단계 검사를 견적에 그대로 적용 ─────────────────────────────────────────

def test_a_cpu_and_board_with_different_sockets_is_a_confirmed_incompatibility():
    compat = _compat({"CPU": "AMD Ryzen 5 7500F", "메인보드": "MSI B450 TOMAHAWK"})   # AM5 CPU 를 AM4 보드에
    assert "socket" in compat["incompatible"]
    row = _by_axis(compat)["socket"]
    assert row["state"] == "fail" and "AM5" in row["detail"] and "AM4" in row["detail"]
    assert compat["link_check"]["socket"] == "fail"


def test_a_matching_platform_passes_the_socket_check():
    compat = _compat({"CPU": "AMD Ryzen 5 7500F", "메인보드": "MSI B650 TOMAHAWK"})
    assert _by_axis(compat)["socket"]["state"] == "ok"
    assert "socket" not in compat["incompatible"]


def test_missing_specs_are_unknown_not_incompatible():
    """정보 없음 ≠ 비호환 — 스펙을 못 읽은 부품은 "확인 못 함"으로 남고 실패로 단정하지 않는다."""
    compat = _compat({"GPU": "제가 만든 그래픽카드", "케이스": "이름 모를 케이스"})
    rows = _by_axis(compat)
    assert rows["gpu_len"]["state"] == "unknown"
    assert compat["incompatible"] == []


def test_checks_for_parts_missing_from_the_quote_are_skipped_with_a_quote_specific_reason():
    compat = _compat({"CPU": "AMD Ryzen 5 7500F"})
    row = _by_axis(compat)["gpu_len"]
    assert row["state"] == "skipped"
    assert "견적에" in row["detail"] and "바뀌는" not in row["detail"]


def test_the_result_uses_the_engine_check_labels_and_counts_every_state():
    compat = _compat({"CPU": "AMD Ryzen 5 7500F", "메인보드": "MSI B450 TOMAHAWK"})
    assert sum(compat["summary"].values()) == len(compat["checks"])
    assert all(c["label"] for c in compat["checks"])


def test_the_matching_table_comes_with_the_analysis():
    review = qrs.analyze({"CPU": "i5-14400F"})
    assert [r["part"] for r in review["parts"]] == ["CPU"]
    assert review["input"]["current_specs"] == {"CPU": "i5-14400F"}
    assert len(review["input"]["input_hash"]) == 64


def test_the_same_quote_has_the_same_hash_regardless_of_slot_spelling_or_blanks():
    a = qrs.analyze({"그래픽카드": " RTX 3060 ", "CPU": "i5-14400F", "쿨러": "  "})
    b = qrs.analyze({"GPU": "RTX 3060", "CPU": "i5-14400F"})
    assert a["input"] == b["input"]


def test_an_empty_quote_is_rejected():
    with pytest.raises(ValidationFailed):
        qrs.analyze({})
    with pytest.raises(ValidationFailed):
        qrs.analyze({"CPU": "   "})


# ── CHK-09: 세션에 저장 (HTTP, 일회용 DB) ────────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
db_only = pytest.mark.skipif(not DSN, reason="requires disposable test database")

QUOTE = {"current_specs": {"CPU": "AMD Ryzen 5 7500F", "메인보드": "MSI B450 TOMAHAWK"}}


@pytest.fixture()
def client():
    from src.api import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def raw_conn():
    conn = psycopg.connect(DSN, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def _lock_version(raw_conn, list_id: str) -> int:
    return raw_conn.execute(
        "SELECT pr.lock_version FROM planning.plan p JOIN planning.plan_revision pr ON pr.id=p.current_revision_id "
        "WHERE p.id=%s", (list_id,)).fetchone()[0]


@db_only
def test_a_review_is_saved_in_a_new_session_and_can_be_read_back(client):
    res = client.post("/pc/reviews", json=QUOTE)
    assert res.status_code == 201
    created = res.json()
    assert created["compat"]["incompatible"] == ["socket"]
    got = client.get(f"/pc/reviews/{created['list_id']}")
    assert got.status_code == 200
    assert got.json() == created


@db_only
def test_the_review_is_saved_as_a_named_list_the_owner_can_see(client):
    list_id = client.post("/pc/reviews", json=QUOTE).json()["list_id"]
    listed = {item["list_id"]: item for item in client.get("/lists").json()["items"]}
    assert listed[list_id]["name"] == qrs.REVIEW_LIST_NAME


@db_only
def test_saving_a_review_does_not_touch_the_recommendation_inputs(client, raw_conn):
    """분석 결과는 추천 입력(조건)이 아니다 — 조건 상태에 안 보이고 lock_version 도 그대로다."""
    list_id = client.post("/pc/reviews", json=QUOTE).json()["list_id"]
    before = _lock_version(raw_conn, list_id)
    assert client.put(f"/pc/reviews/{list_id}", json={"current_specs": {"CPU": "AMD Ryzen 5 7500F"}}).status_code == 200
    assert _lock_version(raw_conn, list_id) == before
    state = client.get(f"/session/{list_id}").json()
    assert "quote_review" not in [f["key"] for f in state["fields"]]
    assert state["category"] is None


@db_only
def test_updating_replaces_the_analysis_and_keeps_the_previous_one_as_history(client, raw_conn):
    created = client.post("/pc/reviews", json=QUOTE).json()
    fixed = {"current_specs": {"CPU": "AMD Ryzen 5 7500F", "메인보드": "MSI B650 TOMAHAWK"}}
    updated = client.put(f"/pc/reviews/{created['list_id']}", json=fixed).json()
    assert updated["compat"]["incompatible"] == []
    assert updated["input"]["input_hash"] != created["input"]["input_hash"]
    assert client.get(f"/pc/reviews/{created['list_id']}").json()["compat"]["incompatible"] == []
    states = [r[0] for r in raw_conn.execute(
        "SELECT pc.status FROM planning.plan_condition pc JOIN planning.plan p ON p.current_revision_id=pc.revision_id "
        "WHERE p.id=%s AND pc.condition_key='quote_review' ORDER BY pc.created_at", (created["list_id"],)).fetchall()]
    assert states == ["superseded", "active"]


@db_only
def test_only_the_owner_can_read_or_update_a_review(client):
    list_id = client.post("/pc/reviews", json=QUOTE).json()["list_id"]
    from src.api import app
    with TestClient(app) as stranger:
        assert stranger.get(f"/pc/reviews/{list_id}").status_code == 404
        assert stranger.put(f"/pc/reviews/{list_id}", json=QUOTE).status_code == 404


@db_only
def test_a_list_without_a_review_has_nothing_to_read(client):
    list_id = client.post("/session").json()["list_id"]
    assert client.get(f"/pc/reviews/{list_id}").status_code == 404


@db_only
def test_an_empty_quote_creates_no_session(client):
    before = client.get("/lists").json()
    res = client.post("/pc/reviews", json={"current_specs": {}})
    assert res.status_code == 422
    assert client.get("/lists").json() == before

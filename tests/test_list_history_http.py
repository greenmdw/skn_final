"""견적 리스트 히스토리(C1) — GET /lists/{id}/history 와 부품 교체 기록(item_replaced payload·seq).

일회용 DB 가 필요하다(tests/conftest.py 가 자동으로 만든다). 테스트 환경은 MOCK_MODE 라 요약은 규칙 문장이고,
LLM 경로는 call_llm 을 바꿔 끼워 검사한다."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"hist-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "히스토리", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _recommended_list(c) -> tuple[str, str, dict]:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "게임용 PC 맞추고 싶어요"})
    assert r.status_code == 200, r.text
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", 5_000_000), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    state = r.json()
    assert state["can_recommend"] is True, state
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return lid, state["revision_id"], data


def _swap_to_cheapest_other(c, lid: str, item_id: str, avoid: tuple[str, ...] = ()) -> str:
    alts = c.get(f"/session/{lid}/items/{item_id}/alternatives").json()["items"]
    alt = next(a for a in alts if not a["current"] and a["product"]["name"] not in avoid)
    r = c.post(f"/session/{lid}/items/{item_id}/swap", json={"candidate_id": alt["candidate_id"]})
    assert r.status_code == 200, r.text
    return alt["product"]["name"]


def test_history_tells_the_journey_of_a_confirmed_list(raw_conn):
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    r = c.post(f"/session/{lid}/result-message", json={"text": "그래픽카드는 왜 이걸로 골랐어요?"})
    assert r.status_code == 200, r.text

    item = next(it for it in data["items"] if it["alternatives_count"] > 1)
    first_name = item["product"]["name"]
    second_name = _swap_to_cheapest_other(c, lid, item["item_id"])
    # 같은 품목을 두 번째로 바꾼다 — 처음 제품으로 되돌아가면(A → B → A) 단계에서 빠지므로 다른 제품으로
    third_name = _swap_to_cheapest_other(c, lid, item["item_id"], avoid=(first_name,))

    # 두 번째 교체도 남고(seq), 무엇→무엇이 payload 에 있다
    rows = raw_conn.execute(
        "SELECT payload FROM engine.feedback_event WHERE revision_id=%s AND event_type='item_replaced' ORDER BY occurred_at",
        (revision_id,),
    ).fetchall()
    assert len(rows) == 2
    assert all(p["item_id"] == item["item_id"] and p["from_variant_id"] and p["to_variant_id"] for (p,) in rows)
    assert rows[0][0]["to_variant_id"] == rows[1][0]["from_variant_id"]

    r = c.post(f"/lists/{lid}/confirm", json={"name": "히스토리 테스트"})
    assert r.status_code == 200, r.text

    r = c.get(f"/lists/{lid}/history")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = [e["kind"] for e in body["events"]]
    assert kinds[0] == "condition" and kinds[-1] == "confirm"
    # 아무것도 바꾸지 않은 질문은 빠지고, 버튼으로 두 번 바꾼 건 한 번에 한 줄씩 남는다
    assert "그래픽카드는 왜 이걸로 골랐어요?" not in [e["quote"] for e in body["events"]]
    assert kinds.index("recommend") < kinds.index("swap") and kinds.count("swap") == 2
    swaps = [e["text"] for e in body["events"] if e["kind"] == "swap"]
    assert swaps[0].endswith(f"{first_name} → {second_name}") and swaps[1].endswith(f"{second_name} → {third_name}")
    # 조건을 정한 말에는 알아들은 조건이 붙는다(칩 금액도 말하는 단위로)
    conditions = {e["quote"]: e["text"] for e in body["events"] if e["kind"] == "condition"}
    assert conditions["게임"] == "게임" and conditions["500만 원"] == "예산 500만 원"

    summary = body["summary"]
    assert summary["status"] == "ready"
    assert summary["text"].startswith("게임") and "확정했어요" in summary["text"]

    # 이렇게 정해졌어요: 같은 품목을 두 번 바꾼 건 처음 → 마지막 한 단계, 아무것도 바꾸지 않은 질문은 없다
    steps = body["steps"]
    assert steps[0]["kind"] == "start" and steps[-1]["kind"] == "confirm"
    swap_steps = [s for s in steps if s["kind"] == "swap"]
    assert len(swap_steps) == 1 and swap_steps[0]["changes"] == [f"{first_name} → {third_name}"]
    assert not any("왜 이걸로" in (s["quote"] or "") for s in steps)


def test_history_is_only_for_the_owner_of_a_confirmed_list():
    owner = _signed_up()
    lid, _revision_id, _data = _recommended_list(owner)
    assert owner.get(f"/lists/{lid}/history").status_code == 404        # 아직 확정 전

    assert owner.post(f"/lists/{lid}/confirm", json={"name": "소유 확인"}).status_code == 200
    assert owner.get(f"/lists/{lid}/history").status_code == 200
    assert _signed_up().get(f"/lists/{lid}/history").status_code == 404  # 남의 목록
    assert TestClient(app).get(f"/lists/{lid}/history").status_code == 401  # 로그인 전


def _steps() -> list[dict]:
    step = {"quote": None, "changes": [], "notes": []}
    return [
        {**step, "kind": "start", "text": "원하신 것: 게임 · 150만 원", "quote": "게임용 PC"},
        {**step, "kind": "swap", "text": "GPU를 직접 바꾸셨어요", "changes": ["RX 7600 → RTX 3050"]},
        {**step, "kind": "unapplied", "text": "말씀하셨지만 이번 추천에 반영하지 못한 것",
         "notes": ["‘조용하게’ — 기록했지만 추천에 반영하는 기준이 아직 없어요"]},
        {**step, "kind": "confirm", "text": "1,480,000원으로 확정했어요"},
    ]


def test_particles_follow_how_the_last_letter_is_read():
    from src.services.list_history import _eul, _euro, _user_text

    assert [_eul(w) for w in ("CPU", "RAM", "메인보드", "저장장치", "케이스", "파워")] == \
        ["CPU를", "RAM을", "메인보드를", "저장장치를", "케이스를", "파워를"]
    assert [_euro(w) for w in ("RTX 3050", "RX 7600", "Ryzen 5 7600X", "RTX 4070 SUPER", "970 EVO Plus", "쿨러")] == \
        ["RTX 3050으로", "RX 7600으로", "Ryzen 5 7600X로", "RTX 4070 SUPER로", "970 EVO Plus로", "쿨러로"]
    assert _user_text("5000000") == "500만 원" and _user_text("게임") == "게임"


def test_llm_summary_is_used_only_when_it_invents_no_numbers(monkeypatch):
    from src.clients import llm_client
    from src.services import list_history

    reply = {"text": "게임용으로 찾으시다가 GPU를 RTX 3050으로 바꾸고 1,480,000원에 확정하셨어요."}
    monkeypatch.setattr(llm_client, "call_llm", lambda *a, **k: reply)
    assert list_history.llm_summary(_steps()) == reply["text"]

    reply = {"text": "GPU를 바꿔 20만 원을 아끼고 1,480,000원에 확정하셨어요."}   # 20은 기록에 없다
    assert list_history.llm_summary(_steps()) is None


def test_llm_summary_with_foreign_script_falls_back(monkeypatch):
    """gpt-4o-mini 가 "추천 구성 предложили 이후"처럼 러시아어 낱말을 섞은 적이 있다 — 한글·영문 밖 글자는 버린다."""
    from src.clients import llm_client
    from src.services import list_history

    reply = {"text": "추천 구성 предложили 이후, 1,480,000원으로 확정하셨습니다."}
    monkeypatch.setattr(llm_client, "call_llm", lambda *a, **k: reply)
    assert list_history.llm_summary(_steps()) is None


def test_summary_mentions_unapplied_only_when_there_is_some(monkeypatch):
    """없을 때 "반영하지 못한 것은 없습니다"를 붙이거나, 기본값 안내를 '반영하지 못한 것'으로 옮기던 버릇(2026-10-01)."""
    from src.clients import llm_client
    from src.services import list_history

    prompts = []
    reply = {"text": "게임용으로 찾으셨고 1,480,000원으로 확정하셨어요. 반영하지 못한 것은 없습니다."}
    monkeypatch.setattr(llm_client, "call_llm", lambda prompt, system: prompts.append((prompt, system)) or reply)
    steps = [s for s in _steps() if s["kind"] != "unapplied"]
    steps[0] = {**steps[0], "notes": ["해상도는 말씀 안 하셔서 FHD 144Hz 기준으로 봤어요"]}
    assert list_history.llm_summary(steps) == "게임용으로 찾으셨고 1,480,000원으로 확정하셨어요."
    prompt, system = prompts[0]
    assert "말씀 안 하셔서" not in prompt and "반영 여부는 언급하지 않습니다" in system


def test_summary_falls_back_to_rules_when_llm_fails(monkeypatch):
    from src.clients import llm_client
    from src.services import list_history

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(list_history, "llm_available", lambda: True)
    monkeypatch.setattr(llm_client, "call_llm", boom)
    revision = {"confirmed_at": datetime(2026, 9, 30, tzinfo=timezone.utc)}
    text = list_history.summarize(uuid4(), revision, _steps())
    assert text.startswith("게임 · 150만 원으로 찾기 시작하셨어요.")
    assert "GPU를 직접 바꾸셨어요." in text and "반영하지 못한 것이 1가지" in text and "1,480,000원으로 확정했어요" in text

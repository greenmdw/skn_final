"""견적 리스트 히스토리의 "이렇게 정해졌어요"(src/services/history_journey.py) — 결과를 바꾼 것만 단계가 되는지.

일회용 DB 가 필요하다(tests/conftest.py 가 자동으로 만든다). 테스트 환경은 MOCK_MODE 라 조건은 칩 답변으로 채운다."""
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
        "email": f"journey-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "여정", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _answer(c, lid: str, qid: str, value) -> dict:
    r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
    assert r.status_code == 200, r.text
    return r.json()


def _recommend(c, lid: str) -> dict:
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return data


def _game_list(c, budget: int = 5_000_000) -> tuple[str, dict]:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    assert c.post(f"/session/{lid}/message", json={"text": "게임용 PC 맞추고 싶어요"}).status_code == 200
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", budget), ("q_priority", "성능 우선")):
        state = _answer(c, lid, qid, value)
    assert state["can_recommend"] is True, state
    return lid, state


def _confirm(c, lid: str, name: str) -> None:
    r = c.post(f"/lists/{lid}/confirm", json={"name": name})
    assert r.status_code == 200, r.text


def _steps(c, lid: str, revision: int | None = None) -> list[dict]:
    r = c.get(f"/lists/{lid}/history" + (f"?revision={revision}" if revision else ""))
    assert r.status_code == 200, r.text
    return r.json()["steps"]


def test_budget_changed_twice_is_one_step_and_the_default_resolution_is_named():
    c = _signed_up()
    lid, _ = _game_list(c)
    _recommend(c, lid)
    _answer(c, lid, "q_budget_max", 4_000_000)
    _recommend(c, lid)
    _answer(c, lid, "q_budget_max", 3_000_000)
    _recommend(c, lid)
    _confirm(c, lid, "예산 두 번")

    steps = _steps(c, lid)
    assert [s["kind"] for s in steps] == ["start", "change", "confirm"], steps
    start, change, confirm = steps
    assert start["text"] == "원하신 것: 게임 · 500만 원 · 성능 우선"          # 말하지 않은 해상도는 넣지 않는다
    assert "해상도는 말씀 안 하셔서 FHD 144Hz 기준으로 봤어요" in start["notes"]
    assert change["text"] == "예산 500만 원 → 300만 원"                      # 400만을 거친 건 줄인다
    assert change["quote"] == "300만 원"                                      # 칩 금액도 말하는 단위로
    assert confirm["text"].endswith("원으로 확정했어요")

    # 결과 화면에서 조건을 바꾼 말은 '질문'이 아니라 '조건'이다
    events = c.get(f"/lists/{lid}/history").json()["events"]
    assert [e["kind"] for e in events].count("question") == 0
    assert [e["kind"] for e in events].count("recommend") == 3


def test_revised_quote_starts_from_its_source_and_shows_only_the_swap():
    c = _signed_up()
    lid, _ = _game_list(c)
    _recommend(c, lid)
    _confirm(c, lid, "원본")

    assert c.post(f"/lists/{lid}/revisions", json={}).status_code == 200
    data = c.get(f"/session/{lid}/result").json()
    item = next(it for it in data["items"] if it["alternatives_count"] > 1)
    alts = c.get(f"/session/{lid}/items/{item['item_id']}/alternatives").json()["items"]
    alt = next(a for a in alts if not a["current"])
    r = c.post(f"/session/{lid}/items/{item['item_id']}/swap", json={"candidate_id": alt["candidate_id"]})
    assert r.status_code == 200, r.text
    _confirm(c, lid, "고친 것")

    steps = _steps(c, lid, revision=2)
    assert [s["kind"] for s in steps] == ["start", "swap", "confirm"], steps
    assert steps[0]["text"] == "견적서 1에서 고쳐 시작했어요"
    assert steps[0]["changes"] == ["게임 · 500만 원 · 성능 우선"]
    assert steps[1]["changes"] == [f"{item['product']['name']} → {alt['product']['name']}"]

    # 견적서 1의 히스토리는 그대로다 — 복사가 원본을 건드리지 않는다
    assert [s["kind"] for s in _steps(c, lid, revision=1)] == ["start", "confirm"]


def test_what_was_said_but_not_applied_is_named():
    """자유 요청(extra)과 CPU 밖 브랜드 선호는 조건에 들어가지 않는다 — 들어간 것처럼 읽히지 않게 밝힌다."""
    from src.db import get_conn
    from src.repo.plan_repo import PlanRepo
    from src.repo.preference_repo import PreferenceRepo

    c = _signed_up()
    lid, state = _game_list(c)
    with get_conn() as conn:
        PlanRepo(conn).upsert_condition(state["revision_id"], "extra", {"value": ["조용하게"]}, "extracted")
        owner = conn.execute("SELECT owner_user_id FROM planning.plan WHERE id=%s", (lid,)).fetchone()[0]
        PreferenceRepo(conn).upsert_signal(user_id=owner, dimension="brand", slot="GPU", value="NVIDIA",
                                           direction="prefer", source="explicit_chat")
    _recommend(c, lid)
    _confirm(c, lid, "반영 못 한 것")

    unapplied = next(s for s in _steps(c, lid) if s["kind"] == "unapplied")
    assert "‘조용하게’ — 기록했지만 추천에 반영하는 기준이 아직 없어요" in unapplied["notes"]
    assert any(n.startswith("GPU 브랜드는 NVIDIA가 좋다고 하셨지만, 이번 추천 조건에는 넣지 못했어요")
               for n in unapplied["notes"])


def test_resumed_quote_names_where_it_came_from():
    c = _signed_up()
    first, _ = _game_list(c)
    _recommend(c, first)
    _confirm(c, first, "지난번 견적")

    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/resume", json={"from_list_id": first})
    assert r.status_code == 200, r.text
    _recommend(c, lid)
    _confirm(c, lid, "이어서")

    steps = _steps(c, lid)
    assert steps[0]["kind"] == "start" and steps[0]["text"].endswith("‘지난번 견적’의 조건을 이어서 시작했어요")
    assert steps[0]["changes"] == ["게임 · 500만 원 · 성능 우선"]
    assert [s["kind"] for s in steps[1:]] == ["confirm"]        # 같은 조건이면 바뀐 것이 없다


def test_detail_keeps_what_moved_the_result_and_chat_keeps_everything_in_order():
    """결과에 영향 없는 말은 히스토리에서 빠지고 대화 내역에는 질문 → 답 순서로 남는다. 바꿔 달라고 했는데 그대로면
    '반영 못 함'에 나온다(결과 화면 채팅에는 예산을 바꾸는 도구가 없다)."""
    c = _signed_up()
    lid, _ = _game_list(c)
    _recommend(c, lid)
    for text in ("ㅁㄴㅇㄹ", "예산 늘려줘"):
        assert c.post(f"/session/{lid}/result-message", json={"text": text}).status_code == 200
    _confirm(c, lid, "말만 한 것")

    body = c.get(f"/lists/{lid}/history").json()
    assert not any(e["text"] in ("ㅁㄴㅇㄹ", "예산 늘려줘") for e in body["events"])
    unapplied = next(s for s in body["steps"] if s["kind"] == "unapplied")
    assert unapplied["notes"] == ["‘예산 늘려줘’ — 요청하셨지만 이번 견적에서는 바뀌지 않았어요"]

    messages = c.get(f"/session/{lid}").json()["messages"]
    for text in ("ㅁㄴㅇㄹ", "예산 늘려줘"):
        i = next(i for i, m in enumerate(messages) if m["role"] == "user" and m["text"] == text)
        assert messages[i + 1]["role"] == "assistant", messages[i - 1: i + 2]


def test_question_and_answer_saved_together_keep_their_order():
    """한 트랜잭션에서 저장한 질문과 답 — 예전엔 같은 시각(now())이라 대화 내역에서 답이 먼저 나올 수 있었다."""
    from src.db import get_conn
    from src.repo.user_repo import ConversationRepo

    c = _signed_up()
    lid, _ = _game_list(c)
    with get_conn() as conn:
        conversation_id = conn.execute("SELECT conversation_id FROM planning.plan WHERE id=%s", (lid,)).fetchone()[0]
        repo = ConversationRepo(conn)
        repo.add_message(conversation_id, "user", "질문")
        repo.add_message(conversation_id, "assistant", "답")
        # 수정 전 기록처럼 같은 시각으로 저장된 둘(답이 먼저 들어감)도 사용자 말이 먼저다
        conn.execute("INSERT INTO identity.message (conversation_id, role, content, client_message_id, created_at) "
                     "VALUES (%s, 'assistant', '옛 답', %s, '2026-09-30T00:00:00Z'), "
                     "(%s, 'user', '옛 질문', %s, '2026-09-30T00:00:00Z')",
                     (conversation_id, str(uuid4()), conversation_id, str(uuid4())))
    with get_conn() as conn:
        texts = [m["content"] for m in ConversationRepo(conn).messages(conversation_id)]
    assert texts.index("질문") + 1 == texts.index("답")
    assert texts.index("옛 질문") + 1 == texts.index("옛 답")

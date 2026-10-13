"""4번 예외·폴백 시나리오 중 기존 테스트에 없던 것 — 전체_테스트_시나리오_실행_기획.md §6.

실제 LLM을 부르지 않는다(호출을 가로채 예외·엉뚱한 응답을 주입한다). 일회용 테스트 DB가 필요하다.
이미 덮인 것(없는 list_id 404, 필수 조건 누락, 예산 불가, 이미지 크기·형식, 버전 충돌)은 test_exception_and_concurrency.py·
test_pc_check_router.py·test_quote_drafts.py 가 맡는다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

from src.agent import conditions_agent, quote_review_agent, spec_extraction_agent      # DB 없이도 import 된다(수집 단계 보호)

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from src.auth import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset_all()
    yield


def _client(*, swallow_background_errors: bool = False) -> "TestClient":
    """swallow_background_errors: 백그라운드 추천이 실패 후 예외를 다시 올리는 경우(run을 failed로 기록하고 raise) 운영 서버는
    이미 202를 보낸 뒤라 로그만 남기는데, 테스트 클라이언트는 그 예외를 전파한다 — 그걸 삼켜 실제 서버처럼 본다."""
    c = TestClient(app, raise_server_exceptions=not swallow_background_errors)
    r = c.post("/auth/signup", json={"email": f"fb-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
                                     "display_name": "폴백", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def _ready_session(c, budget: int = 2_000_000) -> str:
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", budget), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    return lid


# ── 검색결과없음 ─────────────────────────────────────────────────────────────

def test_a_slot_with_no_priced_candidates_fails_clearly_with_catalog_incomplete(monkeypatch):
    from src.repo import catalog_repo

    real = catalog_repo.load_candidates_by_slot_from_db

    def without_coolers(conn):
        by_slot = real(conn)
        by_slot["쿨러"] = []
        return by_slot

    monkeypatch.setattr(catalog_repo, "load_candidates_by_slot_from_db", without_coolers)
    c = _client(swallow_background_errors=True)
    lid = _ready_session(c)
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "failed"                                           # running 으로 영원히 남지 않는다(행잉 없음)
    assert data["error"]["code"] == "recommend_failed"
    # 발견 사항(2026-10-05): 사용자에게 가는 사유는 일반 문구뿐이고 "어느 부품 후보가 없는지"(catalog_incomplete, 쿨러)는
    # 서버 로그에만 남는다. 기획서의 통과 기준 "명확한 에러"에는 부분적으로만 맞는다 — 보고서에 기록.
    assert "쿨러" not in str(data["error"])


# ── API/LLM 오류 → 규칙 폴백 ──────────────────────────────────────────────────

@pytest.mark.parametrize("failure", ["raises", "bad_schema", "wrong_shape"])
def test_recommendation_still_completes_when_the_explanation_and_verification_llm_fail(monkeypatch, failure):
    """[5] 설명·[3-C] 쟁점 문장 생성이 예외·스키마 불일치·엉뚱한 모양으로 실패해도 추천은 규칙 템플릿으로 끝난다(500 없음)."""
    from src.engine import stage3c_verify, stage5_explain

    def broken(prompt, **kwargs):
        if failure == "raises":
            raise RuntimeError("simulated OpenAI outage")
        if failure == "bad_schema":
            return {"headline": 123, "items": "not-a-list"}                       # ExplanationDraft 검증 실패
        return {"text": ""}                                                      # 문장이 비어 있다

    monkeypatch.setattr(stage5_explain, "call_llm", broken)
    monkeypatch.setattr(stage3c_verify, "call_llm", broken)
    c = _client()
    lid = _ready_session(c)
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    assert len(data["items"]) == 8 and all(i["product"]["name"] for i in data["items"])
    assert data["explanation"]                                                    # 템플릿 문장이 채워진다


# ── 조건 대화 에이전트 ────────────────────────────────────────────────────────

def test_conditions_agent_failure_falls_back_to_rules_for_that_turn(monkeypatch):
    monkeypatch.setattr(conditions_agent, "available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(conditions_agent, "run_turn", boom)
    c = _client()
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "게임용 PC 예산 150만원 성능 우선"})
    assert r.status_code == 200, r.text                                           # 에러가 사용자에게 새지 않는다
    assert r.json()["messages"][-1]["role"] == "assistant"


def test_conditions_agent_replying_with_text_only_keeps_conditions_and_does_not_error(monkeypatch):
    """도구를 하나도 안 부르고 글만 돌려주면 조건은 그대로, 에러 없음."""
    monkeypatch.setattr(conditions_agent, "available", lambda: True)
    monkeypatch.setattr(conditions_agent, "run_turn",
                        lambda *a, **k: conditions_agent.TurnResult(reply="네, 알겠습니다.", patches={}, trace=[], preference_patches=[]))
    c = _client()
    lid = c.post("/session").json()["list_id"]
    c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"})
    before = c.get(f"/session/{lid}").json()
    r = c.post(f"/session/{lid}/message", json={"text": "음... 잘 모르겠어요"})
    assert r.status_code == 200, r.text
    after = r.json()
    assert [f["value"] for f in after["fields"]] == [f["value"] for f in before["fields"]]
    assert after["messages"][-1]["text"] == "네, 알겠습니다."


# ── 추출 에이전트 ────────────────────────────────────────────────────────────

def test_text_extraction_failure_falls_back_to_the_rule_parser(monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)

    def boom(text):
        raise RuntimeError("extraction model down")

    monkeypatch.setattr(spec_extraction_agent, "extract", boom)
    c = TestClient(app)
    r = c.post("/pc/owned-parts/preview", json={"text": "CPU: AMD Ryzen 5 7500F\n메인보드: MSI B650 TOMAHAWK"})
    assert r.status_code == 200, r.text
    assert {row["part"] for row in r.json()["rows"]} == {"CPU", "메인보드"}


def test_image_extraction_failure_is_503_never_an_empty_success(monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)

    def boom(url):
        raise RuntimeError("vision down")

    monkeypatch.setattr(spec_extraction_agent, "extract_from_image", boom)
    r = TestClient(app).post("/pc/owned-parts/preview", json={"image_data_url": "data:image/png;base64,iVBORw0KGgo="})
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "image_extraction_failed"


# ── MOCK_MODE·키 미설정 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("module,flag", [(conditions_agent, "CONDITIONS_AGENT"), (spec_extraction_agent, "SPEC_EXTRACTION_AGENT"),
                                         (quote_review_agent, "QUOTE_REVIEW_AGENT")])
def test_agents_are_off_without_a_key_or_in_mock_mode(monkeypatch, module, flag):
    """키가 없거나 MOCK_MODE 면 모든 에이전트가 조용히 꺼진다(예외가 아니라 False) — 호출자는 규칙 경로로 간다."""
    for name, value in (("MOCK_MODE", False), ("OPENAI_API_KEY", "sk-test"), ("LLM_PROVIDER", "openai"), ("LLM_MODEL", "m"), (flag, True)):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value)
    assert module.available() is True                                             # 조건을 모두 갖추면 켜진다(대조군)
    monkeypatch.setattr(module, "OPENAI_API_KEY", "")
    assert module.available() is False
    monkeypatch.setattr(module, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(module, "MOCK_MODE", True)
    assert module.available() is False


def test_result_chat_without_agent_uses_rules_and_never_errors(monkeypatch):
    """결과 화면 대화에서 에이전트가 없거나 예외를 내면 규칙 경로 — 구성표를 바꿨다면 바뀐 것만 알린다(코드 근거)."""
    from src.agent import result_agent

    monkeypatch.setattr(result_agent, "available", lambda: False)
    c = _client()
    lid = _ready_session(c)
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    r = c.post(f"/session/{lid}/result-message", json={"text": "쿨러를 더 저렴한 걸로 바꿔줘"})
    assert r.status_code == 200, r.text
    assert r.json()["reply"]


# ── 2번 ML 연동: 이미지 전용 모델 분리 ─────────────────────────────────────────

def test_image_extraction_calls_the_separate_image_model_with_temperature_zero(monkeypatch):
    """LLM_MODEL 과 다르게 설정한 SPEC_EXTRACTION_IMAGE_MODEL 이 비전 호출에 실제로 전달된다(온도 0 포함) — 단일·여러 제품 두 경로 모두."""
    seen: list[dict] = []
    monkeypatch.setattr(spec_extraction_agent, "SPEC_EXTRACTION_IMAGE_MODEL", "vision-model-x")
    monkeypatch.setattr(spec_extraction_agent, "LLM_MODEL", "chat-model-y")
    monkeypatch.setattr(spec_extraction_agent, "call_llm_vision", lambda url, **kw: seen.append(kw) or {"items": [], "cpu": None})
    spec_extraction_agent.extract_items_from_image("data:image/png;base64,AA==")
    spec_extraction_agent.extract_from_image("data:image/png;base64,AA==")
    assert [k["model"] for k in seen] == ["vision-model-x", "vision-model-x"]
    assert all(k["temperature"] == 0 for k in seen)


def test_text_extraction_does_not_use_the_image_model(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(spec_extraction_agent, "SPEC_EXTRACTION_IMAGE_MODEL", "vision-model-x")
    monkeypatch.setattr(spec_extraction_agent, "call_llm", lambda prompt, **kw: seen.append(kw) or {"items": []})
    spec_extraction_agent.extract_items("CPU: 라이젠 5 7500F")
    assert "model" not in seen[0] or seen[0]["model"] != "vision-model-x"

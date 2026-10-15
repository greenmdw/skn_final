"""주변기기 채팅 한 턴 서비스 — 질문이 조건을 바꾸지 않는지, 이번 턴 것만 말하는지, 모델이 질문이라고 해도 질문 말투가 없으면
조건으로 두는지, 추천 결과가 필요한 질문이 그 결과로 답하는지(QA PQA-012·013·014). DB·언어 모델 없이 돈다."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from src.agent import peripheral_intent_agent
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_payload import peripheral_payload
from src.engine.peripheral_rules import chat_config, load_peripheral_rules
from src.engine.peripheral_select import run_peripherals
from src.services import peripheral_chat_service, peripheral_interpret_service, peripherals_service

RULES = load_peripheral_rules()
ANSWERS = chat_config(RULES)["answers"]
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"


@pytest.fixture(autouse=True)
def _words_only(monkeypatch):
    """언어 모델을 쓰지 않는다(로컬 .env 에 키가 있어도). 같은 문장 저장도 비운다."""
    monkeypatch.setattr(peripheral_intent_agent, "available", lambda: False)
    peripheral_interpret_service.clear_cache()
    yield
    peripheral_interpret_service.clear_cache()


@contextmanager
def _no_db():
    raise AssertionError("이 질문은 DB 연결이 필요 없다")
    yield  # pragma: no cover


def _turn(text, previous=None, kinds=None, **kw):
    kw.setdefault("pc_list_id", None)
    kw.setdefault("pc_context", None)
    kw.setdefault("open_conn", _no_db)
    return peripheral_chat_service.turn(text, previous, kinds, **kw)


def _prev(out):
    return out["interpretation"].model_dump()


# ── 질문은 조건을 바꾸지 않는다 · 이번 턴 것만 말한다(PQA-013) ─────────────────────────
def test_condition_turn_reports_what_it_added():
    out = _turn("마우스 가벼운 무선으로 5만원 이하")
    labels = [i["label"] for i in out["turn"]["new_conditions"]]
    assert {"무선", "가벼운 무게", "마우스 예산 50,000원"} <= set(labels)
    assert out["turn"]["reply"].startswith("이번에 반영했어요:") and out["turn"]["answer"] is None


def test_question_turn_does_not_repeat_old_conditions_or_change_them():
    """QA 종합#16: 질문에도 "반영했어요: 무선 · 가벼운 무게"를 되풀이하던 문제."""
    first = _turn("마우스랑 스피커 가벼운 무선으로")
    second = _turn("스피커는 어떤 조건으로 나눌 수 있어?", _prev(first))
    assert second["turn"]["new_conditions"] == []
    assert "이번에 반영했어요" not in second["turn"]["reply"] and "무선 · 가벼운 무게" not in second["turn"]["reply"]
    assert second["turn"]["answer"]["type"] == "conditions" and "북셸프" in second["turn"]["reply"]
    before, after = first["interpretation"], second["interpretation"]
    assert (after.stated, after.purposes, after.kinds) == (before.stated, before.purposes, before.kinds)


def test_question_is_not_carried_to_the_next_turn():
    asked = _turn("스피커는 어떤 조건으로 나눌 수 있어?")
    assert asked["interpretation"].question.type == "conditions"
    then = _turn("마우스 무선으로", _prev(asked))
    assert then["interpretation"].question is None and then["turn"]["answer"] is None


def test_term_question_does_not_become_a_filter():
    out = _turn("래피드 트리거가 뭐야?", None, ["keyboard"])
    assert out["interpretation"].stated == {}
    assert out["turn"]["answer"]["text"] == chat_config(RULES)["glossary"]["래피드 트리거"]["text"]
    assert out["needs_kind"] is False


def test_mixed_sentence_keeps_the_condition_and_answers_the_question(monkeypatch):
    _fake_recommend(monkeypatch, ["mouse"], purpose="game")
    out = _turn("마우스 무선이면 좋겠는데 배터리는 얼마나 가?", None, ["mouse"], open_conn=_stub_recommend)
    assert out["interpretation"].stated == {"mouse": ["wireless"]}
    assert out["turn"]["reply"].split("\n")[0] == "이번에 반영했어요: 무선"
    assert "배터리" in out["turn"]["reply"]


def test_capabilities_question_needs_no_kind_card():
    out = _turn("너가 대답할 수 있는게 뭔데?")
    assert out["needs_kind"] is False and out["turn"]["answer"]["text"] == ANSWERS["capabilities"]
    assert out["turn"]["chips"] == chat_config(RULES)["chips"]["start"]


def test_out_of_scope_question_is_answered_not_asked_for_a_kind():
    out = _turn("앵무새야?")
    assert out["interpretation"].question.type == "other"
    assert out["turn"]["answer"]["text"] == ANSWERS["other"] and out["turn"]["chips"]


@pytest.mark.parametrize("text", [
    "무게 가벼운 마우스 추천", "가격 차이 적은 걸로 골라줘", "손에 맞아요 이런 마우스", "블루투스 있어요 이거 말고 다른 키보드",
])
def test_sentence_without_question_marker_is_never_a_question(text):
    assert _turn(text, None, ["mouse"])["interpretation"].question is None


def test_light_mouse_request_keeps_its_condition():
    out = _turn("무게 가벼운 마우스 추천")
    assert out["interpretation"].stated == {"mouse": ["lightweight"]}


# ── 설명: 반영하지 못한 말 · 읽은 방법(PQA-012) ───────────────────────────────────
def test_unsupported_words_are_explained_in_the_reply():
    out = _turn("청축 키보드 추천해줘")
    assert any("청축" in n for n in out["turn"]["not_reflected"])
    assert out["turn"]["reply"].split("\n")[-1] == out["turn"]["not_reflected"][-1]       # 맨 끝에 붙는다


def test_nothing_read_says_so_with_an_example_and_no_old_conditions():
    first = _turn("마우스 가벼운 무선")
    out = _turn("음 글쎄요", _prev(first))
    assert out["turn"]["reply"].startswith("이번 문장에서는 새로 읽어 낸 조건이 없어요.")
    assert "무선 마우스" in out["turn"]["reply"]


def test_loose_phrase_reading_is_told():
    out = _turn("타건감 묵직한 키보드 찾아요")
    assert out["interpretation"].stated == {"keyboard": ["heavy_key_force"]}
    assert any("묵직한 키압" in n for n in out["turn"]["notes"])


def test_conflict_is_told_once_then_not_repeated():
    first = _turn("엑셀 많이 하는데 텐키리스로 키보드")
    assert any("텐키리스" in n for n in first["turn"]["notes"])
    second = _turn("무선으로", _prev(first), ["keyboard"])
    assert not any("텐키리스" in n and "우선" in n for n in second["turn"]["notes"])


# ── 언어 모델 경로: 질문 종류만 받는다 ──────────────────────────────────────────
def _fake_model(monkeypatch, result: Interpretation):
    monkeypatch.setattr(peripheral_intent_agent, "available", lambda: True)
    monkeypatch.setattr(peripheral_intent_agent, "interpret", lambda *_a, **_k: result)


def test_model_question_is_used_when_the_sentence_has_a_question_marker(monkeypatch):
    _fake_model(monkeypatch, Interpretation(kinds=["keyboard"], stated={"keyboard": ["rapid_trigger"]},
                                            question=Question(type="term", topic="래피드 트리거")))
    out = _turn("그게 어떤 기능인지 궁금해요?")      # 규칙은 종류를 못 가른다 — 모델의 question 을 받는다
    assert out["interpretation"].question.type == "term" and out["interpretation"].stated == {}


def test_model_question_is_ignored_without_a_question_marker(monkeypatch):
    """모델이 질문이라고 해도 질문 말투가 없으면 조건 문장이다 — 조건이 지워지지 않는다."""
    _fake_model(monkeypatch, Interpretation(kinds=["mouse"], stated={"mouse": ["lightweight"]}, question=Question(type="spec", topic="weight")))
    out = _turn("가벼운 마우스 찾고 있어요")
    assert out["interpretation"].question is None and out["interpretation"].stated == {"mouse": ["lightweight"]}


def test_model_unrecognized_words_are_explained(monkeypatch):
    _fake_model(monkeypatch, Interpretation(kinds=["keyboard"], unrecognized=["무드등"]))
    out = _turn("무드등 있는 키보드")
    assert out["turn"]["not_reflected"] == ["“무드등”: 아직 조건으로 고를 수 없어서 반영하지 못했어요."]


# ── 결과가 필요한 질문 ────────────────────────────────────────────────────
def _fake_recommend(monkeypatch, kinds, **values):
    result = run_peripherals({"peripherals": kinds, **values}, load_peripheral_candidates_from_csv(_FIXTURES, RULES), lambda _m: None)
    payload = peripheral_payload(result)
    seen = {}

    def fake(conn, body, pc_context):
        seen["body"] = body
        return payload, result

    monkeypatch.setattr(peripherals_service, "recommend_detailed", fake)
    return result, payload, seen


@contextmanager
def _stub_recommend():
    yield object()


def test_why_question_is_answered_from_the_recommendation(monkeypatch):
    result, payload, seen = _fake_recommend(monkeypatch, ["mouse"], purpose="game")
    first = _turn("마우스 가벼운 무선 5만원 이하")
    out = _turn("왜 이걸 1위로 골랐어?", _prev(first), open_conn=_stub_recommend)
    answer = out["turn"]["answer"]
    assert answer["type"] == "why" and payload["items"][0]["product"]["name"] in answer["text"]
    assert out["turn"]["new_conditions"] == [] and answer["chips"] == chat_config(RULES)["chips"]["after_result"]
    # 추천 요청은 지금까지 합쳐진 조건 그대로다
    body = seen["body"]
    assert body.kinds == ["mouse"] and body.stated == {"mouse": ["wireless", "lightweight"]} and body.kind_budget == {"mouse": 50000}


def test_result_question_without_kind_asks_which_kind():
    out = _turn("왜 이걸 1위로 골랐어?")
    assert out["turn"]["answer"]["text"] == ANSWERS["no_kind"] and len(out["turn"]["answer"]["chips"]) == 4
    assert out["needs_kind"] is True


def test_result_question_without_result_says_a_result_is_needed(monkeypatch):
    monkeypatch.setattr(peripherals_service, "recommend_detailed", lambda *_a: ({"status": "empty", "items": []}, None))
    out = _turn("왜 이걸 1위로 골랐어?", None, ["mouse"], open_conn=_stub_recommend)
    assert out["turn"]["answer"]["text"] == ANSWERS["no_result"]


def test_db_is_not_opened_for_questions_that_need_no_result():
    _turn("스피커는 어떤 조건으로 나눌 수 있어?")      # _no_db 가 열리면 AssertionError
    _turn("래피드 트리거가 뭐야?", None, ["keyboard"])
    _turn("앵무새야?")

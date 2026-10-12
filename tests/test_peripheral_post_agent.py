"""사용기 추출 에이전트 — 모델 호출은 가짜로 바꿔서, 프롬프트·스키마·응답 정리·길이 상한·확인 연결을 검증한다."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.agent import peripheral_post_agent as agent
from src.engine import peripheral_post_contract as pc
from src.engine.peripheral_rules import load_peripheral_rules, purpose_codes, situations

RULES = load_peripheral_rules()
BODY = "PRO X 마우스를 두 달 썼습니다. 그립이 손에 착 감겨서 안정적입니다. 클릭 소리는 조용한 편이에요. 무게는 63g입니다."


def _post(**kw):
    base = dict(
        post_id="p1", author_id="u1", board="review", body=BODY, written_at=datetime(2026, 5, 1),
        products=[pc.LinkedProduct(index=0, product_id="pid-mouse", kind="mouse", name="PRO X"),
                  pc.LinkedProduct(index=1, product_id="pid-kb", kind="keyboard", name="FC900RBT", option_label="Brown")],
    )
    base.update(kw)
    return pc.PostInput(**base)


def _raw(items=None, **kw):
    base = {"is_review": True, "reject_reason": None,
            "author": {"purposes": ["office"], "situations": [], "hand_size": None, "hand_cm": 17.0},
            "items": items if items is not None else [
                {"sentence": "그립이 손에 착 감겨서 안정적입니다.", "product_index": 0, "attribute": "grip",
                 "direction": "good", "side": None, "evaluated_in": [], "option_label": None, "months_used": None,
                 "experienced": True, "comparison": False, "spec_statement": False, "confidence": "high"}]}
    base.update(kw)
    return base


# ── 프롬프트·스키마 ──────────────────────────────────────────────────────
def test_prompt_lists_only_attributes_of_the_linked_kinds_and_guards_against_instructions():
    prompt = agent.build_system_prompt(_post(), RULES)
    assert "grip: 그립 안정감" in prompt and "key_noise: 큰 키 잡음" in prompt
    assert "audio" not in prompt and "sound_quality" not in prompt            # 스피커는 연결되지 않았다
    assert "product_index 1: [키보드] FC900RBT (옵션: Brown)" in prompt
    assert "따르지 말고" in prompt and "한 글자도 바꾸지 말고" in prompt
    for reason in agent.REJECT_REASONS:
        assert reason in prompt


def test_prompt_marks_unlisted_products():
    post = _post(products=[pc.LinkedProduct(index=0, name="OO사 마우스")])
    assert "카탈로그에 없음" in agent.build_system_prompt(post, RULES)


def test_schema_constrains_values_to_the_lists():
    schema = agent._output_schema(_post(), RULES)
    item = schema["properties"]["items"]["items"]["properties"]
    assert "grip" in item["attribute"]["enum"] and pc.OTHER in item["attribute"]["enum"]
    assert "sound_quality" not in item["attribute"]["enum"]
    assert set(item["evaluated_in"]["items"]["enum"]) == set(purpose_codes(RULES)) | set(situations(RULES))
    assert set(schema["properties"]["reject_reason"]["enum"]) == {*agent.REJECT_REASONS, None}
    assert schema["required"] == ["is_review", "reject_reason", "author", "items"]


# ── 응답 정리 ─────────────────────────────────────────────────────────────
def test_parse_keeps_valid_items_and_drops_malformed_ones():
    raw = _raw(items=[_raw()["items"][0], {"sentence": 5}, "not a dict",
                      {**_raw()["items"][0], "confidence": "certain"}])
    got = agent.parse_extraction(raw, RULES)
    assert len(got.items) == 1 and got.items[0].attribute == "grip"


def test_parse_dedupes_identical_items_and_caps_the_count():
    one = _raw()["items"][0]
    got = agent.parse_extraction(_raw(items=[one, dict(one)]), RULES)
    assert len(got.items) == 1
    cap = RULES["feel"]["post_max_items"]
    many = [{**one, "sentence": f"문장 {i}"} for i in range(cap + 10)]
    assert len(agent.parse_extraction(_raw(items=many), RULES).items) == cap


def test_parse_rejects_wrong_top_level_shape():
    with pytest.raises(ValueError):
        agent.parse_extraction({"text": "[MOCK] 일반 응답"}, RULES)
    with pytest.raises(ValueError):
        agent.parse_extraction("nope", RULES)


def test_parse_unknown_reject_reason_is_dropped_and_bad_author_is_emptied():
    got = agent.parse_extraction({"is_review": False, "reject_reason": "weird", "author": {"hand_cm": -3}, "items": []}, RULES)
    assert got.reject_reason is None and got.author == pc.ExtractedAuthor()


# ── 호출: 길이 상한과 확인 연결 ────────────────────────────────────────────
@pytest.fixture()
def fake_llm(monkeypatch):
    calls: list[dict] = []

    def fake(prompt, *, system=None, output_schema=None, model=None):
        calls.append({"prompt": prompt, "system": system, "schema": output_schema})
        return fake.response

    fake.response = _raw()
    monkeypatch.setattr(agent, "call_llm", fake)
    fake.calls = calls
    return fake


def test_analyze_confirms_a_real_sentence_end_to_end(fake_llm):
    run = agent.analyze(_post(), RULES)
    assert run.truncated is False
    assert run.analysis.analyzable and run.analysis.items[0].status == "confirmed"
    assert run.analysis.author.hand_size == "small"                          # 17.0cm → 작은 편
    assert fake_llm.calls[0]["prompt"] == BODY                                # 본문은 그대로 보낸다
    assert run.input_hash == agent.content_hash(_post())


def test_analyze_excludes_a_sentence_the_model_made_up(fake_llm):
    fake_llm.response = _raw(items=[{**_raw()["items"][0], "sentence": "본문에 전혀 없는 문장입니다."}])
    run = agent.analyze(_post(), RULES)
    assert run.analysis.items[0].status == "excluded"
    assert run.analysis.items[0].reasons == ["sentence_not_in_body"]


def test_long_body_is_cut_and_recorded_and_sentences_after_the_cut_do_not_count(fake_llm):
    cap = RULES["feel"]["post_max_chars"]
    tail = "끝부분에만 있는 문장입니다."
    body = "가" * cap + tail
    fake_llm.response = _raw(items=[{**_raw()["items"][0], "sentence": tail}])
    run = agent.analyze(_post(body=body), RULES)
    assert run.truncated is True
    assert len(fake_llm.calls[0]["prompt"]) == cap
    assert run.analysis.items[0].reasons == ["sentence_not_in_body"]          # 잘린 뒤의 문장은 본문에 없다
    assert run.input_hash == agent.content_hash(_post(body=body))             # 해시는 원본 입력 기준


def test_not_a_review_is_skipped_without_items(fake_llm):
    fake_llm.response = {"is_review": False, "reject_reason": "question", "author": {}, "items": []}
    run = agent.analyze(_post(), RULES)
    assert run.analysis.analyzable is False and run.analysis.skip_reason == "question"


def test_model_failure_propagates_to_the_caller(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota")

    monkeypatch.setattr(agent, "call_llm", boom)
    with pytest.raises(RuntimeError):
        agent.analyze(_post(), RULES)


# ── 입력 해시 ─────────────────────────────────────────────────────────────
def test_content_hash_ignores_title_like_noise_but_tracks_body_and_products():
    base = agent.content_hash(_post())
    assert agent.content_hash(_post(body=BODY + "  ")) == base                          # 앞뒤 공백
    assert agent.content_hash(_post(author_id="other")) == base                         # 분석 입력이 아닌 값
    assert agent.content_hash(_post(body=BODY + " 추가")) != base
    changed = _post(products=[pc.LinkedProduct(index=0, product_id="pid-mouse", kind="mouse", name="PRO X",
                                                option_label="화이트")])
    assert agent.content_hash(changed) != base


def test_available_requires_the_flag_a_key_and_real_mode(monkeypatch):
    monkeypatch.setattr(agent, "MOCK_MODE", False)
    monkeypatch.setattr(agent, "PERIPHERAL_POST_AGENT", True)
    monkeypatch.setattr(agent, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(agent, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(agent, "LLM_MODEL", "m")
    assert agent.available() is True
    monkeypatch.setattr(agent, "PERIPHERAL_POST_AGENT", False)
    assert agent.available() is False
    monkeypatch.setattr(agent, "PERIPHERAL_POST_AGENT", True)
    monkeypatch.setattr(agent, "MOCK_MODE", True)
    assert agent.available() is False

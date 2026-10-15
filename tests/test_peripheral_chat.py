"""주변기기 채팅 한 턴 — 질문 분류, 이번 문장에서 새로 반영한 것, 반영하지 못한 말 설명, 질문 답변(QA PQA-012·013·014).

DB·언어 모델 없이 도는 테스트다. 답 문장이 **설정·추천 결과·스펙에서만** 만들어지는지(없는 값을 지어내지 않는지)와,
질문이 조건을 바꾸지 않는지, 설정의 질문 칩·예문이 실제로 같은 종류로 읽히는지를 고정한다."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine import peripheral_chat as chat
from src.engine import peripheral_intent as pi
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_intent import Interpretation, Question
from src.engine.peripheral_payload import peripheral_payload
from src.engine.peripheral_rules import chat_config, load_peripheral_rules, peripheral_kinds
from src.engine.peripheral_select import run_peripherals

RULES = load_peripheral_rules()
CHAT = chat_config(RULES)
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"


def _run(kinds, **values):
    result = run_peripherals({"peripherals": kinds, **values}, load_peripheral_candidates_from_csv(_FIXTURES, RULES), lambda _m: None)
    return result, peripheral_payload(result)


# ── 질문 분류 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, qtype, topic", [
    ("스피커는 어떤 조건으로 나눌 수 있어?", "conditions", None),
    ("너가 대답할 수 있는게 뭔데?", "capabilities", None),
    ("왜 이걸 1위로 골랐어?", "why", None),
    ("1위랑 2위 차이가 뭐야?", "compare", None),
    ("스펙이 어떻게 돼?", "spec", None),
    ("이 마우스 무게 어때?", "spec", "weight"),
    ("이 모니터 USB-C로 충전 돼?", "spec", "usb_c"),
    ("폴링레이트가 얼마야?", "spec", "polling"),
    ("소리는 어때?", "review", "sound"),
    ("이 키보드 소리 커?", "review", "sound"),
    ("래피드 트리거가 뭐야?", "term", "래피드 트리거"),
    ("주사율이 뭐야?", "term", "주사율"),
    ("내 컴퓨터에 이 모니터 맞아?", "compat", None),
    ("무선이면 좋겠는데 배터리는 얼마나 가?", "spec", "battery"),       # 섞인 문장: 질문은 뒤쪽 주제
])
def test_question_is_classified(text, qtype, topic):
    got = chat.classify_question(text, RULES)
    assert got is not None and (got.type, got.topic) == (qtype, topic)


@pytest.mark.parametrize("text", [
    "무게 가벼운 마우스 추천",             # 질문 말투가 없다 — 스펙 낱말이 있어도 조건 문장이다
    "4K 모니터 추천해줘",
    "타건감 묵직한 키보드 찾아요",
    "게임용 마우스 뭐가 좋아?",            # 질문 말투는 있지만 종류를 가를 낱말이 없다 → 조건 문장(other 도 아니다)
    "나는 노래 듣는걸 좋아해",
    "앵무새야?",                           # 질문 말투만 있다 → 분류 함수는 None, other 는 서비스가 해석을 보고 정한다
])
def test_non_question_sentences_are_not_classified(text):
    assert chat.classify_question(text, RULES) is None


def test_question_kinds_are_the_ones_named_in_the_sentence():
    assert chat.classify_question("이 키보드 소리 커?", RULES).kinds == ["keyboard"]
    assert chat.classify_question("왜 이걸 1위로 골랐어?", RULES).kinds == []


# ── 설정의 질문 칩·예문·용어가 정말 그렇게 읽히는가 ───────────────────────────────
@pytest.mark.parametrize("sentence, expected", [
    ("모니터는 어떤 조건으로 나눌 수 있어?", "conditions"),
    ("키보드는 어떤 조건으로 나눌 수 있어?", "conditions"),
    ("너가 대답할 수 있는 게 뭐야?", "capabilities"),
])
def test_start_chips_read_as_their_questions(sentence, expected):
    assert sentence in CHAT["chips"]["start"]
    assert chat.classify_question(sentence, RULES).type == expected


def test_every_chip_is_a_recognised_question():
    for sentence in [*CHAT["chips"]["start"], *CHAT["chips"]["after_result"], *chat.kind_condition_chips(RULES)]:
        assert chat.classify_question(sentence, RULES) is not None, sentence
    assert [chat.classify_question(s, RULES).type for s in CHAT["chips"]["after_result"]] == ["why", "compare", "spec", "review"]


def test_kind_condition_chips_name_their_kind():
    for kind, sentence in zip(peripheral_kinds(RULES), chat.kind_condition_chips(RULES), strict=True):
        assert chat.classify_question(sentence, RULES).kinds == [kind]


def test_every_example_is_read_as_kind_and_conditions():
    """조건 안내 답변 끝에 붙이는 예문은 실제로 그 종류의 조건으로 읽혀야 한다."""
    for kind, sentence in CHAT["examples"].items():
        got = pi.interpret_by_words(sentence, RULES)
        assert got.kinds == [kind], sentence
        assert got.stated.get(kind) or got.purposes or got.budget, sentence
        assert chat.classify_question(sentence, RULES) is None      # 예문은 질문이 아니다


def test_every_glossary_term_is_answered_as_a_term():
    for term, entry in CHAT["glossary"].items():
        got = chat.classify_question(f"{entry['words'][0]}가 뭐야?", RULES)
        assert got is not None and got.type == "term" and got.topic in CHAT["glossary"], term


def test_every_spec_topic_word_is_a_spec_question():
    for name, entry in CHAT["spec_topics"].items():
        got = chat.classify_question(f"이 제품 {entry['words'][0]} 어때?", RULES)
        assert got is not None and got.type == "spec", name


def test_every_review_topic_word_is_a_review_question():
    for name, entry in CHAT["review_topics"].items():
        got = chat.classify_question(f"이 제품 {entry['words'][0]} 어때?", RULES)
        assert got is not None and got.type in ("review", "spec"), name


# ── 질문은 조건을 바꾸지 않는다 ────────────────────────────────────────────────
def test_pure_question_drops_every_condition_but_keeps_kinds():
    interp = pi.interpret_by_words("래피드 트리거가 뭐야? 키보드", RULES)
    assert interp.stated.get("keyboard") == ["rapid_trigger"]               # 낱말 규칙은 조건으로 읽는다
    only = chat.question_only(interp.model_copy(update={"question": Question(type="term", topic="래피드 트리거")}))
    assert only.kinds == ["keyboard"] and only.stated == {} and only.purposes == [] and only.question.type == "term"


def test_request_words_mark_a_mixed_sentence():
    assert chat.has_request_words("무선이면 좋겠는데 배터리는 얼마나 가?", RULES)
    assert not chat.has_request_words("래피드 트리거가 뭐야?", RULES)


def test_read_nothing_is_only_true_for_an_empty_interpretation():
    assert chat.read_nothing(Interpretation())
    assert not chat.read_nothing(Interpretation(kinds=["mouse"]))
    assert not chat.read_nothing(Interpretation(question=Question(type="why")))


# ── 이번 문장에서 새로 반영한 것 ───────────────────────────────────────────────
def test_new_conditions_lists_only_what_this_turn_added():
    first = pi.interpret_by_words("마우스 가벼운 무선으로 5만원 이하", RULES)
    labels = [i["label"] for i in chat.new_conditions(None, first, RULES)]
    assert "무선" in labels and "가벼운 무게" in labels and "마우스 예산 50,000원" in labels

    second = pi.merge(first, pi.interpret_by_words("조용한 걸로", RULES, kinds_hint=["mouse"]))
    added = [i["label"] for i in chat.new_conditions(first, second, RULES)]
    assert added and not {"무선", "가벼운 무게"} & set(added)              # 앞 턴 것을 되풀이하지 않는다
    assert any("조용" in label for label in added)


def test_new_conditions_is_empty_when_nothing_changed():
    first = pi.interpret_by_words("마우스 가벼운 무선", RULES)
    assert chat.new_conditions(first, pi.merge(first, Interpretation()), RULES) == []


def test_changed_budget_counts_as_new():
    first = pi.interpret_by_words("마우스 5만원 이하", RULES)
    second = pi.merge(first, pi.interpret_by_words("마우스 3만원 이하", RULES))
    assert [i["label"] for i in chat.new_conditions(first, second, RULES)] == ["마우스 예산 30,000원"]


# ── 반영하지 못한 말·읽은 방법 ─────────────────────────────────────────────────
@pytest.mark.parametrize("text, hit", [
    ("청축 키보드 추천해줘", "청축"),
    ("모니터 밑에 둘 사운드바", "사운드바"),
    ("성능 우선으로 골라줘", "성능 우선"),
    ("비싼 거 추천해줘", "비싼 거"),
    ("헤드셋도 추천해 줘", "헤드셋"),
])
def test_unsupported_words_are_explained(text, hit):
    notes = chat.unsupported_notes(text, RULES)
    assert [n["words"] for n in notes] == [hit] and notes[0]["text"]


def test_supported_sentence_has_no_unsupported_note():
    assert chat.unsupported_notes("조용한 무선 키보드 10만원 이하", RULES) == []


def test_unrecognized_notes_say_what_was_not_reflected():
    assert chat.unrecognized_notes(["무드등"]) == ["“무드등”: 아직 조건으로 고를 수 없어서 반영하지 못했어요."]


def test_reading_note_tells_how_a_loose_phrase_was_read():
    interp = pi.interpret_by_words("타건감 묵직한 키보드", RULES)
    notes = chat.reading_notes("타건감 묵직한 키보드", interp, RULES)
    assert len(notes) == 1 and "묵직" in notes[0] and "묵직한 키압" in notes[0]
    assert chat.reading_notes("묵직한 키압 키보드", pi.interpret_by_words("묵직한 키압 키보드", RULES), RULES) == []   # 낱말 그대로면 말하지 않는다


def test_conflict_note_is_said_once():
    first = pi.resolve(pi.interpret_by_words("엑셀 많이 하는데 텐키리스로 키보드", RULES), RULES)
    notes = chat.conflict_notes(first, None)
    assert len(notes) == 1 and "텐키리스" in notes[0] and "우선" in notes[0]
    assert chat.conflict_notes(first, first) == []                     # 앞 턴에서 이미 알렸다


# ── 질문 답변: 결과가 필요 없는 것 ──────────────────────────────────────────────
def test_conditions_answer_lists_the_labels_of_that_kind():
    out = chat.static_answer(Question(type="conditions", kinds=["speaker"]), [], RULES)
    for label in ("책상 위 가벼운 감상", "블루투스", "북셸프"):
        assert label in out["text"]
    assert CHAT["examples"]["speaker"] in out["text"] and out["kinds"] == ["speaker"]


def test_conditions_answer_without_kind_asks_which_kind():
    out = chat.static_answer(Question(type="conditions"), [], RULES)
    assert out["text"] == CHAT["answers"]["no_kind"] and len(out["chips"]) == 4


def test_conditions_answer_uses_the_chosen_kinds_when_the_sentence_names_none():
    out = chat.static_answer(Question(type="conditions"), ["mouse", "keyboard"], RULES)
    assert out["kinds"] == ["keyboard", "mouse"] and "무선" in out["text"]


def test_term_answer_is_the_glossary_text_verbatim():
    out = chat.static_answer(Question(type="term", topic="래피드 트리거"), [], RULES)
    assert out["text"] == CHAT["glossary"]["래피드 트리거"]["text"]


def test_unknown_term_falls_back_to_out_of_scope():
    assert chat.static_answer(Question(type="term", topic="없는 용어"), [], RULES)["text"] == CHAT["answers"]["other"]


def test_capabilities_and_other_answers_come_with_chips():
    assert chat.static_answer(Question(type="capabilities"), [], RULES)["text"] == CHAT["answers"]["capabilities"]
    other = chat.static_answer(Question(type="other"), [], RULES)
    assert other["text"] == CHAT["answers"]["other"] and other["chips"] == CHAT["chips"]["start"]


# ── 질문 답변: 추천 결과로 답하는 것(없는 값을 지어내지 않는다) ─────────────────────────
def test_why_answer_repeats_the_reason_and_top_axes():
    result, payload = _run(["mouse"], purpose="game")
    out = chat.result_answer(Question(type="why"), result, payload, ["mouse"], None, RULES)
    item = payload["items"][0]
    assert item["product"]["name"] in out["text"] and item["reason"]["text"] in out["text"]
    top = sorted(item["score_detail"]["axes"], key=lambda a: -a["points"])[0]["axis"]
    assert top in out["text"]


def test_compare_answer_uses_the_alternatives_prices_and_gaps():
    result, payload = _run(["mouse"], purpose="game")
    out = chat.result_answer(Question(type="compare"), result, payload, ["mouse"], None, RULES)
    alts = payload["items"][0]["alternatives"]
    assert alts
    for alt in alts:
        assert alt["name"] in out["text"] and f"{alt['price']:,}원" in out["text"]
        assert f"{abs(alt['diff']):,}원" in out["text"] or alt["diff"] == 0


def test_spec_answer_reads_the_picked_products_specs():
    result, payload = _run(["mouse"], purpose="game")
    specs = result.picks[0].candidate.specs
    out = chat.result_answer(Question(type="spec", topic="weight"), result, payload, ["mouse"], None, RULES)
    if specs.get("weight_g") is not None:
        assert f"{specs['weight_g']:g}g" in out["text"]
    else:
        assert "정보가 없어요" in out["text"]


def test_spec_answer_says_so_when_the_value_is_missing():
    result, payload = _run(["mouse"], purpose="game")
    result.picks[0].candidate.specs.pop("weight_g", None)
    out = chat.result_answer(Question(type="spec", topic="weight"), result, payload, ["mouse"], None, RULES)
    assert "무게: 카탈로그에 정보가 없어요" in out["text"]


def test_spec_summary_without_topic_uses_the_kind_summary():
    result, payload = _run(["mouse"], purpose="game")
    out = chat.result_answer(Question(type="spec"), result, payload, ["mouse"], None, RULES)
    labels = [CHAT["spec_topics"][n]["label"] for n in CHAT["spec_summary"]["mouse"]]
    assert all(f"· {label}:" in out["text"] for label in labels)


def test_review_answer_without_evidence_says_there_is_none():
    result, payload = _run(["mouse"], purpose="game")
    payload["items"][0]["feel"] = None
    out = chat.result_answer(Question(type="review", topic="sound"), result, payload, ["mouse"], None, RULES)
    assert "근거가 아직 없어요" in out["text"] and "소리" in out["text"]


def test_review_answer_quotes_the_feel_rows_of_the_topic():
    result, payload = _run(["mouse"], purpose="game")
    payload["items"][0]["feel"] = {"attributes": [
        {"code": "click_sound", "label": "클릭 소리", "text": "조용한 편이라는 글이 많아요", "quotes": [{"sentence": "클릭이 조용해요"}]},
        {"code": "grip", "label": "그립 안정감", "text": "좋다는 글이 많아요", "quotes": []},
    ]}
    out = chat.result_answer(Question(type="review", topic="sound"), result, payload, ["mouse"], None, RULES)
    assert "클릭 소리: 조용한 편이라는 글이 많아요" in out["text"] and "“클릭이 조용해요”" in out["text"]
    assert "그립" not in out["text"]


def test_compat_answer_without_pc_says_to_connect_one():
    result, payload = _run(["monitor"], resolution="QHD_165")
    out = chat.result_answer(Question(type="compat"), result, payload, ["monitor"], None, RULES)
    assert out["text"] == CHAT["answers"]["no_pc"]


def test_compat_answer_for_non_monitor_has_nothing_to_cross_check():
    result, payload = _run(["mouse"], purpose="game")
    out = chat.result_answer(Question(type="compat"), result, payload, ["mouse"], {"resolution": "QHD_165"}, RULES)
    assert CHAT["answers"]["no_cross_check"] in out["text"]


def test_question_about_one_kind_answers_only_that_kind():
    result, payload = _run(["mouse", "keyboard"], purpose="game")
    out = chat.result_answer(Question(type="why", kinds=["keyboard"]), result, payload, ["mouse", "keyboard"], None, RULES)
    assert out["kinds"] == ["keyboard"]


def test_result_question_without_result_says_a_result_is_needed():
    out = chat.result_answer(Question(type="why"), None, None, ["mouse"], None, RULES)
    assert out["text"] == CHAT["answers"]["no_result"]


def test_empty_result_also_says_a_result_is_needed():
    result, payload = _run(["mouse"], peripheral_kind_budget={"mouse": 1})        # 예산 안에 드는 마우스가 없다
    out = chat.result_answer(Question(type="why"), result, payload, ["mouse"], None, RULES)
    assert out["text"] == CHAT["answers"]["no_result"]


# ── 답장 한 덩어리 ─────────────────────────────────────────────────────────
def test_reply_orders_new_conditions_then_answer_then_unreflected():
    reply = chat.compose_reply(
        [{"kind": "mouse", "label": "무선"}], ["‘묵직’ → 읽었어요."], ["상충을 정리했어요."],
        {"text": "답이에요."}, ["청축은 반영하지 못했어요."],
    )
    assert reply.split("\n") == ["이번에 반영했어요: 무선", "‘묵직’ → 읽었어요.", "상충을 정리했어요.", "답이에요.", "청축은 반영하지 못했어요."]


def test_reply_does_not_repeat_old_conditions_when_nothing_is_new():
    reply = chat.compose_reply([], [], [], None, [], example="발로란트 할 가벼운 무선 마우스 5만원 이하")
    assert reply.startswith("이번 문장에서는 새로 읽어 낸 조건이 없어요.") and "무선 마우스" in reply
    assert "이번에 반영했어요" not in reply

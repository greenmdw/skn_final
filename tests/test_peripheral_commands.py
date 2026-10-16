"""주변기기 채팅의 결과 화면 명령 — 빼기·조건 취소·다른 걸로·더 싸게·상대 금액·처음부터(10/16 실측: 모두 "새로 읽어 낸 조건이 없어요"로 끝났다).

명령은 낱말로만 가른다(언어 모델을 부르지 않는다). 추천이 필요한 명령은 픽스처 카탈로그로 엔진을 돌려 확인한다. DB·언어 모델 없이 돈다."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from src.agent import peripheral_intent_agent
from src.engine import peripheral_commands as pc
from src.engine import peripheral_intent as pi
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_intent import Interpretation
from src.engine.peripheral_payload import peripheral_payload
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import run_peripherals
from src.services import peripheral_chat_service, peripheral_interpret_service, peripherals_service

RULES = load_peripheral_rules()
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_CANDIDATES = load_peripheral_candidates_from_csv(_FIXTURES, RULES)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """언어 모델을 쓰지 않고, 추천은 픽스처 카탈로그로 엔진을 그대로 돌린다(DB 없이)."""
    monkeypatch.setattr(peripheral_intent_agent, "available", lambda: False)
    peripheral_interpret_service.clear_cache()

    def recommend(_conn, body, pc_context):
        interp, _ignored = peripherals_service._intent_from_body(body)
        values = {"peripherals": body.kinds, "peripheral_budget_max": body.budget_max, "peripheral_kind_budget": interp.budget,
                  "peripheral_kind_budget_min": interp.budget_min, "peripheral_intent": interp,
                  "peripheral_resolved": pi.resolve(interp), "peripheral_exclude": interp.exclude,
                  "peripheral_brand_avoid": interp.brand_avoid}
        result = run_peripherals(values, _CANDIDATES, lambda _m: None, pc_context=pc_context)
        return peripheral_payload(result), result

    monkeypatch.setattr(peripherals_service, "recommend_detailed", recommend)
    yield
    peripheral_interpret_service.clear_cache()


@contextmanager
def _conn():
    yield object()


def _turn(text, previous=None, kinds=None):
    return peripheral_chat_service.turn(text, previous, kinds, pc_list_id=None, pc_context=None, open_conn=_conn)


def _prev(out):
    return out["interpretation"].model_dump()


def _pick(interp: Interpretation, kind: str):
    _payload, result = peripherals_service.recommend_detailed(None, peripheral_chat_service._recommend_body(interp, None), None)
    return next(p.candidate for p in result.picks if p.kind == kind)


# ── 가르기 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, context, expected", [
    ("마우스 다른 걸로 바꿔줘", ["mouse", "keyboard"], ("swap", ["mouse"], 0)),
    ("다른 거 없어?", ["mouse"], ("swap", ["mouse"], 0)),                       # 종류가 하나뿐인 대화
    ("키보드는 빼줘", ["mouse", "keyboard"], ("remove", ["keyboard"], 0)),
    ("아까 무선 조건 취소", ["mouse"], ("remove", [], 0)),
    ("스피커 필요 없어요", ["mouse", "speaker"], ("remove", ["speaker"], 0)),
    ("마우스 3만원 더 싸게", ["mouse", "keyboard"], ("relative_budget", ["mouse"], -30000)),
    ("만원 더 싸게", ["mouse"], ("relative_budget", ["mouse"], -10000)),
    ("5만원 올려줘", ["monitor"], ("relative_budget", ["monitor"], 50000)),
    ("더 싼 걸로", ["mouse"], ("cheaper", ["mouse"], 0)),
    ("처음부터 다시", ["mouse"], ("reset", [], 0)),
])
def test_result_screen_commands_are_recognised(text, context, expected):
    command = pc.detect(text, context, RULES)
    assert command is not None and (command.type, command.kinds, command.delta) == expected


@pytest.mark.parametrize("text", [
    "무선 말고 유선 마우스",        # 상충 조건 — 해석이 나중 말을 이기게 한다
    "로지텍 빼줘",                  # 브랜드가 있으면 기피 브랜드다
    "RGB 빼고 조용한 키보드",       # 빼기 낱말 뒤에 조건이 이어진다 — 조건 문장
    "무선으로 바꿔줘",              # 조건 낱말이 있다 — 조건 문장
    "20만원으로 줄여줘",            # "으로" — 정한 금액이다(상대 금액이 아니다)
    "게임용 마우스",
    "조용한 키보드 찾아줘",
])
def test_condition_sentences_are_not_commands(text):
    assert pc.detect(text, ["mouse", "keyboard"], RULES) is None


# ── 빼기·처음부터 ──────────────────────────────────────────────────────────
def test_removing_a_kind_drops_it_and_its_conditions():
    first = _turn("무선 마우스랑 조용한 키보드 15만원", None, ["mouse", "keyboard"])
    out = _turn("키보드는 빼줘", _prev(first), ["mouse", "keyboard"])      # 화면은 고른 카드를 그대로 보낸다
    interp = out["interpretation"]
    assert interp.kinds == ["mouse"] and "keyboard" not in interp.stated and "keyboard" not in interp.budget
    assert out["turn"]["command"] == "remove" and out["turn"]["removed_conditions"]
    assert out["turn"]["reply"] == "키보드를 품목에서 뺐어요."


def test_cancelling_a_condition_removes_only_that_condition():
    first = _turn("무선 마우스 5만원", None, ["mouse"])
    out = _turn("아까 무선 조건 취소", _prev(first), ["mouse"])
    assert out["interpretation"].stated == {} and out["interpretation"].budget == {"mouse": 50000}
    assert [c["label"] for c in out["turn"]["removed_conditions"]] == ["무선"] and out["turn"]["reply"] == "뺐어요: 무선"


def test_cancelling_nothing_says_so_and_changes_nothing():
    first = _turn("무선 마우스 5만원", None, ["mouse"])
    out = _turn("블루투스 취소", _prev(first), ["mouse"])
    assert out["interpretation"] == first["interpretation"] and not out["turn"]["removed_conditions"]
    assert out["turn"]["reply"].startswith("뺄 조건을 찾지 못했어요")


def test_reset_clears_conditions_but_keeps_the_chosen_kinds():
    first = _turn("무선 마우스랑 조용한 키보드 15만원", None, ["mouse", "keyboard"])
    out = _turn("처음부터 다시", _prev(first), ["mouse", "keyboard"])
    assert out["interpretation"] == Interpretation(kinds=["keyboard", "mouse"]) and out["turn"]["reset"] is True
    assert "키보드·마우스" in out["turn"]["reply"]


# ── 다른 걸로 ──────────────────────────────────────────────────────────────
def test_swap_excludes_the_current_first_and_names_the_replacement():
    first = _turn("게임용 마우스", None, ["mouse"])
    before = _pick(first["interpretation"], "mouse")
    out = _turn("다른 걸로 바꿔줘", _prev(first), ["mouse"])
    after = _pick(out["interpretation"], "mouse")
    assert out["interpretation"].exclude == {"mouse": [before.name]} and after.name != before.name
    assert out["turn"]["reply"].startswith(f"마우스를 바꿨어요: {before.name}") and after.name in out["turn"]["reply"]
    assert out["turn"]["new_conditions"] == [{"kind": "mouse", "label": f"마우스에서 뺀 제품: {before.name}"}]

    again = _turn("다른 거 없어?", _prev(out), ["mouse"])      # 되풀이하면 쌓인다
    assert again["interpretation"].exclude == {"mouse": [before.name, after.name]}


def test_swap_with_no_other_candidate_changes_nothing():
    previous = Interpretation(kinds=["mouse"], exclude={"mouse": [c.name for c in _CANDIDATES["mouse"]][1:]})
    out = _turn("다른 걸로", previous.model_dump(), ["mouse"])
    assert out["interpretation"].exclude == previous.exclude and "후보가 없어 바꾸지 않았어요" in out["turn"]["reply"]


def test_swap_without_a_kind_in_a_multi_kind_chat_asks_which():
    first = _turn("무선 마우스랑 조용한 키보드", None, ["mouse", "keyboard"])
    out = _turn("다른 걸로 바꿔줘", _prev(first), ["mouse", "keyboard"])
    assert out["interpretation"] == first["interpretation"] and out["turn"]["reply"] == "어느 품목을 바꿀까요?"
    assert out["turn"]["chips"] == ["키보드 다른 걸로", "마우스 다른 걸로"]


def test_excluded_products_are_dropped_by_the_engine_and_survive_sanitize():
    interp = pi.sanitize({"kinds": ["mouse"], "exclude": {"mouse": ["Logitech G502 X", " "], "gpu": ["x"]}}, RULES)
    assert interp.exclude == {"mouse": ["Logitech G502 X"]}
    assert all(_pick(interp, "mouse").name != "Logitech G502 X" for _ in range(1))


# ── 더 싸게·상대 금액 ──────────────────────────────────────────────────────
def test_cheaper_sets_the_budget_below_the_current_first():
    first = _turn("fps용 마우스", None, ["mouse"])            # 픽스처에서 1위가 가장 비싼 쪽(188,200원)
    before = _pick(first["interpretation"], "mouse")
    out = _turn("더 싼 걸로", _prev(first), ["mouse"])
    budget = out["interpretation"].budget["mouse"]
    assert budget < before.price and _pick(out["interpretation"], "mouse").price <= budget
    assert out["turn"]["reply"].startswith(f"마우스 예산을 {budget:,}원으로 바꿔 다시 골랐어요")


def test_cheaper_when_the_first_is_already_the_cheapest_says_so():
    first = _turn("마우스 추천해줘", None, ["mouse"])
    before = _pick(first["interpretation"], "mouse")
    out = _turn("더 싼 걸로", _prev(first), ["mouse"])
    assert out["interpretation"].budget == {} and out["turn"]["reply"] == f"지금 마우스 1위 {before.name}({before.price:,}원)보다 싼 후보는 조건에 맞는 게 없어요."


def test_relative_budget_moves_the_stated_budget():
    first = _turn("마우스 15만원", None, ["mouse"])
    out = _turn("5만원 더 싸게", _prev(first), ["mouse"])
    assert out["interpretation"].budget == {"mouse": 100000}
    assert out["turn"]["new_conditions"] == [{"kind": "mouse", "label": "마우스 예산 100,000원"}]


def test_raising_the_budget_looks_above_the_current_first():
    """예산만 올리면 가격 축이 오히려 싼 제품을 올린다(실측 125,000원 → 38,480원) — 지금 1위보다 비싼 쪽에서 고른다."""
    first = _turn("마우스 추천해줘", None, ["mouse"])
    before = _pick(first["interpretation"], "mouse")
    out = _turn("5만원 올려줘", _prev(first), ["mouse"])
    interp = out["interpretation"]
    assert interp.budget == {"mouse": before.price + 50000} and interp.budget_min["mouse"] > before.price
    assert _pick(interp, "mouse").price > before.price


def test_relative_budget_without_a_kind_moves_the_total_in_a_multi_kind_chat():
    first = _turn("모니터랑 마우스 다 합쳐서 60만원", None, ["monitor", "mouse"])
    assert first["interpretation"].budget_total == 600000
    out = _turn("3만원 더 싸게", _prev(first), ["monitor", "mouse"])
    assert out["interpretation"].budget_total == 570000 and out["turn"]["reply"] == "예산 합계를 570,000원으로 바꿨어요."


def test_lowering_below_every_candidate_is_refused():
    first = _turn("마우스 4만원", None, ["mouse"])
    out = _turn("3만원 더 싸게", _prev(first), ["mouse"])       # 1만 원 이하 마우스는 픽스처에 없다
    assert out["interpretation"].budget == {"mouse": 40000}
    assert out["turn"]["reply"] == "마우스 예산 10,000원에는 조건에 맞는 후보가 없어 바꾸지 않았어요."

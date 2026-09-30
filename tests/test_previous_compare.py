"""이전 견적 비교(B1) — 순수 비교 함수. 인과는 요구사양이 실제로 달라진 부품에만 붙는지 본다."""
from __future__ import annotations

from src.services.previous_compare import compare
from src.services.recommendation_service import _is_previous_comparison_request

BASE = {"category": "computer", "mode": "build", "purpose": "game", "budget_max": 1_500_000,
        "priority": "value", "resolution": "FHD_144", "games": ["오버워치"]}


def _result(**parts: tuple[str, int]) -> dict:
    labels = {"GPU": "그래픽카드", "CPU": "CPU", "RAM": "RAM", "파워": "파워"}
    return {"items": [{"slot": slot, "slot_label": labels[slot], "product": {"name": name},
                       "price": price, "qty": 1, "selected": True} for slot, (name, price) in parts.items()]}


BEFORE = _result(GPU=("RTX 4060", 400_000), CPU=("i5-14400F", 250_000), RAM=("DDR5 16GB", 60_000))


def _reason(c: dict, slot: str) -> dict:
    return next(r for r in c["reasons"] if r["slot"] == slot)


def test_resolution_change_explains_the_gpu_upgrade_and_keeps_the_rest():
    after = _result(GPU=("RTX 4070", 700_000), CPU=("i5-14400F", 250_000), RAM=("DDR5 16GB", 60_000))
    c = compare(BASE, {**BASE, "resolution": "QHD_165"}, BEFORE, after, "9월 25일")
    reason = _reason(c, "GPU")
    assert reason["kind"] == "requirement"
    assert "그래픽 성능 등급 6 → 7" in reason["claim"]
    assert reason["evidence"] == ["해상도·주사율 FHD 144Hz → QHD 165Hz"]
    assert c["unchanged"] == ["CPU", "RAM"]
    assert c["totals"]["diff"] == 300_000
    assert "RTX 4060(400,000원) → RTX 4070(700,000원) (+300,000원)" in c["text"]
    assert "근거: 해상도·주사율 FHD 144Hz → QHD 165Hz" in c["text"]
    assert c["caveats"] == []


def test_game_change_that_does_not_raise_the_requirement_is_not_given_as_the_cause():
    # 오버워치(GPU 4)·배그(GPU 5) 모두 FHD 기준(6)보다 낮다 — 요구는 그대로이므로 원인을 지어내지 않는다.
    after = _result(GPU=("RX 7600", 380_000), CPU=("i5-14400F", 250_000), RAM=("DDR5 16GB", 60_000))
    c = compare(BASE, {**BASE, "games": ["배틀그라운드"]}, BEFORE, after, "9월 25일")
    reason = _reason(c, "GPU")
    assert reason["kind"] == "unexplained" and reason["evidence"] == []
    assert "요구 사양은 그대로예요" in c["text"]
    assert c["condition_changes"][0]["key"] == "games"
    assert c["caveats"] == [], "게임 표를 근거로 쓰지 않았으면 잠정값 안내도 없다"


def test_heavier_game_is_named_as_the_cause_with_its_table_value():
    after = _result(GPU=("RTX 4070", 700_000), CPU=("i5-14400F", 250_000), RAM=("DDR5 16GB", 60_000))
    c = compare(BASE, {**BASE, "games": ["오버워치", "사이버펑크"]}, BEFORE, after, "9월 25일")
    reason = _reason(c, "GPU")
    assert reason["kind"] == "requirement"
    assert reason["evidence"] == ["사이버펑크 추가(그래픽 성능 등급 7 요구)"]
    assert not any("오버워치" in e and "추가" in e for e in reason["evidence"])
    assert c["caveats"], "게임 표가 잠정값이면 그렇다고 적는다"


def test_only_the_condition_that_moves_the_requirement_is_cited():
    # 해상도와 우선순위가 함께 바뀌어도 GPU 요구를 올린 건 해상도뿐 — 우선순위는 원인으로 적지 않는다.
    after = _result(GPU=("RTX 4070", 700_000), CPU=("i5-14400F", 250_000), RAM=("DDR5 16GB", 60_000))
    c = compare(BASE, {**BASE, "resolution": "QHD_165", "purpose": "game", "priority": "performance"},
                BEFORE, after, "9월 25일")
    assert _reason(c, "GPU")["evidence"] == ["해상도·주사율 FHD 144Hz → QHD 165Hz"]
    assert {x["key"] for x in c["condition_changes"]} == {"resolution", "priority"}


def test_same_build_says_so():
    c = compare(BASE, BASE, BEFORE, BEFORE, "9월 25일")
    assert c["part_changes"] == [] and c["reasons"] == []
    assert "조건은 같아요" in c["text"] and "부품 구성도 같아요" in c["text"]
    assert c["totals"]["diff"] == 0


def test_comparison_request_wording():
    assert _is_previous_comparison_request("지난번이랑 뭐가 달라?")
    assert _is_previous_comparison_request("저번 견적이랑 비교해줘")
    assert not _is_previous_comparison_request("그래픽카드 더 저렴한 걸로")
    assert not _is_previous_comparison_request("지난번 거 좋았어")

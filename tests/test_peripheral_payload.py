"""주변기기 payload 가공(E13) 테스트 — src/engine/peripheral_payload.py.

DB 불필요. 다룬다: skipped/empty/ready 상태별 모양과 필드 집합 고정(스냅샷), price_note
고정 문구, checks 병합(E12 축 중복 제거 + verify_per_item judge->state 매핑), alternatives
diff, reason 규칙 템플릿(판정어·confidence 숫자 없음), requirement의 assumed 해상도 안내,
guide none(4종) + search_care_guide가 임베딩 없이도 즉시 빈 결과를 내는지(SLOT_GUIDE_IDS 등록).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.dto import (Candidate, Issue, PeripheralPick, PeripheralRequirement, PeripheralResult,
                     VerificationResult, VerificationTarget)
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_payload import _requirement_rows, peripheral_payload
from src.engine.peripheral_requirement import build_requirements
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import run_peripherals
from src.schemas import PeripheralItemOut
from src.engine.stage3c_verify import _BANNED_KOREAN_VERDICTS
from src.rag.care_guides import SLOT_GUIDE_IDS, search_care_guide

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_NOLOG = lambda _m: None  # noqa: E731

_TOP_KEYS = {"status", "items", "empty", "totals"}
_ITEM_KEYS = {"kind", "kind_label", "product", "price", "price_source", "price_note",
              "requirement", "checks", "reason", "alternatives", "guide", "review",
              "review_weight", "review_note"}
_PRODUCT_KEYS = {"name", "brand", "variant_id", "product_url", "image_url"}


def _rules():
    return load_peripheral_rules()


def _candidates():
    return load_peripheral_candidates_from_csv(_FIXTURES, _rules())


def _ready_result(kinds, **extra_values):
    values = {"peripherals": kinds, **extra_values}
    return run_peripherals(values, _candidates(), _NOLOG)


# ── status: skipped/empty ────────────────────────────────────────────────
def test_skipped_shape():
    payload = peripheral_payload(PeripheralResult(status="skipped"))
    assert set(payload) == _TOP_KEYS
    assert payload["status"] == "skipped"
    assert payload["items"] == []
    assert payload["empty"] == []
    assert payload["totals"] == {"reference_price": 0, "note": "PC 예산과 별도"}


def test_empty_shape_carries_reason():
    result = PeripheralResult(status="empty", empty=[{"kind": "monitor", "reason": "이유"}])
    payload = peripheral_payload(result)
    assert set(payload) == _TOP_KEYS
    assert payload["status"] == "empty"
    assert payload["items"] == []
    assert payload["empty"] == [{"kind": "monitor", "reason": "이유"}]
    assert payload["totals"]["reference_price"] == 0


def test_run_peripherals_fhd144_empty_status_becomes_empty_payload():
    """C6(계획 §1) — 기본 해상도 FHD_144엔 144Hz 이상 모니터가 없어 run_peripherals가
    이미 status="empty"를 낸다. payload는 그 이유를 그대로 옮긴다."""
    result = _ready_result(["monitor"], resolution="FHD_144")
    assert result.status == "empty"
    payload = peripheral_payload(result)
    assert payload["status"] == "empty"
    assert payload["empty"] == [{"kind": "monitor",
                                 "reason": "FHD·144Hz 이상 조건에 맞는 모니터가 카탈로그에 없습니다"}]


# ── status: ready — 필드 집합 고정(스냅샷) ─────────────────────────────────
def test_ready_top_and_item_key_sets_are_fixed():
    result = _ready_result(["monitor", "mouse"], resolution="QHD_165", purpose="game")
    payload = peripheral_payload(result)
    assert payload["status"] == "ready"
    assert set(payload) == _TOP_KEYS
    assert len(payload["items"]) == 2
    for item in payload["items"]:
        assert set(item) == _ITEM_KEYS
        assert set(item["product"]) == _PRODUCT_KEYS
        # catalog.product.image_url이 실재하고 CSV "이미지 URL" 열도 채워져 있다(E13 감사
        # 정정) — 두 픽스처 후보(모니터·마우스) 다 이미지가 있으므로 None이면 회귀다.
        assert item["product"]["image_url"] is not None
        assert item["product"]["image_url"].startswith("https://")
        assert item["reason"].keys() == {"status", "text"}
        assert item["reason"]["status"] == "ready"
        for row in item["requirement"]:
            assert set(row) == {"key", "label", "value"}
        for check in item["checks"]:
            assert set(check) == {"axis", "label", "state", "detail"}
            assert check["state"] in ("ok", "unknown", "fail")
        for alt in item["alternatives"]:
            assert set(alt) == {"name", "price", "diff", "review", "review_weight", "review_note"}
            assert alt["review_weight"] == 0.0
            assert alt["review_note"]
        assert item["guide"].keys() == {"status", "text"}
        PeripheralItemOut.model_validate(item)


def test_ready_totals_is_sum_of_picked_prices():
    result = _ready_result(["monitor", "mouse"], resolution="QHD_165", purpose="game")
    payload = peripheral_payload(result)
    expected = sum(p.candidate.price for p in result.picks)
    assert payload["totals"]["reference_price"] == expected
    assert payload["totals"]["note"] == "PC 예산과 별도"


def test_price_note_is_fixed_text_and_reuses_price_note_constant():
    from src.engine.peripheral_catalog import PRICE_NOTE

    result = _ready_result(["mouse"], purpose="game")
    payload = peripheral_payload(result)
    note = payload["items"][0]["price_note"]
    assert note == "판매처·관측일 미확인 참고가 — 구매 가능 가격이 아닙니다"
    assert note.startswith(PRICE_NOTE)   # peripheral_catalog.PRICE_NOTE를 그대로 재사용한다


def test_alternatives_diff_is_price_minus_pick_price():
    result = _ready_result(["mouse"], purpose="game")
    payload = peripheral_payload(result)
    item = payload["items"][0]
    pick_price = result.picks[0].candidate.price
    assert len(item["alternatives"]) == len(result.picks[0].alternatives)
    for alt_dict, alt_cand in zip(item["alternatives"], result.picks[0].alternatives):
        assert alt_dict["name"] == alt_cand.name
        assert alt_dict["price"] == alt_cand.price
        assert alt_dict["diff"] == alt_cand.price - pick_price
        assert alt_dict["review"] == (alt_cand.review_detail.model_dump(mode="json")
                                       if alt_cand.review_detail else None)


# ── reason: 규칙 템플릿, 판정어·confidence 숫자 없음 ─────────────────────
def test_reason_text_has_no_verdict_words_or_confidence_score_digits():
    result = _ready_result(["monitor", "mouse"], resolution="QHD_165", purpose="game")
    payload = peripheral_payload(result)
    for item in payload["items"]:
        text = item["reason"]["text"]
        assert not any(word in text for word in _BANNED_KOREAN_VERDICTS)
        assert not re.search(r"\d+\s*점", text)   # "94점" 류 신뢰도 숫자 금지(결정 0003)


def test_reason_text_mentions_hard_goal_and_rank():
    result = _ready_result(["monitor"], resolution="QHD_165", purpose="game")
    payload = peripheral_payload(result)
    text = payload["items"][0]["reason"]["text"]
    assert "QHD" in text and "165Hz" in text
    assert "조건 충족" in text   # 모니터는 hard 조건(해상도·주사율)이 있다
    assert "위" in text   # "N개 중 M위"


def test_reason_text_no_condition_satisfied_wording_for_kind_without_hard():
    """키보드는 hard 조건이 없다(계획 §3.3 E10) — kept 후보가 "조건을 충족해서" 남은 게
    아니므로 "조건 충족"이라고 쓰면 실제로 없던 필터링이 있었던 것처럼 보인다."""
    result = _ready_result(["keyboard"])
    assert result.status == "ready"
    text = result and peripheral_payload(result)["items"][0]["reason"]["text"]
    assert "조건 충족" not in text
    assert "후보" in text and "위" in text


def test_reason_text_mentions_soft_preferences_briefly_without_naming_spec():
    result = _ready_result(["keyboard"], priority="quiet")
    text = peripheral_payload(result)["items"][0]["reason"]["text"]
    assert "조건 충족" not in text
    assert "선호 조건 반영" in text


# ── requirement: hard/soft + assumed 해상도 안내 ───────────────────────────
def test_requirement_rows_include_assumed_resolution_note_when_no_condition():
    req = build_requirements({}, ["monitor"], _rules())["monitor"]
    rows = _requirement_rows(req)
    keys = [r["key"] for r in rows]
    assert "resolution_assumed" in keys
    assumed_row = next(r for r in rows if r["key"] == "resolution_assumed")
    assert assumed_row["value"]   # 안내 문장이 비어 있지 않다


def test_requirement_rows_no_assumed_note_when_resolution_given():
    req = build_requirements({"resolution": "QHD_165"}, ["monitor"], _rules())["monitor"]
    rows = _requirement_rows(req)
    assert "resolution_assumed" not in [r["key"] for r in rows]
    assert {"key": "resolution_class", "label": "요구 해상도 등급", "value": "QHD"} in rows


# ── checks 병합: E12 축 중복 없이, judge -> state 매핑 ─────────────────────
def test_checks_merges_e12_and_per_item_without_duplicating_axis():
    cand = Candidate(product_key="m1", slot="monitor", name="테스트모니터", price=100000, rank=1)
    pick = PeripheralPick(
        kind="monitor", candidate=cand,
        checks=[{"axis": "monitor_gpu_port", "label": "라벨", "state": "unknown", "detail": "GPU 정보 없음"}],
    )
    dup_issue = Issue(axis="monitor_gpu_port", text="중복이면 안 됨", judge="확인 필요", penalty=6)
    hard_issue = Issue(axis="monitor_hard", text="필수 조건 확인 못함", judge="확인 필요", penalty=6)
    fail_issue = Issue(axis="monitor_extra", text="문제 있음", judge="위반", penalty=20)
    target = VerificationTarget(
        subject="모니터", confidence=100, passed=True, issues=[dup_issue, hard_issue, fail_issue],
        transcript=[{"kind": "monitor", "issues": []}],
    )
    verification = VerificationResult(list_id="peripherals", category="computer", mode="per_item", targets=[target])
    result = PeripheralResult(status="ready", picks=[pick], verification=verification,
                              requirements={"monitor": PeripheralRequirement(kind="monitor")})
    payload = peripheral_payload(result)
    checks = payload["items"][0]["checks"]
    axes = [c["axis"] for c in checks]
    assert axes.count("monitor_gpu_port") == 1   # 중복 제거
    by_axis = {c["axis"]: c for c in checks}
    assert by_axis["monitor_gpu_port"]["detail"] == "GPU 정보 없음"   # pick.checks 쪽이 유지된다
    assert by_axis["monitor_hard"]["state"] == "unknown"
    assert by_axis["monitor_hard"]["label"] == "필수 조건 확인 불가"
    assert by_axis["monitor_extra"]["state"] == "fail"
    assert by_axis["monitor_extra"]["detail"] == "문제 있음"


def test_checks_empty_when_no_verification_and_no_e12_checks():
    cand = Candidate(product_key="s1", slot="speaker", name="스피커", price=10000, rank=1)
    pick = PeripheralPick(kind="speaker", candidate=cand)
    result = PeripheralResult(status="ready", picks=[pick],
                              requirements={"speaker": PeripheralRequirement(kind="speaker")})
    payload = peripheral_payload(result)
    assert payload["items"][0]["checks"] == []


# ── guide: 4종 전부 none, 임베딩 호출 없음 ─────────────────────────────────
@pytest.mark.parametrize("kind", ["monitor", "keyboard", "mouse", "speaker"])
def test_slot_guide_ids_registers_peripheral_kinds_as_empty(kind):
    assert SLOT_GUIDE_IDS.get(kind) == ()


def test_ready_payload_guide_is_none_without_embedding_calls(monkeypatch):
    import src.rag.care_guides as care_guides

    def _boom(*_a, **_kw):
        raise AssertionError("가이드가 없는 종류인데 임베딩을 불렀다")

    monkeypatch.setattr(care_guides, "_load_guides", _boom)
    result = _ready_result(["mouse"], purpose="game")
    payload = peripheral_payload(result)
    assert payload["items"][0]["guide"] == {"status": "none", "text": "이 품목의 사용 가이드는 아직 없습니다"}


def test_search_care_guide_with_registered_empty_tuple_returns_no_results(monkeypatch):
    """SLOT_GUIDE_IDS에 monitor=()로 등록돼 있으면 allowed=()라 어떤 문서와도 안 걸린다 —
    등록을 빼먹으면(allowed=None) search_care_guide가 전 문서(PC용 포함)를 검색해 엉뚱한
    가이드가 새어 들어온다(계획 §3.3 E13). _load_guides/_embed를 목으로 바꿔 실제 모델을
    로드하지 않고 확인한다."""
    import src.rag.care_guides as care_guides

    fake_docs = ({"id": "gpu_power", "text": "GPU 전원 가이드"},)
    fake_embeddings = ((1.0, 0.0),)
    monkeypatch.setattr(care_guides, "_load_guides", lambda: (fake_docs, fake_embeddings))
    monkeypatch.setattr(care_guides, "_embed", lambda texts: [(1.0, 0.0) for _ in texts])

    assert search_care_guide("아무 질의", slot="monitor") == []
    assert search_care_guide("아무 질의", slot="keyboard") == []
    assert search_care_guide("아무 질의", slot="mouse") == []
    assert search_care_guide("아무 질의", slot="speaker") == []

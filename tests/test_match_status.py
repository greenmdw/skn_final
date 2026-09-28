"""매칭 상태 세분화(match_status) — state(ok/warn) 두 가지로는 화면이 "확정"과 "여러 후보 중
공통값만 씀(모호함)"을 구분하지 못해 추가했다. 목업(2026-09-28) 검토에서 나온 요구사항:
"대응됨"(confirmed) / "모호함"(ambiguous, 후보 개수 포함) / "대응 제품 없음"(unmatched)을 구분해서 보여준다.
"""
from __future__ import annotations

from src.dto import Candidate
from src.engine.owned_parts import preview_current_specs, resolve_owned_parts

SLOT_STRUCTURE = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]


def _cand(slot, name, **specs):
    return Candidate(slot=slot, product_key=name, name=name, price=1, specs=specs)


# 목업의 "메인보드 B760M 보드 (DDR5) — 후보 3개 · 공통값만 사용" 사례와 같은 모양: 글에 용량을 안 적어서
# 용량만 다른 후보 여럿이 동점으로 남는다(이 프로젝트에서 이미 검증된 대표적인 동점 패턴).
AMBIGUOUS_POOL = {
    "GPU": [
        _cand("GPU", "NVIDIA GeForce RTX 3050 (6GB)", perf_tier=3, vram_gb=6),
        _cand("GPU", "NVIDIA GeForce RTX 3050 (8GB)", perf_tier=3, vram_gb=8),
        _cand("GPU", "NVIDIA GeForce RTX 3050 (12GB)", perf_tier=3, vram_gb=12),
    ],
}


def test_a_single_catalog_match_is_confirmed():
    pool = {"CPU": [_cand("CPU", "AMD Ryzen 7 7800X3D", socket="AM5")]}
    row = preview_current_specs({"CPU": "Ryzen 7 7800X3D"}, pool, SLOT_STRUCTURE)[0]
    assert row["match_status"] == "confirmed" and row["candidate_count"] is None and row["state"] == "ok"


def test_several_tied_candidates_are_ambiguous_with_a_count():
    row = preview_current_specs({"GPU": "RTX 3050"}, AMBIGUOUS_POOL, SLOT_STRUCTURE)[0]
    assert row["match_status"] == "ambiguous" and row["candidate_count"] == 3
    assert row["state"] == "ok"                          # state 는 하위 호환을 위해 그대로(카탈로그 대응은 맞음)
    assert "후보 3개" in row["matched_note"] and "공통값만 사용" in row["matched_note"]


def test_the_nearest_candidate_case_is_still_its_own_status_not_ambiguous():
    pool = {"CPU": [_cand("CPU", "AMD Ryzen 7 5800X3D", socket="AM4")]}
    row = preview_current_specs({"CPU": "5800X3D"}, pool, SLOT_STRUCTURE)[0]
    assert row["match_status"] == "candidate" and row["candidate_count"] is None


def test_no_match_at_all_is_unmatched():
    row = preview_current_specs({"GPU": "존재하지 않는 그래픽카드"}, {"GPU": []}, SLOT_STRUCTURE)[0]
    assert row["match_status"] == "unmatched" and row["candidate_count"] is None


def test_text_read_specs_without_a_catalog_match_are_inferred():
    row = preview_current_specs({"CPU": "i5-13600K"}, {"CPU": []}, SLOT_STRUCTURE)[0]
    assert row["match_status"] == "inferred" and row["candidate_count"] is None


def test_ambiguous_ties_still_carry_the_common_specs_for_downstream_checks():
    """모호해도 공통 스펙은 안전하게 쓸 수 있다 — 호환 검사 등 다른 계산까지 막지 않는다."""
    owned = resolve_owned_parts({"GPU": "RTX 3050"}, AMBIGUOUS_POOL, ["GPU"])["GPU"]
    assert owned["source"] == "catalog" and owned["candidate_count"] == 3
    assert owned["specs"] == {"perf_tier": 3}             # vram_gb 는 갈려서 공통값에서 빠짐(6/8/12GB)


def test_ambiguous_catalog_price_is_none_when_candidates_differ_in_price():
    pool = {"GPU": [
        _cand("GPU", "NVIDIA GeForce RTX 3050 (6GB)", perf_tier=3).model_copy(update={"price": 250_000}),
        _cand("GPU", "NVIDIA GeForce RTX 3050 (8GB)", perf_tier=3).model_copy(update={"price": 280_000}),
    ]}
    owned = resolve_owned_parts({"GPU": "RTX 3050"}, pool, ["GPU"])["GPU"]
    assert owned["candidate_count"] == 2 and owned["catalog_price"] is None

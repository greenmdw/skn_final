"""[3-B] "호환여유" 축 — 예전엔 모든 후보가 상수 0.5를 받았다. 이제 CPU/GPU는
[2]가 계산해 둔 전력 예산 대비 실측 여유를, 파워는 요구 전력 대비 용량 여유를
실제로 계산하는지 확인한다. 다른 슬롯이 뭘 뽑을지 이 시점엔 모르므로, target
자체가 들고 있는 기준치와의 여유만 본다는 한계도 같이 문서화한다."""
from __future__ import annotations

from src.dto import Candidate
from src.engine.stage3b_rank import _compat_margin


def _cand(**specs) -> Candidate:
    return Candidate(product_key="k", slot="s", name="n", brand="b", price=1000, specs=specs)


def test_cpu_margin_is_higher_when_actual_tdp_is_well_under_budget():
    low_power = _compat_margin(_cand(tdp_w=65), "CPU", {"tdp_budget_w": 125})
    near_budget = _compat_margin(_cand(tdp_w=120), "CPU", {"tdp_budget_w": 125})
    assert low_power > near_budget
    assert 0.0 <= near_budget <= 1.0


def test_gpu_margin_missing_actual_or_budget_falls_back_to_neutral():
    assert _compat_margin(_cand(), "GPU", {"tgp_budget_w": 300}) == 0.5
    assert _compat_margin(_cand(power_w=300), "GPU", {}) == 0.5


def test_psu_margin_rewards_headroom_over_the_required_wattage():
    tight = _compat_margin(_cand(wattage_w=560), "파워", {"wattage_min": 550})
    roomy = _compat_margin(_cand(wattage_w=850), "파워", {"wattage_min": 550})
    assert roomy > tight
    assert tight >= 0.0


def test_psu_margin_is_zero_when_wattage_is_below_the_requirement():
    # 요구보다 낮으면(정상적으로는 하드필터에서 이미 Fail 처리되겠지만) 마이너스가
    # 아니라 0으로 클램프된다 — 점수를 깎는 게 아니라 "여유 없음"으로만 표현.
    assert _compat_margin(_cand(wattage_w=400), "파워", {"wattage_min": 550}) == 0.0


def test_slots_without_a_defined_margin_stay_neutral():
    # RAM/메인보드/저장장치/케이스/쿨러는 target에 전력 기준치가 없어 아직 계산
    # 대상이 아니다 — 중립값 0.5로 남아 점수에 영향을 주지 않는다.
    assert _compat_margin(_cand(), "RAM", {"capacity_gb_min": 32}) == 0.5
    assert _compat_margin(_cand(), "케이스", {}) == 0.5

"""[3-A] 하드필터의 PC 부품 체크 — 예전엔 perf_tier만 보고 socket/vram/capacity/
wattage/plus_rating은 TODO로 비워둔 채 전부 통과시켰다. 이제 실제로 비교하는지,
그리고 정보가 없을 때는 여전히 Fail이 아니라 Pending으로 남는지 확인한다."""
from __future__ import annotations

from src.dto import Candidate
from src.engine.stage3a_hardfilter import _judge_computer


def _cand(**specs) -> Candidate:
    return Candidate(product_key="k", slot="s", name="n", brand="b", price=1000, specs=specs)


def test_socket_mismatch_fails_when_both_sides_known():
    out = _judge_computer(_cand(socket="LGA1700"), {"socket_in": ["AM5", "AM4"]})
    assert out.verdict == "Fail"
    assert any("SOCKET" in r for r in out.reasons)


def test_socket_match_passes():
    out = _judge_computer(_cand(socket="AM5"), {"socket_in": ["AM5", "AM4"]})
    assert out.verdict == "Pass"


def test_missing_socket_is_pending_not_fail():
    out = _judge_computer(_cand(), {"socket_in": ["AM5"]})
    assert out.verdict == "Pending"
    assert "PENDING_SPEC_MISSING:socket" in out.reasons


def test_vram_below_minimum_fails():
    out = _judge_computer(_cand(vram_gb=8), {"vram_gb_min": 12})
    assert out.verdict == "Fail"


def test_vram_meets_minimum_passes():
    out = _judge_computer(_cand(vram_gb=16), {"vram_gb_min": 12})
    assert out.verdict == "Pass"


def test_ram_mem_type_uses_either_type_or_mem_type_target_key():
    # stage2의 RAM target은 키가 "type"이고 메인보드 target은 "mem_type"이다 —
    # 두 스펠링 다 받아야 한다.
    assert _judge_computer(_cand(mem_type="DDR5"), {"type": "DDR5"}).verdict == "Pass"
    assert _judge_computer(_cand(mem_type="DDR4"), {"type": "DDR5"}).verdict == "Fail"
    assert _judge_computer(_cand(mem_type="DDR5"), {"mem_type": "DDR5"}).verdict == "Pass"


def test_capacity_below_minimum_fails():
    out = _judge_computer(_cand(capacity_gb=500), {"capacity_gb_min": 1000})
    assert out.verdict == "Fail"


def test_ssd_interface_target_is_checked_against_protocol_spec():
    # target["interface"]는 이름과 달리 프로토콜(NVMe/SATA)과 비교한다 — SSD 원본
    # 데이터의 "인터페이스"(PCIe 세대)와 "프로토콜"이 분리돼 있어서다.
    assert _judge_computer(_cand(protocol="NVMe"), {"interface": "NVMe"}).verdict == "Pass"
    assert _judge_computer(_cand(protocol="SATA"), {"interface": "NVMe"}).verdict == "Fail"


def test_wattage_below_minimum_fails():
    out = _judge_computer(_cand(wattage_w=550), {"wattage_min": 750})
    assert out.verdict == "Fail"


def test_efficiency_rating_below_minimum_fails_and_meets_or_exceeds_passes():
    assert _judge_computer(_cand(efficiency_rating="Bronze"), {"plus_rating_min": "Gold"}).verdict == "Fail"
    assert _judge_computer(_cand(efficiency_rating="Gold"), {"plus_rating_min": "Gold"}).verdict == "Pass"
    assert _judge_computer(_cand(efficiency_rating="Titanium"), {"plus_rating_min": "Gold"}).verdict == "Pass"


def test_multiple_checks_fail_beats_pending_beats_pass():
    # perf_tier 정보 없음(Pending) + vram 부족(Fail) 이면 전체 verdict는 Fail이어야
    # 한다 — "하나라도 확실히 어기면 Fail"이 "정보 없어서 보류"보다 우선한다.
    out = _judge_computer(_cand(vram_gb=4), {"perf_tier_min": 6, "vram_gb_min": 8})
    assert out.verdict == "Fail"
    assert not any("PENDING" in r for r in out.reasons)  # Fail 이유만 남아야 함


def test_no_applicable_targets_passes_with_plain_reason():
    out = _judge_computer(_cand(), {})
    assert out.verdict == "Pass"
    assert out.reasons == ["PASS"]


def test_case_form_and_cooler_tdp_capacity_are_not_yet_checked():
    # 대응하는 실측 컬럼이 없어 아직 판정하지 않는다(TODO) — 있지도 않은 정보로
    # 단정하지 않는다는 원칙. 이 테스트는 그 의도된 미구현 상태를 문서화한다.
    out = _judge_computer(_cand(), {"form": "ATX_mid", "tdp_capacity_w_min": 125})
    assert out.verdict == "Pass"

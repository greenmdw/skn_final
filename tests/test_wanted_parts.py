"""원한 미보유 부품(wanted_parts) → 나머지 부품의 호환 조건 (설계 §11). DB·LLM 없이 도는 순수 테스트.

호환성 규칙이 읽는 값은 소켓·메모리 규격뿐이라 CPU·메인보드·RAM을 원했을 때만 추천이 달라지고, 값이
모호하거나 모순이거나 맞는 카탈로그 후보가 없으면 조건을 걸지 않는다는 점을 고정한다."""
from __future__ import annotations

import pytest

from src.dto import Candidate, Slots
from src.engine import stage2_requirement
from src.engine.wanted_parts import apply_wanted_constraints, describe_hints, platform_hints


def _build_spec(**values):
    return stage2_requirement.run(Slots(category="computer", mode="build", objective_text="", values=values), {},
                                  lambda _: None)


def _cand(slot, key, **specs):
    return Candidate(slot=slot, product_key=key, name=key, price=100, score=1.0, specs=specs)


POOL = {
    "CPU": [_cand("CPU", "c-am5", socket="AM5"), _cand("CPU", "c-1700", socket="LGA1700"), _cand("CPU", "c-am4", socket="AM4")],
    "메인보드": [_cand("메인보드", "b-am5", socket="AM5", mem_type="DDR5"),
               _cand("메인보드", "b-1700-d4", socket="LGA1700", mem_type="DDR4"),
               _cand("메인보드", "b-1700-d5", socket="LGA1700", mem_type="DDR5")],
    "RAM": [_cand("RAM", "r4", mem_type="DDR4"), _cand("RAM", "r5", mem_type="DDR5")],
}


def _wanted(slot, **fields):
    return {slot: {"name": f"원하는 {slot}", "fields": fields, "source_url": "https://example.com"}}


def _spec():
    return _build_spec(purpose="game", budget_max=2_000_000)


# ── platform_hints: 하나로 정해지는 값만 ───────────────────────────────────────

@pytest.mark.parametrize("socket,expected", [
    ("AM5", "AM5"), ("LGA 1700", "LGA1700"), ("LGA-1851", "LGA1851"), ("am4", "AM4"),
    ("Intel LGA 1851 / 1700 / 1200; AMD AM5 / AM4", None),          # 여러 소켓 나열 — 모호
    ("AM5 (LGA 1718)", None),                                        # 서로 다른 두 소켓 표기 — 모호
    ("", None), (None, None),
])
def test_socket_hint_is_only_kept_when_it_is_exactly_one_socket(socket, expected):
    hints = platform_hints(_wanted("CPU", socket=socket))
    assert (hints.get("CPU") or {}).get("socket") == expected


def test_memory_hint_needs_exactly_one_ddr_generation():
    assert platform_hints(_wanted("RAM", mem_type="DDR5"))["RAM"] == {"mem_type": "DDR5"}
    assert platform_hints(_wanted("RAM", mem_type="DDR4 / DDR5")) == {}
    assert platform_hints(_wanted("RAM", mem_type="Samsung V-NAND")) == {}


def test_slots_that_cannot_make_a_platform_condition_produce_no_hint():
    for slot, fields in [("GPU", {"interface": "PCIe 5.0"}), ("파워", {"wattage_w": 1000}),
                         ("케이스", {"supports_form_factors": "ATX"}), ("쿨러", {"socket": "AM5", "height_mm": 168}),
                         ("저장장치", {"capacity_gb": 1000})]:
        assert platform_hints(_wanted(slot, **fields)) == {}, slot


def test_cpu_memory_type_is_not_a_hint_because_cpus_can_support_two_generations():
    assert platform_hints(_wanted("CPU", socket="LGA1700", mem_type="DDR5")) == {"CPU": {"socket": "LGA1700"}}


def test_alias_slot_names_and_bad_shapes_do_not_crash():
    assert platform_hints({"그래픽카드": {"fields": {"interface": "x"}}}) == {}
    assert platform_hints({"CPU": "문자열"}) == {} and platform_hints(None) == {} and platform_hints([]) == {}
    assert platform_hints({"메모리": {"fields": {"mem_type": "DDR5"}}}) == {"RAM": {"mem_type": "DDR5"}}


# ── apply_wanted_constraints ─────────────────────────────────────────────────

def test_wanted_cpu_socket_constrains_the_board_target_and_leaves_spec_owned_empty():
    spec = _spec()
    notes = apply_wanted_constraints(spec, _wanted("CPU", socket="AM5"), POOL)
    assert spec.targets["메인보드"]["socket_in"] == ["AM5"]
    assert spec.targets["CPU"]["socket_in"] == ["AM5"]            # 같은 슬롯의 카탈로그 후보도 그 소켓으로 맞춘다
    assert spec.owned == {}                         # 원한 부품은 검사용 보유 부품(spec.owned)에 들어가지 않는다
    assert "CPU" in spec.targets                   # 같은 슬롯은 여전히 카탈로그에서 추천한다
    assert any("원하는 미보유 부품 기준" in n for n in notes)


def test_wanted_ram_type_constrains_the_board_memory():
    spec = _spec()
    apply_wanted_constraints(spec, _wanted("RAM", mem_type="DDR4"), POOL)
    assert spec.targets["메인보드"]["mem_type"] == "DDR4"
    assert spec.targets["RAM"]["type"] == "DDR4"                  # RAM 슬롯 자신도 — 기본 DDR5 와 어긋나지 않게


def test_wanted_board_constrains_cpu_socket_and_ram_type():
    spec = _spec()
    apply_wanted_constraints(spec, _wanted("메인보드", socket="LGA1700", mem_type="DDR4"), POOL)
    assert spec.targets["CPU"]["socket_in"] == ["LGA1700"] and spec.targets["RAM"]["type"] == "DDR4"
    assert spec.targets["메인보드"]["socket_in"] == ["LGA1700"] and spec.targets["메인보드"]["mem_type"] == "DDR4"


def test_unconstrainable_wants_change_nothing():
    spec = _spec()
    before = {slot: dict(target) for slot, target in spec.targets.items()}
    for slot, fields in [("GPU", {"interface": "PCIe 5.0"}), ("파워", {"wattage_w": 1000}), ("쿨러", {"cooling_type": "수랭"})]:
        assert apply_wanted_constraints(spec, _wanted(slot, **fields), POOL) == []
    assert spec.targets == before


def test_contradicting_wants_are_dropped_with_a_note():
    spec = _spec()
    before = dict(spec.targets["메인보드"])
    wanted = {**_wanted("CPU", socket="AM5"), **_wanted("메인보드", socket="LGA1700")}
    notes = apply_wanted_constraints(spec, wanted, POOL)
    assert spec.targets["메인보드"] == before and spec.targets["CPU"].get("socket_in") != ["LGA1700"]
    assert any("소켓이 서로 달라" in n for n in notes)


def test_a_condition_no_catalog_candidate_can_satisfy_is_not_applied():
    spec = _spec()
    before = dict(spec.targets["메인보드"])
    pool = {**POOL, "메인보드": [_cand("메인보드", "b-am4", socket="AM4", mem_type="DDR4")]}
    notes = apply_wanted_constraints(spec, _wanted("CPU", socket="AM5"), pool)
    assert spec.targets["메인보드"] == before
    assert any("맞는 메인보드가 카탈로그에 없어" in n for n in notes)


def test_cpu_socket_and_ram_type_must_be_satisfiable_by_one_board_together():
    spec = _spec()
    wanted = {**_wanted("CPU", socket="AM5"), **_wanted("RAM", mem_type="DDR4")}      # AM5 보드는 전부 DDR5뿐
    notes = apply_wanted_constraints(spec, wanted, POOL)
    assert spec.targets["메인보드"]["socket_in"] == ["AM5"]                          # 소켓은 건다
    assert spec.targets["메인보드"].get("mem_type") != "DDR4"                        # 같이 못 맞추는 메모리 조건은 뺀다
    assert any("함께 만족하는 메인보드" in n for n in notes)


def test_no_wanted_parts_is_a_no_op():
    spec = _spec()
    before = {slot: dict(target) for slot, target in spec.targets.items()}
    assert apply_wanted_constraints(spec, None, POOL) == [] and apply_wanted_constraints(spec, {}, POOL) == []
    assert spec.targets == before


def test_describe_hints_reads_naturally():
    assert describe_hints({"CPU": {"socket": "AM5"}, "RAM": {"mem_type": "DDR5"}}) == "CPU 소켓 AM5 · RAM 메모리 규격 DDR5"
    assert describe_hints({}) == ""


# ── 조건 화면 표시 ────────────────────────────────────────────────────────────────────────────

def _fields_for(values):
    from src.services import session_service
    from src.categories import load_category
    return {f["key"]: f for f in session_service._build_fields(load_category("computer"), values)}


def test_wanted_parts_field_is_hidden_until_set_then_shows_effect():
    assert "wanted_parts" not in _fields_for({"mode": "build"})
    wanted = {"RAM": {"name": "삼성 DDR5-5600 16GB", "fields": {"mem_type": "DDR5"}}}
    shown = _fields_for({"mode": "build", "wanted_parts": wanted})["wanted_parts"]
    assert shown["label"] == "원하는 부품"
    assert "RAM 삼성 DDR5-5600 16GB" in shown["display"] and "메모리 규격 DDR5" in shown["display"]


def test_wanted_parts_display_in_upgrade_mode_says_record_only():
    wanted = {"CPU": {"name": "AMD Ryzen 9 9950X3D", "fields": {"socket": "AM5"}}}
    shown = _fields_for({"mode": "upgrade", "wanted_parts": wanted})["wanted_parts"]
    assert "기록만" in shown["display"]

"""RAM 모듈 2개 구성 기준(정책 §2.5) — 키트는 그대로, 단품은 2개 구성으로 바꿔 판정·가격·용량을 구성 전체로 본다."""
from __future__ import annotations

import pytest

from src.dto import Candidate, RankResult, RequirementSpec
from src.engine import feasibility, ram_config, stage3a_hardfilter
from src.engine.stage2_requirement import RequirementRuleError, _check_ranking_priority, load_computer_rules
from src.engine.stage3a_hardfilter import CandidateShortage
from src.engine.stage4_optimize import build_computer

_noop = lambda _m: None  # noqa: E731


def _ram(key="ram", price=100_000, capacity=32, config="16GB × 2", **extra) -> Candidate:
    specs = {"mem_type": "DDR5", **extra}
    if capacity is not None:
        specs["capacity_gb"] = capacity
    if config is not None:
        specs["module_config"] = config
    return Candidate(product_key=key, slot="RAM", name=key, price=price, specs=specs,
                     provenance={"by_key": {"capacity_gb": "u"}})


def _spec(need=None) -> RequirementSpec:
    target = {"mem_type": "DDR5", **({"capacity_gb_min": need} if need else {})}
    return RequirementSpec(list_id="t", category="computer", mode="build", targets={"RAM": target},
                           budget={"total": 1_000_000, "alloc": {"RAM": 0.1}})


# ── as_pair ───────────────────────────────────────────────────────────────────

def test_kit_keeps_price_and_capacity_and_is_one_product():
    kit = _ram(price=120_000, capacity=32, config="16GB × 2")
    pair, reason = ram_config.as_pair(kit)
    assert reason is None
    assert (pair.price, pair.specs["capacity_gb"], pair.purchase_qty, pair.unit_price) == (120_000, 32, 1, 120_000)
    assert pair.specs["module_config"] == "16GB × 2" and "ram_pair_from_single" not in pair.flags
    assert ram_config.pair_price(kit) == 120_000        # 키트에 2를 곱하지 않는다


def test_single_module_becomes_two_modules_without_touching_the_original():
    single = _ram(price=60_000, capacity=16, config="16GB × 1")
    pair, reason = ram_config.as_pair(single)
    assert reason is None
    assert (pair.price, pair.unit_price, pair.purchase_qty) == (120_000, 60_000, 2)
    assert pair.specs["capacity_gb"] == 32 and pair.specs["module_config"] == "16GB × 2"
    assert "ram_pair_from_single" in pair.flags
    assert single.price == 60_000 and single.specs["capacity_gb"] == 16 and single.specs["module_config"] == "16GB × 1"
    assert single.flags == [] and single.purchase_qty == 1
    assert pair.provenance == single.provenance and pair.provenance is not single.provenance
    assert ram_config.pair_price(single) == 120_000


def test_as_pair_is_idempotent_so_price_and_capacity_are_never_summed_twice():
    pair, _ = ram_config.as_pair(_ram(price=60_000, capacity=16, config="16GB × 1"))
    again, reason = ram_config.as_pair(pair)
    assert reason is None and again.price == 120_000 and again.specs["capacity_gb"] == 32 and again.purchase_qty == 2


def test_four_module_kit_is_excluded_not_converted():
    out, reason = ram_config.as_pair(_ram(capacity=64, config="16GB × 4"))
    assert out is None and reason == "EXCLUDED_RAM_NOT_PAIR:4"
    assert ram_config.pair_price(_ram(capacity=64, config="16GB × 4")) is None


def test_unreadable_module_config_or_single_without_capacity_is_pending():
    assert ram_config.as_pair(_ram(config=None)) == (None, "PENDING_SPEC_MISSING:module_config")
    assert ram_config.as_pair(_ram(config="가나다")) == (None, "PENDING_SPEC_MISSING:module_config")
    assert ram_config.as_pair(_ram(capacity=None, config="16GB × 1")) == (None, "PENDING_SPEC_MISSING:capacity_gb")


def test_fractional_module_size_is_written_without_trailing_zero():
    pair, _ = ram_config.as_pair(_ram(capacity=8, config="8GB × 1"))
    assert pair.specs["module_config"] == "8GB × 2"


# ── 하드 필터 ──────────────────────────────────────────────────────────────────

def _run(need, *cands):
    return stage3a_hardfilter.run(_spec(need), {"RAM": list(cands)}, _noop)


def test_required_capacity_is_judged_on_the_two_module_total():
    single16 = _ram("single16", 60_000, 16, "16GB × 1")
    kit16x2 = _ram("kit16x2", 120_000, 32, "16GB × 2")
    kit8x2 = _ram("kit8x2", 70_000, 16, "8GB × 2")
    hf = _run(32, single16, kit16x2, kit8x2)
    assert sorted(c.product_key for c in hf.slots["RAM"]) == ["kit16x2", "single16"]
    assert hf.stats["RAM"]["fail_reasons"] == {"FAIL_CAPACITY_BELOW": 1}
    by_key = {c.product_key: c for c in hf.slots["RAM"]}
    assert by_key["single16"].specs["capacity_gb"] == 32 and by_key["single16"].price == 120_000
    assert by_key["kit16x2"].price == 120_000 and by_key["kit16x2"].purchase_qty == 1


def test_eight_gb_single_satisfies_a_16gb_requirement_as_two_modules():
    hf = _run(16, _ram("single8", 30_000, 8, "8GB × 1"))
    assert [c.product_key for c in hf.slots["RAM"]] == ["single8"]
    assert hf.slots["RAM"][0].price == 60_000


def test_four_module_kit_fails_and_unknown_config_is_held():
    ok = _ram("ok", 120_000, 32, "16GB × 2")
    four = _ram("four", 200_000, 64, "16GB × 4")
    unknown = _ram("unknown", 100_000, 32, None)
    hf = _run(None, ok, four, unknown)
    assert [c.product_key for c in hf.slots["RAM"]] == ["ok"]
    assert hf.stats["RAM"]["fail_reasons"] == {"EXCLUDED_RAM_NOT_PAIR": 1}
    assert [c.product_key for c in hf.held["RAM"]] == ["unknown"]
    assert hf.stats["RAM"]["pending_reasons"] == {"PENDING_SPEC_MISSING:module_config": 1}
    assert unknown.specs.get("module_config") is None                       # 근거 없는 값을 채우지 않는다


def test_single_without_capacity_is_pending():
    hf = _run(None, _ram("ok", 120_000, 32, "16GB × 2"), _ram("nocap", 60_000, None, "16GB × 1"))
    assert [c.product_key for c in hf.held["RAM"]] == ["nocap"]
    assert hf.stats["RAM"]["pending_reasons"] == {"PENDING_SPEC_MISSING:capacity_gb": 1}


def test_no_automatic_switch_to_another_module_count():
    """2개 구성이 하나도 안 되면 1개·4개로 바꿔 채우지 않고 후보 부족이다."""
    with pytest.raises(CandidateShortage) as exc:
        _run(None, _ram("four", 200_000, 64, "16GB × 4"))
    assert exc.value.slots["RAM"]["fail_reasons"] == {"EXCLUDED_RAM_NOT_PAIR": 1}
    assert "모듈 2개 구성이 아님" in exc.value.summary()


def test_enrichment_that_fills_module_config_is_converted_once_on_rejudge():
    """보완 뒤 재판정에서도 같은 변환을 적용한다 — 단품이면 가격·용량이 2배, 키트면 그대로."""
    def enrich(slot, pending):
        out = [c.model_copy(update={"specs": {**c.specs, "module_config": "16GB × 1" if c.product_key == "s" else "16GB × 2"}})
               for c in pending]
        return out, [{"slot": slot, "product_key": c.product_key, "status": "filled"} for c in pending]

    held_single = _ram("s", 60_000, 16, None)
    held_kit = _ram("k", 120_000, 32, None)
    hf = stage3a_hardfilter.run(_spec(32), {"RAM": [held_single, held_kit]}, _noop, enrich=enrich)
    by_key = {c.product_key: c for c in hf.slots["RAM"]}
    assert by_key["s"].price == 120_000 and by_key["s"].specs["capacity_gb"] == 32 and by_key["s"].purchase_qty == 2
    assert by_key["k"].price == 120_000 and by_key["k"].specs["capacity_gb"] == 32 and by_key["k"].purchase_qty == 1


def test_other_slots_are_not_converted():
    gpu = Candidate(product_key="g", slot="GPU", name="g", price=100, specs={"perf_tier": 5})
    spec = RequirementSpec(list_id="t", category="computer", mode="build", targets={"GPU": {}},
                           budget={"total": 1000, "alloc": {"GPU": 1}})
    hf = stage3a_hardfilter.run(spec, {"GPU": [gpu]}, _noop)
    assert hf.slots["GPU"][0].price == 100 and hf.slots["GPU"][0].purchase_qty == 1 and hf.slots["GPU"][0].unit_price is None


# ── 점수·설정 ────────────────────────────────────────────────────────────────────

def test_dual_channel_bonus_setting_is_gone_and_rejected():
    ranking = load_computer_rules()["ranking"]
    assert "ram_dual_channel_bonus" not in ranking
    with pytest.raises(RequirementRuleError, match="ram_dual_channel_bonus"):
        _check_ranking_priority({**ranking, "ram_dual_channel_bonus": 0.05})


def test_pair_score_has_no_module_count_bonus_and_prices_the_whole_pair():
    from src.engine.score_policy import price_axis
    from src.engine.stage3b_rank import _score
    kit, _ = ram_config.as_pair(_ram("kit", 100_000, 32, "16GB × 2"))
    single, _ = ram_config.as_pair(_ram("single", 50_000, 16, "16GB × 1"))
    # 키트(100,000원)와 단품 2개(50,000×2)는 같은 구성 가격이고 둘 다 모듈 2개 — 점수가 같다(가산점 없음).
    a, b = _score(kit, 200_000.0, "RAM"), _score(single, 200_000.0, "RAM")
    assert a.score == pytest.approx(b.score)
    assert a.breakdown["가격"] == pytest.approx(price_axis(100_000, 200_000.0))
    # 필요 용량과 같은 구성이든 아니든 가산점이 붙지 않는다.
    assert a.score == pytest.approx(_score(kit.model_copy(update={"specs": {**kit.specs, "capacity_gb": 64}}),
                                           200_000.0, "RAM").score)


# ── with_purchase_qty ───────────────────────────────────────────────────────────

def test_with_purchase_qty_for_single_kit_and_one():
    single = _ram(capacity=16, config="16GB × 1")
    two = ram_config.with_purchase_qty(single, 2)
    assert two.specs["capacity_gb"] == 32 and two.specs["module_config"] == "16GB × 2" and two.purchase_qty == 2
    assert single.specs["capacity_gb"] == 16                                  # 원본 불변

    kit = _ram(capacity=32, config="16GB × 2")
    four = ram_config.with_purchase_qty(kit, 2)
    assert four.specs["capacity_gb"] == 64 and four.specs["module_config"] == "16GB × 4"

    assert ram_config.with_purchase_qty(kit, 1) is kit
    unreadable = _ram(config=None)
    assert ram_config.with_purchase_qty(unreadable, 3) is unreadable


# ── feasibility · stage4 ─────────────────────────────────────────────────────────

def test_feasibility_lower_bound_uses_the_two_module_price():
    single = _ram("single", 60_000, 16, "16GB × 1")
    kit = _ram("kit", 150_000, 32, "16GB × 2")
    spec = _spec(32)
    out = feasibility.assess(spec, {"RAM": [single, kit]})
    assert out["per_slot"]["RAM"] == 120_000        # 단품 60,000 × 2 가 키트 150,000 보다 싸다
    out = feasibility.assess(spec, {"RAM": [_ram("kit", 150_000, 32, "16GB × 2"), _ram("four", 10_000, 64, "16GB × 4")]})
    assert out["per_slot"]["RAM"] == 150_000        # 4개 키트는 하한에 들어가지 않는다


def test_stage4_items_carry_qty_and_unit_price_and_totals_sum_the_pair_price():
    single, _ = ram_config.as_pair(_ram("single", 60_000, 16, "16GB × 1"))
    cpu = Candidate(product_key="cpu", slot="CPU", name="cpu", price=300_000, score=.5, specs={"perf_tier": 5})
    ranked = {"CPU": [cpu], "RAM": [single]}
    slots = {s: {"ranked": [c.model_dump() for c in cs]} for s, cs in ranked.items()}
    spec = RequirementSpec(list_id="q", category="computer", mode="build",
                           targets={"CPU": {}, "RAM": {}}, budget={"total": 1_000_000})
    build = build_computer(RankResult(slots=slots), spec, _noop)
    items = {i.slot: i for i in build.items}
    assert (items["RAM"].qty, items["RAM"].unit_price, items["RAM"].price) == (2, 60_000, 120_000)
    assert (items["CPU"].qty, items["CPU"].unit_price) == (1, None)
    assert build.totals["price"] == 420_000


# ── 채팅 경로(result_advice) — 비교는 2개 구성 기준 ─────────────────────────────────

def _advice_ctx(current_row_qty=1):
    from src.services import result_advice
    cur = _ram("cur", 120_000, 32, "16GB × 2", variant_id="v-cur")
    cur = cur.model_copy(update={"variant_id": "v-cur"})
    single = _ram("single", 50_000, 16, "16GB × 1").model_copy(update={"variant_id": "v-single"})
    cheap_small = _ram("small", 40_000, 16, "8GB × 2").model_copy(update={"variant_id": "v-small"})   # 16GB → 요구 32GB 미달
    four = _ram("four", 90_000, 64, "16GB × 4").model_copy(update={"variant_id": "v-four"})
    pool = [cur, single, cheap_small, four]
    row = {"id": "r1", "slot": "RAM", "variant_id": "v-cur", "price": 120_000, "qty": current_row_qty,
           "selected": True, "product_name": "cur"}
    spec = RequirementSpec(list_id="x", category="computer", mode="build")
    return result_advice._Ctx(
        conn=None, revision_id=None, stored=[row], cvals={}, targets={"RAM": {"mem_type": "DDR5", "capacity_gb_min": 32}},
        pool={"RAM": pool}, by_variant={c.variant_id: c for c in pool}, spec=spec,
        rules=load_computer_rules()["verification"]), result_advice


def test_chat_step_down_compares_two_module_configurations():
    ctx, advice = _advice_ctx()
    assert [c.product_key for c in advice._cfgs(ctx, "RAM")] == ["cur", "single", "small"]   # 4개 키트는 구성 불가라 뺌
    cand = advice.step_candidate(ctx, "RAM", "down")
    # 같은 총용량(32GB)의 더 싼 구성 = 단품 2개(50,000×2). 8GB×2(→16GB)는 요구 미달이라 고르지 않는다.
    assert cand.product_key == "single" and cand.purchase_qty == 2 and cand.price == 100_000
    assert cand.specs["capacity_gb"] == 32
    row = ctx.row("RAM")
    assert advice._extra_cost("RAM", row, cand) == -20_000                   # 구성 가격 − 현재 단가 × 수량
    assert advice._label("RAM", cand) == "single ×2"


def test_chat_current_ram_uses_the_stored_qty_for_price_and_capacity():
    ctx, advice = _advice_ctx(current_row_qty=2)                              # 사용자가 키트를 2개로 바꾼 경우
    cur = advice._current(ctx, "RAM", ctx.row("RAM"))
    assert cur.price == 240_000 and cur.specs["capacity_gb"] == 64 and cur.specs["module_config"] == "16GB × 4"
    assert ctx.chosen()["RAM"].specs["module_config"] == "16GB × 4"           # 호환 검사도 같은 수량으로 본다

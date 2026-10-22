"""사전 필터 적격성(정책 §5.1~§5.3) — Pass만 평가 후보가 되고, Pending은 보류·보완·재판정, 후보 부족은 안내."""
from __future__ import annotations

import os
import uuid

import pytest

from src.auth.deps import Principal
from src.dto import Candidate, HardFilterResult, RequirementSpec, Slots
from src.engine import feasibility, stage3a_hardfilter, stage3b_rank
from src.engine.score_policy import ScoreInputError
from src.engine.stage3a_hardfilter import CandidateShortage, _judge_computer

_noop = lambda _m: None  # noqa: E731


def _cand(key="k", slot="GPU", price=1000, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=key, brand="b", price=price, specs=specs)


def _spec(targets, *, mode="build", total=1_000_000) -> RequirementSpec:
    return RequirementSpec(list_id="t", category="computer", mode=mode, targets=targets,
                           budget={"total": total, "alloc": {s: 1 / max(1, len(targets)) for s in targets}})


def _slots() -> Slots:
    return Slots(category="computer", mode="build", objective_text="", values={"purpose": "game"})


# ── 가격 유효성 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("price", [0, -1000, True, 1000.5, None])
def test_invalid_price_is_pending_with_reason(price):
    out = _judge_computer(_cand(perf_tier=7).model_copy(update={"price": price}), {"perf_tier_min": 5})
    assert out.verdict == "Pending"
    assert out.reasons == ["PENDING_PRICE_INVALID"]


def test_invalid_price_without_any_target_is_still_pending():
    out = _judge_computer(_cand().model_copy(update={"price": 0}), {})
    assert out.verdict == "Pending"


def test_fail_still_beats_invalid_price():
    out = _judge_computer(_cand(vram_gb=4).model_copy(update={"price": 0}), {"vram_gb_min": 8})
    assert out.verdict == "Fail"


# ── keep / held / 후보 부족 ───────────────────────────────────────────────────────

def test_single_pass_does_not_promote_pending_into_keep():
    """예전에는 Pass가 TOP_N 미만이면 Pending을 끌어올렸다."""
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    pool = {"GPU": [_cand("ok", perf_tier=8), _cand("unknown"), _cand("unknown2")]}
    hf = stage3a_hardfilter.run(spec, pool, _noop)
    assert [c.product_key for c in hf.slots["GPU"]] == ["ok"]
    assert sorted(c.product_key for c in hf.held["GPU"]) == ["unknown", "unknown2"]
    assert hf.stats["GPU"]["pending_reasons"] == {"PENDING_SPEC_MISSING:perf_tier": 2}
    assert hf.stats["GPU"]["pass"] == 1 and hf.stats["GPU"]["pending"] == 2
    assert {a["status"] for a in hf.enrichment} == {"no_path"}
    assert all(a["missing_keys"] == ["perf_tier"] for a in hf.enrichment)


def test_all_pending_without_enrich_is_shortage_with_no_path_records():
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    with pytest.raises(CandidateShortage) as exc:
        stage3a_hardfilter.run(spec, {"GPU": [_cand("a"), _cand("b")]}, _noop)
    assert exc.value.slots["GPU"] == {"pass": 0, "pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 2},
                                      "fail_reasons": {}}
    assert [a["status"] for a in exc.value.enrichment] == ["no_path", "no_path"]
    assert "성능 등급 정보가 없는 후보 2개" in exc.value.summary()


def test_all_fail_is_shortage_without_promotion_and_counts_fail_prefixes():
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    pool = {"GPU": [_cand("a", perf_tier=3), _cand("b", perf_tier=4), _cand("c", perf_tier=1)]}
    with pytest.raises(CandidateShortage) as exc:
        stage3a_hardfilter.run(spec, pool, _noop)
    assert exc.value.slots["GPU"]["fail_reasons"] == {"FAIL_PERF_BELOW": 3}
    assert exc.value.summary().endswith("GPU — 요구 등급 미달 3개")


def test_summary_mixes_pending_and_fail_and_leaves_unknown_codes_as_is():
    exc = CandidateShortage({"GPU": {"pass": 0, "pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 11,
                                                                     "PENDING_PRICE_INVALID": 2, "PENDING_X": 1},
                                     "fail_reasons": {"FAIL_PERF_BELOW": 8}}}, [])
    text = exc.summary()
    assert "GPU — 성능 등급 정보가 없는 후보 11개, 가격 정보가 유효하지 않은 후보 2개, PENDING_X 후보 1개, 요구 등급 미달 8개" in text


def test_target_slot_missing_from_pool_is_shortage():
    with pytest.raises(CandidateShortage) as exc:
        stage3a_hardfilter.run(_spec({"GPU": {}}), {}, _noop)
    assert exc.value.slots["GPU"]["pass"] == 0 and "후보가 없습니다" in exc.value.summary()


def test_upgrade_mode_ignores_non_target_slots_for_shortage():
    spec = _spec({"GPU": {"perf_tier_min": 6}}, mode="upgrade")
    pool = {"GPU": [_cand("g", perf_tier=8)], "CPU": [_cand("c", slot="CPU", price=0)]}
    hf = stage3a_hardfilter.run(spec, pool, _noop)
    assert list(hf.slots) == ["GPU"]


def test_non_target_slot_with_no_pass_does_not_raise_in_build_mode():
    spec = _spec({"GPU": {}})
    pool = {"GPU": [_cand("g")], "CPU": [_cand("c", slot="CPU", price=0)]}
    hf = stage3a_hardfilter.run(spec, pool, _noop)
    assert hf.slots["CPU"] == [] and len(hf.held["CPU"]) == 1


# ── 보완·재판정 ─────────────────────────────────────────────────────────────────

def _filler(value, status="filled"):
    calls = []

    def enrich(slot, pending):
        calls.append((slot, [c.product_key for c in pending]))
        out = [c.model_copy(update={"specs": {**c.specs, "perf_tier": value},
                                    "provenance": {"by_key": {"perf_tier": "https://src"}}}) for c in pending]
        return out, [{"slot": slot, "product_key": c.product_key, "missing_keys": ["perf_tier"],
                      "source": "https://src", "status": status, "detail": ""} for c in pending]
    return enrich, calls


def test_enrichment_that_fills_the_missing_key_returns_the_candidate_to_pass_and_it_is_scored():
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    enrich, calls = _filler(8)
    hf = stage3a_hardfilter.run(spec, {"GPU": [_cand("u")]}, _noop, enrich=enrich)
    assert [c.product_key for c in hf.slots["GPU"]] == ["u"] and hf.held["GPU"] == []
    assert hf.slots["GPU"][0].verdict == "Pass"
    assert hf.slots["GPU"][0].provenance["by_key"]["perf_tier"] == "https://src"
    assert calls == [("GPU", ["u"])]
    assert hf.enrichment[0]["status"] == "filled"
    rank = stage3b_rank.run(hf, spec, _slots(), _noop)
    assert rank.slots["GPU"]["ranked"][0]["score"] > 0


def test_enrichment_value_below_requirement_makes_it_fail():
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    enrich, _ = _filler(3)
    with pytest.raises(CandidateShortage) as exc:
        stage3a_hardfilter.run(spec, {"GPU": [_cand("u")]}, _noop, enrich=enrich)
    assert exc.value.slots["GPU"]["fail_reasons"] == {"FAIL_PERF_BELOW": 1}
    assert exc.value.slots["GPU"]["pending_reasons"] == {}


def test_not_found_keeps_candidate_held():
    spec = _spec({"GPU": {"perf_tier_min": 6}})

    def enrich(slot, pending):
        return pending, [{"slot": slot, "product_key": c.product_key, "missing_keys": ["perf_tier"],
                          "source": "x", "status": "not_found", "detail": ""} for c in pending]

    pool = {"GPU": [_cand("ok", perf_tier=8), _cand("u")]}
    hf = stage3a_hardfilter.run(spec, pool, _noop, enrich=enrich)
    assert [c.product_key for c in hf.slots["GPU"]] == ["ok"]
    assert [c.product_key for c in hf.held["GPU"]] == ["u"]
    assert hf.enrichment[0]["status"] == "not_found"


def test_enrich_exception_is_recorded_as_failed_and_not_retried():
    spec = _spec({"GPU": {"perf_tier_min": 6}})
    calls = []

    def boom(slot, pending):
        calls.append(slot)
        raise RuntimeError("secret detail")

    pool = {"GPU": [_cand("ok", perf_tier=8), _cand("u")]}
    hf = stage3a_hardfilter.run(spec, pool, _noop, enrich=boom)
    assert calls == ["GPU"]
    assert [(a["status"], a["detail"]) for a in hf.enrichment] == [("failed", "RuntimeError")]
    assert [c.product_key for c in hf.held["GPU"]] == ["u"]


def test_enrich_is_called_once_per_slot_and_only_when_something_is_pending():
    spec = _spec({"GPU": {"perf_tier_min": 6}, "CPU": {}})
    calls = []

    def enrich(slot, pending):
        calls.append(slot)
        return pending, []

    stage3a_hardfilter.run(spec, {"GPU": [_cand("a", perf_tier=8), _cand("u")],
                                  "CPU": [_cand("c", slot="CPU")]}, _noop, enrich=enrich)
    assert calls == ["GPU"]


# ── 점수·가능성 ─────────────────────────────────────────────────────────────────

def test_rank_rejects_non_pass_candidates():
    spec = _spec({"GPU": {}}, total=100)
    pending = _cand("p", perf_tier=5).model_copy(update={"verdict": "Pending"})
    with pytest.raises(ScoreInputError):
        stage3b_rank.run(HardFilterResult(slots={"GPU": [pending]}), spec, _slots(), _noop)


def test_feasibility_counts_only_pass_candidates():
    spec = _spec({"GPU": {"perf_tier_min": 7}}, total=2_000_000)
    pool = {"GPU": [_cand("cheap-unknown", price=300_000), _cand("bad-price", price=0, perf_tier=9),
                    _cand("weak", price=100_000, perf_tier=1), _cand("ok", price=500_000, perf_tier=8)]}
    assert feasibility.assess(spec, pool)["per_slot"]["GPU"] == 500_000


# ── 서비스 보완 함수(저장소 읽기 전용) ──────────────────────────────────────────

DSN = os.getenv("DATABASE_URL")
_db = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

if DSN:
    import psycopg

    @pytest.fixture()
    def conn():
        connection = psycopg.connect(DSN, prepare_threshold=None, autocommit=True)
        try:
            yield connection
        finally:
            connection.execute("DELETE FROM catalog.live_spec_lookup_cache WHERE lookup_key LIKE 'eligibility test %'")
            connection.close()


def _put(conn, key, fields, *, relevant=True, status="unreviewed", age_days=0, source_url="https://spec.example/x"):
    import json

    conn.execute(
        "INSERT INTO catalog.live_spec_lookup_cache (lookup_key, query_text, relevant, supported_fields, source_url, "
        "fetched_at, status) VALUES (%s, %s, %s, %s::jsonb, %s, now() - make_interval(days => %s), %s)",
        (key, key, relevant, json.dumps(fields), source_url, age_days, status))


def _ram(name) -> Candidate:
    return Candidate(product_key=name, slot="RAM", name=name, brand="b", price=50_000,
                     specs={"capacity_gb": 16, "module_config": "8GB × 2"})


@pytest.fixture()
def no_web(monkeypatch):
    from src.services import live_spec_lookup

    def forbidden(*a, **k):
        raise AssertionError("웹 검색·LLM 경로를 부르면 안 된다")

    for fn in ("lookup", "lookup_with_meta", "_search_and_verify"):
        monkeypatch.setattr(live_spec_lookup, fn, forbidden)
    monkeypatch.setattr(live_spec_lookup, "call_web_search", forbidden)
    monkeypatch.setattr(live_spec_lookup, "call_llm", forbidden)


@_db
@pytest.mark.db
def test_enricher_fills_ram_from_cache_with_provenance_and_passes_rejudge(conn, no_web):
    from src.services.catalog_enrichment import make_enricher

    _put(conn, "eligibility test ram a", {"mem_type": "DDR5", "capacity_gb": 32})
    cand = _ram("Eligibility-Test RAM-A")
    spec = _spec({"RAM": {"type": "DDR5", "capacity_gb_min": 16}})
    kit = {"capacity_gb": 16, "module_config": "8GB × 2"}   # RAM 은 모듈 2개 구성(정책 §2.5)으로 판정한다
    pool = {"RAM": [cand.model_copy(update={"specs": kit}), _ram("x").model_copy(
        update={"specs": {"mem_type": "DDR5", **kit}})]}
    hf = stage3a_hardfilter.run(spec, pool, _noop, enrich=make_enricher(conn))
    filled = next(c for c in hf.slots["RAM"] if c.product_key == "Eligibility-Test RAM-A")
    assert filled.specs["mem_type"] == "DDR5" and filled.specs["capacity_gb"] == 16   # 있던 값은 덮지 않는다
    assert filled.provenance["by_key"] == {"mem_type": "https://spec.example/x"}
    assert hf.enrichment[0]["status"] == "filled" and hf.enrichment[0]["source"] == "https://spec.example/x"


@_db
@pytest.mark.db
@pytest.mark.parametrize("row", [
    dict(status="rejected"),
    dict(age_days=400),
    dict(relevant=False),
])
def test_enricher_ignores_rejected_expired_and_not_relevant_rows(conn, no_web, row):
    from src.services.catalog_enrichment import make_enricher

    _put(conn, "eligibility test ram b", {"mem_type": "DDR5"}, **row)
    pending = [_judge_computer(_ram("Eligibility-Test RAM-B"), {"type": "DDR5"})]
    out, attempts = make_enricher(conn)("RAM", pending)
    assert out[0].specs.get("mem_type") is None
    assert attempts[0]["status"] == "not_found" and attempts[0]["missing_keys"] == ["mem_type"]


@_db
@pytest.mark.db
def test_enricher_uses_confirmed_rows_even_when_old(conn, no_web):
    from src.services.catalog_enrichment import make_enricher

    _put(conn, "eligibility test ram c", {"mem_type": "DDR4"}, status="confirmed", age_days=900)
    pending = [_judge_computer(_ram("Eligibility-Test RAM-C"), {"type": "DDR4"})]
    out, attempts = make_enricher(conn)("RAM", pending)
    assert out[0].specs["mem_type"] == "DDR4" and attempts[0]["status"] == "filled"


@_db
@pytest.mark.db
def test_enricher_does_not_look_up_keys_the_store_does_not_cover(conn, no_web, monkeypatch):
    from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo
    from src.services.catalog_enrichment import make_enricher

    monkeypatch.setattr(LiveSpecLookupRepo, "get_fresh",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("조회하면 안 된다")))
    gpu = _judge_computer(_cand("gpu-x", slot="GPU"), {"perf_tier_min": 6})
    bad_price = _judge_computer(_cand("gpu-y", slot="GPU", perf_tier=9).model_copy(update={"price": 0}), {})
    out, attempts = make_enricher(conn)("GPU", [gpu, bad_price])
    assert [a["status"] for a in attempts] == ["no_path", "no_path"]
    assert [a["missing_keys"] for a in attempts] == [["perf_tier"], ["price"]]
    assert [c.specs for c in out] == [gpu.specs, bad_price.specs]


# ── DB 통합: 후보 부족은 failed + candidates_insufficient ─────────────────────────

def _run_with_impossible_gpu(conn, monkeypatch):
    from src.engine import stage2_requirement
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service, session_service

    real = stage2_requirement.run

    def impossible(slots, cat_def, log):
        spec = real(slots, cat_def, log)
        spec.targets["GPU"]["perf_tier_min"] = 99      # 어떤 카탈로그 GPU도 못 넘는 요구
        return spec

    monkeypatch.setattr(stage2_requirement, "run", impossible)
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 2_000_000), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))   # 예외 없이 끝난다
    return recommendation_service, revision_id


@_db
@pytest.mark.db
def test_insufficient_candidates_end_the_run_failed_and_status_api_explains_why(conn, monkeypatch):
    rs, revision_id = _run_with_impossible_gpu(conn, monkeypatch)

    status = rs.get_result_status(conn, revision_id)
    assert status["status"] == "failed"
    assert status["error"]["code"] == "candidates_insufficient"
    assert "GPU — " in status["error"]["message"] and "요구 등급 미달" in status["error"]["message"]
    assert status["error"]["slots"]["GPU"]["pass"] == 0
    assert "FAIL_PERF_BELOW" in status["error"]["slots"]["GPU"]["fail_reasons"]

    stored = rs.get_stored_result(conn, revision_id)
    assert stored["status"] == "failed" and stored["error"]["code"] == "candidates_insufficient"
    assert stored["items"] == []


@_db
@pytest.mark.db
def test_other_failures_keep_the_generic_error(conn):
    from src.repo.engine_repo import EngineRepo
    from src.services import recommendation_service as rs

    # 사유 단계가 없는 failed run 은 일반 문구
    class _Repo:
        def get_run_step(self, run_id, step):
            return None

    assert rs._failure_error(_Repo(), uuid.uuid4())["code"] == "recommend_failed"
    assert EngineRepo(conn).get_run_step(uuid.uuid4(), "추천 불가") is None


def test_hold_trace_detail_reports_held_counts_and_enrichment_outcomes():
    from src.services.recommendation_service import _hold_trace_detail

    assert _hold_trace_detail(HardFilterResult()) is None
    hf = HardFilterResult(held={"GPU": [_cand("a"), _cand("b")], "RAM": []},
                          enrichment=[{"status": "no_path"}, {"status": "no_path"}, {"status": "filled"}])
    assert _hold_trace_detail(hf) == "평가 제외(정보 부족) GPU 2개 · 보완 시도 보완 경로 없음 2, 보완됨 1"

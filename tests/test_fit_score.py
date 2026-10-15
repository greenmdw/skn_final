"""추천 적합도 표시(src/services/fit_score.py)와 저장·API·설명 연결 — 5단계.

표시 점수의 원본은 리뷰 계산 snapshot 의 반올림 없는 값이다. engine.recommendation_candidate.score(numeric(8,4))로
66.5점을 만들지 않는다.
"""
from __future__ import annotations

import math
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

from src.engine.score_policy import AXES
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.schemas import FitOut, ItemOut, RecommendErrorOut, RecommendResultOut, ResultStatusOut, TotalsOut
from src.services import recommendation_service, result_advice
from src.services.fit_score import avg_fit, display_points, fit_for_item
from src.services.recommendation_review_snapshot import SNAPSHOT_STEP, clear_snapshot_cache, snapshot_step

WEIGHTS = {"가격": 0.45, "성능": 0.30, "리뷰": 0.25}
NEW = {"pipeline": "computer-v1", "computer_rules": "computer-rules-v12", "score_method": "pc-fit-v2"}


# ── display_points ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,shown", [
    (0.665, 66.5), (0.605, 60.5), (0.66449, 66.4), (0.6645, 66.5), (0.66450, 66.5),
    (0, 0.0), (1, 100.0), (0.0, 0.0), (1.0, 100.0), (0.8, 80.0), (0.36, 36.0),
])
def test_display_points_boundaries(raw, shown):
    assert display_points(raw) == shown


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, False, -0.01, 1.01, "0.5", None])
def test_display_points_rejects_invalid(bad):
    with pytest.raises(ValueError):
        display_points(bad)


# ── fit_for_item / avg_fit (DB 없음) ──────────────────────────────────────────

def _candidate(slot, raw_axes, *, weights=WEIGHTS, score=None, product=None, variant=None):
    product, variant = product or str(uuid.uuid4()), variant or str(uuid.uuid4())
    score = math.fsum(weights[a] * raw_axes[a] for a in AXES) if score is None else score
    return {"slot": slot, "product_id": product, "variant_id": variant, "rank_score": score,
            "rank_breakdown": raw_axes, "rank_weights": weights, "score_method": "pc-fit-v2"}


def _snap(*cands):
    return {"candidates": {c["variant_id"]: c for c in cands}}


def test_fit_for_item_scored_uses_raw_axes_and_one_rounding():
    cand = _candidate("GPU", {"가격": 0.8, "성능": 0.6, "리뷰": 0.5})
    fit = fit_for_item(_snap(cand), NEW, variant_id=cand["variant_id"], product_id=cand["product_id"], slot="GPU")
    assert fit["status"] == "scored" and fit["method_version"] == "pc-fit-v2" and fit["reason"] is None
    assert fit["score"] == 66.5
    assert [a["axis"] for a in fit["axes"]] == list(AXES)
    assert fit["axes"][0] == {"axis": "가격", "points": 80.0, "weight": 0.45, "weighted_points": 36.0}
    assert fit["axes"][1]["weighted_points"] == 18.0 and fit["axes"][2]["weighted_points"] == 12.5


def test_legacy_run_is_not_converted_to_100():
    cand = _candidate("GPU", {"가격": 0.8, "성능": 0.6, "리뷰": 0.5})
    for versions in ({"pipeline": "computer-v1"}, None, {}):
        fit = fit_for_item(_snap(cand), versions, variant_id=cand["variant_id"], product_id=cand["product_id"], slot="GPU")
        assert fit == {"status": "legacy_method", "score": None, "axes": [], "method_version": "v1", "reason": None}


def test_unavailable_reasons():
    cand = _candidate("GPU", {"가격": 0.8, "성능": 0.6, "리뷰": 0.5})
    ident = dict(variant_id=cand["variant_id"], product_id=cand["product_id"], slot="GPU")

    def reason(snapshot, **over):
        fit = fit_for_item(snapshot, NEW, **{**ident, **over})
        assert fit["status"] == "unavailable" and fit["score"] is None and fit["axes"] == []
        return fit["reason"]

    assert reason(None) == "snapshot_missing"
    assert reason(_snap(cand), variant_id=str(uuid.uuid4())) == "candidate_not_in_snapshot"
    assert reason(_snap(cand), product_id=str(uuid.uuid4())) == "snapshot_identity_mismatch"
    assert reason(_snap(cand), slot="CPU") == "snapshot_identity_mismatch"
    for broken in (
        {k: v for k, v in cand.items() if k != "rank_breakdown"},
        {k: v for k, v in cand.items() if k != "rank_weights"},
        {k: v for k, v in cand.items() if k != "score_method"},
        {**cand, "rank_score": cand["rank_score"] + 0.01},                       # 가중합과 다름
        {**cand, "rank_breakdown": {"가격": 0.8, "성능": 0.6}},                    # 축 부족
        {**cand, "rank_breakdown": {**cand["rank_breakdown"], "리뷰": 1.5}},        # 범위 밖
        {**cand, "rank_breakdown": {**cand["rank_breakdown"], "리뷰": "0.5"}},
        {**cand, "rank_weights": {"가격": 0.5, "성능": 0.5}},
        {**cand, "rank_weights": {"가격": 0.5, "성능": 0.4, "리뷰": 0.2}},          # 합이 1 아님
        {**cand, "score_method": "pc-fit-v9"},
        {**cand, "rank_score": True},
        {**cand, "rank_score": float("nan")},
    ):
        assert reason(_snap(broken)) == "invalid_snapshot", broken


def test_avg_fit_averages_raw_scores_and_rounds_once():
    a = _candidate("CPU", {"가격": 0.6440, "성능": 0.6440, "리뷰": 0.6440})     # 64.4
    b = _candidate("GPU", {"가격": 0.6649, "성능": 0.6649, "리뷰": 0.6649})     # 66.5
    snap = _snap(a, b)
    rows = [{"variant_id": c["variant_id"], "product_id": c["product_id"], "slot": c["slot"]} for c in (a, b)]
    out = avg_fit(snap, NEW, rows)
    assert out == {"score": display_points(math.fsum([a["rank_score"], b["rank_score"]]) / 2), "count": 2, "of": 2}
    assert out["score"] == 65.4
    # 부품별 표시 점수의 평균을 다시 반올림하면 65.5 가 된다 — 그 값이 아니다.
    assert display_points((display_points(a["rank_score"]) + display_points(b["rank_score"])) / 2 / 100) == 65.5


def test_avg_fit_counts_only_scored_parts_and_has_no_ad_field():
    a = _candidate("CPU", {"가격": 0.5, "성능": 0.5, "리뷰": 0.5})
    rows = [{"variant_id": a["variant_id"], "product_id": a["product_id"], "slot": "CPU"},
            {"variant_id": str(uuid.uuid4()), "product_id": str(uuid.uuid4()), "slot": "GPU"}]
    out = avg_fit(_snap(a), NEW, rows)
    assert out == {"score": 50.0, "count": 1, "of": 2}
    assert avg_fit(_snap(a), {"pipeline": "computer-v1"}, rows) == {"score": None, "count": 0, "of": 2}
    assert avg_fit(None, NEW, rows) == {"score": None, "count": 0, "of": 2}
    assert not [k for k in out if "ad" in k.split("_")]
    assert not [f for f in TotalsOut.model_fields if "ad_" in f or f.startswith("ad")]


# ── snapshot_step 검증 ────────────────────────────────────────────────────────

def _detail(value=0.5):
    return {"profile": {"profile_version": "p", "analysis_version": "a", "part_type": "gpu", "attributes": []},
            "value": value, "readiness": {"global_completeness_verified": False}, "contributions": []}


def _rank(axes, score=None, weights=WEIGHTS):
    variant, product = str(uuid.uuid4()), str(uuid.uuid4())
    cand = {"variant_id": variant, "product_id": product, "breakdown": axes, "review_detail": _detail(axes.get("리뷰", 0.5)),
            "score": math.fsum(weights[a] * axes[a] for a in AXES) if score is None else score}
    return (SimpleNamespace(weights_used=weights, slots={"GPU": {"pool": [cand]}}),
            SimpleNamespace(items=[SimpleNamespace(slot="GPU", variant_id=variant)]), cand)


def test_snapshot_step_stores_raw_score_axes_weights_and_method():
    axes = {"가격": 0.8, "성능": 0.6, "리뷰": 0.5}
    rank, build, cand = _rank(axes)
    entry = snapshot_step(rank, build, uuid.uuid4(), {})["review_snapshot"]["candidates"][cand["variant_id"]]
    assert entry["rank_score"] == cand["score"]                  # 반올림하지 않은 값 그대로
    assert entry["rank_breakdown"] == axes and entry["rank_weights"] == WEIGHTS and entry["score_method"] == "pc-fit-v2"


@pytest.mark.parametrize("mutate", ["score", "missing_axis", "bad_weights"])
def test_snapshot_step_rejects_inconsistent_rank(mutate):
    axes = {"가격": 0.8, "성능": 0.6, "리뷰": 0.5}
    if mutate == "score":
        rank, build, _ = _rank(axes, score=0.7)
    elif mutate == "missing_axis":
        rank, build, _ = _rank(axes)
        del rank.slots["GPU"]["pool"][0]["breakdown"]["성능"]
    else:
        rank, build, _ = _rank(axes)
        rank.weights_used = {"가격": 0.9, "성능": 0.4, "리뷰": 0.2}
    with pytest.raises(ValueError):
        snapshot_step(rank, build, uuid.uuid4(), {})


# ── 스키마 ────────────────────────────────────────────────────────────────────

def test_schema_adds_fields_and_keeps_existing_keys():
    assert {"item_id", "slot", "price", "qty", "budget_share", "review_detail", "reason", "checks"} <= set(ItemOut.model_fields)
    assert "fit" in ItemOut.model_fields
    assert FitOut().status == "unavailable"
    assert {"selected_price", "selected_units", "budget_remaining", "over_budget"} <= set(TotalsOut.model_fields)
    assert TotalsOut(selected_price=0, selected_units=0).avg_fit_score is None
    for key in ("eligibility", "margins", "explanation", "verification", "compat_checks", "reasoning_log"):
        assert key in RecommendResultOut.model_fields
    assert RecommendResultOut.model_fields["eligibility"].default is None
    # 후보 부족(candidates_insufficient)은 슬롯별 사유까지 응답에 남는다
    error = {"code": "candidates_insufficient", "message": "부족", "slots": {"GPU": {"reasons": ["x"]}}}
    assert RecommendErrorOut(**error).model_dump() == error
    status = ResultStatusOut(run_id="r", status="failed", explanation_status="pending", result_version="v", error=error)
    assert status.model_dump()["error"]["slots"] == error["slots"]


# ── DB: 저장·조회 왕복 ────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    from src.config import DATABASE_URL
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다.")
    try:
        yield connection
    finally:
        connection.close()
        clear_snapshot_cache()


def _build(conn, budget: int = 1_500_000) -> uuid.UUID:
    from src.auth.deps import Principal
    from src.services import session_service
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return revision_id


def _run(conn, revision_id):
    return EngineRepo(conn).get_latest_run_light(revision_id)


def _edit_snapshot(conn, run_id, edit):
    """저장된 snapshot 단계를 고쳐 쓴다(테스트가 snapshot 값을 정해 두려는 용도)."""
    log = conn.execute("SELECT reasoning_log FROM engine.recommendation_run WHERE id=%s", (run_id,)).fetchone()[0]
    for step in log:
        if step.get("step") == SNAPSHOT_STEP:
            edit(step["review_snapshot"])
    conn.execute("UPDATE engine.recommendation_run SET reasoning_log=%s WHERE id=%s", (Jsonb(log), run_id))
    clear_snapshot_cache()


def _fits(result):
    return {i["slot"]: i["fit"] for i in result["items"]}


@pytest.mark.db
def test_run_stores_new_method_versions(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    assert {k: run["engine_versions"][k] for k in NEW} == NEW
    rows = EngineRepo(conn).get_candidates(run["id"])
    assert rows and {r["score_method_version"] for r in rows} == {"pc-fit-v2"}


@pytest.mark.db
def test_result_fit_matches_raw_snapshot_not_the_four_digit_column(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    result = recommendation_service.get_stored_result(conn, revision_id)
    from src.services.recommendation_review_snapshot import cached_snapshot
    snapshot = cached_snapshot(EngineRepo(conn), run["id"])
    raw = []
    for item in result["items"]:
        cand = snapshot["candidates"][item["product"]["variant_id"]]
        fit = item["fit"]
        assert fit["status"] == "scored" and fit["method_version"] == "pc-fit-v2"
        assert fit["score"] == display_points(cand["rank_score"])
        assert [a["axis"] for a in fit["axes"]] == list(AXES)
        assert math.isclose(sum(a["weighted_points"] for a in fit["axes"]), fit["score"], abs_tol=0.31)
        raw.append(cand["rank_score"])
    totals = result["totals"]
    assert totals["avg_fit_score_of"] == len(result["items"]) and totals["avg_fit_score_count"] == len(raw)
    assert totals["avg_fit_score"] == display_points(math.fsum(raw) / len(raw))
    assert not [k for k in totals if k.startswith("ad")]
    # 기존 값은 그대로다 — budget_share 는 예산 비중, explanation.contribution 은 합 100 의 비율.
    assert all(i["budget_share"] is not None for i in result["items"] if i["selected"])
    assert result["explanation"]["contribution"] is None or sum(result["explanation"]["contribution"].values()) == 100


@pytest.mark.db
def test_raw_066449_shows_664_in_api_and_explanation_never_665(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    result = recommendation_service.get_stored_result(conn, revision_id)
    gpu = next(i for i in result["items"] if i["slot"] == "GPU")
    variant = gpu["product"]["variant_id"]
    weights, axes = {"가격": 0.5, "성능": 0.3, "리뷰": 0.2}, {"가격": 0.6, "성능": 0.7, "리뷰": 0.77245}

    def edit(snapshot):
        cand = snapshot["candidates"][variant]
        cand.update(rank_score=0.66449, rank_breakdown=axes, rank_weights=weights)
    _edit_snapshot(conn, run["id"], edit)
    conn.execute("UPDATE engine.recommendation_candidate SET score=0.6645 WHERE id=%s", (gpu["item_id"],))
    stored = [r for r in EngineRepo(conn).get_candidates(run["id"]) if r["slot"] == "GPU"][0]
    assert float(stored["score"]) == 0.6645                      # DB 네 자리 값은 66.5 로 읽힌다 — 표시는 이것이 아니다

    fit = _fits(recommendation_service.get_stored_result(conn, revision_id))["GPU"]
    assert fit["status"] == "scored" and fit["score"] == 66.4
    assert [a["points"] for a in fit["axes"]] == [60.0, 70.0, 77.2]
    assert fit["axes"][2]["weight"] == 0.2
    text = "\n".join(result_advice.pick_basis(conn, revision_id, "GPU", variant))
    assert "66.4점(100점 만점)" in text and "66.5" not in text and "가격 50%" in text, text


@pytest.mark.db
def test_snapshot_missing_or_invalid_is_unavailable_never_the_stored_score(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    variant = next(i for i in recommendation_service.get_stored_result(conn, revision_id)["items"] if i["slot"] == "CPU")["product"]["variant_id"]

    _edit_snapshot(conn, run["id"], lambda s: s["candidates"][variant].pop("rank_breakdown"))
    result = recommendation_service.get_stored_result(conn, revision_id)
    assert _fits(result)["CPU"]["status"] == "unavailable" and _fits(result)["CPU"]["reason"] == "invalid_snapshot"
    assert _fits(result)["CPU"]["score"] is None
    assert result["totals"]["avg_fit_score_count"] == result["totals"]["avg_fit_score_of"] - 1
    text = "\n".join(result_advice.pick_basis(conn, revision_id, "CPU", variant))
    assert "표시하지 못함" in text

    _edit_snapshot(conn, run["id"], lambda s: s["candidates"][variant].update(rank_breakdown={"가격": 0.1, "성능": 0.1, "리뷰": 0.1}))
    assert _fits(recommendation_service.get_stored_result(conn, revision_id))["CPU"]["reason"] == "invalid_snapshot"

    conn.execute("UPDATE engine.recommendation_run SET reasoning_log='[]'::jsonb WHERE id=%s", (run["id"],))
    clear_snapshot_cache()
    result = recommendation_service.get_stored_result(conn, revision_id)
    assert {f["reason"] for f in _fits(result).values()} == {"snapshot_missing"}
    assert result["totals"]["avg_fit_score"] is None and result["totals"]["avg_fit_score_count"] == 0


@pytest.mark.db
def test_legacy_run_has_no_fit_score(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    conn.execute("UPDATE engine.recommendation_run SET engine_versions=%s WHERE id=%s",
                 (Jsonb({"pipeline": "computer-v1"}), run["id"]))
    result = recommendation_service.get_stored_result(conn, revision_id)
    assert {f["status"] for f in _fits(result).values()} == {"legacy_method"}
    assert all(f["score"] is None and f["axes"] == [] for f in _fits(result).values())
    assert result["totals"]["avg_fit_score"] is None and result["totals"]["avg_fit_score_count"] == 0
    assert result["totals"]["avg_fit_score_of"] == len(result["items"])
    text = "\n".join(result_advice.pick_basis(conn, revision_id, "GPU", next(
        i for i in result["items"] if i["slot"] == "GPU")["product"]["variant_id"]))
    assert "100점으로 표시하지 않음" in text


@pytest.mark.db
def test_swapped_part_is_scored_only_when_in_the_snapshot_pool(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    erepo = EngineRepo(conn)
    result = recommendation_service.get_stored_result(conn, revision_id)
    gpu = next(i for i in result["items"] if i["slot"] == "GPU")
    from src.services.recommendation_review_snapshot import cached_snapshot
    pool = {v: c for v, c in cached_snapshot(erepo, run["id"])["candidates"].items() if c["slot"] == "GPU"}
    other = next(v for v in pool if v != gpu["product"]["variant_id"])
    swapped = recommendation_service.swap_item(conn, revision_id, uuid.UUID(gpu["item_id"]), uuid.UUID(other))
    fit = _fits(swapped)["GPU"]
    assert fit["status"] == "scored" and fit["score"] == display_points(pool[other]["rank_score"])
    assert swapped["totals"]["avg_fit_score_count"] == swapped["totals"]["avg_fit_score_of"]

    _edit_snapshot(conn, run["id"], lambda s: s["candidates"].pop(other))
    fit = _fits(recommendation_service.get_stored_result(conn, revision_id))["GPU"]
    assert fit["status"] == "unavailable" and fit["reason"] == "candidate_not_in_snapshot"


@pytest.mark.db
def test_eligibility_and_margins_come_from_the_stored_trace_even_while_explanation_pending(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    stored = EngineRepo(conn).get_run_steps(run["id"], ["추천 적격성", "조합 여유", "없는 단계"])
    assert set(stored) == {"추천 적격성", "조합 여유"}
    for pending in (False, True):
        if pending:
            conn.execute("UPDATE engine.recommendation_run SET explanation_status='pending', explanation_headline=NULL, "
                         "explanation_text=NULL WHERE id=%s", (run["id"],))
        result = recommendation_service.get_stored_result(conn, revision_id)
        assert result["explanation"]["status"] == ("pending" if pending else result["explanation"]["status"])
        assert result["eligibility"]["status"] == stored["추천 적격성"]["status"]
        assert [r["code"] for r in result["eligibility"]["reasons"]] == [r["code"] for r in stored["추천 적격성"]["reasons"]]
        assert all(r["text"] for r in result["eligibility"]["reasons"])
        assert result["margins"]["power"] == stored["조합 여유"]["margins"]["power"]
        assert result["margins"]["size"] == stored["조합 여유"]["margins"]["size"]
        assert result["margins"]["detail"] == stored["조합 여유"]["detail"]
    # 단계가 없는 옛 run 은 None
    conn.execute("UPDATE engine.recommendation_run SET reasoning_log=(SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) "
                 "FROM jsonb_array_elements(reasoning_log) e WHERE e->>'step' NOT IN ('추천 적격성','조합 여유')) WHERE id=%s", (run["id"],))
    clear_snapshot_cache()
    result = recommendation_service.get_stored_result(conn, revision_id)
    assert result["eligibility"] is None and result["margins"] is None


@pytest.mark.db
def test_eligibility_follows_the_reverified_set_after_a_swap(conn):
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    erepo = EngineRepo(conn)
    result = recommendation_service.get_stored_result(conn, revision_id)
    gpu = next(i for i in result["items"] if i["slot"] == "GPU")
    other = next(a for a in recommendation_service.list_alternatives(conn, revision_id, uuid.UUID(gpu["item_id"]))["items"]
                 if not a["current"])
    swapped = recommendation_service.swap_item(conn, revision_id, uuid.UUID(gpu["item_id"]), uuid.UUID(other["candidate_id"]))
    stored = erepo.get_run_steps(run["id"], ["추천 적격성", "조합 여유"])
    assert swapped["eligibility"]["status"] == stored["추천 적격성"]["status"]
    assert swapped["margins"]["power"] == stored["조합 여유"]["margins"]["power"]


# ── DB: 품목 순서(동점 정렬) ──────────────────────────────────────────────────

@pytest.mark.db
def test_candidate_order_is_deterministic_across_updates_and_clone(conn):
    from src.categories import load_category
    expected = load_category("computer")["slot_structure"]
    revision_id = _build(conn)
    run = _run(conn, revision_id)
    erepo = EngineRepo(conn)

    def slots():
        return [r["slot"] for r in erepo.get_candidates(run["id"])]

    assert slots() == expected
    rows = erepo.get_candidates(run["id"])
    for row in rows[::-1]:                                       # 행을 거꾸로 UPDATE 해 물리 위치를 옮긴다
        erepo.update_candidate_state(row["id"], qty=row["qty"], timing="later")
        erepo.update_candidate_reason(row["id"], "x")
    assert slots() == expected

    result = recommendation_service.get_stored_result(conn, revision_id)
    plan_id = PlanRepo(conn).get_revision(revision_id)["plan_id"]
    cloned_id = PlanRepo(conn).clone_revision(plan_id, revision_id)
    cloned = recommendation_service.get_stored_result(conn, cloned_id)
    assert [i["slot"] for i in cloned["items"]] == [i["slot"] for i in result["items"]] == expected

"""결과 화면의 "묻는 말" 계산(src/services/result_advice.py)과 규칙 경로 연결 — 실제 카탈로그 DB 로.

남은 예산으로 올릴 후보, 바꾸면 어떻게 되나(저장 안 함), 줄일 수 있는 것, 게임 요구 사양 비교.
공통 확인: 어떤 함수도 구성표를 바꾸지 않는다.
"""
from __future__ import annotations

import re
import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.repo.engine_repo import EngineRepo
from src.repo.plan_repo import PlanRepo
from src.services import recommendation_service, result_advice, session_service

_ID = re.compile(r"candidate_id=([0-9a-f-]{36})")


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        yield connection
    finally:
        connection.close()


def _build(conn, budget: int = 1_500_000, purpose: str = "game", priority: str = "value") -> uuid.UUID:
    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", purpose), ("budget_max", budget), ("priority", priority)):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return revision_id


def _snapshot(conn, revision_id) -> list[tuple]:
    run = recommendation_service._require_done_run(conn, revision_id)[1]
    return [(r["slot"], str(r["variant_id"]), r["qty"], r["selected"]) for r in EngineRepo(conn).get_candidates(run["id"])]


def test_upgrade_options_lists_only_better_compatible_parts_within_budget(conn):
    revision_id = _build(conn, budget=3_000_000)
    before = _snapshot(conn, revision_id)
    out = result_advice.upgrade_options(conn, revision_id)
    ctx = result_advice._context(conn, revision_id)
    budget = ctx.budget_max - ctx.total()
    ids = _ID.findall(out)
    assert ids, out
    for cid in ids:
        cand = ctx.by_variant[cid]
        row = ctx.row(cand.slot)
        current = ctx.by_variant[str(row["variant_id"])]
        assert cand.slot in ("CPU", "GPU", "RAM")
        assert result_advice._metric(cand.slot, cand.specs) > result_advice._metric(cand.slot, current.specs)
        assert 0 < (cand.price - row["price"]) * (row["qty"] or 1) <= budget
        assert not result_advice._new_failures(ctx, cand.slot, cand)
        assert result_advice._requirement_verdict(ctx, cand.slot, cand)[0] != "Fail"
    assert _snapshot(conn, revision_id) == before


def test_upgrade_options_with_new_budget_reports_remaining_against_the_new_budget(conn):
    from src.agent.result_agent import ResultSession
    revision_id = _build(conn)                       # 예산 150만
    result = recommendation_service.get_stored_result(conn, revision_id)
    out = ResultSession(conn=conn, revision_id=revision_id, result=result).upgrade_options(new_budget="200만원")
    pairs = re.findall(r"바꾼 뒤 총액 ([\d,]+)원, 바꾼 뒤 잔여 (-?[\d,]+)원", out)
    assert pairs, out
    for after, left in pairs:
        assert int(left.replace(",", "")) == 2_000_000 - int(after.replace(",", "")), out


def test_upgrade_options_with_tiny_amount_says_nothing_fits(conn):
    revision_id = _build(conn)
    out = result_advice.upgrade_options(conn, revision_id, 1)
    assert "추가 금액 1원" in out and "올릴 수 있는 후보가 없습니다" in out and not _ID.findall(out)


def test_preview_swap_reports_socket_mismatch_without_saving(conn):
    revision_id = _build(conn)
    before = _snapshot(conn, revision_id)
    ctx = result_advice._context(conn, revision_id)
    board_socket = ctx.chosen()["메인보드"].specs["socket"]
    other = next(c for c in ctx.pool["CPU"] if c.specs.get("socket") and c.specs["socket"] != board_socket)
    out = result_advice.preview_swap(conn, revision_id, "CPU", other.variant_id)
    assert out.startswith("(가정 계산 — 구성표는 그대로)")
    assert "⚠ 호환 점검 문제" in out and "소켓" in out
    assert _snapshot(conn, revision_id) == before


def test_preview_swap_up_picks_the_next_tier_and_reports_budget(conn):
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    out = result_advice.preview_swap(conn, revision_id, "GPU", direction="up")
    cand = ctx.by_variant[_ID.findall(out)[0]]
    now = result_advice._metric("GPU", ctx.chosen()["GPU"].specs)
    higher = [result_advice._metric("GPU", c.specs) for c in ctx.pool["GPU"]
              if (result_advice._metric("GPU", c.specs) or 0) > now and not result_advice._new_failures(ctx, "GPU", c)]
    assert result_advice._metric("GPU", cand.specs) == min(higher)
    assert "바꾼 뒤 총액" in out and ("잔여" in out or "예산 초과" in out)
    assert "전력:" in out or "⚠ 호환 점검 문제" in out


def test_savings_options_target_beyond_reach_says_so(conn):
    revision_id = _build(conn)
    out = result_advice.savings_options(conn, revision_id, 10_000_000)
    assert "을 줄이는 조합(부품 3개까지)은 없습니다" in out and "아직 아무것도 바꾸지 않았습니다" in out


def test_game_check_compares_table_tiers(conn):
    revision_id = _build(conn)
    out = result_advice.game_check(conn, revision_id, "사이버펑크")
    assert out.startswith("사이버펑크") and "GPU 성능 등급 요구" in out and "fps" in out
    assert "표에 없어" in result_advice.game_check(conn, revision_id, "없는게임123")


def test_rule_path_answers_questions_without_changing_the_build(conn):
    """에이전트가 없을 때(MOCK_MODE) — 묻는 말은 계산 결과로 답하고 구성표는 그대로다(P5)."""
    revision_id = _build(conn)
    before = _snapshot(conn, revision_id)

    up = recommendation_service.handle_result_message(conn, revision_id, "돈 남았는데 바꿀 거 추천해 줄 수 있나?")
    assert "올릴 수 있는 부품" in up["reply"] and "candidate_id" not in up["reply"]

    whatif = recommendation_service.handle_result_message(conn, revision_id, "그래픽카드 더 좋은 걸로 바꿔도 돼?")
    assert whatif["reply"].startswith("(가정 계산 — 구성표는 그대로)") and "바꿔줘" in whatif["reply"]

    power = recommendation_service.handle_result_message(conn, revision_id, "파워 용량 충분해?")
    assert "파워 용량" in power["reply"]
    assert "성능 등급과 이 용도 기준 등급: CPU" in power["reply"]          # 병목 질문의 근거 — 등급만, fps 아님

    game = recommendation_service.handle_result_message(conn, revision_id, "배그 돌아가?")
    assert "배틀그라운드" in game["reply"]
    assert _snapshot(conn, revision_id) == before

    # 바꾸라는 말은 예전처럼 바꾼다
    done = recommendation_service.handle_result_message(conn, revision_id, "그래픽카드를 더 저렴한 걸로 바꿔줘")
    assert "바꿨어요" in done["reply"] and _snapshot(conn, revision_id) != before


@pytest.mark.parametrize("text", [
    "왜 700만원 예산에 맞춰서 견적 짜달라 했는데 300만원에 짰어?", "예산 많이 남았는데 왜 다 안 썼어?",
    "예산을 왜 이것밖에 안 썼어?", "왜 예산을 덜 썼어", "예산 다 안 쓰고 남긴 이유가 뭐야?",
    # 10/8 표현 점검에서 놓치던 것
    "예산 다 안 쓴 거야?", "왜 이렇게 싸게 맞췄어?", "300만원밖에 안 나왔네?", "예산 더 써도 되는데 왜 이렇게 싸?",
    "왜 예산이 100만원 남았다고 나와?",
])
def test_budget_left_questions_are_recognized(text):
    assert result_advice.is_budget_left_question(text)


@pytest.mark.parametrize("text", [
    "남은 예산으로 뭘 올릴까?", "돈 남았는데 바꿀 거 추천해 줄 수 있나?", "왜 이 CPU 골랐어?", "그래픽카드 왜 이거야?",
    "10만원 더 쓰면 뭐가 좋아져?",
    # 넓힌 규칙이 잡으면 안 되는 것
    "남은 돈이 10만원밖에 안 되는데 뭐 올릴 수 있어?", "왜 이 SSD가 다른 것보다 싸?", "돈 남는데 더 좋은 걸로 해줘",
    "예산 안에서 그래픽카드 바꿔줘", "왜 이 케이스 골랐어? 싸서?", "50만원만 안 쓰면 되는데 뭘 빼?",
    # 부품 하나를 집은 말 — 세트를 고른 방식이 아니라 그 부품의 근거로 답한다(10/8 오탐 점검)
    "왜 SSD는 싸게 맞췄어?", "파워 너무 싸게 맞춘 거 아니야? 왜 그래?", "왜 쿨러는 기본으로 짰어? 돈 더 써도 돼",
    "왜 램을 16GB만 넣었어? 32GB 넣을 돈 남잖아", "왜 메모리가 16GB만 들어갔어? 돈 남잖아", "왜 수냉 쿨러 안 넣었어? 돈 남는데",
    "왜 이 메인보드는 다른 것보다 10만원 싸게 나왔어?", "왜 이 부품은 싸게 맞췄는지 설명해 줘",
    "왜 모니터 값은 안 들어갔어? 20만원 남았는데",
    # 가정·제약·앞으로의 이야기
    "예산 안 쓰고 중고로 사면 어때?", "왜 예산을 못 쓰게 막아놨어?", "예산을 안 쓴 부분은 다음에 쓸 수 있어?",
])
def test_other_questions_are_not_budget_left_questions(text):
    assert not result_advice.is_budget_left_question(text)


def test_budget_reason_explains_how_the_set_was_chosen_without_changing_it(conn):
    """700만원 예산에 300만원 구성이 나왔을 때 "근거를 확인할 수 없다"고만 답하던 것(2026-10-08) — 고르는 방식·이번
    점수 비중·용도 기준 등급과 지금 등급을 코드가 옮긴다."""
    revision_id = _build(conn, budget=7_000_000, purpose="office", priority="performance")
    before = _snapshot(conn, revision_id)
    ctx = result_advice._context(conn, revision_id)
    out = result_advice.budget_reason(conn, revision_id)
    assert f"잔여 {ctx.budget_max - ctx.total():,}원" in out, out
    assert "점수 합이 가장 높은 것" in out and "예산은 넘으면 안 되는 상한" in out
    assert "(성능 우선): 성능 55%" in out                       # 우선순위별 가중치 표 그대로
    assert "사무 용도 기준 등급" in out and "- CPU:" in out and "- GPU:" in out
    assert "\n→ " in out                                         # 결론 줄은 코드가 고른다
    assert _snapshot(conn, revision_id) == before


def test_budget_reason_for_value_priority_points_at_the_price_weight(conn):
    revision_id = _build(conn, budget=3_000_000)
    out = result_advice.budget_reason(conn, revision_id)
    assert "(가성비 우선): 가격 50%" in out and "→ 가성비 우선이라 가격 비중이 커서" in out, out


def test_rule_path_answers_why_the_budget_was_left(conn):
    revision_id = _build(conn, budget=7_000_000, purpose="office", priority="performance")
    reply = recommendation_service.handle_result_message(
        conn, revision_id, "왜 700만원 예산에 맞춰서 견적 짜달라 했는데 300만원에 짰어?")["reply"]
    assert "예산을 채우는 방식이 아니라" in reply, reply


def test_step_down_prefers_parts_that_still_meet_the_requirement(conn):
    """"파워 더 싼 걸로"가 요구 용량·효율을 못 채우는 파워를 고르던 것 — 채우는 후보가 있으면 그 안에서 고른다."""
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    cheaper_ok = [c for c in ctx.pool["파워"] if c.price < ctx.row("파워")["price"]
                  and result_advice._requirement_verdict(ctx, "파워", c)[0] != "Fail"
                  and not result_advice._new_failures(ctx, "파워", c)]
    cand = result_advice.step_candidate(ctx, "파워", "down")
    out = result_advice.preview_swap(conn, revision_id, "파워", direction="down")
    if cheaper_ok:
        assert cand.variant_id == max(cheaper_ok, key=lambda c: c.price).variant_id
        assert "요구 사양을 못 채움" not in out
    elif cand is not None:                      # 채우는 후보가 없으면 그 사실을 먼저 밝힌다
        assert out.startswith("이 견적의 요구 사양을 채우는 한 단계 아래 파워는 카탈로그에 없어") and "⚠" in out


def test_box_cooler_value_reaches_check_and_cpu_preview(conn):
    """카탈로그의 cpu_spec.cooler_included 를 채팅 근거로 쓴다 — 예전엔 아무도 읽지 않아 "데이터에 없다"고 답했다."""
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    cpu_vid = ctx.row("CPU")["variant_id"]
    raw = result_advice.box_cooler(conn, cpu_vid)
    out = result_advice.check_build(conn, revision_id)
    assert f"CPU 기본 쿨러(카탈로그 값): {raw or '정보 없음'}" in out

    # 별도 쿨러를 빼고, 기본 쿨러가 없는 CPU 로 바꾼다고 가정하면 경고
    cooler = ctx.row("쿨러")
    recommendation_service.patch_item(conn, revision_id, cooler["id"], selected=False, qty=None, timing=None)
    ctx = result_advice._context(conn, revision_id)
    no_box = next((c for c in ctx.pool["CPU"]
                   if result_advice._has_box_cooler(result_advice.box_cooler(conn, c.variant_id)) is False
                   and not result_advice._new_failures(ctx, "CPU", c)), None)
    if no_box is not None:
        preview = result_advice.preview_swap(conn, revision_id, "CPU", no_box.variant_id)
        assert "⚠ 별도 쿨러가 빠져 있는데 이 CPU는 기본 쿨러가 없을 수 있음" in preview


def test_target_plan_loses_the_least_performance_not_the_most_money(conn):
    """"10만원 정도 절약할 부품" — 예전엔 절약액 큰 것부터 더해 CPU 를 등급 8→4 로 내리며 18.6만원을 줄였다(시연).
    목표를 채우는 조합 중 성능 손실이 가장 적은 것을 고른다: 목표를 채우는 어떤 단일 교체보다 손실이 크지 않다."""
    revision_id = _build(conn, budget=1_240_000, purpose="office")
    ctx = result_advice._context(conn, revision_id)
    options = {r["slot"]: result_advice._cheaper_options(ctx, r["slot"]) for r in ctx.picked}
    target = 100_000
    plan = result_advice._target_plan(ctx, options, target)
    singles = [o for opts in options.values() for o in opts if o[0] >= target]
    if plan is None:
        assert not singles
        return
    (loss, _, saving), swaps = plan
    assert saving >= target
    assert all(loss <= o[1] for o in singles)
    out = result_advice.savings_options(conn, revision_id, target)
    assert "성능을 가장 적게 잃는 조합" in out


def test_relaxed_target_plan_is_summed_by_code(conn):
    """"20만원 줄이려면" — 요구 사양을 지켜선 안 될 때, 기준을 낮춘 조합의 합계도 코드가 낸다(모델이 더하다 틀렸다)."""
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    loose = {r["slot"]: result_advice._cheaper_options(ctx, r["slot"], allow_fail=True) for r in ctx.picked}
    plan = result_advice._target_plan(ctx, loose, 200_000)
    out = result_advice.savings_options(conn, revision_id, 200_000)
    if result_advice._target_plan(ctx, {r["slot"]: result_advice._cheaper_options(ctx, r["slot"]) for r in ctx.picked},
                                  200_000) is None and plan is not None:
        (_, _, saving), _ = plan
        assert f"요구 사양을 낮추면 200,000원 이상 줄일 수 있는 조합" in out and f"합계 절약 {saving:,}원" in out


def test_relaxing_only_lowers_performance_never_power_or_socket(conn):
    revision_id = _build(conn)
    ctx = result_advice._context(conn, revision_id)
    for row in ctx.picked:
        for saving, loss, cand in result_advice._cheaper_options(ctx, row["slot"], allow_fail=True):
            verdict, reasons = result_advice._requirement_verdict(ctx, row["slot"], cand)
            if verdict == "Fail":
                assert row["slot"] in ("CPU", "GPU", "RAM"), (row["slot"], reasons)

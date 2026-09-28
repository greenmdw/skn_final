"""E1 재탐색 루프(src/engine/research_loop.py).

C5(현황 문서): [4] 는 탐색 중 확정 비호환을 이미 걸러내므로, 후보 하나를 빼고 다시 찾아 나아질 수
있는 것은 "근사(확인 필요) 누적"뿐이다. 아래 테스트는 계획서 §3.1 E1 의 테스트 목록을 구현한다.
DB 통합 테스트(맨 아래, @pytest.mark.db) 하나를 빼고는 DB 가 필요 없다.
"""
from __future__ import annotations

from src.dto import BuildResult, Candidate, Issue, RankResult, RequirementSpec, VerificationResult, VerificationTarget
from src.engine import research_loop, stage2_requirement, stage3c_verify

_noop = lambda _m: None  # noqa: E731


def _cand(key: str, price: int, slot: str, *, name: str | None = None, score: float = 0.5, **specs) -> Candidate:
    return Candidate(product_key=key, slot=slot, name=name or key, brand="b", price=price, specs=specs, score=score)


def _base_pools(cooler_pool: list[Candidate]) -> dict[str, list[Candidate]]:
    """8슬롯 완성 세트 — 쿨러 축(cooler_height) 만 "근사"가 되도록 나머지 축은 전부 맞춘다."""
    return {
        "CPU": [_cand("cpu1", 240_000, "CPU", name="AMD Ryzen 5 7600", score=0.8, socket="AM5", tdp_w=65)],
        "GPU": [_cand("gpu1", 400_000, "GPU", score=0.8, length_mm=280, power_w=200, aux_power="X")],
        "RAM": [_cand("ram1", 90_000, "RAM", score=0.8, mem_type="DDR5")],
        "메인보드": [_cand("mb1", 155_000, "메인보드", score=0.8, socket="AM5", mem_type="DDR5", form_factor="ATX",
                        supported_cpu_family="Ryzen 7000 / 8000G / 9000 계열")],
        "저장장치": [_cand("ssd1", 100_000, "저장장치", score=0.8)],
        "파워": [_cand("psu1", 90_000, "파워", score=0.8, form_factor="ATX", wattage_w=650)],
        "케이스": [_cand("case1", 72_000, "케이스", score=0.8, psu_form_factor="ATX",
                       supports_form_factors=["ATX", "mATX"], max_gpu_len_mm=330, max_cooler_height_mm=170)],
        "쿨러": cooler_pool,
    }


def _rank_result(pools: dict[str, list[Candidate]]) -> RankResult:
    rr = RankResult()
    for slot, cands in pools.items():
        rr.slots[slot] = {"ideal_tier": None, "ranked": [c.model_dump() for c in cands], "bottleneck_hint": None}
    return rr


def _spec(pools: dict[str, list[Candidate]], owned: dict | None = None) -> RequirementSpec:
    return RequirementSpec(list_id="t", category="computer", mode="build",
                           targets={s: {} for s in pools}, budget={"total": 2_000_000, "alloc": {}},
                           owned=owned or {})


def _cooler_bad() -> Candidate:
    # height_mm 없음(비어 있는 스펙) — cooler_height 축이 "근사"가 된다.
    return _cand("cooler_bad", 58_000, "쿨러", name="쿨러 A(높이 미상)", score=0.9,
                supported_socket="AM5/AM4", cooling_type="Air (Dual-Tower)")


def _cooler_good() -> Candidate:
    return _cand("cooler_good", 60_000, "쿨러", name="쿨러 B", score=0.5,
                supported_socket="AM5/AM4", cooling_type="Air (Dual-Tower)", height_mm=150)


def _run(monkeypatch, pools, owned=None, threshold=95):
    """run_set_with_research 를 실경로와 같은 방식(verify_build + rule_based_exclusion)으로 돌린다."""
    monkeypatch.setattr(stage3c_verify, "CONFIDENCE_THRESHOLD", threshold)
    rank = _rank_result(pools)
    spec = _spec(pools, owned)
    computer_rules = stage2_requirement.load_computer_rules()
    rules = computer_rules["verification"]
    impact_slots = frozenset(computer_rules["ranking"].get("impact_slots", []))

    def verify(build, _round_index):
        return stage3c_verify.verify_build(build, "computer", _noop)

    def choose(build, verification):
        chosen = research_loop.resolve_chosen(rank, build)
        return research_loop.rule_based_exclusion(build, verification, chosen, spec, rules, impact_slots=impact_slots)

    return research_loop.run_set_with_research(rank, spec, _noop, verify=verify, choose_exclusion=choose)


# ── 1) 근사 쟁점 → 대체 후보가 있으면 2라운드 구성이 채택된다 ─────────────────────

def test_pending_axis_switches_to_a_candidate_with_data_in_round_2(monkeypatch):
    pools = _base_pools([_cooler_bad(), _cooler_good()])
    build, verification, rounds = _run(monkeypatch, pools)

    assert len(rounds) == 2
    cooler = next(i for i in build.items if i.slot == "쿨러")
    assert cooler.product_key == "cooler_good"
    assert verification.targets[0].passed is True
    assert verification.targets[0].rounds == 2
    assert rounds[0].excluded == {"slot": "쿨러", "name": "쿨러 A(높이 미상)", "axis": "cooler_height"}
    # 통과해서 끝난 라운드는 stop_reason="passed" — 다른 이유(소진/개선 불가)와 구분된다(E1 감사).
    assert rounds[-1].stop_reason == "passed"
    assert rounds[0].stop_reason is None   # 마지막 라운드에만 채워진다


# ── 2) 대체가 없으면 1라운드 결과가 유지된다(악화 없음) ──────────────────────────

def test_no_alternative_keeps_round_1_result(monkeypatch):
    pools = _base_pools([_cooler_bad()])
    build, verification, rounds = _run(monkeypatch, pools)

    # 대안이 없어 2라운드를 시도해도(빈 슬롯 → set 실패, 신뢰도 더 낮음) 1라운드보다 나빠지지 않는다.
    assert len(rounds) == 2
    cooler = next(i for i in build.items if i.slot == "쿨러")
    assert cooler.product_key == "cooler_bad"
    assert verification.targets[0].confidence == 94
    assert verification.targets[0].rounds == 1
    # 2라운드에서 choose_exclusion이 None을 반환(set 실패만 남아 재탐색 대상이 없음, C5) —
    # 라운드가 실제로 소진된 게 아니므로 stop_reason이 "max_rounds_exhausted"가 아니라
    # "no_researchable_exclusion"이어야 한다(E1 감사 — 이전엔 둘 다 "소진"으로 잘못 뭉뚱그렸다).
    assert rounds[-1].stop_reason == "no_researchable_exclusion"


# ── 3) 업그레이드 유지 부품(spec.owned)은 절대 제외되지 않는다 ────────────────────

def test_kept_owned_slot_is_never_chosen_for_exclusion(monkeypatch):
    spec = RequirementSpec(list_id="t", category="computer", mode="upgrade",
                           owned={"쿨러": {"name": "기존 쿨러", "specs": {}}})
    chosen = {
        "쿨러": _cand("cooler_kept", 1, "쿨러"),
        "GPU": _cand("gpu1", 1, "GPU"),
    }
    build = BuildResult(list_id="t")

    def fake_details(_chosen, _spec, _rules):
        return [{"axis": "cooler_height", "missing_slots": ("쿨러",)},
                {"axis": "gpu_len", "missing_slots": ("GPU",)}]
    monkeypatch.setattr(research_loop.stage4_optimize, "pc_compat_details", fake_details)

    verification = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=88, passed=False, issues=[
            Issue(axis="cooler_height", judge="확인 필요", penalty=6),
            Issue(axis="gpu_len", judge="확인 필요", penalty=6),
        ]),
    ])
    # 쿨러는 owned 라 건너뛰고, 다음 쟁점(gpu_len)의 GPU 가 대신 뽑힌다.
    choice = research_loop.rule_based_exclusion(build, verification, chosen, spec, {})
    assert choice == ("GPU", "gpu1", "gpu_len")

    # 뺄 수 있는 슬롯이 owned 뿐이면 제외 대상이 없다 — None.
    def fake_details_owned_only(_chosen, _spec, _rules):
        return [{"axis": "cooler_height", "missing_slots": ("쿨러",)}]
    monkeypatch.setattr(research_loop.stage4_optimize, "pc_compat_details", fake_details_owned_only)
    verification_owned_only = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=94, passed=False, issues=[
            Issue(axis="cooler_height", judge="확인 필요", penalty=6),
        ]),
    ])
    assert research_loop.rule_based_exclusion(build, verification_owned_only, chosen, spec, {}) is None


# ── 4) set/budget(예산) 실패만 있으면 1라운드에서 끝난다 ─────────────────────────

def test_set_or_budget_only_issues_are_not_researchable():
    spec = RequirementSpec(list_id="t", category="computer", mode="build")
    build = BuildResult(list_id="t")
    verification = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=65, passed=False, issues=[
            Issue(axis="set", judge="위반", penalty=20),
            Issue(axis="예산", judge="초과", penalty=15),
        ]),
    ])
    assert research_loop.rule_based_exclusion(build, verification, {}, spec, {}) is None


# ── 5) 영향이 큰 슬롯(ranking.impact_slots, 보통 CPU·GPU)은 제외 대상이 될 수 없다 ─

def test_impact_slots_are_never_chosen_for_exclusion(monkeypatch):
    """리뷰 지적: CPU 전력 데이터가 없다는 이유만으로 CPU 를 빼면 성능이 눈에 띄게 낮은
    구성이 "확인 필요 건수 감소"만으로 채택될 수 있다. impact_slots 는 항상 건너뛴다."""
    spec = RequirementSpec(list_id="t", category="computer", mode="build")
    build = BuildResult(list_id="t")
    chosen = {
        "CPU": _cand("cpu1", 1, "CPU"),
        "파워": _cand("psu1", 1, "파워"),
        "메인보드": _cand("mb1", 1, "메인보드"),
    }

    # 5-1) power 축의 유일한 missing_slot이 CPU(impact_slots) 뿐이면 건너뛰고 다음 쟁점(psu_form)으로.
    def fake_power_and_psu_form(_chosen, _spec, _rules):
        return [{"axis": "power", "missing_slots": ("CPU",)},
                {"axis": "psu_form", "missing_slots": ("파워",)}]
    monkeypatch.setattr(research_loop.stage4_optimize, "pc_compat_details", fake_power_and_psu_form)
    verification = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=82, passed=False, issues=[
            Issue(axis="power", judge="확인 필요", penalty=6),
            Issue(axis="psu_form", judge="확인 필요", penalty=6),
        ]),
    ])
    choice = research_loop.rule_based_exclusion(build, verification, chosen, spec, {}, impact_slots={"CPU", "GPU"})
    assert choice == ("파워", "psu1", "psu_form")

    # 5-2) 같은 축 안에 impact_slots 아닌 다른 missing_slot이 있으면 그쪽을 대신 고른다.
    def fake_bios_pair(_chosen, _spec, _rules):
        return [{"axis": "bios", "missing_slots": ("CPU", "메인보드")}]
    monkeypatch.setattr(research_loop.stage4_optimize, "pc_compat_details", fake_bios_pair)
    verification_pair = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=94, passed=False, issues=[
            Issue(axis="bios", judge="확인 필요", penalty=6),
        ]),
    ])
    choice_pair = research_loop.rule_based_exclusion(build, verification_pair, chosen, spec, {}, impact_slots={"CPU", "GPU"})
    assert choice_pair == ("메인보드", "mb1", "bios")

    # 5-3) 뺄 수 있는 슬롯이 impact_slots(CPU) 뿐이고 다른 쟁점도 없으면 제외 대상이 없다.
    def fake_power_only(_chosen, _spec, _rules):
        return [{"axis": "power", "missing_slots": ("CPU",)}]
    monkeypatch.setattr(research_loop.stage4_optimize, "pc_compat_details", fake_power_only)
    verification_cpu_only = VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=94, passed=False, issues=[
            Issue(axis="power", judge="확인 필요", penalty=6),
        ]),
    ])
    assert research_loop.rule_based_exclusion(
        build, verification_cpu_only, chosen, spec, {}, impact_slots={"CPU", "GPU"}) is None


# ── run_set_with_research: 종료 이유(stop_reason) 3종 구분 ─────────────────────
# 계획 §3.1 E1(C5): "재탐색으로 개선 불가"는 라운드가 실제로 소진된 것과 다른 사유다.
# stage4_optimize.run 을 목으로 바꿔 순수하게 루프 제어 흐름만(진짜 PC 카탈로그 없이) 본다.

def _fake_stage4_run(_rank, _spec, _log, **kw):
    return BuildResult(list_id="t", round=kw.get("round_no", 1))


def _not_passed_verification(confidence: int = 50) -> VerificationResult:
    return VerificationResult(list_id="t", category="computer", mode="set", targets=[
        VerificationTarget(subject="세트 전체", confidence=confidence, passed=False,
                           issues=[Issue(axis="cooler_height", judge="확인 필요", penalty=6)]),
    ])


def test_stop_reason_no_exclusion_strategy_when_choose_exclusion_is_none(monkeypatch):
    """choose_exclusion 자체를 안 넘기면(호출부가 재탐색을 안 쓰기로 함) 1라운드에서 곧바로
    끝난다 — 이것도 "소진"이 아니라 별개 사유(no_exclusion_strategy)다."""
    monkeypatch.setattr(research_loop.stage4_optimize, "run", _fake_stage4_run)
    rank = RankResult()
    spec = RequirementSpec(list_id="t", category="computer", mode="build")

    def verify(_build, _round_index):
        return _not_passed_verification()

    build, verification, rounds = research_loop.run_set_with_research(
        rank, spec, _noop, verify=verify, choose_exclusion=None,
    )
    assert len(rounds) == 1
    assert rounds[-1].stop_reason == "no_exclusion_strategy"
    assert verification.targets[0].passed is False
    assert verification.targets[0].transcript[0]["stop_reason"] == "no_exclusion_strategy"


def test_stop_reason_max_rounds_exhausted_when_always_researchable_but_never_passes(monkeypatch):
    """매 라운드 뺄 후보가 있어도(choose_exclusion 이 항상 선택지를 냄) MAX_RESEARCH_ROUNDS
    를 다 쓰면 진짜 "소진"이다 — no_researchable_exclusion 과 구분된다."""
    monkeypatch.setattr(research_loop.stage4_optimize, "run", _fake_stage4_run)
    rank = RankResult()
    spec = RequirementSpec(list_id="t", category="computer", mode="build")

    def verify(_build, _round_index):
        return _not_passed_verification()

    calls = {"n": 0}

    def choose(_build, _verification):
        calls["n"] += 1
        return ("쿨러", f"alt{calls['n']}", "cooler_height")   # 항상 뺄 게 있다고 답한다

    build, verification, rounds = research_loop.run_set_with_research(
        rank, spec, _noop, verify=verify, choose_exclusion=choose,
    )
    from src.config import MAX_RESEARCH_ROUNDS

    assert len(rounds) == MAX_RESEARCH_ROUNDS
    assert rounds[-1].stop_reason == "max_rounds_exhausted"
    assert verification.targets[0].passed is False
    # 소진 전까지는 매 라운드 실제로 제외를 시도했다 — "개선 불가"로 곧바로 끝난 게 아니다.
    assert all(rec.excluded is not None for rec in rounds[:-1])


# ── research_trace_detail: 채택 라운드까지만 "빼고 다시 구성"으로 서술한다 ────────

def _trace_record(round_no: int, issue_count: int, *, excluded: dict | None = None, confidence: int = 100):
    target = VerificationTarget(
        subject="세트 전체", confidence=confidence, passed=(issue_count == 0),
        issues=[Issue(axis="x", judge="확인 필요", penalty=1) for _ in range(issue_count)],
    )
    verification = VerificationResult(list_id="t", category="computer", mode="set", targets=[target])
    return research_loop.RoundRecord(round=round_no, build=BuildResult(list_id="t", round=round_no),
                                     verification=verification, excluded=excluded)


def test_research_trace_detail_none_when_only_one_round():
    assert research_loop.research_trace_detail([_trace_record(1, issue_count=0)]) is None


def test_research_trace_detail_two_rounds_adopts_the_last():
    records = [
        _trace_record(1, issue_count=1, confidence=94,
                      excluded={"slot": "쿨러", "name": "A", "axis": "cooler_height"}),
        _trace_record(2, issue_count=0, confidence=100),
    ]
    detail = research_loop.research_trace_detail(records)
    assert detail == ("확인 필요 1건 → 쿨러 'A'(쿨러 높이 확인 필요)를 빼고 다시 구성 → "
                      "확인 필요 0건 구성 채택")


def test_research_trace_detail_three_rounds_adopts_the_middle_one():
    # 3라운드까지 돌았지만 2라운드가 채택 — 2라운드 "뒤"에 뺀 부품(3라운드용)은 나열하지 않는다.
    records = [
        _trace_record(1, issue_count=2, confidence=88,
                      excluded={"slot": "쿨러", "name": "A", "axis": "cooler_height"}),
        _trace_record(2, issue_count=1, confidence=94,
                      excluded={"slot": "GPU", "name": "B", "axis": "gpu_len"}),
        _trace_record(3, issue_count=1, confidence=80),
    ]
    detail = research_loop.research_trace_detail(records)
    assert detail == ("확인 필요 2건 → 쿨러 'A'(쿨러 높이 확인 필요)를 빼고 다시 구성 → "
                      "확인 필요 1건 구성 채택 "
                      "(이후 1회 더 구성해 봤지만 확인 필요 건수가 줄지 않아 채택하지 않음)")
    assert "GPU" not in detail
    assert "B" not in detail


def test_research_trace_detail_round_1_kept_says_so_without_implying_a_part_was_removed():
    # 재탐색을 시도했지만 나아지지 않아 1라운드가 유지되는 경우 — "X 를 빼고" 로 읽히면 안 된다.
    records = [
        _trace_record(1, issue_count=1, confidence=94,
                      excluded={"slot": "쿨러", "name": "A", "axis": "cooler_height"}),
        _trace_record(2, issue_count=1, confidence=80),
    ]
    detail = research_loop.research_trace_detail(records)
    assert detail == ("확인 필요 1건 — 처음 구성 유지 "
                      "(이후 1회 더 구성해 봤지만 확인 필요 건수가 줄지 않아 채택하지 않음)")
    assert "빼고" not in detail


# ── DB 통합: execute_recommendation 이 저장한 구성 == 채택 라운드 구성 ───────────
# 로컬 PostgreSQL + PC 카탈로그 seed 가 필요하다(tests/test_reverify_after_swap.py 와 같은 방식).

import uuid  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402

from src.auth.deps import Principal  # noqa: E402
from src.config import DATABASE_URL  # noqa: E402


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        ok = connection.execute("SELECT to_regclass('config.domain_version') IS NOT NULL").fetchone()[0]
        if not (ok and connection.execute("SELECT count(*) FROM catalog.cpu_spec").fetchone()[0] > 0):
            pytest.skip("PC 카탈로그가 seed 되지 않았습니다 — db/setup_all.py로 준비하세요.")
        yield connection
    finally:
        connection.close()


@pytest.mark.db
def test_execute_recommendation_persists_the_adopted_research_round(conn):
    """저장된 후보가 재탐색 루프의 채택 라운드(run_set_with_research 의 best) 구성과 같다.

    execute_recommendation 이 실제로 쓰는 것과 같은 함수(research_loop.run_set_with_research +
    rule_based_exclusion)를 같은 조건·같은 DB 상태로 독립적으로 다시 돌려 비교한다 — 엔진은
    결정적이라 같은 입력엔 같은 결과가 나와야 한다(중간 라운드가 아니라 채택된 라운드가 저장됐는지 확인).
    """
    from src.categories import load_category
    from src.engine import research_loop, stage2_requirement, stage3a_hardfilter, stage3b_rank
    from src.engine import stage3c_verify as s3c
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service as rs
    from src.services import session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 2_000_000), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = rs.start_recommendation(conn, revision_id, strategy="default")
    rs.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    stored = rs.get_stored_result(conn, revision_id)

    full = PlanRepo(conn).load_full(revision_id)
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    cat_def = load_category("computer")
    slots = rs._slots_from_conditions("computer", cat_def, values)
    spec = stage2_requirement.run(slots, cat_def, _noop)
    spec.list_id = str(revision_id)
    by_slot = load_candidates_by_slot_from_db(conn)
    hf = stage3a_hardfilter.run(spec, by_slot, _noop)
    rank = stage3b_rank.run(hf, spec, slots, _noop)
    computer_rules = stage2_requirement.load_computer_rules()
    rules = computer_rules["verification"]
    impact_slots = frozenset(computer_rules["ranking"].get("impact_slots", []))

    def verify(b, _round_index):
        return s3c.verify_build(b, "computer", _noop)

    def choose(b, v):
        chosen = research_loop.resolve_chosen(rank, b)
        return research_loop.rule_based_exclusion(b, v, chosen, spec, rules, impact_slots=impact_slots)

    build, _verification, _rounds = research_loop.run_set_with_research(
        rank, spec, _noop, verify=verify, choose_exclusion=choose,
    )

    stored_variant_by_slot = {i["slot"]: i["product"]["variant_id"] for i in stored["items"]}
    build_variant_by_slot = {i.slot: i.variant_id for i in build.items}
    assert stored_variant_by_slot == build_variant_by_slot

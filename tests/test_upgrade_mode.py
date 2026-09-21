"""PC 업그레이드 모드 — 고른 부품만 견적을 내고, 그대로 쓰는 부품과의 호환을 본다.

회귀 배경: mode=upgrade 와 upgrade_parts·current_specs 를 화면에서 받는데 엔진이 전부 무시해서, GPU 만
바꾸겠다고 해도 8부품 새 견적이 나왔다. 여기서는 (1) 요구사양이 고른 슬롯으로 좁혀지는지,
(2) 유지 부품(current_specs)이 호환성 검사에 쓰이는지, (3) 모르는 것을 지어내지 않는지,
(4) 세션 -> 사양 파일 -> 추천 -> 결과 전체 흐름을 확인한다."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.dto import Candidate, RankResult, RequirementSpec, Slots
from src.engine import stage2_requirement
from src.engine.owned_parts import constrain_targets, resolve_owned_parts
from src.engine.stage4_optimize import build_computer

ALL_SLOTS = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]


def _slots(mode="upgrade", **values) -> Slots:
    return Slots(category="computer", mode=mode, objective_text="", values=values)


def _spec(**values):
    return stage2_requirement.run(_slots(**values), {}, lambda _: None)


def cand(slot, key, price=100, score=1.0, **specs) -> Candidate:
    return Candidate(slot=slot, product_key=key, name=key, price=price, score=score, specs=specs)


# ── [2] 요구사양: 고른 슬롯만 ─────────────────────────────────────────────────

def test_upgrade_restricts_targets_to_the_chosen_parts_in_canonical_order():
    spec = _spec(upgrade_parts=["쿨러", "GPU"], purpose="game", budget_max=500_000)
    assert list(spec.targets) == ["GPU", "쿨러"] and "upgrade" in spec.flags and spec.mode == "upgrade"


def test_build_mode_still_covers_all_slots_even_if_upgrade_parts_is_present():
    assert list(_spec(mode="build", upgrade_parts=["GPU"], purpose="game").targets) == ALL_SLOTS


@pytest.mark.parametrize("raw, slot", [("GPU", "GPU"), ("gpu", "GPU"), ("그래픽카드", "GPU"), ("PSU", "파워"),
                                       ("메모리", "RAM"), ("motherboard", "메인보드"), ("SSD", "저장장치")])
def test_part_names_are_normalised(raw, slot):
    assert list(_spec(upgrade_parts=[raw], purpose="game").targets) == [slot]


def test_comma_separated_string_is_accepted_too():
    assert list(_spec(upgrade_parts="CPU, 파워", purpose="game").targets) == ["CPU", "파워"]


def test_unrecognised_parts_are_reported_not_guessed():
    spec = _spec(upgrade_parts=["GPU", "선풍기"], purpose="game")
    assert list(spec.targets) == ["GPU"]
    assert spec.unresolved == [{"key": "upgrade_parts", "value": "선풍기", "reason": "알 수 없는 부품"}]
    assert _spec(upgrade_parts=["foo"], purpose="game").targets == {}
    assert _spec(purpose="game").targets == {}                       # upgrade_parts 자체가 없을 때


def test_budget_allocation_is_renormalised_over_the_chosen_parts():
    alloc = _spec(upgrade_parts=["GPU", "쿨러"], purpose="game", budget_max=1).budget["alloc"]
    assert set(alloc) == {"GPU", "쿨러"} and sum(alloc.values()) == pytest.approx(1.0)
    assert alloc["GPU"] > alloc["쿨러"]


def test_requirement_floors_of_the_purpose_still_apply_to_the_chosen_parts():
    game = _spec(upgrade_parts=["GPU"], purpose="game", resolution="4K").targets["GPU"]
    office = _spec(upgrade_parts=["GPU"], purpose="office").targets["GPU"]
    assert game["perf_tier_min"] > office["perf_tier_min"]


# ── 유지 부품 해석 ───────────────────────────────────────────────────────────

def _named(slot, name, **specs) -> Candidate:
    return Candidate(slot=slot, product_key=name, name=name, price=1, specs=specs)


POOL = {
    "CPU": [_named("CPU", "Intel Core i5-13600K", socket="LGA1700", tdp_w=125, perf_tier=8),
            _named("CPU", "AMD Ryzen 5 5600X", socket="AM4", tdp_w=65),
            _named("CPU", "AMD Ryzen 5 7600", socket="AM5", tdp_w=65)],
    "GPU": [_named("GPU", "NVIDIA GeForce RTX 3060 (12GB)", power_w=170, length_mm=242),
            _named("GPU", "NVIDIA GeForce RTX 3060 12GB", power_w=170, length_mm=242),
            _named("GPU", "NVIDIA GeForce RTX 3060 Ti", power_w=200, length_mm=242),
            _named("GPU", "NVIDIA GeForce RTX 3050 (6GB)", power_w=70, length_mm=200),
            _named("GPU", "NVIDIA GeForce RTX 3050 (8GB)", power_w=130, length_mm=230)],
    "메인보드": [_named("메인보드", "ASUS PRIME H610M-K D4", socket="LGA1700", mem_type="DDR4")],
}


def _owned(current, keep=("CPU", "GPU", "RAM", "메인보드", "파워", "케이스", "쿨러", "저장장치")):
    return resolve_owned_parts(current, POOL, keep)


def test_model_name_matches_the_catalog_and_brings_its_specs():
    owned = _owned({"CPU": "i5-13600K"})["CPU"]
    assert owned["source"] == "catalog" and owned["name"] == "Intel Core i5-13600K"
    assert owned["specs"]["socket"] == "LGA1700" and owned["specs"]["perf_tier"] == 8


def test_match_is_exact_per_token_5600_is_not_5600x():
    owned = _owned({"CPU": "Ryzen 5 5600"})["CPU"]
    assert owned["source"] == "inferred"                       # 카탈로그 대응이 아니라 세대 규칙으로 읽었다
    assert owned["specs"] == {"socket": "AM4"}                 # 5600X 의 카탈로그 스펙(tdp_w 등)이 새어 들지 않는다


def test_rtx_3060_is_not_confused_with_the_ti():
    owned = _owned({"GPU": "RTX 3060"})["GPU"]
    assert owned["source"] == "catalog" and owned["specs"]["power_w"] == 170        # Ti(200W)가 아니다


def test_ambiguous_match_keeps_only_the_values_all_candidates_agree_on():
    owned = _owned({"GPU": "RTX 3050"})["GPU"]                                      # 6GB(70W) / 8GB(130W)
    assert owned["source"] == "catalog"
    assert "power_w" not in owned["specs"]                                          # 갈리는 값은 지어내지 않는다
    assert "length_mm" not in owned["specs"]


def test_text_without_a_model_number_is_not_matched_to_a_catalog_part():
    owned = _owned({"CPU": "Intel Core"})["CPU"]
    assert owned["source"] == "unverified" and owned["specs"] == {}


def test_ram_is_never_matched_by_capacity_only_the_ddr_generation_is_read():
    ram = _owned({"RAM": "DDR4 32GB"})["RAM"]
    assert ram["source"] == "text" and ram["specs"] == {"mem_type": "DDR4"}
    assert _owned({"RAM": "32GB"})["RAM"]["source"] == "unverified"


def test_specs_readable_from_plain_text_are_used_when_the_catalog_has_no_match():
    assert _owned({"메인보드": "AM4 DDR4"})["메인보드"]["specs"] == {"socket": "AM4", "mem_type": "DDR4"}
    assert _owned({"메인보드": "LGA 1700"})["메인보드"]["specs"] == {"socket": "LGA1700"}
    assert _owned({"파워": "650W 골드"})["파워"]["specs"] == {"wattage_w": 650}


def test_only_kept_slots_the_user_described_are_resolved():
    owned = _owned({"CPU": "i5-13600K", "GPU": "RTX 3060"}, keep=["CPU"])
    assert list(owned) == ["CPU"]
    assert _owned({}) == {} and resolve_owned_parts(None, POOL, ["CPU"]) == {}
    assert resolve_owned_parts({"cpu": "i5-13600K"}, POOL, ["CPU"])["CPU"]["source"] == "catalog"   # 키 별칭


# ── 유지 부품이 요구 플랫폼을 정한다 ─────────────────────────────────────────

def _upgrade_spec(parts, owned, **values):
    spec = _spec(upgrade_parts=parts, purpose="game", **values)
    spec.owned = owned
    constrain_targets(spec)
    return spec


def test_owned_board_platform_replaces_the_new_build_socket_and_ddr_floor():
    spec = _upgrade_spec(["CPU", "RAM"], _owned({"메인보드": "AM4 DDR4"}))
    assert spec.targets["CPU"]["socket_in"] == ["AM4"] and spec.targets["RAM"]["type"] == "DDR4"


def test_owned_cpu_and_ram_decide_the_board_requirements():
    spec = _upgrade_spec(["메인보드"], _owned({"CPU": "i5-13600K", "RAM": "DDR4 16GB"}))
    assert spec.targets["메인보드"]["socket_in"] == ["LGA1700"] and spec.targets["메인보드"]["mem_type"] == "DDR4"


def test_unknown_owned_parts_leave_the_default_requirements_untouched():
    plain = _spec(upgrade_parts=["CPU"], purpose="game").targets["CPU"]["socket_in"]
    assert _upgrade_spec(["CPU"], {}).targets["CPU"]["socket_in"] == plain


# ── [4] 호환 검사에 유지 부품이 들어간다 ─────────────────────────────────────

def _build(pools, owned, budget=10_000):
    rank = RankResult(slots={s: {"ranked": [c.model_dump() for c in cs]} for s, cs in pools.items()})
    spec = RequirementSpec(list_id="u", category="computer", mode="upgrade",
                           targets={s: {} for s in pools}, budget={"total": budget}, owned=owned)
    return build_computer(rank, spec, lambda _: None)


def test_result_lists_only_the_upgraded_parts_and_the_budget_counts_only_them():
    result = _build({"GPU": [cand("GPU", "g", 400)]}, {"CPU": {"name": "c", "specs": {}, "source": "text"}})
    assert [i.slot for i in result.items] == ["GPU"] and result.totals["price"] == 400


def test_cpu_must_match_the_socket_of_the_kept_board_even_if_another_scores_higher():
    pools = {"CPU": [cand("CPU", "lga", score=9, socket="LGA1700"), cand("CPU", "am4", score=1, socket="AM4")]}
    owned = {"메인보드": {"name": "b", "specs": {"socket": "AM4"}, "source": "text"}}
    result = _build(pools, owned)
    assert [i.product_key for i in result.items] == ["am4"] and result.link_check["socket"] == "ok"


def test_incompatible_only_pool_is_marked_failed_not_hidden():
    pools = {"CPU": [cand("CPU", "lga", socket="LGA1700")]}
    owned = {"메인보드": {"name": "b", "specs": {"socket": "AM4"}, "source": "text"}}
    result = _build(pools, owned)
    assert result.link_check["socket"] == "fail" and result.link_check["set"] == "fail"


def test_power_budget_uses_the_kept_gpu_and_psu():
    pools = {"CPU": [cand("CPU", "hot", score=9, tdp_w=125), cand("CPU", "cool", score=1, tdp_w=65)]}
    owned = {"GPU": {"name": "g", "specs": {"power_w": 170}, "source": "catalog"},
             "파워": {"name": "p", "specs": {"wattage_w": 300}, "source": "text"}}
    result = _build(pools, owned)                     # 300W*0.9=270 → CPU 은 100W 이하여야 한다
    assert [i.product_key for i in result.items] == ["cool"] and result.link_check["power"] == "ok"


def test_gpu_length_is_checked_against_the_kept_case():
    pools = {"GPU": [cand("GPU", "long", score=9, length_mm=330), cand("GPU", "short", score=1, length_mm=250)]}
    owned = {"케이스": {"name": "k", "specs": {"max_gpu_len_mm": 300}, "source": "catalog"}}
    assert [i.product_key for i in _build(pools, owned).items] == ["short"]


def test_unknown_kept_parts_are_not_treated_as_failures():
    result = _build({"CPU": [cand("CPU", "c", socket="AM5")]}, {})
    assert result.link_check["socket"] == "ok (근사)" and "set" not in result.link_check


def test_balance_is_pending_when_a_tier_is_unknown_and_real_when_both_are_known():
    unknown = _build({"GPU": [cand("GPU", "g", perf_tier=6)]}, {})
    assert unknown.balance["verdict"] == "판단 보류"
    owned = {"CPU": {"name": "c", "specs": {"perf_tier": 6}, "source": "catalog"}}
    known = _build({"GPU": [cand("GPU", "g", perf_tier=6)]}, owned)
    assert known.balance["verdict"] == "균형"


# ── 사양 파일 파서 ───────────────────────────────────────────────────────────

def test_spec_file_parser_reads_all_partial_upgrade_keys():
    from src.services.session_service import _parse_spec_file

    text = "CPU: i5-13600K\nGPU: RTX 3060\nRAM: DDR4 16GB\n메인보드: AM4 DDR4\nPSU: 650W\n케이스: 미들타워\n쿨러: 순정\n"
    assert _parse_spec_file(text) == {"CPU": "i5-13600K", "GPU": "RTX 3060", "RAM": "DDR4 16GB",
                                      "메인보드": "AM4 DDR4", "파워": "650W", "케이스": "미들타워", "쿨러": "순정"}
    assert _parse_spec_file("아무 말\n") == {}


# ── 종단: 세션 -> 사양 파일 -> 추천 -> 결과 (로컬 PostgreSQL + PC 카탈로그 seed 필요) ──────────

@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        ok = connection.execute("SELECT to_regclass('config.domain_version') IS NOT NULL").fetchone()[0]
        has_pc = ok and connection.execute("SELECT count(*) FROM catalog.cpu_spec").fetchone()[0] > 0
        if not has_pc:
            pytest.skip("PC 카탈로그가 seed 되지 않았습니다 — db/setup_all.py로 준비하세요.")
        yield connection
    finally:
        connection.close()


def _answer_all_questions(conn, lid, principal, choice="unknown"):
    """대화가 묻는 필수 질문에 모두 답한다(기본은 "모르겠어요") — 사양 파일에 정보가 없으면 GPU 교체는 파워 용량을 묻는다."""
    from src.services import session_service as ss

    for _ in range(5):
        nq = ss.get_session_state(conn, lid, principal)["next_question"]
        if not nq:
            return
        ss.handle_answer(conn, lid, nq["id"], [choice], principal)


def _run_upgrade(conn, parts, spec_file=None, budget=800_000, purpose="game"):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service, session_service
    ss = session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "upgrade", principal)
    for field, value in (("purpose", purpose), ("budget_max", budget), ("priority", "value"), ("upgrade_parts", parts)):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    if spec_file:
        session_service.attach_spec_file(conn, list_uuid, "my-pc.txt", spec_file, principal)
    _answer_all_questions(conn, list_uuid, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    return recommendation_service.get_stored_result(conn, revision_id)


def test_end_to_end_upgrade_returns_only_the_chosen_parts(conn):
    result = _run_upgrade(conn, ["GPU"], "CPU: Ryzen 5 7600\nRAM: DDR5 16GB\n")
    assert [i["slot"] for i in result["items"]] == ["GPU"]
    assert result["items"][0]["price"] > 0


def test_end_to_end_two_parts_and_the_kept_platform_is_respected(conn):
    result = _run_upgrade(conn, ["CPU", "쿨러"], "메인보드: AM4 DDR4\n", budget=1_000_000)
    slots = {i["slot"]: i for i in result["items"]}
    assert set(slots) == {"CPU", "쿨러"}
    assert slots["CPU"]["product"]["name"].endswith(("5800X", "5800X3D"))   # AM4 CPU 만 카탈로그에 있다


def test_end_to_end_build_mode_is_unchanged(conn):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service, session_service

    created = session_service.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    list_uuid = uuid.UUID(created["list_id"])
    session_service.choose_category(conn, list_uuid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 1_500_000), ("priority", "value")):
        session_service.patch_slot(conn, list_uuid, field, value, principal)
    revision_id = PlanRepo(conn).get_current_revision(list_uuid)["id"]
    accepted = recommendation_service.start_recommendation(conn, revision_id, strategy="default")
    recommendation_service.execute_recommendation(revision_id, uuid.UUID(accepted["run_id"]))
    result = recommendation_service.get_stored_result(conn, revision_id)
    assert {i["slot"] for i in result["items"]} == set(ALL_SLOTS)

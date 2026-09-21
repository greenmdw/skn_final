"""업그레이드 대화 — 필요한 것만, 칩으로 되묻고, 답(과 교체하는 부품의 옛 모델)을 호환 검사에 쓴다.

회귀 배경: 업그레이드의 필수 입력은 upgrade_parts 하나뿐이고 현재 사양(current_specs)은 질문 없이 사양 파일로만
채워졌다. 파일을 안 올린 사람의 유지 부품은 전부 "확인 안 됨"이었다. 자유 텍스트 답은 문맥을 몰라 못 읽으므로(규칙
추출기는 예산·용도 등만 안다) 칩 질문으로 묻는다 — 사용자는 소켓을 모르니 "세대"·"종류"·"용량 구간"으로.
원칙: 필요한 부품을 고른 경우에만 묻고, 사양 파일에 이미 있으면 다시 묻지 않고, "모르겠어요"도 답이다."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.categories import load_category
from src.config import DATABASE_URL
from src.engine.owned_parts import constrain_targets, owned_for_conditions, upgrade_notes
from src.services import session_service as ss

CAT = load_category("computer")
SLOTS = CAT["slot_structure"]
BASE = {"category": "computer", "mode": "upgrade", "purpose": "game", "budget_max": 800_000, "priority": "value"}


def _v(**kw):
    return {**BASE, **kw}


def _asked(values):
    nq = ss._next_question(CAT, values)
    return nq["id"] if nq else None


# ── 언제 묻는가 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("parts, question", [
    (["CPU"], "q_owned_platform"), (["쿨러"], "q_owned_platform"), (["메인보드"], "q_owned_platform"),
    (["RAM"], "q_owned_ram"), (["GPU"], "q_owned_psu"),
])
def test_the_needed_question_is_asked_for_the_chosen_upgrade(parts, question):
    assert _asked(_v(upgrade_parts=parts)) == question


def test_board_upgrade_needs_both_the_cpu_generation_and_the_ram_type():
    values = _v(upgrade_parts=["메인보드"])
    assert set(ss.compute_missing(CAT, values)) == {"owned_platform", "owned_ram_type"}


@pytest.mark.parametrize("parts", [["저장장치"], ["케이스"], ["파워"]])
def test_upgrades_that_need_no_platform_information_ask_nothing_extra(parts):
    assert ss.compute_missing(CAT, _v(upgrade_parts=parts)) == []


def test_nothing_is_asked_before_the_upgrade_parts_are_chosen():
    assert ss.compute_missing(CAT, _v()) == ["upgrade_parts"]


def test_build_mode_never_asks_these_questions():
    values = _v(mode="build", upgrade_parts=["CPU", "GPU"])
    assert ss.compute_missing(CAT, values) == [] and _asked(values) is None


@pytest.mark.parametrize("parts, specs", [
    (["CPU"], {"CPU": "Ryzen 5 3600"}),            # 옛 CPU 로 플랫폼을 안다
    (["CPU"], {"메인보드": "MSI B450 Tomahawk"}),   # 유지하는 보드로 안다
    (["RAM"], {"RAM": "DDR4 16GB"}), (["GPU"], {"파워": "650W"}),
    (["CPU"], {"cpu": "Ryzen 5 3600"}),            # 키 별칭
])
def test_a_spec_file_that_already_has_the_information_suppresses_the_question(parts, specs):
    assert ss.compute_missing(CAT, _v(upgrade_parts=parts, current_specs=specs)) == []


def test_an_unrelated_spec_line_does_not_suppress_the_question():
    assert _asked(_v(upgrade_parts=["GPU"], current_specs={"CPU": "Ryzen 5 3600"})) == "q_owned_psu"


def test_answered_questions_are_not_asked_again_and_unknown_counts_as_an_answer():
    assert ss.compute_missing(CAT, _v(upgrade_parts=["GPU"], owned_psu_w=500)) == []
    assert ss.compute_missing(CAT, _v(upgrade_parts=["GPU"], owned_psu_w="unknown")) == []      # 추천이 막히지 않는다
    assert ss.compute_missing(CAT, _v(upgrade_parts=["메인보드"], owned_platform="AM4")) == ["owned_ram_type"]


def test_conditional_fields_appear_in_the_screen_list_only_when_relevant():
    def keys(values):
        return {f["key"] for f in ss._build_fields(CAT, values)}
    assert "owned_psu_w" in keys(_v(upgrade_parts=["GPU"]))
    assert not {"owned_platform", "owned_ram_type", "owned_psu_w"} & keys(_v(upgrade_parts=["저장장치"]))
    assert "owned_psu_w" in keys(_v(upgrade_parts=["저장장치"], owned_psu_w=500))            # 답이 있으면 보인다
    assert not {"owned_platform", "owned_ram_type", "owned_psu_w"} & keys(_v(mode="build"))


# ── 질문 정의의 정합성 ───────────────────────────────────────────────────────

CONDITIONAL = [q for q in CAT["question_sets"] if q.get("ask_when")]


def test_category_definitions_serialise_the_way_the_seed_does():
    # db/seed.py 는 카테고리 정의를 JSON(sort_keys)으로 저장한다. 키 타입이 섞이면(예: display 의 450 과 unknown)
    # TypeError 로 시드가 죽어 새 DB 를 준비할 수 없다 — 실제로 한 번 그랬다.
    import json

    for category in ("computer",):
        json.dumps(load_category(category), sort_keys=True, ensure_ascii=False)


def test_the_three_conditional_questions_exist():
    assert {q["maps_to"] for q in CONDITIONAL} == {"owned_platform", "owned_ram_type", "owned_psu_w"}


@pytest.mark.parametrize("q", CONDITIONAL, ids=lambda q: q["id"])
def test_every_conditional_question_is_well_formed(q):
    assert q["select"] == "single" and q["mode_only"] == "upgrade"
    assert len(q["options"]) == len(q["values"]) == len(q["options_en"])
    assert q["values"][-1] == "unknown" and q["options"][-1] == "모르겠어요" and q["options_en"][-1] == "Not sure"
    assert q["maps_to"] in CAT["slot_schema"] and q["label_en"]
    assert set(q["values"]) == set(CAT["slot_schema"][q["maps_to"]]["values"])            # 스키마와 일치
    assert q["maps_to"] in {f["key"] for f in CAT["fields"]}
    assert set(q["ask_when"]["upgrade_parts_any"]) <= set(SLOTS)
    assert set(q["ask_when"]["unless_current_specs_any"]) <= set(SLOTS)


def test_answers_round_trip_to_their_typed_values():
    q = next(q for q in CAT["question_sets"] if q["id"] == "q_owned_psu")
    assert ss._canonicalize_answer_values(q, ["500"]) == ["500"]                  # data-* 로 와도 YAML 의 값으로 정규화
    assert ss._canonicalize_answer_values(q, ["모르겠어요"]) == ["unknown"]
    assert ss._canonicalize_answer_values(q, ["Not sure"]) == ["unknown"]


def test_english_users_get_english_question_text():
    nq = ss._next_question(CAT, {**_v(upgrade_parts=["GPU"]), "language": "en"})
    assert nq["id"] == "q_owned_psu" and "power supply" in nq["text"]
    assert [o["label"] for o in nq["options"]][-1] == "Not sure"


# ── 답이 엔진에 어떻게 쓰이는가 ───────────────────────────────────────────────

def _owned(parts, **kw):
    return owned_for_conditions(_v(upgrade_parts=parts, **kw), {}, parts, SLOTS)


def test_cpu_generation_answer_fills_the_socket_of_the_kept_board_and_cpu():
    owned = _owned(["쿨러"], owned_platform="AM4")
    assert owned["CPU"]["specs"]["socket"] == "AM4" and owned["메인보드"]["specs"]["socket"] == "AM4"
    assert owned["CPU"]["source"] == "answer" and "inferred" not in owned["CPU"]         # 사용자가 알려 준 확정값


def test_unknown_answers_fill_nothing():
    assert _owned(["CPU"], owned_platform="unknown", owned_ram_type="unknown", owned_psu_w="unknown") == {}


def test_the_replaced_cpus_old_model_reveals_the_kept_boards_socket():
    # 새 CPU 를 사려는 사람의 옛 CPU(Ryzen 5 3600 = AM4)가 곧 유지하는 보드의 소켓이다.
    owned = _owned(["CPU"], current_specs={"CPU": "Ryzen 5 3600"})
    board = owned["메인보드"]
    assert board["specs"]["socket"] == "AM4" and board["source"] == "inferred" and board["inferred"] == ["socket"]
    assert board["basis"] == {"kind": "replaced", "slot": "CPU", "model": "Ryzen 5 3600"}
    assert "CPU" not in owned                                                        # 교체 대상이라 유지 부품이 아니다


def test_the_replaced_boards_chipset_reveals_the_kept_cpus_socket():
    owned = _owned(["메인보드"], current_specs={"메인보드": "MSI B450 Tomahawk"})
    assert owned["CPU"]["specs"]["socket"] == "AM4" and owned["CPU"]["basis"]["slot"] == "메인보드"


def test_answer_beats_inference_and_explicit_text_is_never_overwritten():
    owned = _owned(["CPU"], owned_platform="LGA1700", current_specs={"CPU": "Ryzen 5 3600", "메인보드": "AM4 보드"})
    assert owned["메인보드"]["specs"]["socket"] == "AM4"                             # 글에 적힌 값이 우선
    owned = _owned(["CPU"], owned_platform="LGA1700", current_specs={"CPU": "Ryzen 5 3600"})
    assert owned["메인보드"]["specs"]["socket"] == "LGA1700"                         # 답이 추정보다 우선


def test_ram_type_answer_fills_both_ram_and_board_and_the_psu_bucket_becomes_a_wattage():
    owned = _owned(["CPU"], owned_ram_type="DDR4", owned_psu_w=500)
    assert owned["RAM"]["specs"]["mem_type"] == "DDR4" and owned["메인보드"]["specs"]["mem_type"] == "DDR4"
    assert owned["파워"]["specs"]["wattage_w"] == 500


def test_targets_are_never_treated_as_kept_parts():
    owned = _owned(["CPU", "메인보드"], owned_platform="AM4", owned_ram_type="DDR4")
    assert "CPU" not in owned and "메인보드" not in owned and "RAM" in owned


def test_the_answer_constrains_the_new_cpu_platform_like_a_spec_file_would():
    from src.dto import Slots
    from src.engine import stage2_requirement

    spec = stage2_requirement.run(Slots(category="computer", mode="upgrade", objective_text="",
                                        values=_v(upgrade_parts=["CPU"])), {}, lambda _: None)
    spec.owned = _owned(["CPU"], owned_platform="AM4")
    constrain_targets(spec)
    assert spec.targets["CPU"]["socket_in"] == ["AM4"]


def test_conditions_from_a_build_session_never_produce_kept_parts():
    assert owned_for_conditions({**BASE, "mode": "build", "owned_platform": "AM4"}, {}, ["CPU"], SLOTS) == {}


# ── 안내 문장: 근거를 밝힌다 ──────────────────────────────────────────────────

def test_notes_disclose_that_the_board_socket_was_deduced_from_the_old_cpu():
    notes = upgrade_notes(["CPU"], _owned(["CPU"], current_specs={"CPU": "Ryzen 5 3600"}))
    assert notes == ["현재 메인보드의 소켓은 교체하는 CPU(Ryzen 5 3600)의 모델명으로 보아 AM4일 것으로 추정했어요 — 구매 전 확인하세요."]


def test_answers_from_the_user_produce_no_caveat_and_english_has_no_korean():
    assert upgrade_notes(["CPU"], _owned(["CPU"], owned_platform="AM4")) == []
    en = upgrade_notes(["CPU"], _owned(["CPU"], current_specs={"CPU": "Ryzen 5 3600"}), "en")
    assert en and not any("가" <= ch <= "힣" for n in en for ch in n)
    assert "model name of the CPU you are replacing (Ryzen 5 3600)" in en[0]


# ── 종단: 세션 -> 칩 답변 -> 추천 -> 결과 (로컬 PostgreSQL + PC 카탈로그 seed 필요) ─────────

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


def _session(conn, parts, spec_file=None, budget=1_000_000):
    created = ss.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    lid = uuid.UUID(created["list_id"])
    ss.choose_category(conn, lid, "computer", "upgrade", principal)
    for field, value in (("purpose", "game"), ("budget_max", budget), ("priority", "value"), ("upgrade_parts", parts)):
        ss.patch_slot(conn, lid, field, value, principal)
    if spec_file:
        ss.attach_spec_file(conn, lid, "my-pc.txt", spec_file, principal)
    return lid, principal


def _run(conn, lid):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service as rs

    rev = PlanRepo(conn).get_current_revision(lid)["id"]
    acc = rs.start_recommendation(conn, rev, strategy="default")
    rs.execute_recommendation(rev, uuid.UUID(acc["run_id"]))
    return rs.get_stored_result(conn, rev)


def _socket(conn, name):
    row = conn.execute("SELECT s.socket FROM catalog.product p JOIN catalog.cpu_spec s ON s.product_id = p.id "
                       "WHERE p.name = %s", (name,)).fetchone()
    return row[0] if row else None


def test_end_to_end_chip_answer_drives_the_recommendation(conn):
    lid, principal = _session(conn, ["CPU"])
    state = ss.get_session_state(conn, lid, principal)
    assert state["next_question"]["id"] == "q_owned_platform" and state["can_recommend"] is False
    labels = [o["label"] for o in state["next_question"]["options"]]
    assert "Ryzen 1000~5000" in labels and labels[-1] == "모르겠어요"

    state = ss.handle_answer(conn, lid, "q_owned_platform", ["AM4"], principal)
    assert state["can_recommend"] is True and state["next_question"] is None
    result = _run(conn, lid)
    cpu = next(i for i in result["items"] if i["slot"] == "CPU")
    assert _socket(conn, cpu["product"]["name"]) == "AM4"                              # 답에 맞는 소켓의 CPU


def test_end_to_end_unknown_answer_still_lets_the_user_proceed_with_a_notice(conn):
    lid, principal = _session(conn, ["GPU"])
    state = ss.handle_answer(conn, lid, "q_owned_psu", ["모르겠어요"], principal)
    assert state["can_recommend"] is True
    text = (_run(conn, lid).get("explanation") or {}).get("text") or ""
    assert "GPU만 포함" in text and "현재 파워 정보가 없어" in text                       # 모른다고 했으니 안내로 남는다


def test_end_to_end_old_cpu_model_in_the_spec_file_skips_the_question_and_picks_the_right_socket(conn):
    lid, principal = _session(conn, ["CPU"], "CPU: Ryzen 5 3600\n")
    state = ss.get_session_state(conn, lid, principal)
    assert state["next_question"] is None and state["can_recommend"] is True
    result = _run(conn, lid)
    cpu = next(i for i in result["items"] if i["slot"] == "CPU")
    assert _socket(conn, cpu["product"]["name"]) == "AM4"
    assert "교체하는 CPU(Ryzen 5 3600)의 모델명으로 보아" in (result["explanation"]["text"] or "")


def test_end_to_end_build_flow_is_untouched(conn):
    created = ss.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    lid = uuid.UUID(created["list_id"])
    ss.choose_category(conn, lid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 1_500_000), ("priority", "value")):
        ss.patch_slot(conn, lid, field, value, principal)
    state = ss.get_session_state(conn, lid, principal)
    assert state["can_recommend"] is True and state["next_question"] is None

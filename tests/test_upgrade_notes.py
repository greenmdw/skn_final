"""업그레이드 결과 안내 — 코드가 만드는 결정적 문장(LLM 아님)과, LLM 입력에 업그레이드 정보 싣기.

회귀 배경: 유지 부품 정보가 부족해도 화면에는 어느 부품을 몰라서인지 안 나왔고("확인 필요" 감점만),
추천 이유 문장(LLM)은 입력에 upgrade_parts·current_specs 가 없어 새 컴퓨터 한 대처럼 쓸 수 있었다.
원칙: 무엇을 못 읽었는지는 코드가 아는 사실이라 코드가 적는다(판정은 코드, 설명은 AI)."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.engine.owned_parts import UPGRADE_NEEDS, upgrade_notes, upgrade_scope_note
from src.engine import stage5_explain


def _owned(**parts):
    return {slot: dict(info) for slot, info in parts.items()}


CPU_CONFIRMED = {"name": "AMD Ryzen 5 7600", "specs": {"socket": "AM5"}, "source": "catalog"}


# ── 범위 문장 ────────────────────────────────────────────────────────────────

def test_scope_note_lists_the_upgraded_parts_and_says_the_rest_stays():
    ko = upgrade_scope_note(["GPU", "파워"])
    assert "GPU, 파워만 포함" in ko and "그대로 쓰는 것" in ko
    assert upgrade_scope_note([]) == ""


# ── 미확인 안내 ──────────────────────────────────────────────────────────────

def test_no_information_at_all_names_exactly_what_was_not_checked():
    notes = upgrade_notes(["CPU"], {})
    assert notes == ["현재 메인보드 정보가 없어 소켓 호환은 확인하지 못했어요."]


def test_something_written_but_unreadable_says_so():
    notes = upgrade_notes(["CPU"], _owned(메인보드={"name": "그냥 보드", "specs": {}, "source": "unverified"}))
    assert notes == ["현재 메인보드(그냥 보드)의 소켓을 확인하지 못했어요 — 호환은 직접 확인이 필요해요."]


def test_inferred_values_are_disclosed_as_guesses():
    board = {"name": "MSI B450 Tomahawk", "specs": {"socket": "AM4", "mem_type": "DDR4"}, "source": "inferred",
             "inferred": ["socket", "mem_type"]}
    notes = upgrade_notes(["CPU"], _owned(메인보드=board))
    assert notes == ["현재 메인보드(MSI B450 Tomahawk)의 소켓은 모델명으로 보아 AM4일 것으로 추정했어요 — 구매 전 제조사 표기를 확인하세요."]


def test_confirmed_information_produces_no_note():
    board = {"name": "AM4 DDR4", "specs": {"socket": "AM4"}, "source": "text"}
    assert upgrade_notes(["CPU"], _owned(메인보드=board)) == []
    assert upgrade_notes(["GPU"], _owned(파워={"name": "650W", "specs": {"wattage_w": 650}, "source": "text"},
                                        케이스={"name": "c", "specs": {"max_gpu_len_mm": 330}, "source": "catalog"})) == []


def test_parts_being_upgraded_are_never_reported_as_unknown():
    # CPU 와 메인보드를 함께 바꾸면 서로의 소켓은 견적 안에서 맞춰지므로 알림이 필요 없다.
    notes = upgrade_notes(["CPU", "메인보드"], {})
    assert not any("현재 CPU" in n or "현재 메인보드" in n for n in notes)
    assert any("RAM" in n for n in notes)                       # 메인보드 교체는 유지하는 RAM 종류가 필요하다


def test_the_same_missing_fact_is_reported_once_even_if_two_upgrades_need_it():
    notes = upgrade_notes(["CPU", "쿨러"], {})                   # 둘 다 유지하는 것의 소켓이 필요 — 쿨러 쪽은 CPU 소켓
    assert len(notes) == len(set(notes))


@pytest.mark.parametrize("aspect, expected", [("소켓", "소켓을"), ("메모리 종류", "메모리 종류를"), ("정격 용량", "정격 용량을"),
                                              ("쿨러 높이 여유", "쿨러 높이 여유를"), ("권장 파워", "권장 파워를")])
def test_korean_object_particle_follows_the_final_consonant(aspect, expected):
    from src.engine.owned_parts import _josa

    assert _josa(aspect, "을", "를") == expected


def test_every_upgrade_type_has_a_defined_set_of_needs():
    assert set(UPGRADE_NEEDS) == {"CPU", "메인보드", "RAM", "GPU", "파워", "쿨러", "케이스"}       # 저장장치는 호환 정보 불필요


# ── [5] 입력 라벨(LLM 이 보는 사용자 조건) ───────────────────────────────────────

def test_llm_input_tells_the_model_it_is_an_upgrade_and_which_parts():
    lines = stage5_explain._conditions_lines({
        "mode": "upgrade", "purpose": "game", "upgrade_parts": ["GPU", "파워"],
        "current_specs": {"CPU": "Ryzen 5 3600", "RAM": "DDR4 16GB"}})
    text = " ".join(lines)
    assert "구성 방식 업그레이드" in text
    assert "업그레이드 부품 GPU, 파워" in text
    assert "현재 사양 CPU Ryzen 5 3600, RAM DDR4 16GB" in text
    assert "[" not in text and "{" not in text                   # 파이썬 repr 이 그대로 새지 않는다


def test_build_mode_input_is_unchanged_apart_from_readable_mode_label():
    text = " ".join(stage5_explain._conditions_lines({"mode": "build", "purpose": "game", "priority": "value"}))
    assert "구성 방식 새로 조립" in text and "업그레이드 부품" not in text


# ── 종단: 결과 요약에 실제로 실린다 (로컬 PostgreSQL + PC 카탈로그 seed 필요) ───────────────

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


def _upgrade(conn, parts, spec_file):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service as rs, session_service as ss

    created = ss.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    lid = uuid.UUID(created["list_id"])
    ss.choose_category(conn, lid, "computer", "upgrade", principal)
    for field, value in (("purpose", "game"), ("budget_max", 800_000), ("priority", "value"), ("upgrade_parts", parts)):
        ss.patch_slot(conn, lid, field, value, principal)
    if spec_file:
        ss.attach_spec_file(conn, lid, "my-pc.txt", spec_file, principal)
    for _ in range(5):                                  # 대화가 묻는 필수 질문(예: GPU 교체의 파워 용량)에 "모르겠어요"로 답한다
        nq = ss.get_session_state(conn, lid, principal)["next_question"]
        if not nq:
            break
        ss.handle_answer(conn, lid, nq["id"], ["unknown"], principal)
    rev = PlanRepo(conn).get_current_revision(lid)["id"]
    acc = rs.start_recommendation(conn, rev, strategy="default")
    rs.execute_recommendation(rev, uuid.UUID(acc["run_id"]))
    return rs.get_stored_result(conn, rev)


def _summary(result):
    return (result.get("explanation") or {}).get("text") or ""


def test_end_to_end_summary_says_what_is_included_and_what_could_not_be_checked(conn):
    text = _summary(_upgrade(conn, ["GPU"], "CPU: Ryzen 5 7600\n"))
    assert "GPU만 포함" in text                               # 범위
    assert "현재 파워 정보가 없어 정격 용량 호환은 확인하지 못했어요" in text     # 유지 파워를 몰라서
    assert "확인이 필요한 것" in text


def test_end_to_end_a_confirmed_kept_part_is_not_listed_as_unknown(conn):
    text = _summary(_upgrade(conn, ["CPU"], "메인보드: AM4 DDR4\n"))
    assert "CPU만 포함" in text and "현재 메인보드 정보가 없어" not in text


def test_end_to_end_build_mode_summary_has_no_upgrade_wording(conn):
    from src.repo.plan_repo import PlanRepo
    from src.services import recommendation_service as rs, session_service as ss

    created = ss.create_session(conn, Principal(user_id=None, browser_token=None))
    principal = Principal(user_id=None, browser_token=created["browser_token"])
    lid = uuid.UUID(created["list_id"])
    ss.choose_category(conn, lid, "computer", "build", principal)
    for field, value in (("purpose", "game"), ("budget_max", 1_500_000), ("priority", "value")):
        ss.patch_slot(conn, lid, field, value, principal)
    rev = PlanRepo(conn).get_current_revision(lid)["id"]
    acc = rs.start_recommendation(conn, rev, strategy="default")
    rs.execute_recommendation(rev, uuid.UUID(acc["run_id"]))
    assert "만 포함해요" not in _summary(rs.get_stored_result(conn, rev))

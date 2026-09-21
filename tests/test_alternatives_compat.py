"""결과 화면의 "다른 후보"에서 확정 비호환 후보를 뺀다 + 메인보드 크기 규칙을 위계로 판정한다.

회귀 배경: (1) list_alternatives 가 슬롯의 모든 변형을 가격순으로 내보내서, 신규 조립 결과의 CPU 대안 39개 중
23개가 메인보드 소켓과 안 맞았고 가장 싼 후보(LGA1700 i3)가 목록 맨 위에 나왔다. 그중 하나로 교체해도
오류·경고가 없었다. (2) 이 필터를 검증하다 발견: 엔진의 보드-케이스 규칙이 정확 일치(`not in`)라서 "ATX" 케이스
23개가 mATX 보드 22개와 "비호환"으로 판정됐다 — ATX 케이스는 mATX·ITX 보드도 수용한다."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from src.auth.deps import Principal
from src.config import DATABASE_URL
from src.dto import Candidate
from src.engine.stage2_requirement import load_computer_rules
from src.engine.stage4_optimize import _form_fits, _form_rank, _pc_known_failures
from src.services import recommendation_service as rs


def cand(slot, key, variant, **specs) -> Candidate:
    return Candidate(slot=slot, product_key=key, name=key, price=1, variant_id=variant, specs=specs)


# ── 메인보드 크기 위계 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text, rank", [("ITX", 1), ("Mini-ITX", 1), ("mATX", 2), ("Micro-ATX", 2), ("M-ATX", 2),
                                        ("ATX", 3), ("E-ATX", 4), ("Extended ATX", 4), ("SFX", None), ("", None)])
def test_form_factor_names_are_normalised_to_a_size_rank(text, rank):
    assert _form_rank(text) == rank


@pytest.mark.parametrize("board, case, fits", [
    ("mATX", ["E-ATX", "ATX"], True),            # 예전엔 False — 이게 버그의 핵심
    ("mATX", ["ATX"], True),
    ("Mini-ITX", ["ATX"], True),
    ("ATX", ["ATX", "mATX"], True),
    ("ATX", ["mATX"], False),
    ("E-ATX", ["ATX"], False),
    ("ATX", ["Mini-ITX"], False),
    ("mATX", ["Mini-ITX", "mATX"], True),
    ("mATX", "E-ATX / ATX", True),               # 문자열 표기도 읽는다
    ("mATX", ["알 수 없음"], None),                # 못 읽으면 판정 보류
])
def test_a_board_fits_any_case_that_lists_its_size_or_larger(board, case, fits):
    assert _form_fits(board, case) is fits


def test_known_failures_uses_the_hierarchy_not_exact_match():
    rules = load_computer_rules()["verification"]
    from src.dto import RequirementSpec
    spec = RequirementSpec(list_id="x", category="computer", mode="build")
    ok = {"메인보드": cand("메인보드", "b", "v1", form_factor="mATX"),
          "케이스": cand("케이스", "c", "v2", supports_form_factors=["E-ATX", "ATX"])}
    assert "motherboard_case" not in _pc_known_failures(ok, spec, rules)
    bad = {"메인보드": cand("메인보드", "b", "v1", form_factor="ATX"),
           "케이스": cand("케이스", "c", "v2", supports_form_factors=["mATX"])}
    assert "motherboard_case" in _pc_known_failures(bad, spec, rules)


def test_loader_splits_case_support_on_both_slash_and_comma():
    from src.repo.catalog_repo import _specs_from_row

    assert _specs_from_row("case", {"supported_motherboard": "E-ATX, ATX / mATX"})["supports_form_factors"] == [
        "E-ATX", "ATX", "mATX"]


# ── 대안 목록 필터 (DB 없이: 후보 풀을 대신 넣어 검증) ─────────────────────────

@pytest.fixture
def pool(monkeypatch):
    cpus = [cand("CPU", "am5_a", "c-am5-a", socket="AM5"), cand("CPU", "am5_b", "c-am5-b", socket="AM5"),
            cand("CPU", "lga", "c-lga", socket="LGA1700"), cand("CPU", "am4", "c-am4", socket="AM4"),
            cand("CPU", "nosock", "c-none")]
    boards = [cand("메인보드", "board_am5", "b-am5", socket="AM5", mem_type="DDR5"),
              cand("메인보드", "board_am4", "b-am4", socket="AM4", mem_type="DDR4")]
    data = {"CPU": cpus, "메인보드": boards}
    monkeypatch.setattr("src.repo.catalog_repo.load_candidates_by_slot_from_db", lambda conn: data)
    return data


def _row(slot, variant, **extra):
    return {"slot": slot, "variant_id": variant, "selected": True, **extra}


def _variants(*ids):
    return [{"variant_id": v} for v in ids]


CVALS = {"category": "computer", "mode": "build"}


def _names(rows):
    return [r["variant_id"] for r in rows]


def test_incompatible_candidates_are_removed_and_compatible_ones_kept(pool):
    stored = [_row("CPU", "c-am5-a"), _row("메인보드", "b-am5")]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-am5-b", "c-lga", "c-am4"), CVALS)
    assert _names(kept) == ["c-am5-b"]


def test_candidates_without_enough_information_are_kept_not_declared_incompatible(pool):
    stored = [_row("CPU", "c-am5-a"), _row("메인보드", "b-am5")]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-none", "not-in-catalog"), CVALS)
    assert _names(kept) == ["c-none", "not-in-catalog"]


def test_only_newly_introduced_incompatibility_counts(pool):
    # 현재 구성에 이미 소켓 불일치가 있다(CPU LGA1700 + 보드 AM5). 같은 문제를 가진 대안은 후보 탓이 아니다.
    stored = [_row("CPU", "c-lga"), _row("메인보드", "b-am5")]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-lga", "c-am5-a", "c-am4"), CVALS)
    # 소켓 불일치는 후보가 만든 문제가 아니다 — 바로잡는 후보(c-am5-a)뿐 아니라 같은 문제를 가진 후보도
    # 이 필터에서는 새로 생기는 비호환이 아니므로 남긴다.
    assert set(_names(kept)) == {"c-lga", "c-am5-a", "c-am4"}


def test_deselected_parts_do_not_constrain_the_alternatives(pool):
    stored = [_row("CPU", "c-am5-a"), {**_row("메인보드", "b-am5"), "selected": False}]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-lga", "c-am4"), CVALS)
    assert _names(kept) == ["c-lga", "c-am4"]


def test_baby_and_other_categories_are_untouched(pool):
    stored = [_row("CPU", "c-am5-a"), _row("메인보드", "b-am5")]
    variants = _variants("c-lga")
    assert rs._drop_incompatible_alternatives(None, stored, stored[0], variants, {"category": "baby"}) == variants


def test_upgrade_uses_the_kept_parts_the_user_described(pool):
    # 견적 대상은 CPU 뿐이고, 유지하는 메인보드는 AM4 DDR4 라고 적었다.
    cvals = {"category": "computer", "mode": "upgrade", "upgrade_parts": ["CPU"],
             "current_specs": {"메인보드": "AM4 DDR4"}}
    stored = [_row("CPU", "c-am4")]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-am5-a", "c-lga", "c-am4"), cvals)
    assert _names(kept) == ["c-am4"]


def test_upgrade_without_kept_part_information_does_not_filter_by_platform(pool):
    cvals = {"category": "computer", "mode": "upgrade", "upgrade_parts": ["CPU"], "current_specs": {}}
    stored = [_row("CPU", "c-am4")]
    kept = rs._drop_incompatible_alternatives(None, stored, stored[0], _variants("c-am5-a", "c-lga"), cvals)
    assert _names(kept) == ["c-am5-a", "c-lga"]


# ── 종단: 실제 추천 결과의 대안 (로컬 PostgreSQL + PC 카탈로그 seed 필요) ───────────────

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


def _recommend(conn):
    from src.repo.plan_repo import PlanRepo
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
    return revision_id, rs.get_stored_result(conn, revision_id)


def _socket(conn, product_type, name):
    row = conn.execute(
        f"SELECT s.socket FROM catalog.product p JOIN catalog.{'cpu_spec' if product_type == 'cpu' else 'mainboard_spec'} s "
        "ON s.product_id = p.id WHERE p.name = %s", (name,)).fetchone()
    return row[0] if row else None


def test_end_to_end_cpu_alternatives_all_fit_the_chosen_board(conn):
    revision_id, result = _recommend(conn)
    items = {i["slot"]: i for i in result["items"]}
    board_socket = _socket(conn, "motherboard", items["메인보드"]["product"]["name"])
    alts = rs.list_alternatives(conn, revision_id, uuid.UUID(items["CPU"]["item_id"]))["items"]
    assert alts, "호환되는 대안이 하나도 없으면 안 된다"
    assert {_socket(conn, "cpu", a["product"]["name"]) for a in alts} == {board_socket}


def test_end_to_end_board_alternatives_all_fit_the_chosen_cpu(conn):
    revision_id, result = _recommend(conn)
    items = {i["slot"]: i for i in result["items"]}
    cpu_socket = _socket(conn, "cpu", items["CPU"]["product"]["name"])
    alts = rs.list_alternatives(conn, revision_id, uuid.UUID(items["메인보드"]["item_id"]))["items"]
    assert alts and {_socket(conn, "motherboard", a["product"]["name"]) for a in alts} == {cpu_socket}

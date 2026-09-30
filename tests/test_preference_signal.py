"""docs/사용자_선호비선호_기록_설계.md 구현 검증.

1. swap_item/patch_item이 (from/to)_variant_id·slot을 payload에 담고 user_id를 채우는지
   (실 HTTP 스왑, 파이프라인 B의 입력 데이터).
2. PreferenceRepo(신호 저장·조회·거부).
3. preference_signal_batch.run()이 반복 패턴을 탐지해 신호를 쌓는지.
4. 회원 탈퇴 시 신호가 같이 지워지는지.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="set DATABASE_URL to a disposable migrated database",
)

if DSN:
    os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local-test")
    from fastapi.testclient import TestClient

    from src.api import app
    from src.repo.preference_repo import PreferenceRepo
    from src.repo.user_repo import UserRepo
    from src.workers import preference_signal_batch

    @pytest.fixture()
    def client():
        with TestClient(app) as c:
            yield c

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def _create(c) -> str:
    r = c.post("/session")
    assert r.status_code == 200, r.text
    return r.json()["list_id"]


def _choose_computer(c, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/category", json={"category": "computer", "mode": "build"})
    assert r.status_code == 200, r.text
    return r.json()


def _answer(c, list_id: str, qid: str, selected: list) -> dict:
    r = c.post(f"/session/{list_id}/answer", json={"question_id": qid, "selected": selected})
    assert r.status_code == 200, r.text
    return r.json()


def _fill_computer_conditions(c, list_id: str, *, budget: int = 5_000_000) -> dict:
    state = _answer(c, list_id, "q_purpose", ["게임"])
    state = _answer(c, list_id, "q_budget_max", [budget])
    state = _answer(c, list_id, "q_priority", ["성능 우선"])
    assert state["can_recommend"] is True, state
    return state


def _recommend_and_wait(c, list_id: str) -> dict:
    r = c.post(f"/session/{list_id}/recommend")
    assert r.status_code == 202, r.text
    r = c.get(f"/session/{list_id}/result")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done", data
    return data


def _current_user_id(conn, email: str):
    row = conn.execute("SELECT id FROM identity.app_user WHERE email_normalized=%s", (email,)).fetchone()
    return row[0]


def _make_user(conn, label: str):
    now = datetime.now(timezone.utc)
    row = UserRepo(conn).create_local_user(
        email_normalized=f"pref-{label}-{uuid4().hex[:12]}@example.test",
        password_hash="x", display_name=label,
        terms_version="v1", terms_agreed_at=now, privacy_agreed_at=now, marketing_agreed_at=None,
    )
    return row["id"]


# ── 1. swap/removed 이벤트에 근거 데이터(payload)와 user_id가 실리는지 ──────────
def test_swap_payload_carries_from_to_variant_and_slot(raw_conn):
    email = f"pref-swap-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "SwapTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    user_id = _current_user_id(raw_conn, email.lower())

    list_id = _create(c)
    _choose_computer(c, list_id)
    state = _fill_computer_conditions(c, list_id)
    revision_id = state["revision_id"]
    data = _recommend_and_wait(c, list_id)
    item = next(it for it in data["items"] if it["alternatives_count"] > 0)

    r = c.get(f"/session/{list_id}/items/{item['item_id']}/alternatives")
    assert r.status_code == 200, r.text
    alt = r.json()["items"][0]

    r = c.post(f"/session/{list_id}/items/{item['item_id']}/swap",
               json={"candidate_id": alt["candidate_id"]})
    assert r.status_code == 200, r.text

    row = raw_conn.execute(
        "SELECT payload, user_id FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type='item_replaced' ORDER BY created_at DESC LIMIT 1",
        (revision_id,),
    ).fetchone()
    payload, event_user_id = row
    assert payload["from_variant_id"], payload
    assert payload["to_variant_id"] == alt["candidate_id"], payload
    assert payload["slot"], payload
    assert str(event_user_id) == str(user_id)


def test_removed_payload_carries_variant_and_slot(raw_conn):
    email = f"pref-rm-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "RemoveTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    user_id = _current_user_id(raw_conn, email.lower())

    list_id = _create(c)
    _choose_computer(c, list_id)
    state = _fill_computer_conditions(c, list_id)
    revision_id = state["revision_id"]
    data = _recommend_and_wait(c, list_id)
    item_id = data["items"][0]["item_id"]

    r = c.patch(f"/session/{list_id}/items/{item_id}", json={"selected": False})
    assert r.status_code == 200, r.text

    row = raw_conn.execute(
        "SELECT payload, user_id FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type='item_removed' LIMIT 1",
        (revision_id,),
    ).fetchone()
    payload, event_user_id = row
    assert payload["removed_variant_id"]
    assert payload["slot"]
    assert str(event_user_id) == str(user_id)


# ── 2. PreferenceRepo ───────────────────────────────────────────────────────
def test_preference_repo_upsert_accumulates_confidence_and_reactivates_dismissed(raw_conn):
    repo = PreferenceRepo(raw_conn)
    user_id = _make_user(raw_conn, "repo")

    first = repo.upsert_signal(user_id=user_id, dimension="brand", slot="GPU", value="AMD",
                               direction="prefer", source="inferred_swap", confidence_delta=3)
    assert first["confidence"] == 3
    assert first["status"] == "active"

    second = repo.upsert_signal(user_id=user_id, dimension="brand", slot="GPU", value="AMD",
                                direction="prefer", source="inferred_swap", confidence_delta=2)
    assert second["confidence"] == 5, "confidence must accumulate across upserts"

    active = repo.list_active(user_id, dimension="brand")
    assert len(active) == 1 and active[0]["value"] == "AMD"

    repo.dismiss(user_id, first["id"])
    assert repo.list_active(user_id) == []

    reactivated = repo.upsert_signal(user_id=user_id, dimension="brand", slot="GPU", value="AMD",
                                     direction="prefer", source="inferred_swap", confidence_delta=1)
    assert reactivated["status"] == "active", "a repeated observation must reactivate a dismissed signal"


def test_opposite_observations_net_out_instead_of_flipping_and_summing(raw_conn):
    """유일 키에 direction 이 없다 — 예전엔 방향을 덮고 횟수를 더해 Intel 선호 2 + 비선호 1 이 "비선호 3"(문턱)이 됐다."""
    repo = PreferenceRepo(raw_conn)
    user_id = _make_user(raw_conn, "net")
    key = dict(user_id=user_id, dimension="brand", slot="CPU", value="Intel", source="inferred_swap")
    repo.upsert_signal(direction="prefer", confidence_delta=2, **key)
    row = repo.upsert_signal(direction="avoid", confidence_delta=1, **key)
    assert (row["direction"], row["confidence"]) == ("prefer", 1)
    row = repo.upsert_signal(direction="avoid", confidence_delta=3, **key)
    assert (row["direction"], row["confidence"]) == ("avoid", 2)
    assert repo.list_active(user_id, min_confidence=preference_signal_batch.REPEAT_THRESHOLD) == []


def test_explicit_statement_is_not_overwritten_by_inference_but_by_a_new_statement(raw_conn):
    """예전엔 추론 한 번이 source 를 inferred_swap 으로 덮어, 문턱 우회를 잃고 되묻기가 사라졌다."""
    repo = PreferenceRepo(raw_conn)
    user_id = _make_user(raw_conn, "explicit-keep")
    key = dict(user_id=user_id, dimension="brand", slot="CPU", value="AMD")
    repo.upsert_signal(direction="prefer", source="explicit_chat", **key)
    row = repo.upsert_signal(direction="avoid", source="inferred_swap", confidence_delta=5, **key)
    assert (row["source"], row["direction"], row["confidence"]) == ("explicit_chat", "prefer", 1)
    assert len(repo.list_active(user_id, min_confidence=preference_signal_batch.REPEAT_THRESHOLD)) == 1

    row = repo.upsert_signal(direction="prefer", source="explicit_chat", **key)       # 같은 말을 또 하면 더한다
    assert (row["direction"], row["confidence"]) == ("prefer", 2)
    row = repo.upsert_signal(direction="avoid", source="explicit_chat", **key)        # 말을 바꾸면 그 말이 이긴다
    assert (row["source"], row["direction"], row["confidence"]) == ("explicit_chat", "avoid", 1)


# ── 3. 배치 탐지 ─────────────────────────────────────────────────────────────
def _two_variants_of_different_brands(conn, product_type: str) -> tuple[dict, dict]:
    rows = conn.execute(
        "SELECT v.id AS variant_id, p.brand FROM catalog.product_variant v "
        "JOIN catalog.product p ON p.id = v.product_id "
        "WHERE p.product_type=%s ORDER BY p.brand LIMIT 50",
        (product_type,),
    ).fetchall()
    by_brand: dict[str, list] = {}
    for variant_id, brand in rows:
        by_brand.setdefault(brand, []).append(variant_id)
    brands = list(by_brand)
    assert len(brands) >= 2, f"seed data needs >=2 brands for product_type={product_type}"
    return {"brand": brands[0], "variant_id": by_brand[brands[0]][0]}, \
           {"brand": brands[1], "variant_id": by_brand[brands[1]][0]}


def _make_plan_revision(conn) -> dict:
    row = conn.execute(
        "INSERT INTO identity.conversation(guest_session_hash) VALUES (%s) RETURNING id",
        (f"pref-batch-{uuid4()}",),
    ).fetchone()
    plan_id = conn.execute(
        "INSERT INTO planning.plan(conversation_id,name) VALUES (%s,%s) RETURNING id",
        (row[0], "pref batch test plan"),
    ).fetchone()[0]
    domain_version_id = conn.execute(
        "SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id "
        "WHERE d.code='computer' ORDER BY dv.version_no DESC LIMIT 1"
    ).fetchone()[0]
    revision_id = conn.execute(
        "INSERT INTO planning.plan_revision(plan_id,revision_no,domain_version_id,name_snapshot) "
        "VALUES (%s,1,%s,%s) RETURNING id",
        (plan_id, domain_version_id, "pref batch test revision"),
    ).fetchone()[0]
    return {"plan_id": plan_id, "revision_id": revision_id}


def test_batch_detects_repeated_brand_swap_and_upserts_prefer_avoid(raw_conn):
    from src.services import feedback_service

    user_id = _make_user(raw_conn, "batch")
    pr = _make_plan_revision(raw_conn)
    intel_or_a, amd_or_b = _two_variants_of_different_brands(raw_conn, "cpu")

    for i in range(preference_signal_batch.REPEAT_THRESHOLD):
        feedback_service.emit_replaced(
            raw_conn, plan_id=pr["plan_id"], revision_id=pr["revision_id"], run_id=None,
            item_id=str(uuid4()), version=i, user_id=user_id,
            payload={"from_variant_id": str(intel_or_a["variant_id"]),
                     "to_variant_id": str(amd_or_b["variant_id"]), "slot": "CPU"},
        )

    result = preference_signal_batch.run(raw_conn)
    assert result["updated_signals"] >= 2

    repo = PreferenceRepo(raw_conn)
    active = repo.list_active(user_id, dimension="brand")
    by_value = {row["value"]: row for row in active}
    assert by_value[amd_or_b["brand"]]["direction"] == "prefer"
    assert by_value[intel_or_a["brand"]]["direction"] == "avoid"
    assert by_value[amd_or_b["brand"]]["confidence"] == preference_signal_batch.REPEAT_THRESHOLD


def test_batch_records_confidence_below_threshold_but_does_not_surface_it(raw_conn):
    """쌓기(confidence 누적)는 관측 즉시 하지만, 문턱(REPEAT_THRESHOLD)을 넘기 전엔
    list_active(min_confidence=...)로 걸러 보여주지 않는다 — 쌓는 문턱과 보여주는 문턱을
    분리했다(batch idempotency 재설계 참고)."""
    from src.services import feedback_service

    user_id = _make_user(raw_conn, "below")
    pr = _make_plan_revision(raw_conn)
    a, b = _two_variants_of_different_brands(raw_conn, "gpu")

    feedback_service.emit_replaced(
        raw_conn, plan_id=pr["plan_id"], revision_id=pr["revision_id"], run_id=None,
        item_id=str(uuid4()), version=1, user_id=user_id,
        payload={"from_variant_id": str(a["variant_id"]), "to_variant_id": str(b["variant_id"]), "slot": "GPU"},
    )

    preference_signal_batch.run(raw_conn)
    repo = PreferenceRepo(raw_conn)
    active = repo.list_active(user_id, dimension="brand")
    assert len(active) == 2, "a single swap is still recorded (confidence=1), just below the surfacing threshold"
    assert all(row["confidence"] == 1 for row in active)
    assert repo.list_active(user_id, dimension="brand",
                            min_confidence=preference_signal_batch.REPEAT_THRESHOLD) == [], \
        "one swap must not be treated as a surfaceable pattern"


def test_batch_rerun_is_idempotent_and_does_not_inflate_confidence(raw_conn):
    from src.services import feedback_service

    user_id = _make_user(raw_conn, "idempotent")
    pr = _make_plan_revision(raw_conn)
    a, b = _two_variants_of_different_brands(raw_conn, "ram")

    for i in range(preference_signal_batch.REPEAT_THRESHOLD):
        feedback_service.emit_replaced(
            raw_conn, plan_id=pr["plan_id"], revision_id=pr["revision_id"], run_id=None,
            item_id=str(uuid4()), version=i, user_id=user_id,
            payload={"from_variant_id": str(a["variant_id"]), "to_variant_id": str(b["variant_id"]), "slot": "RAM"},
        )

    first = preference_signal_batch.run(raw_conn)
    second = preference_signal_batch.run(raw_conn)
    third = preference_signal_batch.run(raw_conn)

    assert first["updated_signals"] == 2         # prefer + avoid, first time
    assert second["updated_signals"] == 0, "rerunning with no new events must not touch anything"
    assert third["updated_signals"] == 0

    repo = PreferenceRepo(raw_conn)
    active = {row["value"]: row for row in repo.list_active(user_id, dimension="brand")}
    assert active[b["brand"]]["confidence"] == preference_signal_batch.REPEAT_THRESHOLD
    assert active[a["brand"]]["confidence"] == preference_signal_batch.REPEAT_THRESHOLD

    # 새 이벤트 하나가 더 생기면 그것만 반영된다(전체를 다시 세지 않는다).
    feedback_service.emit_replaced(
        raw_conn, plan_id=pr["plan_id"], revision_id=pr["revision_id"], run_id=None,
        item_id=str(uuid4()), version=99, user_id=user_id,
        payload={"from_variant_id": str(a["variant_id"]), "to_variant_id": str(b["variant_id"]), "slot": "RAM"},
    )
    fourth = preference_signal_batch.run(raw_conn)
    assert fourth["updated_signals"] == 2
    active = {row["value"]: row for row in repo.list_active(user_id, dimension="brand")}
    assert active[b["brand"]]["confidence"] == preference_signal_batch.REPEAT_THRESHOLD + 1


def _swap(raw_conn, pr, user_id, frm, to, slot):
    from src.services import feedback_service
    feedback_service.emit_replaced(
        raw_conn, plan_id=pr["plan_id"], revision_id=pr["revision_id"], run_id=None,
        item_id=str(uuid4()), version=0, user_id=user_id,
        payload={"from_variant_id": str(frm["variant_id"]), "to_variant_id": str(to["variant_id"]), "slot": slot},
    )


def test_batch_counts_swaps_back_and_forth_as_net_not_as_a_pattern(raw_conn):
    """A→B 세 번 뒤 B→A 두 번 — 예전 배치는 새 이벤트를 방향 덮어쓰기로 더해 양쪽 다 문턱을 넘겼다."""
    user_id = _make_user(raw_conn, "batch-net")
    pr = _make_plan_revision(raw_conn)
    a, b = _two_variants_of_different_brands(raw_conn, "gpu")
    for _ in range(3):
        _swap(raw_conn, pr, user_id, a, b, "GPU")
    preference_signal_batch.run(raw_conn)
    for _ in range(2):
        _swap(raw_conn, pr, user_id, b, a, "GPU")
    preference_signal_batch.run(raw_conn)

    active = {r["value"]: r for r in PreferenceRepo(raw_conn).list_active(user_id, dimension="brand")}
    assert (active[b["brand"]]["direction"], active[b["brand"]]["confidence"]) == ("prefer", 1)
    assert (active[a["brand"]]["direction"], active[a["brand"]]["confidence"]) == ("avoid", 1)
    assert PreferenceRepo(raw_conn).list_active(user_id, min_confidence=preference_signal_batch.REPEAT_THRESHOLD) == []
    assert preference_signal_batch.run(raw_conn)["updated_signals"] == 0


def test_batch_leaves_explicit_statements_alone(raw_conn):
    from src.services.session_service import apply_explicit_preference_patches

    user_id = _make_user(raw_conn, "batch-explicit")
    pr = _make_plan_revision(raw_conn)
    a, b = _two_variants_of_different_brands(raw_conn, "cpu")
    apply_explicit_preference_patches(raw_conn, user_id, [{"slot": "CPU", "value": a["brand"], "direction": "prefer"}])
    for _ in range(3):
        _swap(raw_conn, pr, user_id, a, b, "CPU")                  # 말과 반대로 행동해도
    preference_signal_batch.run(raw_conn)
    row = PreferenceRepo(raw_conn).get_signal(user_id=user_id, dimension="brand", slot="CPU", value=a["brand"])
    assert (row["source"], row["direction"], row["confidence"]) == ("explicit_chat", "prefer", 1)


def test_batch_keeps_a_dismissed_signal_dismissed_until_a_new_event(raw_conn):
    user_id = _make_user(raw_conn, "batch-dismiss")
    pr = _make_plan_revision(raw_conn)
    a, b = _two_variants_of_different_brands(raw_conn, "ram")
    for _ in range(3):
        _swap(raw_conn, pr, user_id, a, b, "RAM")
    preference_signal_batch.run(raw_conn)
    repo = PreferenceRepo(raw_conn)
    signal = repo.get_signal(user_id=user_id, dimension="brand", slot="RAM", value=b["brand"])
    repo.dismiss(user_id, signal["id"])

    preference_signal_batch.run(raw_conn)
    assert repo.get_signal(user_id=user_id, dimension="brand", slot="RAM", value=b["brand"])["status"] == "dismissed"
    _swap(raw_conn, pr, user_id, a, b, "RAM")
    preference_signal_batch.run(raw_conn)
    again = repo.get_signal(user_id=user_id, dimension="brand", slot="RAM", value=b["brand"])
    assert (again["status"], again["confidence"]) == ("active", 4)


# ── 4. 회원 탈퇴 시 신호 삭제 ─────────────────────────────────────────────────
def test_withdraw_deletes_preference_signals(raw_conn):
    user_id = _make_user(raw_conn, "withdraw")
    PreferenceRepo(raw_conn).upsert_signal(user_id=user_id, dimension="brand", slot="GPU",
                                           value="AMD", direction="prefer", source="explicit_chat")

    UserRepo(raw_conn).withdraw(user_id)

    remaining = raw_conn.execute(
        "SELECT count(*) FROM identity.preference_signal WHERE user_id=%s", (user_id,)
    ).fetchone()[0]
    assert remaining == 0


# ── 5. 세션 그리팅 되묻기 (§6) ───────────────────────────────────────────────
def test_preference_hint_surfaces_paired_prefer_avoid_and_respond_accept_sets_brand_pref(raw_conn):
    email = f"pref-hint-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "HintTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    user_id = _current_user_id(raw_conn, email.lower())

    repo = PreferenceRepo(raw_conn)
    prefer = repo.upsert_signal(user_id=user_id, dimension="brand", slot="CPU", value="AMD",
                                direction="prefer", source="inferred_swap", confidence_delta=3)
    repo.upsert_signal(user_id=user_id, dimension="brand", slot="CPU", value="Intel",
                       direction="avoid", source="inferred_swap", confidence_delta=3)

    r = c.get("/session/previous", params={"category": "computer", "mode": "build"})
    assert r.status_code == 200, r.text
    hint = r.json()["preference_hint"]
    assert hint is not None
    assert hint["slot"] == "CPU" and hint["value"] == "AMD" and hint["direction"] == "prefer"
    assert "Intel" in hint["summary"] and "AMD" in hint["summary"]

    list_id = _create(c)
    _choose_computer(c, list_id)
    r = c.post(f"/session/{list_id}/preference-hint/{hint['id']}/respond", json={"accepted": True})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True

    row = raw_conn.execute(
        "SELECT pc.value FROM planning.plan_condition pc "
        "JOIN planning.plan_revision pr ON pr.id = pc.revision_id "
        "JOIN planning.plan p ON p.id = pr.plan_id "
        "WHERE p.id = %s AND pc.condition_key='brand_pref' AND pc.status='active'",
        (list_id,),
    ).fetchone()
    assert row[0]["value"] == "amd"
    # "예"는 신호를 지우지 않는다(§9) — 다음 세션에도 다시 물어볼 수 있게.
    assert any(s["id"] == prefer["id"] for s in repo.list_active(user_id, dimension="brand"))


@pytest.mark.parametrize("slot,brand", [("GPU", "NVIDIA"), ("파워", "Seasonic"), ("CPU", "인텔")])
def test_accepting_a_prefer_hint_brand_pref_cannot_hold_does_not_break_recommend(raw_conn, slot, brand):
    """brand_pref 는 CPU 브랜드 enum(intel·amd·none)이다 — stage2 가 sockets_by_brand[brand] 로 읽는다.
    예전엔 GPU "NVIDIA"를 수락하면 brand_pref="nvidia"가 들어가 다음 추천이 KeyError 로 죽었다.
    CPU 가 아니거나 enum 밖의 값(에이전트가 적은 "인텔" 등)은 조건에 넣지 않고 신호만 active 로 둔다."""
    email = f"pref-accept-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    assert c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "AcceptTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    }).status_code == 201
    user_id = _current_user_id(raw_conn, email.lower())
    signal = PreferenceRepo(raw_conn).upsert_signal(user_id=user_id, dimension="brand", slot=slot, value=brand,
                                                    direction="prefer", source="explicit_chat")

    list_id = _create(c)
    _choose_computer(c, list_id)
    for field, value in (("purpose", "game"), ("budget_max", 2_000_000), ("priority", "performance"), ("resolution", "FHD_144")):
        assert c.patch(f"/session/{list_id}/slot", json={"field": field, "value": value}).status_code == 200
    r = c.post(f"/session/{list_id}/preference-hint/{signal['id']}/respond", json={"accepted": True})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is False

    assert raw_conn.execute(
        "SELECT count(*) FROM planning.plan_condition pc JOIN planning.plan_revision pr ON pr.id = pc.revision_id "
        "WHERE pr.plan_id = %s AND pc.condition_key='brand_pref' AND pc.status='active'", (list_id,),
    ).fetchone()[0] == 0
    assert any(s["id"] == signal["id"] for s in PreferenceRepo(raw_conn).list_active(user_id, dimension="brand"))

    assert c.post(f"/session/{list_id}/recommend").status_code == 202
    assert c.get(f"/session/{list_id}/result").json()["status"] == "done"


def test_preference_hint_respond_reject_dismisses_signal_without_touching_condition(raw_conn):
    email = f"pref-reject-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "RejectTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    user_id = _current_user_id(raw_conn, email.lower())

    repo = PreferenceRepo(raw_conn)
    signal = repo.upsert_signal(user_id=user_id, dimension="brand", slot="GPU", value="NVIDIA",
                                direction="prefer", source="inferred_swap", confidence_delta=3)

    list_id = _create(c)
    _choose_computer(c, list_id)
    r = c.post(f"/session/{list_id}/preference-hint/{signal['id']}/respond", json={"accepted": False})
    assert r.status_code == 200, r.text

    assert repo.list_active(user_id, dimension="brand") == []
    row = raw_conn.execute(
        "SELECT count(*) FROM planning.plan_condition pc "
        "JOIN planning.plan_revision pr ON pr.id = pc.revision_id "
        "JOIN planning.plan p ON p.id = pr.plan_id "
        "WHERE p.id = %s AND pc.condition_key='brand_pref'",
        (list_id,),
    ).fetchone()
    assert row[0] == 0


def test_preference_hint_is_none_for_guest_sessions(client):
    r = client.get("/session/previous", params={"category": "computer", "mode": "build"})
    assert r.status_code == 200, r.text
    assert r.json()["preference_hint"] is None


# ── 6. 결과 화면 채팅으로 바꾼 것도 잡히는지 (규칙 경로 — MOCK_MODE=1이라 에이전트는 비활성) ──
def test_chat_swap_via_result_message_also_carries_user_id_and_payload(raw_conn):
    email = f"pref-chat-{uuid4().hex[:12]}@example.test"
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": email, "password": "abcd1234", "display_name": "ChatSwapTester",
        "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    user_id = _current_user_id(raw_conn, email.lower())

    list_id = _create(c)
    _choose_computer(c, list_id)
    state = _fill_computer_conditions(c, list_id)
    revision_id = state["revision_id"]
    _recommend_and_wait(c, list_id)

    r = c.post(f"/session/{list_id}/result-message", json={"text": "그래픽카드 더 저렴한 걸로 바꿔줘"})
    assert r.status_code == 200, r.text

    row = raw_conn.execute(
        "SELECT payload, user_id FROM engine.feedback_event "
        "WHERE revision_id=%s AND event_type='item_replaced' ORDER BY created_at DESC LIMIT 1",
        (revision_id,),
    ).fetchone()
    assert row is not None, "chat-triggered swap must still emit item_replaced"
    payload, event_user_id = row
    assert payload["from_variant_id"] and payload["to_variant_id"] and payload["slot"] == "GPU"
    assert str(event_user_id) == str(user_id)


# ── 7. 채팅에서 직접 말한 선호(파이프라인 A) — session_service 저장 로직 + 문턱 우회 ──
def test_apply_explicit_preference_patches_persists_and_skips_for_guest(raw_conn):
    from src.services.session_service import apply_explicit_preference_patches

    user_id = _make_user(raw_conn, "explicit")
    n = apply_explicit_preference_patches(
        raw_conn, user_id,
        [{"slot": "GPU", "value": "NVIDIA", "direction": "prefer"},
         {"slot": "CPU", "value": "Intel", "direction": "avoid"}],
    )
    assert n == 2
    repo = PreferenceRepo(raw_conn)
    active = {(row["slot"], row["value"]): row for row in repo.list_active(user_id, dimension="brand")}
    assert active[("GPU", "NVIDIA")]["source"] == "explicit_chat"
    assert active[("GPU", "NVIDIA")]["confidence"] == 1

    guest_n = apply_explicit_preference_patches(raw_conn, None, [{"slot": "GPU", "value": "AMD", "direction": "prefer"}])
    assert guest_n == 0, "guests (no user_id) must not have preferences persisted"


def test_explicit_chat_signal_surfaces_immediately_without_repeat_threshold(raw_conn):
    """단 한 번 말한 것도 즉시 되묻기에 뜬다 — 문턱은 inferred_swap에만 적용된다."""
    from src.services.session_service import apply_explicit_preference_patches

    user_id = _make_user(raw_conn, "explicit-hint")
    apply_explicit_preference_patches(
        raw_conn, user_id, [{"slot": "케이스", "value": "다크플래쉬", "direction": "prefer"}],
    )
    repo = PreferenceRepo(raw_conn)
    gated = repo.list_active(user_id, dimension="brand", min_confidence=preference_signal_batch.REPEAT_THRESHOLD)
    assert len(gated) == 1 and gated[0]["value"] == "다크플래쉬"

"""예외/동시성 시나리오 — 전체_테스트_시나리오_실행_기획.md §6(4번 예외) · §11(9번 동시성).

실제 동시 요청(스레드)을 쓰지 않고, 가드가 보는 DB 상태를 직접 만들어 결정론적으로 검사한다
(스레드 기반 레이스 테스트는 타이밍에 의존해 flaky해지기 쉽다 — §2.5 반복 정책 참고, 가능하면
타이밍 비의존적인 쪽을 우선한다). 일회용 DB 가 필요하다.

주의: 애초에 전체_테스트_시나리오_실행_기획.md §11에 "동시 PATCH → Conflict 409"라고 적어뒀던
것은 부정확했다 — 실제로 `/session/{id}/slot`과 `/items/{id}` PATCH에는 버전 비교가 전혀 없다
(마지막에 쓴 값이 그냥 이긴다, optimistic lock 없음). 실제로 버전 충돌을 막는 곳은 `/lists/{id}`
confirm의 `If-Match` 헤더(§ test_confirm_with_stale_if_match_is_conflict)뿐이다 — 이 파일이 그
차이를 실측으로 확정한다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app

    @pytest.fixture()
    def raw_conn():
        conn = psycopg.connect(DSN, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()


def _signed_up() -> "TestClient":
    c = TestClient(app)
    r = c.post("/auth/signup", json={
        "email": f"exc-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
        "display_name": "예외 테스트", "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False,
    })
    assert r.status_code == 201, r.text
    return c


def _conditions(c, lid: str, *, budget: int = 2_000_000) -> dict:
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/message", json={"text": "게임용 PC 맞추고 싶어요"})
    assert r.status_code == 200, r.text
    for qid, value in (("q_purpose", "게임"), ("q_budget_max", budget), ("q_priority", "성능 우선")):
        r = c.post(f"/session/{lid}/answer", json={"question_id": qid, "selected": [value]})
        assert r.status_code == 200, r.text
    return r.json()


def _recommended_list(c, **kw) -> tuple[str, str]:
    lid = c.post("/session").json()["list_id"]
    state = _conditions(c, lid, **kw)
    assert state["can_recommend"] is True, state
    assert c.post(f"/session/{lid}/recommend").status_code == 202
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] == "done", data
    return lid, state["revision_id"]


# ── 4번 예외 ──────────────────────────────────────────────────────────────

def test_nonexistent_list_id_is_404():
    c = _signed_up()
    assert c.get(f"/session/{uuid4()}/result").status_code == 404
    assert c.get(f"/session/{uuid4()}").status_code == 404


def test_recommend_without_category_is_conflict_not_crash():
    c = _signed_up()
    lid = c.post("/session").json()["list_id"]
    r = c.post(f"/session/{lid}/recommend")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "category_required"


def test_recommend_with_missing_required_conditions_is_validation_error():
    c = _signed_up()
    lid = c.post("/session").json()["list_id"]
    assert c.post(f"/session/{lid}/category", json={"category": "computer", "mode": "build"}).status_code == 200
    r = c.post(f"/session/{lid}/recommend")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "conditions_incomplete"


def test_impossible_budget_still_produces_a_clear_outcome_not_a_hang():
    """예산이 터무니없이 낮아도(최저가 합계보다 한참 아래) 추천 파이프라인이 멈추거나 500을 내지
    않고, 완료(가능한 한 싼 구성) 또는 명확한 실패로 끝나는지 — catalog_incomplete 류."""
    c = _signed_up()
    lid = c.post("/session").json()["list_id"]
    _conditions(c, lid, budget=1_000)  # 사실상 0원 — 어떤 카탈로그도 못 채움
    r = c.post(f"/session/{lid}/recommend")
    assert r.status_code == 202, r.text
    data = c.get(f"/session/{lid}/result").json()
    assert data["status"] in {"done", "failed"}, data  # 행잉·500 없이 둘 중 하나로 확정


def test_confirm_requires_login_guest_cannot_confirm():
    guest = TestClient(app)
    lid, _rid = _recommended_list(guest)
    r = guest.post(f"/lists/{lid}/confirm", json={"name": "게스트 확정 시도"})
    assert r.status_code in (401, 403), r.text


# ── 9번 동시성/정합성 ──────────────────────────────────────────────────────

def test_confirm_with_stale_if_match_is_conflict():
    """다른 탭에서 조건을 바꿔(lock_version 증가) revision이 앞서가면, 구 버전을 쥔 쪽의 확정
    요청은 If-Match 불일치로 막힌다 — 자동 덮어쓰기 없음."""
    c = _signed_up()
    lid, _rid = _recommended_list(c)
    state = c.get(f"/session/{lid}").json()
    stale_version = state["lock_version"]

    # 조건을 하나 더 바꿔 lock_version을 올린다(새로 추천할 필요까진 없이 slot만 바꿔도 올라간다).
    assert c.patch(f"/session/{lid}/slot", json={"field": "priority", "value": "quiet"}).status_code == 200

    r = c.post(f"/lists/{lid}/confirm", json={"name": "낡은 버전으로 확정 시도"},
              headers={"If-Match": str(stale_version)})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "stale_revision"


def test_confirm_after_condition_changed_without_rerecommend_is_conflict():
    """추천을 받은 뒤 조건을 바꾸고 재추천 없이 바로 확정하면 stale_recommendation으로 막힌다."""
    c = _signed_up()
    lid, _rid = _recommended_list(c)
    assert c.patch(f"/session/{lid}/slot", json={"field": "priority", "value": "quiet"}).status_code == 200

    r = c.post(f"/lists/{lid}/confirm", json={"name": "조건만 바꾸고 확정"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "stale_recommendation"


def test_recommend_while_already_running_is_conflict(raw_conn):
    """진행 중인 run이 있는 상태에서 또 /recommend를 부르면 거부된다(`run_in_progress`).
    실제 스레드 경합 대신, 가드가 읽는 DB 상태(status='running')를 직접 만들어 결정론적으로 검사한다."""
    c = _signed_up()
    lid, _rid = _recommended_list(c)
    raw_conn.execute("UPDATE engine.recommendation_run SET status='running' WHERE revision_id="
                     "(SELECT current_revision_id FROM planning.plan WHERE id=%s)", (lid,))

    r = c.post(f"/session/{lid}/recommend")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "run_in_progress"


def test_patch_item_has_no_optimistic_lock_last_write_wins():
    """발견 사항(회귀 아님, 현재 설계 확인) — /items/{id} PATCH는 버전 비교가 없다. 두 번 연달아
    보내면 그냥 둘 다 적용되고 나중 값이 남는다. 동시 수정 충돌 감지가 필요하면 이 엔드포인트에는
    아직 없다는 뜻 — 전체_테스트_시나리오_실행_기획.md §14에 발견 사항으로 반영 필요."""
    c = _signed_up()
    lid, _rid = _recommended_list(c)
    item_id = c.get(f"/session/{lid}/result").json()["items"][0]["item_id"]

    r1 = c.patch(f"/session/{lid}/items/{item_id}", json={"qty": 2})
    assert r1.status_code == 200, r1.text
    r2 = c.patch(f"/session/{lid}/items/{item_id}", json={"qty": 3})
    assert r2.status_code == 200, r2.text

    final = c.get(f"/session/{lid}/result").json()
    item = next(i for i in final["items"] if i["item_id"] == item_id)
    assert item["qty"] == 3  # 충돌 에러 없이 마지막 값이 조용히 이긴다 — 의도된 설계인지는 별도 확인 필요

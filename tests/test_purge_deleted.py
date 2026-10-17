"""영구 삭제(재기획 6.7) — 완전히 삭제, 보관 기간 지난 항목 정리. 실제 추천 흐름이 만든 행(실행·후보·피드백·가격 알림)까지 지워지는지 본다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg
    from fastapi.testclient import TestClient

    from src.api import app
    from tests.test_list_history_http import _recommended_list, _signed_up

TABLES = [
    ("planning.plan", "id"), ("planning.plan_revision", "plan_id"), ("planning.purchase_line", None), ("engine.recommendation_run", None),
    ("engine.feedback_event", "plan_id"), ("identity.conversation", None),
]


def _db():
    return psycopg.connect(DSN, autocommit=True)


def _count(sql: str, *params) -> int:
    with _db() as conn:
        return conn.execute(sql, params).fetchone()[0]


def _rows(lid: str) -> dict[str, int]:
    return {
        "plan": _count("SELECT count(*) FROM planning.plan WHERE id=%s", lid),
        "revisions": _count("SELECT count(*) FROM planning.plan_revision WHERE plan_id=%s", lid),
        "lines": _count("SELECT count(*) FROM planning.purchase_line l JOIN planning.plan_revision r ON r.id=l.revision_id WHERE r.plan_id=%s", lid),
        "runs": _count("SELECT count(*) FROM engine.recommendation_run x JOIN planning.plan_revision r ON r.id=x.revision_id WHERE r.plan_id=%s", lid),
        "feedback": _count("SELECT count(*) FROM engine.feedback_event WHERE plan_id=%s", lid),
        "conditions": _count("SELECT count(*) FROM planning.plan_condition c JOIN planning.plan_revision r ON r.id=c.revision_id WHERE r.plan_id=%s", lid),
    }


def _confirmed_with_alert(c):
    lid, _rev, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "지울 견적", "target_amount": 4_000_000}).status_code == 200
    c.post(f"/lists/{lid}/alert", json={"enabled": True, "target_amount": 4_000_000})
    return lid


def test_permanent_delete_removes_every_row_of_a_confirmed_list():
    c = _signed_up()
    lid = _confirmed_with_alert(c)
    before = _rows(lid)
    assert before["plan"] == 1 and before["runs"] >= 1 and before["lines"] >= 1 and before["conditions"] >= 1, before
    assert c.delete(f"/lists/{lid}", params={"permanent": "true"}).status_code == 204
    assert _rows(lid) == {k: 0 for k in before}
    assert c.get(f"/lists/{lid}/report").status_code == 404


def test_a_plain_delete_only_marks_and_a_stranger_or_guest_cannot_delete_permanently():
    owner = _signed_up()
    lid = _confirmed_with_alert(owner)
    assert _signed_up().delete(f"/lists/{lid}", params={"permanent": "true"}).status_code == 404
    assert TestClient(app).delete(f"/lists/{lid}", params={"permanent": "true"}).status_code in (401, 404)
    assert _rows(lid)["plan"] == 1
    assert owner.delete(f"/lists/{lid}").status_code == 204                       # 삭제 표시만 — 행은 남는다
    assert _rows(lid)["plan"] == 1 and _count("SELECT count(*) FROM planning.plan WHERE id=%s AND status='deleted'", lid) == 1


def test_permanent_delete_of_one_report_keeps_the_conversation_and_other_reports():
    from tests.test_report_delete_rename_http import _confirm_second_report

    c = _signed_up()
    lid, _rev, _data = _recommended_list(c)
    assert c.post(f"/lists/{lid}/confirm", json={"name": "A"}).status_code == 200
    _confirm_second_report(c, lid, "B")
    assert c.delete(f"/lists/{lid}/reports/1", params={"permanent": "true"}).status_code == 200
    assert _count("SELECT count(*) FROM planning.plan_revision WHERE plan_id=%s AND revision_no=1", lid) == 0
    assert _count("SELECT count(*) FROM planning.plan_revision WHERE plan_id=%s AND state='confirmed'", lid) == 1
    assert c.get(f"/lists/{lid}/report", params={"revision": 2}).status_code == 200


def test_purge_expired_removes_only_items_past_the_retention_period():
    from src.services import purge_service

    c = _signed_up()
    old, fresh, alive = _confirmed_with_alert(c), _confirmed_with_alert(c), _confirmed_with_alert(c)
    assert c.delete(f"/lists/{old}").status_code == 204 and c.delete(f"/lists/{fresh}").status_code == 204
    with _db() as conn:
        conn.execute("UPDATE planning.plan SET deleted_at = now() - interval '31 days' WHERE id=%s", (old,))
        result = purge_service.purge_expired(conn, 30)
    assert result["plans"] >= 1
    assert _rows(old)["plan"] == 0 and _rows(old)["runs"] == 0
    assert _rows(fresh)["plan"] == 1 and _rows(alive)["plan"] == 1

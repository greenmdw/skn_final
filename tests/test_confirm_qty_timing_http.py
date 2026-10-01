"""확정 스냅샷이 결과 화면에서 바꾼 수량을 그대로 얼리는지.

예전엔 purchase_line 을 1개·단가로 얼려서, 수량을 바꾸고 확정하면 리포트에 ×1 로 보이고 부품 금액의 합이
확정 총액(단가 × 수량의 합)과 어긋났다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    import psycopg

    from tests.test_list_history_http import _recommended_list, _signed_up


def test_confirm_keeps_quantity_and_lines_add_up_to_total():
    c = _signed_up()
    lid, revision_id, data = _recommended_list(c)
    item = next(it for it in data["items"] if it["selected"])
    r = c.patch(f"/session/{lid}/items/{item['item_id']}", json={"qty": 2})
    assert r.status_code == 200, r.text

    report = c.post(f"/lists/{lid}/confirm", json={"name": "수량 확인"}).json()
    line = next(it for it in report["items"] if it["slot"] == item["slot"])
    assert line["qty"] == 2
    assert line["price"] == item["price"]                               # 리포트 price 는 단가
    assert sum(it["price"] * it["qty"] for it in report["items"]) == report["total"]

    with psycopg.connect(DSN) as conn:
        rows = conn.execute(
            "SELECT pack_count, line_amount FROM planning.purchase_line WHERE revision_id=%s", (revision_id,)
        ).fetchall()
    assert sorted(int(p) for p, _ in rows).count(2) == 1
    assert sum(int(a) for _, a in rows) == report["total"]            # 줄 합계의 합 = 확정 총액

    # 다시 읽어도(GET) 같은 값
    again = c.get(f"/lists/{lid}/report").json()
    assert next(it for it in again["items"] if it["slot"] == item["slot"])["qty"] == 2

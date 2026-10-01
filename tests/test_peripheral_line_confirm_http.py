"""개발요청 11번 — 확정 견적서에 주변기기(모니터·키보드·마우스·스피커) 저장.

`POST /lists/{id}/confirm`의 `peripherals`로 PC 부품과 같이 확정하면 `planning.peripheral_line`에
얼려지고, `GET /lists`의 `reports[].peripheral_count`·`GET /lists/{id}/report`의 `peripherals[]`에
나타난다. `item_count`는 본체 부품 수만, `total`은 본체+주변기기 합계다. 일회용 DB 가 필요하다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.api import app
    from tests.test_list_history_http import _recommended_list, _signed_up


def _list_item(c, lid: str) -> dict:
    r = c.get("/lists")
    assert r.status_code == 200, r.text
    return next(item for item in r.json()["items"] if item["list_id"] == lid)


def _peripheral_candidate(c, lid: str, kind: str) -> dict:
    # QHD_165는 모니터 카탈로그에 실제 매칭 후보가 있다(FHD_144 기본값은 없다 — 카탈로그 한계, 7번 참고).
    r = c.post(f"/session/{lid}/peripherals/recommend", json={"kinds": [kind], "resolution": "QHD_165"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready", data
    return next(i for i in data["items"] if i["kind"] == kind)   # {kind, product, price, ...}


def test_confirm_with_peripherals_freezes_them_and_adds_to_total():
    c = _signed_up()
    lid, _revision_id, data = _recommended_list(c)
    pc_total = sum(i["price"] * i["qty"] for i in data["items"] if i["selected"])

    keyboard = _peripheral_candidate(c, lid, "keyboard")
    monitor = _peripheral_candidate(c, lid, "monitor")

    r = c.post(f"/lists/{lid}/confirm", json={
        "name": "주변기기 포함 견적",
        "peripherals": [
            {"kind": "keyboard", "variant_id": keyboard["product"]["variant_id"], "qty": 1},
            {"kind": "monitor", "variant_id": monitor["product"]["variant_id"], "qty": 1},
        ],
    })
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["total"] == pc_total + keyboard["price"] + monitor["price"]
    kinds = {p["kind"]: p for p in report["peripherals"]}
    assert set(kinds) == {"keyboard", "monitor"}
    assert kinds["keyboard"]["product"]["name"] == keyboard["product"]["name"]
    assert kinds["keyboard"]["price"] == keyboard["price"]

    item = _list_item(c, lid)
    assert item["reports"][0]["peripheral_count"] == 2
    assert item["reports"][0]["item_count"] == len(report["items"])     # 본체 부품 수만

    again = c.get(f"/lists/{lid}/report").json()
    assert {p["kind"] for p in again["peripherals"]} == {"keyboard", "monitor"}


def test_confirm_without_peripherals_keeps_old_behavior():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    r = c.post(f"/lists/{lid}/confirm", json={"name": "주변기기 없음"})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["peripherals"] == []

    item = _list_item(c, lid)
    assert item["reports"][0]["peripheral_count"] == 0


def test_confirm_rejects_an_unknown_peripheral_variant_and_persists_nothing():
    c = _signed_up()
    lid, _revision_id, _data = _recommended_list(c)
    r = c.post(f"/lists/{lid}/confirm", json={
        "name": "실패해야 함",
        "peripherals": [{"kind": "keyboard", "variant_id": "00000000-0000-0000-0000-000000000000", "qty": 1}],
    })
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "peripheral_not_found"

    # 확정 자체가 안 됐다 — 다시 시도하면(주변기기 없이) 정상 확정된다.
    r2 = c.post(f"/lists/{lid}/confirm", json={"name": "재시도"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["peripherals"] == []

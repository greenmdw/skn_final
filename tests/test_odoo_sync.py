"""A 방식 Odoo 미러 — 비활성 시 무해, RPC 바디 형태, 노트 파싱 검증."""

from __future__ import annotations

import os
import unittest

os.environ.pop("ODOO_SYNC", None)

from fastapi.testclient import TestClient

from app.integrations.odoo.rpc import OdooRpc
from app.integrations.odoo.sync import _parse_notes, seed, sync_enabled


class _StubClient:
    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def call(self, model, method, parameters=None):
        self.calls.append((model, method, dict(parameters or {})))
        return self.ret


class SyncDisabledTests(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(sync_enabled())
        self.assertFalse(seed()["ok"])

    def test_buyer_pull_returns_409_when_disabled(self):
        from app.buyer_service import app
        r = TestClient(app).post("/api/odoo/pull")
        self.assertEqual(r.status_code, 409)


class RpcShapeTests(unittest.TestCase):
    def test_search_read_body(self):
        stub = _StubClient([{"id": 5}])
        rows = OdooRpc(stub).search_read("sale.order", [["id", "=", 5]], ["id"], limit=3)
        self.assertEqual(rows, [{"id": 5}])
        model, method, params = stub.calls[0]
        self.assertEqual((model, method), ("sale.order", "search_read"))
        self.assertEqual(params, {"domain": [["id", "=", 5]], "fields": ["id"], "limit": 3})

    def test_create_sends_vals_list_and_unwraps_id(self):
        stub = _StubClient([42])
        rid = OdooRpc(stub).create("res.partner", {"name": "x"})
        self.assertEqual(rid, 42)
        self.assertEqual(stub.calls[0][2], {"vals_list": [{"name": "x"}]})

    def test_result_wrapper_unwrapped(self):
        stub = _StubClient({"result": [{"id": 9}]})
        self.assertEqual(OdooRpc(stub).search_read("m", [], ["id"]), [{"id": 9}])


class NoteParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(_parse_notes("spec: GDDR6 48GB ECC | priority: spec_max"),
                         ("GDDR6 48GB ECC", "spec_max"))
        self.assertEqual(_parse_notes("사양: HBM3 94GB"), ("HBM3 94GB", "price_min"))
        self.assertEqual(_parse_notes(""), ("", "price_min"))
        self.assertEqual(_parse_notes("priority: bogus"), ("", "price_min"))


if __name__ == "__main__":
    unittest.main()

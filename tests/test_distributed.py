"""
v5 분산 구조 — broker → seller HTTP, buyer → broker HTTP 를 in-process 로 검증.

net.set_dispatcher 로 실제 네트워크 대신 TestClient 로 라우팅한다.
핵심 검증:
  - 진짜로 서비스 경계를 넘어 호출이 일어난다 (broker 로그에 REQUEST->endpoint 가 찍힘).
  - 정보 경계: broker 응답/로그, buyer 응답 어디에도 floor_price 가 없다.
  - price_min / spec_max / NO_MATCH / NO_DEAL 이 분산 경로에서도 동작한다.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("NEGOTIATOR_MODE", "rule")

from fastapi.testclient import TestClient

from app import net
from app.broker_service import app as broker_app
from app.schemas import Item, SellerRegister
from app.seller_service import create_app as make_seller

L40S = Item.L40S.value
DESC = "Ada Lovelace 아키텍처; GDDR6 48GB ECC; PCIe 4.0 x16; 최대 소비전력 350W"


def _seller(seller_id, offer, floor, **kw):
    return SellerRegister(
        seller_id=seller_id, item=Item.L40S, qty=kw.get("qty", 50),
        offer_price=offer, floor_price=floor, description=DESC,
        lead_time_days=kw.get("lead", 20), moq=kw.get("moq", 1),
        trust_score=kw.get("trust", 100),
        bulk_discount_rate=kw.get("bdr", 0.0), bulk_discount_min_qty=kw.get("bdq", 0),
        payment_terms=kw.get("pay", ""), delivery_terms=kw.get("deliv", ""),
    )


class DistributedNegotiationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s1 = TestClient(make_seller(_seller("셀러1", 11_000_000, 9_800_000, pay="선급 30%")))
        self.s2 = TestClient(make_seller(_seller("셀러2", 10_600_000, 10_100_000)))
        self.broker = TestClient(broker_app)
        self.clients = {
            "http://seller1:8000": self.s1,
            "http://seller2:8000": self.s2,
            "http://broker:9000": self.broker,
        }
        net.set_dispatcher(self._dispatch)
        self.addCleanup(net.set_dispatcher, None)

    def _dispatch(self, method, url, body):
        for base, cli in self.clients.items():
            if url.startswith(base):
                path = url[len(base):]
                r = cli.post(path, json=body) if method == "POST" else cli.get(path)
                return r.status_code, (r.json() if r.content else None)
        raise AssertionError(f"라우팅 안 됨: {url}")

    def _start(self, **over):
        body = {
            "item": L40S, "qty": 10, "cap_price": 12_000_000, "spec": "GDDR6 48GB ECC",
            "max_lead_time_days": 40, "priority": "price_min",
            "seller_endpoints": ["http://seller1:8000", "http://seller2:8000"],
        }
        body.update(over)
        return self.broker.post("/api/negotiate/start", json=body)

    def test_distributed_settlement_and_crosses_service_boundary(self) -> None:
        r = self._start()
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["status"], "SETTLED")
        # price_min → 더 싼 셀러2
        self.assertEqual(data["seller_id"], "셀러2")
        self.assertLessEqual(data["price"], 12_000_000)

        # 브로커 로그에 실제 서비스 경계 호출이 남았는지
        log = self.broker.get(f"/api/negotiate/{data['txid']}/log").json()["log"]
        req_to_sellers = [e for e in log if e["type"] == "REQUEST" and e["to"].startswith("http")]
        self.assertGreaterEqual(len(req_to_sellers), 2)
        self.assertTrue(any(e["type"] == "OFFER" for e in log))
        self.assertTrue(any(e["type"] == "SETTLED" for e in log))

    def test_information_boundary_no_floor_price_anywhere_broker_side(self) -> None:
        r = self._start()
        data = r.json()
        blob = r.text + self.broker.get(f"/api/negotiate/{data['txid']}/log").text
        self.assertNotIn("floor_price", blob)
        self.assertNotIn("floor", blob.lower())
        # cap_price 도 공개 로그엔 없어야 한다
        self.assertNotIn("cap_price", self.broker.get(f"/api/negotiate/{data['txid']}/log").text)

    def test_spec_max_prefers_higher_similarity(self) -> None:
        # 셀러2를 사양 약한 설명으로 교체 → spec_max 면 셀러1이 이겨야 한다
        self.s2.post("/api/seller/config", json=_seller(
            "셀러2", 10_600_000, 10_100_000).model_dump() | {"description": "GDDR6 48GB", "item": L40S})
        r = self._start(priority="spec_max")
        data = r.json()
        self.assertEqual(data["status"], "SETTLED")
        self.assertEqual(data["seller_id"], "셀러1")

    def test_no_match_when_spec_cannot_be_met(self) -> None:
        r = self._start(spec="HBM3 94GB NVLink")
        self.assertEqual(r.json()["fail_type"], "NO_MATCH")

    def test_no_deal_when_cap_below_all_floors(self) -> None:
        r = self._start(cap_price=9_000_000)
        self.assertEqual(r.json()["fail_type"], "NO_DEAL")


if __name__ == "__main__":
    unittest.main()

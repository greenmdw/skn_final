"""
Buyer 서비스 (v5 분산 구조) — Buyer EC2에서 포트 8000으로 실행.

기존 app.main(목업 화면 + Odoo 라우터 + 로컬 협상 엔드포인트)을 그대로 쓰고,
분산용 엔드포인트를 얹는다:

  POST /api/request        BuyerRequest → 중앙 브로커로 전달, 결과 그대로 반환
  POST /api/odoo/pull      Odoo 구매(purchase.order 초안)에서 새 RFQ 1건을 읽어 협상 → 결과를 그 PO chatter 로 기록  (A 방식)
  POST /api/dev/seed-odoo  협상봇 파트너 + GPU 5종 product 시드

환경변수:
  BROKER_URL          브로커 위치 (예: http://10.0.1.13:9000)
  ODOO_SYNC=on         Odoo 미러 on/off
  ODOO_POLL_SECONDS>0  백그라운드 폴러 간격 (0=수동만)
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException
from pydantic import BaseModel

from .main import app  # 목업 + Odoo + 로컬 엔드포인트 재사용
from .integrations.odoo import sync as odoo_sync
from .net import HttpCallError, get_json, post_json
from .schemas import BuyerRequest, Item

BROKER_URL = os.environ.get("BROKER_URL", "http://localhost:9000")
SELLER_ENDPOINTS = [e.strip() for e in os.environ.get("SELLER_ENDPOINTS", "").split(",") if e.strip()]
POLL_SECONDS = int(os.environ.get("ODOO_POLL_SECONDS", "0") or 0)
_ITEM_VALUES = {i.value for i in Item}


class DistributedRequest(BuyerRequest):
    seller_endpoints: list[str] = []


def _call_broker(body: dict, timeout: float = 60.0) -> dict:
    try:
        code, resp = post_json(f"{BROKER_URL.rstrip('/')}/api/negotiate/start", body, timeout=timeout)
    except HttpCallError as exc:
        raise HTTPException(502, f"브로커 호출 실패: {exc.detail}")
    if code >= 400:
        raise HTTPException(code, detail=resp)
    return resp


@app.post("/api/request")
def distributed_request(req: DistributedRequest) -> dict:
    return _call_broker({
        "item": req.item.value if hasattr(req.item, "value") else req.item,
        "qty": req.qty, "cap_price": req.cap_price, "spec": req.spec,
        "max_lead_time_days": req.max_lead_time_days, "priority": req.priority,
        "seller_trust_min": req.seller_trust_min,
        "seller_endpoints": req.seller_endpoints or SELLER_ENDPOINTS,
    })


@app.post("/api/dev/seed-odoo")
def seed_odoo() -> dict:
    return odoo_sync.seed("buyer")


def _replay_log_to_po(inbox: "odoo_sync.PurchaseInbox", po_id: int, txid: str) -> None:
    """브로커 로그의 핵심 이벤트를 PO chatter 로 옮긴다 (best-effort)."""
    try:
        code, data = get_json(f"{BROKER_URL.rstrip('/')}/api/negotiate/{txid}/log", timeout=10.0)
        if code != 200 or not isinstance(data, dict):
            return
        for e in data.get("log", []):
            p = e.get("payload", {})
            t = e.get("type")
            if t == "OFFER" and p.get("available"):
                inbox.note(po_id, f"{p.get('seller_id', e.get('from'))} 제안 {int(p.get('price') or 0):,}원 (라운드 {p.get('round')})")
            elif t == "ACCEPT":
                inbox.note(po_id, f"수락 → {int(p.get('price') or 0):,}원")
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/odoo/pull")
def odoo_pull() -> dict:
    """Odoo 구매 초안(PO)에서 미처리 RFQ 1건을 꺼내 협상하고 결과를 그 PO 에 기록."""
    if not odoo_sync.sync_enabled():
        raise HTTPException(409, "ODOO_SYNC off 또는 Odoo 미설정")
    inbox = odoo_sync.PurchaseInbox()
    rfq = inbox.next_new_rfq()
    if not rfq:
        return {"message": "새 RFQ 없음"}
    if rfq["item"] not in _ITEM_VALUES:
        raise HTTPException(422, f"품목명이 카탈로그와 불일치: {rfq['item']!r} (Odoo product 이름을 {sorted(_ITEM_VALUES)} 중 하나로)")

    result = _call_broker({
        "item": rfq["item"], "qty": rfq["qty"], "cap_price": rfq["cap_price"],
        "spec": rfq["spec"], "max_lead_time_days": 999, "priority": rfq["priority"],
        "seller_trust_min": 0, "seller_endpoints": SELLER_ENDPOINTS,
    })
    txid = result.get("txid", "")
    inbox.claim(rfq["po_id"], txid)
    _replay_log_to_po(inbox, rfq["po_id"], txid)
    inbox.outcome(rfq["po_id"], result.get("status", ""), result.get("seller_id", ""), int(result.get("price") or 0))
    return {"po_id": rfq["po_id"], "rfq": rfq, "result": result}


def _poller() -> None:
    while True:
        time.sleep(POLL_SECONDS)
        try:
            if odoo_sync.sync_enabled():
                odoo_pull()
        except HTTPException:
            pass
        except Exception:  # noqa: BLE001
            pass


if POLL_SECONDS > 0:
    threading.Thread(target=_poller, name="odoo-poller", daemon=True).start()

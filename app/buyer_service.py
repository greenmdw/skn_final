"""
Buyer 서비스 (v5 분산 구조) — Buyer EC2에서 포트 8000으로 실행.

기존 app.main(목업 화면 + Odoo 라우터 + 로컬 협상 엔드포인트)을 그대로 쓰고,
분산용 엔드포인트 하나만 얹는다:

  POST /api/request
    바디: BuyerRequest (+ 선택: seller_endpoints)
    동작: 중앙 브로커의 /api/negotiate/start 로 네트워크 전달
    응답: 브로커가 돌려준 최종 결과 그대로

BROKER_URL 환경변수로 브로커 위치를 지정한다 (예: http://10.0.1.13:9000).
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from pydantic import BaseModel

from .main import app  # 목업 + Odoo + 로컬 엔드포인트 재사용
from .net import HttpCallError, post_json
from .schemas import BuyerRequest

BROKER_URL = os.environ.get("BROKER_URL", "http://localhost:9000")
SELLER_ENDPOINTS = [e.strip() for e in os.environ.get("SELLER_ENDPOINTS", "").split(",") if e.strip()]


class DistributedRequest(BuyerRequest):
    seller_endpoints: list[str] = []


@app.post("/api/request")
def distributed_request(req: DistributedRequest) -> dict:
    endpoints = req.seller_endpoints or SELLER_ENDPOINTS
    body = {
        "item": req.item.value if hasattr(req.item, "value") else req.item,
        "qty": req.qty,
        "cap_price": req.cap_price,
        "spec": req.spec,
        "max_lead_time_days": req.max_lead_time_days,
        "priority": req.priority,
        "seller_trust_min": req.seller_trust_min,
        "seller_endpoints": endpoints,
    }
    try:
        code, resp = post_json(f"{BROKER_URL.rstrip('/')}/api/negotiate/start", body, timeout=60.0)
    except HttpCallError as exc:
        raise HTTPException(502, f"브로커 호출 실패: {exc.detail}")
    if code >= 400:
        raise HTTPException(code, detail=resp)
    return resp

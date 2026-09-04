"""
중앙 브로커 서비스 (v5 분산 구조) — 별도 EC2에서 포트 9000으로 실행. Odoo 없음.

역할: buyer 요청을 받아 각 seller_endpoint 에 라운드마다 POST /api/offer 로 물어보고,
      바이어(자기 cap_price)를 대신해 수락/거절을 판정한 뒤 최종 결과를 돌려준다.
      * cap_price 는 절대 셀러에게 전달하지 않는다.
      * 브로커는 floor_price 를 애초에 받지 않으므로 브로커 로그에는 floor 가 없다.

판단 로직 재사용: agents.RuleBasedBuyerAgent / llm_agents.OpenAIBuyerAgent, audit.audit_buyer_accept,
                 spec_match.extract_spec_tags / score_match.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agents import RuleBasedBuyerAgent
from .audit import audit_buyer_accept
from .net import HttpCallError, post_json
from .schemas import BuyerRequest, Envelope, MsgType, new_txid
from .spec_match import extract_spec_tags, score_match

MAX_ROUNDS = int(os.environ.get("BROKER_MAX_ROUNDS", "3"))
BROKER_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "broker_logs"
BROKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 기본 셀러 목록 (요청에서 seller_endpoints 를 안 주면 이걸 쓴다)
_DEFAULT_ENDPOINTS = [e.strip() for e in os.environ.get("SELLER_ENDPOINTS", "").split(",") if e.strip()]


def _build_buyer_agent():
    if os.environ.get("NEGOTIATOR_MODE", "rule").lower() == "llm":
        from .llm_agents import OpenAIBuyerAgent
        return OpenAIBuyerAgent()
    return RuleBasedBuyerAgent()


_buyer_agent = _build_buyer_agent()

app = FastAPI(title="Broker Service (v5 분산)")


class NegotiateStartRequest(BaseModel):
    item: str
    qty: int
    cap_price: int
    spec: str = ""
    max_lead_time_days: int = 999
    priority: str = "price_min"
    seller_trust_min: int = 0
    seller_endpoints: list[str] = []


def _log_path(txid: str) -> Path:
    return BROKER_LOG_DIR / f"{txid}.jsonl"


def _log(txid: str, frm: str, to: str, mtype: MsgType, payload: dict) -> None:
    env = Envelope(**{"from": frm, "to": to, "type": mtype, "txid": txid, "payload": payload})
    with _log_path(txid).open("a", encoding="utf-8") as f:
        f.write(env.model_dump_json(by_alias=True) + "\n")


def _notify_settle(endpoints: list[str], txid: str, status: str, winner_ep: str | None, price: int) -> None:
    """협상 종료를 참여 셀러에 통지 (Odoo 미러 낙찰/탈락 표시용). best-effort."""
    for ep in endpoints:
        body = {"txid": txid, "status": status, "won": ep == winner_ep, "price": price}
        try:
            post_json(f"{ep.rstrip('/')}/api/settle", body, timeout=5.0)
        except HttpCallError:
            pass


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "broker", "default_sellers": _DEFAULT_ENDPOINTS, "max_rounds": MAX_ROUNDS}


@app.get("/api/negotiate/{txid}/log")
def get_log(txid: str) -> dict:
    path = _log_path(txid)
    if not path.exists():
        raise HTTPException(404, "해당 txid의 브로커 로그가 없습니다")
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    import json
    return {"txid": txid, "log": [json.loads(l) for l in lines]}


@app.post("/api/negotiate/start")
def negotiate_start(req: NegotiateStartRequest) -> dict:
    txid = new_txid()
    endpoints = req.seller_endpoints or _DEFAULT_ENDPOINTS
    if not endpoints:
        raise HTTPException(400, "seller_endpoints 가 비어 있습니다 (요청 바디 또는 SELLER_ENDPOINTS 환경변수)")

    buyer_tags = extract_spec_tags(req.spec)
    buyer_req = BuyerRequest(
        item=req.item, qty=req.qty, cap_price=req.cap_price, spec=req.spec,
        max_lead_time_days=req.max_lead_time_days, seller_trust_min=req.seller_trust_min,
        priority=req.priority,
    )
    _log(txid, "buyer", "*", MsgType.REQUEST, {
        "item": req.item, "qty": req.qty, "spec": req.spec, "spec_tags": buyer_tags,
        "max_lead_time_days": req.max_lead_time_days, "priority": req.priority,
        "seller_endpoints": endpoints,
        # cap_price 는 공개 로그에 남기지 않는다 (바이어 내부 정보)
    })

    # 엔드포인트별 상태
    state: dict[str, dict] = {ep: {"status": "active", "last_reject": None, "info": {}} for ep in endpoints}
    accepted: list[dict] = []
    any_offer = False

    for round_no in range(1, MAX_ROUNDS + 1):
        for ep in endpoints:
            st = state[ep]
            if st["status"] != "active":
                continue
            body = {
                "txid": txid, "item": req.item, "qty": req.qty, "spec": req.spec,
                "max_lead_time_days": req.max_lead_time_days, "round_no": round_no,
                "last_reject_price": st["last_reject"], "max_rounds": MAX_ROUNDS,
                "seller_trust_min": req.seller_trust_min,
            }
            _log(txid, "broker", ep, MsgType.REQUEST, {"round": round_no, "endpoint": ep})
            try:
                code, resp = post_json(f"{ep.rstrip('/')}/api/offer", body, timeout=10.0)
            except HttpCallError as exc:
                st["status"] = "screened"
                _log(txid, ep, "broker", MsgType.REJECT, {"round": round_no, "reason": f"연결 실패: {exc.detail}"})
                continue
            if code != 200 or not isinstance(resp, dict):
                st["status"] = "screened"
                _log(txid, ep, "broker", MsgType.REJECT, {"round": round_no, "reason": f"HTTP {code}"})
                continue

            price = int(resp.get("price", 0))
            message = str(resp.get("message", ""))
            available = bool(resp.get("available", True))
            spec_score = float(resp.get("spec_score", 0.0))
            seller_id = str(resp.get("seller_id") or ep)
            st["info"] = {
                "seller_id": seller_id, "spec_score": spec_score,
                "trust_score": int(resp.get("trust_score", 100)),
                "payment_terms": resp.get("payment_terms", ""),
                "delivery_terms": resp.get("delivery_terms", ""),
            }
            _log(txid, ep, "broker", MsgType.OFFER, {
                "round": round_no, "price": price if available else None,
                "available": available, "message": message,
                "spec_score": spec_score, "seller_id": seller_id,
                "reason": resp.get("reason"),
            })
            if not available:
                st["status"] = "screened"
                continue
            any_offer = True

            # 바이어(브로커가 대행) 판정 — cap_price 는 여기서만 쓴다
            raw_accept, buyer_msg = _buyer_agent.decide(buyer_req, price, message)
            accept, audit_note = audit_buyer_accept(raw_accept, price, req.cap_price)
            if accept:
                st["status"] = "accepted"
                accepted.append({"endpoint": ep, "price": price, **st["info"]})
                _log(txid, "broker", ep, MsgType.ACCEPT, {
                    "round": round_no, "price": price, "message": buyer_msg,
                    "audit_note": audit_note,
                })
            else:
                st["last_reject"] = price
                _log(txid, "broker", ep, MsgType.REJECT, {
                    "round": round_no, "price": price, "message": buyer_msg, "audit_note": audit_note,
                })

        if all(s["status"] != "active" for s in state.values()):
            break

    participated = [ep for ep, s in state.items() if s["info"]]

    # 결과 판정
    if not any_offer:
        result = {"txid": txid, "status": "FAILED", "fail_type": "NO_MATCH",
                  "reason": "조건을 만족하는 셀러가 없습니다."}
        _log(txid, "broker", "*", MsgType.SETTLED, {"status": "NO_MATCH"})
        return result
    if not accepted:
        result = {"txid": txid, "status": "FAILED", "fail_type": "NO_DEAL",
                  "reason": "셀러 제안은 있었으나 라운드 상한 내 가격 합의 실패."}
        _log(txid, "broker", "*", MsgType.SETTLED, {"status": "NO_DEAL"})
        _notify_settle(participated, txid, "NO_DEAL", None, 0)
        return result

    if req.priority == "spec_max":
        win = max(accepted, key=lambda a: (a["spec_score"], -a["price"]))
    else:
        win = min(accepted, key=lambda a: (a["price"], -a["spec_score"]))

    _notify_settle(participated, txid, "SETTLED", win["endpoint"], win["price"])
    _log(txid, "broker", "*", MsgType.SETTLED, {
        "status": "SETTLED", "seller_id": win["seller_id"], "endpoint": win["endpoint"],
        "price": win["price"], "priority": req.priority, "spec_score": win["spec_score"],
        "payment_terms": win["payment_terms"], "delivery_terms": win["delivery_terms"],
    })
    return {
        "txid": txid, "status": "SETTLED",
        "seller_id": win["seller_id"], "endpoint": win["endpoint"],
        "item": req.item, "qty": req.qty, "price": win["price"],
        "spec_score": win["spec_score"], "priority": req.priority,
        "payment_terms": win["payment_terms"], "delivery_terms": win["delivery_terms"],
        "approval": "PENDING",
    }

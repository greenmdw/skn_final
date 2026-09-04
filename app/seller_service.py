"""
Seller 서비스 (v5 분산 구조) — Seller1·Seller2 EC2에서 포트 8000으로 실행.

한 EC2 = 한 판매사. 이 서비스는 자기 회사의 offer_price/floor_price/재고를 안다.
  - floor_price 는 절대 응답에 넣지 않는다 (정보 경계 원칙).
  - 셀러 측 감사(자기 floor_price 위반 여부)는 응답 전에 여기서 수행한다.

판단 로직은 기존 것을 그대로 재사용한다:
  agents.RuleBasedSellerAgent / llm_agents.OpenAISellerAgent  (NEGOTIATOR_MODE 로 전환)
  audit.audit_seller_offer, pricing.apply_bulk_discount,
  spec_match.extract_spec_tags / score_match
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from .agents import RuleBasedSellerAgent
from .audit import audit_seller_offer
from .integrations.odoo import sync as odoo_sync
from .integrations.odoo.router import router as odoo_router
from .pricing import SPEC_MATCH_MIN, apply_bulk_discount
from .schemas import Envelope, Item, MsgType, SellerRegister
from .spec_match import extract_spec_tags, score_match

SELLER_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "seller_logs"
SELLER_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_ROUNDS = 3


def _seller_from_env() -> SellerRegister:
    """이 EC2가 대표하는 판매사 프로필. .env 의 SELLER_* 로 채운다."""
    return SellerRegister(
        seller_id=os.environ.get("SELLER_ID", "셀러"),
        item=Item(os.environ.get("SELLER_ITEM", "NVIDIA L40S")),
        qty=int(os.environ.get("SELLER_QTY", "20")),
        offer_price=int(os.environ.get("SELLER_OFFER_PRICE", "11500000")),
        floor_price=int(os.environ.get("SELLER_FLOOR_PRICE", "9900000")),
        description=os.environ.get("SELLER_DESCRIPTION", ""),
        lead_time_days=int(os.environ.get("SELLER_LEAD_TIME_DAYS", "30")),
        moq=int(os.environ.get("SELLER_MOQ", "1")),
        buyer_trust_required=int(os.environ.get("SELLER_BUYER_TRUST_REQUIRED", "0")),
        trust_score=int(os.environ.get("SELLER_TRUST_SCORE", "100")),
        payment_terms=os.environ.get("SELLER_PAYMENT_TERMS", ""),
        delivery_terms=os.environ.get("SELLER_DELIVERY_TERMS", ""),
        bulk_discount_rate=float(os.environ.get("SELLER_BULK_DISCOUNT_RATE", "0") or 0),
        bulk_discount_min_qty=int(os.environ.get("SELLER_BULK_DISCOUNT_MIN_QTY", "0") or 0),
    )


def _build_seller_agent():
    if os.environ.get("NEGOTIATOR_MODE", "rule").lower() == "llm":
        from .llm_agents import OpenAISellerAgent
        return OpenAISellerAgent()
    return RuleBasedSellerAgent()


class OfferRequest(BaseModel):
    txid: str
    item: str
    qty: int
    spec: str = ""
    max_lead_time_days: int = 999
    round_no: int = 1
    last_reject_price: int | None = None
    max_rounds: int = DEFAULT_MAX_ROUNDS          # 계약 확장(비밀 아님): 양보곡선 t 계산용
    seller_trust_min: int = 0                     # 계약 확장: 브로커가 바이어 요구 신뢰도를 전달


class OfferResponse(BaseModel):
    price: int
    message: str
    # ↓ 계약 확장 필드 (floor_price 등 비밀은 절대 포함하지 않음)
    available: bool = True
    reason: str | None = None
    seller_id: str = ""
    spec_score: float = 0.0
    trust_score: int = 100
    payment_terms: str = ""
    delivery_terms: str = ""


def _seller_log(txid: str, env: Envelope) -> None:
    with (SELLER_LOG_DIR / f"{txid}.jsonl").open("a", encoding="utf-8") as f:
        f.write(env.model_dump_json(by_alias=True) + "\n")


# ── Odoo 미러 (A 방식) — 전부 best-effort, 협상 경로엔 영향 없음 ──

def _mirror_offer(req: "OfferRequest", price: int, message: str, disc: dict | None) -> None:
    try:
        m = odoo_sync.SalesMirror()
        m.ensure_quote(req.txid, req.item, req.qty, req.spec)
        tail = f" (대량할인 {int(disc['rate'] * 100)}%)" if disc else ""
        m.note(req.txid, f"라운드 {req.round_no}: {price:,}원 제안 — {message}{tail}")
    except Exception:  # noqa: BLE001
        pass


def _mirror_settle(txid: str, won: bool, price: int) -> None:
    try:
        odoo_sync.SalesMirror().outcome(txid, won, price)
    except Exception:  # noqa: BLE001
        pass


class SettleNotice(BaseModel):
    txid: str
    status: str = "SETTLED"
    won: bool = False
    price: int = 0


def create_app(profile: SellerRegister | None = None) -> FastAPI:
    """판매사 프로필 하나를 대표하는 Seller 서비스 앱. uvicorn 은 모듈 전역 `app` 을 쓴다."""
    prof = profile or _seller_from_env()
    if not prof.spec_tags:
        prof = prof.model_copy(update={"spec_tags": extract_spec_tags(prof.description)})
    state = {"profile": prof, "agent": _build_seller_agent()}

    svc = FastAPI(title="Seller Service (v5 분산)")
    svc.include_router(odoo_router)

    @svc.get("/health")
    def health() -> dict:
        s = state["profile"]
        return {"ok": True, "service": "seller", "seller_id": s.seller_id, "item": s.item.value}

    @svc.post("/api/seller/config")
    def set_config(new_profile: SellerRegister) -> dict:
        tags = new_profile.spec_tags or extract_spec_tags(new_profile.description)
        state["profile"] = new_profile.model_copy(update={"spec_tags": tags})
        return {"ok": True, "seller_id": state["profile"].seller_id}

    @svc.post("/api/dev/seed-odoo")
    def seed_odoo() -> dict:
        return odoo_sync.seed("seller")

    @svc.post("/api/settle")
    def settle(notice: SettleNotice, background: BackgroundTasks) -> dict:
        """브로커가 협상 종료 시 각 셀러에 통지 → Odoo 견적에 낙찰/탈락 기록."""
        if odoo_sync.sync_enabled():
            background.add_task(_mirror_settle, notice.txid, notice.won, notice.price)
        return {"ok": True}

    @svc.post("/api/offer", response_model=OfferResponse)
    def make_offer(req: OfferRequest, background: BackgroundTasks) -> OfferResponse:
        s: SellerRegister = state["profile"]

        # 1. 자기 스크리닝 (품목·재고·납기·MOQ·신뢰도·사양) — floor 는 안 씀
        reasons: list[str] = []
        if req.item != s.item.value:
            reasons.append(f"품목 불일치({req.item} != {s.item.value})")
        if s.qty < req.qty:
            reasons.append("재고 부족")
        if s.lead_time_days > req.max_lead_time_days:
            reasons.append("납기 초과")
        if req.qty < s.moq:
            reasons.append("최소주문수량 미달")
        if s.trust_score < req.seller_trust_min:
            reasons.append("셀러 신뢰도 미달")
        spec_score, _ = score_match(extract_spec_tags(req.spec), s.spec_tags)
        if spec_score < SPEC_MATCH_MIN:
            reasons.append(f"사양 유사도 미달({spec_score:.2f})")

        if reasons:
            _seller_log(req.txid, Envelope(**{
                "from": s.seller_id, "to": "broker", "type": MsgType.REJECT, "txid": req.txid,
                "payload": {"stage": "screening", "reason": ", ".join(reasons), "round": req.round_no},
            }))
            return OfferResponse(
                price=0, message="이번 요청은 공급 불가: " + ", ".join(reasons),
                available=False, reason=", ".join(reasons),
                seller_id=s.seller_id, spec_score=spec_score, trust_score=s.trust_score,
            )

        # 2. 가격 산출 (양보곡선). buyer_cap_price 는 전달받지 않으므로 0(미공개)로 넘긴다.
        raw_price, msg = state["agent"].decide(s, req.round_no, 0, req.last_reject_price, req.max_rounds)

        # 3. 셀러 측 감사 — 자기 floor_price 위반이면 응답 전에 보정
        priced, audit_note = audit_seller_offer(raw_price, s.floor_price)

        # 4. 대량구매할인 — 수량 기준으로 셀러 내부에서 적용
        final_price, disc = apply_bulk_discount(s, req.qty, priced)

        # 로컬 로그 (셀러 자기 EC2 — floor 남겨도 됨)
        _seller_log(req.txid, Envelope(**{
            "from": s.seller_id, "to": "broker", "type": MsgType.OFFER, "txid": req.txid,
            "payload": {
                "round": req.round_no, "price": final_price, "raw_price": raw_price,
                "floor_price": s.floor_price, "audit_note": audit_note,
                "bulk_discount": disc, "spec_score": spec_score,
            },
        }))

        if odoo_sync.sync_enabled():
            background.add_task(_mirror_offer, req, final_price, msg, disc)

        return OfferResponse(
            price=final_price,
            message=msg + (f" (대량할인 {int(disc['rate'] * 100)}%)" if disc else ""),
            available=True, seller_id=s.seller_id,
            spec_score=spec_score, trust_score=s.trust_score,
            payment_terms=s.payment_terms, delivery_terms=s.delivery_terms,
        )

    return svc


app = create_app()

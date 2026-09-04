"""
L3 — 중앙 서버 매칭 + 바로구매 성사
지난 리뷰에서 지적된 "협상 라운드 상한 없으면 REJECT<->OFFER 무한루프 위험"을
MAX_ROUNDS로 반영했다. 초과 시 해당 셀러는 자동으로 결렬 처리한다.

[v3 확정안 반영]
- 매칭 조건에 사양·납기 추가 (기존엔 수량만 체크)
- 조건 미달 셀러는 협상 라운드에 들어가지도 못하고 "제외" 사유가 로그에 남는다
  (v3가 "룰로도 걸러지는 감사 검증"이라 명시한 지점 — 재고초과/납기초과 주장을 사전 차단)
- 실패를 2종류로 구분: NO_MATCH(조건 맞는 셀러 자체 없음) / NO_DEAL(협상은 했으나 결렬)

에이전트 구현체는 NEGOTIATOR_MODE 환경변수로 전환된다:
  - "rule" (기본값): RuleBasedSellerAgent/RuleBasedBuyerAgent — API 비용 없음
  - "llm": OpenAISellerAgent/OpenAIBuyerAgent — OPENAI_API_KEY 필요
어느 쪽이든 SellerAgentPort/BuyerAgentPort 인터페이스가 같아서 이 파일의
나머지 로직(라운드 진행, 로그 적재, 최저가 채택)은 전혀 안 바뀐다.
"""

from __future__ import annotations
import os
from .schemas import Envelope, MsgType, BuyerRequest, SellerRegister, new_txid
from .agents import RuleBasedSellerAgent, RuleBasedBuyerAgent, SellerAgentPort, BuyerAgentPort
from .audit import audit_seller_offer, audit_buyer_accept
from .store import CentralStore
from .spec_match import extract_spec_tags, score_match
from .pricing import SPEC_MATCH_MIN, apply_bulk_discount as _apply_bulk_discount

MAX_ROUNDS = 3  # 하한선: 이 이상 왕복해도 안 맞으면 결렬 (무한루프 방지)


def _build_agents() -> tuple[SellerAgentPort, BuyerAgentPort]:
    mode = os.environ.get("NEGOTIATOR_MODE", "rule").lower()
    if mode == "llm":
        from .llm_agents import OpenAISellerAgent, OpenAIBuyerAgent  # 필요할 때만 임포트(키 없어도 rule 모드는 동작)
        return OpenAISellerAgent(), OpenAIBuyerAgent()
    return RuleBasedSellerAgent(), RuleBasedBuyerAgent()


def _screen_candidates(
    store: CentralStore, txid: str, request: BuyerRequest, buyer_tags: dict
) -> list[tuple[SellerRegister, float]]:
    """
    1차 스크리닝 — 협상 이전에 재고·납기·MOQ·신뢰도를 룰로 검사하고, 사양은 유사도 점수를 매긴다.
    떨어진 셀러는 라운드에 들어가지 않고, 왜 떨어졌는지 로그에 즉시 남는다
    (v3: "재고 10대인데 100대 가능하다고 응답" 같은 할루시네이션을 룰로 사전 차단).
    반환: 통과한 (셀러, 사양_유사도) 목록.
    """
    passed: list[tuple[SellerRegister, float]] = []
    for seller in store.sellers_for(request.item):
        reasons = []
        if seller.qty < request.qty:
            reasons.append(f"재고부족(보유 {seller.qty} < 요청 {request.qty})")
        spec_score, spec_detail = score_match(buyer_tags, seller.spec_tags)
        if spec_score < SPEC_MATCH_MIN:
            reasons.append(f"사양 유사도 미달({spec_score:.2f} < {SPEC_MATCH_MIN})")
        if seller.lead_time_days > request.max_lead_time_days:
            reasons.append(f"납기초과(제시 {seller.lead_time_days}일 > 허용 {request.max_lead_time_days}일)")
        if request.qty < seller.moq:
            reasons.append(f"최소주문수량 미달(요청 {request.qty} < MOQ {seller.moq})")
        if request.trust_score < seller.buyer_trust_required:
            reasons.append(f"바이어 신뢰도 부족(보유 {request.trust_score} < 요구 {seller.buyer_trust_required})")
        if seller.trust_score < request.seller_trust_min:
            reasons.append(f"셀러 신뢰도 부족(보유 {seller.trust_score} < 요구 {request.seller_trust_min})")

        if reasons:
            store.append(Envelope(**{
                "from": "central", "to": seller.seller_id, "type": MsgType.REJECT, "txid": txid,
                "payload": {"stage": "screening", "reason": ", ".join(reasons),
                            "spec_score": spec_score, "spec_detail": spec_detail},
            }))
        else:
            passed.append((seller, spec_score))
    return passed


def run_negotiation(store: CentralStore, request: BuyerRequest) -> dict:
    txid = new_txid()
    seller_agent, buyer_agent = _build_agents()

    # 0. 바이어 요구 사양을 구조화 태그로 추출 (LLM 또는 정규식 폴백, 캐시됨)
    buyer_tags = extract_spec_tags(request.spec)

    # 1. REQUEST 브로드캐스트
    store.append(Envelope(**{
        "from": "buyer", "to": "*", "type": MsgType.REQUEST, "txid": txid,
        "payload": {
            "item": request.item, "qty": request.qty, "cap_price": request.cap_price,
            "spec": request.spec, "spec_tags": buyer_tags,
            "max_lead_time_days": request.max_lead_time_days,
            "priority": request.priority,
        },
    }))

    # 2. 1차 스크리닝 (재고·납기·MOQ·신뢰도 룰 + 사양 유사도) — 통과 못 하면 라운드 자체에 안 들어감
    candidates = _screen_candidates(store, txid, request, buyer_tags)
    spec_scores: dict[str, float] = {s.seller_id: sc for s, sc in candidates}

    if not candidates:
        summary = {
            "txid": txid, "status": "FAILED", "fail_type": "NO_MATCH",
            "item": request.item, "qty": request.qty,
            "reason": "조건(재고·납기·MOQ·신뢰도·사양 유사도)을 만족하는 판매자가 없습니다. 조건 완화가 필요합니다.",
        }
        store.set_deal(txid, summary)
        return summary

    # 3. 스크리닝 통과 셀러끼리 가격 협상
    accepted: list[tuple[SellerRegister, int]] = []

    for seller, spec_score in candidates:
        last_reject_price: int | None = None
        for round_no in range(1, MAX_ROUNDS + 1):
            raw_price, seller_msg = seller_agent.decide(
                seller, round_no, request.cap_price, last_reject_price, MAX_ROUNDS
            )
            price, seller_audit_note = audit_seller_offer(raw_price, seller.floor_price)

            offer_payload = {"price": price, "round": round_no, "message": seller_msg, "spec_score": spec_score}
            if seller_audit_note:
                offer_payload["audit_note"] = seller_audit_note
            store.append(Envelope(**{
                "from": seller.seller_id, "to": "buyer", "type": MsgType.OFFER, "txid": txid,
                "payload": offer_payload,
            }))

            raw_accept, buyer_msg = buyer_agent.decide(request, price, seller_msg)
            accept, buyer_audit_note = audit_buyer_accept(raw_accept, price, request.cap_price)

            if accept:
                final_price, disc_note = _apply_bulk_discount(seller, request.qty, price)
                accept_payload = {"price": final_price, "agreed_price": price, "message": buyer_msg}
                if disc_note:
                    accept_payload["bulk_discount"] = disc_note
                if buyer_audit_note:
                    accept_payload["audit_note"] = buyer_audit_note
                store.append(Envelope(**{
                    "from": "buyer", "to": seller.seller_id, "type": MsgType.ACCEPT, "txid": txid,
                    "payload": accept_payload,
                }))
                accepted.append((seller, final_price))
                break
            else:
                reject_payload = {"reason": "상한가 초과", "cap_price": request.cap_price, "message": buyer_msg}
                if buyer_audit_note:
                    reject_payload["audit_note"] = buyer_audit_note
                store.append(Envelope(**{
                    "from": "buyer", "to": seller.seller_id, "type": MsgType.REJECT, "txid": txid,
                    "payload": reject_payload,
                }))
                last_reject_price = price
                # 하한선: 라운드 상한 도달 시 이 셀러는 자동 결렬 (재시도 없음)

    if not accepted:
        summary = {
            "txid": txid, "status": "FAILED", "fail_type": "NO_DEAL",
            "item": request.item, "qty": request.qty,
            "reason": "조건에 맞는 판매자는 있었으나, 라운드 상한 내 가격 합의에 실패했습니다.",
        }
        store.set_deal(txid, summary)
        return summary

    # 낙찰 — 바이어가 사전 선택한 우선순위(§2-2)에 따라:
    #   price_min : 최저가 우선 (동가면 사양 유사도 높은 쪽)
    #   spec_max  : 사양 유사도 우선 (동점이면 저가 쪽)
    if request.priority == "spec_max":
        winner, price = max(
            accepted, key=lambda sp: (spec_scores.get(sp[0].seller_id, 0.0), -sp[1])
        )
    else:
        winner, price = min(
            accepted, key=lambda sp: (sp[1], -spec_scores.get(sp[0].seller_id, 0.0))
        )

    store.append(Envelope(**{
        "from": "central", "to": "*", "type": MsgType.SETTLED, "txid": txid,
        "payload": {"seller_id": winner.seller_id, "price": price,
                    "priority": request.priority,
                    "spec_score": spec_scores.get(winner.seller_id, 0.0),
                    "payment_terms": winner.payment_terms,
                    "delivery_terms": winner.delivery_terms},
    }))

    summary = {
        "txid": txid,
        "status": "SETTLED",
        "seller_id": winner.seller_id,
        "item": request.item,
        "qty": request.qty,
        "price": price,
        "approval": "PENDING",  # L4에서 사람이 바꾼다
    }
    store.set_deal(txid, summary)
    return summary
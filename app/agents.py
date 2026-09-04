"""
L2 — 에이전트 판단 로직
규칙 기반(RuleBased*)과 LLM 기반(llm_agents.py)이 같은 인터페이스(SellerAgentPort/
BuyerAgentPort)를 만족하도록 만들어서, negotiate.py는 어느 쪽을 쓰는지 몰라도 되게 한다.

셀러 가격 로직: Boulware/Conceder 시간(라운드)기반 양보곡선 + 재고 기반 E값.
  price(t) = P0 - (P0 - Pfloor) * t^(1/e)    (t = 경과 라운드 비율 0~1)
  e < 1 → Boulware(마감 직전까지 버팀), e > 1 → Conceder(초반부터 빠르게 양보)
  e 는 재고로 정한다: 재고가 많을수록 빨리 팔고 싶으므로 Conceder(e>1),
  재고가 적으면 희소하므로 버틴다(e<1).
  (상수는 강화학습_감사자_기술대안.md §1-5의 1000/(재고+50) 논의를 참고한 값이며
   아직 검증되지 않았다 — 추후 ES/튜닝 대상.)
"""

from __future__ import annotations
from typing import Protocol
from .schemas import SellerRegister, BuyerRequest


class SellerAgentPort(Protocol):
    def decide(
        self,
        offer: SellerRegister,
        round_no: int,
        buyer_cap_price: int,
        last_reject_price: int | None,
        max_rounds: int,
    ) -> tuple[int, str]:
        """(제시가, 협상 메시지)를 반환."""
        ...


class BuyerAgentPort(Protocol):
    def decide(self, request: BuyerRequest, offer_price: int, seller_message: str) -> tuple[bool, str]:
        """(수락 여부, 협상 메시지)를 반환."""
        ...


def stock_based_e(qty: int) -> float:
    """재고 기반 E값. 재고 많음 → e>1 (Conceder), 재고 적음 → e<1 (Boulware). [0.2, 5]로 클램프."""
    e = (qty + 50) / 300.0
    return min(5.0, max(0.2, e))


def concession_price(offer: SellerRegister, round_no: int, max_rounds: int) -> int:
    """Boulware/Conceder 곡선. round_no 1..max_rounds, 최저수용가 밑으로는 절대 안 감."""
    span = max(max_rounds, 1)
    t = min(round_no, span) / span
    e = stock_based_e(offer.qty)
    price = offer.offer_price - (offer.offer_price - offer.floor_price) * (t ** (1.0 / e))
    return max(int(round(price)), offer.floor_price)


def _buyer_decide(request: BuyerRequest, offer_price: int) -> bool:
    """바이어 규칙: 제시가 <= 상한가 이면 ACCEPT 가능."""
    return offer_price <= request.cap_price


class RuleBasedSellerAgent:
    """LLM 없이 양보곡선 수식으로만 응답하는 구현. 감사자로 floor 위반을 한 번 더 검증한다."""

    def decide(
        self,
        offer: SellerRegister,
        round_no: int,
        buyer_cap_price: int,
        last_reject_price: int | None,
        max_rounds: int,
    ) -> tuple[int, str]:
        price = concession_price(offer, round_no, max_rounds)
        # 이미 상대가 거절한 가격보다 높게 다시 부르지 않는다 (곡선이 그럴 일은 거의 없지만 안전장치).
        if last_reject_price is not None and price >= last_reject_price:
            price = max(offer.floor_price, last_reject_price - 1)
        if round_no <= 1:
            message = f"{price}원에 제안합니다."
        else:
            message = f"{price}원으로 조정하여 다시 제안합니다."
        return price, message


class RuleBasedBuyerAgent:
    def decide(self, request: BuyerRequest, offer_price: int, seller_message: str) -> tuple[bool, str]:
        accept = _buyer_decide(request, offer_price)
        if accept:
            message = "제안을 수락합니다."
        else:
            message = f"상한가 {request.cap_price}원을 초과하여 거절합니다."
        return accept, message

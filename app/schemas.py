"""
L0 계약서 (코드화)
- 품목 스키마 5필드: 품목ID, 수량, 제시가, 셀러 최저수용가, 바이어 상한가
- 메시지 타입 5종: REQUEST, OFFER, ACCEPT, REJECT, SETTLED
- 메시지 봉투(envelope): from/to/type/txid/ts/payload
- LLM 어댑터 인터페이스: 지금은 템플릿 구현체, 나중에 파일 하나만 갈아끼우면 LLM으로 교체됨
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Protocol
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid


# ── 고정 품목 — 도메인: 그래픽카드(GPU) 제조업체 B2B (명세서 §1).
# 값은 app/seed_data/nvidia_gpu_corporate_deliveries.csv 의 "제품명"과 정확히 일치시킨다 (시드 재사용).
class Item(str, Enum):
    RTX_PRO_6000_Blackwell = "NVIDIA RTX PRO 6000 Blackwell"
    L40S = "NVIDIA L40S"
    H100_NVL = "NVIDIA H100 NVL"
    RTX_6000_Ada = "NVIDIA RTX 6000 Ada Generation"
    A100_80GB_PCIe = "NVIDIA A100 80GB PCIe"


class MsgType(str, Enum):
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    SETTLED = "SETTLED"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_txid() -> str:
    # TX-YYYYMMDD-XXXX 형식 (목업 예시와 동일한 규칙)
    today = datetime.now().strftime("%Y%m%d")
    return f"TX-{today}-{uuid.uuid4().hex[:4].upper()}"


class Envelope(BaseModel):
    """모든 메시지는 반드시 이 형태로만 오간다. 확장은 payload 안에서만 (5절 원칙)."""
    frm: str = Field(alias="from")
    to: str
    type: MsgType
    txid: str
    ts: str = Field(default_factory=now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ── 등록 시 입력 스키마 ──
# v3 확정안 D-02 반영: 사양·납기 필드 추가 (기존 5필드에서 확장)
class SellerRegister(BaseModel):
    seller_id: str            # "셀러 A" / "셀러 B"
    item: Item
    qty: int                  # 재고
    offer_price: int          # 제시가        (§2-1: 알고리즘 — Boulware/Conceder + 재고 E값)
    floor_price: int          # 최저 수용가    (§2-1: 알고리즘 대상, 바이어에게 노출 금지)
    description: str = ""      # 상품 상세설명  (§2-1: LLM + RAG 벡터화 대상)
    spec_tags: dict[str, Any] = Field(default_factory=dict)  # description에서 추출한 구조화 태그 (register 시 채워짐, RAG 인덱스 자리)
    lead_time_days: int = 0   # 납기일수       (§2-1: 룰베이스)
    moq: int = 1                    # 최소주문수량 — 요청 수량이 이 값 이상이어야 함 (§2-1: 룰베이스)
    buyer_trust_required: int = 0   # 이 셀러가 요구하는 바이어 최소 신뢰도(0~100) (§2-1: 룰베이스)
    trust_score: int = 100          # 이 셀러의 신뢰도 점수(0~100) — 바이어의 seller_trust_min과 비교
    payment_terms: str = ""         # 대금결제조건 (예: "선급 30% / 납품 후 70%") — 표시·기록용
    delivery_terms: str = ""        # 인도조건 (예: "DDP 매수인 창고", "FOB 부산") — 표시·기록용
    bulk_discount_rate: float = 0.0     # 대량구매할인률 0~1 (예: 0.05 = 5%)
    bulk_discount_min_qty: int = 0      # 이 수량 이상 주문 시 대량할인 적용 (0이면 비활성)


class BuyerRequest(BaseModel):
    item: Item
    qty: int                        # (§2-2: 룰베이스, 사람 입력)
    cap_price: int                  # 상한가 (§2-2: 알고리즘 대상)
    spec: str = ""                  # 요구 사양 (§2-2: LLM+RAG. 빈 문자열이면 사양 불문)
    max_lead_time_days: int = 999   # 허용 최대 납기일수 (§2-2: 룰베이스, 사람 입력. 기본값: 사실상 제한 없음)
    seller_trust_min: int = 0       # 요구하는 셀러 최소 신뢰도(0~100) (§2-2: 룰베이스, 사람 입력)
    trust_score: int = 100          # 이 바이어의 신뢰도 점수(0~100) — 셀러의 buyer_trust_required와 비교
    priority: str = "price_min"     # 협상 우선순위 (§2-2 사전 선택): "spec_max"(스펙우선) | "price_min"(가격우선)


# ── LLM 어댑터 인터페이스 (지금은 템플릿, 나중에 이 인터페이스만 만족하면 교체 가능) ──
class SummarizerPort(Protocol):
    def summarize(self, log: list[Envelope]) -> str:
        ...
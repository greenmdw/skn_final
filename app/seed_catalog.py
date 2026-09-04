"""
CSV(정가 이력) → 셀러 카탈로그 시드.

작업지시문 §2: CSV는 "실제 협상 로그"가 아니라 "이미 계약 끝난 납품 이력"이므로,
단가를 정가(참고 시세)로 놓고 ±10~15% 벌려서 셀러별 offer_price/floor_price를 만든다.

고정 시드(random.Random(20260905))라 실행할 때마다 같은 카탈로그가 나온다 (NFR-02 재현성).

실행:
    python -m app.seed_catalog            # data/mmvp.db 카탈로그를 비우고 다시 채움
    (또는 서버에서 POST /api/dev/seed)
"""

from __future__ import annotations
import csv
import random
from pathlib import Path

from .schemas import Item, SellerRegister
from .store import store

CSV_PATH = Path(__file__).resolve().parent / "seed_data" / "nvidia_gpu_corporate_deliveries.csv"

# 15시 기획안 표준 예시 셀러 3곳 (한 곳이 근거 부족으로 탈락하는 흐름 재현용)
SELLERS = ["한빛테크", "오퍼렛", "바이어드"]


def _load_models() -> dict[str, dict]:
    """CSV에서 모델별 정가·대표 스펙·수량 표본을 모은다."""
    models: dict[str, dict] = {}
    with CSV_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["제품명"]
            m = models.setdefault(name, {"price": int(row["단가(원)"]), "spec": row["스펙"], "qtys": []})
            m["qtys"].append(int(row["수량"]))
    return models


def seed(reset: bool = True, per_model: int = 3) -> int:
    rng = random.Random(20260905)
    if reset:
        store.clear_catalog()

    n = 0
    for name, info in _load_models().items():
        base = info["price"]
        for i in range(per_model):
            offer = round(base * rng.uniform(1.04, 1.15) / 10_000) * 10_000
            floor = round(base * rng.uniform(0.88, 0.98) / 10_000) * 10_000
            floor = max(min(floor, offer - 10_000), int(base * 0.85))
            store.register_seller(SellerRegister(
                seller_id=SELLERS[i % len(SELLERS)],
                item=Item(name),
                qty=rng.choice(info["qtys"]) + rng.randint(2, 12),
                offer_price=offer,
                floor_price=floor,
                description=info["spec"],
                lead_time_days=rng.choice([14, 20, 25, 30, 35, 45]),
                moq=rng.choice([1, 1, 2, 3]),
                buyer_trust_required=rng.choice([0, 0, 40, 60]),
                trust_score=rng.choice([70, 80, 90, 100]),
                payment_terms=rng.choice(["선급 30% / 납품 후 70%", "납품 후 30일 정산", "전액 선급"]),
                delivery_terms=rng.choice(["DDP 매수인 창고", "FOB 부산", "EXW 창고 출고"]),
                bulk_discount_rate=rng.choice([0.0, 0.0, 0.03, 0.05, 0.07]),
                bulk_discount_min_qty=rng.choice([0, 0, 5, 8, 10]),
            ))
            n += 1
    return n


if __name__ == "__main__":
    count = seed()
    print(f"seeded {count} sellers across {len(_load_models())} GPU models")
    for s in store.list_sellers():
        print(f"  {s.seller_id:8s} {s.item.value:32s} offer={s.offer_price:>10,} floor={s.floor_price:>10,} "
              f"qty={s.qty:3d} lead={s.lead_time_days:2d}d moq={s.moq} trust={s.trust_score}")

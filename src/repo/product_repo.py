"""catalog.* 저장소 — product / product_variant / product_category(_membership) /
product_fact / merchant / offer / offer_observation.

데모: 후보·가격은 합성 카탈로그(catalog_repo.py) 사용. 이 repo 는 최종에서
제휴 커머스 API + DB 조인으로 채운다. product_fact 는 검증 실행기의 규격 기준(§20).

"""
from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from src.db.base import Repo


class ProductRepo(Repo):
    def upsert_product(self, *, name: str, brand: str, model: str, product_type: str,
                       attributes: dict) -> UUID:
        row = self._one(
            "SELECT id FROM catalog.product WHERE brand = %s AND model = %s",
            (brand, model),
        )
        if row is not None:
            self._exec(
                "UPDATE catalog.product SET name=%s, product_type=%s, attributes=%s WHERE id=%s",
                (name, product_type, Jsonb(attributes), row["id"]),
            )
            return row["id"]
        row = self._one(
            """INSERT INTO catalog.product (name, brand, model, product_type, attributes)
            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (name, brand, model, product_type, Jsonb(attributes)),
        )
        return row["id"]

    def upsert_variant(self, product_id: UUID, variant_key: str, *, attributes: dict,
                       pack_quantity=1, gtin: str | None = None) -> UUID:
        row = self._one(
            """INSERT INTO catalog.product_variant (product_id, variant_key, attributes, pack_quantity, gtin)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (product_id, variant_key) DO UPDATE SET attributes = EXCLUDED.attributes
            RETURNING id""",
            (product_id, variant_key, Jsonb(attributes), pack_quantity, gtin),
        )
        return row["id"]

    def resolve_category_id(self, code: str, name: str | None = None) -> UUID:
        """catalog.product_category 코드로 get-or-create. 하나의 정식 카테고리만 반환."""
        row = self._one("SELECT id FROM catalog.product_category WHERE code = %s", (code,))
        if row is not None:
            return row["id"]
        row = self._one(
            "INSERT INTO catalog.product_category (code, name) VALUES (%s, %s) RETURNING id",
            (code, name or code),
        )
        return row["id"]

    def add_observation_if_changed(self, offer_id: UUID, *, source_id: UUID,
                                   observed_at, price, currency: str, stock_status: str,
                                   quality_status: str, pricing_terms: dict | None = None
                                   ) -> tuple[UUID, bool]:
        """가격/재고/상태가 동일하면 새 행을 만들지 않는다 — 과거 관측은 절대 덮어쓰지 않되,
        같은 관측 정체성(가격·통화·재고·상태)의 무의미한 중복도 만들지 않는다(CA01)."""
        latest = self.latest_observation(offer_id)
        same = (
            latest is not None
            and latest["stock_status"] == stock_status
            and latest["quality_status"] == quality_status
            and latest["currency"] == currency
            and (
                (latest["price"] is None and price is None)
                or (latest["price"] is not None and price is not None
                    and float(latest["price"]) == float(price))
            )
        )
        if same:
            return latest["id"], False
        row = self._one(
            """INSERT INTO catalog.offer_observation
              (offer_id, source_id, observed_at, price, currency, stock_status,
               quality_status, pricing_terms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (offer_id, source_id, observed_at, price, currency, stock_status,
             quality_status, Jsonb(pricing_terms or {})),
        )
        return row["id"], True

    def upsert_merchant(self, platform: str, external_seller_id: str, name: str) -> UUID:
        row = self._one(
            """INSERT INTO catalog.merchant (platform, external_seller_id, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (platform, external_seller_id) DO UPDATE SET name = EXCLUDED.name
            RETURNING id""",
            (platform, external_seller_id, name),
        )
        return row["id"]

    def upsert_offer(self, variant_id: UUID, merchant_id: UUID, external_offer_id: str,
                     purchase_url: str) -> UUID:
        row = self._one(
            """INSERT INTO catalog.offer (variant_id, merchant_id, external_offer_id, purchase_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (merchant_id, external_offer_id) DO UPDATE SET purchase_url = EXCLUDED.purchase_url
            RETURNING id""",
            (variant_id, merchant_id, external_offer_id, purchase_url),
        )
        return row["id"]

    def add_observation(self, offer_id: UUID, source_id: UUID, *, observed_at,
                        price, stock_status: str, quality_status: str,
                        pricing_terms: dict | None = None) -> UUID:
        """과거 행 불변. valid 면 price 필수."""
        row = self._one(
            """INSERT INTO catalog.offer_observation
              (offer_id, source_id, observed_at, price, stock_status, quality_status, pricing_terms)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (offer_id, source_id, observed_at, price, stock_status, quality_status,
             Jsonb(pricing_terms or {})),
        )
        return row["id"]

    def latest_observation(self, offer_id: UUID) -> dict | None:
        return self._one(
            """SELECT * FROM catalog.offer_observation
            WHERE offer_id = %s AND quality_status = 'valid'
            ORDER BY observed_at DESC LIMIT 1""",
            (offer_id,),
        )

    def variant_id_by_model(self, model: str, variant_key: str = "default") -> UUID | None:
        row = self._one(
            """SELECT v.id FROM catalog.product_variant v
            JOIN catalog.product p ON p.id = v.product_id
            WHERE p.model = %s AND v.variant_key = %s""",
            (model, variant_key),
        )
        return None if row is None else row["id"]

    def offer_observation_id_by_variant(self, variant_id: UUID) -> UUID | None:
        row = self._one(
            """SELECT obs.id FROM catalog.offer o
            JOIN LATERAL (
                SELECT id FROM catalog.offer_observation
                WHERE offer_id = o.id AND quality_status = 'valid'
                ORDER BY observed_at DESC LIMIT 1
            ) obs ON true
            WHERE o.variant_id = %s AND o.status = 'active' LIMIT 1""",
            (variant_id,),
        )
        return None if row is None else row["id"]

    def candidates_by_slot(self) -> dict[str, list[dict]]:
        """슬롯별 최신 유효가 후보. 기존 slot 속성과 새 PC product_type을 모두 읽는다."""
        from src.repo.catalog_repo import PC_TYPE_TO_SLOT
        rows = self._all(
            """
            SELECT v.id AS variant_id, p.id AS product_id, p.model AS product_key,
                   p.product_type,
                   p.name, p.brand, p.attributes, p.image_url,
                   o.purchase_url, obs.id AS offer_observation_id, obs.price
            FROM catalog.product_variant v
            JOIN catalog.product p ON p.id = v.product_id
            JOIN catalog.offer o ON o.variant_id = v.id AND o.status = 'active'
            JOIN LATERAL (
                SELECT id, price FROM catalog.offer_observation
                WHERE offer_id = o.id AND quality_status = 'valid'
                ORDER BY observed_at DESC LIMIT 1
            ) obs ON true
            """
        )
        out: dict[str, list[dict]] = {}
        for r in rows:
            slot = (r["attributes"] or {}).get("slot") or PC_TYPE_TO_SLOT.get(r["product_type"])
            if not slot:
                continue
            out.setdefault(slot, []).append(r)
        return out

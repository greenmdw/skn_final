"""The imported PC catalog must carry the exact DB identities into recommendations."""
from __future__ import annotations

from src.repo.catalog_repo import load_candidates_by_slot_from_db, pc_catalog_key


class _Cursor:
    def __init__(self):
        self.product_type = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _query, params):
        self.product_type = params["product_type"]

    def fetchall(self):
        if self.product_type != "cpu":
            return []
        return [{
            "id": "00000000-0000-0000-0000-000000000003",
            "variant_id": "00000000-0000-0000-0000-000000000001",
            "offer_observation_id": "00000000-0000-0000-0000-000000000002",
            "brand": "Test", "model": "Model", "price": 100000,
            "socket": "AM5", "tdp_w": 65, "memory_type": "DDR5",
        }]


class _Conn:
    def cursor(self, *, row_factory):
        assert row_factory is not None
        return _Cursor()


def test_db_candidate_keeps_variant_and_price_observation_ids():
    by_slot = load_candidates_by_slot_from_db(_Conn())
    candidate = by_slot["CPU"][0]
    assert candidate.variant_id == "00000000-0000-0000-0000-000000000001"
    assert candidate.offer_observation_id == "00000000-0000-0000-0000-000000000002"
    assert candidate.specs["socket"] == "AM5"


def test_pc_catalog_key_matches_review_remap_format():
    assert pc_catalog_key("cpu", "Intel", "Core i5-14400F") == "cpu:intel:core-i5-14400f"

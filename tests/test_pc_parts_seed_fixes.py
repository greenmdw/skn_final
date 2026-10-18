"""PC 부품 시드의 원본 보정(2026-10-16) — 엑셀 중복 행 3개를 적재하지 않고(이미 있으면 지우고),
VRAM 이 "8 / 16"으로 섞인 4060 Ti·5060 Ti 를 다나와 상품에 맞춰 8GB 로 고정한다.

일회용 DB(이름에 test 포함)와 비공개 시드(data/parts_list_modify.xlsx)가 필요하다."""
from __future__ import annotations

import importlib.util
import os
import uuid

import pytest

from src.config import ROOT

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    _spec = importlib.util.spec_from_file_location("seed_pc_parts_specs_under_test", ROOT / "db" / "seed_pc_parts_specs.py")
    seed = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(seed)
    from src.db import get_conn
    from src.repo import catalog_repo
    from src.repo.product_repo import ProductRepo


def _models(conn, model: str) -> int:
    return conn.execute("SELECT count(*) FROM catalog.product WHERE brand = 'NVIDIA' AND model = %s",
                        (model,)).fetchone()[0]


def test_duplicate_rows_are_not_loaded_and_the_kept_name_stays_once():
    with get_conn() as conn:
        for (_sheet, _brand, dropped), kept in seed._DUPLICATE_ROWS.items():
            assert _models(conn, dropped) == 0, dropped
            assert _models(conn, kept) == 1, kept


def test_mixed_vram_rows_are_fixed_to_the_8gb_board_the_price_belongs_to():
    with get_conn() as conn:
        gpus = {c.name: c for c in catalog_repo.load_candidates_by_slot_from_db(conn)["GPU"]}
        basis = conn.execute("""SELECT s.spec_basis FROM catalog.gpu_spec s JOIN catalog.product p ON p.id = s.product_id
                                WHERE p.model = 'NVIDIA RTX 6000 Ada Generation'""").fetchone()[0]
    assert gpus["NVIDIA GeForce RTX 4060 Ti"].specs["vram_gb"] == 8
    assert gpus["NVIDIA GeForce RTX 5060 Ti"].specs["vram_gb"] == 8
    assert basis == "NVIDIA 레퍼런스"                     # 지운 행을 가리키던 "행 13과 동일 모델"이 아니다


def _insert_product(conn, model: str):
    repo = ProductRepo(conn)
    product_id = repo.upsert_product(name=f"NVIDIA {model}", brand="NVIDIA", model=model,
                                     product_type="gpu", attributes={})
    conn.execute("INSERT INTO catalog.gpu_spec (product_id) VALUES (%s)", (product_id,))
    variant_id = repo.upsert_variant(product_id, "default", attributes={})
    merchant_id = repo.upsert_merchant("test", "seed-fix", "test")
    offer_id = repo.upsert_offer(variant_id, merchant_id, f"test:{model}", "https://example.com")
    source_id = conn.execute("INSERT INTO evidence.source (name, source_type) VALUES (%s, 'derived') RETURNING id",
                             (f"test-{uuid.uuid4()}",)).fetchone()[0]
    repo.add_observation_if_changed(offer_id, source_id=source_id, observed_at="2026-10-16T00:00:00Z", price=1000,
                                    currency="KRW", stock_status="available", quality_status="valid")
    return product_id, offer_id


def test_an_already_loaded_duplicate_is_deleted_on_reseed():
    model = f"TEST duplicate {uuid.uuid4()}"
    with get_conn() as conn:
        product_id, _ = _insert_product(conn, model)
        assert seed._delete_duplicate(conn, "NVIDIA", model, "gpu") == f"삭제: {model}"
        assert _models(conn, model) == 0
        assert conn.execute("SELECT count(*) FROM catalog.gpu_spec WHERE product_id = %s", (product_id,)).fetchone()[0] == 0
        assert seed._delete_duplicate(conn, "NVIDIA", model, "gpu") is None       # 두 번째 실행은 할 일이 없다


def test_a_referenced_duplicate_is_only_taken_off_sale():
    model = f"TEST referenced {uuid.uuid4()}"
    with get_conn() as conn:
        product_id, offer_id = _insert_product(conn, model)
        conn.execute("""INSERT INTO evidence.review_document (product_id, source_code, is_synthetic, body)
                        VALUES (%s, 'test', true, 'test')""", (product_id,))
        result = seed._delete_duplicate(conn, "NVIDIA", model, "gpu")
        assert result.startswith("참조가 있어 지우지 않고")
        assert _models(conn, model) == 1
        assert conn.execute("SELECT status FROM catalog.offer WHERE id = %s", (offer_id,)).fetchone()[0] == "expired"
        conn.execute("DELETE FROM evidence.review_document WHERE product_id = %s", (product_id,))
        assert seed._delete_duplicate(conn, "NVIDIA", model, "gpu") == f"삭제: {model}"

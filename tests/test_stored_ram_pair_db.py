"""RAM 2개 구성(정책 §2.5)의 저장·재검증·대안·교체 — 단품은 qty 2로 저장되고 호환 검사가 실제 모듈 수를 본다.
로컬 PostgreSQL + PC 카탈로그 seed 가 필요하다."""
from __future__ import annotations

import uuid

import pytest

from src.engine import ram_config
from src.engine.compat_parse import parse_module_count
from tests.test_reverify_after_swap import _recommend, conn  # noqa: F401  (fixture)

pytestmark = pytest.mark.db


def _ram_variants(conn):
    """(kit, single): 모듈 2개 키트와 낱개 하나씩 — 카탈로그 원본 후보."""
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    rams = [c for c in load_candidates_by_slot_from_db(conn)["RAM"] if c.specs.get("mem_type") == "DDR5"]
    kit = next(c for c in rams if parse_module_count(c.specs.get("module_config")) == 2)
    single = next(c for c in rams if parse_module_count(c.specs.get("module_config")) == 1)
    return kit, single


def _ram_item(result):
    return next(i for i in result["items"] if i["slot"] == "RAM")


def _ram_slots(result) -> dict:
    return next(r for r in result["compat_checks"] if r["axis"] == "ram_slots")


def test_engine_pick_is_saved_with_the_qty_of_its_two_module_config(conn):
    revision_id, result = _recommend(conn)
    ram = _ram_item(result)
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    by_variant = {c.variant_id: c for c in load_candidates_by_slot_from_db(conn)["RAM"]}
    catalog = by_variant[ram["product"]["variant_id"]]
    assert ram["qty"] == ram_config.pair_qty(catalog.specs) and ram["qty"] in (1, 2)
    # 화면 합계는 단가 × qty — 단품이면 구성 가격 전체가 합계에 들어간다.
    assert result["totals"]["selected_price"] == sum(i["price"] * i["qty"] for i in result["items"] if i["selected"])
    assert "2" in _ram_slots(result)["detail"]                        # 호환 검사는 실제 구매 구성(모듈 2개)을 본다


def test_swapping_ram_sets_qty_to_the_target_configuration(conn):
    revision_id, result = _recommend(conn)
    kit, single = _ram_variants(conn)
    item_id = uuid.UUID(_ram_item(result)["item_id"])

    from src.services import recommendation_service as rs
    swapped = rs.swap_item(conn, revision_id, item_id, uuid.UUID(single.variant_id))
    ram = _ram_item(swapped)
    assert ram["qty"] == 2                                              # 낱개는 2개 구성
    assert "모듈 2개" in _ram_slots(swapped)["detail"]                    # 모듈 1개로 보지 않는다

    back = rs.swap_item(conn, revision_id, item_id, uuid.UUID(kit.variant_id))
    assert _ram_item(back)["qty"] == 1                                  # 키트가 qty 2(모듈 4개)가 되지 않는다
    assert "모듈 2개" in _ram_slots(back)["detail"]


def test_user_changed_qty_is_seen_by_the_module_and_capacity_check(conn):
    revision_id, result = _recommend(conn)
    kit, _single = _ram_variants(conn)
    from src.services import recommendation_service as rs
    item_id = uuid.UUID(_ram_item(result)["item_id"])
    rs.swap_item(conn, revision_id, item_id, uuid.UUID(kit.variant_id))
    patched = rs.patch_item(conn, revision_id, item_id, selected=None, qty=2, timing=None)
    assert "모듈 4개" in _ram_slots(patched)["detail"]                    # 키트 2개 = 모듈 4개


def test_alternative_prices_and_deltas_are_per_two_module_configuration(conn):
    revision_id, result = _recommend(conn)
    from src.services import recommendation_service as rs
    ram = _ram_item(result)
    alts = rs.list_alternatives(conn, revision_id, uuid.UUID(ram["item_id"]))["items"]
    current = next(a for a in alts if a["current"])
    assert current["price"] == ram["price"] * ram["qty"] and current["qty"] == ram["qty"]
    from src.repo.catalog_repo import load_candidates_by_slot_from_db
    pool = {c.variant_id: c for c in load_candidates_by_slot_from_db(conn)["RAM"]}
    others = [a for a in alts if not a["current"]]
    assert others, "다른 후보가 있어야 한다"
    for a in others:
        qty = ram_config.pair_qty(pool[a["candidate_id"]].specs)
        assert qty is not None and a["qty"] == qty
        assert a["price_delta"] == a["price"] - current["price"]

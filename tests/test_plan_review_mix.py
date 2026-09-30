"""Review mix allocations use only verified real-review inventory."""

import csv
import json

import pytest

from scripts.plan_review_mix import build_plan, load_inventory, product_key


def _row(target: int) -> dict:
    return {
        "sheet": "CPU", "manufacturer": "Intel", "model": "Core i5-12400F",
        "planned_synthetic_reviews": target,
    }


def test_no_inventory_is_unknown_not_zero():
    plan = build_plan({"records": [_row(71)]})
    record = plan["records"][0]
    assert record["product_key"] == "cpu:intel:core-i5-12400f"
    assert record["target_total_even"] == 72
    assert record["real_reviews_needed_for_target"] == 36
    assert record["verified_real_available"] is None
    assert record["allocated_total"] is None


@pytest.mark.parametrize("available,expected", [(0, 0), (3, 6), (36, 72), (80, 72)])
def test_exact_product_parity_with_real_review_limit(available, expected):
    key = product_key(_row(71))
    record = build_plan({"records": [_row(71)]}, {key: available})["records"][0]
    assert record["allocated_total"] == expected
    assert record["allocated_real"] == record["allocated_synthetic"] == expected // 2


def test_target_never_exceeds_100():
    key = product_key(_row(99))
    record = build_plan({"records": [_row(99)]}, {key: 100})["records"][0]
    assert record["target_total_even"] == record["allocated_total"] == 100


def test_unlisted_product_remains_unknown_with_partial_inventory():
    second = {**_row(20), "model": "Core i7-12700K"}
    plan = build_plan({"records": [_row(71), second]}, {product_key(_row(71)): 2})
    assert plan["records"][1]["status"] == "awaiting_real_inventory"
    assert plan["records"][1]["allocated_total"] is None


def test_inventory_requires_review_id_audit_and_source(tmp_path):
    path = tmp_path / "inventory.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "product_key", "available_real_count", "source_ref", "review_ids_verified", "usage_approved"
        ])
        writer.writeheader()
        writer.writerow({"product_key": product_key(_row(71)), "available_real_count": 3,
                         "source_ref": "domestic-source-1", "review_ids_verified": "no", "usage_approved": "yes"})
    with pytest.raises(ValueError, match="review IDs not verified"):
        load_inventory(path, {product_key(_row(71))})


def test_verified_inventory_can_confirm_zero_and_positive_counts(tmp_path):
    first = product_key(_row(71))
    second = product_key({**_row(20), "model": "Core i7-12700K"})
    path = tmp_path / "inventory.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "product_key", "available_real_count", "source_ref", "review_ids_verified", "usage_approved"
        ])
        writer.writeheader()
        writer.writerow({"product_key": first, "available_real_count": 3,
                         "source_ref": "domestic-source-1", "review_ids_verified": "yes", "usage_approved": "yes"})
        writer.writerow({"product_key": second, "available_real_count": 0,
                         "source_ref": "", "review_ids_verified": "yes", "usage_approved": "yes"})
    assert load_inventory(path, {first, second}) == {first: 3, second: 0}


def test_actual_count_plan_has_unique_catalog_keys():
    from scripts.plan_review_mix import DEFAULT_COUNT_PLAN

    source = json.loads(DEFAULT_COUNT_PLAN.read_text(encoding="utf-8"))
    plan = build_plan(source)
    assert plan["summary"]["products"] == 322
    assert plan["summary"]["pending_products"] == 322

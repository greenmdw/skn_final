from scripts.derive_live_danawa_matches import derive


def test_derive_rejects_distinct_variant_and_shared_pcode() -> None:
    checks = [
        {"product_key": "case:a:north", "pcode": "1", "catalog_model": "North", "sheet": "Case",
         "source_title": "Fractal North Momentum Edition", "model_text_present": True, "error": None},
        {"product_key": "gpu:nvidia:geforce-rtx-3050-(6gb)", "pcode": "2", "catalog_model": "RTX 3050 6GB", "sheet": "GPU",
         "source_title": "RTX 3050 D6 6GB", "model_text_present": False, "error": None},
        {"product_key": "gpu:nvidia:rtx-3050-(6gb)", "pcode": "2", "catalog_model": "RTX 3050 (6GB)", "sheet": "GPU",
         "source_title": "RTX 3050 D6 6GB", "model_text_present": False, "error": None},
    ]
    matches, rejected = derive(checks, [])
    assert [row["pcode"] for row in matches] == ["2"]
    assert [row["reason"] for row in rejected] == ["distinct_named_variant", "pcode_already_claimed_by_another_catalog_key"]


def test_derive_rejects_noncanonical_duplicate_and_size_variant() -> None:
    checks = [
        {"product_key": "gpu:nvidia:geforce-rtx-3050-6gb", "pcode": "11", "catalog_model": "RTX 3050 6GB",
         "sheet": "GPU", "source_title": "RTX 3050 D6 6GB", "model_text_present": False, "error": None},
        {"product_key": "case:fractal:torrent", "pcode": "12", "catalog_model": "Torrent", "sheet": "Case",
         "source_title": "Fractal Design Torrent Nano", "model_text_present": True, "error": None},
    ]
    matches, rejected = derive(checks, [])
    assert matches == []
    assert [row["reason"] for row in rejected] == ["duplicate_catalog_model_uses_canonical_key", "distinct_named_variant"]

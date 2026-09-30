from scripts.verify_danawa_candidate_titles import (extract_title, gpu_model_match, psu_model_match,
                                                    ram_model_match, unresolved_candidates)


def test_extract_title_decodes_entities() -> None:
    assert extract_title(b"<html><title>ASUS &amp; ProArt PA602 : Danawa</title></html>") == "ASUS & ProArt PA602 : Danawa"
    assert extract_title("<title>다나와 가격비교</title>".encode("cp949"), "utf-8") == "다나와 가격비교"


def test_unresolved_candidates_excludes_matched_and_respects_single() -> None:
    queue = [
        {"product_key": "a", "sheet": "Case", "catalog_model": "A", "danawa_candidates": [
            {"pcode": "1", "product_url": "https://prod.danawa.com/info/?pcode=1", "model_match_status": "needs_model_review"}]},
        {"product_key": "b", "sheet": "Case", "catalog_model": "B", "danawa_candidates": [
            {"pcode": "2", "product_url": "https://prod.danawa.com/info/?pcode=2", "model_match_status": "needs_model_review"},
            {"pcode": "3", "product_url": "https://prod.danawa.com/info/?pcode=3", "model_match_status": "needs_model_review"}]},
        {"product_key": "c", "sheet": "Case", "catalog_model": "C", "danawa_candidates": [
            {"pcode": "4", "product_url": "https://prod.danawa.com/info/?pcode=4", "model_match_status": "model_family_matched"}]},
    ]
    assert [row["pcode"] for row in unresolved_candidates(queue, only_single=True, max_candidates=2)] == ["1"]
    assert [row["pcode"] for row in unresolved_candidates(queue, only_single=False, max_candidates=2)] == ["1", "2", "3"]
    assert [row["pcode"] for row in unresolved_candidates(queue, only_single=False, only_multiple=True, max_candidates=1)] == ["2"]
    assert [row["pcode"] for row in unresolved_candidates(queue, only_single=False, max_candidates=1, candidate_index=1)] == ["3"]


def test_gpu_model_match_requires_suffix_and_memory() -> None:
    assert gpu_model_match("GeForce RTX 3050 (6GB)", "이엠텍 지포스 RTX 3050 D6 6GB")
    assert not gpu_model_match("GeForce RTX 3050 (6GB)", "이엠텍 지포스 RTX 3050 D6 8GB")
    assert not gpu_model_match("GeForce RTX 4060", "MSI 지포스 RTX 4060 Ti D6 8GB")
    assert gpu_model_match("Radeon RX 9070 XT", "SAPPHIRE 라데온 RX 9070 XT OC D6 16GB")
    assert not gpu_model_match("Radeon RX 9070", "SAPPHIRE 라데온 RX 9070 XT OC D6 16GB")


def test_ram_match_requires_kit_capacity_and_family() -> None:
    assert ram_model_match("DDR5-6000 CL30 LANCER RGB 패키지 (16GB x 2)",
                           "ADATA DDR5-6000 CL30 LANCER RGB 패키지 (32GB(16Gx2))")
    assert not ram_model_match("DDR5-6000 CL30 LANCER RGB 패키지 (16GB x 2)",
                               "ADATA DDR5-6000 CL30 LANCER RGB 패키지 (64GB(32Gx2))")
    assert ram_model_match("DDR5-5600 CL46 (16GB)", "ADATA DDR5-5600 CL46-45-45 (16GB)")
    assert not ram_model_match("DDR5-5600 CL46 (16GB)", "ADATA DDR5-5600 CL46 (32GB(16Gx2))")


def test_psu_match_requires_atx_version() -> None:
    assert psu_model_match("RM1000x SHIFT ATX 3.1", "CORSAIR RM1000x SHIFT 80PLUS골드 ATX3.1")
    assert not psu_model_match("RM1000x SHIFT ATX 3.1", "CORSAIR RM1000x SHIFT ATX3.0")
    assert not psu_model_match("HX1500i ATX 3.1", "CORSAIR HX1500i 2022 80PLUS플래티넘")

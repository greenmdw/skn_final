from scripts.derive_recorded_danawa_matches import derive, model_tokens_match


def test_cpu_korean_title_matches_sku_but_not_nearby_model():
    assert model_tokens_match("CPU", "Core i3-12100F", "인텔 코어i3-12세대 12100F (정품)")
    assert not model_tokens_match("CPU", "Core i3-12100F", "인텔 코어i3-12세대 12100 (정품)")


def test_full_board_model_string_required():
    assert model_tokens_match("MainBoard", "B650M Pro RS", "ASRock B650M Pro RS 대원씨티에스")
    assert not model_tokens_match("MainBoard", "B650M Pro RS", "ASRock B650M PG Lightning")


def test_event_url_is_rejected_even_if_old_audit_said_matched():
    row = {"status": "matched", "sheet": "CPU", "manufacturer": "Intel", "model": "Core i3-12100F",
           "danawa_product_name": "인텔 코어i3-12세대 12100F",
           "danawa_product_url": "https://event.danawa.com/brandCheck.php?nProdC=16101179"}
    matches, rejected = derive([row], {"cpu:intel:core-i3-12100f"})
    assert matches == {} and rejected[0]["reason"] == "not_product_info_url"

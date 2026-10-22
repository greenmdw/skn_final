"""인식 항목이 왜 확정되지 않았는지(이유 코드) — 이번 웹 테스트에서 본 실제 부품 8개를 카탈로그와 견줘 고정한다."""
from __future__ import annotations

import pytest

from src.engine import match_reason
from src.engine.stage3_0_candidates import Candidate


def _c(slot, name, **specs):
    return Candidate(product_key=name.lower().replace(" ", "-"), slot=slot, name=name, specs=specs)


POOL = {
    "CPU": [_c("CPU", "AMD Ryzen 7 7800X3D", socket="AM5", perf_tier=9)],
    "쿨러": [_c("쿨러", "Deepcool AG620 G2 (블랙)", height_mm=157)],
    "GPU": [_c("GPU", "AMD Radeon RX 9070", vram_gb=16, perf_tier=8), _c("GPU", "AMD Radeon RX 9070 XT", vram_gb=16, perf_tier=9)],
    "저장장치": [_c("저장장치", "ADATA LEGEND 970 PRO", capacity_gb=1000, interface="NVMe")],
    "RAM": [_c("RAM", "삼성전자 DDR5-5600 (16GB)", capacity_gb=16, mem_type="DDR5")],
    "케이스": [_c("케이스", "잘만 (Zalman) P30")],
    "파워": [_c("파워", "FSP VITA GM 850W ATX 3.1", wattage_w=850)],
}


def _why(slot, text, status="unmatched", **kw):
    return match_reason.explain(slot, text, POOL[slot], status=status, **kw)


def test_a_confirmed_item_has_no_reason():
    assert _why("CPU", "라이젠 7800X3D", status="confirmed") is None


def test_a_model_that_is_not_in_the_catalog_says_so_without_blaming_the_photo():
    out = _why("CPU", "라이젠 5-5세대 7500X3D")
    assert out["code"] == "not_in_catalog" and out["nearest"] is None and "같은 모델이 없어요" in out["message"]
    assert _why("케이스", "1stPlayer Mi5 WING")["code"] == "not_in_catalog"
    assert _why("저장장치", "ADATA LEGEND 900 M.2 1TB", status="inferred")["code"] == "not_in_catalog"


def test_the_same_model_with_another_variant_names_the_nearest_product_and_why_it_was_not_used():
    gre = _why("GPU", "ASUS PRIME 라데온 RX 9070 GRE EVO OC D6 12GB")
    assert gre["code"] == "variant_mismatch" and gre["nearest"]["name"] == "AMD Radeon RX 9070" and "한정어" in gre["nearest"]["why_not"]
    assert gre["nearest"]["key_specs"]["VRAM(GB)"] == 16
    argb = _why("쿨러", "DEEPCOOL AG620 G2 ARGB")
    assert argb["code"] == "variant_mismatch" and "argb" in argb["nearest"]["why_not"] and "black" in argb["nearest"]["why_not"]


def test_ram_without_a_brand_product_is_not_in_catalog_and_the_read_values_are_used():
    out = _why("RAM", "울티머스 DDR5-5600 (16G x 2)", status="inferred")
    assert out["code"] == "not_in_catalog" and "용량·속도만으로" in out["message"] and "글에서 읽은 값으로 점검" in out["message"]


def test_a_text_without_a_model_number_is_insufficient_info():
    assert _why("파워", "맥스엘리트 브론즈", status="unmatched")["code"] == "insufficient_info"


def test_several_candidates_are_listed_with_key_specs_and_a_single_nearest_is_an_ambiguous_one():
    pool = [_c("저장장치", "KLEVV CRAS C910 (512GB)", capacity_gb=512), _c("저장장치", "KLEVV CRAS C910 (1TB)", capacity_gb=1000)]
    many = match_reason.explain("저장장치", "KLEVV CRAS C910", pool, status="ambiguous", candidate_count=2)
    assert many["code"] == "ambiguous" and [c["name"] for c in many["candidates"]] == ["KLEVV CRAS C910 (512GB)", "KLEVV CRAS C910 (1TB)"]
    assert many["candidates"][1]["key_specs"]["용량(GB)"] == 1000
    one = _why("CPU", "7800X3D", status="candidate", matched_name="AMD Ryzen 7 7800X3D")
    assert one["code"] == "ambiguous" and one["candidates"][0]["key_specs"]["소켓"] == "AM5"


@pytest.mark.parametrize("flags, code", [({"uncertain": True}, "uncertain_reading"), ({"low_quality": True}, "low_quality_photo")])
def test_an_unreliable_reading_beats_every_other_reason_and_keeps_the_hint(flags, code):
    out = _why("CPU", "라이젠 5-? 7500X3D", status="candidate", matched_name="AMD Ryzen 7 7800X3D", **flags)
    assert out["code"] == code and out["candidates"][0]["name"] == "AMD Ryzen 7 7800X3D"

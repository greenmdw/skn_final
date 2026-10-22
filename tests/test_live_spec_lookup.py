"""2단계 — 검증(critique) 스키마·프롬프트. DB·LLM 호출 없이 계약만 확인한다
(docs/미보유부품_실시간스펙검색_설계.md §3)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.engine.owned_parts import _SPEC_LABEL, merge_live_lookup
from src.services import live_spec_lookup
from src.engine.prompts import live_spec_lookup_system
from src.services.live_spec_lookup import LiveSpecLookupResult, SupportedFields


def test_supported_fields_match_owned_parts_spec_keys():
    """owned_parts.py의 호환성 검사가 읽는 키와 한 글자도 달라지면 안 된다."""
    # supported_socket 은 검색 값의 쿨러 socket 을 검사가 읽는 이름으로 옮긴 표시용 라벨이라 스키마에는 없다
    assert set(SupportedFields.model_fields) == set(_SPEC_LABEL) - {"supported_socket"}


def test_relevant_false_defaults_to_all_null_fields():
    result = LiveSpecLookupResult.model_validate({"relevant": False})
    assert result.has_any_field() is False
    assert result.source_url is None


def test_relevant_true_with_fields_is_detected():
    result = LiveSpecLookupResult.model_validate(
        {"relevant": True, "supported_fields": {"socket": "AM5", "wattage_w": 65},
         "source_url": "https://example.com/spec"})
    assert result.has_any_field() is True
    assert result.supported_fields.socket == "AM5"
    assert result.supported_fields.mem_type is None  # 언급 안 된 필드는 null 유지


def test_unknown_field_is_rejected_not_silently_dropped():
    """스키마 밖 필드(모델이 지어낸 키)가 오면 조용히 무시하지 않고 검증에서 걸린다."""
    with pytest.raises(ValidationError):
        SupportedFields.model_validate({"made_up_field": "x"})


def test_missing_relevant_is_rejected():
    with pytest.raises(ValidationError):
        LiveSpecLookupResult.model_validate({"supported_fields": {}})


def test_prompt_mentions_core_anti_hallucination_rules():
    system = live_spec_lookup_system()
    for phrase in ("relevant", "source_url", "스니펫에 실제로 명시된 값만", "지어내"):
        assert phrase in system, f"프롬프트에 '{phrase}' 규칙이 빠짐"


# --- merge_live_lookup (6단계, 업그레이드 모드 확장) ------------------------------------------


def test_merge_live_lookup_fills_unverified_slot_with_cached_fields():
    owned = {"쿨러": {"name": "모름쿨러 X1", "specs": {}, "source": "unverified"}}
    cached = {"쿨러": {"relevant": True, "supported_fields": {"cooling_type": "수랭", "radiator_mm": 240},
                     "source_url": "https://example.com/cooler"}}
    merge_live_lookup(owned, {"쿨러": "모름쿨러 X1"}, cached)
    assert owned["쿨러"]["source"] == "live"
    assert owned["쿨러"]["specs"] == {"cooling_type": "수랭", "radiator_mm": 240}
    assert owned["쿨러"]["source_url"] == "https://example.com/cooler"


def test_merge_live_lookup_skips_slots_that_already_matched():
    owned = {"CPU": {"name": "i5-13600K", "specs": {"socket": "LGA1700"}, "source": "catalog"}}
    cached = {"CPU": {"relevant": True, "supported_fields": {"socket": "AM5"}, "source_url": None}}
    merge_live_lookup(owned, {"CPU": "i5-13600K"}, cached)
    assert owned["CPU"]["source"] == "catalog"
    assert owned["CPU"]["specs"] == {"socket": "LGA1700"}  # 캐시가 있어도 이미 확정된 매칭을 덮어쓰지 않는다


def test_merge_live_lookup_ignores_irrelevant_or_empty_cache():
    owned = {"쿨러": {"name": "모름쿨러 X1", "specs": {}, "source": "unverified"}}
    cached = {"쿨러": {"relevant": False, "supported_fields": {}, "source_url": None}}
    merge_live_lookup(owned, {"쿨러": "모름쿨러 X1"}, cached)
    assert owned["쿨러"]["source"] == "unverified"


def test_merge_live_lookup_no_cache_entry_leaves_unverified():
    owned = {"쿨러": {"name": "모름쿨러 X1", "specs": {}, "source": "unverified"}}
    merge_live_lookup(owned, {"쿨러": "모름쿨러 X1"}, {})
    assert owned["쿨러"]["source"] == "unverified"


# --- normalize_lookup_key (설계 §9.3-1) --------------------------------------------------------

from src.services.live_spec_lookup import normalize_lookup_key  # noqa: E402


@pytest.mark.parametrize("variant", [
    "AMD 라이젠7 9800X3D",
    "AMD 라이젠7 9800X3D 636,500원",
    "[AMD] 라이젠7 9800X3D-636,500원",
    "AMD 라이젠7 9800X3D 25만 5천원",
    "AMD 라이젠7 9800X3D 19996987",
    "AMD 라이젠7 9800X3D x2",
    "amd  라이젠7  9800x3d (2개)",
    "AMD 라이젠7 9800X3D 수량 2 250,000원",
])
def test_same_product_gets_the_same_key_regardless_of_price_quantity_code_or_brackets(variant):
    assert normalize_lookup_key(variant) == normalize_lookup_key("AMD 라이젠7 9800X3D")


@pytest.mark.parametrize("a,b", [
    ("삼성전자 DDR5-5600 16GB", "삼성전자 DDR5-5600 32GB"),            # 용량은 남긴다
    ("AMD 라이젠5 5600", "AMD 라이젠5 5600X"),                          # 모델 토큰은 남긴다
    ("RTX 4070", "RTX 4070 Ti"),
    ("라이젠7 5800X", "라이젠7 5800X3D"),                               # X3D 의 "3"을 수량으로 오인하지 않는다
])
def test_different_products_never_share_a_key(a, b):
    assert normalize_lookup_key(a) != normalize_lookup_key(b)


def test_x3d_model_name_is_not_mistaken_for_a_quantity():
    assert "x3d" in normalize_lookup_key("라이젠7 5800X3D 2개")


def test_key_is_empty_when_only_price_is_left():
    assert normalize_lookup_key("238,000원") == ""
    assert normalize_lookup_key("  ") == ""


# --- 슬롯별 필드 허용 목록 / 프롬프트 (설계 §10.5-1) ---------------------------------------------

from src.services.live_spec_lookup import SLOT_FIELDS, filter_fields_for_slot  # noqa: E402


def test_slot_fields_only_use_real_supported_field_names():
    for slot, allowed in SLOT_FIELDS.items():
        assert allowed <= set(SupportedFields.model_fields), (slot, allowed - set(SupportedFields.model_fields))


@pytest.mark.parametrize("slot,fields,expected", [
    ("파워", {"wattage_w": 1000, "cooling_type": "140mm FDB 팬", "form_factor": "ATX"}, {"wattage_w": 1000, "form_factor": "ATX"}),
    ("저장장치", {"capacity_gb": 1000, "mem_type": "V-NAND 3-bit MLC", "interface": "SATA"}, {"capacity_gb": 1000, "interface": "SATA"}),
    ("메인보드", {"socket": "AM4", "mem_type": "DDR4", "capacity_gb": 128, "speed_mts": 4400, "form_factor": "ATX"},
     {"socket": "AM4", "mem_type": "DDR4", "form_factor": "ATX"}),
    ("CPU", {"socket": "AM4", "mem_type": "DDR4", "speed_mts": 3200, "interface": "PCIe 4.0"}, {"socket": "AM4", "mem_type": "DDR4"}),
    ("케이스", {"supports_form_factors": "ATX", "height_mm": 493}, {"supports_form_factors": "ATX"}),
    ("쿨러", {"cooling_type": "공랭", "height_mm": 168, "wattage_w": 5}, {"cooling_type": "공랭", "height_mm": 168}),
])
def test_filter_fields_for_slot_drops_fields_that_mean_nothing_for_that_part(slot, fields, expected):
    assert filter_fields_for_slot(slot, fields) == expected


def test_filter_fields_passes_everything_when_slot_is_unknown():
    fields = {"wattage_w": 1000, "cooling_type": "x"}
    assert filter_fields_for_slot(None, fields) == fields
    assert filter_fields_for_slot("모르는슬롯", fields) == fields


def test_filter_fields_accepts_slot_aliases():
    assert filter_fields_for_slot("그래픽카드", {"interface": "PCIe 5.0", "socket": "x"}) == {"interface": "PCIe 5.0"}


def test_prompt_pins_radiator_size_and_slot_relevance():
    system = live_spec_lookup_system()
    assert "두께" in system and "radiator_mm" in system          # 크기이지 두께가 아니다
    assert "부품 종류" in system                                  # 슬롯에 맞는 필드만


# ── 값 표기 정리 · 제품 이름 확인 ─────────────────────────────────────────────────────────────

def test_normalize_fields_turns_sentences_into_engine_vocabulary():
    n = live_spec_lookup.normalize_fields
    assert n("RAM", {"mem_type": "DDR5 SDRAM", "speed_mts": 6000}) == {"mem_type": "DDR5", "speed_mts": 6000}
    assert n("쿨러", {"cooling_type": "일체형 수랭"})["cooling_type"] == "Liquid (AIO)"
    assert n("메인보드", {"socket": "Socket AM5", "form_factor": "Micro-ATX"}) == {"socket": "AM5", "form_factor": "mATX"}
    assert n("케이스", {"supports_form_factors": "ATX, Micro-ATX"})["supports_form_factors"] == "ATX / mATX"


def test_normalize_fields_drops_values_that_do_not_resolve_to_one():
    n = live_spec_lookup.normalize_fields
    assert "mem_type" not in n("메인보드", {"mem_type": "DDR4 / DDR5", "socket": "AM5"})
    assert n("쿨러", {"cooling_type": "140mm FDB 팬"}) == {}
    # 쿨러의 socket 은 지원 소켓 목록이라 손대지 않는다
    assert n("쿨러", {"socket": "AM5, LGA1700"}) == {"socket": "LGA1700, AM5"}


@pytest.mark.parametrize("name,snippet,expected", [
    ("Corsair RM1999x 파워", "The Corsair RM850x delivers 850W", False),       # 없는 모델 — 일반 글만 잡힘
    ("Corsair RM850x 850W", "The Corsair RM850x delivers 850W", True),
    ("Noctua NH-U12A", "Noctua NH-U12A is a 120mm tower cooler", True),
    ("삼성 DDR5 19999MHz 메모리", "Samsung DRAM DDR5 overview", False),
    ("Dark Rock Pro 5", "anything at all", True),                              # 모델 번호 낱말이 없으면 판단하지 않는다
    ("인텔 코어 i9-14900K", "Intel Core i9-14900K processor", True),
])
def test_snippet_must_mention_the_product_model(name, snippet, expected):
    assert live_spec_lookup.snippet_mentions_the_product(name, snippet) is expected


def test_cooler_socket_list_is_rewritten_in_the_catalog_notation_the_checker_can_read():
    from src.engine.compat_parse import socket_supported
    from src.engine.part_values import canonical_cooler_sockets

    text = "Intel 115x / 2011 / 2011-3 / 2066 / 1200 / 1700 / 1851, AMD AM4 / AM5"
    # 원문 그대로는 AM4 쿨러를 비호환으로 오판한다 — 바꾼 표기는 읽는다
    assert socket_supported("AM4", text) is False
    value = canonical_cooler_sockets(text)
    assert [socket_supported(s, value) for s in ("AM4", "AM5", "LGA1700", "LGA1851", "LGA1200", "LGA1151")] == [True] * 6
    assert socket_supported("TR4", value) is False
    assert canonical_cooler_sockets("호환 소켓 없음") is None


def test_live_cooler_socket_reaches_the_checker_under_supported_socket():
    owned = {"쿨러": {"name": "모름 쿨러", "specs": {}, "source": "unverified"}}
    merge_live_lookup(owned, {"쿨러": "모름 쿨러"}, {"쿨러": {"relevant": True, "source_url": "u",
                                                         "supported_fields": {"socket": "LGA1700, AM5/AM4", "height_mm": 154}}})
    assert owned["쿨러"]["specs"] == {"supported_socket": "LGA1700, AM5/AM4", "height_mm": 154}

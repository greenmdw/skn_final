"""2단계 — 검증(critique) 스키마·프롬프트. DB·LLM 호출 없이 계약만 확인한다
(docs/미보유부품_실시간스펙검색_설계.md §3)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.engine.owned_parts import _SPEC_LABEL
from src.engine.prompts import live_spec_lookup_system
from src.services.live_spec_lookup import LiveSpecLookupResult, SupportedFields


def test_supported_fields_match_owned_parts_spec_keys():
    """owned_parts.py의 호환성 검사가 읽는 키와 한 글자도 달라지면 안 된다."""
    assert set(SupportedFields.model_fields) == set(_SPEC_LABEL)


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

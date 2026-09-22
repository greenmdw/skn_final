"""견적 점검 사양 추출 에이전트 — 가용 조건, 추출 결과 정리, 실패 시 호출자에게 예외를 그대로 올리는지."""
from __future__ import annotations

import pytest

from src.agent import spec_extraction_agent as agent_mod


def test_unavailable_when_mock_mode(monkeypatch):
    monkeypatch.setattr(agent_mod, "MOCK_MODE", True)
    monkeypatch.setattr(agent_mod, "SPEC_EXTRACTION_AGENT", True)
    monkeypatch.setattr(agent_mod, "OPENAI_API_KEY", "sk-test")
    assert agent_mod.available() is False


def test_unavailable_when_flag_off(monkeypatch):
    monkeypatch.setattr(agent_mod, "MOCK_MODE", False)
    monkeypatch.setattr(agent_mod, "SPEC_EXTRACTION_AGENT", False)
    monkeypatch.setattr(agent_mod, "OPENAI_API_KEY", "sk-test")
    assert agent_mod.available() is False


def test_unavailable_without_api_key(monkeypatch):
    monkeypatch.setattr(agent_mod, "MOCK_MODE", False)
    monkeypatch.setattr(agent_mod, "SPEC_EXTRACTION_AGENT", True)
    monkeypatch.setattr(agent_mod, "OPENAI_API_KEY", "")
    assert agent_mod.available() is False


def test_available_when_everything_is_set(monkeypatch):
    monkeypatch.setattr(agent_mod, "MOCK_MODE", False)
    monkeypatch.setattr(agent_mod, "SPEC_EXTRACTION_AGENT", True)
    monkeypatch.setattr(agent_mod, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(agent_mod, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(agent_mod, "LLM_MODEL", "gpt-4o-mini")
    assert agent_mod.available() is True


def test_extract_drops_empty_and_null_slots(monkeypatch):
    monkeypatch.setattr(agent_mod, "call_llm", lambda *a, **k: {
        "CPU": "라이젠 7 7800X3D", "GPU": "RTX 4070 SUPER", "RAM": None, "메인보드": "  ", "파워": "",
    })
    assert agent_mod.extract("아무 텍스트") == {"CPU": "라이젠 7 7800X3D", "GPU": "RTX 4070 SUPER"}


def test_extract_ignores_fields_the_schema_does_not_know():
    # 스키마에 없는 키가 섞여 와도(예: MOCK_MODE의 call_llm이 주는 {"text": ...}) 에러 없이 빈 결과.
    import unittest.mock

    with unittest.mock.patch.object(agent_mod, "call_llm", return_value={"text": "[MOCK] 일반 응답"}):
        assert agent_mod.extract("아무 텍스트") == {}


def test_extract_raises_when_the_model_returns_something_unvalidatable(monkeypatch):
    monkeypatch.setattr(agent_mod, "call_llm", lambda *a, **k: {"CPU": ["리스트는 문자열이 아니다"]})
    with pytest.raises(Exception):
        agent_mod.extract("아무 텍스트")


# ── 이미지(스크린샷) 추출 — 영문 슬롯 스키마를 쓰고 한글 슬롯으로 옮긴다(2026-09-22 실측: 비전+한글
# 필드명 조합은 gpt-4o-mini에서 깨진다). 비전 호출이 답을 {"properties": {...}}로 감쌀 때도 처리한다.
def test_extract_from_image_maps_ascii_slots_to_korean_and_cleans_up(monkeypatch):
    seen = {}

    def fake_vision(image_data_url, **kwargs):
        seen["image_data_url"] = image_data_url
        seen["kwargs"] = kwargs
        return {"cpu": "라이젠 7 7800X3D", "gpu": "  ", "ram": None}

    monkeypatch.setattr(agent_mod, "call_llm_vision", fake_vision)
    result = agent_mod.extract_from_image("data:image/png;base64,AAAA")
    assert result == {"CPU": "라이젠 7 7800X3D"}          # 공백·null 슬롯은 빠지고, 한글 슬롯 이름으로 나온다
    assert seen["image_data_url"] == "data:image/png;base64,AAAA"
    assert seen["kwargs"]["system"]


def test_extract_from_image_unwraps_a_properties_envelope():
    # 실측 동작: 모델이 가끔 답을 스키마처럼 한 번 더 감싼다 — 최상위에 슬롯 이름이 하나도 없으면
    # properties 안쪽을 대신 쓴다.
    import unittest.mock

    wrapped = {"type": "object", "properties": {"cpu": "Ryzen 5 7600", "gpu": "RTX 4070 SUPER",
                                                "motherboard": None, "case_": "White Mid Tower"}}
    with unittest.mock.patch.object(agent_mod, "call_llm_vision", return_value=wrapped):
        result = agent_mod.extract_from_image("data:image/png;base64,AAAA")
    assert result == {"CPU": "Ryzen 5 7600", "GPU": "RTX 4070 SUPER", "케이스": "White Mid Tower"}


def test_extract_from_image_does_not_unwrap_when_slots_are_already_top_level():
    # 최상위에 이미 슬롯이 있으면(정상 응답) properties 키가 우연히 껴 있어도 그대로 쓴다 —
    # 예: "케이스" 값 자체가 "properties" 라는 글자를 포함하는 극단적 경우를 오unwrap하지 않는다.
    import unittest.mock

    normal = {"cpu": "Ryzen 5 7600", "properties": "이 값은 슬롯이 아니라 우연한 필드다"}
    with unittest.mock.patch.object(agent_mod, "call_llm_vision", return_value=normal):
        result = agent_mod.extract_from_image("data:image/png;base64,AAAA")
    assert result == {"CPU": "Ryzen 5 7600"}


def test_extract_from_image_propagates_failure_to_the_caller(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vision model unavailable")

    monkeypatch.setattr(agent_mod, "call_llm_vision", boom)
    with pytest.raises(Exception):
        agent_mod.extract_from_image("data:image/png;base64,AAAA")

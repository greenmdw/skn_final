"""브랜드·슬롯 이름 맞추기 — 사용자가 말한 이름을 그 슬롯의 카탈로그 표기로."""
from __future__ import annotations

import pytest

from src.engine.brands import canonical_brand, canonical_slot, cpu_brand_pref


@pytest.mark.parametrize("raw,expected", [
    ("그래픽카드", "GPU"), ("gpu", "GPU"), ("그래픽 카드", "GPU"), ("씨피유", "CPU"), ("램", "RAM"), ("파워", "파워"),
    ("전원", "파워"), ("모니터", "모니터"),        # 모르는 슬롯은 그대로
])
def test_slot_names(raw, expected):
    assert canonical_slot(raw) == expected


@pytest.mark.parametrize("raw,catalog,expected", [
    ("커세어", ["다크플래쉬", "커세어 (Corsair)", "NZXT"], "커세어 (Corsair)"),     # 케이스 표기
    ("Corsair", ["다크플래쉬", "커세어 (Corsair)"], "커세어 (Corsair)"),
    ("corsair", ["Corsair", "Seasonic"], "Corsair"),                                  # 파워 표기
    ("삼성", ["Samsung", "Crucial"], "Samsung"),                                       # SSD
    ("삼성", ["삼성전자", "SK하이닉스"], "삼성전자"),                                     # RAM
    ("하이닉스", ["삼성전자", "SK하이닉스"], "SK하이닉스"),
    ("엔비디아", ["AMD", "NVIDIA"], "NVIDIA"), ("라데온", ["AMD", "NVIDIA"], "AMD"),
    ("be quiet", ["be quiet!", "Noctua"], "be quiet!"), ("G.Skill", ["G.SKILL"], "G.SKILL"),
    ("  잘 모름 ", ["AMD", "NVIDIA"], "잘 모름"),                                       # 모르면 다듬어서 그대로
])
def test_brand_names_follow_the_slots_catalog_spelling(raw, catalog, expected):
    assert canonical_brand(raw, catalog) == expected


def test_cpu_brand_pref_takes_only_intel_or_amd():
    assert [cpu_brand_pref(b) for b in ("인텔", "Intel", "라이젠", "AMD", "NVIDIA", "삼성")] == ["intel", "intel", "amd", "amd", None, None]

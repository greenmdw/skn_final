"""사용 가이드 검색 — 슬롯을 알면 그 슬롯의 가이드 안에서만 고른다."""
from __future__ import annotations

import json

import pytest

from src.config import CARE_GUIDES_JSON
from src.rag.care_guides import SLOT_GUIDE_IDS, search_care_guide


def test_slot_guide_ids_exist_in_data():
    ids = {g["id"] for g in json.loads(CARE_GUIDES_JSON.read_text(encoding="utf-8"))}
    for slot, guide_ids in SLOT_GUIDE_IDS.items():
        assert set(guide_ids) <= ids, slot


@pytest.mark.parametrize("slot", sorted(SLOT_GUIDE_IDS))
def test_search_with_slot_only_returns_that_slots_guides(slot):
    # 질의가 다른 슬롯 얘기여도(임베딩이 그쪽을 더 가깝게 봐도) 슬롯 밖 가이드는 나오지 않는다.
    hits = search_care_guide("NVMe SSD 발열 서멀 스로틀링 히트싱크", k=5, slot=slot)
    assert hits and {h["id"] for h in hits} <= set(SLOT_GUIDE_IDS[slot])


def test_search_without_slot_searches_all_guides():
    ids = {g["id"] for g in json.loads(CARE_GUIDES_JSON.read_text(encoding="utf-8"))}
    assert {h["id"] for h in search_care_guide("SSD 발열", k=len(ids))} == ids


def test_unknown_slot_falls_back_to_all_guides():
    assert search_care_guide("SSD 발열", k=1, slot="특이슬롯")

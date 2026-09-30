"""설치 방법 문서(kind=install)와 구매 전 확인(care) 문서가 검색에서 섞이지 않는다.

조립 가이드(리포트)는 팀 결정으로 없앴다 — 설치 문서를 인용하던 소비처는 없어졌고, 검색 경계만 남겨 검사한다."""
from __future__ import annotations

import json

import pytest

from src.config import CARE_GUIDES_JSON
from src.rag.care_guides import INSTALL_GUIDE_IDS, SLOT_GUIDE_IDS, search_care_guide

DOCS = json.loads(CARE_GUIDES_JSON.read_text(encoding="utf-8"))
SLOTS = ["CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"]


def test_every_slot_has_one_install_document_of_kind_install():
    by_id = {d["id"]: d for d in DOCS}
    assert set(INSTALL_GUIDE_IDS) == set(SLOTS)
    for slot, ids in INSTALL_GUIDE_IDS.items():
        assert ids and all(by_id[i].get("kind") == "install" for i in ids), slot
        assert all(len(by_id[i]["text"]) > 60 for i in ids), f"{slot}: 설치 문서가 너무 짧다"


def test_care_documents_are_untouched_and_default_to_kind_care():
    care = [d for d in DOCS if d.get("kind", "care") == "care"]
    assert len(care) == 18 and not any(d["id"].startswith("install_") for d in care)


@pytest.mark.parametrize("slot", SLOTS)
def test_install_search_only_returns_that_slots_install_document(slot):
    hits = search_care_guide("설치 장착 방법", k=5, slot=slot, kind="install")
    assert [h["id"] for h in hits] == list(INSTALL_GUIDE_IDS[slot])
    assert all(h["kind"] == "install" for h in hits)


@pytest.mark.parametrize("slot", SLOTS)
def test_purchase_checks_never_pick_up_install_documents(slot):
    """결과 화면의 "구매 전 확인"은 kind 를 안 준다 — 설치 문서가 그쪽에 섞이면 안 된다."""
    hits = search_care_guide("확인할 점", k=10, slot=slot)
    assert hits and {h["id"] for h in hits} <= set(SLOT_GUIDE_IDS[slot])
    assert not any(h["id"].startswith("install_") for h in hits)


def test_kind_care_excludes_install_documents_even_without_a_slot():
    assert not any(h["kind"] == "install" for h in search_care_guide("설치", k=30, kind="care"))
    assert all(h["kind"] == "install" for h in search_care_guide("설치", k=30, kind="install"))


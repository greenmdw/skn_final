"""조립·설치 가이드 — 설치 방법 문서(kind=install)와 구매 전 확인(care) 문서가 섞이지 않고, 가이드가 둘 다 인용한다."""
from __future__ import annotations

import json

import pytest

from src.agent.assembly_guide_agent import ASSEMBLY_ORDER, build_guide, build_guide_fallback
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


def _items(*slots: str) -> list[dict]:
    return [{"slot": s, "product": {"name": f"테스트 {s}"}} for s in slots]


def test_fallback_guide_lists_install_and_caution_for_each_part_in_assembly_order():
    items = [{"slot": s, "product": {"name": f"테스트 {s}"}} for s in reversed(SLOTS)]     # 일부러 거꾸로
    guide = build_guide(items)
    assert guide["status"] == "ready"
    text = guide["text"]
    titles = [line for line in text.splitlines() if line[:1].isdigit()]
    assert [t.split(" — ")[0].split(". ")[1] for t in titles] == ASSEMBLY_ORDER      # 표준 조립 순서로 정렬
    assert text.count("   설치: ") == 8 and text.count("   확인: ") == 8
    install_texts = {d["text"] for d in DOCS if d.get("kind") == "install"}
    assert all(any(line[len("   설치: "):] == t for t in install_texts) for line in text.splitlines() if line.startswith("   설치: "))


def test_partial_upgrade_only_guides_the_replaced_parts():
    text = build_guide(_items("GPU"))["text"]
    titles = [line for line in text.splitlines() if line[:1].isdigit()]        # 단계 제목 줄만(본문은 다른 부품 이름을 말할 수 있다)
    assert titles == ["1. GPU — 테스트 GPU"] and text.count("   설치: ") == 1


def test_no_items_means_no_guide_yet():
    assert build_guide([]) == {"status": "pending", "text": None}


def test_a_slot_without_an_install_document_says_so_instead_of_inventing_steps(monkeypatch):
    monkeypatch.setitem(INSTALL_GUIDE_IDS, "쿨러", ("does_not_exist",))
    text = build_guide_fallback(_items("쿨러"))
    assert "설치 안내 문서가 아직 없습니다" in text

"""견적 사진에서 읽은 부품 이름을 카탈로그 제품에 연결하는 규칙 — 줄여 쓴 표기와 제조사 별칭.

배경(2026-10-15 실측): 정확한 DB 이름은 확정률 97%인데 시리즈 숫자·제조사를 줄여 쓰면 47%였다. 실제 견적 사진은
"라이젠 7800X3D"·"만리 5060 Ti 폴라 폭스"·"에센코어 CRAS C910"처럼 적는다. 아래 사례는 그 실패에서 그대로 옮긴 것이다.
원칙: 모델 번호가 카탈로그에서 유일하면 확정하고, 틀린 제품으로 확정하느니 확정하지 않는다."""
from __future__ import annotations

import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.engine.owned_parts import resolve_owned_parts
    from src.engine.stage3_0_candidates import load_pc_catalog


@pytest.fixture(scope="module")
def pool():
    return load_pc_catalog(lambda _m: None)


def _resolve(pool, slot: str, text: str) -> dict:
    return resolve_owned_parts({slot: text}, pool, [slot])[slot]


def _confirmed_name(pool, slot: str, text: str) -> str | None:
    info = _resolve(pool, slot, text)
    return info["name"] if info["source"] == "catalog" and (info.get("candidate_count") or 1) == 1 else None


# (부품군, 사진에 적힌 글, 카탈로그 이름) — 줄여 쓴 표기가 같은 제품으로 확정돼야 한다
CONFIRMED = [
    ("CPU", "라이젠 7800X3D", "AMD Ryzen 7 7800X3D"),
    ("CPU", "라이젠 9600X", "AMD Ryzen 5 9600X"),
    ("CPU", "AMD 7800X3D", "AMD Ryzen 7 7800X3D"),
    ("CPU", "Ryzen 7 7800X3D", "AMD Ryzen 7 7800X3D"),
    ("GPU", "만리 5060 Ti 폴라 폭스", "NVIDIA GeForce RTX 5060 Ti"),
    ("GPU", "RTX 5060 Ti", "NVIDIA GeForce RTX 5060 Ti"),
    ("GPU", "지포스 RTX 5060 Ti", "NVIDIA GeForce RTX 5060 Ti"),
    ("저장장치", "에센코어 CRAS C910 (500GB)", "KLEVV CRAS C910"),
    ("저장장치", "KLEVV CRAS C910", "KLEVV CRAS C910"),
    ("저장장치", "990 EVO Plus", "Samsung 990 EVO Plus"),
    ("저장장치", "T500", "Crucial T500"),
    ("메인보드", "B650M K", "GIGABYTE B650M K"),
    ("메인보드", "기가바이트 B650M K", "GIGABYTE B650M K"),
    ("메인보드", "PRIME H610M-K D4", "ASUS PRIME H610M-K D4"),
    ("쿨러", "NH-D15 G2", "Noctua NH-D15 G2"),
    ("쿨러", "AG400 G2", "Deepcool AG400 G2"),
    ("쿨러", "PALADIN 400", "PCCOOLER PALADIN 400"),
    ("케이스", "H9 Elite", "NZXT H9 Elite"),
]


@pytest.mark.parametrize("slot, text, expected", CONFIRMED)
def test_shortened_names_are_confirmed_to_the_same_catalog_product(pool, slot, text, expected):
    assert _confirmed_name(pool, slot, text) == expected


# 확정하면 안 되는 글 — 칩셋만, 다른 제조사, 모델이 다른 것, 후보가 여럿인 것
NOT_CONFIRMED = [
    ("메인보드", "B650M", "칩셋 이름만으로는 어느 보드인지 모른다"),
    ("메인보드", "ASUS B650M K", "다른 제조사를 적었는데 GIGABYTE 로 연결하면 안 된다"),
    ("CPU", "라이젠 7800", "모델이 불완전하다"),
    ("저장장치", "삼성 990", "990 PRO·990 EVO 가 섞여 한 제품으로 못 정한다"),
    ("저장장치", "SSD 500GB", "모델 번호가 없다"),
    ("CPU", "라이젠 9", "시리즈만 적었다"),
    ("RAM", "DDR5 32GB", "규격과 용량만으로는 제품을 특정할 수 없다"),
    ("RAM", "DDR5-5600 16GB", "속도와 용량만 있다(제조사 없음)"),
    ("파워", "750W", "용량만 적었다"),
    ("저장장치", "NVMe PCIe4 1TB", "규격과 용량만 있다"),
]


@pytest.mark.parametrize("slot, text, why", NOT_CONFIRMED)
def test_ambiguous_or_wrong_names_are_not_confirmed(pool, slot, text, why):
    assert _confirmed_name(pool, slot, text) is None, why


def test_model_only_match_is_marked_so_the_screen_can_say_the_maker_was_not_written(pool):
    """제조사 없이 모델 번호로 찾은 것은 확정이되 그 근거를 남긴다(화면 표시용)."""
    assert _resolve(pool, "메인보드", "B650M K").get("match_via") == "model"
    assert _resolve(pool, "메인보드", "GIGABYTE B650M K").get("match_via") in (None, "name")


def test_a_plain_5060_is_never_linked_to_the_ti_variant(pool):
    """Ti 가 아닌 5060 은 5060 이거나 확정 안 됨이어야 하고, 5060 Ti 로 연결되면 안 된다."""
    assert _confirmed_name(pool, "GPU", "RTX 5060") != "NVIDIA GeForce RTX 5060 Ti"


def test_a_qualifier_in_the_text_that_the_catalog_name_lacks_is_a_different_product(pool):
    """글의 Super·Ti 가 후보 이름에 없으면 그 후보가 아니다(흐린 사진에서 4060 SUPER 가 4060 으로 확정되던 오연결)."""
    assert _confirmed_name(pool, "GPU", "RTX 4060 SUPER") != "NVIDIA GeForce RTX 4060"
    assert _confirmed_name(pool, "GPU", "RTX 4070 SUPER") == "NVIDIA GeForce RTX 4070 SUPER"
    assert _confirmed_name(pool, "GPU", "RTX 4060") == "NVIDIA GeForce RTX 4060"


@pytest.mark.parametrize("slot, text, expected", [
    ("CPU", "CPU 라이젠 7800X3D", "AMD Ryzen 7 7800X3D"),
    ("저장장치", "SSD 에센코어 CRAS C910 500GB", "KLEVV CRAS C910"),
    ("메인보드", "메인보드 기가바이트 B650M K", "GIGABYTE B650M K"),
    ("GPU", "그래픽카드 만리 5060 Ti 폴라 폭스", "NVIDIA GeForce RTX 5060 Ti"),
])
def test_a_part_category_word_in_front_of_the_name_does_not_block_the_match(pool, slot, text, expected):
    """텍스트로 붙여 넣은 견적은 줄 앞에 부품군 이름이 붙는다 — 그 낱말 때문에 연결이 막히면 안 된다."""
    assert _confirmed_name(pool, slot, text) == expected

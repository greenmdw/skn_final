"""견적 텍스트 → 카탈로그 매칭 품질 — 한글 표기, 붙여 쓴 모델명, 용량 변형, 짧게 적은 이름.

2026-09-27 실측: 다나와·블로그 견적에 흔한 표기("라이젠5-5세대 7600", "기가바이트", "커세어 5000D") 38건 중
17건만 대응됐다. 카탈로그 이름은 영문 낱말이고 견적은 한글·약칭이 섞여 낱말이 안 맞았다. 카탈로그 밖 제품은 여전히
지어내지 않는다(대응 없음 또는 "가장 비슷함" 경고 상태).
"""
from __future__ import annotations

import pytest

from src.dto import Candidate
from src.engine.owned_parts import _match_catalog, _match_nearest, preview_current_specs, resolve_owned_parts

NAMES = {
    "CPU": ["AMD Ryzen 5 7600", "AMD Ryzen 5 7600X", "AMD Ryzen 7 7800X3D", "AMD Ryzen 7 5800X3D",
            "Intel Core i5-14400", "Intel Core i5-14400F", "Intel Core i7-14700K", "Intel Core Ultra 7 265K"],
    "GPU": ["NVIDIA GeForce RTX 4060", "NVIDIA GeForce RTX 4060 Ti", "NVIDIA GeForce RTX 3050 (8GB)",
            "NVIDIA GeForce RTX 3050 (6GB)", "NVIDIA GeForce RTX 3060 12GB", "NVIDIA GeForce RTX 5070 Ti",
            "AMD Radeon RX 7800 XT"],
    "RAM": ["삼성전자 DDR5-5600 (16GB)", "삼성전자 DDR5-5600 (32GB)", "SK하이닉스 DDR5-5600 (16GB)"],
    "메인보드": ["ASUS Prime B650M-A II", "MSI MAG B650 Tomahawk WIFI", "GIGABYTE B760M DS3H", "MSI MAG B760M 박격포 II"],
    "파워": ["Micronics Classic II 풀체인지 700W ATX 3.1", "Micronics Classic II 풀체인지 600W", "Seasonic FOCUS GX-750 ATX 3.0",
            "Corsair RM850e ATX 3.1", "Corsair RM1000e ATX 3.1", "Corsair RM1000x SHIFT ATX 3.1"],
    "케이스": ["커세어 (Corsair) 5000D AIRFLOW", "잘만 (Zalman) P30", "NZXT H9 Flow"],
    "쿨러": ["Thermalright Peerless Assassin 120 SE", "Noctua NH-D15 G2"],
    "저장장치": ["Samsung 990 PRO", "Samsung 990 PRO with Heatsink", "Western Digital WD_BLACK SN850X"],
}
POOL = {slot: [Candidate(product_key=f"{slot}:{n}", slot=slot, name=n, specs={"socket": "X"}) for n in names]
        for slot, names in NAMES.items()}


def exact(slot: str, text: str) -> list[str]:
    return [c.name for c in _match_catalog(text, POOL[slot])]


@pytest.mark.parametrize("slot,text,expected", [
    ("CPU", "AMD 라이젠5-5세대 7600 (라파엘) (정품 멀티팩 한글)", "AMD Ryzen 5 7600"),
    ("CPU", "라이젠7 7800X3D", "AMD Ryzen 7 7800X3D"),                       # 한글 브랜드 + 붙여 쓴 숫자
    ("CPU", "인텔 코어i5-14세대 14400F", "Intel Core i5-14400F"),
    ("CPU", "인텔 i7 14700K", "Intel Core i7-14700K"),
    ("CPU", "i5-14400F", "Intel Core i5-14400F"),
    ("GPU", "지포스 RTX 4060 Ti 8GB", "NVIDIA GeForce RTX 4060 Ti"),
    ("GPU", "RTX3060 12GB", "NVIDIA GeForce RTX 3060 12GB"),                  # 붙여 쓴 GPU 모델명
    ("GPU", "GIGABYTE 라데온 RX 7800 XT GAMING OC 16GB", "AMD Radeon RX 7800 XT"),
    ("메인보드", "MSI MAG B650 토마호크 WIFI", "MSI MAG B650 Tomahawk WIFI"),   # 한글 별칭
    ("메인보드", "기가바이트 B760M DS3H", "GIGABYTE B760M DS3H"),
    ("메인보드", "ASUS PRIME B650M-A II 대원씨티에스", "ASUS Prime B650M-A II"),  # 유통사 표기는 무시
    ("케이스", "커세어 5000D AIRFLOW", "커세어 (Corsair) 5000D AIRFLOW"),        # 한글·영문 병기 이름
    ("케이스", "잘만 P30", "잘만 (Zalman) P30"),                                 # 두 글자 모델 번호
    ("케이스", "NZXT H9 FLOW", "NZXT H9 Flow"),
    ("쿨러", "써멀라이트 Peerless Assassin 120 SE", "Thermalright Peerless Assassin 120 SE"),
    ("저장장치", "삼성전자 990 PRO 1TB", "Samsung 990 PRO"),
    ("저장장치", "WD Black SN850X 2TB", "Western Digital WD_BLACK SN850X"),
    ("RAM", "삼성 DDR5 5600 32GB", "삼성전자 DDR5-5600 (32GB)"),               # 제조사+속도가 있으면 RAM 도 대응, 용량으로 좁힌다
])
def test_common_korean_and_compact_notations_match_the_catalog(slot, text, expected):
    assert exact(slot, text) == [expected]


def test_a_capacity_in_the_text_picks_that_variant():
    assert exact("GPU", "RTX 3050 6GB") == ["NVIDIA GeForce RTX 3050 (6GB)"]
    assert exact("GPU", "RTX 3050 8GB") == ["NVIDIA GeForce RTX 3050 (8GB)"]
    assert exact("RAM", "삼성전자 DDR5-5600 16GB") == ["삼성전자 DDR5-5600 (16GB)"]


@pytest.mark.parametrize("slot,text", [
    ("CPU", "라이젠 5 7500F"),                 # 카탈로그에 없는 모델 — 비슷한 7600 으로 대신하지 않는다
    ("CPU", "인텔 i5-12400"),                  # 12400F 는 다른 제품
    ("RAM", "DDR5 32GB"),                      # 용량만으로는 제품을 특정할 수 없다
    ("RAM", "삼성전자 DDR5 32GB"),             # 제조사·용량만 — 속도가 없어 후보가 하나로 좁혀지지 않는다
    ("메인보드", "B650M"),                     # 칩셋만으로는 어느 보드인지 모른다
    ("파워", "마이크로닉스 650W"),
    ("저장장치", "SK하이닉스 P41"),
    ("CPU", "인텔"),                           # 모델 번호 없는 브랜드만
])
def test_products_outside_the_catalog_are_not_invented(slot, text):
    assert exact(slot, text) == []
    assert _match_nearest(text, POOL[slot]) is None


def test_a_shorter_name_than_the_catalog_finds_the_one_nearest_product():
    """"5800X3D" 처럼 짧게 적은 글은 정확한 대응은 아니지만 후보가 하나뿐이면 가장 비슷한 제품으로 본다."""
    assert exact("CPU", "5800X3D") == []
    assert _match_nearest("5800X3D", POOL["CPU"]).name == "AMD Ryzen 7 5800X3D"
    assert _match_nearest("Corsair RM850e", POOL["파워"]).name == "Corsair RM850e ATX 3.1"


def test_when_several_products_fit_a_shorter_name_nothing_is_chosen():
    assert _match_nearest("Corsair RM1000", POOL["파워"]) is None       # rm1000 은 rm1000e·rm1000x 와 다른 낱말이라 후보 0
    assert _match_nearest("Micronics Classic II 풀체인지", POOL["파워"]) is None    # 600W / 700W 둘 다 해당 → 고르지 않는다


def test_a_nearest_product_is_shown_as_needing_confirmation_not_as_a_confirmed_match():
    owned = resolve_owned_parts({"CPU": "5800X3D"}, POOL, ["CPU"])["CPU"]
    assert owned["source"] == "candidate" and owned["candidate"] == "AMD Ryzen 7 5800X3D"
    assert owned["name"] == "5800X3D"                                    # 사용자가 적은 이름 그대로 — 카탈로그 이름으로 바꾸지 않는다
    row = preview_current_specs({"CPU": "5800X3D"}, POOL, ["CPU"])[0]
    assert row["state"] == "warn" and "가장 비슷합니다" in row["matched_note"] and row["matched"] == "5800X3D"


def test_an_exact_match_is_still_a_confirmed_catalog_match():
    row = preview_current_specs({"CPU": "라이젠 7 7800X3D"}, POOL, ["CPU"])[0]
    assert row["state"] == "ok" and row["matched"] == "AMD Ryzen 7 7800X3D"

"""조사 붙이기 — 영문 브랜드·모델명은 읽는 소리로 받침을 판단한다(괄호 "을(를)"로 둘 다 쓰지 않는다)."""
from __future__ import annotations

import pytest

from src.engine.lang import josa


@pytest.mark.parametrize("word,pair,expected", [
    # 약어·숫자는 글자 이름으로
    ("AMD", "을/를", "AMD를"), ("RAM", "은/는", "RAM은"), ("GPU", "은/는", "GPU는"), ("NZXT", "을/를", "NZXT를"),
    ("HDR", "을/를", "HDR을"), ("RTX 3050", "으로/로", "RTX 3050으로"), ("Ryzen 5 7600X", "으로/로", "Ryzen 5 7600X로"),
    # 단어는 표기 관례로 — 대문자로 써도 모음이 있으면 단어
    ("Seasonic", "을/를", "Seasonic을"), ("Corsair", "과/와", "Corsair와"), ("CORSAIR", "을/를", "CORSAIR를"),
    ("ARCTIC", "을/를", "ARCTIC을"), ("ID-COOLING", "을/를", "ID-COOLING을"), ("Zalman", "을/를", "Zalman을"),
    ("Deepcool", "으로/로", "Deepcool로"), ("TeamGroup", "으로/로", "TeamGroup으로"), ("Montech", "을/를", "Montech를"),
    ("NVIDIA", "이/가", "NVIDIA가"), ("Intel", "이/가", "Intel이"), ("RTX 4070 SUPER", "으로/로", "RTX 4070 SUPER로"),
    # 한글·끝 기호
    ("파워", "은/는", "파워는"), ("케이스", "을/를", "케이스를"), ("서울", "으로/로", "서울로"), ("be quiet!", "을/를", "be quiet!를"),
    ('"게임용 PC"', "으로/로", '"게임용 PC"로'),
])
def test_josa_reads_the_word_as_it_is_spoken(word, pair, expected):
    assert josa(word, pair) == expected

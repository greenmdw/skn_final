"""유지 부품의 소켓·메모리를 모델명·칩셋 규칙으로 추정하고, GPU 권장 파워를 유지 파워와 비교한다.

회귀 배경: 카탈로그에 없는 구형 부품(i5-8400, Ryzen 5 3600, GTX 1060, B450 보드 …)은 전부 "확인 안 됨"이라
업그레이드의 호환 검사가 거의 돌지 않았다. 소켓은 제품명이 알려 준다(세대·칩셋). 전력은 같은 세대 안에서도
모델마다 달라 규칙으로 못 읽으므로, 새로 살 GPU 의 제조사 권장 파워(카탈로그 스펙)를 유지 파워 용량과 직접
비교한다. 원칙: 틀리느니 모른다 — 노트북 칩·해석 못 하는 표기는 추정하지 않는다."""
from __future__ import annotations

import pytest

from src.dto import Candidate, RankResult, RequirementSpec
from src.engine.owned_parts import (constrain_targets, infer_board_socket, infer_cpu_socket, resolve_owned_parts)
from src.engine.stage4_optimize import build_computer


# ── CPU: 세대 -> 소켓 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, socket", [
    ("Intel Core i5-8400", "LGA1151"), ("i7-9700K", "LGA1151"), ("i7-7700K", "LGA1151"),
    ("i5-10400F", "LGA1200"), ("Core i5-11400", "LGA1200"), ("i3-10100", "LGA1200"),
    ("i5-12400F", "LGA1700"), ("i5-13600K", "LGA1700"), ("i9-14900KS", "LGA1700"),
    ("i5-2500K", "LGA1155"), ("i7-4790K", "LGA1150"),
    ("Core Ultra 5 245K", "LGA1851"), ("Core Ultra 7 265KF", "LGA1851"), ("Core Ultra 5 225", "LGA1851"),
    ("Ryzen 5 3600", "AM4"), ("AMD Ryzen 5 5600X", "AM4"), ("Ryzen 5 5600G", "AM4"), ("Ryzen 7 5800X3D", "AM4"),
    ("Ryzen 5 1600", "AM4"), ("Ryzen 5 4500", "AM4"),
    ("Ryzen 5 7600", "AM5"), ("Ryzen 7 7800X3D", "AM5"), ("Ryzen 5 9600X", "AM5"), ("Ryzen 9 9950X3D2", "AM5"),
    ("Ryzen 7 8700G", "AM5"),
    ("라이젠 5 3600", "AM4"), ("인텔 코어 i5-12400F", "LGA1700"), ("Ryzen 5600", "AM4"),
])
def test_cpu_model_name_maps_to_its_socket(text, socket):
    assert infer_cpu_socket(text) == socket


@pytest.mark.parametrize("text", [
    "Intel Core i7-12700H", "i5-1135G7", "Ryzen 7 5800U", "Ryzen 9 7940HS", "Core Ultra 7 155H",   # 노트북
    "Intel Pentium G4560", "AMD FX-8350", "Xeon E5-2680", "Intel Core", "그냥 오래된 CPU", "",         # 범위 밖
])
def test_laptop_out_of_scope_or_unreadable_cpus_are_not_guessed(text):
    assert infer_cpu_socket(text) is None


# ── 메인보드: 칩셋 -> 소켓 ───────────────────────────────────────────────────

@pytest.mark.parametrize("text, socket", [
    ("MSI B450 Tomahawk", "AM4"), ("MSI MAG B550M MORTAR", "AM4"), ("ASUS TUF X570-PLUS", "AM4"),
    ("ASRock A520M-HVS", "AM4"), ("GIGABYTE B650M K", "AM5"), ("ASUS ROG STRIX X670E-E", "AM5"),
    ("ASUS PRIME H610M-K D4", "LGA1700"), ("MSI PRO B760M-P", "LGA1700"), ("ASUS Z790-P", "LGA1700"),
    ("GIGABYTE B560M DS3H", "LGA1200"), ("ASUS PRIME Z490-P", "LGA1200"), ("MSI B365M", "LGA1151"),
    ("MSI PRO Z890-S", "LGA1851"), ("ASUS PRIME B860M-A", "LGA1851"),
])
def test_board_chipset_maps_to_its_socket(text, socket):
    assert infer_board_socket(text) == socket


@pytest.mark.parametrize("text", ["ASUS 메인보드", "MSI 전용 보드 X1", "B4500 무엇", ""])
def test_unknown_board_names_are_not_guessed(text):
    assert infer_board_socket(text) is None


# ── resolve: 출처 구분과 메모리 세대 ─────────────────────────────────────────────

def _owned(current, keep=("CPU", "메인보드", "RAM", "GPU", "파워")):
    return resolve_owned_parts(current, {}, keep)


def test_inferred_values_are_labelled_and_explicit_text_is_not():
    guess = _owned({"CPU": "Ryzen 5 3600"})["CPU"]
    assert guess["source"] == "inferred" and guess["specs"] == {"socket": "AM4"} and guess["inferred"] == ["socket"]
    explicit = _owned({"CPU": "Ryzen 5 3600 (AM4)"})["CPU"]
    assert explicit["source"] == "text" and "inferred" not in explicit           # 글에 적힌 값이 우선


def test_board_memory_type_follows_the_socket_only_when_it_is_unambiguous():
    assert _owned({"메인보드": "MSI B450 Tomahawk"})["메인보드"]["specs"] == {"socket": "AM4", "mem_type": "DDR4"}
    assert _owned({"메인보드": "GIGABYTE B650M K"})["메인보드"]["specs"] == {"socket": "AM5", "mem_type": "DDR5"}
    # LGA1700 은 보드마다 DDR4/DDR5 다 -> 소켓만, 메모리는 모름 (이름에 D4 가 있으면 읽는다)
    assert _owned({"메인보드": "MSI PRO B760M-P"})["메인보드"]["specs"] == {"socket": "LGA1700"}
    assert _owned({"메인보드": "ASUS PRIME H610M-K D4"})["메인보드"]["specs"] == {"socket": "LGA1700", "mem_type": "DDR4"}


def test_explicit_ddr_in_the_text_is_confirmed_not_inferred():
    board = _owned({"메인보드": "MSI B760M DDR5"})["메인보드"]
    assert board["specs"]["mem_type"] == "DDR5" and board.get("inferred") == ["socket"]


def test_inferred_socket_constrains_the_platform_like_a_confirmed_one():
    from src.engine import stage2_requirement
    from src.dto import Slots

    slots = Slots(category="computer", mode="upgrade", objective_text="",
                  values={"upgrade_parts": ["메인보드"], "purpose": "game"})
    spec = stage2_requirement.run(slots, {}, lambda _: None)
    spec.owned = _owned({"CPU": "Ryzen 5 3600", "RAM": "DDR4 16GB"}, keep=["CPU", "RAM"])
    constrain_targets(spec)
    assert spec.targets["메인보드"]["socket_in"] == ["AM4"] and spec.targets["메인보드"]["mem_type"] == "DDR4"


# ── 카탈로그 정답 검증: 규칙이 DB 의 실제 소켓과 맞는가 (DB 가 있을 때) ─────────────────────

def test_rule_agrees_with_every_catalog_cpu_it_can_read():
    import psycopg
    from src.config import DATABASE_URL

    try:
        conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다.")
    with conn:
        try:
            rows = conn.execute("select p.brand || ' ' || p.model, c.socket from catalog.cpu_spec c "
                                "join catalog.product p on p.id = c.product_id").fetchall()
        except psycopg.Error:
            pytest.skip("PC 카탈로그가 없습니다.")
    if not rows:
        pytest.skip("PC 카탈로그가 seed 되지 않았습니다.")
    wrong = [(name, socket, infer_cpu_socket(name)) for name, socket in rows
             if infer_cpu_socket(name) not in (None, socket)]
    assert wrong == []                                   # 틀리느니 모른다 — 읽었다면 정답이어야 한다
    assert sum(infer_cpu_socket(n) is not None for n, _ in rows) >= len(rows) - 1     # 그리고 대부분 읽는다


# ── 권장 파워 비교 (한쪽만 견적에 들어갈 때) ───────────────────────────────────

def _cand(slot, key, price=100, score=1.0, **specs) -> Candidate:
    return Candidate(slot=slot, product_key=key, name=key, price=price, score=score, specs=specs)


def _build(pools, owned):
    rank = RankResult(slots={s: {"ranked": [c.model_dump() for c in cs]} for s, cs in pools.items()})
    spec = RequirementSpec(list_id="p", category="computer", mode="upgrade",
                           targets={s: {} for s in pools}, budget={"total": 100_000}, owned=owned)
    return build_computer(rank, spec, lambda _: None)


def test_new_gpu_must_fit_the_kept_psus_recommended_wattage_without_knowing_the_cpu():
    pools = {"GPU": [_cand("GPU", "big", score=9, power_w=320, recommended_psu_w=750),
                     _cand("GPU", "small", score=1, power_w=115, recommended_psu_w=550)]}
    owned = {"파워": {"name": "p", "specs": {"wattage_w": 600}, "source": "text"}}       # CPU 는 모른다
    result = _build(pools, owned)
    assert [i.product_key for i in result.items] == ["small"]
    assert result.link_check["power"] == "ok (근사)"                                      # CPU 전력을 몰라 완전 확인은 아님, 실패도 아님


def test_a_too_small_kept_psu_is_reported_when_nothing_fits():
    pools = {"GPU": [_cand("GPU", "big", power_w=320, recommended_psu_w=750)]}
    owned = {"파워": {"name": "p", "specs": {"wattage_w": 450}, "source": "text"}}
    assert _build(pools, owned).link_check["power"] == "fail"


def test_new_psu_is_checked_against_the_kept_gpus_recommendation():
    pools = {"파워": [_cand("파워", "cheap", score=9, wattage_w=550), _cand("파워", "ok", score=1, wattage_w=850)]}
    owned = {"GPU": {"name": "g", "specs": {"recommended_psu_w": 750}, "source": "catalog"}}
    assert [i.product_key for i in _build(pools, owned).items] == ["ok"]


def test_recommended_wattage_is_not_applied_when_both_or_neither_are_in_the_quote():
    # 신규 조립처럼 둘 다 견적에 있으면 기존 합산 규칙만 쓴다(결과가 바뀌지 않는다).
    both = {"GPU": [_cand("GPU", "g", power_w=200, recommended_psu_w=850)],
            "파워": [_cand("파워", "p", wattage_w=650)]}
    assert _build(both, {}).link_check["power"] != "fail"                         # 권장 850W > 650W 지만 둘 다 견적 안
    # 둘 다 유지 부품이면(다른 슬롯만 견적) 사용자의 기존 조합 문제라 이번 견적의 실패로 세지 않는다.
    owned = {"GPU": {"name": "g", "specs": {"recommended_psu_w": 850}, "source": "catalog"},
             "파워": {"name": "p", "specs": {"wattage_w": 450}, "source": "text"}}
    assert _build({"쿨러": [_cand("쿨러", "c")]}, owned).link_check.get("power") != "fail"


def test_gpu_recommended_psu_reaches_candidate_specs():
    from src.repo.catalog_repo import _specs_from_row

    assert _specs_from_row("gpu", {"recommended_psu_w": 750})["recommended_psu_w"] == 750
    assert "recommended_psu_w" not in _specs_from_row("gpu", {"recommended_psu_w": None})

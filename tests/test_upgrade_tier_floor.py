"""업그레이드 추천은 지금 쓰는 CPU·GPU 보다 낮은 등급을 고르지 않는다 + 못 넘겼으면 그 사실을 알린다.

회귀 배경: RTX 4070 SUPER 를 쓰는 사람에게 GPU 업그레이드로 RX 7600 이 나왔다(현재 부품의 등급을 몰라 하한이 없었다).
"""
from __future__ import annotations

from types import SimpleNamespace

from src.dto import Candidate
from src.engine.owned_parts import current_part_tiers, upgrade_tier_notes


def _cand(slot, name, tier, **kw):
    return Candidate(slot=slot, product_key=name.lower().replace(" ", "-"), name=name, price=1, specs={"perf_tier": tier, **kw})


POOL = {
    "GPU": [_cand("GPU", "NVIDIA GeForce RTX 4070 SUPER", 8), _cand("GPU", "NVIDIA GeForce RTX 4070", 7),
            _cand("GPU", "AMD Radeon RX 7600", 6)],
    "CPU": [_cand("CPU", "AMD Ryzen 7 7800X3D", 8)],
}


def test_current_gpu_tier_is_found_from_the_users_text():
    found = current_part_tiers({"GPU": "RTX 4070 SUPER", "CPU": "AMD Ryzen 7 7800X3D"}, POOL, ["GPU"])
    # 교체 대상이 아닌 CPU 는 보지 않는다
    assert found == {"GPU": {"name": "NVIDIA GeForce RTX 4070 SUPER", "tier": 8.0, "keys": ["nvidia-geforce-rtx-4070-super"]}}


def test_similar_names_are_not_confused():
    # 4070 은 4070 SUPER 가 아니다 — 토큰이 정확히 같아야 대응한다(군더더기가 적은 쪽이 이긴다).
    found = current_part_tiers({"GPU": "RTX 4070"}, POOL, ["GPU"])
    assert found["GPU"]["name"] == "NVIDIA GeForce RTX 4070" and found["GPU"]["tier"] == 7.0


def test_unknown_or_missing_current_part_sets_no_floor():
    assert current_part_tiers({"GPU": "옛날 그래픽카드"}, POOL, ["GPU"]) == {}
    assert current_part_tiers({}, POOL, ["GPU"]) == {}
    assert current_part_tiers(None, POOL, ["GPU"]) == {}
    assert current_part_tiers({"RAM": "DDR5 32GB"}, POOL, ["RAM"]) == {}      # 등급이 있는 건 CPU·GPU 뿐


def test_notes_say_when_the_pick_is_not_an_improvement():
    current = {"GPU": {"name": "RTX 4070 SUPER", "tier": 8.0, "keys": []}}
    item = lambda tier: SimpleNamespace(slot="GPU", name="X", perf_tier=tier)  # noqa: E731
    assert upgrade_tier_notes(current, [item(9.0)]) == []
    same = upgrade_tier_notes(current, [item(8.0)])
    assert len(same) == 1 and "같아요" in same[0] and "알 수 없어요" in same[0]
    lower = upgrade_tier_notes(current, [item(6.0)])
    assert len(lower) == 1 and "낮아요" in lower[0]
    assert upgrade_tier_notes({}, [item(6.0)]) == []

"""화면 조건 필드(ConditionState.fields) — 해상도·게임이 화면에 나가고, 안 정한 해상도는 기본값을 "가정"으로 보여 준다."""
from __future__ import annotations

import pytest

from src.categories import load_category
from src.services import session_service as ss

CAT = load_category("computer")


def _fields(**values) -> dict[str, dict]:
    return {f["key"]: f for f in ss._build_fields(CAT, {"mode": "build", **values})}


@pytest.mark.parametrize("value,shown", [("FHD_144", "FHD 144Hz"), ("QHD_165", "QHD 165Hz"), ("4K", "4K")])
def test_a_chosen_resolution_is_confirmed_with_a_readable_label(value, shown):
    f = _fields(resolution=value)["resolution"]
    assert (f["value"], f["display"], f["status"]) == (value, shown, "confirmed")
    assert f["label"] == "해상도·주사율"


def test_an_unset_resolution_shows_the_default_the_engine_will_use_as_assumed():
    """안 정해도 추천은 기본값(FHD_144)으로 만들어진다 — 화면이 "확인 중"이면 실제와 어긋난다."""
    f = _fields()["resolution"]
    assert (f["value"], f["display"], f["status"]) == (CAT["defaults"]["resolution"], "FHD 144Hz", "assumed")


def test_games_are_listed_only_as_what_the_user_said():
    assert _fields()["games"]["status"] == "missing" and _fields()["games"]["display"] is None
    f = _fields(games=["사이버펑크 2077", "배틀그라운드"])["games"]
    assert f["status"] == "confirmed" and f["display"] == "사이버펑크 2077 · 배틀그라운드"


def test_only_fields_with_an_engine_default_become_assumed():
    """기본값이 있는 필드(해상도)만 가정으로 채운다 — 예산·용도·우선순위는 사용자가 안 정했으면 그대로 비어 있다."""
    fields = _fields()
    assert [k for k, f in fields.items() if f["status"] == "assumed"] == ["resolution"]
    assert all(fields[k]["status"] == "missing" for k in ("purpose", "budget_max", "priority"))


def test_the_new_fields_do_not_change_what_is_required_to_recommend():
    assert ss.compute_missing(CAT, {"mode": "build", "purpose": "game", "budget_max": 1_500_000, "priority": "value"}) == []

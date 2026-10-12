"""게임별 공식 최소·권장 사양 수집본(data/game_requirements.json) — 형식과 config 의 게임 표와의 짝."""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.engine import stage2_requirement as s2

DATA = Path(__file__).resolve().parents[1] / "data" / "game_requirements.json"


def _games() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))["games"]


def test_every_configured_game_has_collected_requirements():
    configured = set(s2.load_computer_rules()["requirements"]["game_titles"])
    assert set(_games()) == configured


def test_each_game_has_a_recommended_spec_with_cpu_gpu_ram_and_a_dated_source():
    for key, g in _games().items():
        rec = g["rec"]
        assert rec.get("cpu") and rec.get("gpu"), key
        assert isinstance(rec.get("ram_gb"), (int, float)) and rec["ram_gb"] > 0, key
        src = g["source"]
        assert src["url"].startswith("https://") and src["type"], key
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", src["checked_at"]), key


def test_minimum_spec_when_present_is_not_above_recommended_ram():
    for key, g in _games().items():
        mn = g["min"]
        if mn is None:           # 메이플스토리처럼 공식 페이지가 권장 한 세트만 주는 경우
            continue
        assert mn.get("cpu") and mn.get("gpu") and mn["ram_gb"] > 0, key
        assert mn["ram_gb"] <= g["rec"]["ram_gb"], key


def test_games_without_a_minimum_say_why():
    for key, g in _games().items():
        if g["min"] is None:
            assert g.get("note"), key

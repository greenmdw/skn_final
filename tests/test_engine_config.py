"""추천 엔진 점수식 설정(config/recommendation_engine.yaml) — 로더 검증과 가격 축 연결."""
from __future__ import annotations

import math

import pytest
import yaml

from src.dto import Candidate
from src.engine import engine_config, stage3b_rank
from src.engine.engine_config import EngineConfigError, load_engine_config, price_alpha


def test_repository_config_sets_alpha_2():
    cfg = load_engine_config()
    assert cfg["schema_version"] == 1 and cfg["config_version"].strip()
    assert price_alpha() == 2.0


def _write(tmp_path, data) -> object:
    path = tmp_path / "engine.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _valid(alpha=2):
    return {"schema_version": 1, "config_version": "t", "scoring": {"price_axis": {"alpha": alpha}}}


@pytest.mark.parametrize("data, match", [
    ({**_valid(), "schema_version": 2}, "schema_version"),
    ({**_valid(), "config_version": " "}, "config_version"),
    ({"schema_version": 1, "config_version": "t", "scoring": {}}, "alpha 없음"),
    (_valid(0), "양수"), (_valid(-1), "양수"), (_valid(True), "양수"), (_valid("2"), "양수"), (_valid(math.inf), "양수"),
])
def test_bad_config_is_rejected(tmp_path, data, match):
    with pytest.raises(EngineConfigError, match=match):
        load_engine_config(_write(tmp_path, data))


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(EngineConfigError, match="없음"):
        load_engine_config(tmp_path / "none.yaml")


def test_ranking_uses_the_configured_alpha(tmp_path, monkeypatch):
    """설정의 alpha가 바뀌면 3-B 가격 축이 그 값을 쓴다."""
    path = _write(tmp_path, _valid(3))
    monkeypatch.setattr(engine_config, "_ENGINE_CONFIG_PATH", path)
    cand = Candidate(product_key="ram", slot="RAM", name="RAM", price=50_000, specs={})
    scored = stage3b_rank._score(cand, 100_000.0, "RAM")
    assert scored.breakdown["가격"] == pytest.approx(1 / (1 + 0.5 ** 3))

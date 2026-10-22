"""scripts/eval_review_search.py — 지표 계산(단위)과, 테스트 DB에서 평가 전체가 도는지(db).

db 테스트는 MOCK 해시 벡터로 돈다 — 점수 자체가 아니라 정답 연결·단위 선별·보고서 모양을 본다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import psycopg
import pytest

from review_search_seed import seeded_reviews
from src.rag.embedding import OpenAIEmbedder

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eval_review_search", ROOT / "scripts" / "eval_review_search.py")
assert SPEC and SPEC.loader
eval_review_search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = eval_review_search
SPEC.loader.exec_module(eval_review_search)


# ── 지표 ──

@pytest.mark.unit
def test_random_hit_at_k():
    assert eval_review_search.random_hit_at_k(4, 1) == pytest.approx(0.75)     # 4건 중 3건을 고르면 정답 1건이 들 확률
    assert eval_review_search.random_hit_at_k(10, 2) == pytest.approx(1 - 56 / 120)
    assert eval_review_search.random_hit_at_k(3, 1) == 1.0


@pytest.mark.unit
def test_unit_metrics():
    ranked = [{"id": "a", "similarity": 0.6}, {"id": "b", "similarity": 0.5},
              {"id": "c", "similarity": 0.4}, {"id": "d", "similarity": 0.1}]
    metrics = eval_review_search.unit_metrics(ranked, {"b", "d"})
    assert metrics["hit"] is True
    assert metrics["precision"] == pytest.approx(1 / 3)
    assert metrics["reciprocal_rank"] == 0.5
    assert [row["relevant"] for row in metrics["top"]] == [False, True, False]
    assert eval_review_search.unit_metrics(ranked, {"d"})["hit"] is False


@pytest.mark.unit
def test_threshold_sweep_and_recommendation():
    units = [
        {"top": [{"similarity": 0.6, "relevant": True}, {"similarity": 0.2, "relevant": False}]},
        {"top": [{"similarity": 0.45, "relevant": True}, {"similarity": 0.3, "relevant": False}]},
    ]
    sweep = {row["threshold"]: row for row in eval_review_search.threshold_sweep(units, [0.0, 0.4, 0.5, 0.7])}
    assert sweep[0.0]["precision"] == 0.5 and sweep[0.0]["retention"] == 1.0
    assert sweep[0.4]["precision"] == 1.0 and sweep[0.4]["retention"] == 1.0 and sweep[0.4]["no_match_rate"] == 0.0
    assert sweep[0.5]["retention"] == 0.5 and sweep[0.5]["no_match_rate"] == 0.5
    assert sweep[0.7]["kept"] == 0 and sweep[0.7]["no_match_rate"] == 1.0
    assert eval_review_search.recommend_threshold(list(sweep.values()))["threshold"] == 0.4


# ── 테스트 DB에서 전체 평가 ──

@pytest.mark.db
def test_evaluate_links_observations_to_search_results():
    with seeded_reviews(os.environ["DATABASE_URL"]) as seed:
        rule_id = seed.conn.execute(
            "SELECT id FROM evidence.review_aspect_rule WHERE part_type='gpu' AND aspect_code='fan_quietness' LIMIT 1"
        ).fetchone()[0]
        product = seed.product("gpu")
        noisy = [seed.review(product, "그래픽카드 팬 소음이 심해요"), seed.review(product, "팬 소음이 좀 있는 편이에요")]
        for body in ["배송 빠르고 포장 꼼꼼해요", "디자인이 예뻐요", "가격 대비 만족합니다"]:
            seed.review(product, body)
        observations = []
        try:
            for doc in noisy:
                observations.append(seed.conn.execute(
                    "INSERT INTO evidence.review_aspect_observation"
                    "(document_id, rule_id, observation_text, direction, evidence_sentences) "
                    "VALUES (%s, %s, '팬 소음', 'negative', %s::jsonb) RETURNING id",
                    (doc, rule_id, json.dumps(["팬 소음"], ensure_ascii=False)),
                ).fetchone()[0])

            with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
                report = eval_review_search.evaluate(conn, OpenAIEmbedder(mock=True))
                conn.rollback()
        finally:
            if observations:
                seed.conn.execute("DELETE FROM evidence.review_aspect_observation WHERE id = ANY(%s::uuid[])",
                                  (observations,))

    units = [u for u in report["units"] if u["product_id"] == str(product)]
    assert len(units) == 1
    unit = units[0]
    assert (unit["part_type"], unit["aspect_code"], unit["reviews"], unit["relevant"]) == ("gpu", "fan_quietness", 5, 2)
    assert unit["hit"] is True and unit["reciprocal_rank"] == 1.0
    assert report["recommended_threshold"] is not None
    assert len(report["threshold_sweep"]) == len(eval_review_search.THRESHOLDS)
    assert report["index_check"]["min"] > 0.999          # MOCK으로 채운 벡터를 MOCK으로 다시 만들었다


@pytest.mark.unit
def test_main_refuses_mock_mode_without_flag(capsys):
    assert eval_review_search.main(["--out", "/dev/null"]) == 2      # 테스트는 MOCK_MODE=1
    assert "MOCK_MODE=0" in capsys.readouterr().err

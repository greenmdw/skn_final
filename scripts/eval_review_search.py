#!/usr/bin/env python3
"""리뷰 검색 품질 평가 — 관련도 하한(REVIEW_SEARCH_MIN_SIMILARITY)을 정하고 상위 3건 적중률을 잰다.

정답은 evidence.review_aspect_observation에서 가져온다. 어떤 리뷰에 (부품, 속성) 관측이 있으면 그 속성을
묻는 질문의 정답으로 본다 — 사람이 라벨을 붙이지 않아도 되고, 같은 방법으로 다시 돌릴 수 있다.
한계: 관측은 규칙에 맞는 명시적 경험만 기록하므로 관측이 없는 리뷰도 그 속성을 말할 수 있다. 그래서
여기서 재는 정밀도는 실제보다 낮게 잡히고, 정한 하한도 보수적인 쪽(높은 쪽)으로 치우칠 수 있다.

평가 단위는 (상품, 속성)이다. 그 상품에 그 속성의 정답 리뷰가 1건 이상 있고, embedding된 실제 리뷰가
MIN_REVIEWS건 이상인 경우만 센다(리뷰가 3건 이하면 상위 3건 적중이 공짜라 순위를 재는 의미가 없다).
질문은 속성마다 하나(QUESTIONS)이고, 관측이 적은 속성은 질문을 두지 않아 빠진다.

지표:
- hit@3·precision@3·MRR과, 같은 상품에서 무작위로 3건 골랐을 때의 hit@3(비교 기준)
- 하한 후보마다: 상위 3건 중 하한을 넘긴 결과의 정밀도, 정답 보존율(하한 없이 상위 3건에 든 정답 중
  남은 비율), 둘의 F1, 정답이 있는데 결과가 하나도 남지 않는(no_match가 되는) 단위의 비율
- 저장된 벡터를 지금 embedder로 다시 만들었을 때의 유사도(서비스의 일치 점검 기준 0.95의 근거)

사용(DB는 읽기만 한다. 유료 호출은 질문 수만큼의 질문 embedding과 점검 표본 embedding 한 번씩):
    MOCK_MODE=0 PYTHONPATH=. uv run python scripts/eval_review_search.py [--out outputs/review_search_eval.json]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOP_K = 3
MIN_REVIEWS = 4
THRESHOLDS = [round(0.05 * i, 2) for i in range(15)]    # 0.00 ~ 0.70
INDEX_CHECK_SAMPLE = 20

# (부품, 속성) → 사용자가 실제로 물을 법한 질문 하나. 관측이 5건 미만인 속성은 두지 않는다.
QUESTIONS: dict[tuple[str, str], str] = {
    ("case", "assembly_ease"): "케이스 조립하기 편한가요?",
    ("case", "build_quality"): "케이스 마감이나 만듦새는 괜찮나요?",
    ("cooler", "cooling"): "쿨러 냉각 성능 괜찮나요? 온도가 잘 잡히나요?",
    ("cooler", "fan_quietness"): "쿨러 팬 소음이 큰가요?",
    ("cooler", "installation_ease"): "쿨러 설치가 어렵나요?",
    ("cpu", "operational_stability"): "CPU 쓰다가 다운되거나 불안정한 적 있나요?",
    ("cpu", "thermal_management"): "CPU 온도나 발열은 어떤가요?",
    ("cpu", "workload_performance"): "게임이나 작업할 때 CPU 성능 충분한가요?",
    ("gpu", "coil_quietness"): "그래픽카드 코일 울림 있나요?",
    ("gpu", "fan_quietness"): "그래픽카드 팬 소음이 심한가요?",
    ("gpu", "gaming_performance"): "게임 성능 어떤가요? 프레임 잘 나오나요?",
    ("gpu", "operational_stability"): "그래픽카드 쓰다가 블랙스크린이나 드라이버 오류 있었나요?",
    ("gpu", "thermal_management"): "그래픽카드 온도는 어느 정도 나오나요?",
    ("keyboard", "connection_stability"): "키보드 연결이 끊기거나 인식 문제 있나요?",
    ("keyboard", "controls_usability"): "키보드 기능키나 설정 프로그램 쓰기 편한가요?",
    ("keyboard", "physical_usability"): "키 배열이나 손목 편안함은 어떤가요?",
    ("keyboard", "typing_feel"): "타건감 어떤가요?",
    ("keyboard", "typing_noise"): "타건 소리가 시끄럽나요?",
    ("mainboard", "assembly_ease"): "메인보드 조립하기 편한가요?",
    ("mainboard", "bios_usability"): "바이오스 설정 쉬운가요?",
    ("mainboard", "boot_memory_stability"): "부팅이나 램 인식 문제 없나요?",
    ("mainboard", "port_connectivity_ease"): "메인보드 포트 연결이나 단자 위치 괜찮나요?",
    ("monitor", "connection_stability"): "모니터 신호 끊김이나 연결 문제 있나요?",
    ("monitor", "controls_ergonomics"): "모니터 높이 조절이나 버튼 조작 편한가요?",
    ("monitor", "functional_reliability"): "모니터 불량이나 고장 없나요?",
    ("monitor", "image_quality"): "화질이나 색감 어떤가요?",
    ("monitor", "motion_response"): "주사율이나 잔상은 어떤가요?",
    ("mouse", "battery_runtime"): "마우스 배터리 오래 가나요?",
    ("mouse", "connection_stability"): "마우스 무선 연결 끊김 있나요?",
    ("mouse", "controls_usability"): "마우스 버튼이나 소프트웨어 설정 편한가요?",
    ("mouse", "ergonomics"): "마우스 그립감 어떤가요? 손이 편한가요?",
    ("mouse", "tracking_input"): "마우스 센서나 클릭감은 어떤가요?",
    ("psu", "cable_installation_ease"): "파워 케이블 정리나 설치 편한가요?",
    ("ram", "recognition_operation_stability"): "램 인식이나 XMP 안정성 문제 없나요?",
    ("speaker", "connection_controls"): "스피커 연결이나 조작 편한가요?",
    ("speaker", "functional_reliability"): "스피커 불량이나 고장 없나요?",
    ("speaker", "output_level"): "스피커 음량 충분한가요?",
    ("speaker", "sound_quality"): "스피커 음질 어떤가요?",
    ("speaker", "unwanted_noise"): "스피커 잡음이나 화이트 노이즈 있나요?",
    ("ssd", "io_performance"): "SSD 속도 빠른가요?",
    ("ssd", "recognition_operation_stability"): "SSD 인식 문제나 오류 없나요?",
}


# ── 지표 (순수 함수 — tests/test_eval_review_search.py) ──

def random_hit_at_k(n: int, relevant: int, k: int = TOP_K) -> float:
    """n건 중 정답 relevant건일 때 무작위로 k건 골라 정답이 하나라도 들어갈 확률."""
    k = min(k, n)
    return 1 - comb(n - relevant, k) / comb(n, k)


def unit_metrics(ranked: list[dict], relevant: set, k: int = TOP_K) -> dict:
    """ranked: 가까운 순 [{"id", "similarity"}] (상품의 embedding된 리뷰 전부). relevant: 정답 리뷰 id."""
    top = ranked[:k]
    top_relevant = sum(1 for row in top if row["id"] in relevant)
    first_rank = next((i for i, row in enumerate(ranked, 1) if row["id"] in relevant), None)
    return {
        "reviews": len(ranked),
        "relevant": len(relevant),
        "hit": top_relevant > 0,
        "precision": top_relevant / len(top),
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "random_hit": random_hit_at_k(len(ranked), len(relevant), k),
        "top": [{"similarity": row["similarity"], "relevant": row["id"] in relevant} for row in top],
    }


def threshold_sweep(units: list[dict], thresholds: list[float] = THRESHOLDS) -> list[dict]:
    """하한 후보마다 상위 k건 중 하한을 넘긴 결과의 정밀도·정답 보존율·F1·no_match 비율."""
    relevant_in_top = sum(1 for unit in units for row in unit["top"] if row["relevant"])
    out = []
    for t in thresholds:
        kept = [row for unit in units for row in unit["top"] if row["similarity"] >= t]
        kept_relevant = sum(1 for row in kept if row["relevant"])
        precision = kept_relevant / len(kept) if kept else 0.0
        retention = kept_relevant / relevant_in_top if relevant_in_top else 0.0
        f1 = 2 * precision * retention / (precision + retention) if precision + retention else 0.0
        no_match = sum(1 for unit in units if not any(row["similarity"] >= t for row in unit["top"]))
        out.append({
            "threshold": t, "kept": len(kept), "precision": round(precision, 4), "retention": round(retention, 4),
            "f1": round(f1, 4), "no_match_rate": round(no_match / len(units), 4) if units else 0.0,
        })
    return out


def recommend_threshold(sweep: list[dict]) -> dict:
    """F1이 가장 높은 하한(같으면 낮은 쪽 — 정답을 덜 버린다)."""
    return max(sweep, key=lambda row: (row["f1"], -row["threshold"]))


# ── DB·embedding ──

def _labels(conn) -> dict[tuple, set]:
    """(product_id, part_type, aspect_code) → 그 속성 관측이 있는 실제 리뷰 id."""
    rows = conn.execute(
        "SELECT DISTINCT d.product_id, r.part_type, r.aspect_code, o.document_id "
        "FROM evidence.review_aspect_observation o "
        "JOIN evidence.review_aspect_rule r ON r.id = o.rule_id "
        "JOIN evidence.review_document d ON d.id = o.document_id AND NOT d.is_synthetic"
    ).fetchall()
    labels: dict[tuple, set] = defaultdict(set)
    for product_id, part_type, aspect_code, document_id in rows:
        labels[(product_id, part_type, aspect_code)].add(document_id)
    return labels


def evaluate(conn, embedder) -> dict:
    from src.repo.review_embedding_repo import ReviewEmbeddingRepo

    repo = ReviewEmbeddingRepo(conn)
    labels = {key: ids for key, ids in _labels(conn).items() if (key[1], key[2]) in QUESTIONS}
    products = sorted({key[0] for key in labels})
    coverage = repo.coverage(products) if products else {}

    questions = sorted(set(QUESTIONS.values()))
    vectors = dict(zip(questions, embedder.embed(questions)))

    units, skipped = [], defaultdict(int)
    for (product_id, part_type, aspect_code), relevant in sorted(labels.items(), key=lambda kv: tuple(map(str, kv[0]))):
        if coverage[product_id]["embedded"] < MIN_REVIEWS:
            skipped["too_few_embedded_reviews"] += 1
            continue
        ranked = repo.search_nearest(vectors[QUESTIONS[(part_type, aspect_code)]], [product_id], per_product=10_000)
        relevant_embedded = relevant & {row["id"] for row in ranked}
        if not relevant_embedded:
            skipped["relevant_not_embedded"] += 1
            continue
        if len(relevant_embedded) == len(ranked):
            skipped["every_review_relevant"] += 1     # 무엇을 골라도 정답 — 순위를 잴 수 없다
            continue
        unit = unit_metrics(ranked, relevant_embedded)
        unit.update(product_id=str(product_id), part_type=part_type, aspect_code=aspect_code,
                    relevant_similarity=[row["similarity"] for row in ranked if row["id"] in relevant_embedded],
                    other_similarity=[row["similarity"] for row in ranked if row["id"] not in relevant_embedded])
        units.append(unit)

    sweep = threshold_sweep(units)
    by_part: dict[str, list] = defaultdict(list)
    for unit in units:
        by_part[unit["part_type"]].append(unit)

    def summary(group: list[dict]) -> dict:
        return {
            "units": len(group),
            "hit_at_3": round(statistics.mean(u["hit"] for u in group), 4),
            "precision_at_3": round(statistics.mean(u["precision"] for u in group), 4),
            "mrr": round(statistics.mean(u["reciprocal_rank"] for u in group), 4),
            "random_hit_at_3": round(statistics.mean(u["random_hit"] for u in group), 4),
        }

    relevant_sims = [s for u in units for s in u["relevant_similarity"]]
    other_sims = [s for u in units for s in u["other_similarity"]]
    return {
        "date": date.today().isoformat(),
        "embedding_model": getattr(embedder, "model", None),
        "questions": len(questions),
        "skipped_units": dict(skipped),
        "overall": summary(units) if units else None,
        "by_part_type": {part: summary(group) for part, group in sorted(by_part.items())},
        "similarity": {
            "relevant_median": round(statistics.median(relevant_sims), 4) if relevant_sims else None,
            "other_median": round(statistics.median(other_sims), 4) if other_sims else None,
        },
        "threshold_sweep": sweep,
        "recommended_threshold": recommend_threshold(sweep) if units else None,
        "index_check": _index_check(repo, embedder),
        "units": [{k: v for k, v in u.items() if k not in ("relevant_similarity", "other_similarity")} for u in units],
    }


def _index_check(repo, embedder) -> dict:
    """저장된 벡터를 지금 embedder로 다시 만들었을 때의 유사도 — 서비스 일치 점검 기준(0.95)의 근거."""
    rows = repo.conn.execute(
        "SELECT d.id, d.body FROM evidence.review_document d JOIN evidence.review_embedding e ON e.review_id = d.id "
        "ORDER BY d.id LIMIT %s", (INDEX_CHECK_SAMPLE,)
    ).fetchall()
    if not rows:
        return {"sample": 0}
    similarities = repo.stored_similarity(list(zip([r[0] for r in rows], embedder.embed([r[1] for r in rows]))))
    return {"sample": len(similarities), "min": round(min(similarities), 6), "median": round(statistics.median(similarities), 6)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="리뷰 검색 품질 평가(관측 기반 정답)")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / f"review_search_eval_{date.today():%Y%m%d}.json")
    parser.add_argument("--allow-mock", action="store_true", help="MOCK 해시 벡터로도 돌린다(스크립트 동작 확인용)")
    args = parser.parse_args(argv)

    import psycopg

    from src.config import DATABASE_URL
    from src.rag.embedding import OpenAIEmbedder

    embedder = OpenAIEmbedder()
    if embedder.mock and not args.allow_mock:
        print("오류: MOCK_MODE=1이면 해시 벡터라 평가 의미가 없습니다. MOCK_MODE=0으로 실행하세요.", file=sys.stderr)
        return 2
    dsn = os.environ.get("TEST_DATABASE_URL") or DATABASE_URL
    with psycopg.connect(dsn) as conn:
        report = evaluate(conn, embedder)
        conn.rollback()     # 읽기만 했다

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("overall", "similarity", "recommended_threshold", "index_check",
                                               "skipped_units")}, ensure_ascii=False, indent=2))
    for row in report["threshold_sweep"]:
        print(f"  t={row['threshold']:.2f} precision={row['precision']:.3f} retention={row['retention']:.3f} "
              f"f1={row['f1']:.3f} no_match={row['no_match_rate']:.3f}")
    print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

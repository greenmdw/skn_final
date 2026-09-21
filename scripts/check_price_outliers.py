"""가격 이상치 점검(읽기 전용) — 같은 종류·등급 부품끼리 견줘 유난히 비싸거나 싼 것을 나열한다.

이 스크립트는 DB 를 고치지 않는다. 결과는 사람이 원본(판매처 가격)과 대조해 볼 후보 목록이다 —
비싼 것이 곧 오류는 아니다(워크스테이션 GPU·플래그십 등은 정상적으로 높다).

사용:  python scripts/check_price_outliers.py [--ratio 3.0] [--limit 40]
DB 는 DATABASE_URL(기본 개발 DB)을 읽는다. 조회만 한다.

비교 기준(같은 집단의 중앙값 대비 배수):
  GPU  — catalog.gpu_spec.lineup 별       CPU  — catalog.cpu_spec.lineup 별
  RAM  — 메모리 규격별 GB 당 가격          그 밖 — 종류 전체(이질적이라 --ratio 의 2배만 넘으면 표시)
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_LATEST_PRICE = """
SELECT p.product_type, p.name, obs.price::bigint AS price, {group_expr} AS grp, {unit_expr} AS unit
FROM catalog.product_variant v
JOIN catalog.product p ON p.id = v.product_id
JOIN catalog.offer o ON o.variant_id = v.id AND o.status = 'active'
JOIN LATERAL (SELECT price FROM catalog.offer_observation
              WHERE offer_id = o.id AND quality_status = 'valid' ORDER BY observed_at DESC LIMIT 1) obs ON true
{joins}
WHERE p.product_type = %s
"""

# 종류별: (조인, 집단 식, 단위 식) — 단위는 비교할 값의 분모(RAM 은 GB). 없으면 1.
_KINDS = {
    "gpu": ("LEFT JOIN catalog.gpu_spec s ON s.product_id = p.id", "coalesce(s.lineup, '(등급 없음)')", "1"),
    "cpu": ("LEFT JOIN catalog.cpu_spec s ON s.product_id = p.id", "coalesce(s.lineup, '(등급 없음)')", "1"),
    "ram": ("LEFT JOIN catalog.ram_spec s ON s.product_id = p.id", "coalesce(s.memory_type, '(규격 없음)')",
            "greatest(coalesce(s.total_capacity_gb, 0), 1)"),
    "motherboard": ("", "'전체'", "1"), "case": ("", "'전체'", "1"), "ssd": ("", "'전체'", "1"),
    "psu": ("", "'전체'", "1"), "cooler": ("", "'전체'", "1"),
}


def outliers(conn, kind: str, ratio: float) -> list[dict]:
    joins, group_expr, unit_expr = _KINDS[kind]
    rows = conn.execute(_LATEST_PRICE.format(joins=joins, group_expr=group_expr, unit_expr=unit_expr), (kind,)).fetchall()
    groups: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for _kind, name, price, grp, unit in rows:
        groups[grp].append((name, int(price), int(price) / float(unit)))
    threshold = ratio if group_expr != "'전체'" else ratio * 2
    found = []
    for grp, items in groups.items():
        if len(items) < 3:                       # 비교 대상이 너무 적으면 판단하지 않는다
            continue
        median = statistics.median(v for _n, _p, v in items)
        for name, price, value in items:
            multiple = value / median if median else 0.0
            if multiple >= threshold or (multiple and multiple <= 1 / threshold):
                found.append({"kind": kind, "group": grp, "name": name, "price": price,
                              "multiple": round(multiple, 2), "median_unit": int(median), "n": len(items)})
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ratio", type=float, default=3.0, help="집단 중앙값의 몇 배부터 표시할지(기본 3.0)")
    parser.add_argument("--limit", type=int, default=40, help="최대 표시 개수")
    args = parser.parse_args(argv)
    if os.environ.get("TEST_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import psycopg
    from src.config import DATABASE_URL

    with psycopg.connect(DATABASE_URL) as conn:
        conn.read_only = True
        found = [row for kind in _KINDS for row in outliers(conn, kind, args.ratio)]
    found.sort(key=lambda r: -max(r["multiple"], 1 / r["multiple"] if r["multiple"] else 0))
    print(f"이상치 후보 {len(found)}건 (집단 중앙값의 {args.ratio}배 이상/이하, 전체 종류는 {args.ratio * 2}배)\n")
    print(f"{'종류':<12}{'집단':<16}{'배수':>6}{'가격':>13}  이름")
    for r in found[: args.limit]:
        print(f"{r['kind']:<12}{r['group']:<16}{r['multiple']:>6}{r['price']:>13,}  {r['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

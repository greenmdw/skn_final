#!/usr/bin/env python3
"""리뷰 요약 → evidence.* 적재 — data/review_summaries.json(scripts/gen_review_summaries.py 산출물).

지금까지 이 JSON은 엔진 [3-B]/[3-C]가 파일로 직접 읽기만 했고, evidence.review_summary는
비어 있었다(review_repo.py는 아직 SQL이 없는 스텁). 상품당 top_summaries[] 문장을
evidence.review_summary 한 행씩으로 적재해 근거 스키마 쪽에도 실제 데이터를 채운다.

author_ref/review_posted_at은 이 합성 데이터에 작성자·게시시각이 없어 NULL로 둔다
(0010_review_summary_relation_axis.sql 정책: 소스가 안 주면 NULL, 기본값으로 채우지 않는다 —
이 값들은 실제 온라인 리뷰 수집 경로가 채울 몫이다). 원문 보관 정책과도 맞다 — 여기 들어가는
summary는 이미 합성 문장이지 실제 리뷰 원문이 아니다.

PC 데이터는 db/seed_pc_parts_specs.py로 새 카탈로그를 먼저 적재한다. 확인된
data/review_catalog_map.csv 대응만 연결하고 나머지는 건너뛴다. 충돌한 기존 요약은
subject_id를 새 상품으로 옮겨 재실행도 멱등으로 처리한다.

    DATABASE_URL=... python db/seed_pc_parts_specs.py   # 먼저
    DATABASE_URL=... python db/seed_review_summaries.py
    DATABASE_URL=... python db/seed_review_summaries.py --input data/review_summaries.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn  # noqa: E402
from src.repo.product_repo import ProductRepo  # noqa: E402
from src.repo.review_repo import load_review_catalog_map  # noqa: E402

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "review_summaries.json"
_PROCESSING_VERSION = "gen_review_summaries-v1"
_SOURCE_NAME_BY_TYPE = {
    "marketplace": "합성 리뷰 요약 (판매처)",
    "community": "합성 리뷰 요약 (커뮤니티)",
}
_DEFAULT_SOURCE_TYPE = "marketplace"


def _slug(name: str) -> str:
    """영숫자만 남기고 전부 접어서 비교한다.

    review_summaries.json의 product_key("g-skill-...-32gb-2x16")와 catalog.product.model을
    seed_catalog.py 규칙대로 슬러그화한 값("g.skill-...-32gb-(2x16)")이 구분자를 서로 다르게
    써서(마침표 vs 하이픈, 괄호 유무) 정확히 안 맞는 RAM 5종이 있었다 — 하이픈까지 포함한
    모든 구두점을 지우고 순수 영숫자만 비교하면 구분자 차이와 무관하게 맞는다.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _source_id(repo: ProductRepo, name: str) -> UUID:
    row = repo._one("SELECT id FROM evidence.source WHERE name=%s", (name,))
    if row is not None:
        return row["id"]
    row = repo._one(
        "INSERT INTO evidence.source (name, source_type) VALUES (%s, 'derived') RETURNING id",
        (name,),
    )
    return row["id"]


def _subject_id(repo: ProductRepo, product_id: UUID) -> UUID:
    row = repo._one("SELECT id FROM evidence.review_subject WHERE product_id=%s", (product_id,))
    if row is not None:
        return row["id"]
    row = repo._one(
        "INSERT INTO evidence.review_subject (product_id) VALUES (%s) RETURNING id", (product_id,)
    )
    return row["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA_PATH,
                         help="review_summaries.json 경로 (기본: data/review_summaries.json)")
    args = parser.parse_args()
    entries = json.loads(args.input.read_text(encoding="utf-8"))
    with get_conn() as conn:
        repo = ProductRepo(conn)
        is_pc = args.input.resolve() == DATA_PATH.resolve()
        legacy_to_current = {legacy: current for current, legacy in load_review_catalog_map().items()} if is_pc else {}
        product_by_key = {}
        for row in repo._all("SELECT id, product_type, brand, model FROM catalog.product"):
            if not row["brand"] or not row["model"]:
                continue
            key = f"{row['product_type']}:{row['brand']}:{row['model']}".lower().replace(" ", "-")
            if key in product_by_key and product_by_key[key] != row["id"]:
                raise ValueError(f"카탈로그 product_key 중복: {key}")
            product_by_key[key] = row["id"]
        product_by_slug = {
            _slug(row["model"]): row["id"]
            for row in repo._all("SELECT id, model FROM catalog.product")
        }
        source_ids = {t: _source_id(repo, name) for t, name in _SOURCE_NAME_BY_TYPE.items()}

        written = skipped_products = 0
        for entry in entries:
            product_id = (product_by_key.get(legacy_to_current.get(entry["product_key"])) if is_pc
                          else product_by_slug.get(_slug(entry["product_key"])))
            if product_id is None:
                skipped_products += 1
                continue
            subject_id = _subject_id(repo, product_id)
            for i, s in enumerate(entry.get("top_summaries", [])):
                source_id = source_ids.get(s.get("source_type"), source_ids[_DEFAULT_SOURCE_TYPE])
                external_key = f"{entry['product_key']}:{i}"
                collected_at = datetime.strptime(s["collected_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                row = repo._one(
                    """INSERT INTO evidence.review_summary AS target
                    (subject_id, source_id, origin, external_review_key, original_url,
                     summary, collected_at, processing_version, cleaning_status)
                    VALUES (%s, %s, 'external', %s, %s, %s, %s, %s, 'retained')
                    ON CONFLICT (source_id, external_review_key, processing_version)
                    WHERE external_review_key IS NOT NULL DO UPDATE
                    SET subject_id=EXCLUDED.subject_id, updated_at=now()
                    WHERE target.subject_id IS DISTINCT FROM EXCLUDED.subject_id
                    RETURNING id""",
                    (subject_id, source_id, external_key, s.get("source_url"), s["text"],
                     collected_at, _PROCESSING_VERSION),
                )
                if row is not None:
                    written += 1
        print(f"seed_review_summaries: {written}개 요약 신규/재연결, "
              f"카탈로그 미매칭 상품 {skipped_products}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""DB setup — migrations, reference data, catalogs, actual review evidence.

새 PostgreSQL(로컬 conda/Docker 또는 RDS)에 DATABASE_URL만 맞추고 이 파일 하나만
실행하면 기준 데이터, 카탈로그, actual review documents/rules/observations/aggregates를
적재한다. 리뷰 적재에는 data/review_seed의 승인된 비공개 번들이 필요하다. 각 단계는
멱등이며 기존 집계가 있어도 동일한 입력의 재실행을 허용한다.

    DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/setup_all.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}
STEPS = [
    ("스키마 마이그레이션", [sys.executable, "db/migrate.py", "up"]),
    ("기준 데이터 (도메인·단위)", [sys.executable, "db/seed.py"]),
    ("컴퓨터 부품 카탈로그", [sys.executable, "db/seed_pc_parts_specs.py"]),
    ("부속기기 4종 카탈로그", [sys.executable, "db/seed_peripherals.py"]),
    ("실제 리뷰 원문·속성 규칙", [sys.executable, "db/seed_review_corpus.py", "--load-bundle", "--apply"]),
    ("리뷰 속성 관측", [sys.executable, "db/import_review_corpus_all_observations.py", "--apply"]),
    ("리뷰 속성 집계", [sys.executable, "db/rebuild_review_aspect_aggregates.py",
                           "--analysis-version", "review-aspect-v6-prod-20261002", "--apply"]),
]


def main() -> int:
    for label, cmd in STEPS:
        print(f"\n=== {label} ===", flush=True)
        result = subprocess.run(cmd, cwd=ROOT, env=_ENV)
        if result.returncode != 0:
            print(f"\n실패: {label} (종료 코드 {result.returncode}) — 여기서 중단합니다.")
            return result.returncode
    print("\n전부 완료. 앱을 실행하세요:  uvicorn src.api:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())

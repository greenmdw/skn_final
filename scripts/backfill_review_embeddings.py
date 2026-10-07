#!/usr/bin/env python3
"""리뷰 임베딩 백필 CLI — `python -m src.workers.review_embedding_batch`와 같다.

실제 CLI는 src/workers/review_embedding_batch.py의 main()에 있다. 배포 이미지(Dockerfile)는
scripts/를 복사하지 않아서, 서버 컨테이너 안에서는 모듈 형태로 실행해야 하기 때문이다:

    docker compose exec api python -m src.workers.review_embedding_batch --dry-run

이 파일은 저장소에서 이 경로로 부르던 사용법을 그대로 두려고 남긴 진입점이다.

사용:
    python scripts/backfill_review_embeddings.py [--limit N] [--batch-size N] [--dry-run] [--rebuild] [--allow-mock]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.workers.review_embedding_batch import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

"""리뷰 임베딩 백필 배치 — evidence.review_embedding에 없는 행을 채운다.

"임베딩 행이 없는 리뷰는 임베딩이 필요하다"가 유일한 규칙이다(0012_review_embedding_invalidate.sql
머리글, AGENTS.md). 그래서 쓰기 경로는 이 워커를 전혀 몰라도 된다 — INSERT는 그대로 두면 다음
배치 실행에서 저절로 뽑히고, body UPDATE는 트리거가 먼저 기존 임베딩을 지워 같은 규칙으로 다시
뽑힌다(src/services/review_preparation.py, db/seed_review_corpus.py 어느 쪽도 이 모듈을 import하지
않는다). 결합을 낮추는 대신 "뒤늦게 채워진다"는 지연을 받아들인다 — 이 배치를 주기적으로 돌려야
실제로 채워진다.

배치(batch_size)마다 커밋한다: 수천 건을 한 트랜잭션에 묶으면 중간에 죽었을 때(네트워크 타임아웃,
요금 한도 등) 이미 임베딩한 몫까지 롤백된다. 입력 오류가 난 배치는 분할해 문제 문서만 제외한다.
통신·서비스 오류는 배치 실패로 남겨 다음 실행에서 재시도한다. 이번 실행에서 시도한 id는 다시
고르지 않는다 — 실패하거나 저장 직전 본문이 바뀐 문서를 계속 고르는 무한 루프를 피한다.

**"배치마다 커밋"이 실제로 디스크에 남으려면 커넥션이 다음 둘 중 하나여야 한다**(psycopg 3의
`conn.transaction()`은 "이미 열려 있는 트랜잭션 블록 안"에서 불리면 진짜 커밋이 아니라
SAVEPOINT가 되기 때문이다):

1. `conn.autocommit = True`인 커넥션 — 배치마다의 `conn.transaction()`이 그 자체로 진짜
   BEGIN/COMMIT이 된다. 이 모듈의 `main()`(CLI)이 이렇게 연다.
2. 호출자가 이미 명시적으로 열어 둔 트랜잭션(`with conn.transaction(): ...` 안에서 이 함수를
   부름) — 이때는 배치마다 SAVEPOINT가 되고, 실제 커밋/롤백 시점은 호출자의 바깥 트랜잭션이
   끝날 때다. 호출자가 "배치별 내구성"의 책임을 스스로 진다는 뜻이고, 테스트의 격리용 롤백
   패턴이 바로 이 경우다.

`autocommit=False`이고 열린 트랜잭션도 없는 '평범한' 커넥션(예: `with psycopg.connect(dsn) as
conn:` 그대로)으로 부르면, 배치마다 커밋한 것처럼 보여도 실제로는 그 `with` 블록이 끝날 때 전부
한 번에 커밋된다 — 중간에 죽으면 이미 "성공"으로 센 배치까지 전부 사라진다. `run()`은 그 모양을
`_require_commit_safe_conn()`으로 미리 걸러 ValueError를 낸다.

**MOCK_MODE의 가짜 벡터는 테스트 DB에만 쓴다.** MOCK_MODE 기본값이 1이라, 환경변수 없이 돌리면
OpenAIEmbedder가 해시 벡터를 만든다. 이걸 개발·운영 DB에 저장하면 행이 생겼으니 나중의 실제 채우기가
그 리뷰들을 건너뛰고, 리뷰 검색은 실제 질문 벡터와 가짜 리뷰 벡터를 비교해 오류 없이 엉뚱한 결과를
낸다(review_embedding에는 모델 컬럼이 없어 데이터만 보고는 모른다). 그래서 이름에 "test"가 없는 DB에
가짜 벡터를 쓰려 하면 `run()`이 거절한다(`allow_mock=True`, CLI `--allow-mock`으로만 허용).

배포 이미지(Dockerfile)는 scripts/를 복사하지 않으므로 서버 컨테이너 안에서는 모듈로 실행한다:

    docker compose exec api python -m src.workers.review_embedding_batch --dry-run
    docker compose exec api python -m src.workers.review_embedding_batch [--limit N] [--batch-size N] [--rebuild]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from uuid import UUID

import psycopg

from src.rag.contracts import EmbeddingError, EmbeddingInputError
from src.repo.review_embedding_repo import ReviewEmbeddingRepo

log = logging.getLogger(__name__)


def _validated_options(limit: int | None, batch_size: int | None) -> int:
    from src.config import REVIEW_EMBEDDING_BATCH_SIZE

    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("limit은 0 이상의 정수여야 한다")
    size = REVIEW_EMBEDDING_BATCH_SIZE if batch_size is None else batch_size
    if type(size) is not int or size < 1:
        raise ValueError("batch_size는 1 이상의 정수여야 한다")
    return size


def _embed_batch(embedder, rows: list[dict]) -> tuple[list[tuple[UUID, str, list[float]]], list[UUID]]:
    """입력 오류는 분할해 격리한다. 서비스 오류에서 문서별 유료 재호출은 하지 않는다."""
    try:
        vectors = embedder.embed([row["body"] for row in rows])
        if len(vectors) != len(rows):
            raise EmbeddingError("embedding_result_count_mismatch")
    except EmbeddingInputError as exc:
        if len(rows) > 1:
            middle = len(rows) // 2
            left, left_failed = _embed_batch(embedder, rows[:middle])
            right, right_failed = _embed_batch(embedder, rows[middle:])
            return left + right, left_failed + right_failed
        log.warning("review embedding: invalid document %s (%s)", rows[0]["id"], exc)
    except EmbeddingError as exc:
        log.warning("review embedding: batch unavailable (%s)", exc)
    else:
        return [(row["id"], row["body"], vector) for row, vector in zip(rows, vectors)], []
    return [], [row["id"] for row in rows]


def _require_commit_safe_conn(conn) -> None:
    """배치별 커밋이 실제로 디스크에 남을 수 있는 커넥션인지 확인한다(모듈 docstring 참고).

    autocommit=True이면 통과. autocommit=False이면, 커넥션이 이미 트랜잭션 안에 있어야 통과한다
    (호출자가 명시적으로 `with conn.transaction():` 등을 열어 둔 상태 — 그 책임은 호출자가 진다).
    autocommit=False이면서 트랜잭션도 열려 있지 않은(IDLE) 경우만 막는다 — 배치마다 커밋한
    줄 알았는데 실제로는 호출자의 `with` 블록이 끝날 때 한 번에 커밋되는, 크래시에 안전하지 않은
    모양이기 때문이다."""
    if conn.autocommit:
        return
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return
    raise ValueError(
        "review_embedding_batch.run()은 배치마다 실제로 커밋돼야 한다 — autocommit=True인 "
        "커넥션을 넘기거나(이 모듈의 main() 참고), 호출자가 이미 열어 둔 "
        "트랜잭션 안에서 불러야 한다. 지금처럼 autocommit=False이고 트랜잭션도 열려 있지 않은 "
        "커넥션으로 부르면 모든 배치가 호출자의 `with psycopg.connect(...)` 블록이 끝날 때 한 번에 "
        "커밋돼, 중간에 죽으면 진행 상황이 전부 사라진다."
    )


def _require_real_vectors_outside_test_db(conn, embedder, allow_mock: bool) -> None:
    """가짜(MOCK) 벡터를 테스트용이 아닌 DB에 쓰려 하면 막는다(모듈 docstring 참고).
    테스트 DB는 이름에 "test"가 들어간다는 저장소 관례(AGENTS.md, tests/conftest.py)를 따른다."""
    if allow_mock or not getattr(embedder, "mock", False):
        return
    dbname = conn.info.dbname or ""
    if "test" in dbname.lower():
        return
    raise ValueError(
        f"MOCK_MODE의 가짜 벡터를 테스트용이 아닌 DB({dbname!r})에 저장하려 한다 — 저장하면 나중의 "
        "실제 채우기가 이 리뷰들을 건너뛰고, 리뷰 검색이 엉뚱한 결과를 낸다. 실제 embedding이면 "
        "MOCK_MODE=0과 OPENAI_API_KEY를 설정하고, 정말 가짜 벡터를 원하면 --allow-mock을 준다."
    )


def run(
    conn,
    embedder,
    *,
    limit: int | None = None,
    batch_size: int | None = None,
    dry_run: bool = False,
    rebuild: bool = False,
    allow_mock: bool = False,
) -> dict:
    """한 번 실행. {"embedded": n, "failed": n, "remaining": n, "batches": n}을 돌려준다.

    conn: autocommit=True 커넥션이거나, 호출자가 이미 열어 둔 트랜잭션 안에서 넘긴 커넥션이어야
        한다 — 그 외(평범한 autocommit=False·트랜잭션 미시작 커넥션)는 ValueError.
    limit: 이번 실행에서 시도할 최대 리뷰 수(0 이상, 기본 None = 남은 전부).
    batch_size: 한 번에 가져와 커밋할 리뷰 수(1 이상, 기본 config.REVIEW_EMBEDDING_BATCH_SIZE).
        batches는 가져온 배치 수이며 입력 오류 격리를 위한 추가 API 호출은 포함하지 않는다.
    dry_run: DB에 쓰지 않고 count_missing()만 보고한다 — embedder를 아예 부르지 않는다(API 비용 없음).
        쓰지 않으므로 conn의 커밋 방식을 따지지 않는다.
    rebuild: 시작 전 기존 임베딩을 전부 지우고 처음부터 다시 채운다(모델을 바꿨을 때 등).
        dry_run과 함께 줄 수 없다(지울지 말지가 모순이라 호출자 실수로 본다).
    allow_mock: embedder가 가짜(MOCK) 벡터를 만들 때도 테스트용이 아닌 DB에 쓰게 한다(기본 거절).
    저장 전 본문이 바뀐 문서는 다음 실행으로 미루며 embedded에는 실제 저장한 수만 센다.
    """
    if dry_run and rebuild:
        raise ValueError("dry_run과 rebuild는 함께 쓸 수 없다")

    batch_size = _validated_options(limit, batch_size)
    repo = ReviewEmbeddingRepo(conn)

    if dry_run:
        return {"embedded": 0, "failed": 0, "remaining": repo.count_missing(), "batches": 0}

    _require_real_vectors_outside_test_db(conn, embedder, allow_mock)
    _require_commit_safe_conn(conn)

    if rebuild:
        with conn.transaction():
            repo.delete_all()

    embedded = 0
    failed = 0
    batches = 0
    attempted_ids: list[UUID] = []
    remaining_budget = limit

    while remaining_budget is None or remaining_budget > 0:
        fetch_n = batch_size if remaining_budget is None else min(batch_size, remaining_budget)
        rows = repo.list_missing(fetch_n, exclude_ids=attempted_ids)
        if not rows:
            break
        batches += 1
        # 네트워크 호출이 끝난 뒤에만 본문 확인·저장 트랜잭션을 연다.
        ready, failed_ids = _embed_batch(embedder, rows)
        failed += len(failed_ids)
        embedded += repo.upsert_current_many(ready)
        attempted_ids.extend(row["id"] for row in rows)
        if remaining_budget is not None:
            remaining_budget -= len(rows)

    return {
        "embedded": embedded,
        "failed": failed,
        "remaining": repo.count_missing(),
        "batches": batches,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI — 결과를 JSON 한 줄로 내고, 실패한 리뷰가 있으면 1, 사용법 오류는 2로 끝난다.

    DB는 DATABASE_URL을 쓴다. TEST_DATABASE_URL이 있으면 그쪽이 먼저다 — 다른 CLI
    (scripts/check_price_outliers.py)와 같은 관례로, pytest 밖에서 돌려도 테스트 DB를 쓸 수 있게 한다.
    MOCK_MODE=1(기본)이면 가짜 벡터를 만들므로 테스트 DB에만 쓸 수 있다 — 실제로 채우려면
    MOCK_MODE=0과 OPENAI_API_KEY가 필요하다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.workers.review_embedding_batch",
        description="evidence.review_embedding이 없는 리뷰를 OpenAI 임베딩으로 채운다.",
    )
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 시도할 최대 리뷰 수(기본: 남은 전부)")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="배치 크기(기본: REVIEW_EMBEDDING_BATCH_SIZE 환경변수, 없으면 100)")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 남은 개수만 보고한다(API 호출 없음)")
    parser.add_argument("--rebuild", action="store_true", help="기존 임베딩을 전부 지우고 처음부터 다시 채운다")
    parser.add_argument("--allow-mock", action="store_true",
                        help="MOCK_MODE의 가짜 벡터를 테스트용이 아닌 DB에도 쓴다(기본 거절)")
    args = parser.parse_args(argv)
    if args.dry_run and args.rebuild:
        parser.error("--dry-run과 --rebuild는 함께 줄 수 없습니다")
    try:
        _validated_options(args.limit, args.batch_size)
    except ValueError as exc:
        parser.error(str(exc))

    from src.config import DATABASE_URL
    from src.rag.embedding import OpenAIEmbedder

    dsn = os.environ.get("TEST_DATABASE_URL") or DATABASE_URL
    # autocommit=True — 배치마다 실제로 커밋돼야 중간에 죽어도 그만큼 진행 상황이 남는다
    # (모듈 docstring, _require_commit_safe_conn 참고).
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            result = run(
                conn, OpenAIEmbedder(),
                limit=args.limit, batch_size=args.batch_size,
                dry_run=args.dry_run, rebuild=args.rebuild, allow_mock=args.allow_mock,
            )
        except ValueError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 2

    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())

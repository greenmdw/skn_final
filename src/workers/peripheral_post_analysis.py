"""사용기 분석 작업 — 커뮤니티 글의 변경을 감지해 체감 문장을 뽑고 근거를 쌓는다.

흐름과 규칙은 `src/services/peripheral_post_pipeline.py`, 대기 규칙은 `src/services/community_post_intake.py`,
추출은 `src/agent/peripheral_post_agent.py`, 저장은 `src/repo/peripheral_post_repo.py`(0015) 에 있다. 이 파일은 실행 진입점이다.

- 언어 모델을 쓰므로 `PERIPHERAL_POST_AGENT=1`, `MOCK_MODE=0`, 키가 있어야 돈다. 아니면 아무것도 분석하지 않고 종료한다
  (글은 대기 상태로 남는다). 하루 분석 한도는 `PERIPHERAL_POST_DAILY_LIMIT`(기본 200).
- 변경 감지: 평소에는 커뮤니티가 남긴 대기 기록(B-4)만 처리한다 — 글이 몇 만 건이어도 비용은 대기 글 수에 비례한다.
  전체 글을 훑어 놓친 변경을 찾는 안전망은 `PERIPHERAL_POST_FULL_SCAN_SECONDS`(기본 3600초)마다 한 번, 그리고 `--once` 때 돈다.
- 글마다 바로 커밋한다(autocommit 연결) — 중간에 죽어도 이미 끝낸 글의 근거와 분석 한도 기록이 남는다.
- 읽기는 `community.*`, 쓰기는 `engine.peripheral_post_*` 뿐이다. 근거 문장 임베딩은 분석 뒤에 이어서 채운다(`--no-embed` 로 끈다).

    python -m src.workers.peripheral_post_analysis --dry-run     # 무엇을 분석할지만 센다(모델 호출 없음, 쓰기 없음)
    python -m src.workers.peripheral_post_analysis --once        # 한 번 돌고 종료
    python -m src.workers.peripheral_post_analysis --once --post A3-1,A4-4   # 지정한 글만(실패한 글 재시도용)
    python -m src.workers.peripheral_post_analysis               # 주기적으로 계속(PERIPHERAL_POST_INTERVAL_SECONDS)

배포 이미지(Dockerfile)에서는 모듈로 실행한다: docker compose exec api python -m src.workers.peripheral_post_analysis --once
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import psycopg

from src import config
from src.agent import peripheral_post_agent
from src.rag.embedding import OpenAIEmbedder
from src.repo import peripheral_post_source as source
from src.services import community_post_intake as intake
from src.services import peripheral_evidence_embedding as embedding
from src.services import peripheral_post_pipeline as pipeline

log = logging.getLogger(__name__)


def dry_run(conn, state: pipeline.DbState) -> int:
    """대기에 올라갈 글을 처리 규칙으로 분류만 해 본다. 모델도 쓰기도 하지 않는다."""
    counts = {"analyze": 0, "skip": 0, "close": 0, "remove": 0}
    known = state.get_known()
    for post_id, signal in source.change_signal(conn).items():
        if known.get(post_id) == signal:
            continue
        record = state.intake.get(post_id) or intake.IntakeRecord(post_id=post_id)
        counts[intake.decide(record, source.load_snapshot(conn, post_id))] += 1
    print(f"대기에 올라갈 글: {sum(counts.values())}건 / 분석 {counts['analyze']} / 건너뜀 {counts['skip']} / "
          f"닫음 {counts['close']} / 근거 제거 {counts['remove']}")
    print(f"분석 {counts['analyze']}건은 모델 호출 {counts['analyze']}회다(하루 한도 {config.PERIPHERAL_POST_DAILY_LIMIT}).")
    print(f"임베딩이 필요한 근거 문장: {state.observations.count_missing_embeddings()}건")
    return 0


def run(conn, *, once: bool, dry: bool, embed: bool, only: set[str] | None = None) -> int:
    state = pipeline.DbState(conn)
    if dry:
        return dry_run(conn, state)
    if not peripheral_post_agent.available():
        print("사용기 분석을 돌릴 수 없다: PERIPHERAL_POST_AGENT=1, MOCK_MODE=0, OPENAI_API_KEY, LLM_MODEL 이 필요하다. "
              "글은 대기 상태로 남는다.", file=sys.stderr)
        return 2
    last_scan = float("-inf")          # 첫 실행은 항상 전체를 훑는다. 그 뒤로는 안전망 주기마다 한 번
    while True:
        scan = once or time.monotonic() - last_scan >= config.PERIPHERAL_POST_FULL_SCAN_SECONDS
        if scan:
            last_scan = time.monotonic()
        report = pipeline.run_once(conn, state, peripheral_post_agent.analyze,
                                   daily_limit=config.PERIPHERAL_POST_DAILY_LIMIT, only=only, scan=scan)
        line = (f"대기 {report.queued} / 분석 {report.analyzed} / 건너뜀 {report.skipped} / 닫음 {report.closed} / "
                f"근거 제거 {report.removed} / 오류 {report.errors}" + (" / 하루 한도에 닿음" if report.stopped_by_limit else ""))
        if embed and report.analyzed:
            try:
                result = embedding.backfill(conn, OpenAIEmbedder())
                line += f" / 임베딩 {result['embedded']}건(실패 {result['failed']}, 남음 {result['remaining']})"
            except ValueError as exc:       # 가짜 벡터를 개발·운영 DB 에 쓰려는 경우 등 — 분석 결과는 이미 저장됐다
                line += f" / 임베딩 건너뜀: {exc}"
        print(line)
        if once:
            return 0
        time.sleep(config.PERIPHERAL_POST_INTERVAL_SECONDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사용기 분석 작업")
    parser.add_argument("--once", action="store_true", help="한 번만 돌고 종료")
    parser.add_argument("--dry-run", action="store_true", help="분류만 한다(모델 호출·쓰기 없음)")
    parser.add_argument("--no-embed", action="store_true", help="근거 문장 임베딩을 채우지 않는다")
    parser.add_argument("--post", help="이 글만 분석한다(글 id 또는 예시 글 번호의 쉼표 목록, 예: A3-1,A4-4). 다른 대기 글은 그대로 둔다")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    dsn = os.environ.get("TEST_DATABASE_URL") or config.DATABASE_URL
    with psycopg.connect(dsn, autocommit=True) as conn:
        only = None
        if args.post:
            names = [x.strip() for x in args.post.split(",") if x.strip()]
            with conn.cursor() as cur:
                cur.execute("SELECT id::text FROM community.post WHERE id::text = ANY(%s) OR external_id = ANY(%s)", (names, names))
                only = {r[0] for r in cur.fetchall()}
            if not only:
                print(f"지정한 글을 찾지 못했다: {args.post}", file=sys.stderr)
                return 2
        return run(conn, once=args.once, dry=args.dry_run, embed=not args.no_embed, only=only)


if __name__ == "__main__":
    raise SystemExit(main())

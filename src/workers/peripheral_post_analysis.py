"""사용기 분석 작업 — 커뮤니티 글의 변경을 감지해 체감 문장을 뽑고 근거를 쌓는다.

흐름과 규칙은 `src/services/peripheral_post_pipeline.py`, 대기 규칙은 `src/services/community_post_intake.py`,
추출은 `src/agent/peripheral_post_agent.py` 에 있다. 이 파일은 실행 진입점이다.

- 언어 모델을 쓰므로 `PERIPHERAL_POST_AGENT=1`, `MOCK_MODE=0`, 키가 있어야 돈다. 아니면 아무것도 분석하지 않고 종료한다
  (글은 대기 상태로 남는다). 하루 분석 한도는 `PERIPHERAL_POST_DAILY_LIMIT`(기본 200).
- 상태는 `PERIPHERAL_POST_STATE_PATH` 의 JSON 파일에 저장된다(분석 결과 테이블 위치가 정해지기 전의 임시 방식). 서버는 이 파일을
  읽어 체감 점수에 반영한다.
- 읽기는 `community.*` 만 한다. 쓰기는 상태 파일뿐이다.

    python -m src.workers.peripheral_post_analysis --dry-run     # 무엇을 분석할지만 센다(모델 호출 없음, 파일 쓰기 없음)
    python -m src.workers.peripheral_post_analysis --once        # 한 번 돌고 종료
    python -m src.workers.peripheral_post_analysis               # 주기적으로 계속(PERIPHERAL_POST_INTERVAL_SECONDS)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from src import config
from src.agent import peripheral_post_agent
from src.db import close_pool, get_conn
from src.repo import peripheral_post_source as source
from src.services import community_post_intake as intake
from src.services import peripheral_post_pipeline as pipeline

log = logging.getLogger(__name__)


def dry_run(state: pipeline.PipelineState) -> int:
    """대기에 올라갈 글을 처리 규칙으로 분류만 해 본다. 모델도 파일도 건드리지 않는다."""
    counts = {"analyze": 0, "skip": 0, "close": 0, "remove": 0}
    with get_conn() as conn:
        signals = source.change_signal(conn)
        for post_id, signal in signals.items():
            if state.known.get(post_id) == signal:
                continue
            record = state.intake.get(post_id) or intake.IntakeRecord(post_id=post_id)
            counts[intake.decide(record, source.load_snapshot(conn, post_id))] += 1
    print(f"대기에 올라갈 글: {sum(counts.values())}건 / 분석 {counts['analyze']} / 건너뜀 {counts['skip']} / "
          f"닫음 {counts['close']} / 근거 제거 {counts['remove']}")
    print(f"분석 {counts['analyze']}건은 모델 호출 {counts['analyze']}회다(하루 한도 {config.PERIPHERAL_POST_DAILY_LIMIT}).")
    return 0


def run(*, once: bool, dry: bool) -> int:
    state = pipeline.FileState(config.PERIPHERAL_POST_STATE_PATH)
    if dry:
        return dry_run(state)
    if not peripheral_post_agent.available():
        print("사용기 분석을 돌릴 수 없다: PERIPHERAL_POST_AGENT=1, MOCK_MODE=0, OPENAI_API_KEY, LLM_MODEL 이 필요하다. "
              "글은 대기 상태로 남는다.", file=sys.stderr)
        return 2
    while True:
        with get_conn() as conn:
            report = pipeline.run_once(conn, state, peripheral_post_agent.analyze,
                                      daily_limit=config.PERIPHERAL_POST_DAILY_LIMIT)
        state.save()
        print(f"대기 {report.queued} / 분석 {report.analyzed} / 건너뜀 {report.skipped} / 닫음 {report.closed} / "
              f"근거 제거 {report.removed} / 오류 {report.errors}" + (" / 하루 한도에 닿음" if report.stopped_by_limit else ""))
        if once:
            return 0
        time.sleep(config.PERIPHERAL_POST_INTERVAL_SECONDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사용기 분석 작업")
    parser.add_argument("--once", action="store_true", help="한 번만 돌고 종료")
    parser.add_argument("--dry-run", action="store_true", help="분류만 한다(모델 호출·파일 쓰기 없음)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        return run(once=args.once, dry=args.dry_run)
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())

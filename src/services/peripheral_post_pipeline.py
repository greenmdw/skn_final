"""사용기 분석 작업 연결 — 변경 감지 → 대기 → 추출·확인 → 근거 저장 → 추천에 공급.

지금까지 따로 만든 부품을 한 줄로 잇는다.

```
community.post 변경 신호(peripheral_post_source.change_signal)
   └▶ sync_changes: 바뀐 글을 on_post_changed 로 대기에 올린다
        └▶ run_once: 대기 글을 하나씩 community_post_intake.process_one 으로 처리
             ├ analyze  → peripheral_post_agent.analyze(추출 + 확인 여섯 가지) → 근거 문장을 저장
             ├ remove   → 숨김·삭제·사용기 아님: 그 글의 근거를 지운다
             ├ close    → 분석 대상이 아닌 글: 바로 닫는다
             └ skip     → 본문·연결 제품이 그대로: 모델을 부르지 않는다
   └▶ current_observations(): 종류별 FeelObservation 목록 → 추천(peripherals_service)의 체감 점수 입력
```

상태(대기 기록·본 변경 신호·근거)는 `DbState` 가 `engine.peripheral_post_*` 테이블에 둔다(0015). 시험이나 DB 가 없는 곳에서는
`PipelineState`(메모리)를 쓴다. 이 모듈은 언어 모델을 직접 부르지 않는다 — 분석기(`analyzer`)를 인자로 받는다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol, Sequence

from src.engine.peripheral_feel import FeelObservation
from src.engine.peripheral_post_contract import PostInput
from src.repo import peripheral_post_source as source
from src.services import community_post_intake as intake

log = logging.getLogger(__name__)

Analyzer = Callable[[PostInput], "object"]      # peripheral_post_agent.analyze 와 같은 모양(ExtractionRun)
OTHER = "other"                                  # 속성이 없는 직접 겪은 문장 — 점수에는 쓰지 않고 문장 검색에만 쓴다


class ObservationStore(Protocol):
    def replace_post(self, post_id: str, items: list[tuple[str, FeelObservation]]) -> None: ...
    def remove_post(self, post_id: str) -> None: ...
    def by_kind(self, product_ids: Sequence[str] | None = None) -> dict[str, list[FeelObservation]]: ...


class MemoryObservationStore:
    def __init__(self) -> None:
        self._by_post: dict[str, list[tuple[str, FeelObservation]]] = {}

    def replace_post(self, post_id: str, items: list[tuple[str, FeelObservation]]) -> None:
        if items:
            self._by_post[post_id] = list(items)
        else:
            self._by_post.pop(post_id, None)

    def remove_post(self, post_id: str) -> None:
        self._by_post.pop(post_id, None)

    def by_kind(self, product_ids: Sequence[str] | None = None) -> dict[str, list[FeelObservation]]:
        wanted = set(product_ids) if product_ids is not None else None
        out: dict[str, list[FeelObservation]] = {}
        for post_id in sorted(self._by_post):
            for kind, obs in self._by_post[post_id]:
                if obs.attribute == OTHER or (wanted is not None and obs.product_id not in wanted):
                    continue
                out.setdefault(kind, []).append(obs)
        return out

    def post_ids(self) -> list[str]:
        return sorted(self._by_post)


# ── 상태(대기 기록 + 근거 + 이미 본 변경 신호) ────────────────────────────────────
@dataclass
class PipelineState:
    """메모리 상태(시험·DB 가 없는 곳)."""

    intake: intake.MemoryIntakeStore = field(default_factory=intake.MemoryIntakeStore)
    observations: MemoryObservationStore = field(default_factory=MemoryObservationStore)
    known: dict[str, str] = field(default_factory=dict)       # post_id → 이미 대기에 올린 변경 신호

    def get_known(self) -> dict[str, str]:
        return dict(self.known)

    def set_known(self, signals: dict[str, str], gone: Sequence[str] = ()) -> None:
        self.known.update(signals)
        for pid in gone:
            self.known.pop(pid, None)


class DbState:
    """`engine.peripheral_post_*` 에 상태를 둔다. 연결은 호출자가 연다(작업은 autocommit 연결을 쓴다)."""

    def __init__(self, conn) -> None:
        from src.repo.peripheral_post_repo import DbIntakeStore, DbObservationStore

        self.intake = DbIntakeStore(conn)
        self.observations = DbObservationStore(conn)

    def get_known(self) -> dict[str, str]:
        return self.intake.known_signals()

    def set_known(self, signals: dict[str, str], gone: Sequence[str] = ()) -> None:
        self.intake.set_signals(signals, gone)


# ── 한 번의 실행 ───────────────────────────────────────────────────────────
@dataclass
class RunReport:
    queued: int = 0                              # 이번에 대기에 올린 글 수
    analyzed: int = 0
    skipped: int = 0
    closed: int = 0
    removed: int = 0
    errors: int = 0
    stopped_by_limit: bool = False

    def total_processed(self) -> int:
        return self.analyzed + self.skipped + self.closed + self.removed + self.errors


def sync_changes(conn, state, now: datetime | None = None) -> int:
    """변경 신호가 이미 본 값과 다른 글을 대기에 올린다. 신호에서 사라진 글(하드 삭제)도 같은 방식으로 처리한다.
    반환: 대기에 올린 글 수."""
    signals = source.change_signal(conn)
    known = state.get_known()
    changed = [pid for pid, sig in signals.items() if known.get(pid) != sig]
    gone = [pid for pid in known if pid not in signals]
    for pid in [*changed, *gone]:
        intake.on_post_changed(pid, store=state.intake, now=now)
    state.set_known({pid: signals[pid] for pid in changed}, gone)
    return len(changed) + len(gone)


def run_once(
    conn, state, analyzer: Analyzer, *, daily_limit: int, max_posts: int = 100, now: datetime | None = None,
) -> RunReport:
    """대기 글을 `max_posts` 개까지 처리한다. 분석 한도에 닿으면 멈춘다."""
    report = RunReport(queued=sync_changes(conn, state, now))

    def _load_snapshot(post_id: str):
        return source.load_snapshot(conn, post_id)

    def _analyze(post_id: str) -> tuple[str, bool]:
        post = source.load_post_input(conn, post_id)
        if post is None:
            raise LookupError(f"글을 읽지 못했다: {post_id}")
        run = analyzer(post)
        state.observations.replace_post(post.post_id, run.analysis.evidence_with_kind(post))
        return run.input_hash, run.truncated

    failed_now: set[str] = set()          # 이번 실행에서 실패한 글은 다음 실행에서 다시 시도한다(바로 반복하지 않는다)
    for _ in range(max_posts):
        outcome = intake.process_one(
            state.intake, _load_snapshot, _analyze, daily_limit=daily_limit, now=now,
            on_cleared=state.observations.remove_post, exclude=failed_now,
        )
        if outcome is None:
            report.stopped_by_limit = any(r.post_id not in failed_now for r in state.intake.pending_oldest_first(50))
            break
        record, action = outcome
        if action == "error":
            failed_now.add(record.post_id)
        if action == "analyze":
            report.analyzed += 1
        elif action == "skip":
            report.skipped += 1
        elif action == "close":
            report.closed += 1
        elif action == "remove":
            report.removed += 1
        else:
            report.errors += 1
    return report


# ── 추천 쪽이 읽는 통로 ────────────────────────────────────────────────────
_source_override: Callable[[], dict[str, list[FeelObservation]]] | None = None


def set_observation_source(source_fn: Callable[[], dict[str, list[FeelObservation]]] | None) -> None:
    """체감 점수에 쓸 관측을 어디서 읽을지 바꾼다(시험용). None 이면 기본(DB)."""
    global _source_override
    _source_override = source_fn


def current_observations(conn, product_ids: Sequence[str] | None = None) -> dict[str, list[FeelObservation]]:
    """추천 요청이 체감 점수에 쓸 관측(종류 → 목록). 분석 결과가 없으면 빈 값 — 외부 리뷰 기준으로 계산된다.
    `product_ids` 를 주면(후보 제품들) 그 제품의 근거만 읽는다."""
    if _source_override is not None:
        return _source_override()
    from src.repo.peripheral_post_repo import DbObservationStore

    return DbObservationStore(conn).by_kind(product_ids)

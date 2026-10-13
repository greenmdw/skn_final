"""사용기 분석 작업 연결 — 변경 감지 → 대기 → 추출·확인 → 근거 저장 → 추천에 공급.

지금까지 따로 만든 부품을 한 줄로 잇는다.

```
community.post 변경 신호(peripheral_post_source.change_signal)
   └▶ sync_changes: 바뀐 글을 on_post_changed 로 대기에 올린다
        └▶ run_once: 대기 글을 하나씩 community_post_intake.process_one 으로 처리
             ├ analyze  → peripheral_post_agent.analyze(추출 + 확인 여섯 가지) → 관측을 저장
             ├ remove   → 숨김·삭제·사용기 아님: 그 글의 근거를 지운다
             ├ close    → 분석 대상이 아닌 글: 바로 닫는다
             └ skip     → 본문·연결 제품이 그대로: 모델을 부르지 않는다
   └▶ current_observations(): 종류별 FeelObservation 목록 → 추천(peripherals_service)의 체감 점수 입력
```

저장 위치(개발요청 R-1)가 정해지기 전이라 상태는 **파일 하나**(`FileState`, JSON)에 둔다. 분석 작업 프로세스가 쓰고 서버가
읽는다. 테이블이 정해지면 `IntakeStore`·`ObservationStore` 두 인터페이스만 DB 구현으로 바꾸면 된다. 이 모듈은 언어 모델을
직접 부르지 않는다 — 분석기(`analyzer`)를 인자로 받는다(시험에서는 가짜를 넣는다).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from src.engine.peripheral_feel import FeelObservation
from src.engine.peripheral_post_contract import PostInput
from src.repo import peripheral_post_source as source
from src.services import community_post_intake as intake

log = logging.getLogger(__name__)

Analyzer = Callable[[PostInput], "object"]      # peripheral_post_agent.analyze 와 같은 모양(ExtractionRun)


# ── 근거 저장소 ────────────────────────────────────────────────────────────
class ObservationStore(Protocol):
    def replace_post(self, post_id: str, items: list[tuple[str, FeelObservation]]) -> None: ...
    def remove_post(self, post_id: str) -> None: ...
    def by_kind(self) -> dict[str, list[FeelObservation]]: ...


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

    def by_kind(self) -> dict[str, list[FeelObservation]]:
        out: dict[str, list[FeelObservation]] = {}
        for post_id in sorted(self._by_post):
            for kind, obs in self._by_post[post_id]:
                out.setdefault(kind, []).append(obs)
        return out

    def post_ids(self) -> list[str]:
        return sorted(self._by_post)

    def export(self) -> dict:
        return {pid: [{"kind": kind, **_obs_to_dict(obs)} for kind, obs in items] for pid, items in self._by_post.items()}

    def restore(self, data: dict) -> None:
        self._by_post = {pid: [(row["kind"], _obs_from_dict(row)) for row in rows] for pid, rows in data.items()}


def _obs_to_dict(o: FeelObservation) -> dict:
    return {
        "author_id": o.author_id, "product_id": o.product_id, "attribute": o.attribute, "direction": o.direction,
        "side": o.side, "purposes": sorted(o.purposes), "situations": sorted(o.situations), "hand_size": o.hand_size,
        "evaluated_in": sorted(o.evaluated_in), "written_at": o.written_at.isoformat() if o.written_at else None,
        "is_example": o.is_example, "post_id": o.post_id, "quote_id": o.quote_id, "sentence": o.sentence,
        "photo_url": o.photo_url,
    }


def _obs_from_dict(d: dict) -> FeelObservation:
    return FeelObservation(
        author_id=d["author_id"], product_id=d["product_id"], attribute=d["attribute"], direction=d.get("direction"),
        side=d.get("side"), purposes=frozenset(d.get("purposes", [])), situations=frozenset(d.get("situations", [])),
        hand_size=d.get("hand_size"), evaluated_in=frozenset(d.get("evaluated_in", [])),
        written_at=datetime.fromisoformat(d["written_at"]) if d.get("written_at") else None,
        is_example=d.get("is_example", False), post_id=d.get("post_id"), quote_id=d.get("quote_id"),
        sentence=d.get("sentence"), photo_url=d.get("photo_url"),
    )


# ── 상태(대기 기록 + 근거 + 이미 본 변경 신호) ────────────────────────────────────
@dataclass
class PipelineState:
    intake: intake.MemoryIntakeStore = field(default_factory=intake.MemoryIntakeStore)
    observations: MemoryObservationStore = field(default_factory=MemoryObservationStore)
    known: dict[str, str] = field(default_factory=dict)       # post_id → 이미 대기에 올린 변경 신호


class FileState(PipelineState):
    """`PipelineState` 를 JSON 파일 하나에 저장한다(임시). 분석 작업이 쓰고 서버가 `load_observations` 로 읽는다."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.intake.restore(data.get("intake", {}))
            self.observations.restore(data.get("observations", {}))
            self.known = dict(data.get("known", {}))

    def save(self) -> None:
        payload = {"version": 1, "saved_at": datetime.now(timezone.utc).isoformat(), "known": self.known,
                   "intake": self.intake.export(), "observations": self.observations.export()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)           # 읽는 쪽이 쓰다 만 파일을 보지 않게 한다


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


def sync_changes(conn, state: PipelineState, now: datetime | None = None) -> int:
    """변경 신호가 이미 본 값과 다른 글을 대기에 올린다. 신호에서 사라진 글(하드 삭제)도 같은 방식으로 처리한다.
    반환: 대기에 올린 글 수."""
    signals = source.change_signal(conn)
    changed = [pid for pid, sig in signals.items() if state.known.get(pid) != sig]
    gone = [pid for pid in state.known if pid not in signals]
    for pid in [*changed, *gone]:
        intake.on_post_changed(pid, store=state.intake, now=now)
    state.known = dict(signals)
    return len(changed) + len(gone)


def run_once(
    conn, state: PipelineState, analyzer: Analyzer, *, daily_limit: int, max_posts: int = 100,
    now: datetime | None = None,
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
        state.observations.replace_post(post.post_id, run.analysis.observations_with_kind(post))
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
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, list[FeelObservation]]]] = {}
_source_override: Callable[[], dict[str, list[FeelObservation]]] | None = None


def set_observation_source(source_fn: Callable[[], dict[str, list[FeelObservation]]] | None) -> None:
    """서버가 체감 점수에 쓸 관측을 어디서 읽을지 바꾼다(시험·DB 저장소로 바꿀 때). None 이면 기본(파일)."""
    global _source_override
    _source_override = source_fn


def load_observations(path: str | os.PathLike[str]) -> dict[str, list[FeelObservation]]:
    """상태 파일에서 종류별 관측을 읽는다. 파일이 바뀐 때만 다시 읽는다(수정 시각 기준). 없거나 깨졌으면 빈 값."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    key = str(p.resolve())
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        store = MemoryObservationStore()
        store.restore(data.get("observations", {}))
        result = store.by_kind()
    except (OSError, ValueError, KeyError):
        log.warning("분석 상태 파일을 읽지 못했다: %s", p, exc_info=True)
        return {}
    with _cache_lock:
        _cache[key] = (mtime, result)
    return result


def current_observations() -> dict[str, list[FeelObservation]]:
    """추천 요청이 체감 점수에 쓸 관측(종류 → 목록). 분석 결과가 없으면 빈 값 — 외부 리뷰 기준으로 계산된다."""
    if _source_override is not None:
        return _source_override()
    from src.config import PERIPHERAL_POST_STATE_PATH

    return load_observations(PERIPHERAL_POST_STATE_PATH)

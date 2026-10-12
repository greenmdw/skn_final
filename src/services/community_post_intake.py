"""글 변경 알림과 분석 대기 규칙 — 작업지시서 W-2.

커뮤니티가 글을 저장한 뒤 `on_post_changed(post_id)` 를 부르면 여기서는 **기록만 남기고 바로 끝낸다.** 분석은 별도 작업이
대기 기록을 읽어 처리한다(`claim_next` → 분석 → `finish_ok`/`finish_error`). 이 모듈은 상태 전이 규칙만 갖고 있고
저장소는 `IntakeStore` 로 분리한다 — 대기 테이블의 위치와 마이그레이션 번호는 개발요청_추가_누적.md X-5·X-6 회신을 기다리는
중이라, 지금 제공하는 저장소는 시험용 `MemoryIntakeStore` 뿐이다. DB 저장소는 테이블이 정해지면 같은 인터페이스로 붙인다.

## 상태 전이 (W-2)

| 지금 | 알림이 오면 |
|---|---|
| 기록 없음 | `pending` 한 건 |
| `pending` | `requested_at` 만 갱신 |
| `done`, `failed` | `pending` 으로 되돌리고 `requested_at` 갱신(실패 횟수는 새 변경이므로 0으로) |
| `processing` | `requested_at` 만 갱신. 분석을 끝낼 때 `requested_at` 이 시작 시각보다 뒤면 다시 `pending` |

## 분석 대상 판단(`decide`)

| 글 상태 | 처리 |
|---|---|
| 글이 없다, 숨김·삭제·미게시 | `remove` — 이 글의 기존 근거를 지운다 |
| 사용기 게시판이 아니거나 카탈로그 제품이 하나도 연결되지 않음 | 분석한 적이 있으면 `remove`, 없으면 `close`(바로 done) |
| 본문·연결 제품의 해시가 마지막 분석과 같음 | `skip`(done) — 제목만 고친 수정 등 |
| 그 밖 | `analyze` |

비용 장치: 하루 분석 한도(`claim_next(daily_limit=…)`)를 넘으면 남은 글은 `pending` 으로 두고 다음 날 처리한다. 실패는
`max_attempts` 까지 다시 대기하고 그 뒤에는 `failed` 다. 이 함수들은 DB·언어 모델을 모른다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol
from uuid import UUID

log = logging.getLogger(__name__)

Status = Literal["pending", "processing", "done", "failed"]
Action = Literal["analyze", "skip", "close", "remove"]

REVIEW_BOARD = "review"
DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class IntakeRecord:
    post_id: str
    status: Status = "pending"
    requested_at: datetime | None = None     # 마지막으로 알림을 받은 시각
    started_at: datetime | None = None       # 마지막으로 분석을 시작한 시각
    processed_at: datetime | None = None     # 마지막으로 분석(또는 종료 처리)을 끝낸 시각
    attempts: int = 0
    last_error: str | None = None
    analyzed_hash: str | None = None         # 마지막으로 분석한 본문·연결 제품의 해시. 같으면 다시 분석하지 않는다
    truncated: bool = False                  # 마지막 분석이 길이 상한으로 본문을 잘랐는가


@dataclass(frozen=True)
class PostSnapshot:
    """처리 시점에 읽은 글의 현재 상태. 분석할 때 알림의 종류가 아니라 이 값으로 판단한다."""

    board: str
    status: str                  # published / hidden / deleted / draft
    catalog_product_count: int   # 카탈로그 제품이 연결된 수(목록에 없는 제품은 세지 않는다)
    content_hash: str


class IntakeStore(Protocol):
    def get(self, post_id: str) -> IntakeRecord | None: ...
    def put(self, record: IntakeRecord) -> None: ...
    def pending_oldest_first(self, limit: int) -> list[IntakeRecord]: ...
    def analyses_started_since(self, since: datetime) -> int: ...


class MemoryIntakeStore:
    """시험·개발용 저장소. 프로세스 안에만 남는다."""

    def __init__(self) -> None:
        self._rows: dict[str, IntakeRecord] = {}
        self._started: list[datetime] = []

    def get(self, post_id: str) -> IntakeRecord | None:
        return self._rows.get(post_id)

    def put(self, record: IntakeRecord) -> None:
        previous = self._rows.get(record.post_id)
        # 분석 시작 = 시도 횟수가 늘면서 processing 이 된 것(claim_next). 종료 처리는 시도 횟수를 늘리지 않는다.
        if (record.status == "processing" and record.started_at
                and record.attempts > (previous.attempts if previous else 0)):
            self._started.append(record.started_at)
        self._rows[record.post_id] = record

    def pending_oldest_first(self, limit: int) -> list[IntakeRecord]:
        rows = [r for r in self._rows.values() if r.status == "pending"]
        rows.sort(key=lambda r: (r.requested_at or datetime.min.replace(tzinfo=timezone.utc), r.post_id))
        return rows[:limit]

    def analyses_started_since(self, since: datetime) -> int:
        return sum(1 for t in self._started if t >= since)


_default_store: IntakeStore = MemoryIntakeStore()


def set_store(store: IntakeStore) -> None:
    """DB 저장소가 생기면 서버 시작 때 이 함수로 바꿔 끼운다."""
    global _default_store
    _default_store = store


def get_store() -> IntakeStore:
    return _default_store


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── 알림 ──────────────────────────────────────────────────────────────────
def on_post_changed(post_id: UUID | str, *, store: IntakeStore | None = None, now: datetime | None = None) -> None:
    """글이 게시·수정·삭제·숨김된 뒤 한 번씩 부른다. 어떤 변경인지는 받지 않는다(분석할 때 현재 상태를 읽는다).

    예외를 밖으로 내지 않는다 — 이 함수 때문에 글 저장이 실패하면 안 된다. 같은 글로 여러 번 불려도 기록은 한 건이다.
    글이 있는지는 확인하지 않는다(삭제도 같은 함수로 오기 때문이다)."""
    try:
        target = store or _default_store
        at = now or _now()
        key = str(post_id)
        current = target.get(key)
        if current is None:
            target.put(IntakeRecord(post_id=key, status="pending", requested_at=at))
        elif current.status == "processing":
            target.put(replace(current, requested_at=at))
        else:
            target.put(replace(current, status="pending", requested_at=at, attempts=0, last_error=None))
    except Exception:  # noqa: BLE001 — 글 저장을 막지 않는다. 기록만 남긴다.
        log.warning("on_post_changed 실패: post_id=%s", post_id, exc_info=True)


# ── 처리 규칙 ─────────────────────────────────────────────────────────────
def decide(record: IntakeRecord, snapshot: PostSnapshot | None) -> Action:
    """현재 글 상태로 이 글을 어떻게 처리할지 정한다(모듈 docstring 표)."""
    if snapshot is None or snapshot.status != "published":
        return "remove"
    if snapshot.board != REVIEW_BOARD or snapshot.catalog_product_count == 0:
        return "remove" if record.analyzed_hash is not None else "close"
    if record.analyzed_hash is not None and record.analyzed_hash == snapshot.content_hash:
        return "skip"
    return "analyze"


def claim_next(
    store: IntakeStore, *, daily_limit: int, now: datetime | None = None, scan: int = 50,
) -> IntakeRecord | None:
    """가장 오래 기다린 `pending` 글 하나를 `processing` 으로 바꿔 돌려준다. 하루 한도에 닿았거나 대기가 없으면 None.
    한도는 UTC 날짜 기준 분석 시작 건수다. 종료 처리(`close`·`skip`·`remove`)는 한도에 넣지 않는다 — 그건 분석을 시작하지 않는다."""
    at = now or _now()
    day_start = at.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if store.analyses_started_since(day_start) >= daily_limit:
        return None
    rows = store.pending_oldest_first(scan)
    if not rows:
        return None
    record = replace(rows[0], status="processing", started_at=at, attempts=rows[0].attempts + 1)
    store.put(record)
    return record


def finish_without_analysis(store: IntakeStore, record: IntakeRecord, action: Action, now: datetime | None = None) -> IntakeRecord:
    """`close`·`skip`·`remove` 로 끝낸다. 분석 도중 글이 다시 바뀌었으면(`requested_at` 이 시작보다 뒤) 다시 대기한다.
    `remove` 와 `close` 는 분석 해시를 지운다 — 근거를 뺐으니 나중에 같은 글이 돌아오면 다시 분석해야 한다."""
    at = now or _now()
    current = store.get(record.post_id) or record
    analyzed = None if action in ("remove", "close") else current.analyzed_hash
    done = replace(current, status="done", processed_at=at, last_error=None, analyzed_hash=analyzed, truncated=False)
    return _settle(store, current, done)


def finish_ok(
    store: IntakeStore, record: IntakeRecord, *, analyzed_hash: str, truncated: bool = False, now: datetime | None = None,
) -> IntakeRecord:
    at = now or _now()
    current = store.get(record.post_id) or record
    done = replace(current, status="done", processed_at=at, last_error=None, analyzed_hash=analyzed_hash, truncated=truncated)
    return _settle(store, current, done)


def finish_error(
    store: IntakeStore, record: IntakeRecord, error: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    now: datetime | None = None,
) -> IntakeRecord:
    """실패. 시도 횟수가 남았으면 다시 대기하고 아니면 `failed` 다."""
    current = store.get(record.post_id) or record
    status: Status = "pending" if current.attempts < max_attempts else "failed"
    out = replace(current, status=status, last_error=error[:500])
    store.put(out)
    return out


def _settle(store: IntakeStore, current: IntakeRecord, done: IntakeRecord) -> IntakeRecord:
    """분석 도중 글이 다시 바뀌었으면(알림이 시작 시각 뒤에 왔으면) done 대신 pending 으로 둔다."""
    changed_meanwhile = (
        current.requested_at is not None and current.started_at is not None and current.requested_at > current.started_at
    )
    out = replace(done, status="pending") if changed_meanwhile else done
    store.put(out)
    return out


def process_one(
    store: IntakeStore, load_snapshot: Callable[[str], PostSnapshot | None], analyze: Callable[[str], tuple[str, bool]],
    *, daily_limit: int, max_attempts: int = DEFAULT_MAX_ATTEMPTS, now: datetime | None = None,
) -> tuple[IntakeRecord, Action | str] | None:
    """대기 글 하나를 처리한다. 반환: (처리 후 기록, 한 일). 처리할 것이 없거나 한도에 닿았으면 None.

    `load_snapshot(post_id)` 는 글의 현재 상태, `analyze(post_id)` 는 분석을 돌려 (입력 해시, 잘렸는가)를 돌려준다.
    분석 쪽에서 난 예외는 기록하고 재시도 규칙을 따른다 — 이 함수는 예외를 밖으로 내지 않는다."""
    at = now or _now()
    snapshot_cache: dict[str, PostSnapshot | None] = {}

    def _peek(record: IntakeRecord) -> Action:
        snapshot_cache[record.post_id] = load_snapshot(record.post_id)
        return decide(record, snapshot_cache[record.post_id])

    # 종료 처리는 한도에 넣지 않는다 — 먼저 대기 글을 훑어 분석이 필요 없는 글부터 끝낸다.
    for candidate in store.pending_oldest_first(50):
        action = _peek(candidate)
        if action != "analyze":
            started = replace(candidate, status="processing", started_at=at)
            store.put(started)
            return finish_without_analysis(store, started, action, at), action
    record = claim_next(store, daily_limit=daily_limit, now=at)
    if record is None:
        return None
    try:
        analyzed_hash, truncated = analyze(record.post_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("사용기 분석 실패: post_id=%s", record.post_id, exc_info=True)
        return finish_error(store, record, f"{type(exc).__name__}: {exc}", max_attempts=max_attempts, now=at), "error"
    return finish_ok(store, record, analyzed_hash=analyzed_hash, truncated=truncated, now=at), "analyze"

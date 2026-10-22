"""사용기 분석 결과 저장소(0015) — 근거 문장 저장·교체, 제약, 임베딩 채우기와 가까운 문장 찾기, 대기 기록 왕복.

일회용 DB 가 필요하다. 임베딩은 가짜 임베더(결정적 벡터)로 넣는다."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from src.engine.peripheral_feel import FeelObservation
from src.services import community_post_intake as intake
from src.services import peripheral_evidence_embedding as embedding

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

DIM = 1536
T = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def conn():
    from src.db import get_conn

    with get_conn() as c:
        yield c


@pytest.fixture()
def product_id(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM catalog.product WHERE product_type = 'mouse' ORDER BY id LIMIT 1")
        return str(cur.fetchone()[0])


def _obs(product_id, post_id, sentence, attribute="grip", direction="good", side=None, **kw) -> FeelObservation:
    return FeelObservation(
        author_id=str(uuid4()), product_id=product_id, attribute=attribute, direction=direction, side=side,
        purposes=frozenset({"office"}), hand_size="small", written_at=T, post_id=post_id,
        quote_id=f"q-{abs(hash(sentence)) % 10**8}", sentence=sentence, **kw)


class OneHotEmbedder:
    """문장마다 정해진 차원 하나만 1 인 벡터. 같은 말이면 같은 방향이라 거리가 0 이다."""

    mock = False
    model = "test-onehot"

    def __init__(self, slots: dict[str, int]):
        self.slots = slots

    def embed(self, texts):
        out = []
        for text in texts:
            vec = [0.0] * DIM
            vec[self.slots.get(text, DIM - 1)] = 1.0
            out.append(vec)
        return out


def test_replace_post_swaps_rows_and_other_sentences_are_kept_but_not_scored(conn, product_id):
    from src.repo.peripheral_post_repo import DbObservationStore

    store, post = DbObservationStore(conn), str(uuid4())
    store.replace_post(post, [("mouse", _obs(product_id, post, "그립이 안정적입니다.")),
                              ("mouse", _obs(product_id, post, "땀이 차서 미끄러웠습니다.", attribute="other", direction=None))])
    scored = store.by_kind([product_id])["mouse"]
    assert [o.sentence for o in scored if o.post_id == post] == ["그립이 안정적입니다."]   # 기타 문장은 점수 입력이 아니다
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM engine.peripheral_post_evidence WHERE post_id = %s", (post,))
        assert cur.fetchone()[0] == 2                                                    # 문장 검색용으로는 저장돼 있다

    store.replace_post(post, [("mouse", _obs(product_id, post, "그립이 별로입니다.", direction="bad"))])
    again = [o for o in store.by_kind([product_id])["mouse"] if o.post_id == post]
    assert [(o.sentence, o.direction) for o in again] == [("그립이 별로입니다.", "bad")]
    store.remove_post(post)
    assert [o for o in store.by_kind([product_id]).get("mouse", []) if o.post_id == post] == []


def test_by_kind_reads_only_the_requested_products(conn, product_id):
    from src.repo.peripheral_post_repo import DbObservationStore

    store, post = DbObservationStore(conn), str(uuid4())
    store.replace_post(post, [("mouse", _obs(product_id, post, "한 문장입니다."))])
    assert [o.post_id for o in store.by_kind([product_id])["mouse"] if o.post_id == post]
    assert store.by_kind([str(uuid4())]) == {}


def test_value_constraint_rejects_rows_with_both_or_neither_value(conn, product_id):
    post = str(uuid4())
    base = ("INSERT INTO engine.peripheral_post_evidence (post_id, quote_id, product_id, kind, attribute, direction, side, "
            "author_id, sentence) VALUES (%s, %s, %s, 'mouse', %s, %s, %s, %s, '문장')")
    for attribute, direction, side in (("grip", "good", "quiet"), ("grip", None, None), ("other", "good", None)):
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(base, (post, f"q-{attribute}-{direction}-{side}", product_id, attribute, direction, side, str(uuid4())))


def test_embedding_backfill_nearest_and_cascade(conn, product_id):
    from src.repo.peripheral_post_repo import DbObservationStore

    store, post = DbObservationStore(conn), str(uuid4())
    store.replace_post(post, [("mouse", _obs(product_id, post, "클릭 소리가 조용합니다.")),
                              ("mouse", _obs(product_id, post, "배터리가 오래 갑니다.", attribute="battery"))])
    embedder = OneHotEmbedder({"클릭 소리가 조용합니다.": 3, "배터리가 오래 갑니다.": 7, "조용한 클릭": 3})

    assert embedding.backfill(conn, embedder, dry_run=True)["remaining"] >= 2
    result = embedding.backfill(conn, embedder, limit=1000)
    assert result["embedded"] >= 2 and result["failed"] == 0 and result["remaining"] == 0

    near = embedding.nearest_quote_ids(conn, embedder, "조용한 클릭", limit=5, kind="mouse")
    quiet = next(r for r in store.nearest(embedder.embed(["조용한 클릭"])[0], limit=50) if str(r["post_id"]) == post
                 and r["sentence"] == "클릭 소리가 조용합니다.")
    assert near[0] == quiet["quote_id"]                  # 같은 방향의 문장이 가장 가깝다

    store.replace_post(post, [])                          # 글의 근거를 지우면 임베딩도 함께 지워진다
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM engine.peripheral_post_evidence_embedding v "
                    "JOIN engine.peripheral_post_evidence e ON e.id = v.evidence_id WHERE e.post_id = %s", (post,))
        assert cur.fetchone()[0] == 0


def test_backfill_skips_failed_batches_and_continues(conn, product_id):
    from src.rag.contracts import EmbeddingError
    from src.repo.peripheral_post_repo import DbObservationStore

    store, post = DbObservationStore(conn), str(uuid4())
    store.replace_post(post, [("mouse", _obs(product_id, post, f"문장 {i}", attribute="battery")) for i in range(3)])

    class Flaky(OneHotEmbedder):
        calls = 0

        def embed(self, texts):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise EmbeddingError("embedding_unavailable")
            return super().embed(texts)

    # 다른 시험이 남긴 행도 채워질 수 있어 배치 크기를 크게 잡고, 실패한 배치는 건너뛰어 같은 실행에서 무한 반복하지 않는지만 본다
    result = embedding.backfill(conn, Flaky({}), batch_size=1000, limit=5000)
    assert result["failed"] > 0 and Flaky.calls >= 1


def test_mock_vectors_are_refused_outside_test_databases(conn, monkeypatch):
    class Mocked(OneHotEmbedder):
        mock = True

    class FakeInfo:
        dbname = "truefit"

    class FakeConn:
        info = FakeInfo()

    with pytest.raises(ValueError, match="가짜 벡터"):
        embedding._require_real_vectors(FakeConn(), Mocked({}), allow_mock=False)
    embedding._require_real_vectors(FakeConn(), Mocked({}), allow_mock=True)           # 명시적으로 허용하면 통과
    embedding._require_real_vectors(conn, Mocked({}), allow_mock=False)               # 테스트 DB 는 통과


def test_intake_record_roundtrip_and_pending_order(conn):
    from src.repo.peripheral_post_repo import DbIntakeStore

    store = DbIntakeStore(conn)
    a, b = str(uuid4()), str(uuid4())
    intake.on_post_changed(b, store=store, now=T)
    intake.on_post_changed(a, store=store, now=T.replace(hour=8))
    pending = [r.post_id for r in store.pending_oldest_first(1000) if r.post_id in (a, b)]
    assert pending == [a, b]                                           # 오래 기다린 글이 먼저
    claimed = intake.claim_next(store, daily_limit=10**6, now=T.replace(hour=10))
    assert claimed is not None and claimed.status == "processing" and claimed.attempts == 1
    assert store.get(claimed.post_id).started_at == T.replace(hour=10)
    out = intake.finish_ok(store, claimed, analyzed_hash="h", truncated=True, now=T.replace(hour=11))
    saved = store.get(claimed.post_id)
    assert (saved.status, saved.analyzed_hash, saved.truncated) == ("done", "h", True) == (out.status, out.analyzed_hash, out.truncated)


def test_known_signals_roundtrip_and_forget(conn):
    from src.repo.peripheral_post_repo import DbIntakeStore

    store, post = DbIntakeStore(conn), str(uuid4())
    intake.on_post_changed(post, store=store, now=T)
    assert post not in store.known_signals()                           # 아직 본 신호가 없다
    store.set_signals({post: "3:published:0::0"})
    assert store.known_signals()[post] == "3:published:0::0"
    store.set_signals({}, forget=[post])
    assert post not in store.known_signals()

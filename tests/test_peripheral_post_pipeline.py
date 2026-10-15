"""사용기 분석 작업 연결 — 변경 감지 → 대기 → 추출·확인 → 근거 저장 → 추천 공급.

일회용 DB 와 실제 커뮤니티 API 로 글을 만들고, 언어 모델 자리에는 가짜 분석기를 넣는다(모델을 부르지 않는다)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.engine import peripheral_post_contract as pc
from src.services import peripheral_post_pipeline as pipeline

DSN = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="일회용 DB 필요")

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
BODY = "그립이 손에 착 감겨서 안정적입니다. 클릭 소리는 조용한 편이에요. 무게는 63g입니다."


class FakeAnalyzer:
    """모델 대신: 본문에 있는 고정 문장 두 개를 뽑는다. 호출 횟수를 센다."""

    def __init__(self, items=None, review=True):
        self.calls: list[str] = []
        self.review = review
        self.items = items

    def __call__(self, post: pc.PostInput):
        from src.agent.peripheral_post_agent import ExtractionRun, content_hash

        self.calls.append(post.post_id)
        items = self.items if self.items is not None else [
            pc.ExtractedItem(sentence="그립이 손에 착 감겨서 안정적입니다.", product_index=0, attribute="grip", direction="good"),
            pc.ExtractedItem(sentence="무게는 63g입니다.", product_index=0, attribute="grip", direction="good",
                             spec_statement=True),
        ]
        extraction = pc.PostExtraction(is_review=self.review, reject_reason=None if self.review else "question",
                                       author=pc.ExtractedAuthor(purposes=["office"], hand_cm=17.0), items=items)
        return ExtractionRun(analysis=pc.analyze_post(post, extraction), truncated=False, input_hash=content_hash(post))


@pytest.fixture()
def community():
    from fastapi.testclient import TestClient

    from src.api import app
    from src.routers import community as router_module

    for name in ("COMMUNITY_POST_LIMIT_PER_MIN", "COMMUNITY_COMMENT_LIMIT_PER_MIN", "COMMUNITY_LIKE_LIMIT_PER_MIN",
                 "COMMUNITY_UPLOAD_LIMIT_PER_MIN"):
        setattr(router_module, name, 1000)
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"pipe-{uuid4().hex[:12]}@example.test", "password": "abcd1234",
                                      "display_name": "분석연결", "terms_agreed": True, "privacy_agreed": True,
                                      "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c


def _review_post(c, *, board="review", body=BODY, with_product=True, custom_only=False) -> str:
    products = []
    if custom_only:
        products = [{"custom_product_name": "OO사 무선 마우스 X1", "product_kind": "마우스"}]
    elif with_product:
        item = c.get("/catalog/products", params={"kind": "mouse", "q": "PRO X", "limit": 1}).json()["items"][0]
        products = [{"product_id": item["id"], "product_kind": "mouse"}]
    r = c.post("/community/posts", json={"board_type": board, "title": "써 본 후기", "body": body, "publish": True,
                                         "products": products})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _state_for(post_ids) -> pipeline.PipelineState:
    """이 시험이 만든 글만 보게, 다른 글은 이미 본 것으로 표시한 상태."""
    from src.db import get_conn
    from src.repo import peripheral_post_source as source

    state = pipeline.PipelineState()
    with get_conn() as conn:
        state.known = {pid: sig for pid, sig in source.change_signal(conn).items() if pid not in set(post_ids)}
    return state


def _run(state, analyzer, **kw):
    from src.db import get_conn

    with get_conn() as conn:
        return pipeline.run_once(conn, state, analyzer, daily_limit=kw.pop("daily_limit", 100), now=NOW, **kw)


def test_review_post_is_analyzed_and_observations_are_stored_by_kind(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    report = _run(state, analyzer)
    assert (report.queued, report.analyzed, report.errors) == (1, 1, 0)
    by_kind = state.observations.by_kind()
    assert list(by_kind) == ["mouse"]
    (obs,) = by_kind["mouse"]                      # 스펙 문장은 제외되고 체감 문장 하나만 남는다
    assert obs.attribute == "grip" and obs.direction == "good" and obs.post_id == post_id
    assert obs.sentence == "그립이 손에 착 감겨서 안정적입니다." and obs.hand_size == "small"
    assert obs.quote_id and obs.is_example is False
    assert state.intake.get(post_id).status == "done" and state.intake.get(post_id).analyzed_hash


def test_unchanged_post_is_not_analyzed_again(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    _run(state, analyzer)
    second = _run(state, analyzer)
    assert second.queued == 0 and second.analyzed == 0
    assert analyzer.calls == [post_id]            # 모델은 한 번만 불렸다


def test_viewing_a_post_does_not_trigger_reanalysis(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    _run(state, analyzer)
    for _ in range(3):
        community.get(f"/community/posts/{post_id}")
    assert _run(state, analyzer).queued == 0


def test_edited_post_is_reanalyzed_and_observations_replaced(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    _run(state, analyzer)
    current = community.get(f"/community/posts/{post_id}").json()
    new_body = "그립이 아주 불편합니다. " + BODY
    r = community.patch(f"/community/posts/{post_id}", json={"body": new_body, "version": current["version"]})
    assert r.status_code == 200, r.text
    analyzer.items = [pc.ExtractedItem(sentence="그립이 아주 불편합니다.", product_index=0, attribute="grip", direction="bad")]
    report = _run(state, analyzer)
    assert report.analyzed == 1 and len(analyzer.calls) == 2
    (obs,) = state.observations.by_kind()["mouse"]
    assert obs.direction == "bad" and obs.sentence == "그립이 아주 불편합니다."


def test_hidden_post_loses_its_observations(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    _run(state, analyzer)
    assert state.observations.by_kind()
    r = community.delete(f"/community/posts/{post_id}")       # 작성자가 지운다(숨김은 관리자만 할 수 있다)
    assert r.status_code == 204, r.text
    report = _run(state, analyzer)
    assert report.removed == 1
    assert state.observations.by_kind() == {}
    assert len(analyzer.calls) == 1               # 숨김 처리에는 모델을 부르지 않는다


def test_non_review_post_is_closed_without_calling_the_model(community):
    post_id = _review_post(community, board="free", with_product=False)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    report = _run(state, analyzer)
    assert report.closed == 1 and analyzer.calls == []
    assert state.intake.get(post_id).status == "done"


def test_review_without_catalog_product_is_closed(community):
    """목록에 없는 제품만 연결한 사용기는 점수를 낼 수 없어 모델을 부르지 않고 닫는다."""
    post_id = _review_post(community, custom_only=True)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    report = _run(state, analyzer)
    assert analyzer.calls == [] and report.closed == 1


def test_model_reports_not_a_review_clears_the_post(community):
    post_id = _review_post(community)
    state, analyzer = _state_for([post_id]), FakeAnalyzer(review=False)
    report = _run(state, analyzer)
    assert report.analyzed == 1 and state.observations.by_kind() == {}


def test_daily_limit_defers_remaining_posts(community):
    ids = [_review_post(community) for _ in range(3)]
    state, analyzer = _state_for(ids), FakeAnalyzer()
    first = _run(state, analyzer, daily_limit=2)
    assert first.analyzed == 2 and first.stopped_by_limit is True
    assert len([p for p in ids if state.intake.get(p).status == "pending"]) == 1
    from src.db import get_conn

    with get_conn() as conn:
        second = pipeline.run_once(conn, state, analyzer, daily_limit=2, now=NOW + timedelta(days=1))
    assert second.analyzed == 1


def test_model_errors_retry_then_fail(community):
    post_id = _review_post(community)
    state = _state_for([post_id])

    def boom(post):
        raise RuntimeError("quota")

    first = _run(state, boom)
    assert first.errors == 1                         # 한 번의 실행 안에서는 같은 글을 곧바로 다시 시도하지 않는다
    assert state.intake.get(post_id).status == "pending" and state.intake.get(post_id).attempts == 1
    assert "quota" in state.intake.get(post_id).last_error
    _run(state, boom)
    assert state.intake.get(post_id).status == "pending" and state.intake.get(post_id).attempts == 2
    _run(state, boom)
    assert state.intake.get(post_id).status == "failed"        # 세 번째 시도까지 실패하면 failed
    assert state.observations.by_kind() == {}


def _mine(by_kind, post_id, kind="mouse"):
    """DB 상태는 시험들이 함께 쓰므로 이 시험이 만든 글의 근거만 본다."""
    return [o for o in by_kind.get(kind, []) if o.post_id == post_id]


def _day(offset: int):
    """분석 한도는 날짜별로 센다. 시험끼리 섞이지 않게 먼 미래의 서로 다른 날을 쓴다."""
    return datetime(2040, 1, 1, 9, 0, tzinfo=timezone.utc) + timedelta(days=offset)


def _isolated_db_state(conn, post_ids):
    """DB 상태: 이 시험이 만든 글만 보게, 다른 글은 이미 본 것으로 표시한다(다른 시험이 만든 글을 분석하지 않도록)."""
    from src.repo import peripheral_post_source as source

    keep = {str(p) for p in post_ids}
    with conn.cursor() as cur:
        for pid, sig in source.change_signal(conn).items():
            if pid not in keep:
                cur.execute(
                    "INSERT INTO engine.peripheral_post_intake (post_id, status, change_signal, analyzed_hash) "
                    "VALUES (%s, 'done', %s, 'seen') ON CONFLICT (post_id) DO UPDATE SET change_signal = EXCLUDED.change_signal, "
                    "status = 'done', analyzed_hash = 'seen'",   # 커뮤니티가 글 변경을 알리면(B-4) 다른 시험의 글도 이미 대기 중이다
                    (pid, sig))
    return pipeline.DbState(conn)


def test_db_state_runs_the_whole_flow_and_survives_a_new_connection(community):
    from src.db import get_conn

    post_id = _review_post(community)
    analyzer = FakeAnalyzer()
    with get_conn() as conn:
        state = _isolated_db_state(conn, [post_id])
        report = pipeline.run_once(conn, state, analyzer, daily_limit=100, now=_day(1))
        assert (report.queued, report.analyzed, report.errors) == (1, 1, 0)
    with get_conn() as conn:                         # 새 연결 = 서버가 다시 시작된 것과 같다
        state = pipeline.DbState(conn)
        record = state.intake.get(post_id)
        assert record.status == "done" and record.analyzed_hash and record.attempts == 1
        assert state.get_known()[post_id]
        (obs,) = _mine(state.observations.by_kind(), post_id)
        assert obs.sentence == "그립이 손에 착 감겨서 안정적입니다."
        again = pipeline.run_once(conn, state, analyzer, daily_limit=100, now=_day(1))
        assert again.queued == 0 and again.analyzed == 0
    assert analyzer.calls == [post_id]               # 다시 시작해도 모델을 다시 부르지 않는다


def test_db_state_daily_limit_counts_analyses_across_connections(community):
    from src.db import get_conn

    ids = [_review_post(community) for _ in range(2)]
    analyzer = FakeAnalyzer()
    with get_conn() as conn:
        state = _isolated_db_state(conn, ids)
        first = pipeline.run_once(conn, state, analyzer, daily_limit=1, now=_day(10))
        assert first.analyzed == 1 and first.stopped_by_limit is True
    with get_conn() as conn:
        state = pipeline.DbState(conn)
        same_day = pipeline.run_once(conn, state, analyzer, daily_limit=1, now=_day(10) + timedelta(hours=3))
        assert same_day.analyzed == 0 and same_day.stopped_by_limit is True
        next_day = pipeline.run_once(conn, state, analyzer, daily_limit=1, now=_day(11))
        assert next_day.analyzed == 1


def test_db_state_removes_evidence_when_the_post_is_deleted(community):
    from src.db import get_conn

    post_id = _review_post(community)
    analyzer = FakeAnalyzer()
    with get_conn() as conn:
        state = _isolated_db_state(conn, [post_id])
        pipeline.run_once(conn, state, analyzer, daily_limit=10, now=_day(20))
        assert _mine(state.observations.by_kind(), post_id)
    assert community.delete(f"/community/posts/{post_id}").status_code == 204
    with get_conn() as conn:
        state = pipeline.DbState(conn)
        report = pipeline.run_once(conn, state, analyzer, daily_limit=10, now=_day(20))
        assert report.removed == 1
        assert _mine(state.observations.by_kind(), post_id) == []
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM engine.peripheral_post_evidence WHERE post_id = %s", (post_id,))
            assert cur.fetchone()[0] == 0


def test_server_feeds_the_recommendation_from_the_database(community, monkeypatch):
    """분석 작업이 DB 에 쓴 근거 → 서버가 후보 제품의 근거만 읽어 추천의 체감 점수 입력으로 넘긴다."""
    from src import schemas
    from src.db import get_conn
    from src.engine import peripheral_select
    from src.services import peripherals_service

    post_id = _review_post(community)
    with get_conn() as conn:
        state = _isolated_db_state(conn, [post_id])
        pipeline.run_once(conn, state, FakeAnalyzer(), daily_limit=10, now=_day(30))

    seen: dict = {}
    original = peripheral_select.run_peripherals

    def spy(values, *args, **kwargs):
        seen.update(values)
        return original(values, *args, **kwargs)

    monkeypatch.setattr(peripheral_select, "run_peripherals", spy)
    with get_conn() as conn:
        peripherals_service.recommend(conn, schemas.PeripheralsRecommendIn(kinds=["mouse"]), None)
    assert _mine(seen["peripheral_feel_observations"], post_id)
    # 다른 종류만 요청하면 이 제품의 근거는 읽지 않는다(후보 제품만 읽는다)
    seen.clear()
    with get_conn() as conn:
        peripherals_service.recommend(conn, schemas.PeripheralsRecommendIn(kinds=["keyboard"]), None)
    assert "mouse" not in seen["peripheral_feel_observations"]


def test_observation_source_can_be_replaced_in_tests():
    from src.engine.peripheral_feel import FeelObservation

    obs = FeelObservation(author_id="u", product_id="p", attribute="grip", direction="good")
    pipeline.set_observation_source(lambda: {"mouse": [obs]})
    try:
        assert pipeline.current_observations(None) == {"mouse": [obs]}
    finally:
        pipeline.set_observation_source(None)


def test_image_marker_only_edit_is_not_analyzed_again_and_analyzer_sees_plain_text(community):
    """본문 서식·이미지 마커는 분석 입력에서 빠진다. 마커 줄만 추가한 수정(version 은 오른다)은 다시 분석하지 않는다."""
    marked = "## 써 본 느낌\n- **" + BODY + "**"
    post_id = _review_post(community, body=marked)
    state, analyzer = _state_for([post_id]), FakeAnalyzer()
    assert _run(state, analyzer).analyzed == 1
    current = community.get(f"/community/posts/{post_id}").json()
    with_image = marked + "\n\n![책상 위 모습](image:00000000-0000-0000-0000-000000000000)\n"
    r = community.patch(f"/community/posts/{post_id}", json={"body": with_image, "version": current["version"]})
    assert r.status_code == 200, r.text
    again = _run(state, analyzer)
    assert again.analyzed == 0 and analyzer.calls == [post_id]


def test_only_option_analyzes_just_the_given_posts_and_leaves_the_rest_pending(community):
    first, second = _review_post(community), _review_post(community)
    state, analyzer = _state_for([first, second]), FakeAnalyzer()
    report = _run(state, analyzer, only={first})
    assert report.analyzed == 1 and analyzer.calls == [first]
    assert state.intake.get(second).status == "pending"           # 건드리지 않고 대기로 남는다
    assert _run(state, analyzer).analyzed == 1 and analyzer.calls == [first, second]


def test_without_scan_only_waiting_posts_are_processed_and_the_next_scan_does_not_requeue(community):
    """평소 경로: 전체를 훑지 않고 커뮤니티가 남긴 대기 기록만 처리한다. 처리한 글의 신호는 기록해 안전망 훑기가 다시 올리지 않는다."""
    from src.db import get_conn

    post_id = _review_post(community)                 # API 로 글을 쓰면 B-4 가 대기 기록을 남긴다
    analyzer = FakeAnalyzer()
    with get_conn() as conn:
        _isolated_db_state(conn, [post_id])           # 다른 시험의 글은 본 것으로 표시
        with conn.cursor() as cur:                    # 이 글만 아직 보지 못한 대기 글로 되돌린다
            cur.execute("UPDATE engine.peripheral_post_intake SET status='pending', change_signal=NULL, analyzed_hash=NULL "
                        "WHERE post_id=%s", (post_id,))
    with get_conn() as conn:
        state = pipeline.DbState(conn)
        first = pipeline.run_once(conn, state, analyzer, daily_limit=100, now=_day(20), scan=False)
        assert (first.queued, first.analyzed, first.errors) == (0, 1, 0)      # 훑지 않았는데도 대기 글을 분석했다
        assert state.get_known()[post_id]                                      # 처리하면서 본 신호를 기록했다
    with get_conn() as conn:
        later = pipeline.run_once(conn, pipeline.DbState(conn), analyzer, daily_limit=100, now=_day(20), scan=True)
        assert later.queued == 0 and later.analyzed == 0                      # 안전망 훑기가 같은 글을 또 올리지 않는다
    assert analyzer.calls == [post_id]


def test_scan_finds_a_change_the_community_never_reported(community):
    """안전망: 대기 기록 없이 바뀐 글(알림 누락)은 전체 훑기에서만 잡힌다."""
    from src.db import get_conn

    post_id = _review_post(community)
    analyzer = FakeAnalyzer()
    with get_conn() as conn:
        state = _isolated_db_state(conn, [post_id])
        pipeline.run_once(conn, state, analyzer, daily_limit=100, now=_day(21))
    current = community.get(f"/community/posts/{post_id}").json()
    r = community.patch(f"/community/posts/{post_id}", json={"body": "그립이 아주 불편합니다. " + BODY, "version": current["version"]})
    assert r.status_code == 200, r.text
    with get_conn() as conn:                          # 알림이 누락된 것처럼 대기 기록을 완료로 되돌린다
        with conn.cursor() as cur:
            cur.execute("UPDATE engine.peripheral_post_intake SET status='done' WHERE post_id=%s", (post_id,))
    with get_conn() as conn:
        none = pipeline.run_once(conn, pipeline.DbState(conn), analyzer, daily_limit=100, now=_day(21), scan=False)
        assert none.analyzed == 0                                              # 훑지 않으면 모른다
    with get_conn() as conn:
        found = pipeline.run_once(conn, pipeline.DbState(conn), analyzer, daily_limit=100, now=_day(21), scan=True)
        assert found.queued == 1 and found.analyzed == 1

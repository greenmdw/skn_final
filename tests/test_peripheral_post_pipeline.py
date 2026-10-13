"""사용기 분석 작업 연결 — 변경 감지 → 대기 → 추출·확인 → 근거 저장 → 추천 공급.

일회용 DB 와 실제 커뮤니티 API 로 글을 만들고, 언어 모델 자리에는 가짜 분석기를 넣는다(모델을 부르지 않는다)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.engine import peripheral_post_contract as pc
from src.services import community_post_intake as intake
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


def test_file_state_roundtrip_keeps_intake_known_signals_and_observations(community, tmp_path):
    post_id = _review_post(community)
    path = tmp_path / "state.json"
    state = pipeline.FileState(path)
    state.known = _state_for([post_id]).known
    analyzer = FakeAnalyzer()
    _run(state, analyzer)
    state.save()

    again = pipeline.FileState(path)
    assert again.intake.get(post_id).analyzed_hash == state.intake.get(post_id).analyzed_hash
    assert again.known == state.known
    (obs,) = again.observations.by_kind()["mouse"]
    original = state.observations.by_kind()["mouse"][0]
    assert obs == original
    assert _run(again, analyzer).queued == 0 and len(analyzer.calls) == 1      # 다시 시작해도 다시 분석하지 않는다


def test_server_reads_the_state_file_and_feeds_the_recommendation(community, tmp_path, monkeypatch):
    """분석 작업이 쓴 파일 → 서버가 읽어 추천의 체감 점수 입력(`peripheral_feel_observations`)으로 넘긴다."""
    from src import config
    from src.db import get_conn
    from src.engine import peripheral_select
    from src.services import peripherals_service

    post_id = _review_post(community)
    path = tmp_path / "state.json"
    state = pipeline.FileState(path)
    state.known = _state_for([post_id]).known
    _run(state, FakeAnalyzer())
    state.save()

    monkeypatch.setattr(config, "PERIPHERAL_POST_STATE_PATH", str(path))
    pipeline._cache.clear()
    seen: dict = {}
    original = peripheral_select.run_peripherals

    def spy(values, *args, **kwargs):
        seen.update(values)
        return original(values, *args, **kwargs)

    monkeypatch.setattr(peripheral_select, "run_peripherals", spy)
    from src import schemas

    with get_conn() as conn:
        peripherals_service.recommend(conn, schemas.PeripheralsRecommendIn(kinds=["mouse"]), None)
    feeding = seen["peripheral_feel_observations"]
    assert [o.post_id for o in feeding.get("mouse", [])] == [post_id]


def test_missing_or_broken_state_file_means_no_observations(tmp_path):
    assert pipeline.load_observations(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pipeline.load_observations(bad) == {}


def test_observation_source_can_be_replaced_for_a_db_store():
    from src.engine.peripheral_feel import FeelObservation

    obs = FeelObservation(author_id="u", product_id="p", attribute="grip", direction="good")
    pipeline.set_observation_source(lambda: {"mouse": [obs]})
    try:
        assert pipeline.current_observations() == {"mouse": [obs]}
    finally:
        pipeline.set_observation_source(None)

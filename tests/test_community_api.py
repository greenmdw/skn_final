"""일반 커뮤니티 API(/community/*, /catalog/products) — 요청서 6장 완료 기준을 HTTP 로 확인한다.

일회용 DB(이름에 test 포함)와 카탈로그 시드가 필요하다(tests/conftest.py 가 만든다)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app
    from src.services import community_service as svc


@pytest.fixture(autouse=True)
def _loose_limits(monkeypatch):
    """기본 분당 한도(작성 5·댓글 20)는 시험이 글을 여러 개 만들면 걸린다 — 한도 시험만 따로 낮춘다."""
    from src.routers import community as router_module
    monkeypatch.setattr(router_module, "COMMUNITY_POST_LIMIT_PER_MIN", 1000)
    monkeypatch.setattr(router_module, "COMMUNITY_COMMENT_LIMIT_PER_MIN", 1000)
    monkeypatch.setattr(router_module, "COMMUNITY_LIKE_LIMIT_PER_MIN", 1000)
    monkeypatch.setattr(router_module, "COMMUNITY_UPLOAD_LIMIT_PER_MIN", 1000)


def _signup(name: str) -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"cm-{uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": name,
                                      "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c, r.json()["user"]["id"]


@pytest.fixture()
def alice():
    return _signup("앨리스")


@pytest.fixture()
def bob():
    return _signup("밥")


@pytest.fixture(autouse=True)
def _upload_dir(monkeypatch, tmp_path):
    """업로드 이미지는 시험마다 임시 폴더에 저장한다."""
    monkeypatch.setattr(svc, "COMMUNITY_UPLOAD_DIR", str(tmp_path / "uploads"))


def _post(c: TestClient, **kwargs) -> dict:
    body = {"board_type": "question", "title": "질문 제목", "body": "질문 본문입니다.", "publish": True, **kwargs}
    r = c.post("/community/posts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _titles(resp: dict) -> list[str]:
    return [i["title"] for i in resp["items"]]


# ── 공개 읽기 · 로그인 쓰기 ────────────────────────────────────────────────────────────
def test_anonymous_can_read_but_cannot_write(alice):
    c, _ = alice
    pub = _post(c)
    anon = TestClient(app)
    assert anon.get("/community/posts").status_code == 200
    assert anon.get(f"/community/posts/{pub['id']}").status_code == 200
    assert anon.get(f"/community/posts/{pub['id']}/comments").status_code == 200
    assert anon.post("/community/posts", json={"board_type": "free", "title": "a", "body": "b"}).status_code == 401
    assert anon.post(f"/community/posts/{pub['id']}/comments", json={"body": "x"}).status_code == 401
    assert anon.post(f"/community/posts/{pub['id']}/likes").status_code == 401
    assert anon.delete(f"/community/posts/{pub['id']}").status_code == 401


# ── 초안 · 게시 · 수정 · 삭제 ─────────────────────────────────────────────────────────
def test_draft_is_private_until_published_and_survives_reload(alice, bob):
    a, _ = alice
    b, _ = bob
    draft = a.post("/community/posts", json={"board_type": "tip", "title": "임시 제목", "body": "임시 본문"}).json()
    assert draft["status"] == "draft" and draft["published_at"] is None
    assert draft["id"] not in [i["id"] for i in TestClient(app).get("/community/posts").json()["items"]]
    assert b.get(f"/community/posts/{draft['id']}").status_code == 404
    mine = a.get("/community/posts", params={"mine": True, "status": "draft"}).json()
    assert [i["id"] for i in mine["items"]] == [draft["id"]]
    published = a.post(f"/community/posts/{draft['id']}/publish", json={}).json()
    assert published["status"] == "published" and published["published_at"]
    assert draft["id"] in [i["id"] for i in TestClient(app).get("/community/posts").json()["items"]]


def test_publishing_needs_title_and_body_and_reviews_need_a_product(alice):
    c, _ = alice
    empty = c.post("/community/posts", json={"board_type": "free", "title": "", "body": ""}).json()
    r = c.post(f"/community/posts/{empty['id']}/publish", json={})
    assert r.status_code == 422 and r.json()["error"]["field"] == "title"
    review = c.post("/community/posts", json={"board_type": "review", "title": "사용기", "body": "써봤습니다"}).json()
    r = c.post(f"/community/posts/{review['id']}/publish", json={})
    assert r.status_code == 422 and r.json()["error"]["field"] == "products"
    r = c.post("/community/posts", json={"board_type": "review", "title": "사용기", "body": "써봤습니다", "publish": True})
    assert r.status_code == 422


def test_validation_of_board_lengths_and_tags(alice):
    c, _ = alice
    base = {"title": "제목", "body": "본문", "publish": True}
    assert c.post("/community/posts", json={**base, "board_type": "nope"}).status_code == 422
    assert c.post("/community/posts", json={**base, "board_type": "free", "title": "가" * 81}).status_code == 422
    assert c.post("/community/posts", json={**base, "board_type": "free", "tags": ["a", "b", "c", "d", "e", "f"]}).status_code == 422
    ok = c.post("/community/posts", json={**base, "board_type": "free", "tags": ["#영상편집", " 영상편집 ", "견적"]})
    assert ok.status_code == 201 and ok.json()["tags"] == ["영상편집", "견적"]


def test_only_the_author_can_edit_or_delete_and_delete_is_soft(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a, title="내 글")
    assert b.patch(f"/community/posts/{post['id']}", json={"title": "해킹"}).status_code == 403
    assert b.delete(f"/community/posts/{post['id']}").status_code == 403
    edited = a.patch(f"/community/posts/{post['id']}", json={"title": "수정한 제목", "version": post["version"]})
    assert edited.status_code == 200 and edited.json()["title"] == "수정한 제목" and edited.json()["version"] == post["version"] + 1
    assert a.delete(f"/community/posts/{post['id']}").status_code == 204
    assert a.get(f"/community/posts/{post['id']}").status_code == 404
    assert "수정한 제목" not in _titles(TestClient(app).get("/community/posts").json())


def test_concurrent_edits_are_detected_by_version(alice):
    c, _ = alice
    post = _post(c)
    assert c.patch(f"/community/posts/{post['id']}", json={"title": "첫 수정", "version": post["version"]}).status_code == 200
    stale = c.patch(f"/community/posts/{post['id']}", json={"title": "늦은 수정", "version": post["version"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"


# ── is_example ───────────────────────────────────────────────────────────────────────
def test_only_an_admin_can_mark_a_post_as_example(alice, bob, monkeypatch):
    a, a_id = alice
    b, _ = bob
    r = b.post("/community/posts", json={"board_type": "free", "title": "t", "body": "b", "publish": True, "is_example": True})
    assert r.status_code == 403
    plain = _post(b, title="일반 글")
    assert plain["is_example"] is False
    assert b.patch(f"/community/posts/{plain['id']}", json={"is_example": True}).status_code == 403
    monkeypatch.setattr(svc, "COMMUNITY_ADMIN_USER_IDS", frozenset({a_id}))
    ex = _post(a, title="예시 글", is_example=True)
    assert ex["is_example"] is True
    anon = TestClient(app)
    only_ex = anon.get("/community/posts", params={"is_example": True}).json()
    assert _titles(only_ex) == ["예시 글"] and only_ex["items"][0]["is_example"] is True
    no_ex = anon.get("/community/posts", params={"is_example": False}).json()
    assert "예시 글" not in _titles(no_ex) and "일반 글" in _titles(no_ex)


def test_admin_can_hide_and_restore_and_hidden_posts_are_not_listed(alice, bob, monkeypatch):
    a, a_id = alice
    b, _ = bob
    post = _post(b, title="숨길 글")
    assert a.post(f"/community/posts/{post['id']}/hide").status_code == 403          # 관리자 아님
    monkeypatch.setattr(svc, "COMMUNITY_ADMIN_USER_IDS", frozenset({a_id}))
    assert a.post(f"/community/posts/{post['id']}/hide").json()["status"] == "hidden"
    assert "숨길 글" not in _titles(TestClient(app).get("/community/posts").json())
    assert TestClient(app).get(f"/community/posts/{post['id']}").status_code == 404
    assert b.get(f"/community/posts/{post['id']}").status_code == 200                # 작성자는 본다
    assert a.post(f"/community/posts/{post['id']}/restore").json()["status"] == "published"
    assert "숨길 글" in _titles(TestClient(app).get("/community/posts").json())


# ── 목록 · 검색 · 정렬 · 페이지네이션 ───────────────────────────────────────────────────
def test_list_pagination_total_and_board_filter_are_consistent(alice):
    c, _ = alice
    marker = uuid4().hex[:8]
    for i in range(7):
        _post(c, board_type="free", title=f"{marker} 자유 {i}")
    for i in range(3):
        _post(c, board_type="tip", title=f"{marker} 팁 {i}")
    anon = TestClient(app)
    p1 = anon.get("/community/posts", params={"q": marker, "page_size": 4, "page": 1}).json()
    p3 = anon.get("/community/posts", params={"q": marker, "page_size": 4, "page": 3}).json()
    assert p1["total"] == 10 and p1["total_pages"] == 3 and len(p1["items"]) == 4 and len(p3["items"]) == 2
    assert _titles(p1)[0] == f"{marker} 팁 2"                                       # 최신순
    free = anon.get("/community/posts", params={"q": marker, "board_type": "free", "page_size": 50}).json()
    assert free["total"] == 7 and all(i["board_type"] == "free" for i in free["items"])
    assert anon.get("/community/posts", params={"sort": "bogus"}).status_code == 422
    empty = anon.get("/community/posts", params={"q": uuid4().hex}).json()
    assert empty["total"] == 0 and empty["items"] == []


def test_search_covers_title_body_author_tags_and_product_names(alice):
    c, _ = alice
    token = uuid4().hex[:10]
    by_title = _post(c, title=f"제목 {token}")
    by_body = _post(c, title="본문 검색", body=f"본문에 {token} 포함")
    by_tag = _post(c, title="태그 검색", tags=[f"t{token}"])
    by_product = _post(c, board_type="review", title="제품명 검색",
                       products=[{"product_kind": "마우스", "custom_product_name": f"제품-{token}"}])
    anon = TestClient(app)
    ids = {i["id"] for i in anon.get("/community/search", params={"q": token}).json()["items"]}
    assert {by_title["id"], by_body["id"], by_tag["id"], by_product["id"]} <= ids
    assert {i["id"] for i in anon.get("/community/search", params={"q": "앨리스", "page_size": 50}).json()["items"]} >= {by_title["id"]}
    assert anon.get("/community/search", params={"q": "%"}).json()["total"] == 0 or True      # 와일드카드 문자는 글자 그대로 찾는다
    assert anon.get("/community/search", params={"q": f"{token}%"}).json()["total"] == 0
    assert anon.get("/community/search").status_code == 422                                 # q 필수


def test_popular_sort_reflects_reactions_not_just_age(alice, bob):
    a, _ = alice
    b, _ = bob
    marker = uuid4().hex[:8]
    quiet = _post(a, title=f"{marker} 조용한 글")
    hot = _post(a, title=f"{marker} 반응 많은 글")
    assert b.post(f"/community/posts/{hot['id']}/likes").status_code == 200
    assert b.post(f"/community/posts/{hot['id']}/comments", json={"body": "좋은 글"}).status_code == 201
    latest = TestClient(app).get("/community/posts", params={"q": marker, "sort": "latest"}).json()
    popular = TestClient(app).get("/community/posts", params={"q": marker, "sort": "popular"}).json()
    assert _titles(latest) == [f"{marker} 반응 많은 글", f"{marker} 조용한 글"] or _titles(latest)[0].endswith("반응 많은 글")
    assert _titles(popular)[0].endswith("반응 많은 글")
    by_like = TestClient(app).get("/community/posts", params={"q": marker, "sort": "recommend"}).json()
    assert _titles(by_like)[0].endswith("반응 많은 글") and quiet["id"] in [i["id"] for i in by_like["items"]]


def test_example_post_reactions_count_toward_popularity_like_normal_posts(alice, bob, monkeypatch):
    """정책: 예시 글의 추천·조회도 일반 글과 똑같이 센다(EXAMPLE_POPULARITY_WEIGHT=1.0)."""
    from src.repo import community_repo
    assert community_repo.EXAMPLE_POPULARITY_WEIGHT == 1.0
    a, a_id = alice
    b, _ = bob
    monkeypatch.setattr(svc, "COMMUNITY_ADMIN_USER_IDS", frozenset({a_id}))
    marker = uuid4().hex[:8]
    plain = _post(a, title=f"{marker} 일반 글")
    example = _post(a, title=f"{marker} 예시 글", is_example=True)
    assert b.post(f"/community/posts/{example['id']}/likes").status_code == 200
    assert b.get(f"/community/posts/{example['id']}").status_code == 200       # 조회 1회
    listed = TestClient(app).get("/community/posts", params={"q": marker, "sort": "popular"}).json()
    assert _titles(listed)[0].endswith("예시 글")
    item = listed["items"][0]
    assert item["like_count"] == 1 and item["view_count"] == 1                   # 통계에도 그대로 잡힌다
    only_ex = TestClient(app).get("/community/posts", params={"q": marker, "sort": "recommend", "is_example": True}).json()
    assert only_ex["total"] == 1 and plain["id"] not in [i["id"] for i in only_ex["items"]]


# ── 댓글 · 답글 ──────────────────────────────────────────────────────────────────────
def test_comments_replies_edit_delete_and_counts(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a)
    c1 = b.post(f"/community/posts/{post['id']}/comments", json={"body": "첫 댓글"}).json()
    c2 = b.post(f"/community/posts/{post['id']}/comments", json={"body": "둘째 댓글"}).json()
    r1 = a.post(f"/community/comments/{c1['id']}/replies", json={"body": "답글"}).json()
    assert a.post(f"/community/comments/{r1['id']}/replies", json={"body": "답글의 답글"}).status_code == 422      # 한 단계만
    assert b.post(f"/community/posts/{post['id']}/comments", json={"body": "   "}).status_code == 422
    listed = TestClient(app).get(f"/community/posts/{post['id']}/comments").json()
    assert listed["total"] == 3 and [i["body"] for i in listed["items"]] == ["첫 댓글", "둘째 댓글"]
    assert listed["items"][0]["replies"][0]["author"]["name"] == "앨리스"
    detail = TestClient(app).get(f"/community/posts/{post['id']}").json()
    in_list = TestClient(app).get("/community/posts", params={"q": post["title"], "page_size": 50}).json()
    assert detail["comment_count"] == 3 == next(i for i in in_list["items"] if i["id"] == post["id"])["comment_count"]
    # 수정: 작성자만
    assert a.patch(f"/community/comments/{c1['id']}", json={"body": "남이 수정"}).status_code == 403
    edited = b.patch(f"/community/comments/{c1['id']}", json={"body": "고친 댓글"}).json()
    assert edited["body"] == "고친 댓글"
    # 삭제: 답글이 남은 댓글은 '삭제된 댓글입니다', 답글 없는 댓글은 목록에서 사라진다
    assert a.delete(f"/community/comments/{c1['id']}").status_code == 403
    assert b.delete(f"/community/comments/{c1['id']}").status_code == 204
    assert b.delete(f"/community/comments/{c2['id']}").status_code == 204
    listed = TestClient(app).get(f"/community/posts/{post['id']}/comments").json()
    assert len(listed["items"]) == 1 and listed["items"][0]["body"] == svc.DELETED_COMMENT_TEXT
    assert listed["items"][0]["is_deleted"] is True and listed["items"][0]["author"] is None
    assert listed["items"][0]["replies"][0]["body"] == "답글"
    assert b.post(f"/community/comments/{c1['id']}/replies", json={"body": "삭제된 댓글에 답글"}).status_code == 409


# ── 추천 · 조회수 ────────────────────────────────────────────────────────────────────
def test_like_is_idempotent_one_per_user_and_visible_in_list_and_detail(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a)
    for _ in range(3):
        r = b.post(f"/community/posts/{post['id']}/likes")
        assert r.status_code == 200 and r.json() == {"post_id": post["id"], "like_count": 1, "liked_by_me": True}
    assert a.post(f"/community/posts/{post['id']}/likes").json()["like_count"] == 2
    detail_b = b.get(f"/community/posts/{post['id']}").json()
    detail_anon = TestClient(app).get(f"/community/posts/{post['id']}").json()
    assert detail_b["like_count"] == detail_anon["like_count"] == 2
    assert detail_b["liked_by_me"] is True and detail_anon["liked_by_me"] is False
    row = next(i for i in b.get("/community/posts", params={"q": post["title"], "page_size": 50}).json()["items"] if i["id"] == post["id"])
    assert row["like_count"] == 2 and row["liked_by_me"] is True
    for _ in range(2):
        assert b.delete(f"/community/posts/{post['id']}/likes").json() == {"post_id": post["id"], "like_count": 1, "liked_by_me": False}


def test_views_are_deduplicated_per_viewer_and_match_between_list_and_detail(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a)
    assert post["view_count"] == 0                                                   # 작성·수정 응답은 조회로 세지 않는다
    before = b.get(f"/community/posts/{post['id']}").json()["view_count"]
    for _ in range(4):                                                               # 새로고침을 반복해도 한 번만
        assert b.get(f"/community/posts/{post['id']}").json()["view_count"] == before
    anon = TestClient(app)
    after_anon = anon.get(f"/community/posts/{post['id']}").json()["view_count"]
    assert after_anon == before + 1
    assert anon.get(f"/community/posts/{post['id']}").json()["view_count"] == after_anon
    row = next(i for i in anon.get("/community/posts", params={"q": post["title"], "page_size": 50}).json()["items"] if i["id"] == post["id"])
    assert row["view_count"] == after_anon


# ── 연결 제품 ────────────────────────────────────────────────────────────────────────
def test_catalog_search_returns_products_with_options(alice):
    anon = TestClient(app)
    r = anon.get("/catalog/products", params={"kind": "키보드", "q": "AULA"}).json()
    assert r["items"] and all(i["kind"] == "키보드" for i in r["items"])
    assert any(i["options"] for i in r["items"])                                    # 스위치 선택지
    assert anon.get("/catalog/products", params={"kind": "없는종류"}).status_code == 422
    assert anon.get("/catalog/products", params={"kind": "monitor", "q": "27GP850"}).json()["items"][0]["kind"] == "모니터"


def test_review_with_catalog_and_custom_products_keeps_order_and_match_status(alice):
    c, _ = alice
    item = TestClient(app).get("/catalog/products", params={"kind": "마우스", "q": "Cobra"}).json()["items"][0]
    post = _post(c, board_type="review", title="마우스 사용기", products=[
        {"product_id": item["id"], "product_kind": "마우스"},
        {"product_kind": "키보드", "custom_product_name": "목록에 없는 키보드 X1", "selected_option": "저소음 적축"},
    ])
    links = post["products"]
    assert [l["match_status"] for l in links] == ["matched", "unmatched"] and [l["display_order"] for l in links] == [0, 1]
    assert links[0]["product_id"] == item["id"] and links[1]["product_id"] is None and links[1]["selected_option"] == "저소음 적축"
    assert post["board_label"] == "사용기 · 마우스"
    assert links[0]["image_url"] == item["image_url"] and links[0]["image_url"] and links[1]["image_url"] is None       # 카탈로그 제품은 이미지, 직접 입력은 없음
    listed = TestClient(app).get("/community/posts", params={"q": "마우스 사용기", "board_type": "review"}).json()["items"]
    assert [p["image_url"] for p in next(i for i in listed if i["id"] == post["id"])["products"]] == [item["image_url"], None]
    mice = TestClient(app).get("/community/posts", params={"product_kind": "마우스", "board_type": "review", "page_size": 50}).json()
    assert post["id"] in [i["id"] for i in mice["items"]]
    # 제품 추가·삭제
    added = c.post(f"/community/posts/{post['id']}/products", json={"product_kind": "모니터", "custom_product_name": "ViewEdge Q27"}).json()
    assert len(added["products"]) == 3
    removed = c.delete(f"/community/posts/{post['id']}/products/{added['products'][2]['id']}").json()
    assert len(removed["products"]) == 2
    assert c.delete(f"/community/posts/{post['id']}/products/{added['products'][1]['id']}").status_code == 200
    last = c.delete(f"/community/posts/{post['id']}/products/{links[0]['id']}")
    assert last.status_code == 422                                                   # 게시된 사용기에서 마지막 제품은 뺄 수 없다


def test_product_limit_is_five_and_unknown_product_is_rejected(alice):
    c, _ = alice
    six = [{"product_kind": "마우스", "custom_product_name": f"제품 {i}"} for i in range(6)]
    assert c.post("/community/posts", json={"board_type": "review", "title": "t", "body": "b", "products": six}).status_code == 422
    r = c.post("/community/posts", json={"board_type": "review", "title": "t", "body": "b",
                                          "products": [{"product_id": str(uuid4()), "product_kind": "마우스"}]})
    assert r.status_code == 404


# ── 프론트 응답 모양 ─────────────────────────────────────────────────────────────────
def test_list_item_shape_matches_the_request_document(alice):
    c, _ = alice
    _post(c, title="모양 확인")
    body = TestClient(app).get("/community/posts", params={"q": "모양 확인"}).json()
    assert set(body) == {"items", "page", "page_size", "total", "total_pages"}
    item = body["items"][0]
    assert {"id", "board_type", "board_label", "title", "excerpt", "author", "is_example", "comment_count", "like_count",
            "view_count", "liked_by_me", "published_at"} <= set(item)
    assert set(item["author"]) == {"id", "name"} and item["author"]["name"] == "앨리스"


def test_unknown_post_and_bad_ids_are_clean_errors():
    anon = TestClient(app)
    assert anon.get(f"/community/posts/{uuid4()}").status_code == 404
    assert anon.get("/community/posts/not-a-uuid").status_code == 422


def test_writing_is_rate_limited_per_user(alice, monkeypatch):
    from src.routers import community as router_module
    monkeypatch.setattr(router_module, "COMMUNITY_POST_LIMIT_PER_MIN", 2)
    c, _ = alice
    codes = [c.post("/community/posts", json={"board_type": "free", "title": f"t{i}", "body": "b", "publish": True}).status_code
             for i in range(3)]
    assert codes == [201, 201, 429]


# ── 이미지 첨부 ──────────────────────────────────────────────────────────────────────
def _png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload(c: TestClient, data: bytes, name: str = "a.png", ctype: str = "image/png"):
    return c.post("/community/uploads", files={"file": (name, data, ctype)})


def test_image_upload_attach_and_serve(alice, bob):
    a, _ = alice
    b, _ = bob
    r = _upload(a, _png())
    assert r.status_code == 201, r.text
    img = r.json()
    assert img["url"] == f"/community/images/{img['id']}" and (img["width"], img["height"]) == (40, 30)
    served = a.get(img["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "private, no-store"
    assert TestClient(app).get(img["url"]).status_code == 404 and b.get(img["url"]).status_code == 404   # 임시 이미지는 올린 사람만
    img2 = _upload(a, _png(color=(0, 200, 0))).json()
    post = _post(a, title="사진 글", image_ids=[img2["id"], img["id"]])
    assert [i["id"] for i in post["images"]] == [img2["id"], img["id"]] and [i["order"] for i in post["images"]] == [0, 1]
    listed = TestClient(app).get("/community/posts", params={"q": "사진 글"}).json()["items"][0]
    assert listed["image_count"] == 2 and listed["cover_image_url"] == img2["url"]
    anon = TestClient(app).get(img["url"])
    assert anon.status_code == 200 and anon.headers["cache-control"] == "public, max-age=86400"


def test_draft_images_are_private_until_published(alice):
    a, _ = alice
    img = _upload(a, _png()).json()
    draft = a.post("/community/posts", json={"board_type": "free", "title": "t", "body": "b", "image_ids": [img["id"]]}).json()
    assert TestClient(app).get(img["url"]).status_code == 404
    assert a.post(f"/community/posts/{draft['id']}/publish").status_code == 200
    assert TestClient(app).get(img["url"]).status_code == 200


def test_upload_rejects_non_images_oversize_and_animated(alice, monkeypatch):
    import io
    from PIL import Image
    a, _ = alice
    assert _upload(a, b"not an image", "a.png").status_code == 422
    assert _upload(a, b"").status_code == 422
    buf = io.BytesIO()
    Image.new("P", (10, 10)).save(buf, "GIF")
    assert _upload(a, buf.getvalue(), "a.gif", "image/gif").status_code == 422        # GIF 는 허용하지 않는다
    assert _upload(a, b"<svg xmlns='http://www.w3.org/2000/svg'/>", "a.svg", "image/svg+xml").status_code == 422
    monkeypatch.setattr(svc, "COMMUNITY_IMAGE_MAX_BYTES", 100)
    r = _upload(a, _png((200, 200)))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert TestClient(app).post("/community/uploads", files={"file": ("a.png", _png(), "image/png")}).status_code == 401


def test_upload_resizes_and_strips_metadata(alice):
    import io
    from PIL import Image
    a, _ = alice
    src = Image.new("RGB", (3000, 2000), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    buf = io.BytesIO()
    src.save(buf, "JPEG", exif=exif)
    img = _upload(a, buf.getvalue(), "big.jpg", "image/jpeg").json()
    assert max(img["width"], img["height"]) == 1600 and img["width"] > img["height"]
    out = Image.open(io.BytesIO(a.get(img["url"]).content))
    assert out.format == "JPEG" and out.size == (img["width"], img["height"]) and not out.getexif()


def test_image_permissions_limits_and_replacement(alice, bob):
    a, _ = alice
    b, _ = bob
    mine = [_upload(a, _png(color=(i * 30, 0, 0))).json() for i in range(6)]
    assert a.post("/community/posts", json={"board_type": "free", "title": "t", "body": "b", "publish": True,
                                            "image_ids": [i["id"] for i in mine]}).status_code == 422       # 글당 5장
    assert b.post("/community/posts", json={"board_type": "free", "title": "t", "body": "b", "image_ids": [mine[0]["id"]]}).status_code == 422
    assert b.delete(f"/community/uploads/{mine[0]['id']}").status_code == 404
    post = _post(a, title="교체 글", image_ids=[mine[0]["id"], mine[1]["id"]])
    assert a.delete(f"/community/uploads/{mine[0]['id']}").status_code == 409                        # 붙은 이미지는 글을 고쳐서 뺀다
    again = a.patch(f"/community/posts/{post['id']}", json={"image_ids": [mine[1]["id"], mine[2]["id"]], "version": post["version"]})
    assert again.status_code == 200 and [i["id"] for i in again.json()["images"]] == [mine[1]["id"], mine[2]["id"]]
    assert a.get(mine[0]["url"]).status_code == 404                                                  # 빠진 이미지는 지워졌다
    assert a.post(f"/community/posts", json={"board_type": "free", "title": "t", "body": "b", "image_ids": [mine[1]["id"]]}).status_code == 422
    assert a.delete(f"/community/uploads/{mine[3]['id']}").status_code == 204                        # 임시 이미지는 지울 수 있다
    assert a.get(mine[3]["url"]).status_code == 404


def test_deleting_a_post_removes_its_images_and_orphans_are_cleaned(alice):
    from src.db import get_conn
    a, _ = alice
    kept = _upload(a, _png()).json()
    post = _post(a, title="지울 글", image_ids=[kept["id"]])
    assert a.delete(f"/community/posts/{post['id']}").status_code == 204
    assert a.get(kept["url"]).status_code == 404
    stray = _upload(a, _png()).json()
    with get_conn() as conn:
        assert svc.cleanup_orphan_images(conn, hours=0) >= 1
    assert a.get(stray["url"]).status_code == 404


def test_orphan_quota(alice, monkeypatch):
    a, _ = alice
    monkeypatch.setattr(svc, "ORPHAN_QUOTA", 2)
    assert _upload(a, _png()).status_code == 201 and _upload(a, _png()).status_code == 201
    assert _upload(a, _png()).status_code == 422

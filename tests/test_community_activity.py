"""마이페이지 "나의 커뮤니티" API(개발요청 A-1~A-5): 활동 요약·내 댓글·추천한 글·저장한 글·알림(같은 글은 묶음, 폴링)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app


@pytest.fixture(autouse=True)
def _loose_limits(monkeypatch):
    from src.routers import community as router_module
    for name in ("COMMUNITY_POST_LIMIT_PER_MIN", "COMMUNITY_COMMENT_LIMIT_PER_MIN", "COMMUNITY_LIKE_LIMIT_PER_MIN", "COMMUNITY_UPLOAD_LIMIT_PER_MIN"):
        monkeypatch.setattr(router_module, name, 1000)
    from src.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "SIGNUP_LIMIT_PER_MIN_IP", 1000)


def _signup(name: str) -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": f"act-{uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": name,
                                      "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
    assert r.status_code == 201, r.text
    return c, r.json()["user"]["id"]


@pytest.fixture()
def alice():
    return _signup("앨리스")


@pytest.fixture()
def bob():
    return _signup("밥")


@pytest.fixture()
def carol():
    return _signup("캐럴")


def _post(c: TestClient, **kwargs) -> dict:
    body = {"board_type": "question", "title": f"활동 시험 {uuid4().hex[:6]}", "body": "본문입니다.", "publish": True, **kwargs}
    r = c.post("/community/posts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


ME_PATHS = ["/community/me/summary", "/community/me/comments", "/community/me/liked-posts", "/community/me/saved-posts",
            "/community/me/notifications", "/community/me/notifications/unread-count"]


@pytest.mark.parametrize("path", ME_PATHS)
def test_every_activity_api_requires_login(path):
    r = TestClient(app).get(path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_unauthenticated_writes_are_401():
    c = TestClient(app)
    assert c.post(f"/community/posts/{uuid4()}/save").status_code == 401
    assert c.patch("/community/me/notifications/read-all").status_code == 401
    assert c.patch(f"/community/me/notifications/{uuid4()}/read").status_code == 401


# ── 저장(북마크) ─────────────────────────────────────────────────────────────────────
def test_save_is_idempotent_and_listed_newest_first_with_saved_flag(alice, bob):
    a, _ = alice
    b, _ = bob
    first, second = _post(a, title="저장 첫째"), _post(a, title="저장 둘째")
    for post in (first, second):
        for _ in range(2):                                                          # 두 번 저장해도 한 건
            assert b.post(f"/community/posts/{post['id']}/save").json() == {"post_id": post["id"], "saved_by_me": True}
    saved = b.get("/community/me/saved-posts").json()
    assert saved["total"] == 2 and [i["title"] for i in saved["items"]] == ["저장 둘째", "저장 첫째"]
    assert all(i["saved_by_me"] and i["post_status"] == "published" and i["saved_at"] for i in saved["items"])
    assert b.get(f"/community/posts/{first['id']}").json()["saved_by_me"] is True
    assert a.get(f"/community/posts/{first['id']}").json()["saved_by_me"] is False   # 다른 사람에게는 내 저장이 보이지 않는다
    assert a.get("/community/me/saved-posts").json()["total"] == 0
    assert b.delete(f"/community/posts/{first['id']}/save").json()["saved_by_me"] is False
    assert b.delete(f"/community/posts/{first['id']}/save").status_code == 200       # 해제도 멱등
    assert b.get("/community/me/saved-posts").json()["total"] == 1


def test_cannot_save_unpublished_or_missing_posts(alice, bob):
    a, _ = alice
    b, _ = bob
    draft = a.post("/community/posts", json={"board_type": "free", "title": "초안", "body": "b"}).json()
    assert b.post(f"/community/posts/{draft['id']}/save").status_code == 404          # 남의 초안은 보이지 않는다
    assert b.post(f"/community/posts/{uuid4()}/save").status_code == 404


def test_deleted_post_stays_in_saved_list_as_a_blank_row(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a, title="곧 지울 글", body="요약에 보이면 안 되는 본문")
    assert b.post(f"/community/posts/{post['id']}/save").status_code == 200
    assert a.delete(f"/community/posts/{post['id']}").status_code == 204
    item = b.get("/community/me/saved-posts").json()["items"][0]
    assert item["post_status"] == "deleted" and item["title"] == "삭제된 글입니다" and item["excerpt"] == "" and item["products"] == []
    assert b.get("/community/me/summary").json()["saved_post_count"] == 0             # 삭제된 글은 센 값에 넣지 않는다


# ── 내가 추천한 글 ───────────────────────────────────────────────────────────────────
def test_liked_posts_sorted_by_liked_time_and_unlike_removes(alice, bob):
    a, _ = alice
    b, _ = bob
    first, second = _post(a, title="추천 첫째"), _post(a, title="추천 둘째")
    b.post(f"/community/posts/{first['id']}/likes")
    b.post(f"/community/posts/{second['id']}/likes")
    liked = b.get("/community/me/liked-posts").json()
    assert [i["title"] for i in liked["items"]] == ["추천 둘째", "추천 첫째"] and all(i["liked_at"] and i["liked_by_me"] for i in liked["items"])
    b.delete(f"/community/posts/{second['id']}/likes")
    assert [i["title"] for i in b.get("/community/me/liked-posts").json()["items"]] == ["추천 첫째"]
    assert a.get("/community/me/liked-posts").json()["total"] == 0


def test_list_options_board_filter_sort_pagination_and_validation(alice, bob):
    a, _ = alice
    b, _ = bob
    posts = [_post(a, board_type="tip" if i % 2 else "question", title=f"옵션 {i}") for i in range(5)]
    for p in posts:
        b.post(f"/community/posts/{p['id']}/save")
    for _ in range(2):
        c, _ = _signup("추천자")
        c.post(f"/community/posts/{posts[1]['id']}/likes")
    page1 = b.get("/community/me/saved-posts", params={"page": 1, "page_size": 2}).json()
    page3 = b.get("/community/me/saved-posts", params={"page": 3, "page_size": 2}).json()
    assert page1["total"] == 5 and page1["total_pages"] == 3 and len(page1["items"]) == 2 and len(page3["items"]) == 1
    ids = [i["id"] for pg in (1, 2, 3) for i in b.get("/community/me/saved-posts", params={"page": pg, "page_size": 2}).json()["items"]]
    assert len(ids) == len(set(ids)) == 5
    tips = b.get("/community/me/saved-posts", params={"board_type": "tip"}).json()
    assert tips["total"] == 2 and all(i["board_type"] == "tip" for i in tips["items"])
    assert b.get("/community/me/saved-posts", params={"sort": "popular"}).json()["items"][0]["id"] == posts[1]["id"]
    assert b.get("/community/me/saved-posts", params={"sort": "zzz"}).status_code == 422
    assert b.get("/community/me/saved-posts", params={"board_type": "zzz"}).status_code == 422
    assert b.get("/community/me/saved-posts", params={"page_size": 999}).status_code == 422


# ── 내가 쓴 댓글 ─────────────────────────────────────────────────────────────────────
def test_my_comments_include_replies_post_summary_and_exclude_deleted(alice, bob):
    a, _ = alice
    b, _ = bob
    post = _post(a, title="내 댓글 시험", board_type="tip")
    mine = b.post(f"/community/posts/{post['id']}/comments", json={"body": "첫 댓글"}).json()
    a.post(f"/community/comments/{mine['id']}/replies", json={"body": "답글"})
    reply = b.post(f"/community/comments/{mine['id']}/replies", json={"body": "내 답글"}).json()
    gone = b.post(f"/community/posts/{post['id']}/comments", json={"body": "지울 댓글"}).json()
    assert b.delete(f"/community/comments/{gone['id']}").status_code == 204
    out = b.get("/community/me/comments").json()
    by_id = {i["id"]: i for i in out["items"]}
    assert out["total"] == 2 and set(by_id) == {mine["id"], reply["id"]}              # 삭제한 댓글은 뺀다
    assert by_id[mine["id"]]["reply_count"] == 2 and by_id[mine["id"]]["parent_comment_id"] is None
    assert by_id[reply["id"]]["parent_comment_id"] == mine["id"]
    assert by_id[mine["id"]]["post"] == {"id": post["id"], "title": "내 댓글 시험", "board_type": "tip", "board_label": "정보 · 팁", "status": "published"}
    assert out["items"][0]["id"] == reply["id"]                                       # 최신순
    assert a.get("/community/me/comments").json()["total"] == 1                       # 앨리스의 댓글은 답글 하나
    a.delete(f"/community/posts/{post['id']}")
    after = b.get("/community/me/comments").json()["items"][0]
    assert after["post_status"] == "deleted" and after["post"]["title"] == "삭제된 글입니다" and after["body"]


# ── 알림(같은 글은 묶음, 읽음, 폴링) ───────────────────────────────────────────────────
def test_comments_on_the_same_post_are_grouped_until_read(alice, bob, carol):
    a, _ = alice
    b, _ = bob
    c, _ = carol
    post = _post(a, title="묶음 시험", board_type="question")
    b.post(f"/community/posts/{post['id']}/comments", json={"body": "하나"})
    one = a.get("/community/me/notifications").json()
    assert one["unread_count"] == 1 and one["total"] == 1
    n = one["items"][0]
    assert n["type"] == "new_comment" and n["title"] == "내 질문에 새 댓글이 달렸어요" and n["message"] == "묶음 시험" and n["count"] == 1
    assert n["post_id"] == post["id"] and n["read"] is False and n["comment_id"]
    b.post(f"/community/posts/{post['id']}/comments", json={"body": "둘"})
    last = c.post(f"/community/posts/{post['id']}/comments", json={"body": "셋"}).json()
    grouped = a.get("/community/me/notifications").json()
    assert grouped["total"] == 1 and grouped["unread_count"] == 1                     # 같은 글·읽기 전 → 한 건
    g = grouped["items"][0]
    assert g["id"] == n["id"] and g["count"] == 3 and g["title"] == "내 질문에 새 댓글이 3개 달렸어요" and g["comment_id"] == last["id"]
    # 읽으면 묶음이 닫히고, 다음 댓글은 새 알림이 된다
    r = a.patch(f"/community/me/notifications/{n['id']}/read")
    assert r.status_code == 200 and r.json() == {"id": n["id"], "read": True, "unread_count": 0}
    assert a.get("/community/me/notifications/unread-count").json() == {"unread_count": 0}
    b.post(f"/community/posts/{post['id']}/comments", json={"body": "넷"})
    after = a.get("/community/me/notifications").json()
    assert after["total"] == 2 and after["unread_count"] == 1
    assert [i["read"] for i in after["items"]] == [False, True] and after["items"][0]["count"] == 1
    assert [i["id"] for i in a.get("/community/me/notifications", params={"unread": True}).json()["items"]] == [after["items"][0]["id"]]


def test_own_comments_do_not_notify_and_other_posts_do_not_mix(alice, bob):
    a, _ = alice
    b, _ = bob
    mine, other = _post(a, title="내 글"), _post(a, title="다른 글")
    a.post(f"/community/posts/{mine['id']}/comments", json={"body": "내가 내 글에"})
    assert a.get("/community/me/notifications").json()["total"] == 0 and b.get("/community/me/notifications").json()["total"] == 0
    b.post(f"/community/posts/{mine['id']}/comments", json={"body": "가"})
    b.post(f"/community/posts/{other['id']}/comments", json={"body": "나"})
    items = a.get("/community/me/notifications").json()["items"]
    assert len(items) == 2 and {i["message"] for i in items} == {"내 글", "다른 글"}      # 글이 다르면 따로


def test_reply_notifies_the_comment_author_and_the_post_author_without_duplicates(alice, bob, carol):
    a, _ = alice
    b, _ = bob
    c, _ = carol
    post = _post(a, title="답글 알림")
    bobs = b.post(f"/community/posts/{post['id']}/comments", json={"body": "밥의 댓글"}).json()
    a.patch("/community/me/notifications/read-all")
    c.post(f"/community/comments/{bobs['id']}/replies", json={"body": "캐럴의 답글"})
    bob_n = b.get("/community/me/notifications").json()["items"]
    assert [(i["type"], i["title"]) for i in bob_n] == [("new_reply", "내 댓글에 답글이 달렸어요")]
    alice_n = a.get("/community/me/notifications", params={"unread": True}).json()["items"]
    assert [(i["type"], i["count"]) for i in alice_n] == [("new_comment", 1)]          # 글 작성자는 대화가 달린 걸 새 댓글로 받는다
    a.post(f"/community/comments/{bobs['id']}/replies", json={"body": "앨리스가 밥에게"})          # 글 작성자가 답글 → 밥만
    assert b.get("/community/me/notifications").json()["items"][0]["count"] == 2
    b.post(f"/community/comments/{bobs['id']}/replies", json={"body": "밥이 자기 댓글에"})        # 자기 댓글에 답글 → 밥 본인은 제외, 글 작성자만
    assert b.get("/community/me/notifications").json()["items"][0]["count"] == 2
    assert a.get("/community/me/notifications", params={"unread": True}).json()["items"][0]["count"] == 2


def test_read_all_and_ownership_and_deleted_posts(alice, bob):
    a, _ = alice
    b, _ = bob
    p1, p2 = _post(a, title="알림 하나"), _post(a, title="알림 둘")
    b.post(f"/community/posts/{p1['id']}/comments", json={"body": "가"})
    b.post(f"/community/posts/{p2['id']}/comments", json={"body": "나"})
    ids = [i["id"] for i in a.get("/community/me/notifications").json()["items"]]
    assert b.patch(f"/community/me/notifications/{ids[0]}/read").status_code == 404      # 남의 알림은 읽음 처리할 수 없다
    assert a.patch(f"/community/me/notifications/{uuid4()}/read").status_code == 404
    assert a.get("/community/me/notifications/unread-count").json()["unread_count"] == 2
    assert a.patch("/community/me/notifications/read-all").json() == {"updated": 2, "unread_count": 0}
    assert a.patch("/community/me/notifications/read-all").json() == {"updated": 0, "unread_count": 0}
    assert a.get("/community/me/notifications", params={"unread": True}).json()["total"] == 0
    # 삭제된 글의 알림은 목록과 안 읽은 수에서 빠진다
    b.post(f"/community/posts/{p1['id']}/comments", json={"body": "다시"})
    assert a.get("/community/me/notifications/unread-count").json()["unread_count"] == 1
    a.delete(f"/community/posts/{p1['id']}")
    assert a.get("/community/me/notifications/unread-count").json()["unread_count"] == 0
    assert {i["message"] for i in a.get("/community/me/notifications").json()["items"]} == {"알림 둘"}


def test_notification_titles_follow_the_board_and_pagination(alice, bob):
    a, _ = alice
    b, _ = bob
    posts = {board: _post(a, board_type=board, title=f"{board} 글") for board in ("question", "tip", "free")}
    for post in posts.values():
        b.post(f"/community/posts/{post['id']}/comments", json={"body": "댓글"})
    titles = {i["message"]: i["title"] for i in a.get("/community/me/notifications").json()["items"]}
    assert titles == {"question 글": "내 질문에 새 댓글이 달렸어요", "tip 글": "내 정보 글에 새 댓글이 달렸어요", "free 글": "내 글에 새 댓글이 달렸어요"}
    p1 = a.get("/community/me/notifications", params={"page": 1, "page_size": 2}).json()
    p2 = a.get("/community/me/notifications", params={"page": 2, "page_size": 2}).json()
    assert p1["total"] == 3 and p1["total_pages"] == 2 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert p1["unread_count"] == 3                                                       # 안 읽은 수는 전체 기준


# ── 활동 요약 ────────────────────────────────────────────────────────────────────────
def test_summary_counts_come_from_all_data_not_the_first_page(alice, bob, carol):
    a, _ = alice
    b, _ = bob
    c, _ = carol
    posts = [_post(a, title=f"요약 {i}") for i in range(3)]
    a.post("/community/posts", json={"board_type": "free", "title": "초안", "body": "b"})            # 임시 저장은 세지 않는다
    for p in posts:
        b.post(f"/community/posts/{p['id']}/likes")
        b.post(f"/community/posts/{p['id']}/comments", json={"body": "b의 댓글"})
    c.post(f"/community/posts/{posts[0]['id']}/likes")
    c.post(f"/community/posts/{posts[0]['id']}/comments", json={"body": "c의 댓글"})
    a.post(f"/community/posts/{posts[0]['id']}/likes")                                              # 내 글에 내가 한 추천·댓글은 받은 값이 아니다
    a.post(f"/community/posts/{posts[0]['id']}/comments", json={"body": "a의 댓글"})
    a.post(f"/community/posts/{posts[1]['id']}/save")
    assert a.get("/community/me/summary").json() == {
        "post_count": 3, "comment_count": 1, "received_comment_count": 4, "received_like_count": 4,
        "liked_post_count": 1, "saved_post_count": 1, "unread_notification_count": 3}
    assert b.get("/community/me/summary").json() == {
        "post_count": 0, "comment_count": 3, "received_comment_count": 0, "received_like_count": 0,
        "liked_post_count": 3, "saved_post_count": 0, "unread_notification_count": 0}
    a.delete(f"/community/posts/{posts[2]['id']}")                                                  # 삭제된 글과 그 댓글·추천은 센 값에서 빠진다
    summary = a.get("/community/me/summary").json()
    assert summary["post_count"] == 2 and summary["received_comment_count"] == 3 and summary["received_like_count"] == 3
    b_summary = b.get("/community/me/summary").json()
    assert b_summary["comment_count"] == 2 and b_summary["liked_post_count"] == 2


def test_summary_counts_more_than_fifty_posts(alice):
    a, _ = alice
    for i in range(55):
        _post(a, title=f"많은 글 {i}", board_type="free")
    assert a.get("/community/me/summary").json()["post_count"] == 55                                  # 프론트가 50개만 받아 합산하던 문제

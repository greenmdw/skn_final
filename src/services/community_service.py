"""일반 커뮤니티 서비스 — 게시글·연결 제품·댓글·추천·조회.

권한·게시 조건·검증은 여기서 정한다(저장소는 쿼리만). 응답은 프론트(React /community)가 그대로 그릴 수 있는 dict 다.

공개 범위(정책 — 요청서 2.11 "비로그인 조회 허용 여부"): 게시(published)된 글·댓글은 로그인 없이 읽을 수 있다.
초안은 작성자만, 숨김은 작성자와 관리자만 본다. 작성·댓글·추천·삭제는 로그인이 필요하다.
"""
from __future__ import annotations

import hashlib
import math
import re
from uuid import UUID

from src.config import COMMUNITY_ADMIN_USER_IDS, COMMUNITY_BANNED_WORDS
from src.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from src.repo.community_repo import CommunityRepo

BOARD_TYPES = ("question", "review", "tip", "free")
SORTS = ("latest", "popular", "views", "recommend")
TITLE_MAX = 80
BODY_MAX = 20000
TAG_MAX_COUNT = 5
TAG_MAX_LEN = 20
COMMENT_MAX = 2000
PRODUCT_MAX = 5
PAGE_SIZE_MAX = 50
DELETED_COMMENT_TEXT = "삭제된 댓글입니다"

# 화면의 제품 종류 ↔ catalog.product.product_type
KIND_TO_TYPE = {"모니터": "monitor", "키보드": "keyboard", "마우스": "mouse", "스피커": "speaker",
                "CPU": "cpu", "GPU": "gpu", "RAM": "ram", "메인보드": "motherboard", "저장장치": "ssd",
                "파워": "psu", "케이스": "case", "쿨러": "cooler"}
TYPE_TO_KIND = {v: k for k, v in KIND_TO_TYPE.items()}
_BOARD_LABEL = {"question": "질문 · Q&A", "tip": "정보 · 팁", "free": "자유"}


def is_admin(user_id: UUID | None) -> bool:
    return user_id is not None and str(user_id) in COMMUNITY_ADMIN_USER_IDS


def _require_user(user_id: UUID | None) -> UUID:
    if user_id is None:
        raise Unauthorized("로그인이 필요합니다.")
    return user_id


def kind_to_type(kind: str | None) -> str | None:
    if kind is None or not str(kind).strip():
        return None
    kind = str(kind).strip()
    if kind in KIND_TO_TYPE:
        return KIND_TO_TYPE[kind]
    if kind.lower() in TYPE_TO_KIND:
        return kind.lower()
    raise ValidationFailed("지원하지 않는 제품 종류입니다.", field="product_kind")


# ── 검증 ────────────────────────────────────────────────────────────────────────────
def _check_banned(*texts: str) -> None:
    lowered = " ".join(texts).lower()
    for word in COMMUNITY_BANNED_WORDS:
        if word and word in lowered:
            raise ValidationFailed("사용할 수 없는 표현이 들어 있습니다.")


def _clean_tags(tags) -> list[str]:
    if tags is None:
        return []
    out: list[str] = []
    for raw in tags:
        tag = re.sub(r"\s+", " ", str(raw)).strip().lstrip("#")
        if not tag:
            continue
        if len(tag) > TAG_MAX_LEN:
            raise ValidationFailed(f"태그는 {TAG_MAX_LEN}자 이하로 적어 주세요.", field="tags")
        if tag not in out:
            out.append(tag)
    if len(out) > TAG_MAX_COUNT:
        raise ValidationFailed(f"태그는 {TAG_MAX_COUNT}개까지 달 수 있습니다.", field="tags")
    return out


def _check_lengths(title: str, body: str) -> None:
    if len(title) > TITLE_MAX:
        raise ValidationFailed(f"제목은 {TITLE_MAX}자 이하로 적어 주세요.", field="title")
    if len(body) > BODY_MAX:
        raise ValidationFailed(f"본문은 {BODY_MAX:,}자 이하로 적어 주세요.", field="body")


def _board(board_type: str | None) -> str:
    if board_type not in BOARD_TYPES:
        raise ValidationFailed("지원하지 않는 게시판입니다.", field="board_type")
    return board_type


# ── 직렬화 ──────────────────────────────────────────────────────────────────────────
def _excerpt(body: str, limit: int = 120) -> str:
    text = re.sub(r"[#>*`|\[\]]+", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _board_label(board_type: str, first_kind: str | None) -> str:
    if board_type == "review":
        return f"사용기 · {first_kind}" if first_kind else "사용기 · 리뷰"
    return _BOARD_LABEL[board_type]


def _product_out(link: dict) -> dict:
    name = link.get("product_name") or link.get("custom_product_name")
    return {"id": str(link["id"]), "product_id": str(link["product_id"]) if link["product_id"] else None,
            "product_kind": link["product_kind"], "name": name, "brand": link.get("product_brand"),
            "custom_product_name": link["custom_product_name"], "selected_option": link["selected_option"],
            "match_status": link["match_status"], "display_order": link["display_order"]}


def _item(row: dict, products: list[dict]) -> dict:
    return {
        "id": str(row["id"]), "board_type": row["board_type"],
        "board_label": _board_label(row["board_type"], row["first_product_kind"]),
        "title": row["title"], "excerpt": _excerpt(row["body"]),
        "author": {"id": str(row["author_user_id"]), "name": row["author_name"]},
        "is_example": row["is_example"], "status": row["status"],
        "comment_count": int(row["comment_count"]), "like_count": int(row["like_count"]), "view_count": int(row["view_count"]),
        "liked_by_me": bool(row["liked_by_me"]), "tags": list(row["tags"] or []),
        "products": [_product_out(p) for p in products],
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
    }


def _detail(row: dict, products: list[dict], me: UUID | None) -> dict:
    out = _item(row, products)
    mine = me is not None and row["author_user_id"] == me
    out.update(
        body=row["body"], version=row["version"], images=[],            # 이미지 첨부(2.6)는 아직 없다
        created_at=row["created_at"].isoformat(), updated_at=row["updated_at"].isoformat(),
        can_edit=bool(mine and row["status"] != "deleted"), can_delete=bool((mine or is_admin(me)) and row["status"] != "deleted"),
        is_mine=mine)
    return out


def _visible(row: dict | None, me: UUID | None) -> bool:
    if row is None or row["status"] == "deleted":
        return False
    if row["status"] == "published":
        return True
    mine = me is not None and row["author_user_id"] == me
    if row["status"] == "draft":
        return mine
    return mine or is_admin(me)            # hidden


def _load_visible(repo: CommunityRepo, post_id: UUID, me: UUID | None) -> dict:
    row = repo.get_post(post_id, me=me)
    if not _visible(row, me):
        raise NotFound("게시글을 찾을 수 없습니다.")
    return row


def _load_owned(repo: CommunityRepo, post_id: UUID, me: UUID | None, *, allow_admin: bool = False) -> dict:
    user = _require_user(me)
    row = repo.get_post(post_id, me=user)
    if row is None or row["status"] == "deleted":
        raise NotFound("게시글을 찾을 수 없습니다.")
    if row["author_user_id"] != user and not (allow_admin and is_admin(user)):
        if not _visible(row, user):
            raise NotFound("게시글을 찾을 수 없습니다.")
        raise Forbidden("작성자만 할 수 있습니다.")
    return row


# ── 글 ──────────────────────────────────────────────────────────────────────────────
def list_posts(conn, me: UUID | None, *, board_type: str | None = None, sort: str = "latest", q: str | None = None,
               author_id: UUID | None = None, product_kind: str | None = None, is_example: bool | None = None,
               mine: bool = False, status: str | None = None, page: int = 1, page_size: int = 10) -> dict:
    repo = CommunityRepo(conn)
    if sort not in SORTS:
        raise ValidationFailed("지원하지 않는 정렬입니다.", field="sort")
    if board_type is not None:
        _board(board_type)
    page, page_size = max(1, int(page)), min(max(1, int(page_size)), PAGE_SIZE_MAX)
    kind_label = None
    if product_kind:
        kind_label = TYPE_TO_KIND[kind_to_type(product_kind)]
    statuses = ["published"]
    if mine or status:
        user = _require_user(me)
        author_id = user
        wanted = status or "published"
        if wanted not in ("draft", "published", "hidden"):
            raise ValidationFailed("지원하지 않는 상태입니다.", field="status")
        statuses = [wanted]
    elif author_id is not None and author_id == me:
        statuses = ["published"]
    q = (q or "").strip() or None
    if q is not None and len(q) > 100:
        raise ValidationFailed("검색어는 100자 이하로 입력해 주세요.", field="q")
    rows, total = repo.list_posts(me=me, board_type=board_type, q=q, author_id=author_id, product_kind=kind_label,
                                  is_example=is_example, statuses=statuses, sort=sort, limit=page_size, offset=(page - 1) * page_size)
    products = repo.products_for([r["id"] for r in rows])
    return {"items": [_item(r, products.get(r["id"], [])) for r in rows], "page": page, "page_size": page_size,
            "total": total, "total_pages": max(1, math.ceil(total / page_size)) if total else 0}


def viewer_key(user_id: UUID | None, browser_token: str | None, ip: str, user_agent: str) -> str:
    if user_id is not None:
        return f"u:{user_id}"
    if browser_token:
        return "a:" + hashlib.sha1(browser_token.encode()).hexdigest()[:20]
    return "ip:" + hashlib.sha1(f"{ip}|{user_agent}".encode()).hexdigest()[:20]


def get_post(conn, me: UUID | None, post_id: UUID, *, view_key: str | None = None) -> dict:
    repo = CommunityRepo(conn)
    row = _load_visible(repo, post_id, me)
    if view_key and row["status"] == "published":
        if repo.record_view(post_id, view_key):
            row = repo.get_post(post_id, me=me)
    return _detail(row, repo.products_for([post_id]).get(post_id, []), me)


def _prepare_products(repo: CommunityRepo, items) -> list[dict]:
    """요청의 제품 목록을 검증하고 저장할 형태로 만든다(카탈로그 제품은 matched, 직접 입력은 unmatched/review_needed)."""
    items = list(items or [])
    if len(items) > PRODUCT_MAX:
        raise ValidationFailed(f"제품은 최대 {PRODUCT_MAX}개까지 연결할 수 있습니다.", field="products")
    prepared = []
    for order, item in enumerate(items):
        ptype = kind_to_type(item.get("product_kind"))
        if ptype is None:
            raise ValidationFailed("제품 종류를 골라 주세요.", field="product_kind")
        option = (item.get("selected_option") or "").strip() or None
        if option and len(option) > 60:
            raise ValidationFailed("옵션은 60자 이하로 적어 주세요.", field="selected_option")
        if item.get("product_id"):
            found = repo.find_catalog_product(UUID(str(item["product_id"])))
            if found is None:
                raise NotFound("카탈로그에 없는 상품입니다.", field="product_id")
            prepared.append(dict(product_id=found["id"], product_kind=TYPE_TO_KIND.get(found["product_type"], TYPE_TO_KIND[ptype]),
                                 custom_product_name=None, selected_option=option, match_status="matched", display_order=order))
        else:
            name = re.sub(r"\s+", " ", str(item.get("custom_product_name") or "")).strip()
            if not name:
                raise ValidationFailed("제품을 고르거나 제품명을 직접 입력해 주세요.", field="custom_product_name")
            if len(name) > 120:
                raise ValidationFailed("제품명은 120자 이하로 적어 주세요.", field="custom_product_name")
            similar = repo.similar_catalog_product(ptype, name)
            prepared.append(dict(product_id=None, product_kind=TYPE_TO_KIND[ptype], custom_product_name=name, selected_option=option,
                                 match_status="review_needed" if similar else "unmatched", display_order=order))
    return prepared


def _validate_publishable(repo: CommunityRepo, row: dict, *, board_type: str, title: str, body: str) -> None:
    if not title.strip():
        raise ValidationFailed("제목을 입력해 주세요.", field="title")
    if not body.strip():
        raise ValidationFailed("내용을 입력해 주세요.", field="body")
    if board_type == "review" and repo.product_count(row["id"]) < 1:
        raise ValidationFailed("사용기 · 리뷰는 제품을 1개 이상 연결해 주세요.", field="products")


def create_post(conn, me: UUID | None, data: dict) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    board_type = _board(data.get("board_type"))
    title, body = (data.get("title") or "").strip(), (data.get("body") or "").strip()
    _check_lengths(title, body)
    _check_banned(title, body)
    tags = _clean_tags(data.get("tags"))
    is_example = _example_flag(data, user)
    prepared = _prepare_products(repo, data.get("products"))
    publish = bool(data.get("publish"))
    post_id = repo.create_post(author_id=user, board_type=board_type, title=title, body=body, tags=tags, is_example=is_example)
    for item in prepared:
        repo.add_product(post_id, **item)
    if publish:
        row = repo.get_post(post_id, me=user)
        _validate_publishable(repo, row, board_type=board_type, title=title, body=body)
        repo.publish_post(post_id, expected_version=None)
    return get_post(conn, user, post_id)


def _example_flag(data: dict, user: UUID) -> bool:
    """is_example 은 관리자만 정할 수 있다. 일반 사용자가 true 를 보내면 거절한다."""
    value = data.get("is_example")
    if value is None or value is False:
        return False
    if not is_admin(user):
        raise Forbidden("예시 글 표시는 관리자만 정할 수 있습니다.", field="is_example")
    return bool(value)


def update_post(conn, me: UUID | None, post_id: UUID, data: dict) -> dict:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me, allow_admin=False)
    user = _require_user(me)
    fields: dict = {}
    board_type = row["board_type"]
    if "board_type" in data and data["board_type"] is not None:
        board_type = _board(data["board_type"]); fields["board_type"] = board_type
    title, body = row["title"], row["body"]
    if data.get("title") is not None:
        title = data["title"].strip(); fields["title"] = title
    if data.get("body") is not None:
        body = data["body"].strip(); fields["body"] = body
    _check_lengths(title, body)
    _check_banned(title, body)
    if data.get("tags") is not None:
        fields["tags"] = _clean_tags(data["tags"])
    if data.get("is_example") is not None:
        if bool(data["is_example"]) != row["is_example"]:
            if not is_admin(user):
                raise Forbidden("예시 글 표시는 관리자만 정할 수 있습니다.", field="is_example")
            fields["is_example"] = bool(data["is_example"])
    prepared = _prepare_products(repo, data["products"]) if data.get("products") is not None else None
    if row["status"] in ("published", "hidden"):
        # 게시된 글은 고친 뒤에도 게시 조건을 지켜야 한다
        if not title.strip() or not body.strip():
            raise ValidationFailed("제목과 내용은 비울 수 없습니다.")
    version = data.get("version")
    if not fields:
        fields = {"title": title}                    # 제품만 바꾸는 요청도 버전을 올려 충돌을 감지한다
    if not repo.update_post(post_id, expected_version=version, fields=fields):
        raise Conflict("다른 곳에서 먼저 수정했습니다. 새로 고친 뒤 다시 시도해 주세요.", code="version_conflict")
    if prepared is not None:
        repo.delete_all_products(post_id)
        for item in prepared:
            repo.add_product(post_id, **item)
    if row["status"] in ("published", "hidden"):
        current = repo.get_post(post_id, me=user)
        _validate_publishable(repo, current, board_type=board_type, title=title, body=body)
    return get_post(conn, user, post_id)


def publish_post(conn, me: UUID | None, post_id: UUID, *, version: int | None = None) -> dict:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me)
    if row["status"] == "published":
        return get_post(conn, me, post_id)
    if row["status"] == "hidden":
        raise Forbidden("숨김 처리된 글은 관리자만 복원할 수 있습니다.")
    _validate_publishable(repo, row, board_type=row["board_type"], title=row["title"], body=row["body"])
    if not repo.publish_post(post_id, expected_version=version):
        raise Conflict("다른 곳에서 먼저 수정했습니다. 새로 고친 뒤 다시 시도해 주세요.", code="version_conflict")
    return get_post(conn, me, post_id)


def delete_post(conn, me: UUID | None, post_id: UUID) -> None:
    repo = CommunityRepo(conn)
    _load_owned(repo, post_id, me, allow_admin=True)
    repo.set_status(post_id, "deleted")


def hide_post(conn, me: UUID | None, post_id: UUID) -> dict:
    user = _require_user(me)
    if not is_admin(user):
        raise Forbidden("관리자만 할 수 있습니다.")
    repo = CommunityRepo(conn)
    row = repo.get_post(post_id, me=user)
    if row is None or row["status"] == "deleted":
        raise NotFound("게시글을 찾을 수 없습니다.")
    if row["status"] != "published":
        raise Conflict("게시 중인 글만 숨길 수 있습니다.", code="not_published")
    repo.set_status(post_id, "hidden")
    return get_post(conn, user, post_id)


def restore_post(conn, me: UUID | None, post_id: UUID) -> dict:
    user = _require_user(me)
    if not is_admin(user):
        raise Forbidden("관리자만 할 수 있습니다.")
    repo = CommunityRepo(conn)
    row = repo.get_post(post_id, me=user)
    if row is None or row["status"] != "hidden":
        raise NotFound("숨김 처리된 게시글을 찾을 수 없습니다.")
    repo.set_status(post_id, "published")
    return get_post(conn, user, post_id)


# ── 연결 제품 ───────────────────────────────────────────────────────────────────────
def add_product_link(conn, me: UUID | None, post_id: UUID, item: dict) -> dict:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me)
    if repo.product_count(post_id) >= PRODUCT_MAX:
        raise ValidationFailed(f"제품은 최대 {PRODUCT_MAX}개까지 연결할 수 있습니다.", field="products")
    prepared = _prepare_products(repo, [item])[0]
    prepared["display_order"] = repo.product_count(post_id)
    repo.add_product(post_id, **prepared)
    return get_post(conn, me, post_id)


def remove_product_link(conn, me: UUID | None, post_id: UUID, link_id: UUID) -> dict:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me)
    if row["status"] in ("published", "hidden") and row["board_type"] == "review" and repo.product_count(post_id) <= 1:
        raise ValidationFailed("사용기 · 리뷰는 제품이 1개 이상 있어야 합니다.", field="products")
    if not repo.delete_product_link(post_id, link_id):
        raise NotFound("연결된 제품을 찾을 수 없습니다.")
    return get_post(conn, me, post_id)


def catalog_products(conn, *, kind: str | None, q: str | None, limit: int = 20) -> dict:
    repo = CommunityRepo(conn)
    ptype = kind_to_type(kind)
    q = (q or "").strip() or None
    limit = min(max(1, int(limit)), 50)
    items = []
    for r in repo.search_catalog(product_type=ptype, q=q, limit=limit):
        parts: list = []
        if r["product_type"] == "keyboard":
            parts = [r["switch_kind"], r["kb_connectivity"] if isinstance(r["kb_connectivity"], str) else None]
        elif r["product_type"] == "mouse":
            parts = [f"{float(r['mouse_weight_g']):g}g" if r["mouse_weight_g"] else None, r["mouse_sensor"]]
        elif r["product_type"] == "monitor":
            parts = [f"{r['screen_size_inch']}인치" if r["screen_size_inch"] else None, r["resolution"],
                     f"{r['max_refresh_hz']}Hz" if r["max_refresh_hz"] else None]
        elif r["product_type"] == "speaker":
            parts = [r["speaker_channels"]]
        options: list[str] = []
        if r["product_type"] == "keyboard" and r["switch_kind"]:
            options = [o.strip() for o in re.split(r"\s*/\s*", r["switch_kind"]) if o.strip()]
        items.append({"id": str(r["id"]), "kind": TYPE_TO_KIND.get(r["product_type"], r["product_type"]), "maker": r["brand"],
                      "name": r["name"], "model": r["model"], "detail": " · ".join(str(p) for p in parts if p),
                      "options": options, "image_url": r["image_url"]})
    return {"items": items}


# ── 댓글 ────────────────────────────────────────────────────────────────────────────
def _comment_out(c: dict, me: UUID | None) -> dict:
    mine = me is not None and c["author_user_id"] == me
    return {"id": str(c["id"]), "author": {"id": str(c["author_user_id"]), "name": c["author_name"]}, "body": c["body"],
            "is_deleted": False, "is_mine": mine, "can_edit": mine,
            "created_at": c["created_at"].isoformat(), "updated_at": c["updated_at"].isoformat(),
            "edited": (c["updated_at"] - c["created_at"]).total_seconds() > 1}


def list_comments(conn, me: UUID | None, post_id: UUID) -> dict:
    repo = CommunityRepo(conn)
    _load_visible(repo, post_id, me)
    rows = repo.comments_for(post_id)
    replies: dict[UUID, list[dict]] = {}
    for c in rows:
        if c["parent_comment_id"] and c["status"] == "published":
            replies.setdefault(c["parent_comment_id"], []).append(_comment_out(c, me))
    items = []
    for c in rows:
        if c["parent_comment_id"]:
            continue
        kids = replies.get(c["id"], [])
        if c["status"] == "deleted":
            if not kids:
                continue                                  # 답글이 없는 삭제 댓글은 목록에서 뺀다
            items.append({"id": str(c["id"]), "author": None, "body": DELETED_COMMENT_TEXT, "is_deleted": True, "is_mine": False,
                          "can_edit": False, "created_at": c["created_at"].isoformat(), "updated_at": c["updated_at"].isoformat(),
                          "edited": False, "replies": kids})
            continue
        item = _comment_out(c, me)
        item["replies"] = kids
        items.append(item)
    total = sum(1 + len(i["replies"]) for i in items if not i["is_deleted"]) + sum(len(i["replies"]) for i in items if i["is_deleted"])
    return {"items": items, "total": total}


def _comment_body(text: str | None) -> str:
    body = (text or "").strip()
    if not body:
        raise ValidationFailed("댓글 내용을 입력해 주세요.", field="body")
    if len(body) > COMMENT_MAX:
        raise ValidationFailed(f"댓글은 {COMMENT_MAX:,}자 이하로 적어 주세요.", field="body")
    _check_banned(body)
    return body


def add_comment(conn, me: UUID | None, post_id: UUID, text: str | None) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    row = _load_visible(repo, post_id, user)
    if row["status"] != "published":
        raise Conflict("게시된 글에만 댓글을 달 수 있습니다.", code="not_published")
    body = _comment_body(text)
    comment_id = repo.create_comment(post_id=post_id, author_id=user, body=body, parent_id=None)
    return _comment_out(repo.get_comment(comment_id), user) | {"replies": []}


def add_reply(conn, me: UUID | None, comment_id: UUID, text: str | None) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    parent = repo.get_comment(comment_id)
    if parent is None:
        raise NotFound("댓글을 찾을 수 없습니다.")
    row = _load_visible(repo, parent["post_id"], user)
    if row["status"] != "published":
        raise Conflict("게시된 글에만 댓글을 달 수 있습니다.", code="not_published")
    if parent["parent_comment_id"] is not None:
        raise ValidationFailed("답글에는 다시 답글을 달 수 없습니다.", field="comment_id")
    if parent["status"] != "published":
        raise Conflict("삭제된 댓글에는 답글을 달 수 없습니다.", code="comment_deleted")
    body = _comment_body(text)
    reply_id = repo.create_comment(post_id=parent["post_id"], author_id=user, body=body, parent_id=comment_id)
    return _comment_out(repo.get_comment(reply_id), user)


def _owned_comment(repo: CommunityRepo, comment_id: UUID, me: UUID | None) -> dict:
    user = _require_user(me)
    comment = repo.get_comment(comment_id)
    if comment is None or comment["status"] != "published":
        raise NotFound("댓글을 찾을 수 없습니다.")
    if comment["author_user_id"] != user and not is_admin(user):
        raise Forbidden("작성자만 할 수 있습니다.")
    return comment


def update_comment(conn, me: UUID | None, comment_id: UUID, text: str | None) -> dict:
    repo = CommunityRepo(conn)
    comment = _owned_comment(repo, comment_id, me)
    if comment["author_user_id"] != me:
        raise Forbidden("작성자만 수정할 수 있습니다.")
    repo.update_comment(comment_id, _comment_body(text))
    return _comment_out(repo.get_comment(comment_id), me)


def delete_comment(conn, me: UUID | None, comment_id: UUID) -> None:
    repo = CommunityRepo(conn)
    _owned_comment(repo, comment_id, me)
    repo.soft_delete_comment(comment_id)


# ── 추천 ────────────────────────────────────────────────────────────────────────────
def set_like(conn, me: UUID | None, post_id: UUID, liked: bool) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    row = _load_visible(repo, post_id, user)
    if row["status"] != "published":
        raise Conflict("게시된 글만 추천할 수 있습니다.", code="not_published")
    (repo.add_like if liked else repo.remove_like)(post_id, user)
    return {"post_id": str(post_id), "like_count": repo.like_count(post_id), "liked_by_me": liked}

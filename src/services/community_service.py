"""일반 커뮤니티 서비스 — 게시글·연결 제품·댓글·추천·조회.

권한·게시 조건·검증은 여기서 정한다(저장소는 쿼리만). 응답은 프론트(React /community)가 그대로 그릴 수 있는 dict 다.

공개 범위(정책 — 요청서 2.11 "비로그인 조회 허용 여부"): 게시(published)된 글·댓글은 로그인 없이 읽을 수 있다.
초안은 작성자만, 숨김은 작성자와 관리자만 본다. 작성·댓글·추천·삭제는 로그인이 필요하다.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from uuid import UUID

from src.config import (
    COMMUNITY_ADMIN_USER_IDS, COMMUNITY_BANNED_WORDS, COMMUNITY_IMAGE_MAX_BYTES, COMMUNITY_IMAGE_MAX_PER_POST,
    COMMUNITY_IMAGE_MAX_SIDE_PX, COMMUNITY_IMAGE_ORPHAN_HOURS, COMMUNITY_UPLOAD_DIR,
)
from src.errors import Conflict, FileTooLarge, Forbidden, NotFound, Unauthorized, ValidationFailed
from src.repo.community_repo import CommunityRepo
from src.repo.peripheral_post_repo import DbIntakeStore
from src.services.community_post_intake import on_post_changed
from src.storage.community_images import InvalidImage, LocalImageStore, process_image

log = logging.getLogger(__name__)

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


def _notify_changed(conn, post_id: UUID, status: str) -> None:
    """글이 게시·수정·삭제·숨김·복원되거나 제품·이미지가 바뀌었음을 주변기기 사용기 분석에 알린다(개발요청 B-4).

    분석 작업은 별도 프로세스라서 대기 기록은 DB(engine.peripheral_post_intake)에 남긴다. 글 저장과 같은 트랜잭션이라
    글이 저장되지 않으면 기록도 없고, 이 기록이 실패해도(0015 가 아직 적용되지 않은 DB 등) 글 저장은 성공한다 —
    on_post_changed 가 예외를 삼키고, DbIntakeStore.put 이 세이브포인트 안에서 쓴다.
    임시 저장(draft)은 아직 게시된 적이 없어 알리지 않는다."""
    if status == "draft":
        return
    on_post_changed(post_id, store=DbIntakeStore(conn))


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
_ANY_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")                     # 마크다운 이미지 전체(설명 문구 포함)
_IMAGE_MARKER_RE = re.compile(r"!\[[^\]]*\]\(image:([^)\s]*)\)")           # 본문 이미지 마커 ![설명](image:<id>)


def _excerpt(body: str, limit: int = 120) -> str:
    text = _ANY_IMAGE_RE.sub(" ", body or "")
    text = re.sub(r"[#>*`|\[\]]+", " ", text)
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
            "match_status": link["match_status"], "display_order": link["display_order"],
            "image_url": link.get("product_image_url")}


def _item(row: dict, products: list[dict]) -> dict:
    return {
        "id": str(row["id"]), "board_type": row["board_type"],
        "board_label": _board_label(row["board_type"], row["first_product_kind"]),
        "title": row["title"], "excerpt": _excerpt(row["body"]),
        "author": {"id": str(row["author_user_id"]), "name": row["author_name"]},
        "is_example": row["is_example"], "status": row["status"],
        "comment_count": int(row["comment_count"]), "like_count": int(row["like_count"]), "view_count": int(row["view_count"]),
        "liked_by_me": bool(row["liked_by_me"]), "saved_by_me": bool(row.get("saved_by_me")), "tags": list(row["tags"] or []),
        "products": [_product_out(p) for p in products],
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        "image_count": int(row.get("image_count") or 0),
        "cover_image_url": image_url(row["cover_image_id"]) if row.get("cover_image_id") else None,
    }


def image_url(image_id) -> str:
    return f"/community/images/{image_id}"


def _image_out(row: dict) -> dict:
    return {"id": str(row["id"]), "url": image_url(row["id"]), "width": row["width"], "height": row["height"], "order": row["display_order"]}


def _detail(row: dict, products: list[dict], me: UUID | None, images: list[dict] | None = None) -> dict:
    out = _item(row, products)
    mine = me is not None and row["author_user_id"] == me
    out.update(
        body=row["body"], version=row["version"], images=[_image_out(i) for i in images or []],
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
    return _detail(row, repo.products_for([post_id]).get(post_id, []), me, repo.images_for([post_id]).get(post_id, []))


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


# ── 이미지 첨부 ─────────────────────────────────────────────────────────────────────
ORPHAN_QUOTA = 10                # 사용자당 글에 붙이지 않은 임시 이미지 최대 수


def _store() -> LocalImageStore:
    return LocalImageStore(COMMUNITY_UPLOAD_DIR)


def _remove_files(keys: list[str]) -> None:
    store = _store()
    for key in keys:
        store.delete(key)


def cleanup_orphan_images(conn, *, hours: int | None = None, limit: int = 200) -> int:
    """글에 붙지 않은 채 오래된 임시 이미지를 지운다(올릴 때마다 조금씩 돌고, 스크립트로도 부를 수 있다)."""
    keys = CommunityRepo(conn).delete_orphans(older_than_hours=COMMUNITY_IMAGE_ORPHAN_HOURS if hours is None else hours, limit=limit)
    _remove_files(keys)
    return len(keys)


def upload_image(conn, me: UUID | None, raw: bytes) -> dict:
    user = _require_user(me)
    if not raw:
        raise ValidationFailed("빈 파일입니다.", field="file")
    if len(raw) > COMMUNITY_IMAGE_MAX_BYTES:
        raise FileTooLarge(f"이미지는 {COMMUNITY_IMAGE_MAX_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다.", field="file")
    repo = CommunityRepo(conn)
    cleanup_orphan_images(conn, limit=50)
    if repo.count_orphans(user) >= ORPHAN_QUOTA:
        raise ValidationFailed("글에 붙이지 않은 이미지가 너무 많습니다. 글을 저장하거나 이미지를 지운 뒤 다시 올려 주세요.", field="file")
    try:
        processed = process_image(raw, max_side=COMMUNITY_IMAGE_MAX_SIDE_PX)
    except InvalidImage as exc:
        raise ValidationFailed(str(exc), field="file") from exc
    store = _store()
    key = store.new_key(processed.content_type)
    store.save(key, processed.data)
    try:
        row = repo.insert_image(owner_id=user, storage_key=key, content_type=processed.content_type,
                                width=processed.width, height=processed.height, byte_size=len(processed.data))
    except Exception:
        store.delete(key)
        raise
    return _image_out(row)


def delete_upload(conn, me: UUID | None, image_id: UUID) -> None:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    row = repo.get_image(image_id)
    if row is None or row["owner_user_id"] != user:
        raise NotFound("이미지를 찾을 수 없습니다.")
    if row["post_id"] is not None:
        raise Conflict("글에 붙은 이미지는 글을 수정해서 뺄 수 있습니다.", code="image_attached")
    repo.delete_image(image_id)
    _remove_files([row["storage_key"]])


def read_image(conn, me: UUID | None, image_id: UUID) -> tuple[bytes, str, bool]:
    """(바이트, 형식, 공개 여부). 글에 붙은 이미지는 그 글을 볼 수 있는 사람만, 임시 이미지는 올린 사람만 본다."""
    repo = CommunityRepo(conn)
    row = repo.get_image(image_id)
    if row is None:
        raise NotFound("이미지를 찾을 수 없습니다.")
    if row["post_id"] is None:
        if me is None or row["owner_user_id"] != me:
            raise NotFound("이미지를 찾을 수 없습니다.")
        public = False
    else:
        if not _visible(repo.get_post(row["post_id"], me=me), me):
            raise NotFound("이미지를 찾을 수 없습니다.")
        public = True
    data = _store().read(row["storage_key"])
    if data is None:
        raise NotFound("이미지를 찾을 수 없습니다.")
    return data, row["content_type"], public


def _apply_images(repo: CommunityRepo, user: UUID, post_id: UUID, raw_ids) -> None:
    """글의 이미지를 image_ids 순서대로 정한다. 내가 올린 이미지(임시이거나 이 글에 붙은 것)만 쓸 수 있다."""
    try:
        ids = [UUID(str(x)) for x in (raw_ids or [])]
    except ValueError:
        raise ValidationFailed("이미지 id 형식이 올바르지 않습니다.", field="image_ids") from None
    if len(set(ids)) != len(ids):
        raise ValidationFailed("같은 이미지를 두 번 넣을 수 없습니다.", field="image_ids")
    if len(ids) > COMMUNITY_IMAGE_MAX_PER_POST:
        raise ValidationFailed(f"이미지는 글당 최대 {COMMUNITY_IMAGE_MAX_PER_POST}장까지 붙일 수 있습니다.", field="image_ids")
    for image_id in ids:
        row = repo.get_image(image_id)
        if row is None or row["owner_user_id"] != user or row["post_id"] not in (None, post_id):
            raise ValidationFailed("사용할 수 없는 이미지입니다.", field="image_ids")
    _remove_files(repo.attach_images(post_id, ids))


def _uuid_set(raw_ids) -> set[str]:
    out: set[str] = set()
    for value in raw_ids or []:
        try:
            out.add(str(UUID(str(value))))
        except ValueError:
            continue                                   # 형식이 틀린 id 는 _apply_images 가 422 로 거절한다
    return out


def _strip_foreign_image_markers(body: str, allowed: set[str]) -> str:
    """본문의 이미지 마커 중 `allowed`(이 글의 이미지 id)에 없는 것을 지운다. 저장이 실패하지 않고 조용히 정리된다.
    프론트 미리보기가 "이 글의 이미지가 아니면 그리지 않는다"로 그리는 것과 같은 결과다."""
    def keep(match: re.Match) -> str:
        try:
            image_id = str(UUID(match.group(1)))
        except ValueError:
            return ""
        return match.group(0) if image_id in allowed else ""

    cleaned = _IMAGE_MARKER_RE.sub(keep, body)
    if cleaned != body:
        cleaned = re.sub(r"\n[ \t]*(?:\n[ \t]*){2,}", "\n\n", cleaned).strip()     # 마커 줄이 빠진 자리의 빈 줄 정리
    return cleaned


def create_post(conn, me: UUID | None, data: dict) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    board_type = _board(data.get("board_type"))
    title, body = (data.get("title") or "").strip(), (data.get("body") or "").strip()
    body = _strip_foreign_image_markers(body, _uuid_set(data.get("image_ids")))
    _check_lengths(title, body)
    _check_banned(title, body)
    tags = _clean_tags(data.get("tags"))
    is_example = _example_flag(data, user)
    prepared = _prepare_products(repo, data.get("products"))
    publish = bool(data.get("publish"))
    post_id = repo.create_post(author_id=user, board_type=board_type, title=title, body=body, tags=tags, is_example=is_example)
    for item in prepared:
        repo.add_product(post_id, **item)
    if data.get("image_ids") is not None:
        _apply_images(repo, user, post_id, data["image_ids"])
    if publish:
        row = repo.get_post(post_id, me=user)
        _validate_publishable(repo, row, board_type=board_type, title=title, body=body)
        repo.publish_post(post_id, expected_version=None)
        _notify_changed(conn, post_id, "published")
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
    if data.get("body") is not None or data.get("image_ids") is not None:
        # 이미지가 글에서 빠졌거나(⑤) 본문에 남의 이미지 마커가 들어온 경우(④) 본문에서 그 마커를 지운다
        allowed = (_uuid_set(data["image_ids"]) if data.get("image_ids") is not None
                   else {str(i["id"]) for i in repo.images_for([post_id]).get(post_id, [])})
        cleaned = _strip_foreign_image_markers(body, allowed)
        if cleaned != body:
            body = cleaned
            fields["body"] = body
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
    if data.get("image_ids") is not None:
        _apply_images(repo, user, post_id, data["image_ids"])
    if row["status"] in ("published", "hidden"):
        current = repo.get_post(post_id, me=user)
        _validate_publishable(repo, current, board_type=board_type, title=title, body=body)
    _notify_changed(conn, post_id, row["status"])
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
    _notify_changed(conn, post_id, "published")
    return get_post(conn, me, post_id)


def delete_post(conn, me: UUID | None, post_id: UUID) -> None:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me, allow_admin=True)
    repo.set_status(post_id, "deleted")
    _remove_files(repo.delete_post_images(post_id))
    _notify_changed(conn, post_id, row["status"])


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
    _notify_changed(conn, post_id, "hidden")
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
    _notify_changed(conn, post_id, "published")
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
    _notify_changed(conn, post_id, row["status"])
    return get_post(conn, me, post_id)


def remove_product_link(conn, me: UUID | None, post_id: UUID, link_id: UUID) -> dict:
    repo = CommunityRepo(conn)
    row = _load_owned(repo, post_id, me)
    if row["status"] in ("published", "hidden") and row["board_type"] == "review" and repo.product_count(post_id) <= 1:
        raise ValidationFailed("사용기 · 리뷰는 제품이 1개 이상 있어야 합니다.", field="products")
    if not repo.delete_product_link(post_id, link_id):
        raise NotFound("연결된 제품을 찾을 수 없습니다.")
    _notify_changed(conn, post_id, row["status"])
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
    if row["author_user_id"] != user:                                          # 내가 내 글에 단 댓글은 알리지 않는다
        repo.upsert_notification(user_id=row["author_user_id"], type_="new_comment", post_id=post_id, comment_id=comment_id, actor_id=user)
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
    if parent["author_user_id"] != user:                                       # 내 댓글에 답글 → 댓글 작성자에게
        repo.upsert_notification(user_id=parent["author_user_id"], type_="new_reply", post_id=parent["post_id"], comment_id=reply_id, actor_id=user)
    if row["author_user_id"] not in (user, parent["author_user_id"]):          # 내 글에 달린 대화 → 글 작성자에게(이미 답글 알림을 받는 사람은 제외)
        repo.upsert_notification(user_id=row["author_user_id"], type_="new_comment", post_id=parent["post_id"], comment_id=reply_id, actor_id=user)
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


# ── 저장(북마크) ────────────────────────────────────────────────────────────────────
def set_save(conn, me: UUID | None, post_id: UUID, saved: bool) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    row = _load_visible(repo, post_id, user)
    if row["status"] != "published":
        raise Conflict("게시된 글만 저장할 수 있습니다.", code="not_published")
    (repo.add_save if saved else repo.remove_save)(post_id, user)
    return {"post_id": str(post_id), "saved_by_me": saved}


# ── 내 활동(마이페이지 "나의 커뮤니티") ─────────────────────────────────────────────────
ME_SORTS = ("latest", "popular", "comments")
_GONE_TITLE = {"hidden": "숨겨진 글입니다", "deleted": "삭제된 글입니다"}


def _me_list_args(board_type: str | None, sort: str, page: int, page_size: int) -> tuple[str | None, str, int, int]:
    if sort not in ME_SORTS:
        raise ValidationFailed("지원하지 않는 정렬입니다.", field="sort")
    if board_type is not None:
        _board(board_type)
    return board_type, sort, max(1, int(page)), min(max(1, int(page_size)), PAGE_SIZE_MAX)


def _page_out(items: list[dict], page: int, page_size: int, total: int) -> dict:
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, math.ceil(total / page_size)) if total else 0}


def me_summary(conn, me: UUID | None) -> dict:
    user = _require_user(me)
    row = CommunityRepo(conn).activity_summary(user)
    return {key: int(value) for key, value in row.items()}


def _me_posts(conn, me: UUID | None, kind: str, board_type, sort, page, page_size) -> dict:
    user = _require_user(me)
    board_type, sort, page, page_size = _me_list_args(board_type, sort, page, page_size)
    repo = CommunityRepo(conn)
    rows, total = repo.list_user_posts(me=user, kind=kind, board_type=board_type, sort=sort, limit=page_size, offset=(page - 1) * page_size)
    products = repo.products_for([r["id"] for r in rows if r["status"] == "published"])
    when_key = "liked_at" if kind == "liked" else "saved_at"
    items = []
    for r in rows:
        if r["status"] == "published":
            item = _item(r, products.get(r["id"], []))
        else:                                                   # 숨김·삭제된 글: 항목은 남기되 본문 요약·제품·이미지는 비운다
            item = _item(r, [])
            item.update(title=_GONE_TITLE[r["status"]], excerpt="", tags=[], image_count=0, cover_image_url=None)
        item["post_status"] = r["status"]
        item[when_key] = r["rel_at"].isoformat()
        items.append(item)
    return _page_out(items, page, page_size, total)


def me_liked_posts(conn, me: UUID | None, *, board_type: str | None = None, sort: str = "latest", page: int = 1, page_size: int = 10) -> dict:
    return _me_posts(conn, me, "liked", board_type, sort, page, page_size)


def me_saved_posts(conn, me: UUID | None, *, board_type: str | None = None, sort: str = "latest", page: int = 1, page_size: int = 10) -> dict:
    return _me_posts(conn, me, "saved", board_type, sort, page, page_size)


def me_comments(conn, me: UUID | None, *, board_type: str | None = None, sort: str = "latest", page: int = 1, page_size: int = 10) -> dict:
    user = _require_user(me)
    board_type, sort, page, page_size = _me_list_args(board_type, sort, page, page_size)
    rows, total = CommunityRepo(conn).list_my_comments(me=user, board_type=board_type, sort=sort, limit=page_size, offset=(page - 1) * page_size)
    items = []
    for r in rows:
        gone = r["post_status"] != "published"
        items.append({
            "id": str(r["id"]), "body": r["body"], "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
            "parent_comment_id": str(r["parent_comment_id"]) if r["parent_comment_id"] else None,
            "reply_count": int(r["reply_count"]), "post_status": r["post_status"],
            "post": {"id": str(r["post_id"]), "title": _GONE_TITLE[r["post_status"]] if gone else r["post_title"],
                     "board_type": r["board_type"], "board_label": _board_label(r["board_type"], r["first_product_kind"]),
                     "status": r["post_status"]},
        })
    return _page_out(items, page, page_size, total)


# ── 알림(폴링) ──────────────────────────────────────────────────────────────────────
_BOARD_NOUN = {"question": "질문", "review": "사용기", "tip": "정보 글", "free": "글"}


def _notification_out(row: dict) -> dict:
    count = int(row["event_count"])
    if row["type"] == "new_reply":
        title = "내 댓글에 답글이 달렸어요" if count == 1 else f"내 댓글에 새 답글이 {count}개 달렸어요"
    else:
        noun = _BOARD_NOUN.get(row["board_type"], "글")
        title = f"내 {noun}에 새 댓글이 달렸어요" if count == 1 else f"내 {noun}에 새 댓글이 {count}개 달렸어요"
    return {"id": str(row["id"]), "type": row["type"], "title": title, "message": row["post_title"], "count": count,
            "post_id": str(row["post_id"]), "comment_id": str(row["comment_id"]) if row["comment_id"] else None,
            "read": row["read_at"] is not None, "created_at": row["latest_at"].isoformat()}


def me_notifications(conn, me: UUID | None, *, unread: bool = False, page: int = 1, page_size: int = 20) -> dict:
    user = _require_user(me)
    page, page_size = max(1, int(page)), min(max(1, int(page_size)), PAGE_SIZE_MAX)
    repo = CommunityRepo(conn)
    rows, total = repo.list_notifications(me=user, unread_only=unread, limit=page_size, offset=(page - 1) * page_size)
    out = _page_out([_notification_out(r) for r in rows], page, page_size, total)
    return {"unread_count": repo.unread_notification_count(user), **out}


def me_unread_count(conn, me: UUID | None) -> dict:
    user = _require_user(me)
    return {"unread_count": CommunityRepo(conn).unread_notification_count(user)}


def mark_notification_read(conn, me: UUID | None, notification_id: UUID) -> dict:
    user = _require_user(me)
    repo = CommunityRepo(conn)
    if repo.notification_owner(notification_id) != user:
        raise NotFound("알림을 찾을 수 없습니다.")
    repo.mark_notification_read(notification_id)
    return {"id": str(notification_id), "read": True, "unread_count": repo.unread_notification_count(user)}


def mark_all_notifications_read(conn, me: UUID | None) -> dict:
    user = _require_user(me)
    changed = CommunityRepo(conn).mark_all_notifications_read(user)
    return {"updated": changed, "unread_count": 0}

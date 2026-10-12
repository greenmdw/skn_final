"""/community/* — 일반 커뮤니티(질문·사용기·정보·자유) 게시글·댓글·추천·조회, /catalog/products — 연결 제품 검색.

읽기(목록·상세·검색·댓글)는 로그인 없이 되고, 쓰기는 로그인이 필요하다(서비스가 401 을 낸다).
상세(`GET /community/posts/{id}`)는 조회 이벤트를 기록한다 — (글, 조회자, 한 시간)당 한 번만 센다.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from src.auth import ratelimit
from src.auth.deps import Principal, optional_principal
from src.config import COMMUNITY_COMMENT_LIMIT_PER_MIN, COMMUNITY_LIKE_LIMIT_PER_MIN, COMMUNITY_POST_LIMIT_PER_MIN
from src.db import get_conn
from src.errors import RateLimited
from src.services import community_service as svc

router = APIRouter(prefix="/community", tags=["community"])
catalog_router = APIRouter(prefix="/catalog", tags=["community"])


class ProductLinkIn(BaseModel):
    product_id: UUID | None = None
    product_kind: str
    custom_product_name: str | None = Field(default=None, max_length=120)
    selected_option: str | None = Field(default=None, max_length=60)


class PostCreateIn(BaseModel):
    board_type: str
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    products: list[ProductLinkIn] = Field(default_factory=list, max_length=20)
    publish: bool = False                              # true 면 만들면서 바로 게시, false 면 초안(임시 저장)
    is_example: bool | None = None                     # 관리자만 true 를 줄 수 있다


class PostUpdateIn(BaseModel):
    board_type: str | None = None
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=20)
    products: list[ProductLinkIn] | None = Field(default=None, max_length=20)
    is_example: bool | None = None
    version: int | None = None                         # 읽을 때 받은 version — 다르면 409(version_conflict)


class PublishIn(BaseModel):
    version: int | None = None


class CommentIn(BaseModel):
    body: str = Field(default="", max_length=5000)


def _limit(user_id: UUID | None, kind: str, per_min: int) -> None:
    if user_id is not None and not ratelimit.allow(f"community-{kind}:{user_id}", limit=per_min, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")


def _list(me: UUID | None, **kwargs) -> dict:
    with get_conn() as conn:
        return svc.list_posts(conn, me, **kwargs)


@router.get("/posts")
def list_posts(
    principal: Principal = Depends(optional_principal),
    board_type: str | None = Query(None, description="question · review · tip · free"),
    sort: str = Query("latest", description="latest · popular · views · recommend"),
    q: str | None = Query(None, description="제목·본문·작성자·태그·연결 제품명 검색"),
    author_id: UUID | None = None,
    product_kind: str | None = Query(None, description="연결 제품 종류(모니터·키보드·마우스·스피커 …)"),
    is_example: bool | None = None,
    mine: bool = Query(False, description="내 글만(로그인 필요). status=draft 와 함께 쓰면 내 임시 저장"),
    status_: str | None = Query(None, alias="status", description="mine=true 일 때만: draft · published · hidden"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=svc.PAGE_SIZE_MAX),
) -> dict:
    return _list(principal.user_id, board_type=board_type, sort=sort, q=q, author_id=author_id, product_kind=product_kind,
                 is_example=is_example, mine=mine, status=status_, page=page, page_size=page_size)


@router.get("/search")
def search(
    principal: Principal = Depends(optional_principal),
    q: str = Query(..., min_length=1, description="검색어"),
    board_type: str | None = None,
    sort: str = Query("latest"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=svc.PAGE_SIZE_MAX),
) -> dict:
    return _list(principal.user_id, board_type=board_type, sort=sort, q=q, page=page, page_size=page_size)


@router.get("/posts/{post_id}")
def get_post(post_id: UUID, request: Request, principal: Principal = Depends(optional_principal)) -> dict:
    key = svc.viewer_key(principal.user_id, principal.browser_token, ratelimit.client_ip(request), request.headers.get("user-agent", ""))
    with get_conn() as conn:
        return svc.get_post(conn, principal.user_id, post_id, view_key=key)


@router.post("/posts", status_code=status.HTTP_201_CREATED)
def create_post(body: PostCreateIn, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "post", COMMUNITY_POST_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.create_post(conn, principal.user_id, body.model_dump(mode="json"))


@router.patch("/posts/{post_id}")
def update_post(post_id: UUID, body: PostUpdateIn, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.update_post(conn, principal.user_id, post_id, body.model_dump(mode="json", exclude_unset=True))


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: UUID, principal: Principal = Depends(optional_principal)) -> Response:
    with get_conn() as conn:
        svc.delete_post(conn, principal.user_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/posts/{post_id}/publish")
def publish_post(post_id: UUID, body: PublishIn | None = None, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "post", COMMUNITY_POST_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.publish_post(conn, principal.user_id, post_id, version=body.version if body else None)


@router.post("/posts/{post_id}/hide")
def hide_post(post_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.hide_post(conn, principal.user_id, post_id)


@router.post("/posts/{post_id}/restore")
def restore_post(post_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.restore_post(conn, principal.user_id, post_id)


@router.post("/posts/{post_id}/products", status_code=status.HTTP_201_CREATED)
def add_product(post_id: UUID, body: ProductLinkIn, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.add_product_link(conn, principal.user_id, post_id, body.model_dump(mode="json"))


@router.delete("/posts/{post_id}/products/{link_id}")
def remove_product(post_id: UUID, link_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.remove_product_link(conn, principal.user_id, post_id, link_id)


@router.get("/posts/{post_id}/comments")
def list_comments(post_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.list_comments(conn, principal.user_id, post_id)


@router.post("/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(post_id: UUID, body: CommentIn, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "comment", COMMUNITY_COMMENT_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.add_comment(conn, principal.user_id, post_id, body.body)


@router.post("/comments/{comment_id}/replies", status_code=status.HTTP_201_CREATED)
def add_reply(comment_id: UUID, body: CommentIn, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "comment", COMMUNITY_COMMENT_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.add_reply(conn, principal.user_id, comment_id, body.body)


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: UUID, body: CommentIn, principal: Principal = Depends(optional_principal)) -> dict:
    with get_conn() as conn:
        return svc.update_comment(conn, principal.user_id, comment_id, body.body)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: UUID, principal: Principal = Depends(optional_principal)) -> Response:
    with get_conn() as conn:
        svc.delete_comment(conn, principal.user_id, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/posts/{post_id}/likes")
def like(post_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "like", COMMUNITY_LIKE_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.set_like(conn, principal.user_id, post_id, True)


@router.delete("/posts/{post_id}/likes")
def unlike(post_id: UUID, principal: Principal = Depends(optional_principal)) -> dict:
    _limit(principal.user_id, "like", COMMUNITY_LIKE_LIMIT_PER_MIN)
    with get_conn() as conn:
        return svc.set_like(conn, principal.user_id, post_id, False)


@catalog_router.get("/products")
def catalog_products(
    kind: str | None = Query(None, description="모니터·키보드·마우스·스피커 …(또는 monitor·keyboard 코드)"),
    q: str | None = Query(None, description="제품명·브랜드·모델 검색어"),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    with get_conn() as conn:
        return svc.catalog_products(conn, kind=kind, q=q, limit=limit)

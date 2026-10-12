"""사용기 분석이 커뮤니티 글을 읽는 통로(요청서 B-3) — `community.*` 테이블을 **읽기 전용**으로 조회한다.

커뮤니티 담당의 테이블(0013·0014)과 API 는 건드리지 않는다. 여기서는 분석에 필요한 값만 SELECT 한다.
커뮤니티가 글 변경 알림 함수를 부르지 않아도 되도록, 마지막으로 본 시각 이후 바뀐 글을 찾는 조회도 둔다(W-2 대안).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from src.agent.peripheral_post_agent import content_hash
from src.engine.peripheral_post_contract import LinkedProduct, PostInput
from src.services.community_post_intake import REVIEW_BOARD, PostSnapshot

_KINDS = {"monitor", "keyboard", "mouse", "speaker"}
# community.post.status → 분석 계약의 PostStatus. 임시 저장(draft)은 아직 게시되지 않은 글이라 숨김과 같이 취급한다.
_STATUS = {"published": "published", "hidden": "hidden", "deleted": "deleted", "draft": "hidden"}


def _image_url(image_id: Any) -> str:
    return f"/community/images/{image_id}"      # community_service.image_url 과 같은 규칙


def load_post_input(conn, post_id: UUID | str) -> PostInput | None:
    """글 하나를 분석 입력으로 읽는다. 글이 없으면 None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, author_user_id, board_type, body, status, is_example, published_at FROM community.post WHERE id = %s",
            (str(post_id),),
        )
        post = cur.fetchone()
        if post is None:
            return None
        cur.execute(
            """SELECT pp.product_id, pp.product_kind, pp.custom_product_name, pp.selected_option,
                      p.brand, p.model, p.product_type
               FROM community.post_product pp
               LEFT JOIN catalog.product p ON p.id = pp.product_id
               WHERE pp.post_id = %s ORDER BY pp.display_order, pp.created_at""",
            (str(post_id),),
        )
        links = cur.fetchall()
        cur.execute(
            "SELECT id FROM community.post_image WHERE post_id = %s ORDER BY display_order, created_at LIMIT 1",
            (str(post_id),),
        )
        image = cur.fetchone()
    products = []
    for index, link in enumerate(links):
        # community.post_product.product_kind 는 화면 표시 이름("마우스")이라 카탈로그의 product_type 을 쓴다.
        kind = link["product_type"] if link["product_type"] in _KINDS else None
        name = f"{link['brand']} {link['model']}".strip() if link["product_id"] else (link["custom_product_name"] or "")
        products.append(LinkedProduct(
            index=index, product_id=str(link["product_id"]) if link["product_id"] else None,
            kind=kind if link["product_id"] else None, name=name, option_label=link["selected_option"],
        ))
    return PostInput(
        post_id=str(post["id"]), author_id=str(post["author_user_id"]), board=post["board_type"], body=post["body"] or "",
        products=products, status=_STATUS.get(post["status"], "hidden"), is_example=bool(post["is_example"]),
        written_at=post["published_at"], photo_url=_image_url(image["id"]) if image else None,
    )


def load_snapshot(conn, post_id: UUID | str) -> PostSnapshot | None:
    """처리 규칙(`community_post_intake.decide`)이 쓰는 글의 현재 상태."""
    post = load_post_input(conn, post_id)
    if post is None:
        return None
    return PostSnapshot(
        board=post.board, status=post.status,
        catalog_product_count=sum(1 for p in post.products if p.product_id and p.kind),
        content_hash=content_hash(post),
    )


def find_changed_posts(conn, since: datetime | None, *, limit: int = 500) -> list[tuple[str, datetime]]:
    """`since` 이후에 바뀐 글(게시·수정·삭제·숨김 포함)의 (id, 갱신 시각), 오래된 순. `since=None` 이면 전부.

    분석 대상이 될 수 있는 글만 고른다: 사용기 게시판이거나 이미 분석한 글일 수 있어서 게시판은 거르지 않고,
    임시 저장(draft)만 뺀다. 판단은 처리 규칙이 현재 상태로 다시 한다."""
    sql = ("SELECT id, updated_at FROM community.post WHERE status <> 'draft'"
           + (" AND updated_at > %s" if since is not None else "") + " ORDER BY updated_at, id LIMIT %s")
    params: tuple = (since, limit) if since is not None else (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(str(row[0]), row[1]) for row in cur.fetchall()]


__all__ = ["REVIEW_BOARD", "find_changed_posts", "load_post_input", "load_snapshot"]

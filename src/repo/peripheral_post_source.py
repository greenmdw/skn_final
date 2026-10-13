"""사용기 분석이 커뮤니티 글을 읽는 통로(요청서 B-3) — `community.*` 테이블을 **읽기 전용**으로 조회한다.

커뮤니티 담당의 테이블(0013·0014)과 API 는 건드리지 않는다. 여기서는 분석에 필요한 값만 SELECT 한다.
커뮤니티가 글 변경 알림 함수를 부르지 않는 동안에는 변경 신호(`change_signal`)를 비교해 바뀐 글을 찾는다(W-2 대안).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from src.agent.peripheral_post_agent import content_hash
from src.engine.peripheral_post_contract import LinkedProduct, PostInput
from src.engine.peripheral_post_text import plain_text
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
        post_id=str(post["id"]), author_id=str(post["author_user_id"]), board=post["board_type"], body=plain_text(post["body"]),
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


def change_signal(conn, post_ids: list[str] | None = None) -> dict[str, str]:
    """글마다 "내용이 바뀌었는가"를 가르는 신호 문자열 {post_id: 신호}. 임시 저장(draft)은 뺀다.

    `updated_at` 은 쓰지 않는다 — 글을 조회할 때마다 `view_count` 갱신과 갱신 시각 트리거 때문에 바뀐다.
    대신 `version`(본문·제목·상태 수정 때 오른다), 상태, 연결 제품(개수·가장 최근 연결 시각), 첨부 이미지 수를 묶는다."""
    sql = """
        SELECT p.id, p.version, p.status,
               (SELECT count(*) FROM community.post_product pp WHERE pp.post_id = p.id) AS n_products,
               (SELECT coalesce(max(pp.created_at)::text, '') FROM community.post_product pp WHERE pp.post_id = p.id) AS last_product,
               (SELECT count(*) FROM community.post_image pi WHERE pi.post_id = p.id) AS n_images
        FROM community.post p
        WHERE p.status <> 'draft'""" + (" AND p.id = ANY(%s::uuid[])" if post_ids is not None else "")
    with conn.cursor() as cur:
        cur.execute(sql, (post_ids,) if post_ids is not None else ())
        return {str(r[0]): f"{r[1]}:{r[2]}:{r[3]}:{r[4]}:{r[5]}" for r in cur.fetchall()}


def find_changed_posts(conn, known: dict[str, str] | None = None, *, limit: int = 500) -> list[tuple[str, str]]:
    """`known`({post_id: 이미 반영한 신호})와 다른 글의 [(id, 새 신호)]. `known=None` 이면 전부. 처음 보는 글도 포함한다.

    분석 대상 여부는 판단하지 않는다(게시판이나 제품 연결은 처리 규칙이 현재 상태로 다시 본다). 반환한 신호를 알림 기록에
    함께 저장해 두면 다음 호출에서 `known` 으로 넘길 수 있다."""
    signals = change_signal(conn)
    changed = [(pid, sig) for pid, sig in sorted(signals.items()) if (known or {}).get(pid) != sig]
    return changed[:limit]


__all__ = ["REVIEW_BOARD", "change_signal", "find_changed_posts", "load_post_input", "load_snapshot"]

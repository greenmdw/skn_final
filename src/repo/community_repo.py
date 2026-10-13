"""community.post* 저장소 — 일반 커뮤니티 게시글·연결 제품·댓글·추천·조회.

규칙 판단(권한, 게시 조건, 문구)은 서비스(src/services/community_service.py)가 하고, 여기는 쿼리만 한다.
목록·상세 응답에 쓰는 집계(추천 수·댓글 수·내가 추천했는지·최근 조회수)는 한 쿼리 안의 상관 서브쿼리로 낸다.
"""
from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from src.db.base import Repo

# 인기 점수 = (추천×3 + 댓글×2 + 최근 7일 조회×1) × 예시 글 가중치 ÷ (게시 후 경과 시간(h) + 2)^1.2
POPULARITY_LIKE_WEIGHT = 3.0
POPULARITY_COMMENT_WEIGHT = 2.0
POPULARITY_VIEW_WEIGHT = 1.0
POPULARITY_DECAY_EXPONENT = 1.2
EXAMPLE_POPULARITY_WEIGHT = 1.0           # 예시 글의 반응을 인기 점수에 얼마나 반영할지(정책 값 — 1.0 이면 일반 글과 같다)

_POST_COLUMNS = """
    p.id, p.author_user_id, p.board_type, p.title, p.body, p.tags, p.status, p.is_example, p.view_count, p.version,
    p.external_id, p.published_at, p.deleted_at, p.created_at, p.updated_at,
    u.display_name AS author_name,
    (SELECT count(*) FROM community.post_like l WHERE l.post_id = p.id) AS like_count,
    (SELECT count(*) FROM community.post_comment c WHERE c.post_id = p.id AND c.status = 'published') AS comment_count,
    EXISTS (SELECT 1 FROM community.post_like l WHERE l.post_id = p.id AND l.user_id = %(me)s) AS liked_by_me,
    (SELECT count(*) FROM community.post_view v WHERE v.post_id = p.id AND v.bucket > now() - interval '7 days') AS recent_views,
    (SELECT pp.product_kind FROM community.post_product pp WHERE pp.post_id = p.id ORDER BY pp.display_order LIMIT 1) AS first_product_kind,
    (SELECT count(*) FROM community.post_image i WHERE i.post_id = p.id) AS image_count,
    (SELECT i.id FROM community.post_image i WHERE i.post_id = p.id ORDER BY i.display_order, i.created_at LIMIT 1) AS cover_image_id
"""
_POST_FROM = "FROM community.post p JOIN identity.app_user u ON u.id = p.author_user_id"


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CommunityRepo(Repo):
    # ── 글 ──────────────────────────────────────────────────────────────────────────
    def create_post(self, *, author_id: UUID, board_type: str, title: str, body: str, tags: Sequence[str],
                    status: str = "draft", is_example: bool = False, external_id: str | None = None,
                    published_at: Any = None) -> UUID:
        row = self._one(
            """INSERT INTO community.post (author_user_id, board_type, title, body, tags, status, is_example, external_id, published_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, CASE WHEN %s = 'published' THEN now() END)) RETURNING id""",
            (author_id, board_type, title, body, list(tags), status, is_example, external_id, published_at, status))
        return row["id"]

    def get_post(self, post_id: UUID, *, me: UUID | None = None) -> dict | None:
        return self._one(f"SELECT {_POST_COLUMNS} {_POST_FROM} WHERE p.id = %(id)s", {"id": post_id, "me": me})

    def get_post_by_external_id(self, external_id: str) -> dict | None:
        return self._one("SELECT id, author_user_id, status FROM community.post WHERE external_id = %s", (external_id,))

    def update_post(self, post_id: UUID, *, expected_version: int | None, fields: dict) -> bool:
        """낙관적 잠금: expected_version 이 있으면 그 버전일 때만 고친다. 고치면 version 을 올린다."""
        allowed = {"board_type", "title", "body", "tags", "is_example"}
        sets = [f"{k} = %({k})s" for k in fields if k in allowed]
        params: dict = {k: v for k, v in fields.items() if k in allowed}
        if "tags" in params:
            params["tags"] = list(params["tags"])
        params.update(id=post_id, ver=expected_version)
        row = self._one(
            f"UPDATE community.post SET {', '.join(sets + ['version = version + 1'])} "
            "WHERE id = %(id)s AND status <> 'deleted' AND (%(ver)s::int IS NULL OR version = %(ver)s::int) RETURNING id", params)
        return row is not None

    def publish_post(self, post_id: UUID, *, expected_version: int | None) -> bool:
        row = self._one(
            "UPDATE community.post SET status = 'published', published_at = COALESCE(published_at, now()), version = version + 1 "
            "WHERE id = %(id)s AND status IN ('draft', 'hidden') AND (%(ver)s::int IS NULL OR version = %(ver)s::int) RETURNING id",
            {"id": post_id, "ver": expected_version})
        return row is not None

    def set_status(self, post_id: UUID, status: str) -> None:
        self._exec(
            "UPDATE community.post SET status = %s, deleted_at = CASE WHEN %s = 'deleted' THEN now() ELSE NULL END, "
            "version = version + 1 WHERE id = %s", (status, status, post_id))

    def list_posts(self, *, me: UUID | None, board_type: str | None, q: str | None, author_id: UUID | None,
                   product_kind: str | None, is_example: bool | None, statuses: Sequence[str], sort: str,
                   limit: int, offset: int) -> tuple[list[dict], int]:
        where = ["p.status = ANY(%(statuses)s)"]
        params: dict[str, Any] = {"me": me, "statuses": list(statuses), "limit": limit, "offset": offset,
                                  "like_w": POPULARITY_LIKE_WEIGHT, "comment_w": POPULARITY_COMMENT_WEIGHT,
                                  "view_w": POPULARITY_VIEW_WEIGHT, "decay": POPULARITY_DECAY_EXPONENT,
                                  "example_w": EXAMPLE_POPULARITY_WEIGHT}
        if board_type:
            where.append("p.board_type = %(board_type)s"); params["board_type"] = board_type
        if author_id:
            where.append("p.author_user_id = %(author_id)s"); params["author_id"] = author_id
        if is_example is not None:
            where.append("p.is_example = %(is_example)s"); params["is_example"] = is_example
        if product_kind:
            where.append("EXISTS (SELECT 1 FROM community.post_product pk WHERE pk.post_id = p.id AND pk.product_kind = %(product_kind)s)")
            params["product_kind"] = product_kind
        if q:
            params["pat"] = f"%{escape_like(q)}%"
            where.append("""(p.title ILIKE %(pat)s ESCAPE '\\' OR p.body ILIKE %(pat)s ESCAPE '\\'
                OR u.display_name ILIKE %(pat)s ESCAPE '\\' OR array_to_string(p.tags, ' ') ILIKE %(pat)s ESCAPE '\\'
                OR EXISTS (SELECT 1 FROM community.post_product pq LEFT JOIN catalog.product cp ON cp.id = pq.product_id
                           WHERE pq.post_id = p.id AND (pq.custom_product_name ILIKE %(pat)s ESCAPE '\\'
                                 OR cp.name ILIKE %(pat)s ESCAPE '\\' OR cp.model ILIKE %(pat)s ESCAPE '\\')))""")
        clause = " AND ".join(where)
        total = self._one(f"SELECT count(*) AS n {_POST_FROM} WHERE {clause}", params)["n"]
        order = {
            "latest": "t.published_at DESC NULLS LAST, t.id DESC",
            "views": "t.view_count DESC, t.published_at DESC NULLS LAST, t.id DESC",
            "recommend": "t.like_count DESC, t.published_at DESC NULLS LAST, t.id DESC",
            "popular": "t.score DESC, t.published_at DESC NULLS LAST, t.id DESC",
        }[sort]
        rows = self._all(
            f"""SELECT * FROM (
                    SELECT {_POST_COLUMNS},
                           ((%(like_w)s::float8 * (SELECT count(*) FROM community.post_like l2 WHERE l2.post_id = p.id)
                             + %(comment_w)s::float8 * (SELECT count(*) FROM community.post_comment c2 WHERE c2.post_id = p.id AND c2.status = 'published')
                             + %(view_w)s::float8 * (SELECT count(*) FROM community.post_view v2 WHERE v2.post_id = p.id AND v2.bucket > now() - interval '7 days'))
                            * CASE WHEN p.is_example THEN %(example_w)s::float8 ELSE 1 END
                            / power(extract(epoch FROM (now() - COALESCE(p.published_at, p.created_at)))::float8 / 3600.0 + 2, %(decay)s::float8)) AS score
                    {_POST_FROM} WHERE {clause}
                ) t ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s""", params)
        return rows, int(total)

    # ── 연결 제품 ───────────────────────────────────────────────────────────────────
    def products_for(self, post_ids: Sequence[UUID]) -> dict[UUID, list[dict]]:
        if not post_ids:
            return {}
        rows = self._all(
            """SELECT pp.id, pp.post_id, pp.product_id, pp.product_kind, pp.custom_product_name, pp.selected_option,
                      pp.match_status, pp.display_order, cp.name AS product_name, cp.brand AS product_brand, cp.model AS product_model, cp.image_url AS product_image_url
               FROM community.post_product pp LEFT JOIN catalog.product cp ON cp.id = pp.product_id
               WHERE pp.post_id = ANY(%s) ORDER BY pp.post_id, pp.display_order, pp.created_at""", (list(post_ids),))
        out: dict[UUID, list[dict]] = {}
        for r in rows:
            out.setdefault(r["post_id"], []).append(r)
        return out

    def product_count(self, post_id: UUID) -> int:
        return int(self._one("SELECT count(*) AS n FROM community.post_product WHERE post_id = %s", (post_id,))["n"])

    def add_product(self, post_id: UUID, *, product_id: UUID | None, product_kind: str, custom_product_name: str | None,
                    selected_option: str | None, match_status: str, display_order: int) -> UUID:
        return self._one(
            """INSERT INTO community.post_product (post_id, product_id, product_kind, custom_product_name, selected_option, match_status, display_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (post_id, product_id, product_kind, custom_product_name, selected_option, match_status, display_order))["id"]

    def delete_product_link(self, post_id: UUID, link_id: UUID) -> bool:
        return self._one("DELETE FROM community.post_product WHERE id = %s AND post_id = %s RETURNING id", (link_id, post_id)) is not None

    def delete_all_products(self, post_id: UUID) -> None:
        self._exec("DELETE FROM community.post_product WHERE post_id = %s", (post_id,))

    def find_catalog_product(self, product_id: UUID) -> dict | None:
        return self._one("SELECT id, name, brand, model, product_type FROM catalog.product WHERE id = %s", (product_id,))

    def similar_catalog_product(self, product_type: str, name: str) -> UUID | None:
        """직접 입력한 제품명이 같은 종류의 카탈로그 제품명과 거의 같은지(대소문자·공백 무시 포함 관계)."""
        row = self._one(
            "SELECT id FROM catalog.product WHERE product_type = %s AND (lower(name) = lower(%s) OR lower(model) = lower(%s) "
            "OR lower(name) LIKE '%%' || lower(%s) || '%%') ORDER BY length(name) LIMIT 1", (product_type, name, name, name))
        return row["id"] if row else None

    def search_catalog(self, *, product_type: str | None, q: str | None, limit: int) -> list[dict]:
        where, params = ["p.status = 'active'"], {"limit": limit}
        if product_type:
            where.append("p.product_type = %(ptype)s"); params["ptype"] = product_type
        if q:
            where.append("(p.name ILIKE %(pat)s ESCAPE '\\' OR p.model ILIKE %(pat)s ESCAPE '\\' OR p.brand ILIKE %(pat)s ESCAPE '\\')")
            params["pat"] = f"%{escape_like(q)}%"
        return self._all(
            f"""SELECT p.id, p.name, p.brand, p.model, p.product_type, p.image_url,
                       ks.switch_kind, ks.connectivity AS kb_connectivity, ks.weight_g AS kb_weight_g,
                       ms.weight_g AS mouse_weight_g, ms.connectivity AS mouse_connectivity, ms.sensor AS mouse_sensor,
                       mo.screen_size_inch, mo.resolution, mo.max_refresh_hz,
                       sp.channels AS speaker_channels, sp.connectivity AS speaker_connectivity
                FROM catalog.product p
                LEFT JOIN catalog.keyboard_spec ks ON ks.product_id = p.id
                LEFT JOIN catalog.mouse_spec ms ON ms.product_id = p.id
                LEFT JOIN catalog.monitor_spec mo ON mo.product_id = p.id
                LEFT JOIN catalog.speaker_spec sp ON sp.product_id = p.id
                WHERE {' AND '.join(where)} ORDER BY p.brand, p.name LIMIT %(limit)s""", params)

    # ── 댓글 ────────────────────────────────────────────────────────────────────────
    def comments_for(self, post_id: UUID) -> list[dict]:
        return self._all(
            """SELECT c.id, c.post_id, c.parent_comment_id, c.author_user_id, c.body, c.status, c.created_at, c.updated_at, c.deleted_at,
                      u.display_name AS author_name
               FROM community.post_comment c JOIN identity.app_user u ON u.id = c.author_user_id
               WHERE c.post_id = %s AND c.status <> 'hidden' ORDER BY c.created_at, c.id""", (post_id,))

    def get_comment(self, comment_id: UUID) -> dict | None:
        return self._one(
            """SELECT c.id, c.post_id, c.parent_comment_id, c.author_user_id, c.body, c.status, c.created_at, c.updated_at,
                      u.display_name AS author_name
               FROM community.post_comment c JOIN identity.app_user u ON u.id = c.author_user_id WHERE c.id = %s""", (comment_id,))

    def create_comment(self, *, post_id: UUID, author_id: UUID, body: str, parent_id: UUID | None) -> UUID:
        return self._one(
            "INSERT INTO community.post_comment (post_id, parent_comment_id, author_user_id, body) VALUES (%s, %s, %s, %s) RETURNING id",
            (post_id, parent_id, author_id, body))["id"]

    def update_comment(self, comment_id: UUID, body: str) -> None:
        self._exec("UPDATE community.post_comment SET body = %s WHERE id = %s AND status = 'published'", (body, comment_id))

    def soft_delete_comment(self, comment_id: UUID) -> None:
        self._exec("UPDATE community.post_comment SET status = 'deleted', deleted_at = now() WHERE id = %s AND status = 'published'", (comment_id,))

    def reply_count(self, comment_id: UUID) -> int:
        return int(self._one("SELECT count(*) AS n FROM community.post_comment WHERE parent_comment_id = %s AND status = 'published'",
                             (comment_id,))["n"])

    # ── 추천 ────────────────────────────────────────────────────────────────────────
    def add_like(self, post_id: UUID, user_id: UUID) -> None:
        self._exec("INSERT INTO community.post_like (post_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (post_id, user_id))

    def remove_like(self, post_id: UUID, user_id: UUID) -> None:
        self._exec("DELETE FROM community.post_like WHERE post_id = %s AND user_id = %s", (post_id, user_id))

    def like_count(self, post_id: UUID) -> int:
        return int(self._one("SELECT count(*) AS n FROM community.post_like WHERE post_id = %s", (post_id,))["n"])

    # ── 조회 ────────────────────────────────────────────────────────────────────────
    def record_view(self, post_id: UUID, viewer_key: str) -> bool:
        """(글, 조회자, 한 시간 구간)당 한 번만 센다. 새로 센 경우에만 view_count 를 올리고 True."""
        row = self._one(
            "INSERT INTO community.post_view (post_id, viewer_key, bucket) VALUES (%s, %s, date_trunc('hour', now())) "
            "ON CONFLICT DO NOTHING RETURNING post_id", (post_id, viewer_key))
        if row is None:
            return False
        self._exec("UPDATE community.post SET view_count = view_count + 1 WHERE id = %s", (post_id,))
        return True

    # ── 이미지 ──────────────────────────────────────────────────────────────────────
    def insert_image(self, *, owner_id: UUID, storage_key: str, content_type: str, width: int, height: int, byte_size: int) -> dict:
        return self._one(
            """INSERT INTO community.post_image (owner_user_id, storage_key, content_type, width, height, byte_size)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, owner_user_id, post_id, storage_key, content_type, width, height, byte_size, display_order, created_at""",
            (owner_id, storage_key, content_type, width, height, byte_size))

    def get_image(self, image_id: UUID) -> dict | None:
        return self._one(
            "SELECT id, owner_user_id, post_id, storage_key, content_type, width, height, byte_size, display_order, created_at "
            "FROM community.post_image WHERE id = %s", (image_id,))

    def images_for(self, post_ids: Sequence[UUID]) -> dict[UUID, list[dict]]:
        if not post_ids:
            return {}
        rows = self._all(
            "SELECT id, post_id, width, height, display_order FROM community.post_image WHERE post_id = ANY(%s) "
            "ORDER BY post_id, display_order, created_at", (list(post_ids),))
        out: dict[UUID, list[dict]] = {}
        for r in rows:
            out.setdefault(r["post_id"], []).append(r)
        return out

    def count_orphans(self, owner_id: UUID) -> int:
        return int(self._one("SELECT count(*) AS n FROM community.post_image WHERE owner_user_id = %s AND post_id IS NULL", (owner_id,))["n"])

    def attach_images(self, post_id: UUID, image_ids: Sequence[UUID]) -> list[str]:
        """image_ids 순서대로 글에 붙이고, 이 글에 붙어 있던 나머지는 지운다(지운 행의 storage_key 를 돌려준다)."""
        for order, image_id in enumerate(image_ids):
            self._exec("UPDATE community.post_image SET post_id = %s, display_order = %s WHERE id = %s", (post_id, order, image_id))
        rows = self._all("DELETE FROM community.post_image WHERE post_id = %s AND NOT (id = ANY(%s)) RETURNING storage_key",
                         (post_id, list(image_ids)))
        return [r["storage_key"] for r in rows]

    def delete_image(self, image_id: UUID) -> str | None:
        row = self._one("DELETE FROM community.post_image WHERE id = %s RETURNING storage_key", (image_id,))
        return row["storage_key"] if row else None

    def delete_post_images(self, post_id: UUID) -> list[str]:
        return [r["storage_key"] for r in self._all("DELETE FROM community.post_image WHERE post_id = %s RETURNING storage_key", (post_id,))]

    def delete_orphans(self, *, older_than_hours: int, limit: int) -> list[str]:
        rows = self._all(
            """DELETE FROM community.post_image WHERE id IN (
                   SELECT id FROM community.post_image WHERE post_id IS NULL
                   AND created_at < now() - make_interval(hours => %s) ORDER BY created_at LIMIT %s) RETURNING storage_key""",
            (older_than_hours, limit))
        return [r["storage_key"] for r in rows]

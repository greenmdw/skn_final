"""Two-table community retrieval storage, durable claims and current-source filtering."""
from __future__ import annotations

from uuid import UUID, uuid4

from psycopg.rows import dict_row

from src.repo.review_embedding_repo import _vector_literal
from src.services.community_review_chunking import chunk_id, normalized_body

# Use this identical DB expression for queueing, completing and searching. JSON
# boundaries distinguish title/body/profile; sha256 is built into PostgreSQL 16.
KEY_SQL = "encode(sha256(convert_to(jsonb_build_array(p.title, p.body, %(profile)s::text)::text, 'UTF8')), 'hex')"
ELIGIBLE_SQL = """p.status = 'published' AND p.board_type = 'review'
    AND EXISTS (SELECT 1 FROM community.post_product pp WHERE pp.post_id = p.id AND pp.product_id IS NOT NULL)"""
LINKS_SQL = """coalesce((SELECT jsonb_agg(jsonb_build_object(
    'product_id', cp.id, 'name', cp.name, 'selected_option', pp.selected_option)
    ORDER BY pp.display_order, pp.id)
    FROM community.post_product pp JOIN catalog.product cp ON cp.id = pp.product_id
    WHERE pp.post_id = p.id), '[]'::jsonb)"""


class CommunityReviewSearchRepo:
    def __init__(self, conn, profile: str):
        self.conn, self.profile = conn, profile

    def _rows(self, sql, **params):
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, {"profile": self.profile, **params})
            return cur.fetchall()

    def source(self, post_id, *, lock=False):
        rows = self._rows(f"""SELECT p.id, p.title, p.body, p.status, p.board_type, p.is_example,
            p.published_at, {KEY_SQL} AS current_key, ({ELIGIBLE_SQL}) AS eligible,
            {LINKS_SQL} AS linked_products FROM community.post p WHERE p.id = %(id)s"""
            + (" FOR UPDATE OF p" if lock else ""), id=post_id)
        return rows[0] if rows else None

    def enqueue(self, post_id, *, include_examples=False, force=False):
        """Keep same-input retries/claims intact; replace changed requests atomically."""
        with self.conn.transaction():
            post = self.source(post_id, lock=True)
            if not post or not post["eligible"] or not normalized_body(post["body"]).strip():
                self.conn.execute("DELETE FROM evidence.community_review_search_document WHERE post_id=%s", (post_id,))
                return False
            if post["is_example"] and not include_examples:
                return False
            rows = self._rows("""INSERT INTO evidence.community_review_search_document AS d (post_id, index_key)
                VALUES (%(id)s, %(key)s) ON CONFLICT (post_id) DO UPDATE SET
                index_key=EXCLUDED.index_key, status='pending', attempts=0, last_error=NULL,
                claim_token=NULL, updated_at=clock_timestamp()
                WHERE d.index_key <> EXCLUDED.index_key OR %(force)s
                RETURNING post_id""", id=post_id, key=post["current_key"], force=force)
            return bool(rows)

    def sync(self, *, include_examples=False, only=None, force=False):
        """Reconcile missing/changed originals, without using view-driven updated_at."""
        scope = " AND p.id = ANY(%(only)s::uuid[])" if only is not None else ""
        rows = self._rows(f"SELECT p.id FROM community.post p WHERE {ELIGIBLE_SQL}" + scope,
                          only=list(only or []))
        queued = sum(self.enqueue(r["id"], include_examples=include_examples, force=force) for r in rows)
        stale = self._rows(f"""SELECT d.post_id FROM evidence.community_review_search_document d
            WHERE NOT EXISTS (SELECT 1 FROM community.post p WHERE p.id=d.post_id AND {ELIGIBLE_SQL})"""
            + (" AND d.post_id=ANY(%(only)s::uuid[])" if only is not None else ""), only=list(only or []))
        for row in stale:
            self.enqueue(row["post_id"], include_examples=include_examples)
        return queued

    def inventory(self):
        return self._rows(f"""SELECT p.id, p.status, p.board_type, p.is_example, ({ELIGIBLE_SQL}) AS eligible,
            p.body, d.status AS index_status, (d.status='done' AND d.index_key={KEY_SQL}) AS current
            FROM community.post p LEFT JOIN evidence.community_review_search_document d ON d.post_id=p.id""")

    def claim(self, *, include_examples, max_attempts, lease_seconds, retry_seconds, exclude=(), only=None):
        params = dict(examples=include_examples, max_attempts=max_attempts, lease=lease_seconds,
                      retry=retry_seconds, exclude=list(exclude), only=list(only or []))
        scope = " AND d.post_id=ANY(%(only)s::uuid[])" if only is not None else ""
        with self.conn.transaction():
            self._rows("""UPDATE evidence.community_review_search_document d
                SET status='failed', claim_token=NULL, last_error='worker_expired', updated_at=clock_timestamp()
                WHERE status='processing' AND attempts >= %(max_attempts)s
                AND updated_at < clock_timestamp() - %(lease)s * interval '1 second'""" + scope
                + " RETURNING post_id", **params)
            rows = self._rows(f"""WITH next AS (
                SELECT d.post_id FROM evidence.community_review_search_document d
                JOIN community.post p ON p.id=d.post_id WHERE {ELIGIBLE_SQL}
                AND (NOT p.is_example OR %(examples)s) AND d.attempts < %(max_attempts)s
                AND NOT (d.post_id=ANY(%(exclude)s::uuid[])) {scope}
                AND ((d.status='pending' AND (d.attempts=0 OR d.updated_at <= clock_timestamp()
                    - %(retry)s * least(d.attempts, 10) * interval '1 second'))
                    OR (d.status='processing' AND d.updated_at < clock_timestamp() - %(lease)s * interval '1 second'))
                ORDER BY d.updated_at, d.post_id FOR UPDATE OF d SKIP LOCKED LIMIT 1)
                UPDATE evidence.community_review_search_document d SET status='processing',
                attempts=d.attempts+1, claim_token=%(token)s, updated_at=clock_timestamp()
                FROM next WHERE d.post_id=next.post_id RETURNING d.*""", token=uuid4(), **params)
            return rows[0] if rows else None

    def heartbeat(self, claim):
        return bool(self._rows("""UPDATE evidence.community_review_search_document SET updated_at=clock_timestamp()
            WHERE post_id=%(id)s AND claim_token=%(token)s AND status='processing' RETURNING post_id""",
            id=claim["post_id"], token=claim["claim_token"]))

    def fail(self, claim, error, *, max_attempts):
        return bool(self._rows("""UPDATE evidence.community_review_search_document
            SET status=CASE WHEN attempts >= %(maximum)s THEN 'failed' ELSE 'pending' END,
            last_error=%(error)s, claim_token=NULL, updated_at=clock_timestamp()
            WHERE post_id=%(id)s AND claim_token=%(token)s RETURNING post_id""",
            id=claim["post_id"], token=claim["claim_token"], maximum=max_attempts, error=error[:500]))

    def defer(self, claim):
        self._rows("""UPDATE evidence.community_review_search_document SET status='pending',
            attempts=greatest(attempts-1,0), claim_token=NULL, updated_at=clock_timestamp()
            WHERE post_id=%(id)s AND claim_token=%(token)s RETURNING post_id""",
            id=claim["post_id"], token=claim["claim_token"])

    def finish(self, claim, chunks, vectors, *, include_examples):
        """Fence old owners and atomically publish the complete current document."""
        with self.conn.transaction():
            post = self.source(claim["post_id"], lock=True)  # same lock order as community writes
            rows = self._rows("""SELECT * FROM evidence.community_review_search_document
                WHERE post_id=%(id)s FOR UPDATE""", id=claim["post_id"])
            if not rows or rows[0]["claim_token"] != claim["claim_token"]:
                return False
            if not post or not post["eligible"] or (post["is_example"] and not include_examples):
                self.conn.execute("DELETE FROM evidence.community_review_search_document WHERE post_id=%s", (claim["post_id"],))
                return False
            if post["current_key"] != claim["index_key"]:
                self.enqueue(post["id"], include_examples=include_examples)
                return False
            body = normalized_body(post["body"])
            if not chunks or len(chunks) != len(vectors) or any(body[c.start:c.end] != c.text for c in chunks):
                raise ValueError("incomplete or mismatched community chunks")
            self.conn.execute("DELETE FROM evidence.community_review_search_chunk WHERE post_id=%s", (post["id"],))
            with self.conn.cursor() as cur:
                cur.executemany("""INSERT INTO evidence.community_review_search_chunk(id,post_id,start_char,text,embedding)
                    VALUES (%s,%s,%s,%s,%s::vector)""", [
                    (chunk_id(post["id"], claim["index_key"], c.start), post["id"], c.start, c.text, _vector_literal(v))
                    for c, v in zip(chunks, vectors)])
            self.conn.execute("""UPDATE evidence.community_review_search_document SET status='done',
                claim_token=NULL, last_error=NULL, updated_at=clock_timestamp() WHERE post_id=%s""", (post["id"],))
            return True

    def coverage(self, product_ids, *, demo=False):
        rows = self._rows(f"""SELECT r.product_id, (cp.id IS NOT NULL) AS exists,
            count(DISTINCT p.id) AS documents, count(DISTINCT d.post_id) FILTER (WHERE c.id IS NOT NULL) AS indexed_documents,
            count(c.id) AS chunks FROM unnest(%(ids)s::uuid[]) r(product_id)
            LEFT JOIN catalog.product cp ON cp.id=r.product_id
            LEFT JOIN community.post p ON ({ELIGIBLE_SQL}) AND p.is_example=%(demo)s
                AND EXISTS (SELECT 1 FROM community.post_product pp WHERE pp.post_id=p.id AND pp.product_id=r.product_id)
            LEFT JOIN evidence.community_review_search_document d ON d.post_id=p.id AND d.status='done' AND d.index_key={KEY_SQL}
            LEFT JOIN evidence.community_review_search_chunk c ON c.post_id=d.post_id
            GROUP BY r.product_id, cp.id""", ids=list(product_ids), demo=demo)
        return {r["product_id"]: r for r in rows}

    def _candidates(self):
        return f"""FROM unnest(%(ids)s::uuid[]) r(product_id)
            JOIN community.post p ON ({ELIGIBLE_SQL}) AND p.is_example=%(demo)s
                AND EXISTS (SELECT 1 FROM community.post_product pp WHERE pp.post_id=p.id AND pp.product_id=r.product_id)
            JOIN evidence.community_review_search_document d ON d.post_id=p.id AND d.status='done' AND d.index_key={KEY_SQL}
            JOIN evidence.community_review_search_chunk c ON c.post_id=d.post_id"""

    def nearest(self, vector, product_ids, *, limit, demo=False):
        # Select each document's best chunk BEFORE the per-product limit.
        return self._rows(f"""WITH scored AS (SELECT r.product_id, p.id AS post_id, c.id, c.start_char, c.text,
            p.title, p.published_at, p.is_example, {LINKS_SQL} AS linked_products,
            c.embedding <=> %(q)s::vector AS distance,
            row_number() OVER (PARTITION BY r.product_id,p.id ORDER BY c.embedding <=> %(q)s::vector,c.start_char,c.id) AS in_post
            {self._candidates()}), ranked AS (SELECT *, row_number() OVER (
                PARTITION BY product_id ORDER BY distance,post_id,start_char,id) AS rank FROM scored WHERE in_post=1)
            SELECT *, 1-distance AS similarity FROM ranked WHERE rank <= %(limit)s ORDER BY product_id,rank""",
            q=_vector_literal(vector), ids=list(product_ids), limit=limit, demo=demo)

    def sample(self, product_ids, *, demo=False):
        return self._rows(f"""SELECT DISTINCT ON (r.product_id) c.id, p.title, c.text {self._candidates()}
            ORDER BY r.product_id, length(c.text),c.id""", ids=list(product_ids), demo=demo)

    def stored_similarity(self, rows):
        if not rows:
            return []
        return [r["similarity"] for r in self._rows("""SELECT 1-(c.embedding <=> q.vector::vector) AS similarity
            FROM unnest(%(ids)s::uuid[], %(vectors)s::text[]) q(id,vector)
            JOIN evidence.community_review_search_chunk c ON c.id=q.id""",
            ids=[r[0] for r in rows], vectors=[_vector_literal(r[1]) for r in rows])]

    def citation(self, chunk_id, *, demo=False):
        rows = self._rows(f"""SELECT c.id, p.id AS post_id, c.start_char, c.text, p.title,
            p.published_at, p.is_example, {LINKS_SQL} AS linked_products
            FROM evidence.community_review_search_chunk c
            JOIN evidence.community_review_search_document d ON d.post_id=c.post_id
            JOIN community.post p ON p.id=d.post_id WHERE c.id=%(id)s AND {ELIGIBLE_SQL}
            AND p.is_example=%(demo)s AND d.status='done' AND d.index_key={KEY_SQL}""", id=chunk_id, demo=demo)
        return rows[0] if rows else None

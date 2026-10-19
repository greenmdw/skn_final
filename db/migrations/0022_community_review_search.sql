-- Community full-text review retrieval; document rows also form the durable queue.
CREATE TABLE evidence.community_review_search_document (
    post_id uuid PRIMARY KEY REFERENCES community.post(id) ON DELETE CASCADE,
    index_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error text,
    claim_token uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    CHECK ((status = 'processing') = (claim_token IS NOT NULL))
);
CREATE INDEX community_review_search_work_idx
    ON evidence.community_review_search_document (status, updated_at, post_id);

CREATE TABLE evidence.community_review_search_chunk (
    id uuid PRIMARY KEY,
    post_id uuid NOT NULL REFERENCES evidence.community_review_search_document(post_id) ON DELETE CASCADE,
    start_char integer NOT NULL CHECK (start_char >= 0),
    text text NOT NULL CHECK (btrim(text) <> ''),
    embedding public.vector(1536) NOT NULL,
    UNIQUE (post_id, start_char)
);

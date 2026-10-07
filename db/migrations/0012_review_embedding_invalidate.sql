-- 0012_review_embedding_invalidate.sql: body가 바뀐 리뷰의 임베딩을 지운다.
-- 트랜잭션은 마이그레이션 러너가 관리한다(db/migrate.py).
--
-- 임베딩 백필(src/workers/review_embedding_batch.py)의 유일한 규칙은 "임베딩 행이 없는 리뷰는
-- 임베딩이 필요하다"이다. INSERT는 그 규칙만으로 이미 다뤄진다(새 리뷰는 처음부터 임베딩 행이
-- 없다) — 하지만 UPDATE로 body(본문)가 바뀌면, evidence.review_embedding에 남아 있는 기존 벡터는
-- 더 이상 그 리뷰를 대표하지 않는 "거짓 임베딩"이 된다. 쓰기 경로(견적 점검 초안 수정 등)가 매번
-- 임베딩을 다시 계산해 넣게 하는 대신, DB 트리거로 그 행만 지운다 — 그러면 다시 "임베딩 행이 없는
-- 리뷰"가 되어 다음 배치 실행에서 저절로 다시 채워진다. 이렇게 하면 쓰기 경로는 임베딩이라는 개념을
-- 전혀 몰라도 된다(결합도를 낮춘다) — 대신 재임베딩까지 약간의 지연이 생긴다(다음 배치 전까지는
-- 리뷰 검색에서 그 리뷰가 빠진다).
--
-- WHEN (OLD.body IS DISTINCT FROM NEW.body)로 한정한다 — posted_at 등 다른 컬럼만 바뀌는 흔한
-- 수정에서까지 임베딩을 지우면, 바뀐 적 없는 본문을 쓸데없이 다시 임베딩하게 된다(API 비용).
--

CREATE FUNCTION evidence.invalidate_review_embedding_on_body_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  DELETE FROM evidence.review_embedding WHERE review_id = NEW.id;
  RETURN NEW;
END;
$$;

CREATE TRIGGER invalidate_embedding_on_body_change
    AFTER UPDATE OF body ON evidence.review_document
    FOR EACH ROW
    WHEN (OLD.body IS DISTINCT FROM NEW.body)
    EXECUTE FUNCTION evidence.invalidate_review_embedding_on_body_change();

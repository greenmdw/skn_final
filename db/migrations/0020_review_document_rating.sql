--
-- 0020_review_document_rating.sql
--
-- 리뷰 원문에 수집처 별점을 둔다 (docs/리뷰평점_적재_표시_계획_20261019.md).
--  · evidence.review_document.rating — 다나와 등 수집처에서 구매자가 남긴 1~5점 별점 그대로의 값.
--    검수 전 값이며 정제·보정한 평점이 아니다. 별점이 없는 리뷰는 NULL(모름)이다.
--  · 합성(is_synthetic) 리뷰의 평점은 실제 평점이 아니므로 집계(평균·건수)에 넣지 않는다.
--  · 기본값은 두지 않는다. 0012 의 임베딩 무효화 트리거는 UPDATE OF body 에만 걸리므로 rating 갱신은 임베딩을 지우지 않는다.
--

ALTER TABLE evidence.review_document
    ADD COLUMN rating smallint,
    ADD CONSTRAINT review_document_rating_check CHECK (rating IS NULL OR rating BETWEEN 1 AND 5);

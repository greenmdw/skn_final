--
-- 0006_report_soft_delete.sql
--
-- 견적서(plan_revision) 하나만 삭제 (개발요청 10번). plan은 이미 status/deleted_at로
-- 대화 전체를 소프트 삭제하는데, plan_revision에는 그 짝이 없었다 — 견적서 하나만 지우려면
-- 같은 패턴(deleted_at)을 plan_revision에도 둔다. state는 그대로 'draft'/'confirmed'만
-- 쓰고(CHECK 제약 안 바꿈), "지워졌다"는 deleted_at으로만 구분한다.
--

ALTER TABLE planning.plan_revision ADD COLUMN deleted_at timestamp with time zone;

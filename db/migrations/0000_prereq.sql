-- 0000_prereq.sql — 스키마 · 공용 함수
-- RDS/Aurora PostgreSQL 16 호환. 슈퍼유저 전용 구문 없음.
--   · gen_random_uuid() 는 PG13+ 코어 (pgcrypto 불필요)
--   · DDL 이벤트 트리거·커스텀 tablespace·COPY FROM PROGRAM 미사용

-- 애플리케이션 스키마 9개 (테이블 생성 전에 모두 존재해야 함 — 교차 스키마 FK 때문)
CREATE SCHEMA IF NOT EXISTS config;
CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS planning;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS assets;
CREATE SCHEMA IF NOT EXISTS community;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS engine;
CREATE SCHEMA IF NOT EXISTS notification;

-- updated_at 자동 갱신 (모든 mutable 테이블에 트리거로 연결 → 0004_triggers.sql)
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

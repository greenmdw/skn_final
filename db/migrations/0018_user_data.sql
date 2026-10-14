--
-- 0018_user_data.sql
--
-- 마이페이지 서버 저장(개발요청 C-1, C-2) — 지금까지 브라우저(localStorage)에만 있던 값을 계정에 둔다.
--  · identity.user_pc      — "내 현재 PC". 칸 이름(cpu·gpu·ram·storage·board·psu·cooler·case)은 서비스가 고정하고 값은 사용자가 쓴 자유 문장.
--  · identity.user_data    — 사용자별 이름 붙은 JSON 문서(작성 중 상태·점검 세션 기록·초안 등 화면 전용 값). 키·크기·개수는 서비스가 제한한다.
--  · planning.plan_extras  — 견적서(목록)마다 붙는 JSON 문서(조건 문장·책상 치수·점검 스냅샷 등 서버 필드가 없던 값 전부).
--

CREATE TABLE identity.user_pc (
    user_id uuid PRIMARY KEY REFERENCES identity.app_user(id) ON DELETE CASCADE,
    parts jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL DEFAULT '',
    title text NOT NULL DEFAULT '',
    saved_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT user_pc_parts_check CHECK (jsonb_typeof(parts) = 'object')
);
CREATE TRIGGER set_updated_at BEFORE UPDATE ON identity.user_pc FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE identity.user_data (
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key),
    CONSTRAINT user_data_key_check CHECK (key ~ '^[a-z0-9][a-z0-9._:-]{0,63}$')
);
CREATE TRIGGER set_updated_at BEFORE UPDATE ON identity.user_data FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE planning.plan_extras (
    plan_id uuid PRIMARY KEY REFERENCES planning.plan(id) ON DELETE CASCADE,
    extras jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT plan_extras_object_check CHECK (jsonb_typeof(extras) = 'object')
);
CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.plan_extras FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

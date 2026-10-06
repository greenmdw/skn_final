--
-- 0011_message_metadata.sql
--
-- 받은 견적 점검의 질문·답변 메타데이터 (개발요청서 BE-10·12). 저장 견적 비교에 대한 질문마다 어느 비교(comparison_id)의
-- 답인지, 정규화한 질문, 같은 질문이면 어느 답을 재사용했는지(duplicate_of), 답에 곁들인 시각 자료·가이드·근거를 남긴다 —
-- 새로고침 뒤에도 질문별 해설과 자료를 그대로 복원하고, 같은 질문에 LLM을 다시 부르지 않기 위해서다.
-- 메시지 본문(content)은 그대로 두고, 구조화된 부가 정보만 이 컬럼에 둔다. 기존 행은 빈 객체다.
--

ALTER TABLE identity.message ADD COLUMN metadata jsonb DEFAULT '{}'::jsonb NOT NULL;

-- 같은 대화 안에서 "이 비교의 이 질문"을 찾는 조회(BE-12)용 — 비교가 없는 메시지는 색인에 넣지 않는다.
CREATE INDEX message_comparison_question_idx
    ON identity.message USING btree (conversation_id, ((metadata ->> 'comparison_id')), ((metadata ->> 'normalized_question')))
    WHERE (metadata ? 'comparison_id');

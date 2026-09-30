# 리뷰 검색용 pgvector 스키마 설계 (제안)

- 상태: **설계 문서만. 마이그레이션 미적용, 코드 미연결.** 실제 서비스 경로(`CHAT-04`, `ENG-06`)에 붙이는 건 아래 "지금 하지 않는 것" 조건이 풀린 뒤로 미룬다.
- 근거: [`라벨데이터_labels_csv_안내.md`](라벨데이터_labels_csv_안내.md) 논의에서 이어짐. 벡터DB 자체는 맞는 선택이지만, 검색 대상이 될 리뷰 데이터가 아직 운영 승인을 못 받아서 지금 붙이면 승인 게이트를 우회하게 된다는 점을 먼저 확인했다.

## 1. 왜 지금은 "설계만" 하는가

`config/review_source_use_policy.json` 기준으로 지금 수집된 리뷰(danawa)는 `status: "unreviewed"`, `permitted_use: "metadata_pilot_only"`다. 그리고 실제로 다운스트림이 읽는 `evidence.review_aggregate`(승인 게이트를 통과한 테이블, `src/repo/review_repo.py::get_summary()`가 `status='ready'`만 읽음)는 **지금 0건**이다. `evidence.review_summary`(69건)는 어디까지나 `cleaning_status='pending'`인 스테이징 테이블이라, 여기서 바로 임베딩해 검색 가능하게 만들면 승인 안 된 데이터를 사용자에게 노출하는 셈이 된다.

→ 그래서 이 문서는 **스키마·파이프라인 설계만** 해두고, 실제 운영 연결은 리뷰 데이터 승인 결정 이후로 미룬다.

## 2. 승인 게이트를 그대로 물려받는 원칙

기존 코드의 안전판을 그대로 재사용한다 — 새 규칙을 만들지 않는다.

```
evidence.review_summary  (원문 요약, 스테이징, cleaning_status='pending'/'retained'/'excluded')
        │  evidence.review_aggregate_member (disposition='retained' 인 것만)
        ▼
evidence.review_aggregate  (status='building'/'ready'/'stale'/'revoked')
        │  ← 검색 가능 여부의 유일한 기준: status='ready'
        ▼
(신규) evidence.review_embedding  ← ready 상태를 통과한 summary만 임베딩
```

**임베딩 대상은 `review_summary` 전체가 아니라, `review_aggregate_member`를 통해 `status='ready'`인 `review_aggregate`에 `disposition='retained'`로 연결된 `review_summary` 행만이다.** `top_summaries()`가 지금 `review_aggregate.ratings.summary_texts`만 보여주는 것과 같은 경계를 벡터 검색에도 그대로 적용한다.

## 3. 스키마 (초안)

pgvector 확장은 이미 이 서버에 설치 가능한 상태로 확인됨(`0.8.6`, 미설치 상태) — 별도 서버 설정 없이 `CREATE EXTENSION`만 하면 된다.

```sql
-- db/migrations/0005_review_embedding.sql (초안 — 팀 승인 전 적용 금지)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE evidence.review_embedding (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id      uuid NOT NULL REFERENCES evidence.review_summary(id) ON DELETE CASCADE,
    aggregate_id    uuid NOT NULL REFERENCES evidence.review_aggregate(id) ON DELETE CASCADE,
    -- 어떤 승인된 aggregate를 통해 들어왔는지 남긴다 — aggregate가 나중에 stale/revoked로
    -- 바뀌면 이 컬럼으로 무엇을 내려야 하는지 바로 찾는다(4절 참고).
    embedding       vector(1536) NOT NULL,
    embedding_model text NOT NULL,
    -- care_guides.py 의 CARE_GUIDE_EMBEDDING_MODEL(text-embedding-3-small, 1536차원)과
    -- 같은 프로바이더·같은 인터페이스를 재사용한다 — 별도 임베딩 경로를 새로 안 만든다.
    content_hash    text NOT NULL,
    -- summary 텍스트의 sha256. 같은 텍스트 재임베딩 방지(요약문은 안 바뀌는 게 보통이라
    -- content_hash 로 "이미 임베딩했는지"만 확인하면 충분하다).
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (summary_id, embedding_model)
);

CREATE INDEX review_embedding_vector_idx
    ON evidence.review_embedding
    USING hnsw (embedding vector_cosine_ops);
-- ivfflat 대신 hnsw: 데이터가 계속 추가되는데 재구축(REINDEX) 없이도 삽입 성능이 안정적이다.
-- 리뷰 임베딩은 수만 건 규모까지 갈 수 있어(12만 줄 원문 수집분 기준) ivfflat의
-- "lists 개수를 데이터 규모에 맞춰 미리 정해야 하는" 제약을 피하는 쪽이 유지보수에 낫다.

CREATE INDEX review_embedding_summary_idx ON evidence.review_embedding(summary_id);
CREATE INDEX review_embedding_aggregate_idx ON evidence.review_embedding(aggregate_id);
```

**게이트를 "삽입 시점"이 아니라 "조회 시점"에도 다시 거는 뷰**를 둔다 — aggregate가 나중에 `stale`/`revoked`로 바뀌었는데 배치가 아직 안 돌았을 때를 대비한 이중 안전장치다.

```sql
CREATE VIEW evidence.review_embedding_searchable AS
SELECT e.*
FROM evidence.review_embedding e
JOIN evidence.review_aggregate a ON a.id = e.aggregate_id
WHERE a.status = 'ready';
-- 실제 서비스 코드는 evidence.review_embedding 를 직접 안 읽고 반드시 이 뷰만 읽는다.
```

## 4. 적재·정리 파이프라인 (설계만, 미구현)

- **적재 트리거**: `review_aggregate.status`가 `'ready'`로 바뀌는 시점(리뷰 승인 배치가 끝나는 지점)에, 그 aggregate의 `retained` 멤버 summary들을 임베딩해 `evidence.review_embedding`에 upsert. `content_hash`로 이미 임베딩된 건 건너뛴다.
- **철회 처리**: `status`가 `'stale'`/`'revoked'`로 바뀌면 3절의 뷰가 즉시 걸러주므로 서비스 응답은 바로 안전해진다. 실제 행 삭제는 별도 정리 배치(주기적)로 미뤄도 된다 — 급하지 않다.
- 이 트리거·배치는 **리뷰 데이터 운영 승인이 나온 뒤**에 구현한다. 지금은 코드로 만들지 않는다.

## 5. 조회 경로 설계 (연결은 승인 후)

```
사용자 질문("이 파워로 충분해?")
  → 질문 임베딩 (같은 embedding_model)
  → evidence.review_embedding_searchable 에서 cosine 유사도 top-k
  → 근거로 LLM 프롬프트에 삽입 (summary 텍스트 + 출처 aggregate 표시)
  → 답변에 "리뷰 관측 기반, 개별 리뷰 진위 판정 아님" 문구 고정 부착
```

- 연결 후보 지점: `src/services/quote_chat_service.py`(CHAT-04 되묻기), `src/engine/stage3c_verify.py`의 실경로(`verify_build`, 지금 RAG 미연결 상태)
- **결정 0001 재확인**: 이 경로는 "리뷰 텍스트에서 관련 문장을 찾아 인용"하는 순수 검색이지, "이 리뷰가 진짜인지" 판정하지 않는다. LLM 프롬프트에 진위 판정을 요구하는 문구를 넣지 않는다.

## 6. 지금 할 수 있는 것 vs 승인 후 할 것

| 항목 | 지금 | 리뷰 데이터 승인 후 |
|---|---|---|
| `CREATE EXTENSION vector` | 가능 (설치 확인됨) | — |
| `evidence.review_embedding` 테이블·인덱스 생성 | 설계 완료, 적용은 팀 승인 후 | — |
| 임베딩 적재 배치 구현 | 하지 않음 | 구현 |
| CHAT-04 / ENG-06 실제 연결 | 하지 않음 | 연결 |
| 케어가이드(18건) 벡터DB 전환 | **하지 않음** — 이미 코드 주석에 "이 규모면 인메모리로 충분하다"고 명시돼 있어 과잉설계 | 해당 없음 |

## 7. 미결정 사항

- 임베딩 모델 확정(현재 `text-embedding-3-small` 가정, 1536차원) — LLM 연동 담당자와 확인 필요
- `evidence.review_embedding`을 별도 스키마(`rag.*`)로 뺄지, `evidence.*`에 둘지 — 지금은 승인 게이트 테이블들과 같은 스키마에 두는 쪽이 FK·권한 관리가 단순해서 `evidence.*`로 잡음
- 재임베딩 비용(모델 교체 시 전체 재계산 필요) — 운영 반영 전 팀 논의 필요

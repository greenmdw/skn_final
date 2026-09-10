# Truefit — 목적성 쇼핑 파이프라인 (백엔드 스켈레톤)

목적을 말하면 검증된 근거와 함께 장바구니 전체를 완성하는 목적성 쇼핑 플래너.
현재는 **스켈레톤** — 대부분의 함수 본문이 `raise NotImplementedError` + `# TODO`.
목적: 전체 코드 뼈대를 팀이 나눠 채우기.

데모 도메인: **컴퓨터(PC 본체 조립)** — 유아용품은 데이터 확보 후 (`config/categories/baby.yaml` = stub).

## 지금 돌아가는 것

```bash
python main.py computer_pass       # 엔진 [1]~[5] 콘솔 end-to-end (목)
python main.py computer_research   # [3-C] 신뢰도 72 → 재탐색 → 86 통과
python -m pytest -q tests/         # 스모크 2건
uvicorn src.api:app --reload      # http://127.0.0.1:8000/docs  (엔드포인트 22개, 대부분 501)
```

## 디렉토리 (61개 .py)

```
src/
  config.py                전역 설정 (env·벤더 중립: LLM/임베딩/DB/JWT)
  errors.py                공통 에러 봉투 {error:{code,message,field}}
  dto.py                   엔진 내부 DTO (pydantic)
  schemas.py               API 요청/응답 모델 (pydantic) — 프론트와 계약 확정 대상
  categories.py            config/categories/*.yaml 로더
  pipeline.py              8단계 오케스트레이터 + 카테고리 분기 + 재탐색 루프

  engine/                  ── 엔진 8단계 (흐름도 세로축) ──
    stage1_intent.py         [1] 의도분해·슬롯필링 (동적 기본값)      ✅ 목
    stage2_requirement.py    [2] 요구사양 빌드                        ⚠️ 규칙 일부
    stage3_0_candidates.py   [3-0] 후보 수집                          ✅ CSV
    stage3a_hardfilter.py    [3-A] 하드 필터 Pass/Fail/Pending        ⚠️ perf_tier만
    stage3b_rank.py          [3-B] 적합도·병목 순위                   ⚠️ 리뷰축 stub
    stage4_optimize.py       [4] 세트 최적화 / 예산 배분              ⚠️ 근사
    stage3c_verify.py        [3-C] 적대적 검증 (시나리오 정답값 주입) ✅ 데모용
    stage5_explain.py        [5] 설명 생성                            ⚠️ 고정 기여도
    stage6_feedback.py       [6] 사후 학습 (배치가 호출)              ✗ stub

  rag/
    evidence_search.py       evidence_search(domain,query,filters) @tool  ✅ 미니 코퍼스 목
    embedding.py             텍스트 → 벡터                               ✗ stub
    ingestion.py             파일 → 청크                                 ✗ stub

  db/
    __init__.py              psycopg 커넥션 풀 · get_conn()               ✗ stub
    base.py                  repo 베이스 (_one/_all/_exec)

  repo/                     ── 스키마별 저장소 (58테이블 → 11 repo) ──
    user_repo.py             identity.*        conversation_repo 포함
    plan_repo.py             planning.*        C01/C02 복합FK, C14/C15/C16 트랜잭션
    product_repo.py          catalog.*         product_fact = 검증 기준
    material_repo.py         assets.* + evidence.source/evidence
    rag_repo.py              rag.*             hybrid_search
    review_repo.py           community.review* + evidence.review_*   get_review_authenticity
    engine_repo.py           engine.*          run/candidate/validation/feedback_event
    notification_repo.py     notification.*
    dataset_repo.py          dataset.*         리뷰 근거 판정 데이터셋 (팀원)
    catalog_repo.py          데모 합성 카탈로그 (parts_list.csv)     ✅ 동작
    recall_repo.py           리콜 큐레이션 룩업 (유아, stub)

  auth/
    codes.py                 이메일 6자리 코드 발급·검증  ✗ (auth_code 저장소 결정 필요)
    jwt.py                   JWT 발급·검증
    deps.py                  FastAPI 의존성 (current_user / optional_principal)

  services/                 ── API ↔ repo/engine 오케스트레이션 ──
    auth_service.py          코드 요청·검증·JWT·browser_token 병합
    session_service.py       S1~S3 대화·조건 수집
    recommendation_service.py [추천 실행] → pipeline → 저장     run_from_scenario ✅
    list_service.py          S5-a 확정 · S5-b 리포트
    review_service.py        A7 리뷰 작성·게시
    notification_service.py  목표가 추적

  routers/                  ── FastAPI 라우터 ──
    auth.py     /auth/*      lists.py    /lists/*      dev.py  /dev/*  (동작)
    session.py  /session/*   reviews.py  /reviews/*

  workers/                  ── 배치·비동기 (데모 미가동) ──
    ingestion_worker.py      RAG 자료 추출·임베딩
    review_cleanse_worker.py 오프라인 리뷰 클렌징 (리뷰 팀원)
    price_poll_worker.py     가격 폴링 → 관측 적재 → 목표가 판정
    notification_worker.py   이메일 발송
    feedback_batch.py        [6] 사후 학습

  clients/llm_client.py      관리형 LLM API 래퍼 (벤더 중립, MOCK)

db/                        스키마 마이그레이션 (58테이블, RDS/Aurora PG16) — db/README.md
config/categories/*.yaml   카테고리 정의 (computer 실제 / baby stub)
data/scenarios/*.json      시나리오별 입력 + [3-C] 정답값 + 미니 코퍼스
tests/                     스모크
```

✅ 동작 · ⚠️ 부분(목/근사) · ✗ stub(NotImplementedError)

## API 엔드포인트 (22개, 대부분 501)

| 그룹 | 경로 | 인증 |
|---|---|---|
| auth | `POST /auth/request-code` `POST /auth/verify` `POST /auth/logout` `GET /auth/me` | — |
| session (S1~S3) | `POST /session` `POST /session/{id}/category` `POST /session/{id}/message` `POST /session/{id}/answer` `PATCH /session/{id}/slot` `POST /session/{id}/recommend` `GET /session/{id}/result` | browser_token or JWT |
| lists (S5) | `POST /lists/{id}/confirm` `GET /lists/{id}/report` `POST /lists/{id}/alert` `GET /lists` | JWT 필수 |
| reviews (A7) | `GET /reviews/pending` `POST /reviews/part` `POST /reviews/build` `POST /reviews/{id}/publish` `GET /reviews/summary/{product_key}` | JWT 필수 |
| dev | `GET /dev/scenarios` `POST /dev/run` | — |

## 다음 (파일 단위로 나눠 채우기)

1. `db/__init__.py` + `db/base.py` — 실제 psycopg 풀 → repo 들 구현 시작
2. `services/*` — 트랜잭션 경계·권한·교차 무결성(C03/C07/C09/C11/C13~C24)
3. `routers/*` — 501 → 실제 응답
4. `auth/*` — auth_code 저장소 결정 (마이그레이션 추가 vs Redis)
5. `engine/*` 의 `# TODO` 실제 로직 (하드필터 비교 · 완전탐색 · 리뷰축)
6. 설명서 RAG의 실제 Bedrock 품질 평가·PDF/OCR 확장 — [구현·실행·검증 문서](docs/rag_implementation.md)
7. `db/migrations/0007_*` 이후 — 업무규칙 가드 트리거 (C14 불변성, C15 잠금); `0006`은 RAG 활성 프로필 제약
8. `data/parts_catalog.csv` + `scripts/gen_parts_offers.py`
9. 유아 도메인 (`baby.yaml` + per_item 분기)

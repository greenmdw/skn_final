# db/ — 스키마 마이그레이션과 시드 (TrueFit)

PostgreSQL 16 + **pgvector** 확장을 쓴다. 마이그레이션 21개가 8개 스키마(`assets`·`catalog`·`community`·`config`·`engine`·`evidence`·`identity`·`planning`)에 테이블 77개를 만든다. 로컬은 Docker, 배포는 AWS RDS PostgreSQL에서 같은 파일·같은 러너로 적용한다.

## 1. 준비

로컬 DB는 Docker로 띄운다. 저장소의 `docker-compose.yml`이 pgvector가 들어 있는 이미지(`pgvector/pgvector:pg16`)를 쓴다.

```bash
docker compose up -d db          # 사용자·비밀번호·DB 이름 모두 truefit, 포트 5432
```

- Docker 없이 로컬 PostgreSQL 16을 쓰려면 pgvector 확장을 따로 설치해야 한다. `0008_review_aspect.sql`이 `CREATE EXTENSION IF NOT EXISTS vector`를 실행한다.
- 5432 포트가 이미 쓰이고 있으면 `docker-compose.yml`의 호스트 포트를 바꾸고 `DATABASE_URL`도 같은 포트로 맞춘다.
- 공용 개발 DB는 두지 않는다. 각자 로컬 DB에 같은 마이그레이션과 멱등 시드를 적용해 같은 데이터를 재현한다.

### 시드 입력 파일

| 파일 | Git | 쓰는 스크립트 |
|---|:---:|---|
| `data/parts_list_modify.xlsx` | 포함 | `seed_pc_parts_specs.py` |
| `config/danawa_product_pcode.json` | 포함 | `seed_pc_parts_specs.py` (다나와 상품 코드 매핑) |
| `config/categories/*.yaml` | 포함 | `seed.py` |
| `data/peripherals/{mouse,monitor,speaker,keyboard}_processed.csv` | 미포함 | `seed_peripherals.py` |
| `data/review_seed/` (`bundle_manifest.json`, `documents.json`, `rules.json`, `canonical_results.json`, `consolidated_observation_drafts.json`) | 미포함 | `seed_review_corpus.py`, `import_review_corpus_all_observations.py` |

Git에 없는 파일은 저장소 README의 "10. 설치 및 실행 → 처음 실행할 때 → 1. 시드 데이터 받기"에서 받는다. 하나라도 없으면 `setup_all.py`가 그 단계에서 멈춘다.

## 2. 실행

**한 번에 (권장)** — 아래 7단계를 순서대로 실행하고, 실패하면 그 단계에서 멈춘다. 모든 단계가 멱등이라 다시 실행해도 된다.

```bash
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/setup_all.py
```

| 순서 | 단계 | 명령 |
|---|---|---|
| 1 | 스키마 마이그레이션 | `python db/migrate.py up` |
| 2 | 기준 데이터(카테고리 정의 → `config.domain`·`domain_version`) | `python db/seed.py` |
| 3 | PC 부품 8종 카탈로그 | `python db/seed_pc_parts_specs.py` |
| 4 | 주변기기 4종 카탈로그 | `python db/seed_peripherals.py` |
| 5 | 리뷰 원문·관점 규칙 | `python db/seed_review_corpus.py --load-bundle --apply` |
| 6 | 리뷰 관점 관측 | `python db/import_review_corpus_all_observations.py --apply` |
| 7 | 리뷰 관점 집계 | `python db/rebuild_review_aspect_aggregates.py --analysis-version review-aspect-v6-prod-20261002 --apply` |

단계별로 직접 돌릴 때도 각 명령 앞에 같은 `DATABASE_URL`을 붙인다.

**마이그레이션 러너** (`migrate.py`) — `db/migrations/*.sql`을 파일명 순서로 적용하고 `_migrations.schema_migrations`에 버전과 체크섬을 기록한다. 앞으로만 적용한다(forward-only).

```bash
python db/migrate.py up        # 아직 적용하지 않은 파일 전부 적용 (기본)
python db/migrate.py status    # 적용 현황
python db/migrate.py dry-run   # 적용할 파일만 출력
```

코드를 새로 받은 뒤에는 `python db/migrate.py up`으로 새 파일만 적용한다. RDS에 적용할 때는 `DATABASE_URL`만 RDS 주소로 바꾼다.

## 3. 마이그레이션 파일

| 파일 | 내용 |
|---|---|
| `0000_schema.sql` | 기본 스키마 8개, 공용 함수, 기본 테이블 50개와 컬럼·CHECK |
| `0001_constraints.sql` | PK · UNIQUE · FK |
| `0002_indexes.sql` | 부분 UNIQUE와 성능 인덱스 |
| `0003_triggers.sql` | `updated_at` 자동 갱신 트리거 |
| `0005_preference_signal.sql` | `identity.preference_signal` — 사용자 브랜드 선호·비선호 신호 |
| `0006_report_soft_delete.sql` | `planning.plan_revision.deleted_at` — 확정 리포트 하나만 삭제 표시 |
| `0007_peripheral_line.sql` | `planning.peripheral_line` — 확정 리포트에 함께 얼리는 주변기기 줄 |
| `0008_review_aspect.sql` | `vector` 확장, `evidence.review_document`·`review_embedding`(1536차원)·`review_aspect_rule`·`review_aspect_observation`·`review_aspect_aggregate(_member)`, `engine.review_requirement_profile` |
| `0009_live_spec_lookup_cache.sql` | `catalog.live_spec_lookup_cache` — DB에 없는 부품의 실시간 스펙 검색 결과 |
| `0010_live_spec_lookup_store.sql` | 위 테이블을 임시 부품 저장소로 전환 — 정규화 키 `lookup_key`, 검토 상태 `status`, 참고 가격 컬럼 |
| `0011_message_metadata.sql` | `identity.message.metadata` — 대화 메시지별 부가 정보(견적 점검 비교 id, 근거 등) |
| `0012_review_embedding_invalidate.sql` | 리뷰 본문이 바뀌면 그 리뷰의 임베딩을 지우는 트리거 |
| `0013_community_post.sql` | `community.post`·`post_product`·`post_comment`·`post_like`·`post_view` — 커뮤니티 게시판 |
| `0014_community_post_image.sql` | `community.post_image` — 게시글 첨부 이미지 메타데이터(파일은 `COMMUNITY_UPLOAD_DIR`) |
| `0015_peripheral_post_evidence.sql` | `engine.peripheral_post_intake`·`peripheral_post_analysis_log`·`peripheral_post_evidence`·`peripheral_post_evidence_embedding` — 사용기 분석 대기열·로그·체감 근거·임베딩 |
| `0016_peripheral_spec_columns.sql` | `catalog.gpu_spec`의 HDMI·DP 버전·USB-C 영상 출력, `catalog.keyboard_spec`의 키압 최소·최대 |
| `0017_community_activity.sql` | `community.post_save`(저장), `community.notification`(댓글·답글 알림) |
| `0018_user_data.sql` | `identity.user_pc`(내 PC), `identity.user_data`(사용자별 JSON 문서), `planning.plan_extras`(견적별 JSON) |
| `0019_session_revocation.sql` | `identity.revoked_session`(로그아웃한 토큰), `identity.app_user.sessions_revoked_at`(모든 기기 로그아웃) |
| `0020_kept_part_line.sql` | `planning.kept_part_line` — 받은 견적을 일부 교체해 확정할 때 그대로 둔 부품 |
| `0021_review_document_rating.sql` | `evidence.review_document.rating` — 수집처 구매자 별점(1~5) |

`0004`는 비어 있는 번호다. 스키마 사이에 순환 참조가 있어 "테이블 전부 → 제약 전부 → 인덱스 전부" 순서로 나눴다.

## 4. db/ 스크립트

| 스크립트 | 하는 일 |
|---|---|
| `setup_all.py` | 2장의 7단계를 순서대로 실행 |
| `migrate.py` | 마이그레이션 러너 |
| `seed.py` | `config/categories/*.yaml`을 `config.domain_version`에 적재(컴퓨터 카테고리는 게시 상태) |
| `seed_pc_parts_specs.py` | `parts_list_modify.xlsx` 8개 시트 → `catalog.product`·카테고리별 스펙 테이블·`offer`·`offer_observation`. 중복 행 3개는 제외 |
| `seed_peripherals.py` | 주변기기 CSV 4종 → `catalog.product`·종류별 스펙 테이블·`peripheral_price_snapshot`(판매처·관측일 없는 참고가). `--dry-run`으로 검증만 |
| `seed_review_corpus.py --load-bundle --apply` | 리뷰 시드 번들의 해시를 확인하고 리뷰 원문·관점 규칙 적재 |
| `import_review_corpus_all_observations.py --apply` | 번들의 관점 관측 적재 |
| `rebuild_review_aspect_aggregates.py` | 한 분석 버전의 관점 집계 미리보기(기본) 또는 재생성(`--apply`) |
| `seed_community_examples.py` | 예시 사용기 글(`data/community_examples/`)을 `community.post`에 적재(기본은 점검만, `--apply`로 적재) |
| `community_examples_snapshot.py` | 예시 글·이미지·분석 결과·벡터를 스냅샷으로 내보내기(`export`)·복원(`restore`) |
| `community_examples_from_json.py` | 담당자가 JSON으로 낸 예시 글을 마크다운 파일로 변환 |
| `review_live_lookup.py` | 임시 부품 저장소의 검색 결과를 사람이 검토(`list`·`confirm`·`reject`·`reset`) |
| `seed_catalog.py` | 옛 데모용 카탈로그 적재(`data/parts_list.csv`). `setup_all.py`에서는 쓰지 않음 |
| 그 밖의 `*review_corpus*`·`*review_observations*`·`validate_review_batch.py` 등 | 리뷰 시드 번들을 만들 때 쓴 준비·검증 도구. 번들을 받아 적재만 할 때는 쓰지 않음 |

## 5. 리뷰 관점 집계 다시 만들기

`review_aspect_aggregate`는 한 분석 버전에 등록된 관점 규칙(규칙마다 k값)과 유효한 관측으로 계산한다. 기본 실행은 읽기 전용 미리보기이고, 쓰려면 `--apply`를 붙인다.

```bash
# 미리보기 (쓰기 없음)
PYTHONPATH=. uv run python db/rebuild_review_aspect_aggregates.py --analysis-version review-aspect-v6-prod-20261002

# 재생성
PYTHONPATH=. uv run python db/rebuild_review_aspect_aggregates.py --analysis-version review-aspect-v6-prod-20261002 --apply
```

- `--apply`는 한 트랜잭션에서 그 분석 버전의 집계와 member만 바꾸고, 다른 분석 버전은 건드리지 않는다. 리뷰 원문·관측을 쓰는 작업과 동시에 돌리지 않는다.
- 추천은 요청 후보의 규칙·집계·근거를 한 번의 조회 스냅샷으로 읽는다(`src/repo/review_aspect_repo.py`). 그 분석 버전의 집계가 아예 없거나 요청 후보의 관측과 집계가 맞지 않으면 추천을 실패시키고, 빈 결과를 가짜(mock) 데이터로 바꿔 넣지 않는다.
- 사용한 분석 버전은 `engine.recommendation_run.engine_versions`와 `engine.review_requirement_profile`에 남는다.

## 6. DB가 강제하는 것과 앱이 맡는 것

**DB (마이그레이션)**
- 모든 PK · FK · 단순/복합/부분 UNIQUE
- 한 행 안의 CHECK(열거값, 범위, 둘 중 하나만 채우기, 상태별 필수 컬럼)
- 복합 FK로 같은 소속 강제(예: 견적 ↔ 리비전, 상품 ↔ 변형, 오퍼 ↔ 가격 관측)
- 트리거: `updated_at` 자동 갱신, 리뷰 본문 변경 시 임베딩 삭제

**앱 (`src/repo/`, `src/services/`)**
- 소유권 확인, 상태 전이, 확정 리포트 불변, JSONB 안의 키·자료형 검증
- 화면 단계·예산 비율·합계는 저장하지 않고 저장된 값으로 계산

## 7. AWS(RDS) 호환

- `vector` 확장은 RDS PostgreSQL이 지원한다. 그 밖의 확장은 쓰지 않는다(`gen_random_uuid()`는 PostgreSQL 13+ 기본 함수).
- 슈퍼유저 전용 구문(커스텀 tablespace, DDL 이벤트 트리거, `COPY FROM PROGRAM`)을 쓰지 않는다.
- 시간은 `timestamptz`(UTC)로 저장하고 표시할 때만 Asia/Seoul로 바꾼다.
- 세션 상태에 의존하지 않아 커넥션 풀(PgBouncer·RDS Proxy) 뒤에서도 동작한다.

## 8. 테스트용 일회용 DB

`pytest`는 실행 중인 PostgreSQL에 `truefit_test_<UUID>` DB를 만들고 `setup_all.py`로 마이그레이션·시드를 적용한 뒤, 끝나면 `DROP DATABASE ... WITH (FORCE)`로 지운다. 개발 DB(`truefit`)에는 쓰지 않는다.

```bash
docker compose up -d db
PYTHONPATH=. TRUEFIT_REQUIRE_TEST_DB=1 uv run pytest -q -m "not llm_live"
```

| 환경변수 | 뜻 |
|---|---|
| `TRUEFIT_REQUIRE_TEST_DB=1` | DB 준비 실패를 skip이 아니라 오류로 낸다 |
| `TEST_DATABASE_URL` | 이미 준비된 테스트 DB를 쓴다(이름에 `test`가 있어야 함) |
| `TRUEFIT_AUTO_TEST_DB=0` | 자동 생성을 끈다 |
| `TRUEFIT_ALLOW_ANY_DB=1` | 이름에 `test`가 없는 DB 접속 차단을 푼다(개발 DB에 테스트 데이터가 쌓임) |

테스트는 기본으로 `MOCK_MODE=1`(실제 LLM 호출 없음), `PGCONNECT_TIMEOUT=3`(DB가 꺼져 있으면 몇 초 안에 실패)으로 돈다. 실제 LLM을 부르는 `llm_live` 테스트는 비용이 들어 기본 실행에서 뺀다.

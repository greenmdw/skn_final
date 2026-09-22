# db/ — 스키마 마이그레이션 (Truefit)

[테이블_명세서 v6](../docs/db/table_spec.md)에서 축소된 최종 51개 테이블(9개 애플리케이션 스키마) DDL. **RDS / Aurora PostgreSQL 16 호환** 을 전제로 작성.

## 사전 준비 — Docker 필수 아님

로컬 PostgreSQL을 띄우는 방법은 둘 다 동등합니다. DB 엔진은 PostgreSQL 16이며 별도 확장에 의존하지 않습니다. AWS 배포(RDS)는 관리형 서비스라 로컬을 Docker로 했는지 conda로 했는지와 무관합니다.

**방법 A — conda (Docker Desktop 설치 불필요, 추천)**
```bash
conda create -p ./pgenv -c conda-forge postgresql=16 -y
./pgenv/Library/bin/pg_ctl -D ./pgdata initdb
./pgenv/Library/bin/pg_ctl -D ./pgdata -o "-p 5432" start
```

**방법 B — Docker**
- Docker Desktop 설치 + WSL2 엔진 활성화, 설치 후 IDE 재시작 후 `docker version`으로 확인.
- 기본 포트 5432가 사용 중이면 점유 프로세스를 중지하거나 `docker-compose.yml`의 호스트 포트를 바꾸고 `DATABASE_URL`에도 같은 포트를 사용.

공용 개발 DB는 두지 않는다 — 각자 로컬 DB에 마이그레이션을 적용한 뒤 동일한 멱등 적재 스크립트로 데이터를 재현한다.

## 실행

`data/parts_list_modify.xlsx`와 `data/peripherals/{mouse,monitor,speaker,keyboard}_processed.csv`는
팀 전달 원본이므로 Git에 포함하지 않습니다. PC·부속기기 시더나 `setup_all.py`를 실행하기 전에
해당 파일을 로컬의 위 경로에 별도로 준비해야 합니다. 파일이 없는 새 체크아웃에서
`setup_all.py`는 카탈로그 적재 단계에서 완료되지 않습니다.

**한 번에 (추천)** — 마이그레이션 + 기준 데이터 + PC/부속기기 카탈로그 + 매칭된 리뷰 요약을 순서대로 적용:
```bash
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/setup_all.py
```

**단계별로 직접**:
```bash
# 방법 B(Docker)라면 먼저: docker compose up -d
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/migrate.py up
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/seed.py
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/seed_pc_parts_specs.py
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/seed_peripherals.py
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/seed_review_summaries.py

# 현황
python db/migrate.py status
# RDS/Aurora 에 적용: DATABASE_URL 만 네트워크 DSN 으로 교체 (같은 파일, 같은 러너)
```

## 파일 (phase 순서)

| 파일 | 내용 |
|---|---|
| `0000_schema.sql` | 최종 스키마 9개 · 함수 · 51개 테이블과 최종 컬럼·CHECK |
| `0001_constraints.sql` | PK · UNIQUE · 모든 FK |
| `0002_indexes.sql` | 부분 UNIQUE와 성능 인덱스 |
| `0003_triggers.sql` | `updated_at` 자동 갱신 트리거 |

phase 방식(테이블 전부 → 제약 전부 → 인덱스 전부)을 쓴 이유는 스키마 간 순환 참조가 있기 때문이다.

## AWS 호환 원칙 (반영됨)

- `gen_random_uuid()` = PG13+ 코어 → `pgcrypto` 불필요
- PostgreSQL 확장에 의존하지 않음
- 슈퍼유저 전용 구문 없음: 커스텀 tablespace ✕, DDL 이벤트 트리거 ✕, `COPY FROM PROGRAM` ✕
- `updated_at`·(이후) 업무규칙 트리거는 일반 트리거 → RDS OK
- `timestamptz` = UTC 저장, 표시만 앱에서 Asia/Seoul
- 대용량 테이블(`offer_observation`·`feedback_event`)은
  **파티션 키를 PK 에 포함하지 않았으나 시간 컬럼이 있음** — 최종에서 `pg_partman` 으로 월 range 파티션 (무중단)
- 커넥션 풀(PgBouncer/RDS Proxy) 전제: 세션 상태 의존 없음. 트랜잭션 내 `SET LOCAL` 만 사용할 것

## DB 로 강제하는 것 vs 앱/트리거로 미루는 것

**DB (이 마이그레이션에 포함)**
- 모든 PK / FK(RESTRICT) / 단순·복합·부분 UNIQUE
- 단일 행 CHECK (enum, 범위, `num_nonnulls` XOR, 상태별 필수 컬럼)
- 복합 FK 로 같은 소속 강제: C01(plan↔revision) C02(node/req↔revision) C03(parent node)
  C04(observation↔offer) C05(variant↔product) C06(material current)
  C10(pc_build↔version) C12(review↔revision)
- `updated_at` 트리거

`identity.conversation`은 `created_at`만 저장하므로 갱신 트리거 대상이 아니다.
`config.domain_version`에는 게시 완료된 버전만 적재하며 게시 전 초안은 버전 관리 저장소에서 관리한다.
UI 표시 설정과 알림 수신 설정은 `identity.app_user`의 JSON 컬럼에 저장한다.

프론트 외부 수정 요청은 새 테이블 없이 기존 책임에 맞춰 반영한다. `app_user`는 단일 로컬 인증 수단, `plan`은 리스트 수명주기, `plan_revision`은 확정 스냅샷, `recommendation_run/candidate`는 비동기 설명 상태를 맡는다. 화면 `stage`, `budget_share`, 합계는 저장하지 않고 기존 상태와 관계형 금액으로 계산한다. `requirement.id`를 결과의 안정적인 `item_id`로 사용하며 수량·구매 시점·후보 교체에는 기존 `purchase_line`, `requirement`, `recommendation_candidate`를 사용한다.

**앱 트랜잭션 / 업무규칙 트리거 (여기 미포함 — 다음 작업)**
- C03 깊이 제한(최상위 group→slot / 최상위 slot 만), C07 접근 필터, C09 근거 출처 일치,
  C11 소유권, C13 이중 집계 방지, **C14 게시/확정 불변성**, **C15 낙관적 잠금(lock_version)**,
  C16 통화 일관성
- 상태 전이 제한 (명세서 §9)
- JSONB 키·자료형·단위 검증 (명세서 §7)

→ 이 항목들은 `src/repo/` 저장 서비스 계층 + 소수의 가드 트리거로 구현. 별도 마이그레이션(`0006_guard_triggers.sql` 등)으로 추가.

## 테스트용 일회용 DB (개발 DB 보호)

`pytest`(tests/conftest.py)는 **이름에 `test`가 들어간 DB로만** 접속한다. 개발 DB(`truefit`)에는 테스트가 익명 세션·추천
기록을 쌓지 않도록 접속을 차단하고, 그 때문에 못 도는 테스트는 실패가 아니라 skip으로 보고된다.

```bash
# 1) 일회용 DB를 만들고 같은 절차로 준비 (개발 DB와 같은 서버여도 된다)
psql -c "create database truefit_test" postgresql://truefit:truefit@localhost:5432/postgres
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test python db/setup_all.py
# 2) 테스트는 TEST_DATABASE_URL 로 그 DB를 가리킨다 (DATABASE_URL·RAG_TEST_DATABASE_URL 을 함께 덮는다)
TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test uv run pytest
```

- 보호를 끄려면 `TRUEFIT_ALLOW_ANY_DB=1` (개발 DB에 테스트 데이터가 쌓인다).
- 테스트는 `MOCK_MODE=1`(LLM 실호출 없음)과 `PGCONNECT_TIMEOUT=3`(DB가 꺼져 있어도 몇 초 안에 실패)이 기본이다.

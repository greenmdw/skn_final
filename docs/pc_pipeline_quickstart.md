# PC 추천 파이프라인 — 처음부터 재현하기

브랜치 `pc-catalog-engine` 기준. **PC 추천 파이프라인**(조건 대화 → 추천 → 결과 → 교체 → 확정 → 리포트)만
공유 범위다. 유아용품(baby)은 참고 구현으로 남아 있을 뿐 이 문서의 범위 밖이다([테스트 현황](test_status.md) 참고).

전체 그림과 미완 목록은 [pc_pipeline_overview.md](pc_pipeline_overview.md).

## 0. 준비물

| 항목 | 내용 |
|---|---|
| Python | 3.11 (`pyproject.toml`: `==3.11.*`), 패키지 관리 `uv` |
| PostgreSQL 16 + pgvector | Docker 없이 conda로 띄우는 방법과 Docker 방법 모두 [db/README.md](../db/README.md) 「사전 준비」 |
| **Git에 없는 원본 파일 (필수)** | 아래 표. 없으면 카탈로그 적재 단계에서 멈춘다 |

### Git에 없는 원본 파일 — 별도로 받아서 이 경로에 둔다

저장소 정책상 팀 전달 원본은 추적하지 않는다(`.gitignore`의 `/data/*.xlsx`, `/data/peripherals/*.csv`).

| 경로 | 무엇 | 없으면 |
|---|---|---|
| `data/parts_list_modify.xlsx` | PC 부품 8종(CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러) 카탈로그 원본 | `db/seed_pc_parts_specs.py` 실패 → 추천할 후보가 없음 |
| `data/peripherals/mouse_processed.csv`, `monitor_processed.csv`, `speaker_processed.csv`, `keyboard_processed.csv` | 부속기기 4종 | `db/seed_peripherals.py` 실패(엔진 추천 경로는 아직 이 데이터를 쓰지 않는다) |

> 이 커밋 이전(`abb829e`까지)에는 위 파일이 Git에 들어 있었다. 이 브랜치를 pull 하면 **로컬 원본이 지워질 수 있으니**
> pull 전에 `data/parts_list_modify.xlsx`와 `data/peripherals/*.csv`를 다른 곳에 복사해 두고, pull 후 원래 경로에 되돌린다.

## 1. 의존성 설치와 환경 변수

```bash
uv sync
cp .env.example .env      # 값은 채우지 않아도 된다 — 기본이 MOCK_MODE=1 (LLM 실호출 없음)
```

- `MOCK_MODE=1`이면 설명 문장은 규칙 템플릿/목 문장이다. 실제 LLM을 쓰려면 `MOCK_MODE=0`, `LLM_PROVIDER=openai`,
  `LLM_MODEL`, `OPENAI_API_KEY`가 모두 필요하다(`.env.example` 주석 참고).
- 조건 대화 에이전트(`CONDITIONS_AGENT`)와 결과 대화 에이전트(`RESULT_AGENT`)는 기본 꺼짐(규칙 경로).

## 2. DB 만들기 — 개발용 1개 + 테스트용 1개

개발 DB와 테스트 DB는 **분리**한다. 테스트(`pytest`)는 이름에 `test`가 들어간 DB에만 접속하도록 막혀 있어
(`tests/conftest.py`) 개발 DB에는 테스트 데이터가 쌓이지 않는다.

```bash
# 개발 DB
psql -c "create database truefit" postgresql://truefit:truefit@localhost:5432/postgres
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/setup_all.py

# 테스트 DB (같은 절차)
psql -c "create database truefit_test" postgresql://truefit:truefit@localhost:5432/postgres
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test python db/setup_all.py
```

`setup_all.py`는 마이그레이션(0000~0016) → 기준 데이터 → PC 카탈로그 → 부속기기 → 리뷰 요약을 순서대로 적용한다.
성공하면 마지막 줄이 `전부 완료`다. 적재 후 카탈로그의 PC 부품 수(2026-09-21 기준):

| CPU | GPU | RAM | 메인보드 | 저장장치 | 파워 | 케이스 | 쿨러 |
|---|---|---|---|---|---|---|---|
| 40 | 43 | 39 | 40 | 40 | 40 | 40 | 40 |

(같은 DB에 유아용품·부속기기 상품도 함께 적재된다. `setup_all.py`는 멱등이라 다시 돌려도 된다.)

## 3. 서버 띄우기

```bash
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit uv run uvicorn src.api:app --port 8000
# 프론트(정적) — 다른 터미널
uv run python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

`http://127.0.0.1:5500`에서 카테고리 선택 → 조건 → 추천 → 확정 흐름을 볼 수 있다. API 문서는 `http://127.0.0.1:8000/docs`.

## 4. 파이프라인이 끝까지 되는지 확인 (가장 빠른 방법)

일회용 DB를 가리켜 스모크를 돌린다. 조건 대화, 추천, 결과, 대안, 교체, 확정, 리포트까지 HTTP로 3개 흐름(신규 조립·
업그레이드·경계 상황)을 돌려 단계별 PASS/FAIL 표를 낸다.

```bash
TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test uv run python scripts/e2e_smoke.py
```

기대 결과: `합계: 39/39 단계 통과` (약 2초, 모의 LLM). 이름에 `test`가 없는 DB는 거부한다.
`--flows build,upgrade,edge`로 흐름을 고를 수 있다.

## 5. 테스트

```bash
TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test uv run pytest -q
```

- 2026-09-21 기준: **898 passed, 34 failed, 6 skipped, 1 xfailed** (약 55초). 실패 34건의 분류는 [test_status.md](test_status.md) —
  전부 이 브랜치의 PC 파이프라인 밖이다.
- 같은 테스트 DB에서 반복 실행해도 결과가 같다(인증 테스트는 시작 시 사용자 표를 비운다 — 일회용 DB에서만).
- 테스트 DB가 꺼져 있으면 DB가 필요한 테스트는 실패가 아니라 skip으로 보고된다.
- **Windows 주의**: 기본 임시 폴더(`%TEMP%\pytest-of-<user>`) 접근 거부가 나면 `--basetemp=<쓸 수 있는 폴더>`를 준다.
  콘솔이 cp949라 한글 출력이 깨지면 `PYTHONIOENCODING=utf-8`.

## 6. 자주 막히는 곳

| 증상 | 원인·해결 |
|---|---|
| `setup_all.py`가 카탈로그 적재에서 멈춤 | `data/parts_list_modify.xlsx` 없음 — 0번 표 참고 |
| 추천이 `catalog_incomplete`(가격이 확인된 PC 후보가 없는 슬롯) | 카탈로그 시드가 안 됐거나 다른 DB를 가리킴 — `DATABASE_URL` 확인 |
| 테스트가 전부 skip | `TEST_DATABASE_URL`이 없거나 DB 이름에 `test`가 없음(보호). 의도적 우회는 `TRUEFIT_ALLOW_ANY_DB=1` |
| DB가 꺼져 있을 때 테스트가 오래 멈춤 | 연결 제한시간은 기본 3초(`PGCONNECT_TIMEOUT`). PostgreSQL이 떠 있는지 확인 |

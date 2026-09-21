# PC 추천 파이프라인 — 처음부터 재현하기

브랜치 `pc-catalog-engine` 기준. **PC 추천 파이프라인**(조건 대화 → 추천 → 결과 → 교체 → 확정 → 리포트)만
공유 범위다. 유아용품 지원과 영어 UI는 2026-09-21에 제거했다([테스트 현황](test_status.md) 참고).

전체 그림과 미완 목록은 [pc_pipeline_overview.md](pc_pipeline_overview.md).

## 0. 준비물

| 항목 | 내용 |
|---|---|
| Python | 3.11 (`pyproject.toml`: `==3.11.*`), 패키지 관리 `uv` |
| Node.js | 22.12 이상 — 새 프론트(`web/`) 빌드용. 없어도 백엔드·테스트는 돈다(옛 프론트로 대체) |
| PostgreSQL 16 + pgvector | Docker 없이 conda로 띄우는 방법과 Docker 방법 모두 [db/README.md](../db/README.md) 「사전 준비」 |
| **Git에 없는 원본 파일 (필수)** | 아래 표. 없으면 카탈로그 적재 단계에서 멈춘다 |

### Git에 없는 원본 파일 — 별도로 받아서 이 경로에 둔다

저장소 정책상 팀 전달 원본은 추적하지 않는다(`.gitignore`의 `/data/*.xlsx`, `/data/peripherals/*.csv`).

| 경로 | 무엇 | 없으면 |
|---|---|---|
| `data/parts_list_modify.xlsx` | PC 부품 8종(CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러) 카탈로그 원본 | `db/seed_pc_parts_specs.py` 실패 → 추천할 후보가 없음 |
| `data/peripherals/mouse_processed.csv`, `monitor_processed.csv`, `speaker_processed.csv`, `keyboard_processed.csv` | 부속기기 4종 | `db/seed_peripherals.py` 실패(엔진 추천 경로는 아직 이 데이터를 쓰지 않는다) |
| `data/amazon23/pcparts_product_risk.json` (약 5MB) | PC 부품 리뷰 관측 산출물(리뷰 축의 입력) | **추천은 되지만 리뷰 관측 축이 꺼진 채(관측 0건)로 계산된다.** 이 파일을 직접 읽는 테스트 2건은 skip |

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

(`setup_all.py`는 멱등이라 다시 돌려도 된다. 예전에 유아용품 시드를 넣어 둔 DB에는 그 행이 그대로 남는다 — 삭제 마이그레이션은 없다. 새 DB에서 시작하면 깨끗하다.)

## 3. 프론트 빌드, 서버 띄우기, 웹 확인

새 프론트는 `web/`(React + TypeScript + Vite)에 있다. **Node.js 22.12 이상**이 필요하고, 빌드 결과(`web/dist`)는 Git에 없다.

```bash
cd web && npm ci && npm run build && cd ..        # 새 프론트 빌드 (한 번)
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit uv run uvicorn src.api:app --port 8000
```

`http://127.0.0.1:8000/`에서 랜딩 → 새 PC 구성(대화 → 분석 → 구성) → 확정(로그인 필요) → 리포트를 볼 수 있다. API 문서는 `/docs`.
서버가 프론트도 함께 서빙하므로 **서버는 하나면 된다**(화면 경로 `/plan` 등을 새로고침해도 열린다).

| 상황 | 방법 |
|---|---|
| 프론트를 고치면서 확인 | 서버를 8000에 띄운 채 `cd web && npm run dev` → `http://127.0.0.1:5173` (API 경로는 vite가 8000으로 넘긴다. 백엔드 주소는 `BACKEND_URL`) |
| 백엔드 없이 화면만 | `cd web && VITE_API_MODE=mock npm run dev` (고정 샘플 데이터) |
| 옛 정적 프론트(`frontend/`)로 | `TRUEFIT_FRONTEND=legacy` — 기본(`auto`)은 `web/dist`가 있으면 새 프론트, 없으면 옛 프론트 |

프론트 검사: `cd web && npm run build && npm run lint && npm test` (변환 로직과, 실제 백엔드 응답을 캡처한 계약 테스트).

- **실제 LLM 호출을 피하려면** `.env`의 `MOCK_MODE=1`(`.env.example` 기본값)을 확인한다. `MOCK_MODE=0`에 `OPENAI_API_KEY`가 있고
  `CONDITIONS_AGENT=1`이면 입력한 문장이 외부 LLM으로 나가고 비용이 든다. 환경 변수로 덮어써도 된다(`.env`는 이미 설정된
  환경 변수를 덮지 않는다): `MOCK_MODE=1 CONDITIONS_AGENT=0 RESULT_AGENT=0 uv run uvicorn …`
- 웹에서 만든 세션·가입 정보는 그 DB에 남는다. 연습용이면 테스트 DB(`…/truefit_test`)를 가리켜 띄운다.
- 화면의 401(`/auth/me`)은 로그인 전 게스트 상태의 정상 응답이다.

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

- 2026-09-21 기준(새 DB, 시드는 `computer`만): **622 passed, 7 failed, 6 skipped** (약 30초). 실패 7건은 전부 인증 강화 수용 테스트다
  ([test_status.md](test_status.md)). `d6_iat_boundary…`는 초 경계에 따라 통과할 수도 있어 6~7건으로 나온다.
  `data/amazon23/pcparts_product_risk.json`이 없는 새 체크아웃에서는 리뷰 원본을 읽는 2건이 skip 된다.
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

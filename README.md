<!--
  남은 일: 팀원 사진(docs/images/team/), 대표 이미지, 6번 기능별 화면 캡처 (TODO 표시 부분)
  이전 README(개발자용 실행·설정 메모 전체)는 git 기록에 있다:  git log --oneline -- README.md 로 커밋을 찾아 git show <커밋>:README.md
-->

# TrueFit

> 목적에 맞는 PC와 주변기기를 **근거와 함께** 고르는 쇼핑 플래너

<!-- TODO: 대표 이미지/로고 -->

## 1. 목차

1. [목차](#1-목차)
2. [개요](#2-개요)
3. [팀 소개](#3-팀-소개)
4. [시스템 구성도](#4-시스템-구성도)
5. [실행 방법](#5-실행-방법)
6. [주요 기능](#6-주요-기능)
7. [License](#7-license)

## 2. 개요

### 2.1 프로젝트 소개

TrueFit은 사용자가 말한 **용도·예산·취향**을 조건으로 읽어 새 컴퓨터 본체와 주변기기(모니터·키보드·마우스·스피커)를 추천하고, 이미 받은 견적서를 점검해 주는 서비스입니다. 조건 대화 → 추천 → 확정 → 리포트까지 한 브라우저 화면에서 이어집니다.

### 2.2 만든 이유

- **고르는 과정이 어렵습니다.** 부품 호환, 성능 균형, 예산, 주변기기의 사용감까지 한꺼번에 따져야 하는데 정리된 기준이 없습니다.
- **받은 견적서를 믿어도 되는지 알기 어렵습니다.** 판매점이 준 견적이 호환되는지, 가격이 적정한지 비전문가가 확인할 방법이 마땅치 않습니다.
- **기존 추천은 이유를 알려 주지 않습니다.** 점수나 순위만 있고, 왜 그 제품인지·어떤 사람이 아쉬워했는지는 보이지 않습니다.

### 2.3 차별점

- **근거를 보여 줍니다.** 추천 이유에 리뷰·사용기 인용을 붙이고, 점수가 가격·후기·스펙 등 어떤 비중으로 나왔는지 공개합니다. 후보가 몇 개 중 몇 위인지도 함께 표시합니다.
- **모르는 값은 채우지 않습니다.** 호환 검사는 "통과 / 확인 못 함 / 해당 없음"으로 나누고, 가격을 모르는 부품은 합계에서 빼고 "금액 미인식"으로 둡니다.
- **가격은 참고가임을 밝힙니다.** 판매처·관측일을 확인하지 못한 가격에는 "구매 가능 가격이 아닙니다"를 함께 적습니다.
- **말로 조건을 바꿉니다.** "6만원 이상", "손이 작아서 가벼운 무선 마우스"처럼 돌려 말해도 조건으로 읽고, 결과 화면에서 "더 싸게", "원래대로"처럼 이어서 말할 수 있습니다.
- **확정한 견적을 그대로 다시 엽니다.** 확정 당시의 설명(스펙·근거·점수)이 함께 저장되어, 나중에 열어도 추천 이유를 볼 수 있습니다.

### 2.4 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 화면 | React, Vite, TypeScript (`web/`) |
| 서버 | Python 3.11, FastAPI (`src/`) |
| 데이터베이스 | PostgreSQL (+ pgvector) (`db/`) |
| AI | OpenAI 모델 + Strands Agents SDK (조건 대화·결과 대화·견적 점검·주변기기 문장 해석·사양 추출 에이전트) |
| 배포 | Docker, Docker Compose (`deploy/`) |

## 3. 팀 소개

<!--
  사진은 docs/images/team/ 에 넣고 파일명을 아래와 맞춘다. (권장 가로 100~120px)
  member1=문동원, member2=박회종, member3=이태혁, member4=임정택, member5=이호원
-->

| 사진 | 이름 | 담당 역할 |
|:---:|:---|:---|
| <img src="docs/images/team/member1.png" width="100" alt="문동원"> | 문동원 | 주변기기 추천 알고리즘 개발, PM |
| <img src="docs/images/team/member2.png" width="100" alt="박회종"> | 박회종 | 컴퓨터 본체 제품 추천 알고리즘 개발 |
| <img src="docs/images/team/member3.png" width="100" alt="이태혁"> | 이태혁 | AWS 배포, Backend |
| <img src="docs/images/team/member4.png" width="100" alt="임정택"> | 임정택 | LLM 채팅 고도화 |
| <img src="docs/images/team/member5.png" width="100" alt="이호원"> | 이호원 | Frontend |

## 4. 시스템 구성도

사용자의 말은 AI 에이전트가 조건으로 읽고, 추천 결과는 규칙 기반 엔진이 DB의 부품·리뷰 근거로 계산합니다. AI는 문장을 이해하고 설명을 쓰는 데 쓰고, 호환 판정과 점수는 코드와 데이터로 정합니다.

```mermaid
flowchart LR
    U[사용자 브라우저] --> W[화면<br/>React + Vite]
    W -->|REST API| A[FastAPI 서버<br/>src/api.py]
    A --> E[추천 엔진<br/>호환 검사 · 점수 · 최적화]
    A --> G[AI 에이전트<br/>조건 해석 · 결과 대화 · 견적 점검]
    G -->|LLM 호출| L[(OpenAI)]
    E --> D[(PostgreSQL + pgvector<br/>카탈로그 · 리뷰 근거 · 견적 · 계정 · 커뮤니티)]
    A --> D
```

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| 화면 | `web/` | 대화·추천 결과·장바구니·리포트·커뮤니티 화면. 빌드 결과(`web/dist`)를 서버가 같은 주소로 서빙 |
| 서버 | `src/` | API, 추천 엔진, 서비스, AI 에이전트 |
| 데이터베이스 | `db/` | 마이그레이션, 시드(부품 카탈로그·주변기기·리뷰 근거) |
| 설정·데이터 | `config/`, `data/` | 카테고리·주변기기 규칙, 시드 데이터 |
| 테스트 | `tests/` | pytest |

### 추천 엔진 처리 단계 (`src/engine/`)

| 단계 | 하는 일 |
|---|---|
| 1. 의도 분해 | 대화에서 용도·예산·우선순위를 뽑고 빠진 항목을 되묻는다(슬롯 채우기) |
| 2. 요구 사양 | 조건을 부품별 요구 사양으로 바꾼다 |
| 3-0. 후보 수집 | 카탈로그에서 후보를 모은다 |
| 3-A. 하드 필터 | 조건을 못 지키는 후보를 통과 / 탈락 / 보류로 가른다 |
| 3-B. 순위 | 적합도와 병목을 보고 후보 순위를 정한다 |
| 3-C. 검증 | 규칙으로 호환을 판정하고, 쟁점을 문장으로 쓴다 |
| 4. 세트 최적화 | 예산 안에서 부품 조합을 고른다 |
| 5. 설명 생성 | 추천 이유와 근거를 문장으로 만든다 |
| 6. 되먹임 | 사용 결과를 모아 다음 추천에 반영한다(별도 오프라인 배치) |

주변기기는 같은 구조를 따르되, 문장 해석과 사용기 근거(`src/engine/peripheral_*.py`)를 따로 둡니다.

## 5. 실행 방법

### 5.1 준비물

- Python 3.11, [uv](https://docs.astral.sh/uv/)
- Docker Desktop (PostgreSQL 컨테이너용)
- Node.js 20 이상 (화면 빌드용)
- 시드 데이터 (Git에 없음 — 팀 공유 채널에서 받아 넣기)
  - `data/peripherals/{mouse,monitor,speaker,keyboard}_processed.csv`
  - `data/review_seed/` (리뷰 시드 번들, [안내](data/review_seed/README.md))
  - `data/parts_list_modify.xlsx`는 Git에 있습니다.

### 5.2 최초 설정

저장소 루트에서 PowerShell로 실행합니다.

```powershell
# 1. DB 컨테이너 (Docker Desktop이 켜져 있어야 함)
docker compose up -d db

# 2. 파이썬 패키지
uv sync --locked

# 3. DB 마이그레이션 + 시드
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run python db/setup_all.py

# 4. 화면 빌드
cd web
npm install
npm run build
cd ..
```

`.env`가 없으면 `.env.example`을 복사해서 만듭니다. 기본값(`MOCK_MODE=1`)이면 OpenAI 키 없이 가짜 LLM으로 동작합니다.

### 5.3 실행

```powershell
docker compose up -d db
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run uvicorn src.api:app --reload --port 8000
```

- 화면: http://127.0.0.1:8000
- API 문서: http://127.0.0.1:8000/docs
- 종료: 실행 중인 터미널에서 `Ctrl+C`

코드를 새로 받은 뒤에는 `uv run python db/migrate.py up`(새 마이그레이션 적용)과 화면 재빌드(`npm run build`)를 한 번씩 하세요.

### 5.4 실제 LLM(OpenAI) 사용

`.env`에 아래가 모두 있어야 실제 호출이 켜집니다. 키는 Git에 올리지 마세요.

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna
OPENAI_API_KEY=(본인 키)
```

선택 설정(`CONDITIONS_AGENT`, `RESULT_AGENT` 등)은 `.env.example`의 주석을 따릅니다.

#### 주변기기 견적을 제대로 쓰려면 (`PERIPHERAL_INTENT_AGENT=1`)

주변기기 채팅이 문장을 조건으로 읽는 방법은 두 가지입니다. 화면을 확인할 때는 **켠 상태**(`PERIPHERAL_INTENT_AGENT=1` + 위 LLM 설정)로 보세요. 꺼져 있으면 단어 규칙으로만 읽어, 돌려 말한 문장은 반영되지 않는 일이 많습니다. 서버를 다시 시작해야 반영됩니다.

### 5.5 테스트

```powershell
docker compose up -d db
$env:PYTHONPATH = "."
$env:TRUEFIT_REQUIRE_TEST_DB = "1"
uv run pytest -q -m "not llm_live"
```

`llm_live` 시험은 실제 LLM을 호출해 비용이 드니 기본에서 뺍니다.

### 5.6 자주 겪는 문제

| 증상 | 원인과 해결 |
|---|---|
| `DB 연결 실패 ... connection timeout expired` | Docker Desktop이 꺼져 있거나 DB 컨테이너가 안 떠 있음. `docker compose up -d db` 후 `docker compose ps`에서 `healthy` 확인 |
| 화면이 안 뜨고 API 문서만 보임 | `web/dist`가 없음. `cd web; npm install; npm run build` 후 서버 재시작 |
| `setup_all.py`가 시드 파일이 없다고 실패 | 5.1의 시드 데이터를 받아서 넣기 |
| `ModuleNotFoundError: src` | 저장소 루트에서 실행하고 `$env:PYTHONPATH = "."` 설정 |
| 8000 포트가 이미 사용 중 | 이전 서버 종료 또는 `--port 8001`로 실행 |

### 5.7 Docker로 한 번에 띄우기 (배포용)

```powershell
docker compose up -d --build
docker compose exec api python db/setup_all.py
```

배포 환경에서는 `JWT_SECRET`을 반드시 바꾸고, HTTPS 뒤에서는 `COOKIE_SECURE=1`로 설정합니다.

## 6. 주요 기능

> 기능별로 한 줄 설명과 화면 캡처를 넣어 주세요. (작성 예정)

### 6.1 새 컴퓨터 본체 추천

- 용도·예산·우선순위를 대화로 받아 부품 구성을 추천하고, 호환 검사와 예산 사용을 함께 보여 줍니다.
- 결과 화면에서 부품 교체, 수량 변경, 결과 대화를 할 수 있습니다.
- <!-- TODO: 캡처 -->

### 6.2 받은 견적 점검

- 사진·텍스트로 받은 견적서를 인식해 호환성·가격·용도 적합성을 종합 평가하고, 교체 후보를 비교합니다.
- <!-- TODO: 캡처 -->

### 6.3 주변기기 견적

- 모니터·키보드·마우스·스피커를 말로 고르면 후보와 근거(스펙, 리뷰·사용기 인용, 점수 비중)를 보여 줍니다.
- 예산을 넘으면 결과 화면에서 알려 주고, 확정한 견적은 설명 그대로 다시 열 수 있습니다.
- <!-- TODO: 캡처 -->

### 6.4 장바구니·확정·리포트

- 본체와 주변기기를 장바구니에서 합쳐 확정하면 리포트가 만들어집니다. 저장한 견적에서 다시 열어 수정할 수 있습니다.
- <!-- TODO: 캡처 -->

### 6.5 커뮤니티·마이페이지

- 사용기 게시판, 알림, 내 구성·AI 상담 기록·추천 리포트 모아 보기.
- <!-- TODO: 캡처 -->

## 7. License

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다. Copyright (c) 2026 TrueFit Team.

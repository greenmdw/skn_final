# TrueFit

목적 기반 쇼핑 플래너. 현재 범위는 **PC 추천(한국어)** 입니다.
카테고리 선택 → 조건 대화 → 추천 → 확정 → 리포트 흐름을 한 브라우저 화면에서 진행합니다.

| | |
|---|---|
| 작성자 | Charlie (greenmdw@gmail.com) |
| 최종 수정 | 2026-09-29 |
| 기준 브랜치 | `develop` (`front`와 동일 커밋 `e126920`) |

## 구성

| 폴더 | 내용 |
|---|---|
| `src/` | FastAPI 백엔드 (`src/api.py`), 추천 엔진, 서비스, 에이전트 |
| `web/` | 화면(React + Vite). 빌드 결과 `web/dist`를 백엔드가 같은 주소에서 서빙 |
| `db/` | PostgreSQL 마이그레이션 8개(`db/migrations/0000`~`0007`), 시드 스크립트, `setup_all.py` |
| `config/`, `data/` | 카테고리 설정, 시드·리뷰 데이터 (`data/reviews/`는 [README](data/reviews/README.md) 참고) |
| `tests/` | pytest |

화면은 모두 React(`web/src`)이고, 데이터는 전부 백엔드 API에서 가져옵니다. **가짜(목업) 데이터는 없습니다.** 아직 백엔드와 연결하지 않은 화면은 가짜 내용을 보여주지 않고 "개발 전" 안내만 나옵니다. 옛 `frontend/` 정적 페이지와 HTML 프로토타입은 삭제됐고, 프론트는 `web/`만 씁니다.

| 화면 | 경로 | 상태 |
|---|---|---|
| 로그인, 회원가입 | `/login`, `/signup` | React, 백엔드 연결 |
| 조건 대화 | `/start` | React, 백엔드 연결 |
| 추천 결과 | `/plan` | React, 백엔드 연결 (부품 교체·수량·구매 시점·결과 대화 포함) |
| 장바구니, 확정 | `/cart` | React, 백엔드 연결 (확정은 로그인 필요) |
| 리포트 | `/report/<id>` | React, 백엔드 연결 |
| 저장한 견적 | 상단 버튼 → 오른쪽 슬라이드 패널 | React, 백엔드 연결 (별도 페이지 없음) |
| 메인, 시작 방식 선택 | `/`, `/choose` | React (정적 소개 화면) |
| 받은 견적 점검 | `/check` | 개발 전 (안내만 표시) |
| 주변기기 견적 | `/peripherals` | 개발 전 (안내만 표시) |

백엔드·타 팀에 요청할 일은 [docs/개발요청_백엔드_및_타팀.md](docs/개발요청_백엔드_및_타팀.md)에 정리한다. 새 화면은 `web/src/pages/`에 React 컴포넌트로 만들고, 가짜 데이터로 채우지 않고 처음부터 백엔드 API(`web/src/api/`)에 연결합니다. 서버 통신은 `web/src/api/`, 화면 상태는 `web/src/state/`에 있습니다.

## 준비물

- Python 3.11, [uv](https://docs.astral.sh/uv/)
- Docker Desktop (PostgreSQL 컨테이너용)
- Node.js 20 이상 (화면 빌드용)
- 시드 데이터 파일
  - `data/parts_list_modify.xlsx`: Git에 있음
  - `data/peripherals/{mouse,monitor,speaker,keyboard}_processed.csv`: **Git에 없음**, 팀 공유 파일을 받아 넣기
- 리뷰 원본 `data/reviews/*.jsonl`: **Git에 없음**, 팀 공유 파일을 받아 넣기.
- DB 초기 설정에 필요한 실제 리뷰 시드 `data/review_seed/`: **Git에 없음**, 팀 공유 번들을 준비하기. `setup_all.py`가 원문·규칙·관측·집계를 순서대로 적재하며, 파일이 없거나 해시가 다르면 실패합니다. [시드 번들 안내](data/review_seed/README.md)를 참고하세요.

## 처음 한 번만 (최초 설정)

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

## 평소 실행

```powershell
docker compose up -d db
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run uvicorn src.api:app --reload --port 8000
```

- 화면: http://127.0.0.1:8000
- API 문서: http://127.0.0.1:8000/docs
- 종료: 실행 중인 터미널에서 `Ctrl+C`

## 코드를 받은 뒤 (pull 후 해야 할 일)

- **새 마이그레이션이 들어왔는지 확인하고 개발 DB에 적용합니다.** `db/migrations/`에 파일이 늘어나면(예: `0006_report_soft_delete`, `0007_peripheral_line`) 이미 만들어 둔 로컬 DB에는 자동으로 반영되지 않습니다. 적용하지 않으면 `GET /lists`가 500 오류를 내는 등 API가 깨질 수 있습니다. 매번 pull 뒤에 한 번씩 실행하세요(이미 적용된 것은 건너뜁니다).

  ```powershell
  $env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
  uv run python db/migrate.py status   # 적용 현황 (pending 이 있으면 아래 실행)
  uv run python db/migrate.py up       # 아직 안 한 마이그레이션만 적용
  ```

  처음부터 새로 만드는 경우(`setup_all.py`)에는 마이그레이션이 모두 함께 적용되니 따로 할 필요가 없습니다. 각 마이그레이션이 무엇을 바꾸는지는 `db/README.md`의 표와 파일 머리 주석에 있습니다.

- `web/dist`는 Git에 올라가지 않는 빌드 결과물입니다. **pull 받은 뒤 각자 화면을 한 번 빌드해야** 화면이 뜹니다.

  ```powershell
  cd web
  npm install
  npm run build
  ```

- `web/` 안의 화면 코드를 고쳤을 때도 다시 빌드하고 서버를 재시작합니다.
- `web/dist`가 없으면 화면 없이 API만 뜹니다.

## 실제 LLM(OpenAI) 사용

`.env`에서 아래 값을 채웁니다. 모두 있어야 실제 호출이 켜집니다.

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna      # 팀 기본 모델 (.env.example 과 같음)
OPENAI_API_KEY=(본인 키)
CONDITIONS_AGENT=1   # 조건 대화 에이전트 (선택)
RESULT_AGENT=1       # 결과 화면 대화 에이전트 (선택)
```

`.env`는 Git에 올라가지 않습니다. 키를 커밋하지 마세요.

### 주변기기 견적을 제대로 쓰려면 (`PERIPHERAL_INTENT_AGENT=1`)

주변기기 견적 화면(`/peripherals`)의 채팅은 사용자가 쓴 문장을 **조건(종류·목적·스펙 조건·예산·손 크기·브랜드·질문)으로 읽는 단계**가 있습니다. 읽는 방법이 둘입니다.

| 설정 | 문장을 읽는 방법 | 특징 |
|---|---|---|
| `PERIPHERAL_INTENT_AGENT=1` (+ 아래 LLM 설정) | 언어 모델이 정해진 목록(`config/peripherals.yaml`)의 값으로 읽음 | 말투가 달라도 읽는다. "6만원 이상", "손이 작아서 가벼운 무선", 질문("왜 이걸 1위로 골랐어?")·이어 말하기에 가장 정확하다 |
| `PERIPHERAL_INTENT_AGENT=0` (기본) 또는 LLM 설정 없음 | **단어 규칙**(`interpret_by_words`)으로 읽음 | 목록의 낱말이 있어야만 읽는다. 키가 없어도 돌아가지만, 돌려 말한 문장은 "반영하지 못했어요"로 빠지는 일이 많다 |

팀에서 화면을 확인할 때는 **켠 상태**로 보세요. 꺼져 있으면 같은 문장도 결과가 달라 보입니다. `.env`에 아래 세 가지가 모두 있어야 실제로 켜집니다(하나라도 빠지면 켜도 단어 규칙으로 갑니다).

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna          # 팀 기본 모델
OPENAI_API_KEY=(본인 키)
PERIPHERAL_INTENT_AGENT=1
```

- 서버를 **다시 시작**해야 반영됩니다(`.env`는 시작할 때 한 번 읽습니다).
- 문장 하나를 읽을 때마다 모델을 한 번 부릅니다(같은 문장은 캐시). 비용이 들고, 동시 호출이 몰리거나 모델이 실패하면 **그 문장만 자동으로 단어 규칙으로 물러납니다**(화면에는 오류가 아니라 평소 답이 나옵니다).
- 켜졌는지 확인하려면: 채팅에 `스피커 6만원 이상되는 제품으로 변경해줘` 또는 `조용한 곳에서 쓸 가벼운 무선 마우스` 처럼 돌려 말한 문장을 보내 보세요. 이해한 내용에 칩이 제대로 나오면 켜진 것입니다. 서버 로그에 `peripheral intent: 모델 해석 실패, 단어 규칙으로 물러남`이 보이면 모델 호출이 실패해 규칙으로 간 것입니다(키·모델 이름·네트워크를 확인하세요).
- `MOCK_MODE=1`이면 이 값을 1로 해도 모델을 부르지 않습니다(가짜 LLM 모드).

#### `PERIPHERAL_POST_AGENT`는 뭔가요? (보통은 0으로 둡니다)

`PERIPHERAL_POST_AGENT`는 **웹 화면과는 무관한 배치 작업용** 스위치입니다. 커뮤니티에 올라온 주변기기 **사용기 글**을 언어 모델로 읽어 "소리가 조용하다", "그립이 편하다" 같은 **체감 문장을 뽑아 `engine.peripheral_post_evidence`에 쌓는 분석 작업**(`python -m src.workers.peripheral_post_analysis`)이 켜져 있는지를 정합니다.

- **0(기본)**: 분석 작업이 모델을 부르지 않고 그냥 끝납니다. 화면·추천은 **이미 DB에 쌓인 근거**(예시 글 분석 결과는 `db/community_examples_snapshot.py`로 받습니다 — `data/community_examples/README.md`)를 그대로 씁니다. 개발·화면 확인에는 0이면 충분합니다.
- **1**: 새로 올라온 글을 분석합니다(하루 `PERIPHERAL_POST_DAILY_LIMIT`=200편, 글 하나당 모델 호출, 비용 발생). 사용기 분석을 직접 돌리는 담당자만 켭니다. `MOCK_MODE=0`·`OPENAI_API_KEY`·`LLM_MODEL`이 함께 있어야 하고, 절차는 `data/community_examples/README.md`에 있습니다.
- 추천 화면의 "사용기 인용"이 비어 있다고 이 값을 켤 필요는 없습니다. 그 분석 결과 스냅샷을 아직 DB에 받지 않았거나 해당 제품에 사용기가 없는 경우가 대부분입니다.

## 테스트

DB가 필요한 테스트는 테스트 전용 DB를 자동으로 만들고 끝나면 지웁니다. 개발 DB(`truefit`)에는 접속하지 않습니다.

```powershell
docker compose up -d db
$env:PYTHONPATH = "."
$env:TRUEFIT_REQUIRE_TEST_DB = "1"
uv run pytest -q
```

DB 없이 빠른 테스트만:

```powershell
$env:PYTHONPATH = "."
$env:TRUEFIT_AUTO_TEST_DB = "0"
uv run pytest -q -m "not db and not integration"
```

## 자주 겪는 문제

| 증상 | 원인과 해결 |
|---|---|
| `DB 연결 실패 ... connection timeout expired` | Docker Desktop이 꺼져 있거나 DB 컨테이너가 안 떠 있음. Docker Desktop 실행 후 `docker compose up -d db`, `docker compose ps`에서 `healthy` 확인 |
| 화면이 안 뜨고 API 문서만 보임 | `web/dist`가 없음. `cd web; npm install; npm run build` 후 서버 재시작 |
| 예전 화면이 뜸 | 오래된 `web/dist`가 남아 있음. 다시 빌드하고 서버 재시작, 브라우저는 `Ctrl+Shift+R` |
| `setup_all.py`가 시드 파일 없다고 실패 | 위 "준비물"의 `data/peripherals/*.csv`를 받아서 넣기 |
| `ModuleNotFoundError: src` | 저장소 루트에서 실행하고 `$env:PYTHONPATH = "."` 설정 |
| 8000 포트가 이미 사용 중 | 이전 서버가 남아 있음. 종료하거나 `--port 8001`로 실행 |

## Docker로 한 번에 띄우기 (배포용)

```powershell
docker compose up -d --build
docker compose exec api python db/setup_all.py
```

배포 환경에서는 `JWT_SECRET`을 반드시 바꾸고, HTTPS 뒤에서는 `COOKIE_SECURE=1`로 설정합니다.

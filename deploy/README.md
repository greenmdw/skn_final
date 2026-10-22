# AWS 서버(EC2 + RDS) 배포 — 작업용 서버 (HTTP)

| 구성 | 내용 |
|---|---|
| 서버 | EC2 `t3.medium` 한 대(Ubuntu 24.04)에 도커로 컨테이너 3개(`api`·`worker`·`purge`)를 띄운다 — `docker-compose.aws.yml` |
| DB | RDS PostgreSQL `db.t3.small`(pgvector, `max_connections=191`) — `deploy/aws.env.example`의 연결 풀 설정 기준 |
| 접속 | 도메인·인증서가 없어 HTTP 80 포트로 서비스한다(EC2 80 → 컨테이너 8000) |
| 브랜치 | 작업용 서버는 `develop`을 따라간다. `main`으로도 배포할 수 있다 |

| 컨테이너 | 하는 일 | 켜는 조건 |
|---|---|---|
| `api` | FastAPI 서버 + React 화면. `uvicorn --workers ${UVICORN_WORKERS:-2}` | 항상 |
| `worker` | 커뮤니티 사용기 분석(`src.workers.peripheral_post_analysis`) | `.env`의 `PERIPHERAL_POST_AGENT=1` |
| `purge` | 삭제 표시한 대화·견적서를 보관 기간(`PURGE_DELETED_AFTER_DAYS`, 기본 30일) 뒤 영구 삭제(`src.workers.purge_deleted`) | `.env`의 `PURGE_DELETED=1` |

`worker`·`purge`는 꺼져 있으면 안내 문구만 남기고 대기한다(종료하면 재시작 정책이 계속 다시 띄우기 때문). 세 컨테이너 모두 `api`와 같은 이미지(`truefit-api:aws`)와 같은 `.env`를 쓴다.

## 최초 1회

1. 서버에 도커·git을 설치하고 저장소를 받는다(공개 저장소라 인증 없이 받는다).
   ```bash
   git clone -b develop https://github.com/greenmdw/skn_final.git ~/truefit
   ```
2. `.env`를 만든다. 값은 서버에서만 채운다(저장소는 공개이고 `.env`는 Git에 올라가지 않는다).
   ```bash
   cd ~/truefit && cp deploy/aws.env.example .env
   sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
   nano .env      # DATABASE_URL(RDS 엔드포인트·사용자·비밀번호), 실제 LLM을 쓰려면 OPENAI_API_KEY와 MOCK_MODE=0
   ```
3. Git에 없는 시드 파일을 서버의 `~/truefit/data/` 아래에 같은 경로로 올린다(MobaXterm 업로드 등).
   - `data/peripherals/*_processed.csv` 4개, `data/review_seed/*.json` 5개 (`data/parts_list_modify.xlsx`는 Git에 있다)
   - `docker-compose.aws.yml`이 `./data`를 컨테이너에 읽기 전용으로 마운트하므로, 올린 뒤 다시 빌드하지 않아도 된다.
4. 이미지를 빌드하고 스키마와 시드를 적재한다(최초 1회, 멱등).
   ```bash
   docker compose -f docker-compose.aws.yml build
   docker compose -f docker-compose.aws.yml run --rm api python db/setup_all.py
   ```
5. 기동하고 확인한다.
   ```bash
   scripts/deploy_aws.sh
   ```
   `정상: {"status":"ok",...}`가 나오면 브라우저에서 `http://서버IP/`로 접속한다.

## 평소 재배포 (팀원이 push한 코드 반영)

```bash
cd ~/truefit && scripts/deploy_aws.sh          # develop
cd ~/truefit && scripts/deploy_aws.sh main     # 배포용 브랜치
```

`scripts/deploy_aws.sh`가 하는 일:

1. `.env`가 있는지, `JWT_SECRET`이 채워져 있는지 확인(없으면 중단)
2. 지정한 브랜치를 `git pull --ff-only`로 받기
3. 이미지 빌드
4. 새 마이그레이션만 적용(`python db/migrate.py up`)
5. 컨테이너 전부 기동(`up -d`)
6. `/health`를 2초 간격으로 최대 30번 확인. 실패하면 `api` 로그 50줄을 보여 주고 종료 코드 1

재기동하는 몇 초 동안 서비스가 끊긴다. 시드는 다시 적재하지 않는다(새 시드가 필요하면 최초 1회의 4번을 다시 실행).

## 사용기 분석 작업 (worker)

커뮤니티 사용기 글을 분석해 주변기기 추천의 체감 근거를 쌓는다. 글이 올라오거나 고쳐지면 API가 대기 기록(`engine.peripheral_post_intake`)을 남기고, worker가 `PERIPHERAL_POST_INTERVAL_SECONDS`(기본 60초)마다 읽어 분석한다.

- **켜기:** `.env`에 `PERIPHERAL_POST_AGENT=1`(그리고 `MOCK_MODE=0`, `OPENAI_API_KEY`)을 두고 `docker compose -f docker-compose.aws.yml up -d worker`.
  꺼져 있는 동안 글은 대기 상태로 쌓이고, 켜면 한꺼번에 처리한다.
- **끄기:** `.env`에서 `PERIPHERAL_POST_AGENT=0`으로 바꾸고 `docker compose -f docker-compose.aws.yml up -d --force-recreate worker`.
- **비용:** 글 한 편당 모델 호출 1번과 근거 문장 임베딩. `PERIPHERAL_POST_DAILY_LIMIT`(기본 200편/일, UTC)이 상한이고, 본문·연결 제품이 그대로인 글은 다시 분석하지 않는다. 사용기가 아니거나 카탈로그 제품이 연결되지 않은 글은 모델을 부르지 않는다.
- **미리 보기(모델 호출·쓰기 없음):** `docker compose -f docker-compose.aws.yml exec worker python -m src.workers.peripheral_post_analysis --dry-run`
- **한 번만 돌리기:** `docker compose -f docker-compose.aws.yml exec worker python -m src.workers.peripheral_post_analysis --once`
- **로그:** `docker compose -f docker-compose.aws.yml logs --tail=100 -f worker` — 한 번 돌 때마다 `대기 · 분석 · 건너뜀 · 닫음 · 근거 제거 · 오류` 줄이 남는다. 꺼져 있으면 "꺼져 있습니다" 안내가 남는다.
- **DB 연결:** worker는 연결 하나만 쓴다.

## 삭제 데이터 정리 (purge)

- **켜기:** `.env`에 `PURGE_DELETED=1` → `docker compose -f docker-compose.aws.yml up -d purge`.
- 꺼져 있으면 아무것도 지우지 않고 대기한다. 삭제 표시만 된 대화·견적서는 그대로 남는다.

## 확인·문제 해결

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 | `docker compose -f docker-compose.aws.yml ps` |
| 로그 | `docker compose -f docker-compose.aws.yml logs --tail=100 -f api` |
| 재시작 | `docker compose -f docker-compose.aws.yml restart api` |
| 컨테이너 안에서 | `docker compose -f docker-compose.aws.yml exec api sh` |
| RDS 연결 수 | `psql`로 접속해 `SELECT count(*) FROM pg_stat_activity;` |

## 주의

- **HTTP이므로** `APP_ENV=development`, `COOKIE_SECURE=0`이다. 이 값에서는 `/dev/*` 개발용 경로가 열리고 비밀번호가 평문으로 오간다. EC2 보안 그룹의 80 포트는 팀 IP로만 열어 두고 **실제 비밀번호를 쓰지 않는다.** HTTPS로 옮길 때 `APP_ENV=production`, `COOKIE_SECURE=1`로 바꾼다(`production`이면 로그인 쿠키가 Secure 전용이라 HTTP에서는 로그인이 안 된다).
- **DB 연결 수:** 서버 프로세스 하나가 최대 `DB_POOL_MAX + DB_BACKGROUND_POOL_MAX`개를 쓴다. 견본 값(28 + 6)에 프로세스 2개면 최대 68개이고, worker가 1개를 더 쓴다. RDS `max_connections`(db.t3.small 191)를 넘지 않게 맞춘다. 배포용 컨테이너를 같은 RDS에 더 붙이면 합계를 다시 계산한다.
- **프로세스마다 따로 세는 값:** IP별 요청 한도, LLM 동시 호출 상한(`LLM_MAX_CONCURRENCY`), LLM 대기 요청 수(`LLM_REQUEST_MAX`), 추천 작업자 수. `UVICORN_WORKERS`를 늘리면 합이 배수가 된다.
- **커뮤니티 이미지**는 서버의 `./uploads`에 저장된다(컨테이너 `/app/uploads`). 재배포해도 남지만 EC2를 지우면 함께 사라진다.
- 비밀번호·API 키·JWT 비밀은 채팅·이슈·커밋에 붙여 넣지 않는다.
- **`docker compose config`·`docker inspect`는 `.env`의 값을 그대로 펼쳐 출력한다**(OPENAI_API_KEY·JWT_SECRET·DB 비밀번호 포함). 화면 공유·채팅·로그에 붙여 넣기 전에 확인하고, 새어 나갔다면 그 키를 폐기하고 새로 발급받는다. 구성만 확인하려면 `docker compose -f docker-compose.aws.yml config --no-env-resolution`으로 `.env` 값을 풀지 않고 본다.

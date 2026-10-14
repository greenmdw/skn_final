# AWS 서버(EC2 + RDS) 배포 — 작업용 서버 (HTTP)

구성: EC2 `t3.medium`(Ubuntu 24.04) 한 대에 도커로 api 를 띄우고, DB 는 RDS PostgreSQL(`db.t3.micro`, pgvector)을 쓴다.
도메인·인증서가 없는 동안은 HTTP(80)로 서비스한다. 작업용은 `develop` 브랜치를 따라간다.

## 최초 1회

1. 서버에 도커·git 설치, 저장소 받기 (공개 저장소라 인증 없이 받는다)
   ```bash
   git clone -b develop https://github.com/greenmdw/skn_final.git ~/truefit
   ```
2. `.env` 만들기 — 값은 서버에서만 채운다(이 저장소는 공개이고 `.env` 는 git 에 올라가지 않는다)
   ```bash
   cd ~/truefit && cp deploy/aws.env.example .env
   sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
   nano .env      # DATABASE_URL(RDS 엔드포인트·사용자·비밀번호), 필요하면 OPENAI_API_KEY 와 MOCK_MODE=0
   ```
3. 비공개 시드 데이터 올리기 — git 에 없는 파일을 서버의 `~/truefit/data/` 아래에 같은 경로로 올린다(MobaXterm 업로드 등).
   AGENTS.md 의 "Required seed inputs" 목록: `data/peripherals/*_processed.csv` 4개, `data/review_seed/*.json` 5개.
   (`data/parts_list_modify.xlsx` 는 git 에 있다.) `docker-compose.aws.yml` 이 `./data` 를 컨테이너에 마운트하므로 올린 뒤 다시 빌드하지 않아도 된다.
4. 이미지 빌드 후 스키마와 시드 적재 (최초 1회, 멱등)
   ```bash
   docker compose -f docker-compose.aws.yml build
   docker compose -f docker-compose.aws.yml run --rm api python db/setup_all.py
   ```
5. 기동과 확인
   ```bash
   scripts/deploy_aws.sh
   ```
   `정상: {"status":"ok",...}` 가 나오면 브라우저에서 `http://서버IP/` 로 접속한다.

## 평소 재배포 (팀원이 push 한 코드 반영)

```bash
cd ~/truefit && scripts/deploy_aws.sh          # develop
cd ~/truefit && scripts/deploy_aws.sh main     # 배포용 브랜치
```
pull → 빌드 → 새 마이그레이션 적용 → 재기동 → 헬스체크까지 한 번에 한다. 재기동하는 몇 초 동안 서비스가 끊긴다.

## 사용기 분석 작업 (worker)

커뮤니티 사용기 글을 분석해 주변기기 추천의 체감 근거를 쌓는 작업이다. `docker-compose.aws.yml` 의 `worker` 서비스가 `api` 와 같은 이미지로
따로 돌고, `scripts/deploy_aws.sh` 의 `up -d` 가 `api` 와 함께 띄운다. 글이 올라오면 API 가 DB 에 대기 기록을 남기고(`engine.peripheral_post_intake`),
worker 가 `PERIPHERAL_POST_INTERVAL_SECONDS`(기본 60초)마다 읽어 분석한다.

- **켜기:** 서버 `.env` 에 `PERIPHERAL_POST_AGENT=1`(그리고 `MOCK_MODE=0`, `OPENAI_API_KEY`)을 두고 `docker compose -f docker-compose.aws.yml up -d worker`.
  꺼져 있는 동안 worker 는 "꺼져 있습니다" 안내만 남기고 대기한다(글은 대기 상태로 쌓이고, 켜면 한꺼번에 처리한다).
- **끄기:** `.env` 에서 `PERIPHERAL_POST_AGENT=0` 으로 바꾸고 `docker compose -f docker-compose.aws.yml up -d --force-recreate worker`.
- **비용:** 글 한 편당 모델 호출 1번과 근거 문장 임베딩. `PERIPHERAL_POST_DAILY_LIMIT`(기본 200편/일, UTC)이 상한이고 본문·연결 제품이 그대로인 글은 다시 분석하지 않는다.
  사용기가 아니거나 카탈로그 제품이 연결되지 않은 글은 모델을 부르지 않는다.
- **무엇을 분석할지 미리 보기(모델 호출·쓰기 없음):**
  ```bash
  docker compose -f docker-compose.aws.yml exec worker python -m src.workers.peripheral_post_analysis --dry-run
  ```
- **한 번만 돌리기:** `docker compose -f docker-compose.aws.yml exec worker python -m src.workers.peripheral_post_analysis --once`
- **로그:** `docker compose -f docker-compose.aws.yml logs --tail=100 -f worker` — 한 번 돌 때마다 `대기 · 분석 · 건너뜀 · 닫음 · 근거 제거 · 오류` 줄이 남는다.
- **DB 연결:** worker 는 연결 하나만 쓴다(연결 한도 계산에 +1).

## 확인·문제 해결

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 | `docker compose -f docker-compose.aws.yml ps` |
| 로그 | `docker compose -f docker-compose.aws.yml logs --tail=100 -f api` |
| 재시작 | `docker compose -f docker-compose.aws.yml restart api` |
| 컨테이너 안에서 | `docker compose -f docker-compose.aws.yml exec api sh` |
| RDS 연결 수 | `psql` 로 접속해 `SELECT count(*) FROM pg_stat_activity;` (한도 81) |

## 주의

- **HTTP 이므로** `APP_ENV=development`, `COOKIE_SECURE=0` 이다. 이 값에서는 `/dev/*` 개발용 경로가 열리고 비밀번호가 평문으로 오간다.
  EC2 보안 그룹의 80 포트는 팀 IP 로만 열어 두고, **실제 비밀번호를 쓰지 않는다.** HTTPS 로 옮길 때 `APP_ENV=production`, `COOKIE_SECURE=1` 로 바꾼다.
- **연결 한도:** RDS `max_connections=81`. 서버 프로세스 하나가 최대 `DB_POOL_MAX + DB_BACKGROUND_POOL_MAX`(기본 16)개를 쓰고,
  프로세스가 `UVICORN_WORKERS`(2)개라 최대 32개다. 배포용 컨테이너를 같은 RDS 에 붙이면 합계가 60 을 넘지 않게 줄인다.
- **프로세스마다 따로 세는 값:** IP별 요청 한도, LLM 동시 호출 상한, 추천 작업자 수. 프로세스를 늘리면 합이 배수가 된다.
- 비밀번호·API 키·JWT 비밀은 채팅·이슈·커밋에 붙여 넣지 않는다.

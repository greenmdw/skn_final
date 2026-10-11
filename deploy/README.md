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

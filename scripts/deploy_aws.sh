#!/usr/bin/env bash
# AWS 서버에서 실행: 최신 코드를 받아 빌드하고, 스키마 마이그레이션을 적용하고, 기동한 뒤 헬스체크한다.
#   scripts/deploy_aws.sh            # develop (기본)
#   scripts/deploy_aws.sh main       # 배포용 브랜치
# 최초 1회(스키마 + 시드)는 이 스크립트가 아니라 setup_all 을 따로 돌린다 — docker-compose.aws.yml 맨 위 주석 참고.
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH="${1:-develop}"
COMPOSE="docker compose -f docker-compose.aws.yml"

[ -f .env ] || { echo ".env 가 없습니다. deploy/aws.env.example 을 복사해 값을 채우세요."; exit 1; }
grep -q '^JWT_SECRET=.\+' .env || { echo ".env 의 JWT_SECRET 이 비어 있습니다."; exit 1; }

echo "== 코드 받기 ($BRANCH) =="
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
echo "커밋: $(git log --oneline -1)"

echo "== 빌드 =="
$COMPOSE build

echo "== 스키마 마이그레이션(새 파일만 적용) =="
$COMPOSE run --rm api python db/migrate.py up

echo "== 기동 =="
$COMPOSE up -d

echo "== 헬스체크 =="
for i in $(seq 1 30); do
  if curl -fsS http://localhost/health >/dev/null 2>&1; then
    echo "정상: $(curl -fsS http://localhost/health)"
    $COMPOSE ps
    exit 0
  fi
  sleep 2
done
echo "헬스체크 실패 — 로그: $COMPOSE logs --tail=100 api"
$COMPOSE logs --tail=50 api || true
exit 1

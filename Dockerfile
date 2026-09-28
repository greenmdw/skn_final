# TrueFit API + React 프론트(web/) — 같은 오리진에서 서빙(src/api.py 가 web/dist 를 마운트).

# 1) React 앱 빌드 — 결과물(web/dist)만 다음 단계로 가져간다.
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2) API 서버
FROM python:3.11-slim

WORKDIR /app

# psycopg[binary]·argon2-cffi 등은 보통 wheel로 설치돼 별도 빌드 도구가 필요 없다.
# wheel이 없는 아키텍처라 실패하면 여기에 build-essential을 추가한다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/
COPY data/ ./data/
COPY db/ ./db/
COPY main.py .
COPY --from=web /web/dist ./web/dist

# 이미지에는 새 React 앱만 들어 있다 — 빌드가 빠지면 옛 화면으로 조용히 넘어가지 않고 시작 시 오류로 멈춘다.
ENV TRUEFIT_FRONTEND=spa

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

WORKDIR /app

# 의존성: requirements.txt 는 uv export 결과(사설 인덱스 핀 포함)라 공용 PyPI에서 재현이 안 되므로
# pyproject.toml 의 느슨한 핀과 동일한 목록을 명시적으로 설치한다.
RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.29" \
    "pydantic>=2.6" \
    "python-dotenv>=1.0" \
    "sqlalchemy>=2.0" \
    "openai>=1.50"

COPY app/ ./app/
COPY static/ ./static/
# app/seed_data/ 안에 시드 CSV가 포함되어 함께 복사됨 (POST /api/dev/seed 용)

# data/(SQLite·로그), reports/ 는 실행 시 자동 생성됨 (store.py / report.py 가 mkdir(exist_ok=True))
# 영속화가 필요하면 compose 에서 named volume 으로 마운트한다.

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# 테스트 현황 (2026-09-22)

저장소 루트에서 실행한다. `tests/conftest.py`가 고유한 테스트 DB를 만들고,
현재 baseline 4개와 전체 시드를 적용한 다음 세션 종료 시 DB를 삭제한다.
개발 DB `truefit`에는 연결하지 않는다.

```bash
docker compose up -d db
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 uv run pytest -q -rs
```

전체 실행 결과: **790 passed, 4 skipped, 7 xfailed** (38.64초).
Starlette/AnyIO의 외부 의존성 deprecation warning 1건이 있다.

필수 입력은 `data/parts_list_modify.xlsx`와 `data/peripherals/`의
`mouse_processed.csv`, `monitor_processed.csv`, `speaker_processed.csv`,
`keyboard_processed.csv`다. 누락·DB 준비 실패는 오류로 처리한다.

## 현재 DB 계약과 테스트 격리

- baseline은 `0000_schema.sql`부터 `0003_triggers.sql`까지 정확히 4개다.
- `test_schema_reduction.py`는 실제 DB의 테이블 51개를 이름으로 비교하고,
  제거된 구조의 부재, JSON 저장 컬럼 타입·기본값·NULL 제약,
  마이그레이션 체크섬과 시드 재실행 멱등성을 검증한다.
- 인증 HTTP 테스트의 `TRUNCATE identity.app_user CASCADE`를 제거했다.
  이 명령은 현재 외래 키 관계를 따라 리뷰 시드까지 지워 뒤따르는 멱등성 검사를 깨뜨렸다.
  인증 데이터도 세션 종료 시 테스트 DB와 함께 정리한다.
- 사전 준비한 DB를 직접 지정할 때는 고정 테스트 이메일이 남아 있지 않은 새 테스트 DB를 사용한다.
- `TRUEFIT_REQUIRE_TEST_DB=1`에서는 개발 DB 보호로 차단된 접속을 skip으로 바꾸지 않는다.

## 알려진 인증 결함 — strict xfail 1건

아래 항목은 정상 동작으로 인정하지 않는다. 기존 보안 기대를 유지하면서
정확히 알려진 assertion에서만 `KnownAuthGap`을 발생시킨다.
다른 assertion이나 DB·SQL 오류는 그대로 실패한다.
구현 후 통과하면 strict XPASS로 실패하므로 xfail 표시를 제거해야 한다.

| 추적 ID | 미구현·결함 | 테스트 수 |
|---|---|---:|
| AUTH-01 | 이메일 사용 가능 확인 요청 제한 없음(데모 범위 보류, `routers/auth.py` TODO §A-4) | 1 |

### 해결된 결함 (xfail 표시 제거)

| 추적 ID | 해결 |
|---|---|
| AUTH-02 | `auth_service.login()`이 판정과 실패·성공 기록을 전용 트랜잭션 하나로 묶어 먼저 커밋한 뒤 예외를 던진다. |
| AUTH-03 | JWT `iat`를 초 단위로 버리지 않고 float로 두고 경계를 `<=`로 비교한다. 발급 토큰은 DB가 기록한 `password_updated_at`보다 뒤 `iat`를 보장한다(앱·DB 시계 차이로 방금 발급한 토큰이 무효화되지 않게). `jti`로 같은 시각 발급 토큰도 서로 다르다. |
| AUTH-04 | 로그인 판정 조회를 `SELECT ... FOR UPDATE`(`get_for_login_locked`)로 바꿔 동시 비밀번호 변경 뒤에 서게 했다. 이 잠금은 `login()` 전용 커넥션에서만 잡고 바로 커밋해 푼다. |
| AUTH-05 | 탈퇴 시 `terms_version`·`terms_agreed_at`(`app_user_terms_pair_check`로 세트)·`privacy_agreed_at`·`marketing_agreed_at`을 모두 지운다. |

## 선택 의존성과 데이터

`pandas`가 없으면 리뷰 분석 테스트 모듈 2개가 skip된다.
실행하려면 `uv sync --group review-analysis --group test`로 분석 의존성을 준비한다.
`data/amazon23/pcparts_product_risk.json`이 없으면 해당 파일을 직접 읽는 테스트 2개가 skip된다.
이 파일은 별도 전달 데이터다. 필수 DB 테스트의 skip과 구별해야 한다.

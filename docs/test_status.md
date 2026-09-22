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

## 알려진 인증 결함 — strict xfail 7건

아래 항목은 정상 동작으로 인정하지 않는다. 기존 보안 기대를 유지하면서
정확히 알려진 assertion에서만 `KnownAuthGap`을 발생시킨다.
다른 assertion이나 DB·SQL 오류는 그대로 실패한다.
구현 후 통과하면 strict XPASS로 실패하므로 xfail 표시를 제거해야 한다.

| 추적 ID | 미구현·결함 | 테스트 수 |
|---|---|---:|
| AUTH-01 | 이메일 사용 가능 확인 요청 제한 없음 | 1 |
| AUTH-02 | 로그인 실패 예외가 실패 횟수 갱신까지 롤백하여 계정 잠금 불가 | 2 |
| AUTH-03 | 초 단위 JWT가 같은 초에 변경된 비밀번호의 이전 토큰을 허용 | 2 |
| AUTH-04 | 로그인 비밀번호 조회에 행 잠금이 없어 동시 변경 시 이전 해시 사용 가능 | 1 |
| AUTH-05 | 탈퇴 시 이용약관·개인정보·마케팅 동의 시각 미삭제 | 1 |

탈퇴의 계정 익명화·비밀번호 삭제·토큰 거절 검증은 일반 통과 테스트로 유지하고,
동의 시각 삭제만 별도 xfail로 분리했다. 애플리케이션 인증 코드는 이번 작업에서 변경하지 않았다.

## 선택 의존성과 데이터

`pandas`가 없으면 리뷰 분석 테스트 모듈 2개가 skip된다.
실행하려면 `uv sync --group review-analysis --group test`로 분석 의존성을 준비한다.
`data/amazon23/pcparts_product_risk.json`이 없으면 해당 파일을 직접 읽는 테스트 2개가 skip된다.
이 파일은 별도 전달 데이터다. 필수 DB 테스트의 skip과 구별해야 한다.

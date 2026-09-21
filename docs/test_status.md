# 테스트 현황 (2026-09-21, 브랜치 `pc-catalog-engine`)

```
TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test uv run pytest -q
→ 747 passed, 7 failed, 6 skipped  (약 30초, 새 DB에 `db/setup_all.py`로 `computer`만 시드한 경우)
```

재현 절차는 [pc_pipeline_quickstart.md](pc_pipeline_quickstart.md).
(`data/amazon23/pcparts_product_risk.json`이 없으면 리뷰 원본을 읽는 2건이 skip 된다.)

같은 날 유아용품과 영어 화면·달러 입력을 제거하면서 관련 테스트(baby 26건 실패 포함, 영어·달러 테스트)를 함께 지웠다.
PC 파이프라인 테스트(엔진·서비스·세션·확정·업그레이드·파이프라인 스모크)는 실패가 없다. `scripts/e2e_smoke.py`는 39/39 통과.

## 인증 강화 (7건) — 후순위

`test_password_auth_http.py` — 실제 PostgreSQL + FastAPI로 인증 동작을 검사하는 테스트가 **기대한 보안 동작이 아직 없다**:

| 테스트 | 기대 동작 | 실제 |
|---|---|---|
| `au01_email_availability_is_rate_limited` | 이메일 사용 가능 확인을 반복 호출하면 429 | 계속 200 |
| `au03_five_wrong_passwords_then_lock_then_expiry` | 5번째 실패에서 `locked_until` 설정 | 설정 안 됨 |
| `au03_concurrent_failures_do_not_lose_increments` | 동시 실패도 5번째에서 잠금 | 잠금 안 됨 |
| `au04_password_change_invalidates_old_jwt_immediately` | 비밀번호 변경 즉시 옛 토큰 401 | 200 |
| `au04_login_blocked_by_concurrent_password_change…` | 동시 변경 중 로그인은 새 비밀번호 기준 | 옛 비밀번호로 200 |
| `au06_withdraw_anonymizes_and_invalidates_all_tokens` | 탈퇴 시 동의 시각 삭제 | 시각이 남음 |
| `d6_iat_boundary_rejects_token_at_password_change…` | 비밀번호 변경 시각 이전 토큰 거절 | `/auth/me` 200 (초 경계에 따라 통과하기도 함) |

가입·로그인·로그아웃·세션 병합·확정은 통과한다(스모크에서 가입 후 확정까지 확인). 실제 서비스 전에는 이 항목을 해결해야 한다.

## 이전 정리에서 테스트를 현재 코드에 맞춘 것 (참고)

- `test_review_trace`: 이름·시그니처가 바뀐 함수 호출을 현재 API에 맞춤.
- `test_feedback_events`: 재확정은 409가 아니라 같은 리포트를 돌려주는 동작(멱등)에 맞춤.
- `test_schema_reduction`: develop 이후 이 브랜치가 더한 마이그레이션 0014~0016과 표 13개를 골든에 반영.
- `test_password_auth_http`: 고정 이메일 때문에 같은 DB에서 두 번째 실행부터 깨지던 것 — 일회용 DB에서만 사용자 표를 비우고 시작.

기능 결함으로 고친 것: 선택 0개 확정 허용(`list_service.confirm`), 확정 때 붙인 이름이 리포트에 나오게(`plan_repo.confirm_revision`).

# 테스트 현황 (2026-09-21, 브랜치 `pc-catalog-engine`)

```
TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test uv run pytest -q
→ 898 passed, 34 failed, 6 skipped, 1 xfailed  (약 55초, 같은 DB에서 반복 실행해도 동일)
```

재현 절차는 [pc_pipeline_quickstart.md](pc_pipeline_quickstart.md). 아래 분류는 전체 실행 결과를 파일별로 나눈 것이다.
(위 숫자는 `data/amazon23/pcparts_product_risk.json`이 있을 때다. 없는 새 체크아웃은 passed 896 · skipped 8 — 리뷰 원본을 읽는 2건이 skip.)

## 요약

| 분류 | 건수 | PC 파이프라인 영향 | 조치 |
|---|---|---|---|
| **A. 유아용품(baby) — 범위 밖** | 26 | 없음 | 이번 공유 범위 밖. 참고 구현으로 남김 |
| **B. 인증 강화** | 7 | 없음(가입·로그인·확정은 통과) | 후순위 |
| **C. 테스트 순서 의존** | 1 | 없음 | 단독 실행 시 통과. 격리 정리는 후순위 |
| 합계 | 34 | | |

**PC 파이프라인 관련 테스트(엔진·서비스·세션·확정·업그레이드·파이프라인 스모크)는 실패가 없다.**

## A. 유아용품 — 범위 밖 (26건)

| 파일 | 건수 | 증상 |
|---|---|---|
| `test_baby_verification.py` | 19 | 판정이 `pass`여야 하는데 `unknown`(품목별 `pass_fixture` 14 + 리콜·월령·입력 누락·근거 4~5) |
| `test_baby_recommendation_http.py` | 6 | 유아 추천 HTTP 흐름(소유 품목 미청구, 교체 위조 거절, 수량 수정, 대안·교체 합계, 노출 이벤트, 확정) |
| `test_baby_reviews_http.py` | 1 | 리뷰 요약이 가져온 분석을 반영하는지 |

- 원인은 조사하지 않았다. `unknown`이 대부분이라 유아 설명서 검색 인덱스(`BABY_SEARCH_PROVIDER=local-file`,
  `scripts/rag_manual.py ingest`) 준비 여부가 의심되지만 **확인 전 추정**이다.
- 이 브랜치의 PC 변경(엔진·후보 로더·세션 질문)과 유아 경로는 코드가 갈라져 있다. 유아 실패가 PC 변경 때문인지
  아닌지는 `main`/`develop` 기준으로 같은 테스트를 돌려 비교해야 확정된다(미수행).

## B. 인증 강화 (7건) — 후순위

`test_password_auth_http.py` — 실제 PostgreSQL + FastAPI로 인증 동작을 검사하는 테스트가 **기대한 보안 동작이 아직 없다**:

| 테스트 | 기대 동작 | 실제 |
|---|---|---|
| `au01_email_availability_is_rate_limited` | 이메일 사용 가능 확인을 반복 호출하면 429 | 계속 200 |
| `au03_five_wrong_passwords_then_lock_then_expiry` | 5번째 실패에서 `locked_until` 설정 | 설정 안 됨 |
| `au03_concurrent_failures_do_not_lose_increments` | 동시 실패도 5번째에서 잠금 | 잠금 안 됨 |
| `au04_password_change_invalidates_old_jwt_immediately` | 비밀번호 변경 즉시 옛 토큰 401 | 200 |
| `au04_login_blocked_by_concurrent_password_change…` | 동시 변경 중 로그인은 새 비밀번호 기준 | 옛 비밀번호로 200 |
| `au06_withdraw_anonymizes_and_invalidates_all_tokens` | 탈퇴 시 동의 시각 삭제 | 시각이 남음 |
| `d6_iat_boundary_rejects_token_at_password_change…` | 비밀번호 변경 시각 이전 토큰 거절 | `/auth/me` 200 |

가입·로그인·로그아웃·세션 병합·확정은 통과한다(스모크에서 가입 후 확정까지 확인). 실제 서비스 전에는 이 7건을 해결해야 한다.

## C. 테스트 순서 의존 (1건)

`test_rag_postgres.py::test_conflicting_reviewed_conditions_do_not_pass` — 단독으로 돌리면 25건 모두 통과하지만 전체 실행에서는
`assert 227 == 3`으로 실패한다. 앞선 테스트가 같은 DB에 남긴 행을 세기 때문이다(테스트 간 격리 문제, 제품 결함 아님).

## 이번 정리에서 고친 것 (참고)

기존 실패 50건 중 16건은 **테스트를 현재 코드에 맞춰** 고쳤다(코드 쪽 기대값 기준):

- `test_localized_input`, `test_review_trace`: 이름·시그니처가 바뀐 함수 호출을 현재 API(`_parse_swap_request`,
  `explanation_text_with_caveats(summary, caveats)`)에 맞춤.
- `test_condition_locale`: 영어 문구를 현재 문구("What will you mainly use it for?", "Office", "New build")에 맞춤.
  조건 에이전트의 영어 프롬프트 테스트는 미구현 기능이라 `xfail(strict)`로 표시(구현하면 XPASS로 알려 준다).
- `test_feedback_events`: 재확정은 409가 아니라 같은 리포트를 돌려주는 동작(멱등)에 맞춤.
- `test_schema_reduction`: develop 이후 이 브랜치가 더한 마이그레이션 0014~0016과 표 13개를 골든에 반영.
- `test_password_auth_http`: 고정 이메일 때문에 같은 DB에서 두 번째 실행부터 깨지던 것 — 일회용 DB에서만 사용자 표를 비우고 시작.

기능 결함으로 고친 것: 선택 0개 확정 허용(`list_service.confirm`), 영어 로케일에서 다음 질문이 한국어로 나오던 것
(`session_service._next_question`), 컴퓨터·유아 필드의 영어 라벨(`label_en`) 누락.

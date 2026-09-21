# TrueFit Frontend

React + TypeScript + Vite 기반의 프론트엔드입니다. 1~5번 개선 사항을 포함합니다.

## 실행

Node.js 22.12 이상 환경에서 압축을 해제한 프로젝트 폴더에서 실행합니다.

```sh
npm ci
npm run dev
```

```sh
npm run build
npm run lint
```

## 연결된 흐름

- 새 PC: 채팅으로 조건 입력 → PC 구성 패널에서 예산 적용 → 샘플 분석 → 부품·총액 확인 → 이름·구매일·목표금액·메모 입력 → 리스트 확정 → 리포트
- 업그레이드: 질문·예산 입력 → 부품 직접 수정 → 샘플 변경안 선택 → 플래너 → 선택한 변경 부품만 확정
- 플래너 상단의 메뉴에서 저장 목록 열기 → 구성 복원 / 리포트 조회 / 삭제
- 새로고침해도 작성 중인 조건과 구성·책상 치수를 복원합니다. 분석 도중 새로고침하면 조건 확인 단계로 돌아갑니다. 채팅 대화 이력 전체는 보관하지 않습니다.

## 저장 방식

이 브라우저의 localStorage에 임시 저장합니다. 실제 계정 저장과 기기 간 동기화는 아직 없습니다. 동일한 주소(호스트·포트)의 같은 브라우저에서 다시 열어야 합니다. 브라우저 데이터를 삭제하면 저장 내용도 사라집니다.

- `truefit.workspace.v1`: 현재 작성 중인 구성·조건·책상 치수
- `truefit.setups.v1`: 확정한 구성 전체와 구매 계획
- `/plan/report/:setupId`: 해당 브라우저에 저장된 리포트를 ID로 조회

저장 공간 부족이나 접근 오류가 발생하면 저장 성공으로 처리하지 않고 오류를 표시합니다.

## API 계층 (`src/api/`)

화면과 상태 코드는 서버와 관련된 일을 `src/api`의 `api` 객체로만 요청합니다. 기본은 백엔드에 연결된 `httpApi`(`src/api/http/`)이고,
`VITE_API_MODE=mock`이면 브라우저 안에서 동작하는 목업(`src/api/mock/`)을 씁니다.

| 함수 | 기본(백엔드) | 목업 |
|---|---|---|
| `api.auth.login / signup` | 연결 — `POST /auth/login`, `/auth/signup` (httpOnly 쿠키 세션) | 항상 성공 |
| `api.plans.recommend` | 연결 — 세션 생성 → 조건 입력 → `POST /recommend` → 결과 폴링 → 화면 구성으로 변환 | 고정 샘플 부품 |
| `api.setups.list / save / remove` | 연결 — `GET /lists`·`/report`, `POST /lists/{id}/confirm`(로그인 필요), `DELETE /lists/{id}` | localStorage |
| `api.chat.reply / reviewReply` | **목업 그대로**(백엔드에 해당 API 없음) | 정해진 문장 |
| `api.checks.suggestUpgrade` | **목업 그대로**(백엔드에 해당 API 없음) | 고정 GPU 제안 |

- 계약(요청·응답 타입과 `Api` 인터페이스)은 `src/api/types.ts`, 백엔드 응답 타입은 `src/api/http/wire.ts`, 화면 모델과의 변환은 `src/api/http/mapping.ts`입니다.
- 실패는 `ApiError`로 던지면 화면이 `error.message`를 사용자에게 보여줍니다. 서버의 오류 봉투(`{"error":{"code","message"}}`)를 그대로 옮깁니다.
- 확정은 로그인이 필요합니다. 비로그인이면 `AUTH_REQUIRED`로 거절되고, 확정 화면이 로그인 버튼(`/login?next=/plan/confirm`)을 보입니다.
- 서버에 필드가 없는 화면 전용 값(책상 치수·점검 초안·입력한 조건 문장)은 이 브라우저의 `truefit.setup-extras.v1`에 보관합니다. 작성 중인 조건·구성은 `truefit.workspace.v1`(`src/state/storage.ts`)입니다.
- `src/data/`의 `checkDraftSeed`(점검 화면의 초기 부품 목록), `assemblyGuide`(리포트 조립 가이드), `termsContent`(약관 본문)는 아직 API를 거치지 않는 정적 샘플·문구입니다.

## 개발과 검사

```sh
npm run dev      # 5173 — API 경로(/auth, /session, /lists …)는 vite가 백엔드(BACKEND_URL, 기본 http://127.0.0.1:8000)로 넘깁니다
npm run build    # 타입 검사 + 빌드(dist) — 백엔드(src/frontend_serving.py)가 dist를 서빙합니다
npm run lint
npm test         # 변환 로직 + 실제 백엔드 응답을 캡처한 계약 테스트 (tests/fixtures/backend_flow.json, 새 의존성 없음)
```

## 샘플 데이터 범위

기본(백엔드 연결) 모드에서 추천 구성·가격·추천 이유·리뷰 건수는 서버 응답입니다. 아직 샘플인 것: 채팅 후속 답변, 견적 점검 화면(`/check`)의 부품 목록과 업그레이드 제안, 조립 가이드 문장, 약관 본문.
`VITE_API_MODE=mock`에서는 모든 응답이 고정 샘플이며, 신규 구성의 '기타 부품 예산 (미선정)' 250,000원은 원래 예산 요약에만 있던 항목을 공통 목록에 포함한 것입니다(제품을 확정한 가격이 아닙니다).

## 브라우저 검사(Playwright) — 이 사본에는 검사 스크립트가 없습니다

원본 프로젝트의 `tests/frontend-flow.cjs` 등 Playwright 스크립트는 이 저장소로 옮겨지지 않았습니다(README 원문은 그 스크립트를 가정합니다).
지금 있는 자동 검사는 위 `npm test`(Node 내장 러너)뿐입니다.

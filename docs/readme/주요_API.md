# 주요 API

TrueFit FastAPI 서버의 주요 엔드포인트입니다. 모든 경로는 서버 루트 기준이며(접두사 없음), 화면과 같은 주소에서 제공됩니다.

전체 목록과 요청·응답 형식은 서버 실행 후 http://127.0.0.1:8000/docs 에서 볼 수 있습니다.

| 영역 | 주요 엔드포인트 |
|---|---|
| 인증 `/auth` | `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`, `GET·PATCH /auth/me`, `POST /auth/withdraw` |
| 조건 대화·본체 추천 `/session` | `POST /session`(대화 시작), `POST /session/{list_id}/message`(조건 대화), `POST /session/{list_id}/recommend`(추천 실행), `GET /session/{list_id}/result`, `GET /session/{list_id}/result/status`(결과 폴링) |
| 결과 화면 `/session` | `POST /session/{list_id}/result-message`(결과 대화), `GET /session/{list_id}/items/{item_id}/alternatives`(대안 후보), `POST /session/{list_id}/items/{item_id}/swap`(교체) |
| 주변기기 `/session`, `/peripherals` | `POST /session/{list_id}/peripherals/chat`, `POST /session/{list_id}/peripherals/recommend`, `POST /peripherals/interpret`(문장 해석), `GET /peripherals/catalog/search` |
| 견적 목록·확정·리포트 `/lists` | `GET /lists`, `POST /lists/{list_id}/confirm`, `GET /lists/{list_id}/report`, `DELETE /lists/{list_id}/reports/{revision_no}`, `GET /lists/{list_id}/history` |
| 받은 견적 점검 `/pc` | `POST /pc/review-drafts`(사진·텍스트 업로드), `POST /pc/review-drafts/{draft_id}/analysis`, `POST /pc/review-drafts/{draft_id}/live-lookup-batch`(실시간 스펙 검색), `POST /pc/review-drafts/{draft_id}/confirm` |
| 견적 점검 대화 `/pc` | `GET·POST /pc/reviews/{list_id}/messages` |
| 리뷰 `/reviews` | `GET /reviews/summary/{product_key}`(리뷰 요약), `GET /reviews/search`(리뷰 의미 검색) |
| 커뮤니티 `/community`, `/catalog` | `GET·POST /community/posts`, 댓글·좋아요·저장·이미지 업로드, `GET /community/me/notifications`, `GET /catalog/products`(글에 연결할 제품 검색) |
| 마이페이지 `/me` | `GET·PUT·DELETE /me/pc`(내 PC), `GET·PUT·DELETE /me/data/{key}`(사용자별 저장 데이터) |

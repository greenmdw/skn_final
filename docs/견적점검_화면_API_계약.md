# 견적 점검(4.1.2) 화면 기획용 API 계약

2026-09-28. 문동원·이호원 화면 기획 참고용. 아래 예시는 전부 실제로 돌려서 받은 응답이다(합성 데이터
아님) — 다만 카탈로그 가격 몇 개(RAM·GPU 상위 모델)가 비정상적으로 높게 잡혀 있는 걸 확인 중이니, 화면
시안에서 절대 금액 크기 자체에 의미를 두지 말고 **구조**(어떤 필드가 있고 어떤 상태값이 나오는지)만
참고할 것.

현재 백엔드만 끝났고 **화면은 아직 없다.** `/check`, `/check/review` 화면은 "내 PC 업그레이드 점검"용으로
만들어져 있어 재기획 대상이고, 프론트의 `reviewReply`는 여전히 목업이라 이 계약과 연결돼 있지 않다.

## 0. 여정 단계 ↔ API 매핑 (기획서 4.1.2)

| 여정 단계 | 화면 | API |
|---|---|---|
| 2. 견적 올리기 | 견적 업로드 | `POST /pc/owned-parts/preview`(세션 없는 미리보기, 기존 UI-05 재사용 가능) |
| 3. 인식 결과 확인 | 견적 구성 표 | `POST /pc/reviews`(확정해서 저장), 이후 고치면 `PUT /pc/reviews/{list_id}` |
| 4. 비교 분석 | 비교 분석 결과 | `GET /pc/reviews/{list_id}`의 `compat`·`prices`·`balance`·`compare` |
| 5. 부품 비교 | 부품 비교(UI-06b) | `GET /pc/reviews/{list_id}/parts/{slot}/compare` |
| 6. 되묻기 | 비교 분석 + 채팅 | `POST/GET /pc/reviews/{list_id}/messages` |
| 7. 대안 적용 | 비교 분석 → 장바구니 | `POST /pc/reviews/{list_id}/apply` → 새 `list_id`로 `/session/{id}` 흐름 이어감 |

## 1. 공통 규칙

- **인증**: 로그인 없이 쓸 수 있다(게스트). 첫 호출(`POST /pc/reviews`)이 브라우저 쿠키(`truefit_guest`)를
  세팅하면, 이후 요청은 그 쿠키만 있으면 같은 사람으로 인식된다. 기존 `/session` 흐름과 동일한 방식.
- **소유자만**: 다른 사람(또는 쿠키 없는 요청)이 `list_id`를 알아도 `404`가 난다 — "이 목록에는 견적 점검
  결과가 없습니다" 류의 메시지. 화면에서 "권한 없음"이 아니라 "찾을 수 없음"으로 처리해야 한다.
- **저장은 무상태 미리보기와 별개**: `/pc/owned-parts/preview`는 아무것도 저장 안 하는 순수 미리보기다.
  `/pc/reviews`부터는 세션이 생기고 사이드바 "받은 견적 점검"에 목록으로 나타난다.
- **분석 실패는 전체 실패가 아니다**: `prices`·`balance`·`compare`는 각각 독립적으로 `available: false` +
  `reason`을 줄 수 있다(조건 없음, 가격 없음, 예산 정보 없음 등). 화면은 각 카드 단위로 "이 부분은 준비
  중/정보 부족"을 따로 그려야지, 하나가 비었다고 전체를 에러 화면으로 처리하면 안 된다.

## 2. `POST /pc/reviews` — 견적 저장 + 전체 분석

견적(직접 입력한 슬롯값·붙여넣은 텍스트·캡처 이미지 중 하나 이상)과 조건을 함께 보내면, 매칭·호환·가격·
균형·추천비교를 한 번에 계산해 새 세션에 저장한다.

**요청**
```json
{
  "current_specs": {
    "CPU": "라이젠5-5세대 7600 249,000원",
    "GPU": "지포스 RTX 4060 Ti 8GB 560,000원",
    "RAM": "삼성전자 DDR5-5600 (16GB) x2 120,000원",
    "메인보드": "MSI PRO B650M-P 155,000원",
    "저장장치": "삼성전자 990 PRO 1TB 189,000원",
    "파워": "마이크로닉스 Classic II 풀체인지 700W 89,000원"
  },
  "text": null,
  "image_data_url": null,
  "conditions": {
    "purpose": "game", "resolution": "QHD_165", "priority": "value", "budget_max": 1500000
  }
}
```
- `current_specs`·`text`·`image_data_url` 중 하나만 있어도 된다(`text`/이미지가 있으면 서버가 슬롯별로
  추출). `conditions`는 전부 선택 — 안 주면 `balance`·`compare`가 `available: false`로 나온다.
- `conditions.priority`는 CHK-07(우리 추천 비교)에만 쓰인다. 안 주면 "추천엔진 기본 가중치로 만들었다"는
  안내가 `compare.notes`에 붙는다.

**응답 201** (실제 예시, 필드가 많아 조각내서 설명)

```json
{
  "list_id": "ca803b17-09b4-4d56-a1df-c4fc97ffc372",
  "version": 1,
  "input": {
    "current_specs": { "...": "요청과 동일(슬롯 이름 정규화됨)" },
    "conditions": { "purpose": "game", "resolution": "QHD_165", "priority": "value", "budget_max": 1500000 },
    "input_hash": "3a5fde9e..."
  },
  "parts": [ /* 2.1 절 */ ],
  "compat": { /* 2.2 절 */ },
  "prices": { /* 2.3 절 */ },
  "balance": { /* 2.4 절 */ },
  "compare": { /* 2.5 절 */ },
  "computed_at": "2026-09-27T23:56:17+00:00"
}
```
`prices`·`balance`·`compare`는 `null`일 수 있다(이 세 기능이 생기기 전에 저장된 오래된 결과를 조회할 때만).
화면은 `null`을 "정보 없음"으로 다뤄야지 에러로 다루면 안 된다.

### 2.1 `parts` — 인식·매칭 표 (UI-05, 기존 것과 동일)

```json
[
  {"part": "CPU", "original": "라이젠5-5세대 7600 249,000원", "matched": "AMD Ryzen 5 7600",
   "matched_note": "AM5 · DDR5", "state": "ok"},
  {"part": "메인보드", "original": "MSI PRO B650M-P 155,000원", "matched": "MSI PRO B650M-P",
   "matched_note": "모델명·칩셋 규칙으로 추정 — 소켓: AM5, 메모리 규격: DDR5, 크기: mATX", "state": "warn"},
  {"part": "파워", "original": "마이크로닉스 Classic II 풀체인지 700W 89,000원",
   "matched": "마이크로닉스 Classic II 풀체인지 700W",
   "matched_note": "카탈로그의 'Micronics Classic II 풀체인지 700W ATX 3.1'와 가장 비슷합니다 — 같은 제품인지 확인하세요",
   "state": "warn"}
]
```
- `state`는 `ok`/`warn` 둘뿐이다. **"가장 비슷한 제품"(경고)과 "카탈로그에 확정 매칭"(ok)을 화면에서
  구분해서 보여줘야 한다** — `matched_note` 문구에 "가장 비슷합니다"가 있으면 그 케이스다. 사용자가 실제
  같은 제품인지 확인하라는 뜻이라, 뱃지나 아이콘으로 "확인 필요"를 표시하는 걸 권한다.

### 2.2 `compat` — 호환 검사 (CHK-04)

```json
{
  "checks": [
    {"axis": "socket", "label": "CPU·메인보드 소켓", "state": "ok",
     "detail": "CPU AMD Ryzen 5 7600(AM5) = 메인보드 MSI PRO B650M-P(AM5)"},
    {"axis": "gpu_len", "label": "그래픽카드 길이", "state": "unknown",
     "detail": "GPU 길이: 244 · 케이스 허용 길이: 정보 없음 — 스펙 정보가 부족해 확인하지 못했습니다."},
    {"axis": "cooler_height", "label": "쿨러 높이", "state": "skipped",
     "detail": "견적에 이 검사에 필요한 부품이 없어 확인하지 않았습니다."}
  ],
  "summary": {"ok": 4, "fail": 0, "unknown": 10, "skipped": 2},
  "incompatible": []
}
```
- **상태값 4가지 — 색/문구를 반드시 구분할 것**: `ok`(통과, 초록) / `fail`(**확정된 비호환**, 빨강 —
  `incompatible` 배열에도 그 axis가 들어감) / `unknown`(스펙을 몰라 확인 못 함, 회색 — **비호환이 아니다**,
  "문제 있음"처럼 보이면 안 됨) / `skipped`(이 견적에 해당 부품이 없어 안 봄, 아예 표시 안 해도 됨).
  실측에서 `unknown`이 압도적으로 많이 나온다(카탈로그가 322개뿐이라 흔한 부품도 스펙 매칭이 잘 안 됨) —
  이 비율이 높다고 견적에 문제가 있는 게 아니라는 걸 화면 문구로 분명히 해야 한다.
- `checks` 목록은 항상 15개 축 고정이다(`socket`, `memory`, `motherboard_case`, `gpu_len`,
  `cooler_height`, `cooler_socket`, `bios`, `power`, `psu_form`, `gpu_connector`, `psu_length`,
  `gpu_slots`, `radiator`, `ram_slots`, `ram_speed`, `m2`). `label`은 한글로 이미 붙어 있어 그대로 쓰면 됨.

### 2.3 `prices` — 가격 비교 (CHK-05)

```json
{
  "available": true,
  "rows": [
    {"part": "CPU", "matched": "AMD Ryzen 5 7600", "quoted": 249000, "catalog": 221750,
     "quantity": 1, "diff": 27250, "diff_pct": 12.3, "state": "pricier",
     "detail": "견적 249,000원 · 카탈로그 221,750원 (+27,250원, +12.3%)"},
    {"part": "GPU", "matched": "NVIDIA GeForce RTX 4060 Ti", "quoted": 560000, "catalog": null,
     "quantity": 1, "diff": null, "diff_pct": null, "state": "no_catalog",
     "detail": "용량·구성 변형이 카탈로그와 달라 어느 가격과 비교할지 정할 수 없습니다."},
    {"part": "메인보드", "matched": null, "quoted": 155000, "catalog": null,
     "quantity": 1, "diff": null, "diff_pct": null, "state": "no_catalog",
     "detail": "카탈로그에서 같은 제품을 찾지 못해 비교하지 못했습니다."}
  ],
  "summary": {"compared": 3, "pricier": 1, "cheaper": 2, "similar": 0, "not_compared": 3,
              "quoted_total": 558000, "catalog_total": 959700, "diff": -401700, "diff_pct": -41.9,
              "quote_total_complete": true}
}
```
- `available: false`면 `rows: []`이고 `reason`에 "견적에 가격이 적혀 있지 않아..." 문구가 온다. 이때는
  가격 비교 카드 자체를 숨기거나 "가격을 알려주면 비교해 드려요" 안내로 대체.
- 행의 `state` 5가지: `cheaper`/`similar`/`pricier`(비교됨) vs `no_quote_price`/`no_catalog`(비교 안 됨,
  **회색으로 구분**, `diff`가 항상 `null`). `summary`의 `compared`/`not_compared` 합이 `rows` 길이와 같다.
- `quantity`는 "16GB x2"처럼 한 줄에 여러 개일 때 나온다. 화면에 `quantity > 1`이면 "2개 기준"처럼 표시.
- `summary.quote_total_complete`가 `false`면 일부 부품 가격이 빠진 채로 합계가 과소평가된 것 — 합계 옆에
  "일부 부품 가격 제외" 주석이 필요하다.

### 2.4 `balance` — 용도 대비 균형 (CHK-06)

```json
{
  "available": true,
  "requirement": {"label": "게임 · QHD 165Hz", "purpose": "game", "resolution": "QHD_165",
                  "gpu_tier_min": 7, "cpu_tier_min": 5, "ram_gb_min": 16, "vram_gb_min": 12},
  "rows": [
    {"part": "GPU", "aspect": "VRAM", "state": "short",
     "detail": "GPU VRAM 8GB < 요구 12GB (게임 · QHD 165Hz 기준).", "measured": 8, "target": 12},
    {"part": "저장장치", "aspect": "예산 비중", "state": "excess",
     "detail": "저장장치에 견적 가격의 14%가 쓰였습니다(권장 배분 8%) — 기준보다 많이 쓰였습니다.",
     "measured": 0.139, "target": 0.077}
  ],
  "summary": {"short": 1, "excess": 1, "ok": 5, "unknown": 0},
  "notes": ["성능 등급은 제조사 라인업 기준의 거친 값이라 같은 등급 안의 세대·모델 차이는 구분하지 못합니다."]
}
```
- `available: false`면 대부분 "용도를 알려 주지 않아 판단하지 않았습니다" — 조건 입력을 안 했을 때다.
  화면에서 이 카드에 조건 입력 유도 버튼을 붙이면 좋다.
- `aspect`는 부품마다 다르다(성능 등급/VRAM/용량/예산/예산 비중). 같은 `part`가 여러 행에 나올 수 있다
  (GPU가 "성능 등급" 행과 "VRAM" 행 둘 다 가짐) — 리스트를 `part`로 그룹핑해서 보여주는 걸 권한다.
- `notes`는 **항상 화면에 노출**해야 하는 면책 문구다(등급이 거친 값이라는 점, 조건을 가정했다는 점 등).
  작은 글씨라도 카드 하단에 고정으로 붙일 것.

### 2.5 `compare` — 우리 추천과 비교 (CHK-07)

```json
{
  "available": true,
  "conditions_used": {"purpose": "game", "resolution": "QHD_165", "priority": "value",
                      "budget": 1500000, "budget_source": "condition"},
  "ours": {
    "items": [{"slot": "CPU", "name": "AMD Ryzen 5 7600", "price": 221750, "perf_tier": 6}, "..."],
    "total": 1516348,
    "link_check": {"socket": "ok", "...": "...", "budget": "fail"},
    "incompatible": []
  },
  "rows": [
    {"part": "CPU", "quote": {"name": "AMD Ryzen 5 7600", "price": 249000, "perf_tier": 6,
                              "confirmed": true, "quantity": 1},
     "ours": {"name": "AMD Ryzen 5 7600", "price": 221750, "perf_tier": 6},
     "same_product": true, "price_diff": 27250, "price_diff_pct": 12.3, "price_state": "pricier",
     "tier_diff": 0,
     "detail": "견적과 우리 추천이 같은 제품입니다(AMD Ryzen 5 7600). 견적 249,000원 · 우리 카탈로그 221,750원 (견적 − 카탈로그 +27,250원, +12.3%)"},
    {"part": "케이스", "quote": null,
     "ours": {"name": "다크플래쉬 DLM21 RGB Mesh", "price": 55828},
     "same_product": false, "price_diff": null, "price_diff_pct": null, "price_state": null,
     "detail": "견적에 이 부품이 없습니다. 우리 추천: 다크플래쉬 DLM21 RGB Mesh 55,828원."}
  ],
  "summary": {"our_total": 1516348, "budget": 1500000, "budget_source": "condition",
              "over_budget": true, "same_slots": ["CPU","GPU","RAM","메인보드","저장장치","파워"],
              "quote_total": 1362000, "our_total_same_slots": 1438930, "diff": -76930,
              "diff_pct": -5.3, "same_product": 2, "missing_in_quote": 2},
  "notes": ["우리 추천도 예산 1,500,000원을 넘습니다(합계 1,516,348원) — 이 조건으로는 예산 안의 구성을 찾지 못했습니다.", "..."]
}
```
- `quote`가 `null`인 행(견적에 없는 부품군, 위 "케이스" 예시)은 **우열 판정처럼 보이지 않게** — "견적에 이
  부품이 없다"는 사실 안내로만 표시.
- `same_product: true`인 행은 강조(예: "같은 제품" 뱃지) — 가격 차이만 보여주면 된다.
- `summary.over_budget: true`가 나올 수 있다(**우리 추천도 예산을 넘을 수 있다**). 이때 `notes`에 이유가
  같이 온다. "우리 추천이 항상 예산 안"이라는 전제로 화면을 짜면 안 된다.
- `conditions_used.budget_source`가 `"quote_total"`이면 "예산을 안 알려줘서 견적 합계를 예산으로 썼다"는
  뜻 — 이때는 반드시 그 사실을 화면에 알려야 한다(안 그러면 사용자가 "왜 이 예산으로 비교했지" 오해).

## 3. `PUT /pc/reviews/{list_id}` — 인식 결과 수정 후 재분석

요청·응답 형태는 `POST /pc/reviews`와 동일. 차이:
- `conditions`를 **아예 안 보내면**(필드 자체 생략) 이전 조건이 유지된다.
- `conditions: {}`(빈 객체)를 보내면 조건이 지워지고 `balance`/`compare`가 `available: false`로 바뀐다.
- 이전 분석 결과는 버려지고 새로 계산된 값으로 완전히 교체된다(버전 번호만 올라감).

## 4. `GET /pc/reviews/{list_id}` — 저장된 분석 조회

응답은 `POST`와 완전히 동일한 형태. 새로고침·재방문 시 이 API로 마지막 저장 상태를 그대로 그리면 된다.

## 5. `GET /pc/reviews/{list_id}/parts/{slot}/compare` — 부품 비교 (CHK-10, UI-06b)

쿼리 파라미터: `target`(제품 이름, 최대 4개 반복 가능) 또는 `direction`(`cheaper`|`better`). 아무것도 안
주면 가격이 가까운 순으로 최대 3개.

```
GET /pc/reviews/{list_id}/parts/GPU/compare?direction=cheaper
```
```json
{
  "slot": "GPU",
  "baseline": {"name": "NVIDIA GeForce RTX 4060 Ti", "price": 560000, "perf_tier": 7,
              "confirmed": true, "specs_known": true,
              "review": {"total_count": null, "headline": "리뷰 데이터가 없어요.", "points": [], "reason": "unmapped"}},
  "candidates": [
    {"name": "NVIDIA GeForce RTX 3060 (12GB)", "price": 498990, "price_delta": -61010, "perf_tier": 5,
     "specs": [
       {"key": "perf_tier", "label": "성능 등급", "unit": "", "baseline": 7, "candidate": 5, "diff": -2},
       {"key": "vram_gb", "label": "VRAM", "unit": "GB", "baseline": 8, "candidate": 12, "diff": 4},
       {"key": "power_connector", "label": "전원 커넥터", "unit": "", "baseline": "1× 8-pin", "candidate": "1× 8-pin", "diff": null}
     ],
     "incompatible": [], "compat_changes": [],
     "review": {"total_count": null, "headline": "리뷰 데이터가 없어요.", "points": [], "reason": "unmapped"}}
  ],
  "unmatched_targets": [],
  "note": null
}
```
- **`NVIDIA GeForce RTX 3060 (12GB)`와 `NVIDIA GeForce RTX 3060 12GB`처럼 실제로 거의 같은 이름의 제품이
  카탈로그에 중복으로 들어 있는 걸 확인했다(데이터 이슈, API 정상 동작).** 화면에서 이름이 비슷한 후보가
  중복으로 보일 수 있다는 점을 감안해야 한다.
- `specs` 배열은 부품군마다 다른 스펙 키가 온다(GPU는 성능 등급·VRAM·전력·길이·두께·커넥터, CPU는
  소켓·전력·계열 등) — 고정된 컬럼 세트로 표를 짜지 말고 `label`을 그대로 헤더로 쓸 것. `diff`가 `null`인
  행(문자열 스펙)은 수치 비교 표시를 하지 않는다.
- `incompatible`이 비어 있지 않으면 **이 후보로 바꾸면 새로 생기는 확정 비호환**이다 — 경고 표시 필수.
  `compat_changes`는 검사 상태가 바뀌는 것(예: "통과 → 확정된 비호환")을 보여준다.
- `review`는 추천 결과 화면과 같은 리뷰 배지다. 지금 카탈로그는 리뷰 데이터가 거의 없어 `headline`이
  "리뷰 데이터가 없어요."로 나오는 경우가 대부분이다 — 리뷰 자료가 채워지기 전까지는 이 필드가 비어
  보이는 게 정상이라는 점을 감안하고 레이아웃을 짜야 한다(빈 카드가 아니라 "정보 없음" 처리).
- `target`으로 직접 고른 제품이 카탈로그에 없으면 `unmatched_targets`에 그 이름이 그대로 담긴다(다른
  제품으로 슬쩍 바뀌지 않는다) — "찾지 못했습니다" 안내 필요.

## 6. `POST /pc/reviews/{list_id}/messages` — 되묻기 채팅 (CHAT-04)

**요청**: `{"text": "CPU 가격 어때?"}` (1~1000자)

**응답**
```json
{
  "reply": "CPU 가격 비교 결과, 견적의 CPU인 AMD Ryzen 5 7600은 249,000원이며, 카탈로그 가격은 221,750원입니다. 따라서 견적이 카탈로그보다 27,250원 비쌉니다.",
  "evidence": ["가격 비교"],
  "via": "agent"
}
```
- `evidence`는 답의 근거가 된 분석 블록 이름이다("호환 검사"/"가격 비교"/"용도 대비 균형"/"우리 추천과
  비교"/"대안 조회"/"부품 비교"/"견적 분석 요약"). **채팅 말풍선에 이 근거 태그를 작은 뱃지로 같이 보여주는
  걸 권한다** — 어떤 계산에서 나온 답인지 사용자가 알 수 있게.
- `via`는 `"agent"`(LLM) 또는 `"rules"`(규칙 경로 — LLM이 꺼져 있거나 실패했을 때). 화면 표시에는 영향
  없어도 되지만, 문제 재현 시 로그 대조에 쓸 수 있어 응답 구조에는 유지해 둘 것.
- **판정하지 않는다**: "이 견적 사도 돼?"처럼 물어도 "좋다/나쁘다"를 답하지 않고 사실만 요약한다. 채팅
  UI 카피에 "AI 판단"처럼 오해할 문구를 넣지 말 것 — "저장된 분석 결과를 바탕으로 답해요" 정도가 맞다.

### 수정 이력 — 여러 부품을 한 문장에 묶어 말할 때의 오류 (2026-09-28 수정 완료)
문서 작성 중 실시간으로 "CPU와 RAM은 견적이 비싸고, 저장장치는 견적이 더 쌉니다"처럼 답변 문장이 **한
문장 안에 부품 두 개 이상을 언급**하면 그중 하나의 방향(비쌈/쌈)이 실제와 다르게 나오는 경우를
확인했다(RAM은 실제로는 더 쌌는데 "비싸다" 쪽에 잘못 묶인 사례). 원인은 검증 장치가 "부품이 하나만
언급된 문장"만 검사하고, 두 개 이상 묶이면 안전하게 건너뛰도록 만들어져 있었던 것 — 그 "안전하게
건너뛰기"가 정작 놓치면 안 되는 오류를 통과시켰다. **같은 날 수정 완료**: "A와 B는 X"는 A·B 모두에
X가 적용된다는 한국어 문법을 이용해, 방향이 하나로만 정해지는 문장은 언급된 모든 부품을 각각
대조하도록 검증을 넓혔다(`src/agent/quote_review_agent.py:price_claims_are_grounded`). 실제 서버로
재현 문장을 다시 넣어 정상 서술로 바뀐 것과, "부품별로 하나씩 다 알려줘" 같은 여러 부품 질문에도
6개 부품 전부 정확히 답하는 것을 확인했다. 화면 설계에는 영향 없음 — 참고용으로 남겨 둔다.

## 7. `GET /pc/reviews/{list_id}/messages` — 대화 복원

```json
{"messages": [
  {"id": "795e0bbc-...", "role": "user", "text": "가격이 비싼 편이야?", "created_at": "2026-09-28T08:56:26.391036+09:00"},
  {"id": "df90d25a-...", "role": "assistant", "text": "...", "created_at": "2026-09-28T08:56:26.391036+09:00"}
]}
```
시간순 배열. 저장한 견적을 다시 열 때 이 API로 통째로 불러와 채팅창에 순서대로 렌더링하면 된다 —
페이지네이션 없음(전체 이력을 한 번에 준다).

## 8. `POST /pc/reviews/{list_id}/apply` — 대안 적용 (CHK-08)

**요청**: `{"slots": ["GPU"]}` (업그레이드할 부품군 1~8개)

**응답 201**
```json
{"list_id": "31b50d9e-a1e4-4221-a83a-c030baf26d27", "slots": ["GPU"], "missing": [], "run_id": "781e14b7-..."}
```
- **이 API는 사용자가 비교 화면에서 본 특정 후보를 그대로 담아주지 않는다.** "이 부품군을 다시
  추천받는다"는 뜻이라, 결과가 사용자가 기대한 제품과 다를 수 있다. 버튼 문구를 "이 대안 적용"보다는
  "이 부품 다시 추천받기"에 가깝게 잡는 걸 권한다.
- `missing`이 비어 있지 않으면(예: `["priority"]`) **추천이 아직 시작되지 않은 것**이다. 이때는 새
  `list_id`로 기존 조건 대화 화면(`/session/{list_id}` 흐름)을 이어서 그 항목을 채우게 유도해야 한다.
- `missing`이 비어 있으면 `run_id`가 오고, 추천이 이미 시작됐다 — 새 `list_id`로
  `GET /session/{list_id}/result`를 폴링해서 기존 추천 결과 화면 컴포넌트를 그대로 재사용하면 된다.
  **즉 "대안 적용"의 최종 도착지는 기존 03 결과 화면이다 — 새 화면을 만들 필요가 없다.**

## 9. 상태값 사전 (색상·문구 설계용)

| 값 | 뜻 | 화면 색 권장 |
|---|---|---|
| `ok` | 통과 / 확정 매칭 | 초록 |
| `fail` | **확정된 비호환** | 빨강 |
| `unknown` | 스펙을 몰라 확인 못 함(비호환 아님) | 회색 |
| `skipped` | 이 검사 대상 부품이 없음 | 표시 생략 가능 |
| `warn` (매칭) | 카탈로그 미확정(추정/가장 비슷함/스펙 없음) | 노랑 |
| `cheaper`/`similar`/`pricier` | 가격 비교 결과 | 파랑/회색/주황 |
| `no_quote_price`/`no_catalog` | 가격 비교 불가 | 회색, "비교 안 됨"으로 표시 |
| `short`/`excess`/`ok`(균형) | 부족/과함/충족 | 빨강/주황/초록 |
| `available: false` | 그 분석 블록 전체를 못 만듦(`reason` 참고) | 카드 자체를 "정보 부족" 상태로 |

## 10. 참고 자료
- 백엔드 구현: `src/routers/pc_check.py`, `src/services/quote_*.py`
- 스키마 원본: `src/schemas.py`의 `Quote*`, `OwnedPartsPreview*` 클래스
- 기획 원문: 9/30 기획서 5.3절(CHK-01~10), 4.1.2절

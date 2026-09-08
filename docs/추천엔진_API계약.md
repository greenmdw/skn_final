# 추천 엔진 API 계약 (화면 담당자용)

> 2026-09-07 확정 도메인(PC 부품) · 브랜치 `feat/recommend-engine` · 백엔드만.
> **화면 구성은 이 문서가 정하지 않는다.** 여기 있는 것은 응답에 무엇이 들어
> 있는지뿐이고, 어떻게 보일지는 화면 담당자의 몫이다.

엔드포인트 하나다. 스키마 원본은 `app/engine/schemas.py` 의 `Recommendation`.

```
POST /api/recommend
{ "query": "...", "domain": "pc", "answers": {} }
```

키 없이 돈다. 모드가 셋이고 전부 기본값이 키를 안 쓴다.

| 환경변수 | 기본값 | 다른 값 |
|---|---|---|
| `RECOMMEND_MODE` | `rule` — 1~5단계를 순서대로 부른다 | `strands` — 에이전트가 순서를 정한다 |
| `MATCH_MODE` | `label` — 합성 라벨을 읽는다 | `llm` — 모델이 리뷰 문장을 실제로 읽는다 |
| `RISK_MODE` | `none` — 이미 붙은 점수만 쓴다 | `llm` — 모델이 조작 확률을 매긴다 |
| `REVIEW_SOURCE` | `synthetic` | 새 소스는 `app/reviews/__init__.py` 에 등록 |
| `REVIEW_EXCERPTS` | `auto` — 소스가 정한다 | `off` 언제나 가림 / `on` 언제나 실음 |

프로바이더는 `MODEL_PROVIDER` 하나로 바뀐다 — `openai`(기본) / `bedrock`.
응답 형은 어느 쪽이든 같으므로 **화면은 신경 쓸 것이 없다.**

모델은 자리별로 고른다. 호출부는 `_model("match")` 처럼 자리만 말하고 id 는
프로바이더별 환경변수에서 온다.

| 자리 | openai | bedrock |
|---|---|---|
| 기본 | `OPENAI_MODEL` | `BEDROCK_MODEL` |
| 의미 대조 | `MATCH_MODEL` | `MATCH_BEDROCK_MODEL` |
| 조작 확률 | `RISK_MODEL` | `RISK_BEDROCK_MODEL` |
| 조달 어시스턴트 | `ASSISTANT_MODEL` | `ASSISTANT_BEDROCK_MODEL` |

대조는 **호출량이 압도적이라 여기만 싼 모델을 쓰는 게 정석이다.**

**`MATCH_MODE=label` 은 의미 대조가 아니다.** 합성 데이터에 붙은 정답 라벨을 읽는
것이고 실데이터에는 그 라벨이 없다. 응답 형이 같아서 화면 쪽에서 달라지는 것은
없지만, 데모에서 *"AI 가 리뷰를 읽습니다"* 라고 말하려면 `MATCH_MODE=llm` 으로
돌린 화면이어야 한다. 대조 정확도는 `scripts/eval_matcher.py` 가 잰다.

## 왕복이 두 번이다

1단계가 하는 일이 *"무엇을 모르는지 아는 것"* 이라, **모르는 게 남으면 추천을
만들지 않는다.**

```
1차 → { needs_input: [...], set: [], budget: 1200000 }     ← 질문만 온다
2차 → { needs_input: [], set: [...], claims: [...], ... }   ← answers 를 채워 다시
```

`needs_input[]` 은 `{key, question, options[]}` 다. **화면 형태를 정해 두지
않았다** — 기획안은 카드형 팝업이라 적었지만 그건 화면 몫이라 백엔드는 무엇을
묻는지와 고를 수 있는 것만 준다. 답은 `answers` 에 `{key: 고른 값}` 으로 담아
같은 엔드포인트를 다시 부른다.

## 응답 필드

| 필드 | 무엇 |
|---|---|
| `needs_input[]` | 되묻기. 비어 있지 않으면 나머지는 비어 있다 |
| `requirements[]` | 2단계. `origin`(출처)과 `as_of`(기준 시점)가 붙는다 |
| `claims[]` | **3단계 — 핵심.** 주장 · 근거 · 판정 |
| `set[]` | 4단계. 세트 한 줄씩 |
| `budget` / `spent` | 예산과 합계 (잔액은 뺄셈) |
| `reasons[]` | 5단계 근거 문장. `claim_id` 로 판정과 연결된다 |
| `indicators` | §7 세 지표 |
| `screening[]` | 3단계 ① 깔때기. 하드 제약이 후보를 몇 개 걸렀는가 |
| `budget_met` | 예산 안에 들어왔는가. **`false` 면 `spent > budget`** |
| `notices[]` | 반드시 알려야 하는 것. 비어 있는 것이 정상 |
| `tools_used[]` | `RECOMMEND_MODE=strands` 일 때 도구 호출 내역 |
| `mode` | `rule` / `strands` |

### `claims[]` — 3단계

```json
{ "claim":   { "claim_id": "gpu-temp", "subject": "그래픽카드 B사·12GB",
               "text": "게이밍 부하 시 68°C", "source": "제조사 스펙" },
  "evidence":{ "samples": {"리뷰": 214, "QA": 31}, "relevant": 214, "hits": 47,
               "note": "214건이 이 주장에 닿고 그중 47건이 어긋납니다.",
               "quotes": ["풀로드 돌리면 82도까지 올라갑니다. …"],
               "excerpt_policy": "verbatim", "sources": [],
               "excluded_high_risk": 22 },
  "verdict": "refuted" }
```

`note` 는 **숫자에서 만들어진 문장**이고 구체적인 내용은 `quotes` 에 있다.
목업의 `"214건 중 47건이 80°C 이상을 언급"` 자리에는 `note` 와 `quotes[0]` 을
같이 쓰면 된다.

### ⚠ `quotes` 는 비어 있을 수 있다 — `excerpt_policy` 를 먼저 볼 것

2026-09-08 방침으로 **리뷰 원문을 그대로 내보낼 수 없다.** 그래서 인용은 정책에
따라 가려진다.

| `excerpt_policy` | 뜻 | 화면이 할 일 |
|---|---|---|
| `verbatim` | 인용이 실려 있다 | `quotes` 를 그대로 보인다 |
| `withheld` | **정책상 가렸다** | `sources[]` 로 링크한다. **"근거 없음"으로 보이면 안 된다** |

**가려도 판정과 표본 수는 그대로다.** 모델이 지어낸 인용은 서버 안에서 이미
버려졌고(검증과 노출은 다른 일이다), 가리는 것은 마지막 단계뿐이다. `note` 도
*"리뷰 원문은 정책상 싣지 않습니다 — 출처로 확인하세요"* 를 붙여 나간다.

**`withheld` 를 `no_evidence` 처럼 그리지 말 것.** 근거가 없는 것과 못 보여주는
것은 다르고, 이 서비스가 파는 것이 바로 그 구분이다.

전환은 `REVIEW_EXCERPTS` — `auto`(기본, 소스가 정한다) / `off` / `on`.
합성 리뷰는 우리가 만든 문장이라 `auto` 에서 실리고, 실데이터 소스는 반대가
기본이다.

`excluded_high_risk` 는 **조작 확률 20% 이상이라 대조에서 뺀 건수**다. 공개
화면이 그렇게 약속했으므로 화면 어딘가에 이 수가 보여야 한다 — 지우지 않고
뺀다는 것이 약속의 절반이다.

`unscored_risk` 가 **0이 아니면 "20% 이상을 걸렀다"고 말하면 안 된다.** 조작
확률을 재지 못한 리뷰가 표본에 섞여 있다는 뜻이다(실 리뷰에는 확률이 안 붙어
있고, `RISK_MODE=none` 이면 매기지 않는다). `note` 에도 그 문장이 들어간다.

`verdict` 는 넷이다 — `confirmed` · `partly` · `refuted` · `no_evidence`.
**글리프와 색은 응답에 없다.** 목업이 쓴 ● ◐ ✕ · 를 백엔드가 강제하지 않으려는
것이고, 화면에서 정하면 된다. 다만 목업이 적어 둔 이유대로 **색만으로 구분하지
말 것** — 색각 대응이자 발표 슬라이드로 캡처했을 때도 읽히게 하려는 것이다.

숫자가 셋인 이유가 있다. `samples` 는 읽은 표본(소스별로 쪼갬), `relevant` 는
그중 이 주장에 닿는 것, `hits` 는 그중 어긋나는 것이다. 목업 SSD 행이 그 차이를
보여준다 — 리뷰 142건을 읽었지만 실측을 언급한 것은 3건뿐이라 판정이
`no_evidence` 다. **표시할 때 `samples` 와 `relevant` 를 섞지 말 것.**

### `set[]` — 4단계

```json
{ "category": "쿨러", "code": "COOL-T1", "name": "타워형 공랭", "price": 34000,
  "added_by_claim": "cpu-cooler", "warning": "" }
```

- `added_by_claim` 이 있으면 **반증 판정 때문에 편성된 줄**이다. 목업이 이걸
  *"검증이 설명용 장식이 아니라 구성에 관여한다는 증거"* 라고 부른다 — 화면에서
  이 줄이 그냥 부품처럼 보이면 3단계가 한 일이 안 보인다
- `warning` 이 있으면 **반증됐지만 대안이 없어 유지된 줄**이다. 목록에서 빼지
  말 것 — 백엔드가 빼지 않는 이유와 같다(아래)

### `indicators` — §7 세 지표

```json
{ "conditions_met": 3, "conditions_total": 4, "conditions_unmet": ["refresh_hz: ..."],
  "verdicts": {"refuted": 2, "confirmed": 2, "partly": 1, "no_evidence": 1},
  "samples_compared": 768,
  "review_risk_buckets": {"0-20%": 768, "20-40%": 43, "40-60%": 13, ...} }
```

`samples_compared` 는 **주장별 `samples` 의 합이 아니다.** 한 품목에 주장이 둘이면
같은 리뷰 묶음을 두 주장이 나눠 쓰므로 합계는 그만큼 겹쳐 센다(그래픽카드가 그렇다).
이 값은 겹치지 않게 센 **실제로 읽은 리뷰 수**이고, 그래서 `review_risk_buckets`
의 합보다 작다 — 차이가 조작 확률 때문에 대조에서 뺀 건수다.

**하나로 합치지 말 것.** 종합 점수 필드가 없는 것이 실수가 아니라 설계다 —
합치면 가중치를 정당화해야 하는데 근거가 없고, 멘토가 물어본 것이 정확히 그
지점이었다(기획안 §7). 조작 확률도 이진 판정이 아니라 분포로만 나간다.

### `screening[]` · `notices[]` · `budget_met`

```json
"screening": [{ "key": "vram", "label": "VRAM 12GB 이상", "excluded": 1, "remaining": 11,
                "origin": "게임사 공개 권장 사양 · 〈오르카 프로토콜〉" }],
"budget_met": false,
"notices": ["예산 500,000원 안에 들어오는 조합을 찾지 못했습니다. …"]
```

**`excluded: 0` 인 행을 지우지 말 것.** 외부 사실을 주입해도 예산이 넉넉하면
결과가 같을 수 있다 — 요구는 바닥이지 목표가 아니기 때문이다. 그때 *"권장 사양을
주입했습니다"* 만 뜨고 무엇이 달라졌는지 안 보이면 *"8GB였으면 뭐가 달라집니까"*
에 답할 것이 없다. **0을 0이라고 보이는 것**이 답이다.

**`notices[]` 는 비어 있는 것이 정상이고, 있으면 반드시 보여야 한다.** 셋이 나온다.

| 언제 | 무엇을 말하나 |
|---|---|
| 하드 제약이 하나도 없을 때 | 외부 사실을 못 찾아 조건 없이 추천했다 (모르는 게임 등) |
| `spent > budget` | 예산 안에 들어오는 조합을 못 찾았다 |
| `unscored_risk > 0` | 조작 확률을 못 잰 리뷰가 표본에 섞여 있다 |

**`budget_met: false` 인데 합계만 보여주면 사용자는 예산을 지킨 줄 압니다.**

## 화면이 지켜야 하는 것 둘

목업 마지막의 공개 화면(공정위 사용후기 규정 대응)이 서비스의 약속으로 적어 둔
것이다. 백엔드는 검사로 고정했고(`tests/test_recommend_engine.py`), 화면에서
깨지면 같은 약속이 거짓이 된다.

1. **반증된 항목을 목록에서 빼지 않는다.** 경고만 붙인다
2. **리뷰를 순위에 반영하지 않는다.** 리뷰가 만드는 값은 스펙 주장의 판정
   하나뿐이다. 판정으로 재정렬하지 말 것

## 합성 데이터 고지

리뷰는 지금 **합성**이다(네이버·카카오 리뷰 API 가 없다는 것이 9/7 23시에
확인됐다). 조작 리뷰의 정답 라벨이 필요해 합성했고, **숨기지 않는 것이 조건**이라
화면 어딘가에 고지가 있어야 한다. 문구는 `app/reviews/synthetic.py` 의
`disclosure()` 에 있다.

## 해 보기

```bash
uvicorn app.main:app --reload --port 8000
curl -s localhost:8000/api/recommend -H 'content-type: application/json' \
  -d '{"query":"〈오르카 프로토콜〉 QHD 상옵 예산 120만 원",
       "answers":{"refresh_hz":"144Hz","reuse":"케이스만","priority":"상관없음"}}'
```

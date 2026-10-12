# 추천 엔진 정책 변경 비교 검증

작성일: 2026-10-13
상태: 0~5단계 구현 뒤의 비교 결과(브랜치 `feat/engine-policy-v12`, 최신 커밋 5f88dc5b). 6단계(광고 가산점)와 D5(기본 탐색 범위의 전체 후보 풀 확장)는 이번 구현에 없으므로 이 문서의 비교 대상이 아니다. 정책 근거는 [추천엔진_수정계획.md](../추천엔진_수정계획.md) §9·§10, 구현 계획은 [추천엔진_수정_구현계획_20261012.md](../추천엔진_수정_구현계획_20261012.md) §4 7단계다.

이 문서의 표는 모두 `scripts/engine_policy_report.py`의 출력을 그대로 옮긴 것이다(손으로 만든 수치 없음). 원본 덤프는 같은 폴더의 `engine_policy_baseline_20261012.json`, `engine_policy_after_20261013.json`, `engine_policy_scenarios_20261013.json`이다.

## 1. 목적

정책 변경(점수식 3축·새 가격식, Pending 승격 삭제, RAM 2개 구성, 조합 적격성, 여유 기록, 표시 점수)이 같은 요청·같은 카탈로그에서 추천 결과를 어떻게 바꾸는지 기록한다. 확인하려는 것은 다음이다.

- 추천 가능한 결과만 세어 후보 부족을 숨기지 않는다(비율의 분모는 항상 전체 요청이다).
- 정상 추천으로 나간 결과에 예산 초과·최소 성능 미달·호환 위반·필수 정보 누락이 없다.
- 단계마다 선택 부품·총가격·예산 사용률·등급이 얼마나 바뀌는지 원인과 함께 본다.
- 저소음 요청이 리뷰의 정숙성 근거로만 반영되고 중복 배율이 없다.
- 정보 보완·조합 보완이 무엇을 시도했고 얼마나 채웠는지 본다.
- 전력·크기·냉각 여유 기록이 입력·단위·계산식으로 재현된다.
- 정책 §10의 고정 시나리오 16종이 기대대로 동작한다.

## 2. 실행 방법과 재현성

모두 개발 DB `truefit`을 **읽기만** 한다(비교 스크립트는 `SET TRANSACTION READ ONLY`, run 저장 없음, LLM 없음, 보완은 저장소 조회만). 고정 시나리오는 DB를 쓰지 않는다. 테스트 DB 규칙(`test`가 들어간 이름)과는 별개의 수동 스크립트다.

```bash
# 126개 요청(용도 5 × 우선순위 4 × 소음 민감 2 × 예산 3 = 120, 추가 4, 업그레이드 2)
MOCK_MODE=1 CATALOG_SOURCE=db PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache \
  uv run python scripts/engine_policy_compare.py --out docs/validation/engine_policy_after_20261013.json

# 고정 시나리오 16종(메모리 안의 작은 카탈로그 + 고정 표 대체 조회)
MOCK_MODE=1 PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache \
  uv run python scripts/engine_policy_scenarios.py --out docs/validation/engine_policy_scenarios_20261013.json

# 지표 표(첫 --dump 가 기준선, 마지막이 최종)
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/engine_policy_report.py \
  --dump "0 기준선=docs/validation/engine_policy_baseline_20261012.json" --dump "1 점수식=<스크래치>/phase1.json" ... \
  --dump "최종=docs/validation/engine_policy_after_20261013.json" \
  --scenarios docs/validation/engine_policy_scenarios_20261013.json --timing-note "측정 조건"
```

- 엔진 구간 흐름은 서비스(`execute_recommendation`)와 같다. 사전 필터에 읽기 전용 보완 함수(`catalog_enrichment.make_enricher`)를 넘기고, 최종 조합이 `required_info_missing`이면 서비스의 `_needs_combo_enrichment`·`_enrich_combo_missing`을 그대로 불러 한 번 보완한 뒤 값이 채워졌을 때만 한 번 다시 돈다(로직 복제 없음). 스크립트 쪽에서 서비스를 고치지는 않았다.
- 결정성: 같은 커밋·같은 DB에서 두 번 돌려 `generated_at`·`wall_ms`를 뺀 모든 필드가 같음을 확인했다(126요청 덤프, 시나리오 덤프 각각).
- 최종 덤프의 `git_commit`은 5f88dc5b이고 `git_dirty`는 true다. 생성 시점에 추적 파일 변경은 보강한 `scripts/engine_policy_compare.py` 하나뿐이었다(엔진·서비스 코드는 5f88dc5b 그대로). 시나리오 덤프도 같은 이유로 dirty다.
- 단계별 덤프(스크래치, 저장소에 넣지 않음)는 각 단계 작업 중 같은 스크립트·같은 개발 DB로 만들었다. 덤프의 `git_commit`은 **그 단계 직전 HEAD(이전 단계 커밋)** 이고 `git_dirty=true`는 그 단계의 미커밋 변경을 뜻한다. 아래 표는 이를 다음 커밋의 내용으로 읽는다(커밋 뒤 다시 돌려 byte 단위로 대조하지는 않았다. 3→4a→4b→최종의 선택 부품이 같은 것은 표로 확인된다). 단계별 덤프는 이 문서의 보강 필드(보완 기록·리뷰 근거·성능 하한 등)가 없던 시점의 형식이라 해당 칸은 n/a다.

## 3. 단계별 비교 대상

덤프의 `git_commit`·`git_dirty`와 그 덤프가 나타내는 단계 커밋이다.

| 단계 | 의미 | 덤프의 git_commit | git_dirty | 읽는 커밋 |
|---|---|---|---|---|
| 0 기준선 | 정책 변경 전 | 47712d33 | 아니오 | 47712d33 |
| 1 점수식 | 3축·새 가격식·가중치 | f955d498 | 예 | a5ffbf8f |
| 2 사전 필터 | Pass만 통과·후보 부족 | a5ffbf8f | 예 | ca367626 |
| 3 RAM 2개 | 키트/단품 2개 구성 | ca367626 | 예 | b2b06d79 |
| 4a 적격성 | 조합 필수 정보·적격성 | b2b06d79 | 예 | a69ff1f8 |
| 4b 여유 | 전력·크기·냉각 여유 기록 | a69ff1f8 | 예 | 24b54348 |
| 최종 | 품목 순서 고정(522c1ffd)·표시 점수(5단계) | 5f88dc5b | 예(스크립트 보강) | 5f88dc5b |

**단계별 요약**

| 단계 | 커밋 | dirty | 요청 | 정상 추천 | 부적격 | 후보 부족 | 오류 | 판정 없음 | 평균 총가격(원) | 평균 예산 사용률(%) | CPU 등급 | GPU 등급 | p50(ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 47712d33 | 아니오 | 126 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 | 126 | 1468690 | 80.34 | 6.30 | 4.93 | 368 |
| 1 점수식(a5ffbf8f) | f955d498 | 예 | 126 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 | 126 | 1640843 | 87.64 | 7.27 | 6.42 | 422 |
| 2 사전 필터(ca367626) | a5ffbf8f | 예 | 126 | 0 (0.0%) | 0 (0.0%) | 1 (0.8%) | 0 | 125 | 1650728 | 88.02 | 7.27 | 6.42 | 412 |
| 3 RAM 2개(b2b06d79) | ca367626 | 예 | 126 | 0 (0.0%) | 0 (0.0%) | 1 (0.8%) | 0 | 125 | 1629728 | 87.30 | 7.30 | 6.61 | 457 |
| 4a 적격성(a69ff1f8) | b2b06d79 | 예 | 126 | 108 (85.7%) | 17 (13.5%) | 1 (0.8%) | 0 | 0 | 1629728 | 87.30 | 7.30 | 6.61 | 527 |
| 4b 여유(24b54348) | a69ff1f8 | 예 | 126 | 108 (85.7%) | 17 (13.5%) | 1 (0.8%) | 0 | 0 | 1629728 | 87.30 | 7.30 | 6.61 | 479 |
| 최종(5f88dc5b) | 5f88dc5b | 예 | 126 | 108 (85.7%) | 17 (13.5%) | 1 (0.8%) | 0 | 0 | 1629728 | 87.30 | 7.30 | 6.61 | 320 |

`CPU 등급`·`GPU 등급`은 선택된 부품의 `perf_tier` 평균(조합이 나온 요청 전체), 예산 사용률은 총액/예산이다. 기준선에는 적격성 판정이 없어 `판정 없음`으로 센다(기준선 126건이 모두 그렇다). 부적격·후보 부족은 4a부터(후보 부족은 2단계부터) 나타난다.

## 4. 지표

### 4.1 슬롯별 Pass·Pending·Fail

**기준선: 슬롯별 Pass·Pending·Fail (요청 평균, 괄호는 전체 합)**

| 슬롯 | 요청 | Pass 평균(합) | Pending 평균(합) | Fail 평균(합) |
|---|---|---|---|---|
| CPU | 126 | 31.3 (3940) | 0.0 (0) | 8.7 (1100) |
| GPU | 126 | 28.3 (3569) | 10.8 (1366) | 3.8 (483) |
| RAM | 126 | 29.0 (3649) | 0.0 (0) | 10.0 (1265) |
| 메인보드 | 126 | 31.0 (3900) | 0.0 (0) | 9.0 (1140) |
| 저장장치 | 126 | 35.1 (4420) | 0.0 (0) | 4.9 (620) |
| 케이스 | 126 | 40.0 (5040) | 0.0 (0) | 0.0 (0) |
| 쿨러 | 126 | 40.0 (5040) | 0.0 (0) | 0.0 (0) |
| 파워 | 126 | 33.6 (4232) | 0.0 (0) | 6.4 (808) |

**최종: 슬롯별 Pass·Pending·Fail**

| 슬롯 | 요청 | Pass 평균(합) | Pending 평균(합) | Fail 평균(합) |
|---|---|---|---|---|
| CPU | 124 | 31.1 (3860) | 0.0 (0) | 8.9 (1100) |
| GPU | 125 | 28.2 (3526) | 10.9 (1366) | 3.9 (483) |
| RAM | 124 | 32.9 (4082) | 0.0 (0) | 6.1 (754) |
| 메인보드 | 124 | 31.1 (3860) | 0.0 (0) | 8.9 (1100) |
| 저장장치 | 124 | 35.0 (4340) | 0.0 (0) | 5.0 (620) |
| 케이스 | 124 | 40.0 (4960) | 0.0 (0) | 0.0 (0) |
| 쿨러 | 124 | 40.0 (4960) | 0.0 (0) | 0.0 (0) |
| 파워 | 124 | 33.5 (4152) | 0.0 (0) | 6.5 (808) |

최종의 Pending·Fail 사유 분포는 다음과 같다. 사전 필터가 끝나기 전에 후보 부족이 난 요청(업그레이드 RAM+메인보드 1건)은 슬롯 평균의 분모에서 빠진다.

**최종: Pending 사유**

| 슬롯 | 사유 | 후보 수 합 |
|---|---|---|
| GPU | PENDING_SPEC_MISSING:perf_tier | 1366 |

**최종: Fail 사유**

| 슬롯 | 사유 | 후보 수 합 |
|---|---|---|
| CPU | FAIL_PERF_BELOW | 516 |
| CPU | FAIL_SOCKET_NOT_IN | 884 |
| GPU | FAIL_PERF_BELOW | 474 |
| GPU | FAIL_VRAM_BELOW | 200 |
| RAM | FAIL_CAPACITY_BELOW | 156 |
| RAM | FAIL_MEM_TYPE | 728 |
| 메인보드 | FAIL_FORM_NOT_IN | 372 |
| 메인보드 | FAIL_MEM_TYPE | 364 |
| 메인보드 | FAIL_SOCKET_NOT_IN | 728 |
| 저장장치 | FAIL_PROTOCOL | 620 |
| 파워 | FAIL_RATING_BELOW | 808 |
| 파워 | FAIL_WATTAGE_BELOW | 396 |

### 4.2 정상 추천·부적격·후보 부족

분모는 전체 요청(126)이다. 단계별 건수와 비율은 3장의 표, 사유 분포는 다음과 같다.

- 0 기준선(47712d33): 부적격 사유 {} · 후보 부족 슬롯 {}
- 1 점수식(a5ffbf8f): 부적격 사유 {} · 후보 부족 슬롯 {}
- 2 사전 필터(ca367626): 부적격 사유 {} · 후보 부족 슬롯 {"메인보드": 1}
- 3 RAM 2개(b2b06d79): 부적격 사유 {} · 후보 부족 슬롯 {"메인보드": 1}
- 4a 적격성(a69ff1f8): 부적격 사유 {"budget_exceeded": 17} · 후보 부족 슬롯 {"메인보드": 1}
- 4b 여유(24b54348): 부적격 사유 {"budget_exceeded": 17} · 후보 부족 슬롯 {"메인보드": 1}
- 최종(5f88dc5b): 부적격 사유 {"budget_exceeded": 17} · 후보 부족 슬롯 {"메인보드": 1}

### 4.3 선택 부품 변화

**기준선과 비교**

| 단계(기준선 대비) | 비교 요청 | 하나라도 바뀐 요청 | CPU | GPU | RAM | 메인보드 | 저장장치 | 케이스 | 쿨러 | 파워 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 점수식(a5ffbf8f) | 126 | 103 (81.7%) | 60 | 67 | 59 | 6 | 29 | 33 | 55 | 15 |
| 2 사전 필터(ca367626) | 125 | 103 (82.4%) | 60 | 67 | 59 | 6 | 29 | 33 | 55 | 15 |
| 3 RAM 2개(b2b06d79) | 125 | 124 (99.2%) | 62 | 79 | 124 | 6 | 23 | 23 | 55 | 11 |
| 4a 적격성(a69ff1f8) | 125 | 124 (99.2%) | 62 | 79 | 124 | 6 | 23 | 23 | 55 | 11 |
| 4b 여유(24b54348) | 125 | 124 (99.2%) | 62 | 79 | 124 | 6 | 23 | 23 | 55 | 11 |
| 최종(5f88dc5b) | 125 | 124 (99.2%) | 62 | 79 | 124 | 6 | 23 | 23 | 55 | 11 |

**직전 단계와 비교**

| 단계(직전 단계 대비) | 비교 요청 | 하나라도 바뀐 요청 | CPU | GPU | RAM | 메인보드 | 저장장치 | 케이스 | 쿨러 | 파워 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 점수식(a5ffbf8f) | 126 | 103 (81.7%) | 60 | 67 | 59 | 6 | 29 | 33 | 55 | 15 |
| 2 사전 필터(ca367626) | 125 | 0 (0.0%) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 RAM 2개(b2b06d79) | 125 | 124 (99.2%) | 2 | 16 | 124 | 0 | 10 | 10 | 0 | 4 |
| 4a 적격성(a69ff1f8) | 125 | 0 (0.0%) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 4b 여유(24b54348) | 125 | 0 (0.0%) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 최종(5f88dc5b) | 125 | 0 (0.0%) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

3→4a→4b→최종 사이에 선택 부품이 바뀐 요청은 0건이다. 이 사이의 변화는 점수 순위(4.6)와 기록·판정 필드(적격성·여유·표시 점수)뿐이다. 2→3(RAM 2개 구성)에서 RAM이 124건 모두 바뀌고 일부 다른 슬롯이 따라 바뀐다.

### 4.4 총가격·예산 사용률

**단계별 총가격·예산 사용률**

| 단계 | 범위 | 요청 | 평균 총가격(원) | 예산 사용률 평균(%) | 최소 | p50 | p90 | 최대 |
|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 조합이 나온 전체 | 126 | 1468690 | 80.34 | 21.93 | 83.51 | 130.07 | 179.64 |
| 0 기준선(47712d33) | 정상 추천만 | 126 | 1468690 | 80.34 | 21.93 | 83.51 | 130.07 | 179.64 |
| 1 점수식(a5ffbf8f) | 조합이 나온 전체 | 126 | 1640843 | 87.64 | 21.93 | 94.74 | 130.07 | 179.64 |
| 1 점수식(a5ffbf8f) | 정상 추천만 | 126 | 1640843 | 87.64 | 21.93 | 94.74 | 130.07 | 179.64 |
| 2 사전 필터(ca367626) | 조합이 나온 전체 | 125 | 1650728 | 88.02 | 21.93 | 94.74 | 130.07 | 179.64 |
| 2 사전 필터(ca367626) | 정상 추천만 | 125 | 1650728 | 88.02 | 21.93 | 94.74 | 130.07 | 179.64 |
| 3 RAM 2개(b2b06d79) | 조합이 나온 전체 | 125 | 1629728 | 87.30 | 21.93 | 92.85 | 133.03 | 179.84 |
| 3 RAM 2개(b2b06d79) | 정상 추천만 | 125 | 1629728 | 87.30 | 21.93 | 92.85 | 133.03 | 179.84 |
| 4a 적격성(a69ff1f8) | 조합이 나온 전체 | 125 | 1629728 | 87.30 | 21.93 | 92.85 | 133.03 | 179.84 |
| 4a 적격성(a69ff1f8) | 정상 추천만 | 108 | 1629604 | 76.21 | 21.93 | 84.44 | 99.11 | 99.15 |
| 4b 여유(24b54348) | 조합이 나온 전체 | 125 | 1629728 | 87.30 | 21.93 | 92.85 | 133.03 | 179.84 |
| 4b 여유(24b54348) | 정상 추천만 | 108 | 1629604 | 76.21 | 21.93 | 84.44 | 99.11 | 99.15 |
| 최종(5f88dc5b) | 조합이 나온 전체 | 125 | 1629728 | 87.30 | 21.93 | 92.85 | 133.03 | 179.84 |
| 최종(5f88dc5b) | 정상 추천만 | 108 | 1629604 | 76.21 | 21.93 | 84.44 | 99.11 | 99.15 |

**같은 요청 집합(최종에서 정상 추천인 108건)만의 단계별 비교**

| 단계 | 요청 | 평균 예산 사용률(%) | 평균 총가격(원) |
|---|---|---|---|
| 0 기준선(47712d33) | 108 | 68.76 | 1455514 |
| 1 점수식(a5ffbf8f) | 108 | 77.28 | 1656359 |
| 2 사전 필터(ca367626) | 108 | 77.28 | 1656359 |
| 3 RAM 2개(b2b06d79) | 108 | 76.21 | 1629604 |
| 4a 적격성(a69ff1f8) | 108 | 76.21 | 1629604 |
| 4b 여유(24b54348) | 108 | 76.21 | 1629604 |
| 최종(5f88dc5b) | 108 | 76.21 | 1629604 |

**예산을 늘려도 총가격이 줄지 않는가(성능 우선, noise=0)**

| 단계 | 용도 | 총가격(예산 100만 → 200만 → 350만) | 예산이 늘 때 총가격 유지(−5% 허용) |
|---|---|---|---|
| 0 기준선(47712d33) | creation | 1,794,298 → 1,921,428 → 3,483,208 | 예 |
| 0 기준선(47712d33) | game | 1,300,658 → 1,819,128 → 2,351,210 | 예 |
| 0 기준선(47712d33) | office | 995,698 → 1,998,470 → 2,765,160 | 예 |
| 0 기준선(47712d33) | other | 984,658 → 1,998,470 → 2,765,160 | 예 |
| 0 기준선(47712d33) | study | 984,658 → 1,998,470 → 2,765,160 | 예 |
| 최종(5f88dc5b) | creation | 1,797,338 → 1,893,950 → 3,285,580 | 예 |
| 최종(5f88dc5b) | game | 1,330,298 → 1,975,608 → 2,590,200 | 예 |
| 최종(5f88dc5b) | office | 991,068 → 1,977,720 → 2,931,650 | 예 |
| 최종(5f88dc5b) | other | 991,068 → 1,977,720 → 2,931,650 | 예 |
| 최종(5f88dc5b) | study | 991,068 → 1,977,720 → 2,931,650 | 예 |

### 4.5 RAM 구성

**선택된 RAM 구성**

| 단계 | RAM 선택 수 | 단품 2개 구성(qty=2) | qty=1(키트 또는 단품 1개) | 평균 구성 가격(원) |
|---|---|---|---|---|
| 0 기준선(47712d33) | 125 | 0 | 125 | 405261 |
| 1 점수식(a5ffbf8f) | 125 | 0 | 125 | 346890 |
| 2 사전 필터(ca367626) | 124 | 0 | 124 | 346865 |
| 3 RAM 2개(b2b06d79) | 124 | 124 | 0 | 319309 |
| 4a 적격성(a69ff1f8) | 124 | 124 | 0 | 319309 |
| 4b 여유(24b54348) | 124 | 124 | 0 | 319309 |
| 최종(5f88dc5b) | 124 | 124 | 0 | 319309 |

카탈로그 기준 규격·총용량별 가장 싼 구성 가격(원, 덤프의 ram_pair_prices):

| 규격-총용량 | 가장 싼 키트 | 가장 싼 단품 2개 |
|---|---|---|
| DDR4-16GB | 229990 | 159800 |
| DDR4-32GB | 176000 | 359780 |
| DDR4-64GB | n/a | 981980 |
| DDR5-16GB | n/a | 365160 |
| DDR5-32GB | 759000 | 671040 |
| DDR5-64GB | 758629 | 1336000 |

### 4.6 3-B 순위

| 단계 | CPU | GPU | RAM | 메인보드 | 저장장치 | 케이스 | 쿨러 | 파워 |
|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 1.34 (밖 17) | 1.30 (밖 16) | 1.62 (밖 17) | 2.18 (밖 6) | 1.06 (밖 0) | 1.01 (밖 16) | 1.05 (밖 0) | 1.05 (밖 21) |
| 1 점수식(a5ffbf8f) | 1.99 (밖 27) | 1.27 (밖 36) | 1.12 (밖 21) | 2.06 (밖 0) | 1.31 (밖 0) | 1.19 (밖 0) | 1.00 (밖 0) | 1.03 (밖 0) |
| 2 사전 필터(ca367626) | 1.99 (밖 27) | 1.27 (밖 36) | 1.12 (밖 21) | 2.06 (밖 0) | 1.31 (밖 0) | 1.19 (밖 0) | 1.00 (밖 0) | 1.03 (밖 0) |
| 3 RAM 2개(b2b06d79) | 1.99 (밖 27) | 1.27 (밖 36) | 1.09 (밖 9) | 2.06 (밖 0) | 1.18 (밖 0) | 1.18 (밖 0) | 1.00 (밖 0) | 1.00 (밖 0) |
| 4a 적격성(a69ff1f8) | 1.99 (밖 27) | 1.27 (밖 36) | 1.09 (밖 9) | 2.06 (밖 0) | 1.18 (밖 0) | 1.56 (밖 0) | 1.00 (밖 0) | 1.00 (밖 0) |
| 4b 여유(24b54348) | 1.99 (밖 27) | 1.27 (밖 36) | 1.09 (밖 9) | 2.06 (밖 0) | 1.18 (밖 0) | 1.56 (밖 0) | 1.00 (밖 0) | 1.00 (밖 0) |
| 최종(5f88dc5b) | 1.99 (밖 27, 전체 5.22) | 1.27 (밖 36, 전체 5.95) | 1.09 (밖 9, 전체 1.68) | 2.06 (밖 0, 전체 2.06) | 1.18 (밖 0, 전체 1.18) | 1.56 (밖 0, 전체 1.56) | 1.00 (밖 0, 전체 1.00) | 1.00 (밖 0, 전체 1.00) |

단계별 덤프는 3-B 상위 5개만 기록해, 비교 기준을 "상위 5 안에서의 평균 순위"와 "상위 5 밖 선택 수"로 맞췄다. 최종 덤프만 전체 풀 순위(`rank_in_3b`)를 함께 가진다. 슬롯마다 후보 수가 다르므로(CPU·GPU 상위 5개, 나머지 상위 3개를 조합 탐색에 먼저 쓴다) 순위가 1이 아니라는 것이 곧 문제는 아니다. 조합 호환·예산 때문에 부품별 1위를 그대로 고를 수 없기 때문이다.

### 4.7 저소음 요청의 정숙성 근거 반영

같은 (용도·우선순위·예산)에서 `noise_sensitive`만 다른 60쌍을 비교한다.

**noise=0/1 쌍 비교**

| 단계 | noise 쌍 | 선택이 다른 쌍 | 바깥 가중치가 다른 쌍 | 정숙성 요청 가중이 다른 쌍 | noise=0 선택 부품 중 정숙성 기여 있음 | noise=1 선택 부품 중 정숙성 기여 있음 | 정숙성 요청 가중 평균(noise=0) | (noise=1) |
|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 60 | 32 | 45 | 0 | n/a | n/a | n/a | n/a |
| 1 점수식(a5ffbf8f) | 60 | 1 | 0 | 0 | n/a | n/a | n/a | n/a |
| 2 사전 필터(ca367626) | 60 | 1 | 0 | 0 | n/a | n/a | n/a | n/a |
| 3 RAM 2개(b2b06d79) | 60 | 1 | 0 | 0 | n/a | n/a | n/a | n/a |
| 4a 적격성(a69ff1f8) | 60 | 1 | 0 | 0 | n/a | n/a | n/a | n/a |
| 4b 여유(24b54348) | 60 | 1 | 0 | 0 | n/a | n/a | n/a | n/a |
| 최종(5f88dc5b) | 60 | 1 | 0 | 45 | 193/513 | 180/480 | 0.217 | 0.284 |

**최종: 우선순위별 정숙성 요청 가중 변화**

| 우선순위 | 정숙성 요청 가중 합의 차이 평균(noise=1 − noise=0) |
|---|---|
| none | 0.707 |
| performance | 0.707 |
| quiet | 0.000 |
| value | 0.707 |

### 4.8 필수 조건 위반

정상 추천(기준선·1~3단계는 판정이 없으므로 조합이 나온 전체) 결과에서 예산 초과·최소 성능 미달·호환 위반(link_check fail)·필수 정보 누락/부적격 사유·검증 blocking을 자동으로 확인한 건수다. 4a 이후에는 부적격 결과를 이 검사에서 뺀다(그 결과는 정상 추천이 아니라 진단용이다).

| 단계 | 검사한 결과 | 위반 건수 | 종류 | 성능 하한 정보 없는 요청(성능 검사 생략) |
|---|---|---|---|---|
| 0 기준선(47712d33) | 126 | 19 | budget_exceeded 17, compat_violation 2 | 126 |
| 1 점수식(a5ffbf8f) | 126 | 19 | budget_exceeded 17, compat_violation 2 | 126 |
| 2 사전 필터(ca367626) | 125 | 17 | budget_exceeded 17 | 125 |
| 3 RAM 2개(b2b06d79) | 125 | 17 | budget_exceeded 17 | 125 |
| 4a 적격성(a69ff1f8) | 108 | 0 | — | 108 |
| 4b 여유(24b54348) | 108 | 0 | — | 108 |
| 최종(5f88dc5b) | 108 | 0 | — | 0 |

최종(5f88dc5b): 위반 목록 없음

### 4.9 누락 키와 정보 보완

**최종: 부적격 결과의 누락 키(구매·유지 부품별)**

(없음)

**사전 필터·조합 단계 정보 보완**

| 단계 | 사전 필터 시도 | 채움 | 채움률 | Pass 복귀 | 복귀율(시도 대비) | 상태별 | 조합 보완 요청 수 | 조합 시도 | 조합 채움 | 재실행 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 1 점수식(a5ffbf8f) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 2 사전 필터(ca367626) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 3 RAM 2개(b2b06d79) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 4a 적격성(a69ff1f8) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 4b 여유(24b54348) | 0 | 0 | n/a | 0 | n/a | — | 0 | 0 | 0 | 0 |
| 최종(5f88dc5b) | 1366 | 0 | 0.0% | 0 | 0.0% | no_path 1366 | 0 | 0 | 0 | 0 |

**실제 연결(GPU 보조 전원)·사용자 필수 RAM 속도별 결과(고정 시나리오)**

| 시나리오 | 경우 | 결과 | 기대와 일치 |
|---|---|---|---|
| 13 GPU 커넥터 개수 | 필요 개수 정보 누락(보류) | not_recommendable | 예 |
| 13 GPU 커넥터 개수 | 확인된 부족(탈락) | not_recommendable | 예 |
| 13 GPU 커넥터 개수 | 보조 전원 불필요(비적용) | recommendable | 예 |
| 14 사용자 필수 RAM 속도 | CPU 지원 속도 미확인(보류) | not_recommendable | 예 |
| 14 사용자 필수 RAM 속도 | RAM 속도 미달 | not_recommendable | 예 |
| 14 사용자 필수 RAM 속도 | 충족 | recommendable | 예 |
| 14 사용자 필수 RAM 속도 | 요구 없음(CPU 속도 미확인) | recommendable | 예 |

정상 추천 3/7 (42.9%)

기준선과 1~4b 단계의 0은 당시 스크립트가 보완 함수를 연결하지 않았거나 보완 기록을 덤프하지 않아서이며 측정값이 아니다. 위 시나리오 표의 정상 추천 비율은 시나리오를 고른 방식에 따른 값이지 실제 요청에서의 일반 비율이 아니다.

개발 DB 요청에는 필수 정보 누락으로 부적격이 된 경우가 없어(위 "누락 키" 표가 비어 있음) 누락 키·구매/유지 부품별 사유는 고정 시나리오(5장)에서 본다. 조합 보완(`combo_enrichment`)이 시도된 요청도 없다. 사전 필터의 보완 시도는 GPU의 성능 등급(`perf_tier`) 결측에 대한 것이 전부이고 모두 `no_path`다(저장소가 다루는 키가 아니다). 즉 이 카탈로그에서 보완 성공률과 Pass 복귀율은 0%이며, 보완 흐름이 동작하는지는 고정 시나리오 9~11이 재현한다.

### 4.10 전력·크기 여유

**최종: 항목별 상태**

| 단계 | 항목 | available | unavailable | not_applicable |
|---|---|---|---|---|
| 최종(5f88dc5b) | cooling | 0 | 125 | 0 |
| 최종(5f88dc5b) | power.compat_check | 125 | 0 | 0 |
| 최종(5f88dc5b) | power.requirement_sizing | 124 | 0 | 1 |
| 최종(5f88dc5b) | power.total | 0 | 125 | 0 |
| 최종(5f88dc5b) | size.cooler_height | 124 | 0 | 1 |
| 최종(5f88dc5b) | size.gpu_length | 125 | 0 | 0 |
| 최종(5f88dc5b) | size.gpu_slots | 125 | 0 | 0 |
| 최종(5f88dc5b) | size.psu_length | 124 | 0 | 1 |
| 최종(5f88dc5b) | size.radiator | 0 | 0 | 125 |

**최종: unavailable 사유·누락 키**

| 항목 | 사유 / 키 | 수 |
|---|---|---|
| cooling | no_comparable_thermal_test | 125 |
| power.total | other_load_basis_missing | 125 |

**최종: 값 재현**

입력·단위·계산식으로 다시 계산: 623건 검사, 불일치 0건, 기록만 있는 항목(요구 산정 등) 124건

크기 여유(`size.*`)는 케이스 허용치 − 실제 치수(mm), GPU 슬롯은 케이스 확장 슬롯 − 올림(GPU 두께), 전력 호환 여유는 `파워 정격 × 0.9 − (CPU + GPU)`를 덤프의 입력으로 다시 계산해 대조했다. `power.requirement_sizing`은 2단계 요구 산정이 한 일의 기록이라 다시 계산하지 않는다(기록만 있는 항목). `power.total`(전체 예상 부하 대비 정격 여유)은 기타 구성품 부하의 근거 값이 설정에 없어(`margins.power.other_load: null`) 모든 요청에서 확인 불가이고, 냉각은 비교 가능한 시험 자료가 없어 모든 요청에서 확인 불가다.

### 4.11 조합 탐색 카운터

| 단계 | capped 발생 요청 | pruned_budget 발생 요청 | pruned_compat 발생 요청 | pruned_required_missing 발생 요청 | pruned_requirement_unmet 발생 요청 | pruned_score 발생 요청 | widened 발생 요청 | 조합이 나온 요청 |
|---|---|---|---|---|---|---|---|---|
| 0 기준선(47712d33) | 0 | 67 | 96 | 0 | 0 | 90 | 36 | 126 |
| 1 점수식(a5ffbf8f) | 1 | 70 | 76 | 0 | 0 | 70 | 56 | 126 |
| 2 사전 필터(ca367626) | 1 | 70 | 75 | 0 | 0 | 70 | 55 | 125 |
| 3 RAM 2개(b2b06d79) | 0 | 70 | 75 | 0 | 0 | 70 | 55 | 125 |
| 4a 적격성(a69ff1f8) | 0 | 70 | 75 | 124 | 0 | 70 | 55 | 125 |
| 4b 여유(24b54348) | 0 | 70 | 75 | 124 | 0 | 70 | 55 | 125 |
| 최종(5f88dc5b) | 0 | 70 | 75 | 124 | 0 | 70 | 55 | 125 |

`pruned_required_missing`은 4a부터 나타난다(필수 정보가 없는 부품이 들어간 가지를 쳤다는 뜻이며 선택을 바꾸지는 않았다: 4.3). `widened`는 상위 후보에서 해가 없어 전체 풀로 넓힌 요청, `capped`는 확대 탐색이 노드 상한(150,000)에 닿은 요청이다. 1·2단계 덤프에서 한 요청이 상한에 닿았고 이후에는 닿지 않았다.

### 4.12 요청당 처리 시간

| 단계 | 요청 | 평균(ms) | p50 | p90 | 최대 |
|---|---|---|---|---|---|
| 0 기준선(47712d33) | 126 | 448 | 368 | 572 | 2667 |
| 1 점수식(a5ffbf8f) | 126 | 894 | 422 | 1460 | 11101 |
| 2 사전 필터(ca367626) | 126 | 815 | 412 | 1393 | 8587 |
| 3 RAM 2개(b2b06d79) | 126 | 942 | 457 | 1717 | 8665 |
| 4a 적격성(a69ff1f8) | 126 | 1128 | 527 | 2251 | 10224 |
| 4b 여유(24b54348) | 126 | 1111 | 479 | 1961 | 12046 |
| 최종(5f88dc5b) | 126 | 626 | 320 | 1322 | 5124 |

측정 조건: 최종(5f88dc5b+보강 스크립트) 덤프는 다른 작업을 돌리지 않고 단독으로 실행했다(첫 실행 직전 loadavg 0.13, 개발 DB는 로컬 Docker). 기준선·단계별 덤프는 측정 조건을 기록하지 않았으므로(다른 작업과 동시에 돌았을 수 있음) 단계 사이의 시간 차이는 성능 변화의 근거로 쓰지 않는다. 시간에는 설명 문장(LLM)·저장 단계가 없다.

## 5. 고정 시나리오

정책 §10의 시나리오 16종을 메모리 안의 작은 카탈로그(`make_catalog()`: 슬롯당 2~3개 상품)와 고정 표 대체 조회(스텁, `for_keys` 포함)로 같은 엔진 흐름에 돌린 결과다. 범용 조회·수집·실제 LLM은 연결하지 않았다. 시나리오는 회귀 비교용이고, 같은 성질의 정확성은 아래 단위 테스트가 보장한다. 기대 필드의 접미사: `_has`는 포함, `_sub`는 부분 일치, `_min`은 이상이다.

| # | 시나리오 | 경우 | 기대 | 실제 | 결과 |
|---|---|---|---|---|---|
| 01 | 일부 후보의 필수 정보 누락 | 케이스 A 만 누락 | `{"outcome": "recommendable", "selected_sub": {"케이스": "case:b"}, "passes": 1}` | `{"outcome": "recommendable", "selected": {"CPU": "cpu:r5-7600", "GPU": "gpu:good", "RAM": "ram:kit-8x2", "메인보드": "mb:a620", "저장장치": "ssd:1tb", "케이스": "case:b", "쿨러": "cooler:a", "파워": "psu:750"}, "passes": 1}` | 일치 |
| 02 | 모든 후보의 같은 필수 정보 누락 | 모든 케이스 누락(보완 값 없음) | `{"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"], "axes_has": ["psu_length"], "missing_has": ["purchase:케이스.max_psu_length_mm"]}` | `{"outcome": "not_recommendable", "reason_codes": ["required_info_missing"], "axes": ["psu_length"], "missing": ["purchase:케이스.max_psu_length_mm"]}` | 일치 |
| 03 | Pass 소수 | GPU Pass 1개 | `{"outcome": "recommendable", "selected_sub": {"GPU": "gpu:good"}, "pass_counts_sub": {"GPU": 1}, "fail_counts_sub": {"GPU": 2}}` | `{"outcome": "recommendable", "selected": {"CPU": "cpu:r5-7600", "GPU": "gpu:good", "RAM": "ram:kit-8x2", "메인보드": "mb:a620", "저장장치": "ssd:1tb", "케이스": "case:a", "쿨러": "cooler:a", "파워": "psu:750"}, "pass_counts": {"CPU": 3, "GPU": 1, "RAM": 2, "메인보드": 2, "저장장치": 2, "케이스": 2, "쿨러": 2, "파워": 2}, "fail_counts": {"CPU": 0, "GPU": 2, "RAM": 0, "메인보드": 0, "저장장치": 0, "케이스": 0, "쿨러": 0, "파워": 0}}` | 일치 |
| 04 | 전부 Pending | 보완 조회에 값 없음 | `{"outcome": "candidate_shortage", "shortage_sub": {"GPU": {"pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 3}, "fail_reasons": {}}}, "prefilter_enrichment": {"not_found": 3}}` | `{"outcome": "candidate_shortage", "shortage": {"GPU": {"pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 3}, "fail_reasons": {}}}, "prefilter_enrichment": {"not_found": 3}}` | 일치 |
| 04 | 전부 Pending | 보완 경로 없음 | `{"outcome": "candidate_shortage", "shortage_sub": {"GPU": {"pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 3}, "fail_reasons": {}}}, "prefilter_enrichment": {"no_path": 3}}` | `{"outcome": "candidate_shortage", "shortage": {"GPU": {"pending_reasons": {"PENDING_SPEC_MISSING:perf_tier": 3}, "fail_reasons": {}}}, "prefilter_enrichment": {"no_path": 3}}` | 일치 |
| 05 | 전부 Fail | GPU 전부 등급 미달 | `{"outcome": "candidate_shortage", "shortage_sub": {"GPU": {"pending_reasons": {}, "fail_reasons": {"FAIL_PERF_BELOW": 3}}}, "stub_calls": {"prefilter": 0, "combo": 0}}` | `{"outcome": "candidate_shortage", "shortage": {"GPU": {"pending_reasons": {}, "fail_reasons": {"FAIL_PERF_BELOW": 3}}}, "stub_calls": {"prefilter": 0, "combo": 0}}` | 일치 |
| 06 | 선택적 정보만 부족 | TDP 대체·여유 확인 불가 | `{"outcome": "recommendable", "margins_sub": {"power.compat_check": {"status": "available", "cpu_basis": "tdp_fallback"}, "power.total": {"status": "unavailable", "reason": "other_load_basis_missing"}, "cooling": {"status": "unavailable", "reason": "no_comparable_thermal_test"}}}` | `{"outcome": "recommendable", "margins": {"power.compat_check": {"status": "available", "cpu_basis": "tdp_fallback"}, "power.requirement_sizing": {"status": "available"}, "power.total": {"status": "unavailable", "reason": "other_load_basis_missing"}, "size.gpu_length": {"status": "available"}, "size.cooler_height": {"status": "available"}, "size.psu_length": {"status": "available"}, "size.gpu_slots": {"status": "available"}, "size.radiator": {"status": "not_applicable", "reason": "air_cooler"}, "cooling": {"status": "unavailable", "reason": "no_comparable_thermal_test"}}}` | 일치 |
| 07 | 조합 필수 정보만 부족 | 쿨러 냉각 방식 누락 | `{"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"], "pass_counts_sub": {"쿨러": 2}, "passes": 1, "combo_sub": {"filled": 0, "rerun": false}}` | `{"outcome": "not_recommendable", "reason_codes": ["required_info_missing"], "pass_counts": {"CPU": 3, "GPU": 3, "RAM": 2, "메인보드": 2, "저장장치": 2, "케이스": 2, "쿨러": 2, "파워": 2}, "passes": 1, "combo": {"attempted": 2, "filled": 0, "rerun": false}}` | 일치 |
| 08 | 검증 신뢰도 통과지만 필수 호환 미확인 | 신뢰도 ≥ 80, 부적격 | `{"outcome": "not_recommendable", "confidence_min": 80, "passed": false, "eligible": false}` | `{"outcome": "not_recommendable", "confidence": 100, "passed": false, "eligible": false}` | 일치 |
| 09 | 정보 보완 후 복귀 | 사전 필터 보완 복귀 | `{"outcome": "recommendable", "prefilter_enrichment": {"filled": 3}, "returned_to_pass": 3, "pass_counts_sub": {"GPU": 3}, "pending_counts_sub": {"GPU": 0}}` | `{"outcome": "recommendable", "prefilter_enrichment": {"filled": 3}, "returned_to_pass": 3, "pass_counts": {"CPU": 3, "GPU": 3, "RAM": 2, "메인보드": 2, "저장장치": 2, "케이스": 2, "쿨러": 2, "파워": 2}, "pending_counts": {"CPU": 0, "GPU": 0, "RAM": 0, "메인보드": 0, "저장장치": 0, "케이스": 0, "쿨러": 0, "파워": 0}}` | 일치 |
| 09 | 정보 보완 후 복귀 | 조합 보완 뒤 재실행 | `{"outcome": "recommendable", "passes": 2, "combo_sub": {"filled": 2, "rerun": true}}` | `{"outcome": "recommendable", "passes": 2, "combo": {"attempted": 2, "filled": 2, "rerun": true}}` | 일치 |
| 10 | 보완 실패(not_found) | 사전 필터 not_found | `{"outcome": "candidate_shortage", "prefilter_enrichment": {"not_found": 3}}` | `{"outcome": "candidate_shortage", "prefilter_enrichment": {"not_found": 3}}` | 일치 |
| 10 | 보완 실패(not_found) | 조회 예외 | `{"outcome": "candidate_shortage", "prefilter_enrichment": {"failed": 3}, "stub_calls": {"prefilter": 1, "combo": 0}}` | `{"outcome": "candidate_shortage", "prefilter_enrichment": {"failed": 3}, "stub_calls": {"prefilter": 1, "combo": 0}}` | 일치 |
| 10 | 보완 실패(not_found) | 조합 not_found | `{"outcome": "not_recommendable", "passes": 1, "combo_sub": {"filled": 0, "rerun": false}}` | `{"outcome": "not_recommendable", "passes": 1, "combo": {"attempted": 2, "filled": 0, "rerun": false}}` | 일치 |
| 11 | 보완 한도(조합 재실행 1회) | 부분 보완 뒤에도 누락 | `{"outcome": "not_recommendable", "passes": 2, "combo_sub": {"rerun": true}, "stub_calls": {"prefilter": 0, "combo": 1}, "missing_has": ["purchase:케이스.expansion_slots"]}` | `{"outcome": "not_recommendable", "passes": 2, "combo": {"attempted": 2, "filled": 2, "rerun": true}, "stub_calls": {"prefilter": 0, "combo": 1}, "missing": ["purchase:케이스.expansion_slots"]}` | 일치 |
| 12 | 업그레이드 유지 부품 필수 누락(D2) | 유지 부품 정보 완전 | `{"outcome": "recommendable"}` | `{"outcome": "recommendable"}` | 일치 |
| 12 | 업그레이드 유지 부품 필수 누락(D2) | 유지 파워 정격 출력 없음 | `{"outcome": "not_recommendable", "missing_has": ["owned:파워.wattage_w"], "combo_sub": {"filled": 0, "rerun": false}}` | `{"outcome": "not_recommendable", "missing": ["owned:파워.wattage_w"], "combo": {"attempted": 1, "filled": 0, "rerun": false}}` | 일치 |
| 12 | 업그레이드 유지 부품 필수 누락(D2) | 유지 케이스 GPU 허용 길이 없음 | `{"outcome": "not_recommendable", "missing_has": ["owned:케이스.max_gpu_len_mm"]}` | `{"outcome": "not_recommendable", "missing": ["owned:케이스.max_gpu_len_mm"]}` | 일치 |
| 13 | GPU 커넥터 개수 | 필요 개수 정보 누락(보류) | `{"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"], "missing_has": ["purchase:파워.pcie_8pin_count"]}` | `{"outcome": "not_recommendable", "reason_codes": ["required_info_missing"], "missing": ["purchase:파워.pcie_8pin_count"]}` | 일치 |
| 13 | GPU 커넥터 개수 | 확인된 부족(탈락) | `{"outcome": "not_recommendable", "reason_codes_has": ["compat_violation"], "axes_has": ["gpu_connector"]}` | `{"outcome": "not_recommendable", "reason_codes": ["compat_violation", "no_compatible_set"], "axes": ["gpu_connector", "set"]}` | 일치 |
| 13 | GPU 커넥터 개수 | 보조 전원 불필요(비적용) | `{"outcome": "recommendable"}` | `{"outcome": "recommendable"}` | 일치 |
| 14 | 사용자 필수 RAM 속도 | CPU 지원 속도 미확인(보류) | `{"outcome": "not_recommendable", "reason_codes_has": ["required_info_missing"], "axes_has": ["ram_speed"], "missing_has": ["purchase:CPU.max_memory_speed_mts"]}` | `{"outcome": "not_recommendable", "reason_codes": ["required_info_missing"], "axes": ["ram_speed"], "missing": ["purchase:CPU.max_memory_speed_mts"]}` | 일치 |
| 14 | 사용자 필수 RAM 속도 | RAM 속도 미달 | `{"outcome": "not_recommendable", "reason_codes_has": ["requirement_unmet"]}` | `{"outcome": "not_recommendable", "reason_codes": ["requirement_unmet"]}` | 일치 |
| 14 | 사용자 필수 RAM 속도 | 충족 | `{"outcome": "recommendable"}` | `{"outcome": "recommendable"}` | 일치 |
| 14 | 사용자 필수 RAM 속도 | 요구 없음(CPU 속도 미확인) | `{"outcome": "recommendable"}` | `{"outcome": "recommendable"}` | 일치 |
| 15 | 원본 점수 저장·표시 경계 | 0.66449 경계 | `{"display_from_raw": 66.4, "avg_fit": 66.4, "stored_four_digits": 0.6645, "display_from_stored_value_would_be": 66.5, "status_without_snapshot": "unavailable", "status_legacy_run": "legacy_method", "policy_examples_sub": {"0.665": 66.5, "0.605": 60.5}}` | `{"display_from_raw": 66.4, "avg_fit": 66.4, "stored_four_digits": 0.6645, "display_from_stored_value_would_be": 66.5, "status_without_snapshot": "unavailable", "status_legacy_run": "legacy_method", "policy_examples": {"0.665": 66.5, "0.605": 60.5}}` | 일치 |
| 16 | RAM 단품 2개 구성 가격·용량 | 단품 선택·중복 합산 없음 | `{"outcome": "recommendable", "selected_sub": {"RAM": "ram:single-16"}, "ram_pass_pool_sub": {"ram:single-16": {"price": 120000, "capacity_gb": 32, "purchase_qty": 2, "unit_price": 60000}, "ram:kit-16x2": {"price": 140000, "capacity_gb": 32, "purchase_qty": 1, "unit_price": 140000}}, "ram_item_sub": {"price": 120000, "qty": 2, "unit_price": 60000}, "totals_price": 1070000}` | `{"outcome": "recommendable", "selected": {"CPU": "cpu:r5-7600", "GPU": "gpu:good", "RAM": "ram:single-16", "메인보드": "mb:a620", "저장장치": "ssd:1tb", "케이스": "case:a", "쿨러": "cooler:a", "파워": "psu:750"}, "ram_pass_pool": {"ram:kit-16x2": {"price": 140000, "capacity_gb": 32, "purchase_qty": 1, "unit_price": 140000}, "ram:single-16": {"price": 120000, "capacity_gb": 32, "purchase_qty": 2, "unit_price": 60000}}, "ram_item": {"price": 120000, "qty": 2, "unit_price": 60000}, "totals_price": 1070000}` | 일치 |

### 시나리오와 단위 테스트

| # | 시나리오 | 같은 성질을 검증하는 단위 테스트 |
|---|---|---|
| 01 | 일부 후보의 필수 정보 누락 | test_combo_eligibility.py::test_search_skips_combos_missing_required_info_and_counts_the_pruning |
| 02 | 모든 후보의 같은 필수 정보 누락 | test_combo_eligibility.py::test_required_key_empty_for_every_candidate_is_still_checked<br>test_combo_eligibility.py::test_a_slot_blocked_for_every_candidate_skips_the_search_entirely |
| 03 | Pass 소수 | test_candidate_eligibility.py::test_single_pass_does_not_promote_pending_into_keep |
| 04 | 전부 Pending | test_candidate_eligibility.py::test_all_pending_without_enrich_is_shortage_with_no_path_records<br>test_candidate_eligibility.py::test_not_found_keeps_candidate_held |
| 05 | 전부 Fail | test_candidate_eligibility.py::test_all_fail_is_shortage_without_promotion_and_counts_fail_prefixes |
| 06 | 선택적 정보만 부족 | test_build_margins.py::test_missing_max_power_falls_back_to_tdp_and_records_the_limit<br>test_build_margins.py::test_total_is_unavailable_without_a_documented_other_load_and_keeps_the_known_load<br>test_build_margins.py::test_cooling_is_always_unavailable_with_inputs_and_no_tdp_difference_value |
| 07 | 조합 필수 정보만 부족 | test_combo_eligibility.py::test_cooling_type_unknown_is_itself_the_missing_key<br>test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run |
| 08 | 검증 신뢰도 통과지만 필수 호환 미확인 | test_combo_eligibility.py::test_required_missing_blocks_even_when_the_penalty_accounting_is_quiet<br>test_combo_eligibility.py::test_single_violation_at_confidence_80_is_not_passed_and_not_eligible |
| 09 | 정보 보완 후 복귀 | test_candidate_eligibility.py::test_enrichment_that_fills_the_missing_key_returns_the_candidate_to_pass_and_it_is_scored<br>test_combo_eligibility.py::test_filled_missing_info_reruns_once_and_becomes_eligible |
| 10 | 보완 실패(not_found) | test_candidate_eligibility.py::test_not_found_keeps_candidate_held<br>test_candidate_eligibility.py::test_enrich_exception_is_recorded_as_failed_and_not_retried<br>test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run |
| 11 | 보완 한도(조합 재실행 1회) | test_combo_eligibility.py::test_filled_missing_info_reruns_once_and_becomes_eligible<br>test_combo_eligibility.py::test_unfillable_missing_info_is_saved_as_a_diagnostic_result_without_a_second_run |
| 12 | 업그레이드 유지 부품 필수 누락(D2) | test_combo_eligibility.py::test_upgrade_kept_psu_without_wattage_holds_the_combo_and_names_the_owned_part<br>test_combo_eligibility.py::test_upgrade_kept_case_without_gpu_length_holds_but_a_known_length_is_fine<br>test_combo_eligibility.py::test_upgrade_with_every_needed_kept_part_value_is_eligible |
| 13 | GPU 커넥터 개수 | test_combo_eligibility.py::test_connector_count_missing_on_the_needed_path_is_required_missing<br>test_combo_eligibility.py::test_confirmed_connector_shortage_is_a_violation_not_a_gap<br>test_combo_eligibility.py::test_gpu_without_aux_power_makes_connector_checks_not_applicable |
| 14 | 사용자 필수 RAM 속도 | test_combo_eligibility.py::test_ram_speed_user_requirement_needs_cpu_supported_speed<br>test_combo_eligibility.py::test_ram_speed_confirmed_shortfall_is_requirement_unmet_even_if_something_else_is_missing<br>test_combo_eligibility.py::test_ram_speed_user_requirement_met_when_all_three_support_it<br>test_combo_eligibility.py::test_ram_speed_without_user_requirement_keeps_the_existing_caution_and_is_not_required |
| 15 | 원본 점수 저장·표시 경계 | test_fit_score.py::test_display_points_boundaries<br>test_fit_score.py::test_raw_066449_shows_664_in_api_and_explanation_never_665<br>test_fit_score.py::test_snapshot_missing_or_invalid_is_unavailable_never_the_stored_score |
| 16 | RAM 단품 2개 구성 가격·용량 | test_ram_pair_config.py::test_single_module_becomes_two_modules_without_touching_the_original<br>test_ram_pair_config.py::test_as_pair_is_idempotent_so_price_and_capacity_are_never_summed_twice<br>test_ram_pair_config.py::test_stage4_items_carry_qty_and_unit_price_and_totals_sum_the_pair_price |

주의: 대체 조회 스텁은 어떤 키든 채울 수 있지만 실제 저장소 보완은 슬롯별로 채울 수 있는 키가 제한적이다(`live_spec_lookup.SLOT_FIELDS`). 시나리오 9·11의 "채움"은 보완 흐름(재판정·한 번 재실행·한도)의 재현이지 실제 보완 성공률이 아니다.

## 6. 해석

**1단계 — 예산 사용률이 오른 이유.** 같은 108개 요청으로 비교하면 평균 예산 사용률이 기준선 68.76%에서 1단계 77.28%로, 평균 CPU 등급은 6.30에서 7.27로, GPU 등급은 4.93에서 6.42로 올랐다(4.4, 3장 표). 새 가격식 `B/(B+P)`는 참고 예산을 넘는 가격에서도 0이 되지 않고 가격 차이에 따라 점수가 계속 떨어진다. 옛 식 `max(0, 1−P/B)`는 참고 예산 이상이면 모두 0점이라 비싼 부품끼리 가격 축에서 구분되지 않았고, 대신 성능 가중이 0.25에서 0.30으로, 리뷰가 0.20에서 0.25로 오르고 목표 초과 성능을 깎던 밸런스 축이 사라졌다. 같은 예산에서 더 높은 등급의 부품이 이기는 것이 이 변화의 정상적인 결과이며, 구현 계획 §6의 위험("가격 축이 예산 초과 구간에서도 0이 아니게 되어 더 비싼 부품이 선택될 수 있다")이 실제로 나타난 것이다. 가중치는 정책대로 휴리스틱 초기값이므로 조정은 별도 검증으로 한다. 1단계에서 선택이 바뀐 요청은 103건(81.7%)이다.

**2단계.** 선택 부품은 1단계와 같다(변경 0건). 달라진 것은 업그레이드 `RAM+메인보드` 요청 1건이 후보 부족(`CandidateShortage`)으로 끝난 것뿐이다. 사전 필터 Pending(GPU 약 11개/요청, 성능 등급 없음)은 기준선에서도 Pass가 충분해 승격되지 않았으므로 승격 삭제가 일반 요청의 결과를 줄이지 않았다(구현 계획 F2와 일치).

**3단계 — RAM이 단품 2개로 바뀐 이유.** 기준선과 1단계에서는 RAM이 모두 qty=1이었고, 3단계부터 124건 모두 단품 2개 구성(qty=2)이다. 이 카탈로그에서 같은 규격·총용량이라면 단품 2개가 키트보다 싼 경우가 있고(DDR5 32GB: 키트 759,000원 대 단품 2개 671,040원, DDR4 16GB: 229,990원 대 159,800원), DDR5 16GB에는 키트가 없다(4.5의 마지막 표). 듀얼채널 가산점이 사라져 키트가 점수로 우대받지 못하므로 가격 축에서 싼 쪽이 이긴다. 선택 RAM의 평균 구성 가격이 346,890원에서 319,309원으로 내렸고, 직전 단계 대비 GPU가 바뀐 요청이 16건(기준선 대비로는 67건에서 79건), 평균 GPU 등급이 6.42에서 6.61로 올랐다(RAM에서 아낀 예산이 다른 슬롯의 선택에 영향을 준 것으로 보이며, 이 덤프만으로 인과를 분리하지는 않았다). DDR4 32GB에서는 반대로 키트(176,000원)가 단품 2개(359,780원)보다 훨씬 싸다. 두 구성을 같은 기준으로 비교하는 것이 3단계의 목적이며, 가격만으로 단품이 항상 이기는 것은 아니다.

**4a — 적격성.** 정상 추천 108건(85.7%), 부적격 17건(13.5%), 후보 부족 1건(0.8%)이다. 부적격 17건은 모두 `budget_exceeded`이고, 기준선에서 총액이 예산을 넘던 17건과 같은 요청이다(1단계 이후에도 동일): 예산 100만 원의 게임·창작 16건과 4K 150만 원 1건처럼 예산이 최저가 호환 구성보다 낮은 요청이다. 정책 이전에는 이런 결과가 그대로 "추천"으로 나갔지만 이제는 진단용 부품표와 `not_recommendable`로 구분된다. 필수 정보 누락 가지치기(`pruned_required_missing`)는 124개 요청에서 발생했으나 선택 부품을 바꾸지는 않았다.

**저소음.** 기준선은 `noise_sensitive`가 바깥 가중치를 바꿔 60쌍 중 45쌍에서 가중치가 달랐고 32쌍에서 선택이 달랐다. 이제 바깥 가중치는 달라지지 않고(0쌍) 선택이 다른 쌍은 1쌍뿐이다(creation·성능 우선·350만 원에서 GPU만 다름). 대신 선택 부품의 리뷰 프로필에서 정숙성 요청 가중 합이 가성비·성능·미지정 우선순위에서 평균 0.707 커지고, 저소음 우선순위에서는 0이다(이미 정숙성을 높게 요청하므로 중복 배율이 없다). 정숙성 요청 가중이 커졌는데도 선택이 거의 바뀌지 않은 것은, 선택 부품 중 정숙성 근거가 점수에 기여한 비율이 noise=0 193/513, noise=1 180/480으로 비슷하다는 데서 보듯 이 요청 집합에서는 정숙성 근거가 후보 순위를 가르는 정도가 작다는 뜻이다. 원인(관측 부족인지 후보 간 차이가 작은지)은 이 덤프로 가려지지 않는다. 저소음 요청이 선택을 크게 바꾸지 않는 것 자체를 오류로 보지는 않는다.

**필수 조건.** 정상 추천 108건에서 예산 초과·최소 성능 미달·호환 위반·필수 정보 누락 사유가 모두 0건이다. 기준선에서는 같은 검사로 19건(예산 초과 17, 업그레이드 `RAM+메인보드`의 호환 위반 2)이 나왔다. 기준선과 단계별 덤프는 성능 하한 정보(`target_floors`)가 없어 성능 미달 검사는 최종 덤프에서만 실제로 수행되었다(4.8의 마지막 열).

**성능 우선에서 예산이 늘 때 총가격.** 기준선·최종 모두 5개 용도에서 예산 100만→200만→350만 원일 때 총가격이 줄지 않는다(4.4). 이 비교는 `test_data_coverage.py`의 xfail 테스트(`test_a_bigger_budget_never_gets_a_cheaper_performance_build`)와 같은 기준(−5% 허용)이다. 1단계 이후 그 테스트가 xpass(strict=False)로 바뀐 것은 옛 가격식이 참고 예산 이상에서 0점으로 포화되던 문제가 새 식에서 사라진 결과로 보인다. 7장에서 마커 제거를 권고한다.

**처리 시간.** 최종은 평균 626ms, p50 320ms, p90 1,322ms, 최대 5,124ms다. 가장 오래 걸린 요청들은 상위 후보에서 해가 없어 전체 풀로 넓힌 요청(`widened`)이다(55개 요청). 기준선·단계별 시간은 측정 조건이 달라 비교하지 않는다(4.12).

## 7. 알려진 한계와 범위 밖 결함

이번 단계는 엔진 동작을 바꾸지 않으므로 아래는 고치지 않고 기록한다.

- **업그레이드 `upgrade|RAM+메인보드`가 2단계 이후 후보 부족.** 유지 CPU가 AM4인데 RAM·메인보드 요구가 기본 DDR5로 남는 기존 결함(`owned_parts.constrain_targets`)이다. 메인보드 후보가 소켓 불일치 35개, 폼팩터 불일치 3개, 메모리 규격 불일치 7개(사유 중복 집계)로 모두 탈락한다. 기준선에서는 이 결함이 호환 위반 진단 결과(`memory=fail`)로 나갔다.
- **업그레이드에서 유지 부품 정보를 일부만 입력하면 D2에 따라 대부분 부적격**이다(확인용 구성으로 제공). 고정 시나리오 12가 이 동작을 재현한다.
- **확대 탐색이 노드 상한 근처까지 가면 수 초 걸리는 요청이 있다.** 최종 덤프에서 상한(150,000)에 닿은 요청은 없지만 확대 탐색은 55개 요청에서 발생했고 최대 5.1초가 걸렸다. 1·2단계 덤프에는 상한에 닿은 요청이 있었다.
- **부적격 안내 문장은 요약 앞에 저장되고, 부품 교체 뒤 다시 쓰지 않는다.** 현재 상태는 API의 `eligibility` 필드를 본다.
- **조합 보완 저장소가 채울 수 있는 키는 슬롯별로 제한적이다**(`live_spec_lookup.SLOT_FIELDS`). GPU `perf_tier` 같은 키는 조회 경로가 없어 모든 보완 시도가 `no_path`이며, 개발 카탈로그의 성능 등급 없는 GPU 약 11개는 계속 평가에서 빠진다.
- **개발 DB 요청에서는 필수 정보 누락 부적격이 관측되지 않아** 누락 키 분포·조합 보완 성공률은 고정 시나리오로만 검증했다. 카탈로그 값이 바뀌면 달라질 수 있다.
- **단계별 덤프의 형식·측정 조건이 최종과 다르다.** 보완 기록·리뷰 근거·성능 하한이 없고 처리 시간의 측정 조건이 기록되지 않았다.
- **고정 시나리오는 합성 카탈로그와 스텁 보완**이라 실제 카탈로그·저장소 동작의 대체가 아니다.
- **`test_data_coverage::test_a_bigger_budget_never_gets_a_cheaper_performance_build`가 1단계 이후 xpass(strict=False).** 마커를 지워도 된다고 판단한다. 근거: (1) 옛 문제의 원인이던 가격 축 포화가 새 식에서 없어졌고, (2) 개발 DB 덤프의 5개 용도 모두 같은 기준을 만족하며(4.4), (3) 이번 전체 테스트(통과 2,827건)와 단독 재실행에서 모두 xpass였다. 다만 이 단계에서는 지우지 않았다. 지우면 이후 회귀가 xfail로 가려지지 않고 실패로 드러난다.

이번 작업 중 함께 고친 기존 결함: 결과 품목 순서가 부품 교체·수량 변경·개정 복제 뒤에 바뀌던 문제를 522c1ffd에서 `slot_structure` 순서(→ 슬롯 이름 → created_at → id)로 고정했다. 한 run의 후보 행이 한 트랜잭션에서 같은 `created_at`으로 INSERT되고 `plan_node.position`이 대개 0이라 정렬이 물리 저장 순서에 맡겨져 있었고, 이 때문에 `test_cloned_revision_…`가 간헐 실패했다.

## 8. 다음 실험

- **D5 — 전체 후보 풀 탐색.** 기본 탐색을 슬롯별 상위 N개에서 전체 Pass 풀로 넓히는 실험. 구현 계획 F7(4개 요청에서 최대 4,198노드·86ms)의 측정을 126개 요청으로 넓혀 요청별 선택 차이와 탐색 노드 수·시간을 함께 기록한다. 이 문서의 `widened`/`capped` 카운터와 처리 시간이 비교 기준선이다.
- **광고 가산점(6단계).** 정책 §8 — 원래 추천 점수 S와 선택용 점수를 분리하고 ε 이내 유효 조합에서만 우대. 이 문서의 선택 부품 변화·avg 점수 표를 "광고 없음" 기준선으로 쓴다. 전체 후보 풀 탐색(D5)이 전제다.
- **가중치·가격식 검증.** 정책은 가중치를 휴리스틱 초기값으로 두었다. 1단계에서 확인된 예산 사용률 상승(같은 108건 68.76% → 76.21%)이 의도한 범위인지 점수 시뮬레이션으로 확인하고, 필요하면 가격 민감도 `α`를 별도 실험으로 다룬다.
- **보완 경로 확대.** GPU 성능 등급처럼 저장소가 다루지 않는 키의 보완 경로는 이번 범위 밖(범용 수집기 금지)이다. 수집 경로를 추가하면 Pass 복귀율을 이 문서와 같은 표로 다시 측정한다.
- **업그레이드 `constrain_targets` 결함 수정 뒤 재측정.** `RAM+메인보드` 요청이 정상 추천으로 돌아오는지, 유지 부품 정보 입력 정도별 정상 추천 비율을 본다.

<!--
  남은 일: 7번 시연 영상 유튜브 링크, 6번 기능별 화면 캡처,
  11.2 시드 데이터 구글 드라이브 링크, 13번 운영비 수치, 15번 참고 문서(데이터 수집 과정) 링크 (TODO 표시 부분)
  이전 README(개발자용 실행·설정 메모 전체)는 git 기록에 있다:  git log --oneline -- README.md 로 커밋을 찾아 git show <커밋>:README.md
-->

<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/src/assets/truefit-logo.png">
    <img src="web/src/assets/truefit-logo-light.png" alt="TrueFit" width="360">
  </picture>
</h1>

<p align="center">목적에 맞는 PC와 주변기기를 <b>근거와 함께</b> 고르는 쇼핑 플래너</p>

## 목차

| 프로젝트 이해 | 구현 · 실행 · 검증 |
|:---|:---|
| 1. [프로젝트 소개](#1-프로젝트-소개) | 9. [주요 API](#9-주요-api) |
| 2. [문제 정의](#2-문제-정의) | 10. [데이터베이스](#10-데이터베이스) |
| 3. [기대 효과](#3-기대-효과) | 11. [설치 및 실행](#11-설치-및-실행) |
| 4. [수집 데이터 및 전처리](#4-수집-데이터-및-전처리) | 12. [테스트와 평가](#12-테스트와-평가) |
| 5. [프로젝트 구조](#5-프로젝트-구조) | 13. [운영비](#13-운영비) |
| 6. [주요 기능](#6-주요-기능) | 14. [기술 스택](#14-기술-스택) |
| 7. [시연 영상](#7-시연-영상) | 15. [참고 문서](#15-참고-문서) |
| 8. [아키텍처](#8-아키텍처) | 16. [팀원](#16-팀원) |
| | 17. [라이선스](#17-라이선스) |

---

## 1. 프로젝트 소개

TrueFit은 사용자가 말한 **용도·예산·취향**을 조건으로 읽어 새 컴퓨터 본체와 주변기기(모니터·키보드·마우스·스피커)를 추천하고, 이미 받은 견적서를 점검해 주는 서비스입니다. 조건 대화 → 추천 → 확정 → 리포트까지 한 브라우저 화면에서 이어집니다.

스펙이 같아도 사람마다 맞는 제품은 다릅니다. 그래서 TrueFit은 스펙표만으로 고르지 않고, **실제 구매자 리뷰와 커뮤니티 사용기**를 분석해 그립감·키감·소음 같은 사용감과 손 크기·용도 같은 **사용자 성향**까지 추천 점수에 반영합니다.

- **새 컴퓨터 본체 추천**: 대화로 받은 조건으로 부품 구성을 추천하고 호환·예산을 검사합니다.
- **받은 견적 점검**: 사진·텍스트 견적서를 인식해 호환성·가격·용도 적합성을 평가합니다.
- **주변기기 견적**: 리뷰·사용기 근거와 함께 모니터·키보드·마우스·스피커를 추천합니다.
- **커뮤니티**: 사용기를 올리고, 거기서 뽑은 체감·성향이 추천에 반영됩니다.

## 2. 문제 정의

### 2.1 부품을 고르고 호환을 맞추는 일이 너무 복잡합니다

본체 하나를 맞추려면 CPU·메인보드·RAM·GPU·SSD·파워·케이스·쿨러 **8종 부품**을 고르고, 소켓·메모리 규격·전력·케이스 크기 같은 **호환 조건**을 모두 맞춰야 합니다. 그러나 시판되는 부품 수는 **총 8,163개**입니다.

<sub>다나와 가격비교 카테고리별 등록 상품 수 합계(2026-10-21 조회, 가격 미표시 상품 포함): CPU 517 · 메인보드 1,130 · RAM 649 · 그래픽카드 861 · SSD 1,027 · 파워 1,302 · 케이스 1,357 · CPU 쿨러 1,320(공랭 917 + 수랭 403)</sub>

### 2.2 받은 견적이 내 용도에 맞는지 확인할 방법이 없습니다

- 판매점 견적서에는 부품 이름과 금액만 적혀 있을 뿐, **부품끼리 호환되는지, 내 용도에 비해 과하거나 부족한 부품은 없는지**는 나와 있지 않습니다.
- 비전문가는 이를 검증할 수단이 없어, 커뮤니티에 견적을 올려 답을 기다리거나 받은 견적을 그대로 믿고 구매합니다.

### 2.3 스펙이 같아도 사람마다 맞는 제품이 다릅니다

- 마우스 그립감, 키보드 키감·키압, 스피커 소음처럼 **사용감은 스펙표에 나오지 않습니다.** 같은 마우스라도 손 크기와 쥐는 방식에 따라 평가가 갈리고, 같은 키보드라도 사무용인지 게임용인지에 따라 맞는 제품이 다릅니다.
- 그래서 구매자는 스펙 밖의 정보를 후기에서 찾습니다. 온라인 쇼핑 경험자 500명 중 **97.2%가 구매 전 후기를 확인**합니다. ([한국소비자연맹 조사, 소비자경제 2022-01-11](https://www.dailycnc.com/news/articleView.html?idxno=209683))
- 하지만 제품마다 수백 건씩 쌓인 후기에서 **나와 비슷한 사람의 경험**만 골라 읽기는 어렵고, 기존 추천은 스펙과 별점 순위만 보여 줄 뿐 사용자 성향을 반영하지 않습니다.

### 2.4 그래서 TrueFit이 푸는 문제

| 문제 | TrueFit의 해결 방식 |
|---|---|
| 부품을 고르고 호환을 맞추기 어렵다 (2.1) | 대화로 용도·예산을 받고, **규칙 기반 엔진**이 수천 개 부품 중 후보를 걸러 호환 검사·예산 최적화까지 계산해 완성된 구성을 제안 |
| 받은 견적을 검증할 수 없다 (2.2) | 사진·텍스트 견적서를 인식해 **호환성·용도 적합성**을 점검하고, 아쉬운 부품은 교체 후보와 나란히 비교 |
| 스펙만으로는 나에게 맞는 제품을 고를 수 없다 (2.3) | 구매 리뷰 5,653건과 커뮤니티 사용기에서 **사용감·체감 근거**를 뽑아, 손 크기·용도 같은 **성향이 같은 사용자의 평가**를 추천 점수에 반영 |

## 3. 기대 효과

| 해결한 문제 | 기대 효과 |
|---|---|
| 부품을 고르고 호환을 맞추기 어렵다 (2.1) | **구매 진입 장벽 완화와 결정 시간 단축.** 부품 지식 없이도 "배그 할 거고 150만 원"처럼 말하면 호환이 확인된 구성을 받습니다. 견적 질문 글을 올리고 답을 기다리던 과정이 대화 몇 번으로 줄어듭니다. |
| 받은 견적을 검증할 수 없다 (2.2) | **잘못된 구성 구매 예방.** 사기 전에 호환 문제와 용도에 비해 과하거나 부족한 부품을 짚어 주고, 같은 예산의 더 나은 대안을 보여 줘 판매점 견적을 스스로 판단할 수 있게 합니다. |
| 스펙만으로는 나에게 맞는 제품을 고를 수 없다 (2.3) | **개인 성향에 맞는 추천과 구매 후 후회 감소.** "손이 작아서 가벼운 마우스"처럼 말하면 비슷한 사용자의 체감 평가까지 반영해, 스펙은 맞는데 손에 안 맞는 제품을 사는 일을 줄입니다. 추천 이유에 리뷰·사용기 원문을 함께 보여 줘 사용자가 직접 납득할 수 있습니다. |

## 4. 수집 데이터 및 전처리

> 데이터별 수집 방법과 전처리 세부 규칙은 [데이터 수집 및 전처리](docs/데이터_수집_및_전처리.md) 문서에 정리했습니다.

### 4.1 데이터 한눈에 보기

| 데이터 | 원본 규모 | 시스템 적재 | 쓰이는 곳 |
|---|---|---|---|
| PC 부품 카탈로그 | 8종 322행 (`parts_list_modify.xlsx`) | 319종 (중복 3행 제거) | 본체 추천 후보, 호환 검사, 받은 견적 매칭 |
| 주변기기 카탈로그 | 4종 203행 (`*_processed.csv`) | 203종 | 주변기기 추천 후보, 모니터↔PC 포트 검사 |
| 제품 리뷰 | 14,825건 (`data/reviews/*.jsonl`) | 5,653건 | 리뷰 관점 점수, 추천 이유 인용 |
| 리뷰 관점 규칙 | — | 102개 (PC 부품 82 · 주변기기 20) | 리뷰에서 무엇을 읽을지 정의 |
| 커뮤니티 예시 사용기 | 200편, 이미지 111장 | 체감 문장 2,875개 + 임베딩 | 주변기기 체감 점수, 커뮤니티 화면 |
| 게임 요구 사양 | `game_requirements.json` | 설정 파일 | 용도(게임)별 최소·권장 사양 판정 |

### 4.2 전체 흐름

```text
[수집]    다나와 부품표 · 주변기기 스펙 · 구매 리뷰 · 커뮤니티 사용기
   ▼
[정리]    카탈로그 제품과 매칭 · 중복 제거 · 표기 정규화 · 모르는 값은 비워 둠
   ▼
[구조화]  리뷰·사용기 → LLM이 "어떤 제품의 어떤 사용감이 좋았다/나빴다"와 원문 근거 문장을 추출
   ▼
[적재]    PostgreSQL 카탈로그·근거 테이블 + pgvector 임베딩
   ▼
[활용]    후보 필터·호환 검사 / 추천 점수의 리뷰·체감 비중 / 추천 이유의 원문 인용
```

### 4.3 전처리 원칙

- **추측해서 채우지 않습니다.** 스펙의 `-`·빈 칸·`미표기`는 비워 두고, 엔진은 그 값을 "모름"으로 판정합니다. 판매처·관측일이 없는 가격은 참고가로만 보관합니다.
- **실제로 써 본 경험만 근거로 씁니다.** 리뷰에서 스펙 설명, 배송·포장 불만처럼 사용 경험이 아닌 문장은 버리고, 근거가 없는 리뷰는 억지로 점수를 만들지 않습니다.
- **원본이 기준입니다.** 카탈로그는 원본 파일에서 언제든 다시 만들 수 있고, 다시 적재해도 중복이 생기지 않습니다. 리뷰·사용기 분석 결과는 시드로 묶어 팀원 모두 같은 결과를 씁니다.

## 5. 프로젝트 구조

```text
skn_final/
├── web/        # React + Vite + TypeScript 화면
├── src/        # FastAPI 서버
│   ├── routers/    # API 라우터
│   ├── engine/     # 추천 엔진 (호환 검사·점수·최적화)
│   ├── agent/      # AI 에이전트
│   ├── services/   # 서비스 로직
│   ├── workers/    # 배치 워커 (임베딩·사용기 분석)
│   └── ...
├── db/         # 마이그레이션, 시드
├── config/     # 카테고리·주변기기·엔진 규칙
├── data/       # 시드 데이터
├── deploy/     # 배포 설정
├── docs/       # 기획·설계 문서
├── tests/      # pytest
└── docker-compose.yml
```

## 6. 주요 기능

<!-- 기능마다 같은 틀: 한 줄 요약 → 이런 분께 → 사용 흐름 → 핵심 포인트 → 캡처(GIF 권장) -->

### 6.1 새 컴퓨터 본체 추천

> 말로 조건을 주면, 호환이 확인된 부품 구성을 예산 안에서 만들어 줍니다.

**이런 분께**: 부품을 잘 모르지만 용도와 예산은 정해 둔 분

**사용 흐름**

1. "배그랑 영상 편집, 150만 원 정도"처럼 용도·예산을 말합니다. 빠진 조건은 AI가 되묻습니다.
2. 8종 부품 구성과 호환 검사 결과, 예산 사용 현황이 나옵니다.
3. 결과 화면에서 "더 싸게", "GPU 좀 더 좋게"처럼 이어 말하거나, 부품을 직접 바꾸고 수량을 조정합니다.
4. 가지고 있는 부품은 빼고 나머지만 추천받을 수 있습니다.

**핵심 포인트**

- 호환 검사를 **통과 / 확인 못 함 / 해당 없음**으로 나눠 보여 줍니다.
- 게임 요구 사양과 비교해 용도에 맞는지 판정합니다.
- 부품마다 추천 이유와 리뷰 인용, 점수 비중을 함께 보여 줍니다.

<!-- TODO: 캡처 -->

### 6.2 받은 견적 점검

> 판매점에서 받은 견적서를 사진이나 글로 올리면, 사도 되는 견적인지 점검해 줍니다.

**이런 분께**: 견적을 받았는데 호환되는지, 가격이 적당한지 확인하고 싶은 분

**사용 흐름**

1. 견적서 사진(여러 장 가능)이나 텍스트를 올립니다.
2. 인식된 부품 목록을 확인하고, 잘못 읽은 항목은 고칩니다.
3. 호환성·가격·용도 적합성 종합 평가를 받습니다.
4. 아쉬운 부품은 교체 후보와 나란히 비교하고, 일부만 바꿔 확정합니다.
5. 결과를 보며 궁금한 점을 대화로 묻습니다.

**핵심 포인트**

- DB에 없는 부품은 실시간으로 스펙을 찾아 임시로 점검에 씁니다.
- 가격을 읽지 못한 부품은 합계에서 빼고 "금액 미인식"으로 표시합니다.
- 바꾼 부품과 그대로 둔 부품이 리포트에 구분되어 저장됩니다.

<!-- TODO: 캡처 -->

### 6.3 주변기기 견적

> 모니터·키보드·마우스·스피커를 말로 고르면, 스펙과 실제 사용자 체감을 근거로 추천합니다.

**이런 분께**: 스펙표만으로는 손에 맞을지, 소리가 어떨지 알기 어려운 분

**사용 흐름**

1. "손이 작아서 가벼운 무선 마우스, 6만 원 이상"처럼 말합니다.
2. 종류별 후보와 순위(몇 개 중 몇 위), 근거가 나옵니다.
3. 마음에 안 드는 브랜드나 조건은 이어 말해 바꿉니다.
4. 고른 주변기기를 장바구니에 담습니다.

**핵심 포인트**

- 근거를 **스펙 · 리뷰 인용 · 커뮤니티 사용기 체감 · 점수 비중**으로 나눠 보여 줍니다.
- 모니터는 내 PC 그래픽카드 포트(HDMI·DP·USB-C)와 맞는지 검사합니다.
- 좋아하거나 피하고 싶은 브랜드를 기억해 다음 추천에 반영합니다.
- 예산을 넘으면 결과 화면에서 바로 알려 줍니다.

<!-- TODO: 캡처 -->

### 6.4 장바구니 · 확정 · 리포트

> 본체와 주변기기를 한 번에 확정하고, 추천 이유까지 담긴 리포트로 남깁니다.

**사용 흐름**: 장바구니에서 본체와 주변기기를 합쳐 확인 → 확정 → 리포트 생성 → 저장한 견적에서 다시 열어 수정

**핵심 포인트**

- 확정 당시의 스펙·근거·점수가 그대로 저장되어, 나중에 열어도 같은 설명을 볼 수 있습니다.
- 리포트는 하나씩 지울 수 있고, 같은 대화에서 여러 번 확정할 수 있습니다.

<!-- TODO: 캡처 -->

### 6.5 커뮤니티 · 마이페이지

> 사용기를 나누는 게시판이자, 추천의 체감 근거가 쌓이는 곳입니다.

**핵심 포인트**

- 질문·사용기·팁·자유 게시판, 글에 제품 연결과 이미지 첨부, 좋아요·저장·댓글 알림
- 사용기에 연결된 제품은 체감 근거로 분석되어 주변기기 추천에 반영됩니다.
- 마이페이지에서 내 PC, AI 상담 기록, 추천 리포트, 내가 쓴 글·저장한 글을 모아 봅니다.

<!-- TODO: 캡처 -->

## 7. 시연 영상

<!-- TODO: 유튜브 링크를 아래 두 곳에 넣기 (VIDEO_ID 교체) -->

[![TrueFit 시연 영상](https://img.youtube.com/vi/VIDEO_ID/0.jpg)](https://www.youtube.com/watch?v=VIDEO_ID)

▶ [유튜브에서 보기](https://www.youtube.com/watch?v=VIDEO_ID)

## 8. 아키텍처

사용자의 말은 AI 에이전트가 조건으로 읽고, 추천 결과는 규칙 기반 엔진이 DB의 부품·리뷰 근거로 계산합니다. AI는 문장을 이해하고 설명을 쓰는 데 쓰고, 호환 판정과 점수는 코드와 데이터로 정합니다.

```mermaid
flowchart LR
    U[사용자 브라우저] --> W[화면<br/>React + Vite]
    W -->|REST API| A[FastAPI 서버<br/>src/api.py]
    A --> E[추천 엔진<br/>호환 검사 · 점수 · 최적화]
    A --> G[AI 에이전트<br/>조건 해석 · 결과 대화 · 견적 점검]
    G -->|LLM 호출| L[(OpenAI)]
    E --> D[(PostgreSQL + pgvector<br/>카탈로그 · 리뷰 근거 · 견적 · 계정 · 커뮤니티)]
    A --> D
```

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| 화면 | `web/` | 대화·추천 결과·장바구니·리포트·커뮤니티 화면. 빌드 결과(`web/dist`)를 서버가 같은 주소로 서빙 |
| 서버 | `src/` | API, 추천 엔진, 서비스, AI 에이전트 |
| 데이터베이스 | `db/` | 마이그레이션, 시드(부품 카탈로그·주변기기·리뷰 근거) |
| 설정·데이터 | `config/`, `data/` | 카테고리·주변기기 규칙, 시드 데이터 |
| 테스트 | `tests/` | pytest |

### 8.1 새 컴퓨터 본체 추천 단계 (`src/engine/`)

| 단계 | 하는 일 |
|---|---|
| 1. 의도 분해 | 대화에서 용도·예산·우선순위를 뽑고 빠진 항목을 되묻는다(슬롯 채우기) |
| 2. 요구 사양 | 조건을 부품별 요구 사양으로 바꾼다 |
| 3-0. 후보 수집 | 카탈로그에서 후보를 모은다 |
| 3-A. 하드 필터 | 조건을 못 지키는 후보를 통과 / 탈락 / 보류로 가른다 |
| 3-B. 순위 | 적합도와 병목을 보고 후보 순위를 정한다 |
| 3-C. 검증 | 규칙으로 호환을 판정하고, 쟁점을 문장으로 쓴다 |
| 4. 세트 최적화 | 예산 안에서 부품 조합을 고른다 |
| 5. 설명 생성 | 추천 이유와 근거를 문장으로 만든다 |
| 6. 되먹임 | 사용 결과를 모아 다음 추천에 반영한다(별도 오프라인 배치) |

### 8.2 주변기기 추천 단계 (`src/engine/peripheral_*.py`)

본체와 같은 단계 구조를 따르되, 한 문장 입력 해석과 **체감 점수**(리뷰 + 커뮤니티 사용기)가 더해집니다. 종류별 규칙·가중치는 `config/peripherals.yaml`에 있습니다.

| 단계 | 하는 일 | 모듈 |
|---|---|---|
| 1. 문장 해석 | "손이 작아서 가벼운 무선 마우스"를 목적·상황·스펙 조건으로 읽는다. 값은 설정에 정해진 목록 안에서만 고르고, **직접 말한 조건**과 **목적에서 풀어낸 조건**을 나눈다(LLM 에이전트, 꺼져 있으면 단어 규칙) | `peripheral_intent` |
| 1-1. 결과 화면 명령 | "키보드는 빼줘", "3만원 더 싸게", "처음부터 다시" 같은 명령을 모델 없이 낱말로 처리한다 | `peripheral_commands` |
| 2. 요구 사양 | 조건을 종류별 거르기 조건(hard)과 선호(soft)로 바꾼다. 목적에서 풀린 조건은 항상 선호로만 둬, 해석이 틀려도 제품이 사라지지 않게 한다 | `peripheral_requirement` |
| 3-0. 후보 수집 | 카탈로그에서 후보를 모으고 원문 스펙(DPI·폴링레이트 등)을 판정용 값으로 바꾼다. 못 읽은 값은 "모름"으로 둔다 | `peripheral_catalog`, `peripheral_parse` |
| 3-A. 하드 필터 | 거르기 조건에서 탈락한 후보만 뺀다. 남는 후보가 없어도 조건을 몰래 완화하지 않는다 | `peripheral_select` |
| 3-B. 순위 | 점수 = Σ(축 가중치 × 축 값) − 감점. 축은 **스펙 기준 · 체감(리뷰) · 가격 · 브랜드 · 무상 AS**. 강조한 축은 가중치 ×1.5, 근거가 5건 미만이면 점수에서 감점 | `peripheral_select` |
| 3-B'. 체감 점수 | 외부 리뷰 긍정·부정 수와 커뮤니티 사용기 체감을 합쳐 계산한다. 손 크기·용도가 **같은 조건의 사용자 평가**를 먼저 보고, 표본이 적으면 전체 평균 쪽으로 당겨 과신하지 않는다 | `peripheral_feel` |
| 3-C. 교차 검사 | 모니터를 고르면 PC와 맞는지 본다: 목표 해상도, 그래픽카드와의 HDMI·DP 대역폭, USB-C 영상 출력 | `peripheral_cross` |
| 4. 조합 | 주변기기 전체 예산이 있으면 종류별 상위 5개의 조합을 전부 따져 예산 안에서 점수 합이 가장 큰 조합을 고른다. 예산 안 조합이 없으면 최저가 조합을 내고 "예산 초과"로 알린다 | `peripheral_select` |
| 5. 설명·근거 | "손이 큰 사용자 5명 중 4명이 좋게 평가했습니다" 같은 체감 문구, 리뷰 인용, 점수 비중, 몇 개 중 몇 위를 만든다. 반영 못 한 말은 관련 사용기 문장을 찾아 보여 준다(단어 일치 + 임베딩 순위 결합) | `peripheral_evidence`, `peripheral_display`, `peripheral_search` |
| 6. 더 맞추기 칩 | 눌렀을 때 지금 순위가 실제로 바뀌는 조건만 최대 3개 제안한다 | `peripheral_suggest` |

## 9. 주요 API

전체 목록과 요청·응답 형식은 서버 실행 후 http://127.0.0.1:8000/docs 에서 볼 수 있습니다.

| 영역 | 경로 | 주요 엔드포인트 |
|---|---|---|
| 인증 | `/auth` | `POST /signup`, `POST /login`, `POST /logout`, `POST /logout-all`, `POST /withdraw` |
| 조건 대화 | `/session` | `POST /session`, `GET /session/{list_id}`, `POST /session/{list_id}/category` |
| 본체 추천·견적 | `/lists` | `POST /{list_id}/message`, `POST /{list_id}/recommend`, `POST /{list_id}/result-message`, `POST /{list_id}/items/{item_id}/swap`, `POST /{list_id}/confirm`, `GET /{list_id}/report` |
| 주변기기 | `/peripherals` | 주변기기 채팅·추천 (`POST /lists/{list_id}/peripherals/chat`, `POST /lists/{list_id}/peripherals/recommend`) |
| 받은 견적 점검 | `/pc` | `POST /review-drafts`, `POST /review-drafts/{draft_id}/analysis`, `POST /review-drafts/{draft_id}/quote-comparisons`, `POST /review-drafts/{draft_id}/confirm` |
| 견적 리뷰 대화 | `/reviews` | `GET /reviews/{list_id}/messages`, `POST /reviews/{list_id}/messages` |
| 커뮤니티 | `/community`, `/catalog` | `GET·POST /community/posts`, 댓글·좋아요·저장, `GET /catalog/search` |
| 마이페이지 | `/me` | `GET /me`, `GET /me/summary`, `GET /me/notifications`, `GET /me/saved-posts` |

<!-- TODO: 경로가 실제 서버 prefix와 맞는지 /docs 와 대조해 확정 -->

## 10. 데이터베이스

PostgreSQL + pgvector. 마이그레이션은 `db/migrations/`(21개), 시드는 `db/setup_all.py`로 한 번에 적용합니다.

| 스키마 | 용도 | 주요 테이블 |
|---|---|---|
| `catalog` | 부품·주변기기 카탈로그 | `product`, `cpu_spec`, `gpu_spec`, `monitor_spec`, `keyboard_spec`, `offer` |
| `evidence` | 리뷰 근거 | `review_document`, `review_embedding`, `review_aspect_observation`, `review_aspect_aggregate` |
| `engine` | 추천 실행·검증 | `recommendation_run`, `recommendation_candidate`, `validation_result`, `peripheral_post_evidence` |
| `planning` | 견적·확정 리포트 | `plan`, `plan_revision`, `purchase_line`, `peripheral_line`, `kept_part_line` |
| `identity` | 계정·대화 | `app_user`, `conversation`, `message`, `preference_signal`, `user_pc` |
| `community` | 커뮤니티 | `post`, `post_comment`, `post_like`, `post_image`, `notification` |
| `config` | 설정 도메인 | `domain`, `domain_version` |
| `assets` | 파일·자료 | `file_object`, `product_material` |

## 11. 설치 및 실행

### 11.1 준비물

- Python 3.11, [uv](https://docs.astral.sh/uv/)
- Docker Desktop (PostgreSQL 컨테이너용)
- Node.js 20 이상 (화면 빌드용)
- 시드 데이터 (11.2에서 받기)

### 11.2 시드 데이터 받기

리뷰 원문 등이 들어 있어 Git에 올리지 않는 시드 파일은 구글 드라이브에서 받습니다.

<!-- TODO: 구글 드라이브 링크 -->
**다운로드**: [TrueFit 시드 데이터 (Google Drive)](DRIVE_LINK)

1. 위 링크에서 `truefit_seed.zip`을 받습니다.
2. **저장소 루트(`skn_final/`)에 압축을 풉니다.** 압축 안의 폴더 구조가 저장소와 같아서, 풀면 파일이 아래 위치에 들어갑니다.

```text
skn_final/
└── data/
    ├── peripherals/                    # [필수] 주변기기 카탈로그
    │   ├── monitor_processed.csv
    │   ├── keyboard_processed.csv
    │   ├── mouse_processed.csv
    │   └── speaker_processed.csv
    ├── review_seed/                    # [필수] 리뷰 근거 번들
    │   ├── bundle_manifest.json
    │   ├── documents.json
    │   ├── rules.json
    │   ├── canonical_results.json
    │   └── consolidated_observation_drafts.json
    └── community_examples/
        └── dump/                       # [선택] 커뮤니티 예시 글 + 체감 분석 결과 스냅샷
            ├── manifest.json
            ├── *.copy
            └── images/
```

3. 파일이 제자리에 있는지 확인합니다. 모두 `True`가 나와야 합니다.

```powershell
"monitor","keyboard","mouse","speaker" | ForEach-Object { Test-Path "data/peripherals/$($_)_processed.csv" }
"bundle_manifest","documents","rules","canonical_results","consolidated_observation_drafts" | ForEach-Object { Test-Path "data/review_seed/$_.json" }
```

| 파일 | 필수 | 없으면 |
|---|:---:|---|
| `data/peripherals/*_processed.csv` | ✅ | `setup_all.py`의 주변기기 단계에서 실패 |
| `data/review_seed/*.json` | ✅ | `setup_all.py`의 리뷰 단계에서 실패 (`bundle_manifest.json`의 해시로 파일이 바뀌지 않았는지 검사) |
| `data/community_examples/dump/` | 선택 | 커뮤니티가 빈 상태로 시작하고, 주변기기 추천에 사용기 체감 근거가 빠짐 |

`data/parts_list_modify.xlsx`(PC 부품 카탈로그)와 커뮤니티 예시 글 원본(`data/community_examples/A~F/`)은 Git에 들어 있어 따로 받지 않아도 됩니다.

### 11.3 최초 설정

저장소 루트에서 PowerShell로 실행합니다.

```powershell
# 1. DB 컨테이너 (Docker Desktop이 켜져 있어야 함)
docker compose up -d db

# 2. 파이썬 패키지
uv sync --locked

# 3. DB 마이그레이션 + 시드 (11.2의 필수 파일 필요)
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run python db/setup_all.py

# 4. (선택) 커뮤니티 예시 글 + 체감 근거 복원 (11.2의 dump/ 필요)
$env:PYTHONPATH = "."
uv run python db/community_examples_snapshot.py restore data/community_examples/dump

# 5. 화면 빌드
cd web
npm install
npm run build
cd ..
```

`.env`가 없으면 `.env.example`을 복사해서 만듭니다. 기본값(`MOCK_MODE=1`)이면 OpenAI 키 없이 가짜 LLM으로 동작합니다.

### 11.4 실행

```powershell
docker compose up -d db
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run uvicorn src.api:app --reload --port 8000
```

- 화면: http://127.0.0.1:8000
- API 문서: http://127.0.0.1:8000/docs
- 종료: 실행 중인 터미널에서 `Ctrl+C`

코드를 새로 받은 뒤에는 `uv run python db/migrate.py up`(새 마이그레이션 적용)과 화면 재빌드(`npm run build`)를 한 번씩 하세요.

### 11.5 실제 LLM(OpenAI) 사용

`.env`에 아래가 모두 있어야 실제 호출이 켜집니다. 키는 Git에 올리지 마세요.

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna
OPENAI_API_KEY=(본인 키)
```

선택 설정(`CONDITIONS_AGENT`, `RESULT_AGENT` 등)은 `.env.example`의 주석을 따릅니다.

#### 주변기기 견적을 제대로 쓰려면 (`PERIPHERAL_INTENT_AGENT=1`)

주변기기 채팅이 문장을 조건으로 읽는 방법은 두 가지입니다. 화면을 확인할 때는 **켠 상태**(`PERIPHERAL_INTENT_AGENT=1` + 위 LLM 설정)로 보세요. 꺼져 있으면 단어 규칙으로만 읽어, 돌려 말한 문장은 반영되지 않는 일이 많습니다. 서버를 다시 시작해야 반영됩니다.

### 11.6 Docker로 한 번에 띄우기 (배포용)

```powershell
docker compose up -d --build
docker compose exec api python db/setup_all.py
```

배포 환경에서는 `JWT_SECRET`을 반드시 바꾸고, HTTPS 뒤에서는 `COOKIE_SECURE=1`로 설정합니다.

## 12. 테스트와 평가

```powershell
docker compose up -d db
$env:PYTHONPATH = "."
$env:TRUEFIT_REQUIRE_TEST_DB = "1"
uv run pytest -q -m "not llm_live"
```

- 테스트 시작 시 임시 DB(`truefit_test_<UUID>`)를 만들어 마이그레이션·시드를 적용하고, 끝나면 지웁니다. 개발 DB(`truefit`)에는 연결하지 않습니다. 11.2의 필수 시드 파일이 있어야 합니다.
- `llm_live` 시험은 실제 LLM을 호출해 비용이 드니 기본에서 뺍니다.

<!-- TODO: 평가 결과 요약 (추천 품질·견적 인식 정확도 등) -->

## 13. 운영비

<!-- TODO: 월 예상 비용 (AI 호출비, 서버/AWS, DB 등) 수치 확정 후 작성 -->

| 항목 | 월 예상 비용 | 산출 근거 |
|---|---|---|
| AI(LLM) 호출 | TODO | TODO |
| 서버·DB(AWS) | TODO | TODO |
| 합계 | TODO | |

## 14. 기술 스택

<table width="100%">
  <tr>
    <td width="20%"><b>Frontend</b></td>
    <td>
      <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" />
      <img src="https://img.shields.io/badge/TypeScript-6-3178C6?style=flat-square&logo=typescript&logoColor=white" />
      <img src="https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white" />
      <img src="https://img.shields.io/badge/React_Router-7-CA4245?style=flat-square&logo=reactrouter&logoColor=white" />
    </td>
  </tr>
  <tr>
    <td><b>Backend</b></td>
    <td>
      <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" />
      <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
      <img src="https://img.shields.io/badge/Uvicorn-499848?style=flat-square" />
      <img src="https://img.shields.io/badge/Pydantic-2-E92063?style=flat-square&logo=pydantic&logoColor=white" />
      <img src="https://img.shields.io/badge/uv-DE5FE9?style=flat-square&logo=uv&logoColor=white" />
    </td>
  </tr>
  <tr>
    <td><b>AI</b></td>
    <td>
      <img src="https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white" />
      <img src="https://img.shields.io/badge/Strands_Agents-FF9900?style=flat-square&logo=amazonwebservices&logoColor=white" />
      <img src="https://img.shields.io/badge/text--embedding--3--small-1536d-412991?style=flat-square&logo=openai&logoColor=white" />
    </td>
  </tr>
  <tr>
    <td><b>Database</b></td>
    <td>
      <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white" />
      <img src="https://img.shields.io/badge/pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white" />
      <img src="https://img.shields.io/badge/psycopg-3-336791?style=flat-square" />
    </td>
  </tr>
  <tr>
    <td><b>Infra</b></td>
    <td>
      <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" />
      <img src="https://img.shields.io/badge/Docker_Compose-2496ED?style=flat-square&logo=docker&logoColor=white" />
      <img src="https://img.shields.io/badge/AWS_EC2-FF9900?style=flat-square&logo=amazonec2&logoColor=white" />
      <img src="https://img.shields.io/badge/AWS_RDS-527FFF?style=flat-square&logo=amazonrds&logoColor=white" />
    </td>
  </tr>
  <tr>
    <td><b>Test</b></td>
    <td>
      <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" />
    </td>
  </tr>
</table>

## 15. 참고 문서

<!-- TODO: 공유할 문서만 골라 링크 확정 -->

| 구분 | 문서 | 내용 |
|---|---|---|
| 데이터 | [데이터 수집 및 전처리](docs/데이터_수집_및_전처리.md) | 데이터별 출처·수집 방법(작성 예정), 전처리 규칙, 시스템에서 쓰이는 곳 |
| 데이터 | [커뮤니티 예시 사용기 적재 런북](data/community_examples/README.md) | 예시 글 적재, 체감 분석, 스냅샷 내보내기·복원 |
| DB | [DB 안내](db/README.md) | 마이그레이션·시드 스크립트 |
| 배포 | [배포 안내](deploy/README.md) | AWS EC2 + RDS 배포 절차 |
| 설계 | [미보유 부품 실시간 스펙 검색 설계](docs/미보유부품_실시간스펙검색_설계.md) | 받은 견적에 DB에 없는 부품이 있을 때의 처리 |
| 설계 | [리뷰 평점 적재·표시 계획](docs/리뷰평점_적재_표시_계획_20261019.md) | 리뷰 별점 적재와 화면 표시 |

## 16. 팀원

<table>
  <tr>
    <td rowspan="6" align="center" width="220">
      <img src="docs/images/hi-five-logo.png" alt="Hi Five" width="160"><br>
      <b>Hi Five</b><br>
      <sub>SK Networks AI Family Camp<br>32기 4조</sub>
    </td>
    <th align="left">이름</th>
    <th align="left">담당 역할</th>
    <th align="left">GitHub</th>
  </tr>
  <tr>
    <td>문동원</td>
    <td>PM, 주변기기 추천 알고리즘 개발</td>
    <td><a href="https://github.com/greenmdw"><img src="https://img.shields.io/badge/greenmdw-181717?style=flat-square&logo=github&logoColor=white" /></a></td>
  </tr>
  <tr>
    <td>박회종</td>
    <td>컴퓨터 본체 제품 추천 알고리즘 개발</td>
    <td><a href="https://github.com/1jelly7"><img src="https://img.shields.io/badge/1jelly7-181717?style=flat-square&logo=github&logoColor=white" /></a></td>
  </tr>
  <tr>
    <td>이태혁</td>
    <td>AWS 배포, Backend</td>
    <td><a href="https://github.com/kiri5358"><img src="https://img.shields.io/badge/kiri5358-181717?style=flat-square&logo=github&logoColor=white" /></a></td>
  </tr>
  <tr>
    <td>이호원</td>
    <td>Frontend</td>
    <td><a href="https://github.com/coreawon09"><img src="https://img.shields.io/badge/coreawon09-181717?style=flat-square&logo=github&logoColor=white" /></a></td>
  </tr>
  <tr>
    <td>임정택</td>
    <td>LLM 채팅 고도화</td>
    <td><a href="https://github.com/wjdxor0405"><img src="https://img.shields.io/badge/wjdxor0405-181717?style=flat-square&logo=github&logoColor=white" /></a></td>
  </tr>
</table>

## 17. 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다. Copyright (c) 2026 TrueFit Team.

<!-- TODO: 사용 데이터(크롤링 리뷰 등)·외부 라이브러리 라이선스 고지가 필요하면 여기에 추가 -->

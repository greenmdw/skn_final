<!--
  남은 일: 7번 시연 영상 유튜브 링크, docs/readme/데이터_수집_및_전처리.md 1장(데이터 수집), docs/readme/테스트와_평가.md (TODO 표시 부분)
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

<table align="center">
  <tr>
    <th align="left">서비스 소개</th>
    <th align="left">기술 구현</th>
    <th align="left">개발 · 운영</th>
    <th align="left">참고</th>
  </tr>
  <tr>
    <td>1. <a href="#1-프로젝트-소개">프로젝트 소개</a></td>
    <td>6. <a href="#6-시스템-구성-및-db">시스템 구성 및 DB</a></td>
    <td>9. <a href="#9-프로젝트-구조">프로젝트 구조</a></td>
    <td>12. <a href="#12-참고-문서">참고 문서</a></td>
  </tr>
  <tr>
    <td>2. <a href="#2-문제-정의">문제 정의</a></td>
    <td>7. <a href="#7-수집-데이터-및-전처리">수집 데이터 및 전처리</a></td>
    <td>10. <a href="#10-설치-및-실행">설치 및 실행</a></td>
    <td>13. <a href="#13-팀원">팀원</a></td>
  </tr>
  <tr>
    <td>3. <a href="#3-기대-효과">기대 효과</a></td>
    <td>8. <a href="#8-기술-스택">기술 스택</a></td>
    <td>11. <a href="#11-운영비">운영비</a></td>
    <td>14. <a href="#14-라이선스">라이선스</a></td>
  </tr>
  <tr>
    <td>4. <a href="#4-주요-기능">주요 기능</a></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>5. <a href="#5-시연-영상">시연 영상</a></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>

---

## 1. 프로젝트 소개

TrueFit은 사용자가 말한 **용도·예산·취향**을 조건으로 읽어 새 컴퓨터 본체와 주변기기(모니터·키보드·마우스·스피커)를 추천하고, 이미 받은 견적서를 점검해 주는 서비스입니다. 조건 대화 → 추천 → 확정 → 리포트까지 한 브라우저 화면에서 이어집니다.

스펙이 같아도 사람마다 맞는 제품은 다릅니다. 그래서 TrueFit은 스펙표만으로 고르지 않고, **실제 구매자 리뷰와 커뮤니티 사용기**를 분석해 그립감·키감·소음 같은 사용감과 손 크기·용도 같은 **사용자 성향**까지 추천 점수에 반영합니다.

- **새 컴퓨터 본체 추천**: 대화로 받은 조건으로 부품 구성을 추천하고 호환·예산을 검사합니다.
- **받은 견적 점검**: 사진·텍스트 견적서를 인식해 호환성·가격·용도 적합성을 평가합니다.
- **주변기기 견적**: 리뷰·사용기 근거와 함께 모니터·키보드·마우스·스피커를 추천합니다.
- **커뮤니티**: 사용기를 올리고, 거기서 뽑은 체감·성향이 추천에 반영됩니다.

<p align="center">
  <img src="docs/images/pc-recommend-infographic.png" alt="TrueFit 서비스 개요 — 사용자 고민에서 요구사항 분석·본체 구성 추천·주변기기 매칭을 거쳐 추천 결과까지" width="900">
</p>

## 2. 문제 정의

### 2.1 부품을 고르고 호환을 맞추는 일이 너무 복잡합니다

본체 하나를 맞추려면 CPU·메인보드·RAM·GPU·SSD·파워·케이스·쿨러 **8종 부품**을 고르고, 소켓·메모리 규격·전력·케이스 크기 같은 **호환 조건**을 모두 맞춰야 합니다. 그러나 시판되는 부품 수는 **총 8,163개**입니다(출처: 다나와).

### 2.2 받은 견적이 내 용도에 맞는지 확인할 방법이 없습니다

판매점 견적서에는 부품 이름과 금액만 있어, **부품끼리 호환되는지, 용도에 비해 과하거나 부족한 부품은 없는지** 비전문가가 확인하기 어렵습니다.

### 2.3 스펙이 같아도 사람마다 맞는 제품이 다릅니다

그립감·키감·소음 같은 **사용감은 스펙표에 나오지 않습니다.** 구매자의 **97.2%가 구매 전 후기를 확인**하지만(출처: [한국소비자연맹](https://www.dailycnc.com/news/articleView.html?idxno=209683)), 수백 건의 후기에서 나와 손 크기·용도가 비슷한 사람의 경험만 골라 읽기는 어렵습니다.

### 2.4 그래서 TrueFit이 푸는 문제

| 문제 | TrueFit의 해결 방식 |
|---|---|
| 부품을 고르고 호환을 맞추기 어렵다 (2.1) | 대화로 용도·예산을 받고, **규칙 기반 엔진**이 호환 검사·예산 최적화까지 계산해 완성된 구성을 제안 |
| 받은 견적을 검증할 수 없다 (2.2) | 사진·텍스트 견적서를 인식해 **호환성·용도 적합성**을 점검하고, 아쉬운 부품은 교체 후보와 나란히 비교 |
| 스펙만으로는 나에게 맞는 제품을 고를 수 없다 (2.3) | 구매 리뷰와 커뮤니티 사용기에서 **사용감 근거**를 뽑아, **성향이 같은 사용자의 평가**를 추천 점수에 반영 |

## 3. 기대 효과

| 해결한 문제 | 기대 효과 |
|---|---|
| 부품을 고르고 호환을 맞추기 어렵다 (2.1) | **구매 진입 장벽 완화와 결정 시간 단축.** 부품 지식 없이도 "배그 할 거고 150만 원"처럼 말하면 호환이 확인된 구성을 받습니다. 견적 질문 글을 올리고 답을 기다리던 과정이 대화 몇 번으로 줄어듭니다. |
| 받은 견적을 검증할 수 없다 (2.2) | **잘못된 구성 구매 예방.** 사기 전에 호환 문제와 용도에 비해 과하거나 부족한 부품을 짚어 주고, 같은 예산의 더 나은 대안을 보여 줘 판매점 견적을 스스로 판단할 수 있게 합니다. |
| 스펙만으로는 나에게 맞는 제품을 고를 수 없다 (2.3) | **개인 성향에 맞는 추천과 구매 후 후회 감소.** "손이 작아서 가벼운 마우스"처럼 말하면 비슷한 사용자의 체감 평가까지 반영해, 스펙은 맞는데 손에 안 맞는 제품을 사는 일을 줄입니다. 추천 이유에 리뷰·사용기 원문을 함께 보여 줘 사용자가 직접 납득할 수 있습니다. |

## 4. 주요 기능

> 실제 사용 화면과 동작은 [5. 시연 영상](#5-시연-영상)에서 볼 수 있습니다.

### 4.1 새 컴퓨터 본체 추천

- **해결하려는 문제**: 8천 개가 넘는 부품 중 호환·용도·예산이 맞는 조합을 직접 고르기 어렵습니다.
- **실제 구현한 기능**: 말로 조건을 주면 8종 부품 구성을 추천하고 호환·예산·게임 요구 사양 충족 여부를 보여 줍니다. 결과 화면에서 "더 싸게"처럼 이어 말하거나 부품을 교체할 수 있고, 가지고 있는 부품은 빼고 추천받을 수 있습니다.
- **기술적으로 중요한 특징**: 가격·성능·리뷰 3축 점수와 조합 완전탐색으로 세트를 고르고, 호환 신뢰도가 80점 미만이면 문제 부품을 빼고 다시 찾습니다. LLM은 조건을 읽고 설명을 쓰기만 하며, 실패하면 규칙 경로로 대신합니다.

### 4.2 받은 견적 점검

- **해결하려는 문제**: 판매점 견적서만으로는 호환 여부와 용도 대비 과·부족을 알 수 없습니다.
- **실제 구현한 기능**: 견적서 사진(여러 장)·텍스트를 인식해 호환성·용도 균형·가격을 점검하고, 아쉬운 부품은 교체 후보와 비교해 일부만 바꿔 확정합니다. 결과를 두고 대화로 질문할 수 있습니다.
- **기술적으로 중요한 특징**: Vision으로 읽은 문구를 코드가 카탈로그와 매칭하고, 새 PC 추천과 **같은 호환 검사 함수**로 판정합니다. DB에 없는 부품은 웹 검색 → 검증으로 스펙을 찾아 임시 저장소에 두며, 대화 답에 입력에 없던 숫자가 나오면 모델 문장을 버립니다.

### 4.3 주변기기 견적

- **해결하려는 문제**: 그립감·키감·소음 같은 사용감은 스펙표에 없고, 같은 제품도 손 크기·용도에 따라 평가가 갈립니다.
- **실제 구현한 기능**: "손이 작아서 가벼운 무선 마우스"처럼 한 문장으로 모니터·키보드·마우스·스피커를 추천받고, 순위와 근거(스펙·리뷰 인용·사용기 체감·점수 비중)를 봅니다. 모니터는 내 PC 그래픽카드 포트와 맞는지 검사합니다.
- **기술적으로 중요한 특징**: 직접 말한 조건만 후보를 거르고 목적에서 풀어낸 조건은 선호로만 반영합니다. 체감 점수는 **성향이 같은 사용자의 평가**를 먼저 보고 표본이 적으면 전체 평균 쪽으로 당겨 과신하지 않으며, 근거가 5건 미만이면 감점합니다.

### 4.4 장바구니 · 확정 · 리포트

- **해결하려는 문제**: 본체와 주변기기를 따로 고르면 전체 구성을 한눈에 보기 어렵고, 나중에 왜 골랐는지 남지 않습니다.
- **실제 구현한 기능**: 본체와 주변기기를 장바구니에서 합쳐 확정하면 리포트가 만들어지고, 저장한 견적을 다시 열어 수정하거나 리포트를 하나씩 지울 수 있습니다.
- **기술적으로 중요한 특징**: 확정 시점의 스펙·근거·점수를 리비전으로 얼려 저장해 나중에 열어도 같은 설명이 나오고, 삭제는 표시만 한 뒤 보관 기간이 지나면 정리 작업이 영구 삭제합니다.

### 4.5 커뮤니티 · 마이페이지

- **해결하려는 문제**: 외부 리뷰만으로는 작성자의 손 크기·용도 같은 성향을 알기 어렵습니다.
- **실제 구현한 기능**: 질문·사용기·팁·자유 게시판(제품 연결·이미지·좋아요·저장·댓글 알림)과, 내 PC·상담 기록·리포트를 모아 보는 마이페이지
- **기술적으로 중요한 특징**: 사용기가 올라오면 별도 작업 프로세스가 LLM으로 체감 문장을 뽑아 추천 근거로 쌓고, 본문에 없는 문장 등 여섯 가지 확인을 통과한 것만 점수에 씁니다. 업로드 이미지는 다시 인코딩해 위치 정보 등 메타데이터를 지웁니다.

## 5. 시연 영상

<!-- TODO: 유튜브 링크를 아래 두 곳에 넣기 (VIDEO_ID 교체) -->

[![TrueFit 시연 영상](https://img.youtube.com/vi/VIDEO_ID/0.jpg)](https://www.youtube.com/watch?v=VIDEO_ID)

▶ [유튜브에서 보기](https://www.youtube.com/watch?v=VIDEO_ID)

## 6. 시스템 구성 및 DB

**판정·수치는 코드, LLM은 읽기와 서술.** 언어 모델은 사용자 문장·견적서·리뷰를 읽어 정해진 형식으로 옮기고 설명 문장을 쓰는 데만 씁니다. 호환 판정, 점수, 순위, 금액은 모두 엔진 코드와 DB 데이터로 정합니다. 모델 호출이 꺼져 있거나 실패하면 대부분 규칙 경로로 물러나 서비스가 멈추지 않습니다.

> 본체 추천·견적 점검·주변기기의 처리 흐름과 검색 경로는 [시스템 아키텍처 상세](docs/readme/시스템_아키텍처_상세.md), API 목록은 [주요 API](docs/readme/주요_API.md) 문서에 있습니다.

### 6.1 시스템 구성

```mermaid
flowchart TB
    U["사용자 브라우저<br/>React 화면 실행"]
    subgraph APP["FastAPI 앱: src.api:app"]
        WEB["화면 파일 제공<br/>web/dist"]
        API["API 입구: routers<br/>인증 · 조건 대화 · 추천 · 견적 점검 · 커뮤니티"]
        SVC["서비스: services<br/>요청 순서 조정 · 소유권 확인 · 저장"]
        ENG["계산 엔진: engine<br/>후보 필터 · 점수 · 조합 · 호환 검사"]
        AI["AI 연결 코드<br/>agent · clients · rag"]
        REPO["DB 접근: repo + db<br/>SQL · 연결 풀 · 트랜잭션"]
        WEB -->|"HTML · JS · CSS 응답"| U
        API --> SVC
        SVC --> ENG
        SVC --> AI
        ENG -.->|"쟁점·추천 이유 문장화"| AI
        SVC --> REPO
    end
    DB[("PostgreSQL + pgvector<br/>상품 · 근거 · 계정 · 대화 · 견적")]
    FILES[("서버 파일 저장소<br/>커뮤니티 첨부 이미지")]
    OAI["외부 OpenAI API<br/>대화 · 이미지 읽기 · 웹 검색 · 임베딩"]
    BG["별도 배치 프로세스<br/>사용기 분석 · 리뷰 임베딩 · 삭제 정리"]
    U -->|"화면 접속"| WEB
    U -->|"HTTP API 요청"| API
    REPO <-->|"조회 · 저장"| DB
    SVC <-->|"첨부 저장 · 읽기"| FILES
    AI <-->|"기능별 설정에 따라 호출"| OAI
    BG <-->|"작업 대기 · 분석 결과 · 정리"| DB
    BG -.->|"분석·임베딩 작업에서 호출"| OAI
```

- **큰 FastAPI 상자 안의 칸은 같은 Python 앱 안의 모듈**입니다. 각각 독립 서버가 아닙니다. PostgreSQL과 OpenAI API는 앱 밖에 있고, 배치 작업은 별도 프로세스로 돕니다. 실선은 요청·데이터 이동, 점선은 조건에 따라 쓰는 AI 경로입니다.
- 화면 파일과 API는 같은 서버가 내려 주지만, React 코드는 사용자 브라우저에서 실행됩니다. 브라우저는 API만 호출하고 DB나 OpenAI에 직접 연결하지 않습니다.

| 구성 요소 | 맡은 일 | 위치 |
|---|---|---|
| React 화면 | 대화·견적·리포트·커뮤니티 화면. 화면 상태를 관리하고 HTTP API를 호출합니다 | `web/src/` |
| API 라우터 | 요청 주소와 입력 형식을 확인하고 서비스를 부르는 입구. 로그인 JWT 쿠키와 비로그인 브라우저 식별자를 읽습니다 | `src/routers/`, `src/auth/` |
| 서비스 | 조건 저장 → 후보 조회 → 엔진 계산 → 결과 저장처럼 여러 모듈을 순서대로 연결하고, 견적 소유권을 확인합니다 | `src/services/` |
| 계산 엔진 | 필수 조건, 가격·성능·리뷰 점수, 부품 조합, 호환 여부를 코드와 설정으로 계산합니다 | `src/engine/`, `config/` |
| AI 연결 코드 | 자유 문장을 조건으로 바꾸고, 견적서 이미지·사용기를 읽거나 설명을 만듭니다. 조건·결과·견적 점검 대화는 Strands 도구 호출을 씁니다 | `src/agent/`, `src/clients/`, `src/rag/` |
| 추천 작업자 풀 | 본체 추천의 긴 계산과 설명 생성을 HTTP 응답에서 분리합니다. API 프로세스 안의 스레드 풀입니다 | `src/services/recommendation_runner.py` |
| DB 접근 | SQL로 조회·저장합니다. 요청용과 추천 백그라운드용 연결 풀이 나뉘어 있습니다 | `src/repo/`, `src/db/` |
| 별도 배치 | 사용기 분석, 리뷰 벡터 채우기, 보관 기간이 지난 삭제 데이터 정리 | `src/workers/` |

### 6.2 데이터베이스

PostgreSQL 16 하나에 업무 데이터와 벡터를 함께 둡니다. 리뷰·사용기 문장 임베딩(1536차원)도 **pgvector**로 같은 DB에 저장해, 별도 벡터 DB 없이 SQL 한 번으로 근거와 원문을 함께 읽습니다. 스키마 8개에 테이블 77개이며, 마이그레이션 21개(`db/migrations/`)와 시드(`db/setup_all.py`)로 누구나 같은 DB를 다시 만들 수 있습니다.

| 스키마 | 테이블 | 용도 | 주요 테이블 |
|---|---:|---|---|
| `catalog` | 21 | 부품·주변기기 카탈로그와 가격 | `product`, `cpu_spec`, `gpu_spec`, `monitor_spec`, `offer`, `offer_observation`, `live_spec_lookup_cache` |
| `evidence` | 12 | 리뷰 근거 | `review_document`, `review_embedding`, `review_aspect_rule`, `review_aspect_observation`, `review_aspect_aggregate` |
| `engine` | 9 | 추천 실행·검증, 사용기 체감 근거 | `recommendation_run`, `recommendation_candidate`, `validation_result`, `peripheral_post_evidence` |
| `planning` | 9 | 견적과 확정 리포트 | `plan`, `plan_revision`, `purchase_line`, `peripheral_line`, `kept_part_line` |
| `identity` | 7 | 계정·대화·선호 | `app_user`, `conversation`, `message`, `preference_signal`, `user_pc` |
| `community` | 13 | 커뮤니티 | `post`, `post_product`, `post_comment`, `post_image`, `notification` |
| `config` | 2 | 카테고리 정의 버전 | `domain`, `domain_version` |
| `assets` | 4 | 파일·자료 | `file_object`, `product_material` |

자세한 마이그레이션 목록과 시드 절차는 [DB 안내](db/README.md)에 있습니다.

## 7. 수집 데이터 및 전처리

> 데이터별 수집 방법과 전처리 흐름·규칙은 [데이터 수집 및 전처리](docs/readme/데이터_수집_및_전처리.md) 문서에 정리했습니다.

| 데이터 | 원본 규모 | 시스템 적재 | 쓰이는 곳 |
|---|---|---|---|
| PC 부품 카탈로그 | 8종 322행 (`parts_list_modify.xlsx`) | 319종 (중복 3행 제거) | 본체 추천 후보, 호환 검사, 받은 견적 매칭 |
| 주변기기 카탈로그 | 4종 203행 (`*_processed.csv`) | 203종 | 주변기기 추천 후보, 모니터↔PC 포트 검사 |
| 제품 리뷰 | 14,825건 (`data/reviews/*.jsonl`) | 5,653건 | 리뷰 관점 점수, 추천 이유 인용 |
| 리뷰 관점 규칙 | — | 102개 (PC 부품 82 · 주변기기 20) | 리뷰에서 무엇을 읽을지 정의 |
| 커뮤니티 예시 사용기 | 200편, 이미지 111장 | 체감 문장 2,875개 + 임베딩 | 주변기기 체감 점수, 커뮤니티 화면 |
| 게임 요구 사양 | `game_requirements.json` | 설정 파일 | 용도(게임)별 최소·권장 사양 판정 |

## 8. 기술 스택

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

## 9. 프로젝트 구조

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

## 10. 설치 및 실행

**준비물**: Python 3.11 + [uv](https://docs.astral.sh/uv/), Docker Desktop(PostgreSQL 컨테이너용), Node.js 20 이상(화면 빌드용). 명령은 모두 저장소 루트에서 PowerShell로 실행합니다.

<details>
<summary><b>처음 실행할 때</b> — 시드 데이터 받기 → 환경 설정 → DB·화면 준비 → 서버 실행</summary>

<br>

**1. 시드 데이터 받기**

리뷰 원문 등이 들어 있어 Git에 올리지 않는 파일은 [TrueFit 시드 데이터 (Google Drive)](https://drive.google.com/file/d/1vMO2RW9mYhS03eUIqHkYjLKVX_LbE-3C/view?usp=drive_link)에서 받아 **저장소 루트(`skn_final/`)에 압축을 풉니다.** 압축 안의 폴더 구조가 저장소와 같아서 아래 위치에 들어갑니다.

```text
data/
├── peripherals/*_processed.csv        # [필수] 주변기기 카탈로그 4개
├── review_seed/*.json                 # [필수] 리뷰 근거 번들 5개
└── community_examples/dump/           # [선택] 커뮤니티 예시 글 + 체감 분석 결과
```

필수 파일이 없으면 3단계의 `setup_all.py`가 멈춥니다. `dump/`가 없으면 커뮤니티가 빈 상태로 시작하고 주변기기 추천에 사용기 체감 근거가 빠집니다. PC 부품 카탈로그(`data/parts_list_modify.xlsx`)는 Git에 들어 있습니다.

**2. 환경 설정**

`.env.example`을 복사해 `.env`를 만듭니다. 기본값(`MOCK_MODE=1`)이면 OpenAI 키 없이 가짜 LLM으로 동작합니다. 실제 LLM을 쓰려면 아래 값을 넣습니다(키는 Git에 올리지 않습니다).

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna
OPENAI_API_KEY=(본인 키)
PERIPHERAL_INTENT_AGENT=1   # 주변기기 채팅이 돌려 말한 문장도 조건으로 읽게 함
```

그 밖의 선택 설정(`CONDITIONS_AGENT`, `RESULT_AGENT` 등)은 `.env.example`의 주석을 따릅니다.

**3. DB와 화면 준비**

```powershell
docker compose up -d db                       # DB 컨테이너 (Docker Desktop이 켜져 있어야 함)
uv sync --locked                              # 파이썬 패키지
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run python db/setup_all.py                 # 마이그레이션 + 시드
$env:PYTHONPATH = "."
uv run python db/community_examples_snapshot.py restore data/community_examples/dump   # (선택) 커뮤니티 예시 글 복원
npm --prefix web install
npm --prefix web run build                    # 화면 빌드
```

**4. 서버 실행**

```powershell
uv run uvicorn src.api:app --reload --port 8000
```

화면은 http://127.0.0.1:8000, API 문서는 http://127.0.0.1:8000/docs 에서 열립니다.

</details>

<details>
<summary><b>이미 설정을 마친 뒤 실행할 때</b> — DB 켜기 → 서버 실행</summary>

<br>

```powershell
docker compose up -d db
$env:DATABASE_URL = "postgresql://truefit:truefit@localhost:5432/truefit"
uv run uvicorn src.api:app --reload --port 8000
```

- 화면: http://127.0.0.1:8000 · API 문서: http://127.0.0.1:8000/docs · 종료: 터미널에서 `Ctrl+C`
- 코드를 새로 받았다면 실행 전에 새 마이그레이션 적용(`uv run python db/migrate.py up`)과 화면 재빌드(`npm --prefix web run build`)를 한 번씩 합니다.
- `.env`를 바꿨다면 서버를 다시 시작해야 반영됩니다.

</details>

AWS 서버 배포는 [배포 안내](deploy/README.md)를 따릅니다.

## 11. 운영비

현재 배포 구성(AWS 서울 리전 EC2 `t3.medium` 1대 + RDS `db.t3.small` 1대)과 OpenAI `gpt-6-luna` 단가로 계산한 **월 예상 비용**입니다(2026-10-21 단가, 1달러 = 1,400원 가정). 산출 과정은 [운영비 산출](docs/readme/운영비_산출.md) 문서에 있습니다.

**산출 방법**: ① 인프라는 사용량과 무관한 월 고정비로 계산 → ② 코드에서 모델을 부르는 곳마다 1회당 호출 수·토큰 수를 추정(프롬프트·도구 정의 크기는 코드에서 실측) → ③ 기능을 세션 단위로 묶어 월 세션 수 시나리오에 곱함

| 구분 | 항목 | 월 비용 |
|---|---|---:|
| 인프라 (고정) | EC2 `t3.medium` + EBS 30GB + 퍼블릭 IP | $44.35 |
| | RDS `db.t3.small` PostgreSQL + 스토리지 20GB | $43.50 |
| | **인프라 합계** | **$87.85 (약 12.3만 원)** |
| AI 호출 (세션당) | 본체 추천 (조건 대화 4턴 + 추천 1.5회 + 결과 대화 3턴) | 약 14원 |
| | 받은 견적 점검 (사진 2장 + 실시간 스펙 검색 0.5회 + 대화 3턴) | 약 15원 |
| | 주변기기 견적 (문장 해석 3턴) | 약 2원 |
| | 커뮤니티 사용기 분석 (글 1편) | 약 1원 |

| 시나리오 (월) | 본체 추천 · 견적 점검 · 주변기기 · 사용기 | AI 호출 | **월 합계** |
|---|---|---:|---:|
| 소규모 (시연·베타) | 300 · 100 · 200 · 100 | $4.44 | **$92.29 (약 13만 원)** |
| 중규모 | 3,000 · 1,000 · 2,000 · 1,000 | $44.44 | **$132.29 (약 19만 원)** |
| 대규모 | 30,000 · 10,000 · 20,000 · 6,000 | $440.76 | **$529 + 인프라 증설** |

- 소규모·중규모에서는 인프라가 비용의 대부분(66~95%)이고, AI 호출은 세션당 십여 원 수준입니다.
- 기능 1회 중 가장 비싼 것은 **실시간 스펙 검색**(1회 약 16원, 대부분 웹 검색 호출 요금)입니다. 같은 부품은 임시 저장소에 남아 다시 검색하지 않습니다.
- 토큰 수는 추정치(±30%)이고 프롬프트 캐시 할인을 반영하지 않은 상한에 가깝습니다. 대규모 시나리오의 인프라 증설 비용은 산정하지 않았습니다.

## 12. 참고 문서

<!-- TODO: 공유할 문서만 골라 링크 확정 -->

| 구분 | 문서 | 위치 | 내용 |
|---|---|---|---|
| 시스템 | [시스템 아키텍처 상세](docs/readme/시스템_아키텍처_상세.md) | `docs/readme/` | 본체 추천·받은 견적 점검·주변기기 추천의 처리 흐름(도식), 엔진 단계, 검색 경로 |
| 시스템 | [주요 API](docs/readme/주요_API.md) | `docs/readme/` | 영역별 주요 엔드포인트 (전체 목록은 서버의 `/docs`) |
| 검증 | [테스트와 평가](docs/readme/테스트와_평가.md) | `docs/readme/테스트와_평가.md` | 테스트 실행과 평가 결과 |
| 데이터 | [데이터 수집 및 전처리](docs/readme/데이터_수집_및_전처리.md) | `docs/readme/` | 데이터별 전처리 규칙과 시스템에서 쓰이는 곳 (출처·수집 방법은 작성 예정) |
| 데이터 | [커뮤니티 예시 사용기 적재 런북](data/community_examples/README.md) | `data/community_examples/` | 예시 사용기 200편 적재 → 체감 문장 분석 → 임베딩 → 스냅샷 내보내기·복원 절차 |
| DB | [DB 안내](db/README.md) | `db/` | 마이그레이션 실행(`migrate.py`), 시드 적재 단계, 리뷰 속성 집계 재생성, 테스트용 일회용 DB |
| 배포 | [배포 안내](deploy/README.md) | `deploy/` | AWS EC2 + RDS 최초 설정, 재배포 스크립트, 사용기 분석 worker 켜기·끄기, 운영 주의사항 |
| 운영 | [운영비 산출](docs/readme/운영비_산출.md) | `docs/readme/` | 인프라·AI 호출 단가, 기능별 토큰 추정, 월 비용 시나리오 |
| 기능 | [DB 미보유 부품 실시간 스펙 검색](docs/readme/미보유부품_실시간스펙검색_설계.md) | `docs/readme/` | 카탈로그에 없는 부품을 웹 검색 → LLM 검증으로 찾아 임시 부품 저장소에 두고 호환 검사에 보태는 동작, 호출 한도, 사람 검토 |
| 기능 | [리뷰 평점 적재·표시](docs/readme/리뷰평점_적재_표시_계획_20261019.md) | `docs/readme/` | 수집처 구매자 별점을 DB에 적재하고 추천 결과·대안 후보·리포트·리뷰 요약에 평균 별점과 건수를 보여 주는 동작 |

## 13. 팀원

<table>
  <tr>
    <td rowspan="6" align="center" width="220">
      <img src="docs/images/hi-five-logo.png" alt="Hi Five" width="160"><br>
      <b>Hi Five</b><br>
      <sub>SK Networks AI Family Camp<br>32기 4조</sub><br>
      <sub>개발 기간: 2026.08.28 ~ 2026.10.26</sub>
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

## 14. 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다. Copyright (c) 2026 TrueFit Team.

<!-- TODO: 사용 데이터(크롤링 리뷰 등)·외부 라이브러리 라이선스 고지가 필요하면 여기에 추가 -->

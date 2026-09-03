# Odoo 19 기반 B2B 판매·조달 통합 구현 계획

## 1. 문서 목적과 확정 기준

이 문서는 최신 프로젝트 기획서 v5를 기준으로, 별도 서버에서 실행하는 Odoo 19와 현재 FastAPI 프로젝트를 연결하는 구현 순서와 완료 기준을 정의한다.

확정된 기술·범위 기준은 다음과 같다.

- Odoo 연동은 **JSON-2 API**를 사용한다. XML-RPC는 사용하지 않는다.
- Odoo 앱은 Contacts, CRM, Sales, Inventory, Purchase를 사용한다.
- Accounting은 Sales·Purchase의 의존성으로 설치될 수 있지만 프로젝트 기능 범위에는 포함하지 않는다.
- 최소 구현은 시뮬레이션 시나리오 **S1·S2·S3·S4·S8**을 담당한다.
- S5·S6·S7·S9·S10·S11은 후속 구현에서 담당한다.
- 표준 거래는 규칙으로 발주안을 만들고, 예외 거래만 Agent 협상을 실행한다.
- AI와 Agent는 안과 근거만 만든다. 최종 확정과 외부 송부는 권한 있는 사람이 수행한다.
- 판매자의 최저수용가·할인 정책·양보 규칙은 판매자 측 저장소에만 둔다. Odoo와 중앙 프로젝트 DB에는 저장하지 않는다.

최소 구현의 수직 흐름은 다음과 같다.

```text
Odoo 판매 기회·판매 견적·재고·공급 조건 조회
                ↓
        판매 소요 또는 재고 보충 소요
                ↓
          표준 조건 게이트
           ↙             ↘
   표준 발주안(S1)     예외 협상(S2)
                         + 감사자(S8)
           ↘             ↙
          사람 검토·확정·감사 이력

영업 화면 ── ATP 질의(S3)
          └─ 견적 즉시 조달 확인(S4)
```

## 2. 대상 기업과 업무 경계

### 2.1 참여자

| 참여자 | 의미 | Odoo 표현 |
|---|---|---|
| 플랫폼 도입 기업 | GPU 서버·워크스테이션 조립/SI 업체 | 현재 Odoo company |
| 공급사 | GPU 유통사·제조사 | Vendor인 `res.partner` |
| 도입 기업의 고객 | 데이터센터·연구기관·AI 스타트업 등 | Customer인 `res.partner`, CRM Opportunity의 `partner_id` |
| 영업 담당자 | 고객 기회·견적·판매주문 담당 | CRM/Sales 사용자 |
| 구매 담당자 | 발주안·매입 단가·협상 결과 확정 | Purchase 사용자 |
| 재고 담당자 | 재고 조정과 가용량 기준 관리 | Inventory 사용자 |
| 승인권자 | 금액·가격·납기 한도 초과 승인 | 별도 Odoo 보안 그룹 |

Company에 고정 `BUYER`, `SELLER`, `BOTH` 역할을 저장하지 않는다. 한 회사의 역할은 문서 관계로 결정한다.

- CRM·Sales 문서의 `partner_id`: 고객
- Purchase·Supplierinfo 문서의 `partner_id`: 공급사
- 플랫폼 도입 기업: Odoo의 현재 company

### 2.2 Odoo가 담당하는 기능

- 거래처와 담당자
- GPU·서버 상품 카탈로그와 단위
- CRM 판매 기회와 판매 견적·판매주문
- 현재고, 예약 출고, 입고 예정, 재주문 규칙
- 공급업체 공개 가격표, MOQ와 표준 납기
- draft 구매 RFQ/PO, 구매 승인·입고와 표준 리포트

### 2.3 프로젝트가 새로 담당하는 기능

- 완제품에서 GPU 부품 소요를 산출하는 BOM 룰
- 표준 조건 게이트와 승인 근거 요약
- 셀러·바이어 Agent의 예외 협상
- 판매자 측 감사자와 중앙 감사자
- 다속성 점수화와 순위 제시
- ATP 계산 근거를 제시하는 영업 어시스턴트
- 판매 견적의 즉시 조달 가능성·예상 원가·마진 확인
- 모든 제안·감사·사람 확정 이력

### 2.4 범위 밖

- Odoo Manufacturing, BOM, MRP와 PLM
- Accounting, 청구서 게시, 결제 등록, 은행 조정과 환불
- Agent나 스케줄러의 자동 계약 확정
- 발주서·견적서의 자동 이메일·EDI 송부
- 대금 지급과 카드·계좌 정보 보관
- Odoo 데이터베이스 직접 접속
- 최소 구현에서 S5·S6·S7·S9·S10·S11

## 3. 현재 코드 적합성 및 필수 변경

현재 프로젝트의 FastAPI, Pydantic, SQLAlchemy 구조와 Agent port 분리는 재사용할 수 있다. 다음 구현은 최신 기획과 맞지 않으므로 최소 구현 전에 변경해야 한다.

| 현재 상태 | 문제 | 변경 방향 |
|---|---|---|
| 품목 Enum이 A4용지·토너·볼트로 고정 | GPU 도메인과 Odoo 상품 변형을 표현하지 못함 | Odoo `product.product.id`와 `default_code` 기반 동적 품목 모델 |
| `BuyerRequest`가 직접 협상을 시작 | CRM 판매 수요와 재고 보충 소요가 연결되지 않음 | `ProcurementRequirement`를 먼저 생성하고 표준 게이트를 거침 |
| 중앙 `SellerRegister`에 `floor_price` 저장 | 판매자 기밀정보 경계 위반 | 판매자별 정책 저장소와 Seller Agent 런타임으로 이동 |
| Buyer 상한가를 Seller LLM 프롬프트에 전달 | 정보 비대칭과 협상 의미가 사라짐 | 각 Agent에는 자기 정책과 상대가 공개한 제안만 전달 |
| LLM이 가격을 직접 제안 | 가격 감사 재현성이 부족 | Boulware/Conceder 기반 결정적 가격 함수가 가격 계산 담당 |
| 감사자가 하한 위반 가격을 보정 후 발송 | 위반 제안 자체가 외부로 노출될 수 있음 | 판매자 측 감사자가 발신 전에 차단하고 실패 사유만 기록 |
| 수락 후보 중 최저가만 선택 | 사양·납기·신뢰도·구매 전략을 반영하지 못함 | 하드 조건 검사 후 다속성 점수화 |
| 동기 HTTP 요청 안에서 전체 협상 수행 | timeout·재시도·중복 실행 위험 | 작업 ID 기반 실행, 최소 데모는 단일 worker로 시작 |
| `/api/sellers`가 기밀 하한가까지 직렬화 가능 | 비밀값 노출 | 공개 DTO와 판매자 비공개 DTO 분리 |
| CORS 전체 허용·인증 없음 | Odoo 및 거래 데이터 노출 | 허용 origin, 사용자 인증과 역할 권한 적용 |

## 4. 아키텍처와 정보 경계

### 4.1 구성

```text
영업·구매 사용자
      │
      ▼
프로젝트 FastAPI ───── JSON-2 ───── Odoo 19
      │                                │
      ├─ 중앙 공개 데이터·실행 로그    ├─ CRM/Sales
      ├─ 표준 조건 게이트              ├─ Inventory
      ├─ 바이어 Agent                 └─ Purchase
      ├─ 중앙 감사자
      └─ Seller Agent Gateway
              │
              ├─ Seller A 정책 저장소
              ├─ Seller B 정책 저장소
              └─ Seller C 정책 저장소
```

최소 구현부터 Seller Agent를 판매자별 **독립 프로세스 또는 컨테이너**로 실행하고 각자 별도 비공개 저장소·서비스 자격증명을 사용한다. 같은 물리 호스트를 사용할 수는 있지만 중앙 서비스에는 Seller 저장소 자격증명과 직접 접근 경로를 주지 않는다. 중앙 협상 함수는 Seller API가 제출한 공개 제안과 감사 결과만 받을 수 있다.

### 4.2 데이터 소유권

| 데이터 | 기준 시스템 | 중앙 접근 |
|---|---|---|
| 고객·공급사·담당자 | Odoo `res.partner` | 필요한 공개 필드만 읽기 |
| 상품·단위·공개 사양 | Odoo Product | 읽기 |
| CRM 판매 기회·견적·판매주문 | Odoo CRM/Sales | 읽기, 승인된 최소 필드만 write-back |
| 현재·예약·입고 예정 재고 | Odoo Inventory | 읽기 |
| 공급사 공개 단가·MOQ·납기·계약 상한 | Odoo `product.supplierinfo`와 최소 사용자 정의 필드 | 읽기 |
| 재주문 기준선·목표 재고 | Odoo Reordering Rule | 읽기 |
| BOM 룰 | 프로젝트 DB | 버전 관리 |
| 표준 계약·승인 조건의 실행 snapshot | 프로젝트 DB | Odoo 원본 ID·`write_date`와 판정 당시 값만 불변 저장 |
| 구매 예산·구매 전략·가중치 | 프로젝트 보호 저장소 | 구매자·승인자만 접근 |
| 판매자 최저수용가·양보 규칙 | 각 판매자 측 저장소 | 중앙 접근 금지 |
| 판매자가 실제 제출한 제안 | 중앙 협상 로그 | 참가자·감사자 접근 |
| 협상·감사·승인 이력 | 프로젝트 DB | 권한 기반 조회 |
| draft 구매 문서 | Odoo Purchase | 멱등 생성·연결 |

중앙 로그에는 구매자 상한, 판매자 하한, 다른 판매자의 비공개 정책을 기록하지 않는다. 운영 로그에도 API 키와 전체 Agent 프롬프트를 남기지 않는다.

### 4.3 Agent 구성과 권한

| Agent | 역할 | 허용되지 않는 행위 |
|---|---|---|
| Seller Agent | 자기 정책 저장소와 거래처 이력으로 다속성 제안 생성 | 상대 상한 조회, 정책 미검증 발신, 계약 확정 |
| Buyer Agent | 조달 소요를 요청서로 만들고 수신 제안을 가중치로 평가 | 판매자 하한 조회, 발주 확정 |
| Auditor Agent | 판매자 발신 전 비공개 정책 검사와 중앙 수신 후 공개 규칙 검사 | 가격·정책 임의 변경, 사람 승인 대행 |
| Sales Assistant | 자연어 질의를 Odoo read-only 도구 호출로 바꾸고 근거와 함께 설명 | 근거 없는 추정, 견적·재고·주문 자동 변경 |

모든 Agent는 제안 권한만 가진다. `purchase.order`·`sale.order` 확정, 외부 송부와 지급 도구는 Agent tool 목록에 넣지 않는다.

### 4.4 중앙–Seller Agent 프로토콜

Seller별 서비스는 다음 내부 API 계약을 구현한다.

| 방향 | API | 용도 |
|---|---|---|
| 중앙 → Seller | `POST /internal/negotiations` | 새 협상 요청과 첫 제안 요청 |
| 중앙 → Seller | `POST /internal/negotiations/{id}/rounds` | 이전 공개 제안에 대한 다음 라운드 요청 |
| 중앙 → Seller | `POST /internal/negotiations/{id}/close` | 협상 종료·만료 통지 |
| 중앙 ← Seller | 동기 응답 또는 서명된 callback | 감사 통과 제안 또는 공개 가능한 차단 코드 |

중앙 요청에는 `negotiation_id`, `round`, 품목 코드, 수량, UoM, 요구 사양, 필요일, 통화, 공개 가능한 Buyer 신뢰도 등급, 만료 시각과 nonce를 포함한다. Buyer 상한가·전체 예산·다른 Seller 제안은 포함하지 않는다.

Seller 응답에는 `seller_id`, `negotiation_id`, `round`, 단가, 통화, 제안 수량, 사양, 납기, 제안 유효시각, 공개 증빙 참조, 감사 결과, nonce와 signature를 포함한다. 최저수용가·양보 곡선·내부 재고 정책은 포함하지 않는다.

- 최소 구현은 Seller별 HMAC 또는 OAuth client credentials를 사용하고 운영 확장에서 mTLS를 검토한다.
- `(seller_id, negotiation_id, round, nonce)`에 unique 제약을 둔다.
- timestamp 허용 오차와 만료 시각을 검사해 replay를 차단한다.
- 상태 전이는 `REQUESTED → OFFERED/COUNTERED → ACCEPTABLE → CLOSED/EXPIRED`만 허용한다.
- Seller 감사 실패는 제안으로 저장하지 않고 `SELLER_POLICY_BLOCKED`와 공개 사유 코드만 중앙 감사 이벤트에 남긴다.
- 요청·응답은 OpenAPI와 JSON Schema로 버전 관리하고 비공개 필드 부재를 contract test로 검증한다.

## 5. Odoo 19 JSON-2 연동

### 5.1 호출 방식

- `POST /json/2/<model>/<method>` 형식을 사용한다.
- `Authorization: bearer <API_KEY>`를 사용한다.
- 다중 DB 서버이면 `X-Odoo-Database`를 설정한다.
- 실제 모델·필드·호출 가능한 메서드는 대상 DB의 `/doc`에서 확인한다.
- Odoo 호출 코드는 `OdooGateway` port 뒤에 숨겨 업무 로직과 분리한다.
- 표준 메서드로 안전하게 표현하기 어려운 원자 작업만 최소 Odoo 애드온의 단일 메서드로 제공한다.

관련 공식 문서:

- [Odoo 19 External JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)
- [Odoo CRM](https://www.odoo.com/documentation/19.0/applications/sales/crm.html)
- [Odoo Sales](https://www.odoo.com/documentation/19.0/applications/sales/sales.html)
- [Odoo Replenishment](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment.html)
- [Odoo Reordering Rules](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html)
- [Odoo Purchase RFQ](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/purchase/manage_deals/rfq.html)
- [Odoo Vendor Pricelists](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/purchase/products/pricelist.html)

### 5.2 환경변수

```text
ODOO_BASE_URL=https://odoo.example.com
ODOO_DATABASE=demo
ODOO_API_KEY=secret-reference
ODOO_CONNECT_TIMEOUT_SECONDS=3
ODOO_READ_TIMEOUT_SECONDS=10
ODOO_VERIFY_TLS=true
ODOO_ALLOWED_COMPANY_IDS=1
ODOO_DEFAULT_WAREHOUSE_ID=1
ODOO_SYNC_PAGE_SIZE=100
```

실제 키는 `.env.example`, Git, 보고서와 DB에 저장하지 않는다. 운영에서는 secret manager를 사용한다.

### 5.3 권한과 안정성

- 개인 계정이 아닌 전용 bot 사용자를 사용한다.
- 읽기 bot과 구매 문서 쓰기 bot을 분리한다.
- 초기 단계는 Partner·Product·CRM·Sales·Inventory·Supplierinfo 읽기만 허용한다.
- 쓰기 bot은 draft 구매 문서와 제한된 연동 필드만 다룬다.
- 네트워크 오류, `429`, 일부 `5xx`의 읽기 호출만 제한적으로 재시도한다.
- 생성 호출은 idempotency key와 Odoo unique 외부 참조를 확인한 뒤 재시도한다.
- `401`, `403`, 스키마·권한 오류는 자동 재시도하지 않는다.
- 페이지 크기와 최대 페이지 수를 제한하고 `write_date`, `id` 순으로 증분 조회한다.
- JSON-2 여러 호출이 하나의 트랜잭션이라고 가정하지 않는다.

## 6. 데이터 모델

### 6.1 거래처 `res.partner`

| 필드 | 의미 | 사용 원칙 |
|---|---|---|
| `id` | 현재 Odoo DB 내부 ID | 관계 연결에 사용 |
| `ref` | 업무상 거래처 코드 | 외부 시스템 간 장기 식별자 후보 |
| `name` | 표시명 | UI 표시 |
| `is_company`, `parent_id` | 회사·담당자 관계 | 고객·공급사 연락처 구분 |
| `active` | Odoo 아카이브 여부 | 과거 거래 중단이나 협상 실패 표시로 사용하지 않음 |
| `write_date` | 마지막 변경 시각 | 증분 동기화와 변경 감지 |

`active=false`인 Partner는 신규 문서 후보에서 제외할 수 있지만 과거 거래 이력은 유지한다. 거래 실패 여부와 다음 거래 참여 자격은 별도 거래·정책 상태로 판단한다.

### 6.2 품목 `product.template`, `product.product`

| 필드 | 의미 | 사용 원칙 |
|---|---|---|
| `id` | Odoo 내부 관계 키 | Product, Stock Move, Order Line 연결 |
| `default_code` | 사람이 관리하는 업무 품목 코드 | API·BOM 룰·리포트의 장기 품목 코드 |
| `name` | 표시명 | GPU/서버 제품명 |
| `uom_id` | 기본 단위 | 재고·소요·주문 수량 통일 |
| `purchase_ok`, `sale_ok` | 구매·판매 가능 여부 | 문서 생성 가능성 검증 |
| `active`, `write_date` | 아카이브·변경 시각 | 신규 사용 제외·증분 동기화 |

`id`와 `default_code`를 합치지 않는다. `id`는 DB 내부 관계 무결성을 위한 값이고 `default_code`는 데이터 이관·재생성 후에도 유지할 업무 코드다. 최소 데이터는 GPU 3~5종과 서버 완제품으로 구성한다.

### 6.3 공급사 공개 조건 `product.supplierinfo`

| 필드 | 의미 |
|---|---|
| `id`, `partner_id` | 가격 조건과 공급사 |
| `product_tmpl_id` / `product_id` | 대상 GPU 또는 부품 |
| `min_qty` | 해당 단가가 적용되는 MOQ |
| `price`, `currency_id` | 공개·계약 단가와 통화 |
| `delay` | 표준 리드타임 |
| `date_start`, `date_end` | 조건 유효기간 |
| `write_date` | 변경 감지 |

필요하면 공개 정보만 다음 사용자 정의 필드로 보완한다.

- `x_public_available_qty`: 공급사가 중앙에 공개한 가용량
- `x_public_available_qty_as_of`: 공개 가용량을 확인한 시각
- `x_public_available_qty_valid_until`: 공개 가용량의 사용 만료 시각
- `x_public_inventory_source`: 판매자 Agent·수동 확인 등 값의 출처
- `x_specification`: GPU 모델·메모리·제조사·등급 등 규격
- `x_quality_score`: 검증된 규격을 0~100으로 정규화한 품질 점수
- `x_quality_score_version`: 점수를 만든 평가표 버전
- `x_integration_enabled`: 해당 공개 조건을 연동 후보로 사용할지

`x_quality_score`는 실제 점수이고 `x_quality_score_version`은 그 점수의 계산 규칙 버전이다. 같은 협상 후보는 동일 버전으로만 비교한다. 가격이 비싸다는 이유로 품질 점수를 높이지 않는다.

이 값은 도입 기업 Odoo의 구매자 측 ATP 재고와 다른 **판매자 공개 재고 snapshot**이다. 만료되었거나 출처를 검증할 수 없는 값은 표준·협상 가능 수량으로 사용하지 않는다.

Odoo와 중앙에는 `x_floor_price`, 판매자 양보 속도, 고객별 할인 정책을 만들지 않는다.

### 6.4 CRM과 판매 문서

`crm.lead` Opportunity는 도입 기업 고객의 판매 기회다. 구매 RFQ로 사용하지 않는다.

| 모델·필드 | 용도 |
|---|---|
| `crm.lead.partner_id` | 서버를 구매할 고객 |
| `crm.lead.expected_revenue`, `probability` | 영업 기회 정보 |
| `sale.order.partner_id` | 견적·판매주문의 고객 |
| `sale.order.order_line` | 서버 완제품 또는 판매 부품과 수량·단가·납기 |
| `sale.order.state` | 견적·판매주문 상태 |
| `sale.order.write_date` | 견적 변경 감지 |

영업 담당자가 판매주문을 명시적으로 확정하거나 견적 조달 확인을 요청할 때 프로젝트가 부품 소요를 계산한다. CRM에 구매 예산·판매자 협상 상태를 섞어 넣지 않는다.

### 6.5 재고와 ATP 스냅샷

프로젝트는 품목·창고·기준 날짜별로 다음 값을 기록한다.

- 현재고
- 이미 확정된 출고 예약 수량
- 기준 날짜까지 확정적으로 입고될 예정인 수량
- 품질 보류·사용 불가 수량
- 약속 가능 수량(ATP)
- 근거가 된 Odoo Product·Stock Move·Picking ID와 조회 시각

기본 산식은 다음과 같다.

```text
ATP(기준일) = 사용 가능한 현재고
            - 기준일까지의 확정 출고 예약
            + 기준일까지의 확정 입고 예정
            - 품질 보류·안전재고
```

Odoo의 현재·예측 재고 필드만 복사하지 않고 기준 날짜와 창고를 명시한다. 취소·draft 이동을 포함할지와 입고 신뢰도를 Odoo 19 실제 상태 값으로 확정한다.

### 6.6 프로젝트 내부 모델

#### `bom_rules`

- 완제품 `default_code`
- 부품 `default_code`
- 완제품 한 대당 부품 수량
- 손실·안전 계수
- 유효기간과 버전

MRP를 사용하지 않고 프로젝트 DB에서 결정적으로 전개한다.

#### `procurement_requirements`

- `requirement_id`, `source_type`: `SALES_ORDER`, `REORDER_POINT`, `QUOTE_CHECK`
- Odoo company·warehouse·source document ID
- 제품·수량·UoM·필요일
- 총예산과 선택적 단가 상한
- `QUALITY_FIRST` 또는 `PRICE_FIRST`
- 최소 규격·품질·납기
- 상태: `DRAFT`, `READY`, `GATED`, `NEGOTIATING`, `APPROVAL_PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`
- 입력 hash, 생성·변경 시각

#### `standard_contract_snapshots`

- Odoo Supplierinfo·Reordering Rule·Blanket Order와 사용자 정의 계약 필드의 원본 ID
- 각 원본의 `write_date`와 실행 당시 payload hash
- 공급사·품목·창고·통화
- 계약 수량 상한, 표준 리드타임, 계약 단가와 허용 편차
- 목표 재고·MOQ·품질·규격·유효기간
- 1회·기간별 금액 한도와 승인 기준 버전

Odoo가 공개 계약·재주문·승인 조건의 기준 시스템이다. 프로젝트의 `standard_contract_snapshots`은 실행 당시 판단을 재현하기 위한 불변 복사본이며 수정 가능한 계약 원장이 아니다. 값이 충돌하면 Odoo 최신 원본을 다시 읽어 새 실행 snapshot을 만들고 기존 snapshot은 변경하지 않는다.

#### `proposal_runs`, `approval_decisions`, `audit_events`

- 실행 ID·멱등 키와 입력 snapshot hash
- `STANDARD` 또는 `NEGOTIATION` 경로
- 후보별 공개 제안·적격 여부·점수·제외 사유
- 적용한 정책·BOM·품질 평가 버전
- 감사자 종류, 검사 규칙, 차단 여부와 사유
- 확정자, 확정 시각, 승인 단계와 당시 근거 요약
- Odoo draft 문서 ID와 외부 참조

#### `partner_trust_snapshots`

- Odoo Partner ID와 산정 기준일
- 거래 횟수·누적 금액·납기 준수율·결제 지연 요약값
- 정규화된 Buyer/Seller 신뢰도와 산식 버전
- 근거 데이터 기간, 생성 시각과 `source_type`

Accounting 기능은 프로젝트 범위에 포함하지 않는다. 최소 시연의 결제 지연 값은 초기 데이터로 준비한 사전 산출 지표를 사용하고 `source_type=SIMULATION_SEED`로 표시한다. `account.move`나 결제 API는 직접 조회하지 않는다. 운영용 실제 원천은 후속 구현에서 외부 회계 집계, 검증된 Partner 요약 필드 또는 별도 범위 승인을 받은 어댑터 중 하나로 확정한다.

## 7. 공통 의사결정과 승인 규칙

### 7.1 표준 조건 게이트

다음 조건을 모두 만족할 때만 표준 경로로 보낸다.

- 유효한 기존 공급 계약·가격 조건이 있다.
- 주문 수량이 계약 상한 이내이고 MOQ를 만족한다.
- 요구 납기가 표준 리드타임보다 짧지 않다.
- 예상 총액이 정책 한도와 구매 예산 이내다.
- 품목·UoM·통화·규격·품질 버전이 일치한다.
- 공급 공개 가용량 또는 합의된 공급 능력이 충분하다.
- 정책이 활성 상태이고 유효기간 안이다.

값이 없거나 불명확하면 표준으로 추정하지 않고 예외로 보낸다. 조건을 자동 완화하지 않는다.

### 7.2 승인 단계

기획서 v5의 초기 기본값을 정책으로 구성 가능하게 저장한다.

#### 1단계 간소 확인

- 기준 단가 대비 인상률 `+5%` 이내이며 인하는 제한하지 않음
- 요청 납기 대비 지연 `+3일` 이내
- 발주 총액 `5,000,000원` 이하
- 세 조건을 모두 만족

구매 담당자가 근거 요약을 확인하고 한 번의 명시적 조작으로 확정할 수 있다.

#### 2단계 정식 승인

위 조건을 하나라도 벗어나거나 예외 협상을 거친 건이다. 초과 항목과 초과 폭을 표시하고 구매 담당자 검토 후 승인권자가 확정한다.

어느 단계에서도 스케줄러나 Agent가 승인하지 않는다. 사람의 확정 동작이 있으면 확정자·시각·정책 버전·재고 snapshot과 근거를 저장한다. 사람의 명시적 확정으로 Odoo 문서를 확인 상태로 바꾸는 기능은 허용할 수 있지만 이메일·EDI 송부는 별도 수동 동작으로 둔다.

### 7.3 구매 전략과 다속성 평가

하드 조건을 먼저 검사한 뒤 적격 후보만 순위화한다.

- 하드 조건: 예산, 단가 상한, 수량, 최소 규격·품질, 납기, UoM, 통화, 인증
- `QUALITY_FIRST`: 품질·사양 적합도를 우선하고 같은 수준에서는 총액·납기를 비교
- `PRICE_FIRST`: 총액을 우선하고 같은 수준에서는 품질·납기·신뢰도를 비교
- 신뢰도: Odoo 거래 횟수·누적 금액·납기 준수율·결제 지연 이력을 버전 산식으로 계산

가격·수량·납기·사양·신뢰도 점수와 가중치, 동점 해소 키를 snapshot으로 저장한다. LLM이 최종 점수나 순위를 임의로 바꾸지 못한다.

### 7.4 LLM 사용 경계

LLM 사용 지점은 기획서의 다음 여섯 곳으로 제한한다.

1. 비정형 카탈로그·견적서·요청서를 검증 가능한 구조 필드로 파싱
2. 표현이 다른 사양의 의미 기반 매칭과 RAG 근거 제시
3. 후속 S7의 발주서·거래명세서·세금계산서 3자 대조 설명
4. 알고리즘이 만든 제안 조합의 근거 문장 생성
5. Sales Assistant의 자연어 질의 해석과 read-only 도구 선택
6. 협상 결과·승인 근거·리포트의 자연어 요약

가격, ATP, 예산 적격 여부, 표준 게이트, 감사 규칙과 최종 순위는 일반 코드가 계산한다. LLM 출력은 schema 검증과 근거 ID 확인을 통과해야 한다.

### 7.5 최소 구현 성과 지표

업무 절감 효과를 검증하기 위해 다음 이벤트 시각을 `proposal_runs`와 `approval_decisions`에 저장한다.

- `requirement_detected_at`: 소요 감지
- `proposal_ready_at`: 발주안 또는 협상 후보 준비 완료
- `review_opened_at`: 담당자 검토 시작
- `decision_at`: 승인·거절 결정
- `odoo_confirmed_at`: 사람 조작으로 Odoo 문서 확인
- `sent_at`: 담당자가 외부 송부한 시각. 프로젝트가 자동 생성하지 않음

최소 지표는 다음과 같다.

- 1단계 처리 비율: `LEVEL_1 확정 건수 / 전체 확정 건수`
- 표준 경로 비율: `STANDARD 건수 / 전체 판정 건수`
- 사람 검토 시간: `decision_at - review_opened_at`
- 발주안 준비 시간: `proposal_ready_at - requirement_detected_at`
- 표준 경로 Agent 절감: `STANDARD`의 `agent_call_count=0` 비율

시스템 처리 시간과 사람 검토 시간을 섞지 않고 S1과 S2를 분리해 집계한다.

## 8. 최소 구현 시나리오

### 8.1 S1 — 표준 발주

#### 트리거

- 지정 창고의 예측 재고가 재주문 기준선 미만
- 또는 확정된 판매주문에서 계산한 부품 소요가 ATP를 초과

#### 자동 실행 방식

- Odoo Reordering Rule과 미결 구매·입출고가 보충 필요성의 기준이다.
- 프로젝트 스케줄러가 `S1_SCAN_INTERVAL_SECONDS` 주기로 Odoo 19 JSON-2를 통해 보충 필요 항목을 조회한다. 실제 모델·메서드는 대상 DB `/doc` 검증 후 확정한다.
- 수동 `POST /api/procurement/requirements/replenishment`는 운영 자동 트리거가 아니라 관리자 재처리·smoke test 용도로만 사용한다.
- 멱등 키는 company, warehouse, product, reordering rule 또는 source sale order, required date bucket과 입력 snapshot hash로 만든다.
- 기존 승인 대기 RFQ와 미결 PO를 주문 예정 재고에 포함하고 같은 소요의 새 RFQ를 만들지 않는다.
- 실행 실패는 다음 스캔에서 재개하며 dead-letter 전까지 원본 소요를 잃지 않는다.

#### 흐름

1. Odoo 재고·미결 입출고·Supplierinfo와 프로젝트 정책을 조회한다.
2. 같은 품목·창고·대상 기간의 미결 소요와 draft 주문을 멱등 키로 확인한다.
3. 목표 재고 또는 판매 소요를 기준으로 주문 수량을 결정한다.
4. 표준 조건 게이트를 결정적 함수로 실행한다.
5. 통과하면 Agent를 호출하지 않고 draft `purchase.order` RFQ를 만든다.
6. 재고, 수량, 기준 단가 대비 차이, 총액, 납기와 정책 버전을 승인 근거로 제시한다.
7. 구매 담당자의 명시적 확정 직전에 ATP, 미결 PO, 계약 `write_date`와 원본 판매주문 상태를 다시 읽는다.
8. 재검증을 통과하기 전에는 Odoo 주문을 확정하거나 발주서를 송부하지 않는다.

#### 완료 기준

- 표준 입력에서 Agent 호출 횟수 0회
- 같은 트리거를 반복해도 draft RFQ 한 건
- 1단계 승인 근거와 확정자 감사 이력 확인
- 재고가 목표 수준 이상이면 주문·협상 모두 생성하지 않음

### 8.2 S2 — 예외 협상

#### 예외 트리거

- 계약 수량 상한 초과
- 급납기로 표준 리드타임 미달
- 예산·금액 한도 또는 가격 허용 범위 초과
- 계약 부재·만료, 규격·품질·통화 불일치
- 표준 공급사의 공개 가용량 부족

#### 흐름

1. 중앙이 공개 재고·MOQ·사양·납기로 적격 판매자를 스크리닝한다.
2. 바이어 Agent가 수량·납기·사양·공개 가능한 우선순위를 담은 요청을 만든다.
3. 각 Seller Agent가 자기 저장소의 하한·재고 정책·거래처 이력만 사용해 제안을 계산한다.
4. 가격은 라운드 비율, 판매자 재고·회전율과 Buyer 신뢰도로 E값을 정한 Boulware/Conceder 함수가 계산한다.
5. 판매자 측 감사자(S8)가 비공개 정책 위반을 발신 전에 검사한다.
6. 중앙 감사자(S8)가 수신 제안의 공개 재고·카탈로그·스키마를 검사한다.
7. 적격 제안을 구매 전략과 다속성 점수로 순위화한다.
8. 2단계 승인 화면에 복수 후보안, 점수·근거·초과 조건을 제시한다.
9. 사람의 확정 전에는 낙찰·계약·발주가 성립하지 않는다.

#### 가격 알고리즘 원칙

- LLM은 가격 숫자를 결정하지 않는다.
- 각 Seller Agent는 자기 시작가와 최저수용가 사이에서만 계산한다.
- 상대의 비공개 상한을 입력받지 않는다.
- 최대 라운드와 거래당 LLM 호출 상한을 둔다.
- 같은 입력·정책 버전이면 같은 가격 궤적을 재현할 수 있어야 한다.

최소 구현의 기준식을 다음처럼 고정한다.

```text
r = current_round / max_rounds
price(r) = floor_price + (start_price - floor_price) × (1 - r^E)
```

- 기획서 기준에 따라 판매자 재고가 적어 빠른 양보 정책이면 `E < 1`, 재고 여유가 있어 완만한 양보 정책이면 `E > 1`이 되도록 inventory urgency 구간을 정의한다.
- Buyer 신뢰도는 시작가 또는 E에 제한적으로 반영하되 최저수용가·실제 재고·최대 납기를 변경할 수 없다.
- 입력에는 판매자 실제/정책 재고, 판매 속도, 회전율, 재고 `as_of`, Buyer 신뢰도 snapshot과 산식 버전을 포함한다.
- 판매자 공개 재고와 비공개 정책 재고가 다르면 공개 제안 수량은 둘 중 더 보수적인 값 이하여야 한다.
- 반올림 단위, 통화 최소 단위, E 구간과 `formula_version`을 저장한다.

#### 완료 기준

- 표준 범위 초과 건만 협상 실행
- 셀러별 정책 저장소의 상호 격리
- 가격·납기·사양이 다른 복수 후보안과 결정적 순위
- 사람 승인 전 Odoo 주문 확정 0건
- 네트워크 재시도에도 협상·draft 주문 중복 0건

### 8.3 S3 — 약속 가능 수량 질의

영업 어시스턴트는 Odoo 조회 도구만 사용한다.

예시 질의:

> 9월 20일까지 RTX 계열 GPU 30개를 고객에게 약속할 수 있는가?

응답에는 다음을 포함한다.

- 기준 날짜·창고·품목
- 현재고, 예약 출고, 확정 입고 예정과 안전재고
- 계산된 ATP와 부족 수량
- 근거 Odoo 레코드와 조회 시각
- 산출 불가 또는 불확실한 항목

읽기 전용으로 동작하며 질의만으로 재고·견적·주문을 변경하지 않는다. 근거가 부족하면 추정 답변을 만들지 않는다.

완료 기준: 준비된 재고 시드에서 ATP 숫자와 산식이 Odoo 근거 레코드와 일치하고, 도구 권한이 읽기로 제한된다.

#### 최소 Odoo 화면

- Sales 화면 우측 하단 상주형 OWL Assistant
- 현재 Sale Order·고객·창고를 질의 context로 전달
- ATP 결과의 현재고·예약·입고 예정·안전재고와 근거 레코드 펼쳐보기
- 기준 날짜·창고·조회 시각과 불확실한 값 표시
- 질의만으로 Odoo 레코드가 변경되지 않는 read-only 상태 표시

### 8.4 S4 — 견적 즉시 조달 확인

영업 담당자가 draft `sale.order` 또는 견적 품목을 대상으로 명시적으로 실행한다.

1. 서버 완제품이면 버전이 고정된 BOM 룰로 GPU 부품 소요를 전개한다.
2. 기준 납기일의 ATP를 계산한다.
3. 부족 수량에 표준 조건 게이트를 실행한다.
4. 표준이면 계약 단가·납기로 조달 예상치를 계산한다.
5. 예외이면 S2 협상을 실행하거나 이미 같은 조건의 진행 중 협상을 재사용한다.
6. 영업사원에게 조달 가능 수량·예상 단가·예상 입고일·견적 마진과 위험을 제시한다.
7. 견적 수정·송부·판매주문 확정은 영업 담당자의 명시적 동작으로만 수행한다.

완료 기준: ATP 이내 견적, 부족하지만 표준 조달 가능한 견적, 예외 협상이 필요한 견적 세 경우를 구분하고 예상 마진의 계산 근거를 표시한다.

#### 최소 Odoo 화면

- Sale Order form의 `조달 가능성 확인` 버튼
- BOM 소요·ATP·부족 수량·표준/협상 경로 표시
- 예상 조달 원가·입고일·판매 마진과 위험 근거
- 계산 결과를 견적에 반영하기 전 변경 전·후 비교와 사용자 확인
- 구매안 또는 협상 진행 화면으로 이동하는 링크

### 8.5 S8 — 감사자 차단

#### 판매자 측 감사자

- 제안 단가가 판매자 최저수용가 미만인지
- 실제·정책 재고보다 많은 수량을 약속하는지
- 정책상 불가능한 납기·할인인지
- 고객별 권한과 정책 버전이 맞는지

위반이면 가격을 하한으로 조용히 보정하지 않고 **외부 발신 전에 차단**한다. 중앙에는 `SELLER_POLICY_BLOCKED`와 공개 가능한 사유만 전달하고 하한 숫자는 전달하지 않는다.

#### 중앙 감사자

- 공개 등록 재고 초과
- 카탈로그에 없는 사양 주장
- UoM·통화·필수 필드·메시지 스키마 위반
- 실행 ID·라운드·서명·재전송 중복

기성 가드레일 프레임워크는 Guardrails AI, NeMo Guardrails, Llama Guard 3, OpenAI Moderation 중 최소 구현 초기에 한 종류를 선정하여 중앙 자연어 출력 검증에 적용한다. 선택 기준은 한국어 지원, 구조화 출력 검사, self-host 가능성, 지연과 비용이다. 가격·재고·스키마 규칙 검사는 프레임워크에 맡기지 않고 코드로 구현한다.

완료 기준: 의도적으로 하한을 위반한 Seller Agent 출력을 중앙 협상 로그에 제안으로 저장하기 전에 차단하고, 하한값을 노출하지 않은 감사 이벤트를 남긴다.

## 9. 최소 구현 API와 Odoo 쓰기

### 9.1 프로젝트 API 초안

| API | 권한 | 목적 |
|---|---|---|
| `GET /api/integrations/odoo/health` | ADMIN | 버전·DB·권한·필수 모델 확인 |
| `POST /api/integrations/odoo/sync/master-data` | INTEGRATION | Partner·Product·Supplierinfo 증분 동기화 |
| 내부 scheduler | INTEGRATION | Odoo Reordering Rule을 주기적으로 확인해 S1 소요 생성·평가 |
| `POST /api/procurement/requirements/replenishment` | ADMIN | S1 관리자 재처리·smoke test. 운영 주 트리거가 아님 |
| `POST /api/procurement/requirements/{id}/evaluate` | PURCHASER | 표준/예외 게이트 실행 |
| `GET /api/procurement/proposals/{id}` | PURCHASER/APPROVER | 근거·후보·감사 결과 조회 |
| `POST /api/procurement/proposals/{id}/approve` | PURCHASER/APPROVER | 사람의 명시적 확정과 감사 이력 |
| `POST /api/procurement/proposals/{id}/reject` | PURCHASER/APPROVER | 거절과 사유 기록 |
| `POST /api/assistant/atp-query` | SALES | S3 ATP 조회·설명 |
| `POST /api/sales/quotes/{odoo_id}/procurement-check` | SALES | S4 즉시 조달·마진 확인 |
| `GET /api/negotiations/{run_id}` | 참가자/감사자 | S2 라운드·순위·공개 로그 조회 |

기존 `/api/sellers`와 `/api/deals`는 새 DTO로 교체하고 호환 종료 시점을 명시한다. 어떠한 응답에도 판매자 최저수용가와 구매자 비공개 상한을 함께 포함하지 않는다.

### 9.2 Odoo 최소 사용자 정의 필드

Odoo 커스텀 모듈은 화면·링크 확장에 필요한 최소 범위로 한정한다.

- `purchase.order.x_deal_run_id`: 프로젝트 실행 연결과 중복 방지
- `purchase.order.x_deal_path`: `STANDARD` 또는 `NEGOTIATION`
- `purchase.order.x_deal_approval_level`: `LEVEL_1`, `LEVEL_2`
- `purchase.order.x_deal_basis_summary`: 민감정보가 제거된 근거 요약
- `sale.order.x_deal_last_check_id`: 마지막 S4 조달 확인 결과
- `product.supplierinfo.x_contract_quantity_cap`: 표준 계약 수량 상한
- `res.company` 또는 전용 설정의 1단계 가격·납기·총액 기준
- Sales 화면의 OWL Assistant와 Sale Order 조달 확인 버튼
- Purchase 화면의 근거 요약·승인 단계와 프로젝트 결과 링크

`x_deal_run_id`에는 unique constraint를 둔다. 최저수용가, 구매자 상한, Seller 양보 정책은 Odoo 필드로 추가하지 않는다.

### 9.3 외부 행위 제한

- 스케줄러와 Agent는 draft RFQ까지만 생성한다.
- 승인 API는 인증된 사람의 명시적 조작에서만 호출된다.
- 승인 권한과 Odoo company·문서 상태를 다시 확인한다.
- 이메일 발송, EDI 전송, 지급·결제 메서드는 allowlist에 넣지 않는다.
- 승인 후 발주서 송부는 구매 담당자가 Odoo에서 직접 수행한다.

## 10. 최소 구현 단계와 산출물

### 10.1 0단계 — Odoo·도메인 준비

- Odoo 19 버전, HTTPS, JSON-2와 `/doc` 확인
- CRM, Sales, Inventory, Purchase와 전용 bot 설치·권한 설정
- 확보한 GPU 납품 이력 약 30건의 출처·정제 기준과 사용 범위를 기록
- GPU 3~5종, 서버 완제품 최소 2종과 버전이 고정된 BOM 룰 시드
- 공개 기준가에서 ±10~15% 범위로 Seller별 제시가를 생성하고 하한가는 각 Seller 비공개 fixture에만 생성
- 가격·재고·MOQ·납기 정책이 다른 공급사 3곳 시드
- 신규·거래 1년·거래 3년 이력을 가진 고객 3곳과 `SIMULATION_SEED` 신뢰도 snapshot
- 판매·구매·재고 이력과 공급사 공개 계약 조건 시드
- BOM 룰과 표준 계약 정책 시드
- S1·S2·S3·S4·S8별 고정 입력·기대 결과와 seed 재생성 명령

완료 기준: 필수 모델·필드를 bot으로 읽고 테스트 데이터 ID를 고정 fixture로 기록한다.

### 10.2 1단계 — 기반 리팩터링

- 고정 Item Enum 제거
- Seller별 독립 프로세스/컨테이너, 비공개 저장소와 서비스 자격증명
- 중앙–Seller OpenAPI/JSON Schema, 서명·nonce·replay 방지와 contract test
- Odoo JSON-2 client·mapper·schema probe
- PostgreSQL을 권장하되 일정상 SQLite면 단일 worker와 unique 제약 사용
- 인증, 역할 권한, CORS와 비밀값 마스킹
- 실행·Outbox·감사 로그 멱등 모델

완료 기준: 기존 협상 API에서 하한·상한이 노출되지 않고 같은 Odoo 레코드 동기화가 중복되지 않는다.

### 10.3 2단계 — S1 표준 발주

- 재주문점·판매 소요 기반 `ProcurementRequirement`
- 자동 스캔 주기, 실패 재개와 관리자 재처리 API
- ATP snapshot과 표준 조건 게이트
- draft Purchase RFQ 멱등 생성
- 1·2단계 승인 근거와 사람 확정 이력

### 10.4 3단계 — S2 예외 협상과 S8 감사자

- 판매자별 Agent·정책 저장소
- 결정적 Boulware/Conceder 가격 함수
- 중앙 공개 스크리닝과 다속성 평가
- 판매자 측 발신 전 감사자와 중앙 수신 감사자
- 중앙 자연어 출력용 가드레일 후보를 비교하고 한 종류 선정·어댑터 적용
- 최대 라운드·timeout·비용 상한

### 10.5 4단계 — S3 영업 ATP 어시스턴트

- 자연어 질의를 구조화된 품목·창고·날짜로 변환
- read-only Odoo 도구
- ATP 산식과 근거 레코드 응답
- 산출 불가·권한 없는 질의의 안전 실패
- Odoo Sales 화면 우측 하단 OWL Assistant

### 10.6 5단계 — S4 견적 즉시 조달 확인

- draft Sale Order 조회
- BOM 전개·ATP 부족분 계산
- S1/S2 경로 재사용
- 예상 조달 원가·납기·판매 마진과 위험 설명
- Sale Order 조달 확인 버튼과 변경 전·후 사용자 확인 UI

### 10.7 6단계 — 통합 시연과 안정화

- S1·S2 대조 시연
- S3 ATP 계산 설명
- S4 견적 조달 확인
- S8 발신 전 차단
- 재시도·중복·권한·비밀정보 회귀 테스트
- 승인자·시각·근거 리포트
- 1단계 비율, 표준 경로 비율, 사람 검토 시간과 발주안 준비 시간 지표

## 11. 최소 구현 테스트

### 11.1 단위 테스트

- JSON-2 URL·bearer·DB 헤더와 필드 allowlist
- Odoo 관계값·Decimal 금액·UoM 변환
- `id`와 `default_code` 매핑
- BOM 버전별 정확한 부품 소요
- 날짜별 ATP 산식과 예약·입고 경계
- 표준 게이트의 수량·납기·금액 경계값
- 1단계 `+5%`, `+3일`, `5백만원` 경계
- `QUALITY_FIRST`, `PRICE_FIRST`의 결정적 순위
- 품질 점수 버전 불일치 거부
- Boulware/Conceder 라운드별 가격 재현성
- 재고·회전율·Buyer 신뢰도 변화에 따른 E값 방향과 최저수용가 하한
- 만료되거나 출처 없는 Seller 공개 재고 거부
- 판매자 감사자의 하한·재고·납기 위반 차단
- 중앙 감사자의 스키마·공개 재고 위반 차단
- 선정한 가드레일의 유해·비정상 자연어 출력 차단과 정상 출력 오탐 회귀
- 중앙–Seller 메시지 서명·nonce·만료·상태 전이·비공개 필드 부재
- Seller A 자격증명으로 Seller B 저장소·API 접근 차단
- 비밀값 로그·DTO 누출 검사

### 11.2 통합 테스트

- **S1:** 재고 기준선 미달 → 표준 게이트 통과 → draft RFQ 1건 → 사람 승인
- **S1:** 자동 스캔만으로 소요가 생성되고 수동 API 없이 draft RFQ 준비
- S1 반복 호출·네트워크 재시도에도 같은 RFQ 유지
- S1 승인 직전 재고·계약 변경 시 보류·재판정
- **S2:** 대량주문 → 복수 Seller Agent 협상 → 감사 → 순위 → 2단계 승인
- **S2:** 급납기 → 표준 경로가 아닌 예외 협상 진입
- **S3:** 예약·입고 예정이 있는 기준일 ATP와 근거 일치
- **S4:** ATP 부족 견적 → BOM 부족분 → S1 또는 S2 → 예상 마진
- **S3·S4 UI:** Odoo 화면에서 근거를 확인하고 사용자 확인 전 레코드 변경 0건
- **S8:** 하한 미만 제안이 중앙 제안 로그 전에 차단되고 하한 숫자는 미노출
- 승인 없는 경우 Odoo 문서 확정·외부 송부 0건
- 사용자 company·역할이 다른 문서 접근 차단
- 고정 seed 재생성 후 동일한 시나리오 결과와 순위
- KPI 이벤트로 S1·S2의 시스템 처리 시간과 사람 검토 시간 분리

### 11.3 실제 Odoo smoke test

1. Odoo 19 health·`/doc`·bot 권한 성공
2. 고객·공급사·GPU·서버·Supplierinfo·재고 동기화
3. S1 draft RFQ와 중복 방지 확인
4. S2 협상·다속성 순위·사람 승인 확인
5. S3 ATP 값을 Odoo 재고 화면과 대조
6. S4 견적의 조달 가능량·원가·마진 대조
7. S8 차단 이벤트와 판매자 비밀 미노출 확인
8. 이메일·EDI·결제 호출이 발생하지 않았음을 감사 로그로 확인

## 12. 최소 구현 완료 기준

- Odoo 19 JSON-2로 CRM·Sales·Inventory·Purchase 데이터를 읽는다.
- GPU 3~5종과 서버 완제품, 고객·공급사 각 3곳의 시드가 준비된다.
- 판매주문 또는 재주문점에서 부품 소요를 중복 없이 만든다.
- S1 표준 발주안은 Agent 호출 없이 draft RFQ와 승인 근거를 만든다.
- S2 예외 거래만 Agent 협상을 실행하고 복수 후보안을 순위화한다.
- S3가 날짜·창고 기준 ATP와 계산 근거를 제공한다.
- S4가 견적의 부족 부품·조달 가능성·예상 원가·납기·마진을 제시한다.
- S8이 판매자 비공개 정책 위반 제안을 발신 전에 차단한다.
- 판매자 하한과 구매자 비공개 상한이 Odoo·중앙 DB·상대방·일반 로그에 노출되지 않는다.
- 가격은 결정적 알고리즘이 계산하고 LLM은 구조화·스펙 매칭·설명에만 사용된다.
- 사람 승인 전 주문 확정과 외부 송부가 발생하지 않는다.
- 모든 확정에 확정자·시각·승인 단계·정책/재고 근거가 남는다.
- 모킹 자동 테스트와 실제 Odoo smoke test가 모두 통과한다.

## 13. 후속 구현 계획

### 13.1 S5 — 수주 리스크 사전 점검

판매주문 확정 전 ATP·조달 리드타임·협상 진행 상태로 납기 실현 가능성을 검사하고 납기 조정 또는 급납기 협상을 대안으로 제시한다. 확정은 영업 담당자가 수행한다.

### 13.2 S6 — 단가 이상 감지

품목·공급사·기간별 매입 단가의 정상 범위를 계산하고 이상 건을 근거와 함께 재협상 후보로 만든다. 자동 재협상하지 않고 구매 담당자가 트리거를 확인한다.

### 13.3 S7 — 매입 문서 3자 대조

발주서·거래명세서·세금계산서 업로드 문서에서 품목·수량·단가·합계를 추출하고 불일치만 제시한다. Accounting 앱을 기능 범위에 포함하지 않으며, 세금계산서 원본과 추출값을 프로젝트 문서 저장소에서 다룬다. 지급 여부는 사람이 결정한다.

### 13.4 S9 — 원가 변동과 판매 마진 피드백

확정 매입 단가를 완제품 원가에 반영하고 미확정 판매 견적의 마진을 다시 계산한다. 확정 판매주문은 자동 변경하지 않고 영업 담당자에게 할인 여력 또는 역마진 위험만 알린다.

### 13.5 S10 — 과거 영업 기록 질의

거래처별 판매 이력·평균 할인율·납기 준수·결제 지연 이력을 자연어로 질의하고 근거 레코드와 함께 답한다.

### 13.6 S11 — 거래처 리스크 브리핑

미팅 전에 거래·납기·분쟁·결제 이력을 요약한다. KYC·AML·제재 대상 판정은 범위 밖이며 필요한 연동 자리와 감사 로그만 확보한다.

### 13.7 추가 고도화

- 매입 문서 비정형 파싱과 스펙 RAG 고도화
- 거래 이력 기반 신뢰도 산식 검증
- 협상 반성 요약을 다음 협상에 사용하는 인컨텍스트 메모리
- 고정 시뮬레이션 세트로 메모리 사용 전후 성사율·낙찰가 비교
- A2A·AP2 등 회사 간 Agent 프로토콜 어댑터
- PostgreSQL, 작업 큐, Outbox/Inbox, dead-letter와 다중 인스턴스
- 강화학습은 충분한 실거래 로그와 별도 승인 전까지 보류

## 14. 주요 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| CRM 고객과 공급사를 혼동 | 판매·조달 문서가 잘못 연결됨 | 관계 문서별 역할 판정, 고정 party role 금지 |
| Odoo 필드·권한 차이 | JSON-2 매핑 실패 | `/doc` probe, DTO allowlist, 테스트 DB |
| 오래된 재고 snapshot | 과다 판매·불필요한 구매 | 기준일·창고·조회시각 기록, 승인 직전 재조회 |
| BOM 룰 오류 | 부품 소요·마진 왜곡 | 버전 고정, 샘플 서버 수작업 대조 |
| 판매자 하한 중앙 유출 | 협상 무의미·영업기밀 침해 | 판매자별 저장소, 계약 테스트, 로그 DLP 검사 |
| LLM 가격 결정 | 재현 불가·정책 위반 | 결정적 가격 함수와 발신 전 감사자 |
| 표준 게이트 과대 허용 | 협상 필요 거래가 자동 경로로 진입 | 모든 조건 AND, 누락값은 예외, 정책 버전 감사 |
| 중복 소요·RFQ | 과잉 발주 | source hash·기간 멱등 키·Odoo unique 참조 |
| ATP에 불확실한 입고 포함 | 납기 약속 실패 | 확정 상태만 포함, 신뢰도 표시, 근거 레코드 제공 |
| Agent가 외부 행위를 실행 | 무권한 계약·송부 | 도구 allowlist에서 confirm/send/pay 제거, 사람 조작 검사 |
| 품질·신뢰도 산식 편향 | 잘못된 후보 순위 | 버전 산식, 원자료·점수 분리, 회귀 fixture |
| 최소 구현 과대화 | S1~S4·S8 일정 지연 | 후속 시나리오 API 자리만 두고 구현하지 않음 |

## 15. 착수 전 확인 항목

- [ ] Odoo 19 Edition과 JSON-2 외부 API 사용 가능 조건
- [ ] 별도 서버 HTTPS·인증서·프로젝트 서버 방화벽
- [ ] Odoo DB 이름·company·warehouse·timezone
- [ ] 읽기 bot과 제한된 쓰기 bot API 키
- [ ] `/doc`의 CRM·Sales·Inventory·Purchase 모델·메서드
- [ ] 고객 3곳, 공급사 3곳과 업무 코드
- [ ] GPU 3~5종, 서버 완제품과 UoM
- [ ] 서버별 BOM 룰·손실계수·버전
- [ ] 창고별 안전재고·예약·입고 예정 포함 기준
- [ ] 공급사 공개 단가·MOQ·계약 상한·표준 리드타임
- [ ] 판매자별 비공개 정책 저장소와 Agent 인증 방식
- [ ] 품목별 사양 평가표·품질 점수 버전
- [ ] `QUALITY_FIRST`, `PRICE_FIRST` 가중치와 동점 규칙
- [ ] 1단계 `+5%`, `+3일`, `5백만원`의 운영 승인
- [ ] 구매 담당자·영업 담당자·재고 담당자·승인권자 그룹
- [ ] Odoo 확정과 외부 송부를 구분한 사용자 동작
- [ ] S1·S2·S3·S4·S8 데모 fixture와 기대 결과

## 16. 검토에서 확인된 문제와 해결 게이트

이 절은 최신 기획서와의 대조 검토에서 확인된 문제를 추적한다. **`[최소 구현 필수]`가 붙은 항목은 S1·S2·S3·S4·S8 완료 전에 반드시 해결하고 테스트 증거를 남겨야 한다.** 표시가 없는 항목은 최소 구현을 막지 않는 후속 정리다.

### 16.1 최소 구현 필수 해결 항목

#### [최소 구현 필수] M-01 — Seller Agent 독립성

- 문제: 같은 프로세스에서 논리적으로만 저장소를 나누면 중앙이 최저수용가·양보 정책을 읽을 수 있고 S8의 발신 전 차단 경계가 성립하지 않는다.
- 해결: Seller별 독립 프로세스/컨테이너, 저장소, 서비스 자격증명과 네트워크 경계를 사용한다.
- 종료 조건: 중앙 계정과 다른 Seller 계정으로 비공개 정책 접근이 실패하고 하한 미만 제안이 중앙 전송 전에 차단된다.

#### [최소 구현 필수] M-02 — Odoo와 프로젝트의 계약 데이터 중복

- 문제: 계약 단가·MOQ·납기·상한을 두 시스템에서 수정하면 표준/예외 판정과 Odoo 주문 가격이 달라질 수 있다.
- 해결: Odoo를 계약·재주문·승인 조건의 기준 시스템으로 두고 프로젝트에는 원본 ID·`write_date`와 실행 당시 불변 snapshot만 저장한다.
- 종료 조건: 필드별 기준 시스템 표가 확정되고 Odoo 변경 후 새 실행은 최신 값, 과거 감사는 기존 snapshot을 사용한다.

#### [최소 구현 필수] M-03 — S1 자동 트리거 부재

- 문제: 수동 API만으로는 재고를 주기적으로 확인해 발주안을 자동 준비하는 S1을 만족하지 못한다.
- 해결: Odoo Reordering Rule을 기준으로 프로젝트 스케줄러가 JSON-2 조회·게이트·draft RFQ 생성을 수행하고 수동 API는 관리자 재처리로 제한한다.
- 종료 조건: 사람의 API 호출 없이 S1이 시작되고 중복 스캔·실패 재개·승인 직전 재검증 테스트가 통과한다.

#### [최소 구현 필수] M-04 — 중앙–Seller Agent 프로토콜 미정

- 문제: 메시지 계약과 인증이 없으면 상한·하한 유출, Seller 위조, replay, 라운드 역행과 중복 제안이 발생할 수 있다.
- 해결: OpenAPI/JSON Schema, Seller 인증, signature, timestamp, nonce, 만료와 상태 전이를 정의한다.
- 종료 조건: contract test가 비공개 필드 부재·서명·재전송·만료·상태 전이를 검증한다.

#### [최소 구현 필수] M-05 — Seller 재고와 E값 산식 불명확

- 문제: 구매자 ATP와 Seller 공급 재고를 혼동하거나 재고 시각·출처가 없으면 불가능한 수량을 협상하며 구현마다 반대 양보 곡선이 나올 수 있다.
- 해결: Seller 재고 snapshot에 `as_of`, `valid_until`, source를 두고 E값·가격식·반올림·신뢰도 조정을 버전화한다.
- 종료 조건: 고정 입력으로 가격 궤적을 재현하고 재고·신뢰도 변화가 기대 방향으로 반영되며 최저수용가를 위반하지 않는다.

#### [최소 구현 필수] M-06 — S3·S4 Odoo 사용자 화면 부재

- 문제: API만으로는 Odoo 화면 안에서 ATP 근거 확인과 견적 조달 검토를 수행한다는 핵심 사용 경험을 시연할 수 없다.
- 해결: Sales 우측 하단 OWL Assistant, Sale Order 조달 확인 버튼, 근거·마진·위험 표시와 변경 전 사용자 확인을 구현한다.
- 종료 조건: Odoo 화면에서 S3·S4를 수행하고 사용자 확인 전 견적·재고·주문 변경이 0건임을 확인한다.

#### [최소 구현 필수] M-07 — 재현 가능한 시뮬레이션 데이터 부족

- 문제: 고정 fixture가 없으면 S1/S2 분기, 전략별 순위, 신뢰도 조정과 S8 차단 결과를 반복 검증할 수 없다.
- 해결: 확보 GPU 이력, ±10~15% 제시가, Seller 3곳, 고객 신규·1년·3년, GPU·서버·BOM과 시나리오 기대 결과를 seed로 고정한다.
- 종료 조건: 빈 환경에서 seed를 재생성한 뒤 S1·S2·S3·S4·S8 결과와 순위가 동일하다.

#### [최소 구현 필수] M-08 — 업무 절감 KPI 부재

- 문제: 발주안 생성 여부만으로는 1단계 처리 비율과 사람 검토 시간 감소를 측정할 수 없다.
- 해결: 소요 감지, 안 준비, 검토 시작, 결정, Odoo 확인과 외부 송부 시각을 경로·승인 단계와 함께 저장한다.
- 종료 조건: S1·S2별 1단계 비율, 표준 경로 비율, 사람 검토 시간, 시스템 준비 시간과 Agent 호출 수를 계산할 수 있다.

#### [최소 구현 필수] M-09 — 신뢰도 결제 지연 값의 최소 구현 출처

- 문제: Accounting을 사용하지 않으면서 출처 표시 없이 결제 지연 값을 사용하면 실데이터로 오인하거나 재현할 수 없다.
- 해결: 최소 구현은 사전 산출 fixture만 사용하고 `source_type=SIMULATION_SEED`, 기준 기간과 산식 버전을 표시한다.
- 종료 조건: Odoo Accounting API 호출 0건, 모든 신뢰도 snapshot에 출처·기간·버전이 존재한다.

#### [최소 구현 필수] M-10 — 중앙 가드레일 미선정

- 문제: S8 구현 중 제품을 바꾸면 메시지 구조·배포·비용·한국어 품질 테스트가 다시 바뀔 수 있다.
- 해결: S2·S8 착수 전에 후보를 비교해 하나를 선정하고 `GuardrailPort` 뒤에 적용한다. 가격·재고·예산 판정은 코드에 유지한다.
- 종료 조건: 선정 기록과 한국어 정상·유해·스키마 오류 fixture의 차단율·오탐률·지연 테스트가 존재한다.

### 16.2 최소 구현 이후 정리 항목

#### 문서 파일명

현재 파일명에는 `payment`가 남아 있지만 Payment는 범위에서 제외됐다. 기존 링크를 조사한 후 `odoo-sales-procurement-integration-plan.md`로 변경하고 참조를 함께 갱신한다. 기능 구현을 막는 항목은 아니다.

#### 운영용 결제 지연 원천

최소 구현은 `SIMULATION_SEED`만 사용한다. S10 또는 운영 적용 전에 외부 회계 집계, 검증된 Partner 요약 필드, 범위 승인을 받은 Accounting read-only 어댑터 중 하나를 선택한다. 선택 전에는 합성 신뢰도를 실제 거래처 평가로 사용하지 않는다.

## 17. 최종 권장 범위

최소 구현을 다음 한 문장으로 고정한다.

> Odoo 19 JSON-2로 CRM·판매·재고·구매 데이터를 연결하고, GPU/서버 수요에 대해 S1 표준 발주안, S2 예외 Agent 협상, S3 근거 기반 ATP 질의, S4 견적 즉시 조달 확인과 S8 발신 전 감사자 차단을 구현하되, 가격은 결정적 알고리즘이 계산하고 모든 확정·외부 송부는 권한 있는 사람이 수행한다.

S5·S6·S7·S9·S10·S11은 최소 구현 완료 기준을 통과한 뒤 순서대로 추가한다.

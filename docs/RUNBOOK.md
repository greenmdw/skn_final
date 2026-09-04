# 분산 협상 + Odoo 연동 — 처음부터 끝까지 테스트 Runbook

**전제:** AWS 계정과 리전만 있고 나머지는 아무것도 없는 상태.
**목표:** EC2 4대(Buyer / Seller1 / Seller2 / Broker)를 띄우고 ① 분산 협상 통신 테스트 ② Odoo 연동 테스트를 통과시킨다.

```
VPC — 퍼블릭 서브넷 1개
 └ 보안그룹 SG-nego (4대 공유)
     ├ EC2 #1 buyer    t3.small  20GB  : app(buyer_service :8000)  + Odoo + Postgres
     ├ EC2 #2 seller1  t3.small  20GB  : app(seller_service:8000)  + Odoo + Postgres
     ├ EC2 #3 seller2  t3.small  20GB  : app(seller_service:8000)  + Odoo + Postgres
     └ EC2 #4 broker   t3.micro  10GB  : app(broker_service:9000)              (Odoo 없음)
```

전부 Ubuntu 24.04 LTS. 협상은 규칙 기반(`NEGOTIATOR_MODE=rule`)이라 OpenAI 키가 필요 없다.

---

## 0. 준비물

- AWS 콘솔 접근 권한, 작업 리전 결정
- EC2 키페어 1개(`.pem`) — 없으면 EC2 → 키 페어 → 생성 후 다운로드
- 본인 공인 IP (검색창에 "my ip") — SSH 허용에 사용
- 이 저장소 URL

---

## 1. 보안그룹 생성 (한 번만)

EC2 → 보안 그룹 → **보안 그룹 생성**. 이름 `SG-nego`, VPC = 인스턴스를 띄울 VPC.

인바운드 규칙:

| 유형 | 포트 | 소스 | 용도 |
|---|---|---|---|
| SSH | 22 | `<내 IP>/32` | 접속 |
| 사용자 지정 TCP | 8000 | 이 보안그룹(sg-…) | Broker→Seller, Buyer 로컬 호출 |
| 사용자 지정 TCP | 8000 | `<내 IP>/32` | 목업 화면 |
| 사용자 지정 TCP | 9000 | 이 보안그룹 | Buyer→Broker |
| 사용자 지정 TCP | 9000 | `<내 IP>/32` | (선택) broker 직접 curl |
| 사용자 지정 TCP | 8069 | 이 보안그룹 | (선택) 인스턴스 간 Odoo |
| 사용자 지정 TCP | 8069 | `<내 IP>/32` | (선택) Odoo 웹 접속 |

> **"이 보안그룹" 소스** = 소스 칸에 이 보안그룹 자신의 ID를 지정. 규칙을 한 번 저장하면 목록에서 `sg-…`를 고를 수 있다. 4대가 사설 IP로 서로 통신하려면 이 규칙이 필수.

아웃바운드는 기본값(전체 허용) 그대로 둔다.

---

## 2. EC2 4대 생성

인스턴스 시작 공통:
- AMI: **Ubuntu Server 24.04 LTS (x86_64)**
- 키 페어: 0번에서 준비한 것
- 네트워크: 퍼블릭 서브넷, **퍼블릭 IP 자동 할당 켜기**
- 방화벽: 기존 보안 그룹 선택 → **SG-nego**
- 스토리지: gp3

| # | Name 태그 | 유형 | 스토리지 |
|---|---|---|---|
| 1 | `buyer` | t3.small | 20 GiB |
| 2 | `seller1` | t3.small | 20 GiB |
| 3 | `seller2` | t3.small | 20 GiB |
| 4 | `broker` | t3.micro | 10 GiB |

생성 후 각 인스턴스의 **퍼블릭 / 프라이빗 IPv4**를 적어둔다:

| | 퍼블릭 IP | 프라이빗 IP |
|---|---|---|
| buyer |54.180.152.110 |172.31.38.44|
| seller1 |43.201.109.72 |172.31.46.240 |
| seller2 |15.164.104.185 |172.31.34.28 |
| broker |15.164.212.106  |172.31.47.56 |

(프라이빗 IP는 인스턴스 안에서 `hostname -I | awk '{print $1}'` 로도 확인)

---

## 3. 공통 초기 설정 (4대 전부 동일)

각 인스턴스에 SSH:

```bash
ssh -i /경로/키.pem ubuntu@<퍼블릭IP>
```

> Windows에서 `bad permissions` 에러 시 (한 번만):
> `icacls 키.pem /inheritance:r /grant:r "%USERNAME%:R"`

접속 후:

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker $USER && newgrp docker
```

스왑 2GB (Odoo OOM 방지 — broker는 생략 가능):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

코드 가져오기:

```bash
git clone -b develop https://github.com/greenmdw/skn_final.git demo && cd demo && cp env.example .env
```

여기까지 4대 동일. 다음 단계부터 역할별로 갈린다.

---

## 4. 역할별 `.env` 설정 + 기동

`nano .env` 로 편집. 각 역할에서 **바꿔야 하는 줄만** 표기한다.

### 4-1. Buyer (EC2 #1)

```
APP_MODULE=app.buyer_service:app
NEGOTIATOR_MODE=rule
BROKER_URL=http://<broker_프라이빗IP>:9000
ODOO_BASE_URL=http://odoo:8069
ODOO_DATABASE=
ODOO_API_KEY=
```

```bash
docker compose up -d --build
```

### 4-2. Seller1 (EC2 #2)

```
APP_MODULE=app.seller_service:app
NEGOTIATOR_MODE=rule
SELLER_ID=한빛테크
SELLER_ITEM=NVIDIA L40S
SELLER_QTY=50
SELLER_OFFER_PRICE=11000000
SELLER_FLOOR_PRICE=9800000
SELLER_DESCRIPTION=Ada Lovelace 아키텍처; GDDR6 48GB ECC; PCIe 4.0 x16; 최대 소비전력 350W
SELLER_LEAD_TIME_DAYS=30
SELLER_MOQ=1
ODOO_BASE_URL=http://odoo:8069
ODOO_DATABASE=
ODOO_API_KEY=
```

```bash
docker compose up -d --build
```

### 4-3. Seller2 (EC2 #3)

Seller1과 동일하되 **가격만 다르게** (안 그러면 협상 비교가 무의미):

```
SELLER_ID=오퍼렛
SELLER_OFFER_PRICE=10600000
SELLER_FLOOR_PRICE=10100000
```

```bash
docker compose up -d --build
```

### 4-4. Broker (EC2 #4)

```
NEGOTIATOR_MODE=rule
BROKER_MAX_ROUNDS=3
SELLER_ENDPOINTS=http://<seller1_프라이빗IP>:8000,http://<seller2_프라이빗IP>:8000
```

**전용 compose 파일 사용** (Odoo·Postgres는 안 뜬다):

```bash
docker compose -f docker-compose.broker.yml up -d --build
```

> ⚠️ `ODOO_API_KEY` 에 한글/비ASCII 를 넣으면 Odoo health 가 500 난다. 비워두거나 실제 키만.

---

## 5. 개별 헬스체크

| 인스턴스 | 명령 | 기대 결과 |
|---|---|---|
| buyer | `curl -s localhost:8000/api/integrations/odoo/health` | `"status":"NOT_CONFIGURED"` (Odoo 미설정이라 정상) |
| buyer | 브라우저 `http://<buyer_퍼블릭IP>:8000/` | 목업 3화면 로드 |
| seller1/2 | `curl -s localhost:8000/health` | `{"ok":true,"service":"seller","seller_id":"한빛테크",…}` |
| broker | `curl -s localhost:9000/health` | `{"ok":true,"service":"broker","max_rounds":3,…}` |

컨테이너 상태: `docker compose ps` (broker는 `docker compose -f docker-compose.broker.yml ps`)

---

## 6. 통신 테스트 (분산 협상)

### 6-0. .env 값 수정 시 필요 사항

다음 명령을 실행한다.

```bash
docker compose up -d --force-recreate app
```

**다음 명령으로는 컨테이너 내부에 변경이 반영되지 않는다.**

`docker restart [컨테이너 이름 또는 ID]`

### 6-1. Broker → Seller 네트워크 — **broker EC2 안에서**

```bash
curl -s http://<seller1_프라이빗IP>:8000/api/offer -X POST -H "Content-Type: application/json" \
  -d '{"txid":"TEST-01","item":"NVIDIA L40S","qty":10,"spec":"GDDR6 48GB","max_lead_time_days":40,"round_no":1,"last_reject_price":null}'
```

기대: `{"price":<숫자>,"message":"…","available":true,…}` — 응답에 **`floor_price` 가 없어야** 정상.

### 6-2. 전체 흐름 — **buyer EC2 안에서** (또는 목업 화면에서)

```bash
curl -s localhost:8000/api/request -X POST -H "Content-Type: application/json" \
  -d '{"item":"NVIDIA L40S","qty":10,"cap_price":12000000,"spec":"GDDR6 48GB ECC","priority":"price_min"}'
```

기대:

```json
{"txid":"TX-…","status":"SETTLED","seller_id":"오퍼렛","endpoint":"http://<프라이빗IP>:8000","price":10581481,"spec_score":0.95,"priority":"price_min",…}
```

- `endpoint` 가 프라이빗 IP → 인스턴스 경계를 넘은 실제 네트워크 호출
- `price_min` → 더 싼 셀러(오퍼렛) 낙찰. `"priority":"spec_max"` 로 바꿔 재실행하면 사양 유사도 높은 쪽

실패 시나리오:

| 입력 변경 | 기대 |
|---|---|
| `"spec":"HBM3 94GB NVLink"` | `"fail_type":"NO_MATCH"` |
| `"cap_price":9000000` | `"fail_type":"NO_DEAL"` |

### 6-3. 브로커 로그 — 아무 인스턴스에서 (txid 는 6-2 응답값)

```bash
curl -s http://<broker_프라이빗IP>:9000/api/negotiate/<txid>/log
```

기대: `REQUEST` 가 각 seller endpoint 로 나가고 `OFFER` 회신 → `ACCEPT`/`REJECT` → `SETTLED` 순서.

### 6-4. 정보 경계 검증

Broker EC2 안에서 — **아무것도 안 나와야 통과**:

```bash
grep -i floor ~/demo/data/broker_logs/*.jsonl ; echo "exit=$?"
```

```bash
docker compose -f docker-compose.broker.yml logs broker | grep -i floor
```

Seller EC2 안에서는 **`floor_price` 가 나오는 게 정상** (셀러 자기 서버 로그):

```bash
grep -i floor ~/demo/data/seller_logs/*.jsonl
```

---

## 7. Odoo 연동 테스트 (선택 — 6번 협상과 독립)

Buyer 또는 Seller 인스턴스 하나에서 진행한다 (Broker 는 Odoo 없음).

### 7-1. Odoo 웹 접속

보안그룹에 `8069 ← 내 IP` 를 넣었으면: 브라우저 `http://<인스턴스_퍼블릭IP>:8069`

안 넣었으면 SSH 터널 (노트북에서):

```bash
ssh -i 키.pem -L 8069:localhost:8069 ubuntu@<인스턴스_퍼블릭IP>
```

→ 터널을 유지한 채 `http://localhost:8069`

### 7-2. 데이터베이스 생성

첫 접속 시 Database Manager 화면:
- Master Password: 비우고 시도 → 막히면 `admin`
- Database Name: `odoo`
- 이메일 / 비밀번호 / 국가 입력 → **Create database** (1~2분)

### 7-3. 앱 설치 — Purchase(buyer) / Sales(seller1·seller2)

DB를 새로 만들면 Odoo 기본 모델만 있고 `product.product`·`purchase.order`·`sale.order`는 없다 (해당 앱을 설치해야 딸려 들어옴). 왼쪽 위 **Apps** → 검색창에 앱 이름 입력 → **Install**:

| 인스턴스 | 설치할 앱 |
|---|---|
| buyer | `Purchase` |
| seller1, seller2 | `Sales` |

설치 후 페이지가 리로드되고 상단 메뉴에 "구매"/"판매"가 나타난다. **8번(A방식) 진행 전 필수** — 안 하면 `/api/dev/seed-odoo`에서 `the model 'product.product' does not exist` 에러가 난다.

### 7-4. API 키 발급

Odoo 로그인(방금 만든 계정) → 우측 상단 아바타 → **My Profile** → **Account Security** 탭 → **New API Key** → 이름 입력, 로그인 비밀번호 확인 → **표시되는 키를 즉시 복사** (재확인 불가).

### 7-5. `.env` 반영 후 재기동 (해당 인스턴스 SSH)

```bash
cd ~/demo
sed -i 's/^ODOO_DATABASE=.*/ODOO_DATABASE=odoo/' .env
sed -i 's|^ODOO_API_KEY=.*|ODOO_API_KEY=붙여넣은키|' .env
docker compose up -d
```

```bash
curl -s localhost:8000/api/integrations/odoo/health ; echo
```

### 7-6. 결과 해석

| status | 의미 | 조치 |
|---|---|---|
| `OK` (`"ok":true`) | 성공 — 버전·인증·유저 컨텍스트 확인됨 | — |
| `NOT_CONFIGURED` | `ODOO_DATABASE`/`ODOO_API_KEY` 비어있음 | 7-5 다시 |
| `VERSION_MISMATCH` | Odoo 이미지가 19가 아님 | `.env` 에 `ODOO_EXPECTED_MAJOR_VERSION=<실제버전>` 추가 후 재기동 |
| `AUTH_FAILED` | API 키 오타/만료 | 7-4 재발급 |
| `INVALID_RESPONSE` | Odoo 아직 부팅 중 | 1분 뒤 재시도 |
| `UNREACHABLE` | `ODOO_BASE_URL` 오타 / odoo 컨테이너 다운 | `docker compose ps`, `ODOO_BASE_URL=http://odoo:8069` 확인 |

---

## 8. Odoo 협상 미러 테스트 (A 방식)

7번(연결 확인: `health` = `OK`)까지 통과했다는 전제. buyer·seller1·seller2 각각에 `.env`의 `ODOO_DATABASE`·`ODOO_API_KEY`가 채워져 있어야 한다. **Broker는 Odoo가 없으므로 이 섹션에서 제외.**

구조: buyer가 Odoo **구매(Purchase)**에 발주서 초안을 쓰면 buyer_service가 감지해서 협상을 돌리고, 결과를 그 발주서의 로그(chatter)에 되돌려 쓴다. 각 seller_service는 offer 요청을 받을 때마다 자기 Odoo **판매(Sales)**에 견적요청 미러를 만들고 라운드·낙찰 결과를 chatter에 남긴다.

### 8-1. `ODOO_SYNC` 켜기 — buyer, seller1, seller2 (각각)

```
ODOO_SYNC=on
ODOO_POLL_SECONDS=15
```

`ODOO_POLL_SECONDS=0`이면 자동 폴링 없이 수동 트리거(8-4)만 동작한다.

```bash
docker compose up -d --force-recreate app
```

### 8-2. 카탈로그 시드 — buyer, seller1, seller2 각각 1회

```bash
curl -s localhost:8000/api/dev/seed-odoo -X POST; echo
```

기대: `{"ok":true,"role":"…","bot_partner_id":N,"products":{"NVIDIA L40S":M,…}}`

이게 에러 나면 Odoo JSON-2 호출 바디 형태가 그 Odoo 버전과 안 맞는 것 — `app/integrations/odoo/rpc.py` 한 파일만 에러 메시지 보고 조정하면 된다 (부록 참고).

### 8-3. buyer Odoo에서 RFQ(발주서 초안) 작성

buyer 퍼블릭 IP로 Odoo 접속(7-1과 동일) → **구매 → 발주서 새로 만들기**:

| 필드 | 값 |
|---|---|
| 공급업체 | `협상 브로커` (8-2 시드로 자동 생성됨) |
| 제품(라인 추가) | `NVIDIA L40S` — **8-2 시드 제품 목록에 있는 이름과 정확히 일치해야 함** |
| 수량 | `10` |
| 단가 | `12000000` (바이어가 낼 수 있는 상한가로 사용됨) |
| **그 제품 라인의 설명(Description)** | 제품명 아래 편집 가능한 설명 칸에 이어서: `spec: GDDR6 48GB ECC \| priority: price_min` |

> ⚠️ "기타 정보(Other Info) 탭 → 메모(Notes)"가 아니라 **제품 라인 자체의 설명 칸**입니다. `purchase.order`의 상단 메모 필드는 Odoo 버전마다 이름이 달라 조회에 안 씁니다 — 라인 설명(`purchase.order.line.name`)은 모든 버전에 항상 있는 표준 필드라 이걸 씁니다.

**확정(Confirm)하지 말고 초안 상태로 저장**한다 — 초안만 폴링 대상이다.

### 8-4. 협상 트리거

자동 폴러가 돌고 있으면 최대 `ODOO_POLL_SECONDS` 후 처리된다. 즉시 확인하려면 buyer EC2에서:

```bash
curl -s localhost:8000/api/odoo/pull -X POST; echo
```

기대: `{"po_id":N,"rfq":{…},"result":{"status":"SETTLED","seller_id":"오퍼렛","price":…}}`

### 8-5. 양쪽 GUI에서 확인

- **buyer Odoo** → 방금 그 발주서 열기 → 하단 로그(chatter): "분산 협상 시작 (txid …)" → 라운드별 제안 → `✅ 낙찰: 오퍼렛 · 확정 단가 …`
- **seller1 / seller2 Odoo** → 판매 → 견적 → 고객 참조가 `NEGO:<txid>`인 견적 열기 → chatter에 라운드별 제안 메시지 + 낙찰(`✅`)/탈락(`❌`) 노트

### 8-6. 재실행

같은 발주서는 한 번 처리되면 "공급업체 참조"(`partner_ref`)가 채워져 다시 안 잡힌다 — 반복 테스트하려면 8-3처럼 새 발주서를 또 만든다.

---

## 9. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `curl` 무응답 / 타임아웃 | 대상 포트의 SG 인바운드에 "이 보안그룹" 규칙 없음 |
| buyer `/api/request` 가 멈춤 | `BROKER_URL` 오타 또는 broker 미기동. broker 에서 `curl localhost:9000/health` |
| odoo health 500 | `ODOO_API_KEY` 에 한글 예시문구 남음 → 비우고 `docker compose up -d` |
| Odoo 컨테이너가 계속 재시작 | 메모리 부족(t3.micro). t3.small 로 변경 + 스왑(3장) |
| `table … has no column …` | 스키마 변경 후 옛 DB 잔존 → `docker compose down -v && docker compose up -d` |
| `/api/dev/seed-odoo` → `the model 'product.product' does not exist` | Purchase(buyer)/Sales(seller) 앱 미설치 → 7-3 진행 |
| `/api/dev/seed-odoo` 기타 에러 | `app/integrations/odoo/rpc.py` 의 `search_read`/`create` 바디 형태가 이 Odoo 버전과 안 맞음. 에러 메시지의 필드명 보고 그 파일만 조정 |
| `/api/odoo/pull` → 502 `Invalid field 'notes' on 'purchase.order'` | 이미 고쳐짐(라인 설명 필드로 전환) — `git pull && docker compose up -d --build` 로 최신 코드 반영 |
| `/api/odoo/pull` → `"새 RFQ 없음"` | PO가 초안 상태가 아니거나 이미 처리돼 `partner_ref`가 채워짐 → 8-3처럼 새 발주서로 재시도 |
| `/api/odoo/pull` → 422 품목명 불일치 | 발주서 라인의 제품명이 GPU 카탈로그 값과 정확히 안 맞음 — 8-2 시드 제품을 그대로 선택했는지 확인 |
| chatter에 기록이 안 남음 | 해당 인스턴스 `.env`에 `ODOO_SYNC=on` 확인 후 `docker compose logs app \| grep -i "odoo sync"` 로 원인 확인 (best-effort라 실패해도 협상 자체는 계속됨) |
| 로그 확인 | `docker compose logs app --tail=80` / `docker compose logs odoo --tail=80` |
| 코드 갱신 | `git pull && docker compose up -d --build` |

---

## 10. 정리 (Teardown)

각 인스턴스:

```bash
cd ~/demo && docker compose down -v
```

(broker 는 `docker compose -f docker-compose.broker.yml down -v`)

AWS: 인스턴스 종료 → 필요 시 AMI/스냅샷 삭제 → `SG-nego` 삭제.

---

## 부록 — 서비스 계약 요약

| 서비스 | 포트 | 주요 엔드포인트 |
|---|---|---|
| Buyer | 8000 | `POST /api/request` (분산) · `POST /api/buyers/request` (로컬 단일) · `POST /api/odoo/pull` (A방식 트리거) · `POST /api/dev/seed-odoo` · 목업 `GET /` |
| Seller | 8000 | `POST /api/offer` · `POST /api/settle` (브로커→셀러, 낙찰통지) · `GET /health` · `POST /api/seller/config` · `POST /api/dev/seed-odoo` |
| Broker | 9000 | `POST /api/negotiate/start` · `GET /api/negotiate/{txid}/log` · `GET /health` |
| Buyer/Seller | 8000 | `GET /api/integrations/odoo/health` (Broker 제외) |

`POST /api/offer` 요청 바디: `{txid, item, qty, spec, max_lead_time_days, round_no, last_reject_price, max_rounds?, seller_trust_min?}`
응답 바디: `{price, message, available, spec_score, trust_score, seller_id, payment_terms, delivery_terms}` — **`floor_price` 절대 미포함**

### A 방식(Odoo 미러) 관련 파일

| 파일 | 내용 |
|---|---|
| `app/integrations/odoo/rpc.py` | JSON-2 ORM 호출 헬퍼 (`search_read`/`create`/`write`/`post_note`) — Odoo 버전 차이는 이 파일에서만 조정 |
| `app/integrations/odoo/sync.py` | `SalesMirror`(seller) · `PurchaseInbox`(buyer) · `seed()` · `sync_enabled()` |
| `.env` | `ODOO_SYNC=on\|off`, `ODOO_POLL_SECONDS`(0=수동만) |

레코드 식별은 커스텀 필드 없이 표준 필드를 재사용한다: `sale.order.client_order_ref` / `purchase.order.partner_ref` = `NEGO:<txid>`. `ODOO_SYNC=off`(기본값)면 전부 no-op — 협상 자체는 Odoo 상태와 무관하게 항상 동작한다.

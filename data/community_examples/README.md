# 예시 사용기 글 — 적재 런북

커뮤니티 시작용 예시 글(200편)을 로컬 DB에 넣고, 체감 문장 분석·벡터 저장까지 끝내서 팀이 같은 결과를 쓰게 하는 절차다.
글 형식은 `docs/개발요청_커뮤니티_본문_이미지_배치.md` 5장(예시 글 작성 형식)을 따른다.

## 1. 한눈에 보기

```
글 .md (A·B·C·D·E·F)                                      ← 이 폴더, 담당자들이 작성
   │ ① 수집·점검  db/seed_community_examples.py (dry-run)
   ▼
community.post / post_product                             ← ② 적재 (--apply)
   │ ③ 분석  python -m src.workers.peripheral_post_analysis   (언어 모델, 한 사람이 한 번)
   ▼
engine.peripheral_post_evidence                           ← 체감 문장(제품·속성·방향·원문)
   │ ④ 임베딩 (분석 뒤 이어서 채움, text-embedding-3-small 1536차원)
   ▼
engine.peripheral_post_evidence_embedding                 ← 문장당 벡터(pgvector, 같은 PostgreSQL)
   │ ⑤ 스냅샷  db/community_examples_snapshot.py export
   ▼
data/community_examples/dump/*.copy + manifest.json       ← 팀에 전달(git 추적 안 함)
   │ ⑥ 각자 복원  db/community_examples_snapshot.py restore
   ▼
팀원 로컬 DB (글·분석 결과·벡터가 같음)
```

| 누가 | 하는 단계 | 필요한 것 |
|---|---|---|
| 글 작성자(담당 1~5) | 글 `.md`를 이 폴더에 낸다 | 글 형식 |
| 적재·분석 담당(한 명) | ①~⑤ | 로컬 DB, `OPENAI_API_KEY`(팀 공유 키), 임베딩 모델 |
| 팀원 | ⑥ 복원만 | 로컬 DB(마이그레이션 완료), 받은 `dump/` 폴더 |

팀원은 분석을 다시 돌리지 않는다(비용·결과 차이). 글 id는 DB마다 달라서 근거만 따로 옮기면 글과 끊기므로, 글과 근거를 한 묶음으로 옮긴다.

## 2. 폴더 구조

```
data/community_examples/
├── README.md              ← 이 문서
├── A/ … F/               ← 묶음별 글 파일(A1-1.md …). 글 id는 파일 이름과 같다. 이미지는 글 파일과 같은 폴더에 둔다
├── revisions/             ← 수정본 글(F12-edited.md 등). 원글 적재 뒤에 --update 로 올린다
└── dump/                  ← 스냅샷(manifest.json, *.copy). .gitignore 대상, 팀 내 파일로 공유
```

규칙

- 한 폴더에는 **글 `.md`만** 둔다. 스크립트가 폴더의 `*.md`를 모두 글로 읽으므로 안내 문서가 섞이면 "머리말이 없다"는 오류가 난다.
- 글 id는 전체에서 유일해야 한다(`A1-1`, `E7`, `F12`). 같은 id가 둘이면 거절된다.
- 담당자가 JSON(`예시_사용기_담당5.json` 같은)으로 낸 글은 변환 도구로 `.md`로 푼다(글 1편 = 파일 1개).

  ```bash
  PYTHONPATH=. uv run python db/community_examples_from_json.py <JSON 경로> data/community_examples
  ```

  묶음 폴더는 글 번호 앞 알파벳으로 정해지고(`A11-1`→`A/`, `E3`→`E/`), 수정본(`revision: edited`)은 `revisions/`로 간다.
  이미 있는 파일은 덮어쓰지 않는다. 변환 뒤에는 ①(dry-run)로 점검한다.
- **제품이 없는 사용기는 올릴 수 없다**(실제 글쓰기도 사용기는 제품 1개 이상 연결해야 한다). 카탈로그에 없는 제품은
  `products`에 `custom: <제품명>`과 `kind: 마우스`처럼 적는다(F11이 그렇다).

## 3. 준비 (한 번)

```bash
docker compose up -d db
# 개발 DB 마이그레이션이 0015 까지 적용됐는지 확인 (db/setup_all.py 가 적용한다)
```

- 임베딩과 분석은 `.env`에 아래 값이 있어야 돈다(`.env.example` 참고).

| 변수 | 값 |
|---|---|
| `MOCK_MODE` | `0` |
| `LLM_PROVIDER` / `LLM_MODEL` | `openai` / 팀이 정한 경량 모델 |
| `OPENAI_API_KEY` | 팀 공유 키 |
| `PERIPHERAL_POST_AGENT` | `1` |
| `PERIPHERAL_POST_DAILY_LIMIT` | 기본 200 — 전체 적재가 이 한도에 딱 맞는다. 재실행하면 넘으므로 필요하면 올린다 |

- **가짜 벡터는 이름에 `test`가 없는 DB에 저장되지 않는다.** `MOCK_MODE=1`로 4단계를 돌리면 막힌다(개발 DB 보호).

## 4. 적재·분석 담당 절차 (①~⑤)

### ① 수집·점검

```bash
# 폴더 전체(하위 폴더 포함)를 한 번에 점검한다. 읽기 전용, 아무것도 쓰지 않는다.
# revisions/ · dump/ · README.md · _로 시작하는 이름은 자동으로 건너뛴다.
PYTHONPATH=. uv run python db/seed_community_examples.py data/community_examples
```

기대 출력: `점검(dry-run): 새 글 40 · 갱신 0 · 건너뜀 0 · 오류 0`. 오류가 있으면 파일 이름과 원인이 나온다
(`머리말(---)이 없다`, `제품 … 카탈로그에서 0개 일치`, `written_at 이 미래 날짜다` 등).

체크: 이 점검으로 제품 표기(brand/model)와 머리말 형식까지 확인된다. 본문 내용 점검은 기획 문서 6장 체크리스트.

### ② 적재

```bash
PYTHONPATH=. uv run python db/seed_community_examples.py data/community_examples --apply
# 같은 글은 다시 올려도 두 번 들어가지 않는다. 묶음 하나만 올리려면 그 폴더(예: .../A)를 지정한다.
```

- 오류가 하나라도 있으면 그 실행 전체가 취소된다(아무것도 저장되지 않는다).
- 작성자 20명(P01~P20)은 `example-pXX@truefit.invalid` 계정으로 만들어진다(로그인 불가).
- 수정본(F12-edited 등)은 원글 적재 **뒤에** 별도로 올린다: `… data/community_examples/revisions --apply --update`

### ③ 분석 (모델 호출 — 비용 발생)

먼저 규모만 센다(모델 호출·쓰기 없음).

```bash
PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --dry-run
```

출력 예: `대기에 올라갈 글: N건 / 분석 … / 건너뜀 … / 닫음 … / 근거 제거 …` 와 `임베딩이 필요한 근거 문장: M건`.

**시범 5편 먼저** — 하루 한도를 5로 줘서 5편만 돌리고, 결과를 정답표(기획 문서 7장)와 비교한다.

```bash
PERIPHERAL_POST_DAILY_LIMIT=5 PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --once
```

괜찮으면 전체(한도가 남아 있어야 한다. 오늘 이미 5편을 썼으면 한도를 +5 하거나 내일 이어서 한다).

```bash
PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --once
```

- 글마다 바로 커밋하므로 중간에 멈춰도 끝낸 글의 결과는 남고, 다시 돌리면 남은 글만 한다.
- 분석이 끝난 글은 본문·연결 제품이 같으면 다시 분석하지 않는다(`analyzed_hash`).
- `--no-embed`를 주면 임베딩을 뒤로 미룬다(④를 따로 돌릴 때).

### ④ 임베딩

③이 분석 뒤에 이어서 채운다. 따로 채우려면:

```bash
PYTHONPATH=. uv run python -c "
from src.db import get_conn
from src.rag.embedding import OpenAIEmbedder
from src.services import peripheral_evidence_embedding as e
with get_conn() as c: print(e.backfill(c, OpenAIEmbedder()))"
```

`remaining`이 0이면 끝이다. `failed`가 있으면 다시 돌린다(실패한 문장만 다시 시도된다).

### ⑤ 점검 후 스냅샷 내보내기

**먼저 결과를 확인한다.**

```sql
-- 제품별 근거 수와 방향 (기획 문서 7장 정답표와 비교)
SELECT p.brand, p.model, e.attribute, e.direction, count(*)
FROM engine.peripheral_post_evidence e JOIN catalog.product p ON p.id = e.product_id
WHERE e.is_example GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;

-- 분석 상태
SELECT status, count(*) FROM engine.peripheral_post_intake GROUP BY 1;     -- done / failed / pending

-- 임베딩 누락
SELECT count(*) FROM engine.peripheral_post_evidence e
LEFT JOIN engine.peripheral_post_evidence_embedding m ON m.evidence_id = e.id WHERE m.evidence_id IS NULL;   -- 0 이어야 한다
```

확인할 것: F 묶음 글은 근거가 없어야 한다 · 같은 글은 한 번만 세어진다(E21~E24) · F12는 수정본 적재 뒤 원글 근거가 사라진다 ·
제품별 최근 3개월 글 수가 기획표(`최근에 몰림` 8종, `예전에 몰림` 8종)와 같다.

문제가 없으면 내보낸다.

```bash
PYTHONPATH=. uv run python db/community_examples_snapshot.py export data/community_examples/dump
```

출력: 테이블별 행 수. `dump/` 폴더를 팀 사설 채널로 전달한다(저장소에는 올리지 않는다).

## 5. 팀원 절차 (⑥ 복원)

1. 저장소를 받고 DB 마이그레이션을 마친다(`db/setup_all.py`가 자동 적용 — 카탈로그 제품이 들어 있어야 한다).
2. 전달받은 `dump/` 폴더를 `data/community_examples/dump/`에 둔다.
3. 복원한다.

```bash
PYTHONPATH=. uv run python db/community_examples_snapshot.py restore data/community_examples/dump
```

| 출력 | 뜻 |
|---|---|
| `복원함` + 행 수 | 정상. 글·연결 제품·분석 대기·근거·벡터가 들어갔다 |
| `이미 있는 예시 글 N편과 겹친다` | 이 DB에 같은 글이 이미 있다. 덮어쓰려면 `--replace` |
| `테이블 열 구성이 달라 복원할 수 없다` | 마이그레이션이 다르다. 최신 develop을 받아 `db/setup_all.py`를 다시 돌린다 |
| `카탈로그에서 제품을 하나로 찾지 못했다` | 이 DB의 카탈로그에 그 제품이 없다. 카탈로그 시드를 확인한다 |

- 복원은 한 트랜잭션이라 실패하면 아무것도 바뀌지 않는다.
- 제품 id는 DB마다 달라서 스냅샷에는 `brand`·`model`이 같이 들어 있고, 복원 때 이 DB의 카탈로그에서 다시 찾는다.
- 작성자 계정은 이메일로 맞춘다(있으면 그 계정을 쓰고, 없으면 만든다).

## 6. 글을 고치거나 더할 때

| 상황 | 방법 |
|---|---|
| 글 하나를 고침 | 적재 담당 DB에서 `--apply --update`(본문·제목·태그·제품 갱신). 분석은 다음 실행에서 해당 글만 다시 한다. 이후 스냅샷을 다시 내보낸다 |
| 글을 더함 | ②에서 새 글만 올라간다(같은 id는 건너뜀). ③ 분석, 스냅샷 재생성 |
| 팀원 DB를 처음 상태로 | `restore … --replace` (같은 글을 지우고 다시 넣는다) |
| 이미지를 붙임 | 8장 절차. 스냅샷에는 이미지 파일이 함께 들어가므로 다시 내보내면 된다 |

## 7. 알아 둘 제약

- **게시일**: 머리말 `written_at`이 `community.post.published_at`이 된다. `--update`는 이미 올라간 글의 날짜를 바꾸지 않는다(날짜를 고치려면 `restore --replace`나 글 삭제 후 재적재).
- **이미지 위치**: 지금은 글 아래에 모아서 표시된다. 본문 중간에 넣는 방식은 `개발요청_커뮤니티_본문_이미지_배치.md`의 마커가 반영된 뒤에 켠다.
- **카탈로그**: 제품은 `catalog.product`의 `brand`+`model`로 연결한다. 글의 표기가 글자까지 같아야 한다.
- **분석 한도**: 하루 분석 한도(`PERIPHERAL_POST_DAILY_LIMIT`)를 넘으면 그날은 멈추고 남은 글은 대기로 남는다.
- **개발·운영 DB에는 가짜 벡터를 넣지 않는다**(`MOCK_MODE=1` 금지).

## 8. 이미지 넣기

글마다 0~2장(생성 이미지). 파일은 글 파일과 같은 폴더에 두고 머리말 `images`에 이름을 적는다.

```yaml
images: [a1-1_1.png, a1-1_2.png]     # 첫 장이 대표 이미지, 글당 최대 5장
```

| 규칙 | 값 |
|---|---|
| 파일 이름 | `<글번호 소문자>_<순번>.<확장자>` (예 `a1-1_1.png`) |
| 형식·크기 | JPEG, PNG, WebP, 장당 5MB 이하 |
| 가공 | 적재 때 긴 변 1600px로 줄이고 EXIF를 지운다 |
| 출처 | 직접 찍거나 생성한 이미지만. 제조사·쇼핑몰 이미지 금지 |
| 설명 | 특정 모델의 외형을 정확히 따라 그리기보다 책상·작업 환경 같은 분위기 컷을 권한다 |

순서

1. 이미지를 만들고 이름 규칙대로 글 옆에 둔다. 머리말 `images`를 채운다.
2. **점검**(dry-run): 파일이 없거나 형식·크기가 맞지 않으면 글별로 오류가 나온다.
3. 이미 올라간 글에 이미지를 붙이거나 바꾸려면 `--apply --update` (머리말에 `images`가 있을 때만 이미지를 교체한다).
4. 적재한 DB에서 스냅샷을 다시 내보낸다. 이미지 파일은 `dump/images/<저장 키>`로 함께 담긴다.
5. 팀원은 복원한다. 이미지 파일이 각자 저장소(`COMMUNITY_UPLOAD_DIR`)에 같은 키로 복사된다.

`restore --replace`로 글을 다시 넣을 때 새 스냅샷에 없는 이전 이미지 파일은 커밋 뒤에 정리된다.

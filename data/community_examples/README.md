# 예시 사용기 글 — 적재 런북

커뮤니티 시작용 예시 글(200편, 이미지 111장)을 로컬 DB에 넣고, 체감 문장 분석·벡터 저장까지 끝내서 팀이 같은 결과를 쓰게 하는 절차다.
글 형식은 `docs/개발요청_커뮤니티_본문_이미지_배치.md` 5장(예시 글 작성 형식)을 따른다.

## 0. 현재 상태 (2026-10-14)

| 묶음 | 글 | 이미지 | DB 적재(담당 DB) | 분석 |
|---|---|---|---|---|
| A 마우스 | 48 | 48 | 완료 | 완료 |
| B 키보드 | 40 | 10 | 완료 | 완료 |
| C 모니터 | 36 | 9 | 완료 | **미분석** |
| D 스피커 | 36 | 10 | 완료 | **미분석** |
| E 여러 제품 | 24 | 28 | 완료 | **미분석** |
| F 근거 아님 | 16 | 6 | 완료 | **미분석** |

- 스냅샷(`dump/`)은 분석이 끝난 뒤에 내보낸다. C~F 분석 전의 스냅샷은 근거가 A·B만 들어 있다.
- 글 수·이미지 수는 `ls`와 `db/seed_community_examples.py` 점검(①)으로 직접 확인할 수 있다.

## 1. 한눈에 보기

```
글 .md + 이미지 (A·B·C·D·E·F)                              ← 이 폴더, 담당자들이 작성·생성
   │ ⓪ 이미지 연결  scripts/link_example_images.py          (PNG→JPEG, 머리말 images, 본문 마커)
   │ ① 수집·점검   db/seed_community_examples.py (dry-run)
   ▼
community.post / post_product / post_image                 ← ② 적재 (--apply, 마커 → 이미지 id)
   │ ③ 분석  python -m src.workers.peripheral_post_analysis   (언어 모델, 한 사람이 한 번)
   ▼
engine.peripheral_post_evidence                            ← 체감 문장(제품·속성·방향·원문)
   │ ④ 임베딩 (분석 뒤 이어서 채움, text-embedding-3-small 1536차원)
   ▼
engine.peripheral_post_evidence_embedding                  ← 문장당 벡터(pgvector, 같은 PostgreSQL)
   │ ⑤ 스냅샷  db/community_examples_snapshot.py export
   ▼
data/community_examples/dump/*.copy + manifest.json        ← 팀에 전달(git 추적 안 함)
   │ ⑥ 각자 복원  db/community_examples_snapshot.py restore
   ▼
팀원 로컬 DB (글·이미지·분석 결과·벡터가 같음)
```

| 누가 | 하는 단계 | 필요한 것 |
|---|---|---|
| 글 작성자(담당 1~5) | 글 `.md`와 이미지를 이 폴더에 낸다 | 글 형식, 8장 이미지 규칙 |
| 적재·분석 담당(한 명) | ①~⑤ | 로컬 DB, `OPENAI_API_KEY`(팀 공유 키), 임베딩 모델 |
| 팀원 | ⑥ 복원만 (또는 ①②만) | 로컬 DB(마이그레이션 완료), 받은 `dump/` 폴더 |

팀원은 분석을 다시 돌리지 않는다(비용·결과 차이). 글 id는 DB마다 달라서 근거만 따로 옮기면 글과 끊기므로, 글과 근거를 한 묶음으로 옮긴다.
글과 이미지만 필요하면(분석 결과 없이 커뮤니티 화면만 볼 때) ①②만 하면 된다.

## 2. 폴더 구조

```
data/community_examples/
├── README.md                   ← 이 문서
├── A/ … F/                    ← 묶음별 글 파일(A1-1.md …)과 그 글의 이미지(a1-1_1.jpg …). 글 id는 파일 이름과 같다
├── revisions/                  ← 수정본 글(F12-edited.md 등). 원글 적재 뒤에 --update 로 올린다
├── expectations.yaml           ← A 묶음 정답표(분석 결과 점검용)
├── expectations_B_draft.yaml   ← B 묶음 정답표 초안(사람 확인 전)
└── dump/                       ← 스냅샷(manifest.json, *.copy). .gitignore 대상, 팀 내 파일로 공유
```

규칙

- 글 폴더(`A/`~`F/`)에는 **글 `.md`와 이미지 파일만** 둔다. 폴더의 `*.md`를 모두 글로 읽으므로 안내 문서가 섞이면
  "머리말이 없다"는 오류가 난다(`README.md`는 건너뛴다).
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
git pull origin develop
docker compose up -d db
PYTHONPATH=. uv run python db/migrate.py up            # 마이그레이션을 0019 까지 적용 (또는 신규 DB 는 db/setup_all.py)
PYTHONPATH=. uv run python db/seed_peripherals.py      # 주변기기 카탈로그(data/peripherals/*.csv 필요, 키압 값 포함)
```

- `migrate up`이 0016에서 "column ... already exists"로 실패하면 누군가 GPU 컬럼(`hdmi_version`·`dp_version`·`usb_c_video_out`)을 직접
  추가한 DB다. DB 담당에게 알린다(값이 있으면 지우지 않고 빠진 부분만 더한 뒤 적용 기록을 남긴다 — 2026-10-14 개발 DB가 그랬다).
- 화면까지 보려면 `npm --prefix web install` 후 `npm --prefix web run build`(또는 개발 서버 `npm --prefix web run dev`).
  글 본문의 마크다운·이미지 위치는 `web/src/components/MarkdownBody.tsx`가 그린다. 의존성이 없으면 개발 서버가 오류로 뜬다.
- 분석을 직접 돌리는 사람은 `.env`에 아래 값이 있어야 한다(`.env.example` 참고).

| 변수 | 값 |
|---|---|
| `MOCK_MODE` | `0` |
| `LLM_PROVIDER` / `LLM_MODEL` | `openai` / 팀이 정한 경량 모델 |
| `OPENAI_API_KEY` | 팀 공유 키(채팅·문서에 붙이지 않는다) |
| `PERIPHERAL_POST_AGENT` | `1` |
| `PERIPHERAL_POST_DAILY_LIMIT` | 기본 200 — 하루에 분석을 시작하는 글 수. 전체 200편이 이 한도에 딱 맞는다. 재분석하면 넘으므로 필요하면 올린다 |
| `PERIPHERAL_POST_LLM_TIMEOUT_SECONDS` | 기본 150 — 분석 호출 한 번의 제한. 여러 제품 글은 기본 제한(45초)에 못 끝난다 |
| `PERIPHERAL_POST_FULL_SCAN_SECONDS` | 기본 3600 — 주기 실행 때 전체 글을 훑어 놓친 변경을 찾는 안전망 주기 |

- **가짜 벡터는 이름에 `test`가 없는 DB에 저장되지 않는다.** `MOCK_MODE=1`로 4단계를 돌리면 막힌다(개발 DB 보호).

## 4. 적재·분석 담당 절차 (⓪~⑤)

### ⓪ 이미지 연결 (이미지를 새로 받았을 때)

이미지 파일 이름에서 글 번호를 읽어(`A1-1.png`, `B1-2-image.png`, `c1-3_1.png`, `e22_1.png`, `A6-1-v2.png` …) 글에 붙인다.
같은 순번에 재생성본(`-v2` …)이 있으면 가장 높은 버전만 쓴다.

```bash
PYTHONPATH=. uv run python scripts/link_example_images.py data/community_examples --dry-run      # 무엇을 할지 확인(변경 없음)
PYTHONPATH=. uv run python scripts/link_example_images.py data/community_examples \
    --originals data/community_example_images_original                                           # JPEG 변환 + 연결
```

- JPEG(품질 85)로 바꿔 `<글번호 소문자>_<순번>.jpg`로 저장하고 원본은 `--originals` 폴더로 옮긴다(저장소 밖 보관, `.gitignore`).
- 글 머리말에 `images: [a1-1_1.jpg]`를 쓰고, 본문에 마커 `![설명](a1-1_1.jpg)`를 흐름에 맞는 자리에 넣는다.
  첫 장은 스펙 표 바로 뒤(첫 소제목 앞), 둘째 장부터는 이어지는 소제목 앞이다. 표·소제목·목록 안에는 넣지 않는다.
- 설명(alt)은 한 줄로 무엇이 보이는지만 쓴다("제품명 사용 장면"). 여러 제품 글은 "사용 장면 1/2/3".
- 여러 번 실행해도 같은 결과다(이전 마커를 걷어내고 다시 넣는다).

### ① 수집·점검

```bash
# 폴더 전체(하위 폴더 포함)를 한 번에 점검한다. 읽기 전용, 아무것도 쓰지 않는다.
# revisions/ · dump/ · README.md · _로 시작하는 이름은 자동으로 건너뛴다.
PYTHONPATH=. uv run python db/seed_community_examples.py data/community_examples
```

기대 출력(빈 DB): `점검(dry-run): 새 글 200 · 갱신 0 · 건너뜀 0 · 오류 0`. 이미 적재된 글은 `건너뜀`으로 센다.
오류가 있으면 파일 이름과 원인이 나온다(`머리말(---)이 없다`, `제품 … 카탈로그에서 0개 일치`,
`본문 마커 '…' 이(가) 머리말 images 에 없다`, `이미지 '…' 파일이 없다`, `written_at 이 미래 날짜다` 등).

### ② 적재

```bash
PYTHONPATH=. uv run python db/seed_community_examples.py data/community_examples --apply
# 같은 글은 다시 올려도 두 번 들어가지 않는다. 묶음 하나만 올리려면 그 폴더(예: .../A)를 지정한다.
```

- 본문 마커 `![설명](a1-1_1.jpg)`는 적재할 때 이미지 id(`![설명](image:<id>)`)로 바뀌어 저장된다. 마커 파일 이름은 모두 머리말 `images`에 있어야 한다.
- 오류가 하나라도 있으면 그 실행 전체가 취소된다(아무것도 저장되지 않고, 이미 저장한 이미지 파일도 지운다). 점검(dry-run)에서 오류가 0인지 먼저 본다.
- 작성자 20명(P01~P20)은 `example-pXX@truefit.invalid` 계정으로 만들어진다(로그인 불가).
- 수정본(F12-edited 등)은 원글 적재 **뒤에** 별도로 올린다: `… data/community_examples/revisions --apply --update`

### ③ 분석 (모델 호출 — 비용 발생)

먼저 규모만 센다(모델 호출·쓰기 없음).

```bash
PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --dry-run
```

출력 예: `대기에 올라갈 글: N건 / 분석 … / 건너뜀 … / 닫음 … / 근거 제거 …` 와 `임베딩이 필요한 근거 문장: M건`.

**시범 5편 먼저** — 하루 한도를 5로 줘서 5편만 돌리고, 결과를 정답표와 비교한다.

```bash
PERIPHERAL_POST_DAILY_LIMIT=5 PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --once
```

괜찮으면 전체(한도가 남아 있어야 한다. 오늘 이미 5편을 썼으면 한도를 +5 하거나 내일 이어서 한다).

```bash
PYTHONPATH=. uv run python -m src.workers.peripheral_post_analysis --once
# 일부 글만: --post A1-1,A1-2   (글 id 또는 예시 글 번호의 쉼표 목록. 다른 대기 글은 그대로 둔다)
```

- 글마다 바로 커밋하므로 중간에 멈춰도 끝낸 글의 결과는 남고, 다시 돌리면 남은 글만 한다.
- 분석이 끝난 글은 본문(서식·이미지 마커를 걷어낸 글자 본문)·연결 제품이 같으면 다시 분석하지 않는다(`analyzed_hash`).
  이미지 위치만 바꾼 수정은 다시 분석하지 않는다.
- **시간**: 글 하나가 모델 호출 1번, 평균 약 35초(긴 글 90초 이상)이다. 200편이면 순서대로 약 2시간이다.
- 예시 글 맨 앞의 면책 문구("가상 예시 사용기입니다…")는 분석 입력에서 뺀다. 목적·상황은 글쓴이가 직접 밝힌 문장이 있을 때만 채운다.
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

**정답표 자동 점검**(읽기 전용): 기획 문서 표를 속성 코드로 옮긴 정답표와 비교한다.

```bash
PYTHONPATH=. uv run python scripts/check_example_expectations.py            # A 묶음(expectations.yaml)
PYTHONPATH=. uv run python scripts/check_example_expectations.py --verbose  # 글마다 놓친 속성
PYTHONPATH=. uv run python scripts/check_example_expectations.py --expectations data/community_examples/expectations_B_draft.yaml   # B 초안
```

- 평가 속성 적중률(글마다 반드시 나와야 하는 속성·성향) — 보고만 한다. `--min-coverage 0.8`을 주면 미달 시 실패한다.
- 규칙 위반(있으면 종료 코드 1): 사용기가 아닌 글의 근거 · `-4` 글(조건을 밝히지 않는 글)에 잡힌 손 크기·목적 ·
  6개월 미만 글의 내구성 근거 · 본문에 없는 근거 문장.
- 짐작·가정 문장으로 보이는 근거는 의심 목록으로만 보인다(사람이 확인).
- 손 크기·목적·상황·성향 쪽 비교는 `scripts/eval_peripheral_post_extraction.py`가 한다(짝 도구).
- 추출 정확도를 사람 정답으로 정식 평가하는 도구와 절차는 9장.

확인할 것: F 묶음 글은 근거가 없어야 한다(F10은 `other`만 나올 수 있다) · 같은 글은 한 번만 세어진다(E21~E24) ·
F12는 수정본 적재 뒤 원글 근거가 사라진다 · 제품별 최근 3개월 글 수가 기획표(`최근에 몰림` 8종, `예전에 몰림` 8종)와 같다.

문제가 없으면 내보낸다.

```bash
PYTHONPATH=. uv run python db/community_examples_snapshot.py export data/community_examples/dump
```

출력: 테이블별 행 수. `dump/` 폴더를 팀 사설 채널로 전달한다(저장소에는 올리지 않는다).

## 5. 팀원 절차

**분석 결과까지 받을 때(⑥ 복원)**

1. 저장소를 받고 3장 준비를 마친다(마이그레이션 0019까지, 카탈로그 제품이 들어 있어야 한다).
2. 전달받은 `dump/` 폴더를 `data/community_examples/dump/`에 둔다.
3. 복원한다.

```bash
PYTHONPATH=. uv run python db/community_examples_snapshot.py restore data/community_examples/dump
```

| 출력 | 뜻 |
|---|---|
| `복원함` + 행 수 | 정상. 글·연결 제품·이미지·분석 대기·근거·벡터가 들어갔다 |
| `이미 있는 예시 글 N편과 겹친다` | 이 DB에 같은 글이 이미 있다. 덮어쓰려면 `--replace` |
| `테이블 열 구성이 달라 복원할 수 없다` | 마이그레이션이 다르다. 최신 develop을 받아 `db/migrate.py up`(또는 `db/setup_all.py`)을 다시 돌린다 |
| `카탈로그에서 제품을 하나로 찾지 못했다` | 이 DB의 카탈로그에 그 제품이 없다. `db/seed_peripherals.py`를 확인한다 |

- 복원은 한 트랜잭션이라 실패하면 아무것도 바뀌지 않는다.
- 제품 id는 DB마다 달라서 스냅샷에는 `brand`·`model`이 같이 들어 있고, 복원 때 이 DB의 카탈로그에서 다시 찾는다.
- 작성자 계정은 이메일로 맞춘다(있으면 그 계정을 쓰고, 없으면 만든다).

**글과 이미지만 필요할 때(분석 결과 없이)**: 3장 준비 → ①(점검) → ②(`--apply`). 이미지는 저장소에 JPEG로 들어 있다.

## 6. 글을 고치거나 더할 때

| 상황 | 방법 |
|---|---|
| 글 하나를 고침 | 적재 담당 DB에서 `--apply --update`(본문·제목·태그·제품 갱신). 분석은 다음 실행에서 해당 글만 다시 한다. 이후 스냅샷을 다시 내보낸다 |
| 글을 더함 | ②에서 새 글만 올라간다(같은 id는 건너뜀). ③ 분석, 스냅샷 재생성 |
| 이미지를 더하거나 바꿈 | 8장 절차. ⓪ → `--apply --update`. 스냅샷에는 이미지 파일이 함께 들어가므로 다시 내보내면 된다 |
| 팀원 DB를 처음 상태로 | `restore … --replace` (같은 글을 지우고 다시 넣는다) |

## 7. 알아 둘 제약

- **게시일**: 머리말 `written_at`이 `community.post.published_at`이 된다. `--update`는 이미 올라간 글의 날짜를 바꾸지 않는다(날짜를 고치려면 `restore --replace`나 글 삭제 후 재적재).
- **이미지 위치**: 본문 마커 자리에 이미지가 나온다. 마커 없이 머리말 `images`에만 있는 이미지는 본문 맨 아래에 붙는다.
  프런트는 `web/src/components/MarkdownBody.tsx`(react-markdown)가 그린다.
- **카탈로그**: 제품은 `catalog.product`의 `brand`+`model`로 연결한다. 글의 표기가 글자까지 같아야 한다.
- **분석 한도**: 하루 분석 한도(`PERIPHERAL_POST_DAILY_LIMIT`)를 넘으면 그날은 멈추고 남은 글은 대기로 남는다.
- **모델 응답은 매번 조금 다르다**: 같은 글을 다시 분석하면 추출 항목이 약 30% 달라질 수 있다(재현성 약 70%). 그래서 분석은 한 사람이 한 번 하고 스냅샷으로 나눈다.
- **개발·운영 DB에는 가짜 벡터를 넣지 않는다**(`MOCK_MODE=1` 금지).

## 8. 이미지 규칙

글마다 0~3장. 파일은 글 파일과 같은 폴더에 두고 머리말 `images`에 이름을 적는다(⓪이 자동으로 한다).

```yaml
images: [a1-1_1.jpg, a1-1_2.jpg]     # 첫 장이 대표 이미지, 글당 최대 5장
```

| 규칙 | 값 |
|---|---|
| 파일 이름 | `<글번호 소문자>_<순번>.<확장자>` (예 `a1-1_1.jpg`) |
| 형식·크기 | JPEG, PNG, WebP, 장당 5MB 이하(저장소에는 JPEG만 둔다) |
| 가공 | 적재 때 긴 변 1600px로 줄이고 EXIF를 지운다 |
| 출처 | 직접 찍거나 **생성한** 이미지만. 제조사·쇼핑몰 이미지를 그대로 쓰지 않는다 |
| 내용 | 책상·작업 환경 같은 분위기 컷. 로고·글자·얼굴이 나오지 않게 한다 |

순서

1. 이미지를 만들고(원본 이름은 글 번호가 보이면 된다) 글 폴더에 둔다.
2. ⓪ `link_example_images.py`로 JPEG 변환·머리말·마커를 한 번에 처리한다.
3. ① 점검(dry-run): 파일이 없거나 형식·크기가 맞지 않거나 마커가 머리말에 없으면 글별로 오류가 나온다.
4. 이미 올라간 글에 이미지를 붙이거나 바꾸려면 `--apply --update`(머리말에 `images`가 있을 때만 이미지를 교체한다).
5. 적재한 DB에서 스냅샷을 다시 내보낸다. 이미지 파일은 `dump/images/<저장 키>`로 함께 담긴다.
6. 팀원은 복원한다. 이미지 파일이 각자 저장소(`COMMUNITY_UPLOAD_DIR`)에 같은 키로 복사된다.

`restore --replace`로 글을 다시 넣을 때 새 스냅샷에 없는 이전 이미지 파일은 커밋 뒤에 정리된다.

PNG 원본(약 220MB)은 저장소에 올리지 않는다. 필요한 사람에게 파일로 따로 전달한다(`data/community_example_images_original/`).

## 9. 추출 정확도 평가

분석 결과가 사람이 읽은 정답과 얼마나 맞는지 재는 절차와 도구는 `data/eval_extraction/README.md`에 있다.
정답 라벨링(라벨러 2명)이 끝나기 전에는 정확도 지표를 낼 수 없고, 정답이 필요 없는 지표(재현성·환각)만 `report.md`에 있다.
라벨 시트·열쇠·모델 결과·정답 파일은 라벨러가 정답을 보게 되면 평가가 오염되므로 저장소에 올리지 않는다.

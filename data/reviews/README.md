# 제품별 리뷰 데이터 (팀 내 공유 파일)

PC 부품·주변기기 제품별 리뷰 원본입니다. **리뷰 원문과 작성자(일부 마스킹) 정보가 들어 있어 `*.jsonl`은 Git에 올리지 않습니다.**
팀 공유 파일을 받아 이 폴더에 넣어 주세요. (`.gitignore`의 `/data/reviews/*.jsonl`)

| 파일 | 대상 | 리뷰 수 |
|---|---|---|
| `computer_review_processed.jsonl` | PC 부품 | 5,578 |
| `monitor_review_processed.jsonl` | 모니터 | 2,111 |
| `keyboard_review_processed.jsonl` | 키보드 | 2,523 |
| `mouse_review_processed.jsonl` | 마우스 | 4,007 |
| `speaker_review_processed.jsonl` | 스피커 | 606 |

## 형식

한 줄이 리뷰 한 건인 JSON Lines(UTF-8)입니다.

| 필드 | 설명 |
|---|---|
| `manufacturer`, `model` | 제품 식별(제조사 + 모델명) |
| `data_kind` | 데이터 종류 (예: `real`) |
| `title`, `text` | 리뷰 제목, 본문 |
| `rating` | 별점 |
| `source_platform`, `source_url` | 출처(예: 다나와), 원문 주소(없으면 `null`) |
| `metadata` | 작성자(마스킹), 작성일, 실제/생성 구분 등 |

## 현재 상태

- 이 파일들을 읽어서 DB나 추천에 반영하는 코드는 **아직 없습니다.** 적재·연동은 담당 팀원이 별도로 작성합니다.
- 카탈로그(`catalog.*`)와 연결하려면 `manufacturer` + `model` 기준 매핑이 필요합니다.

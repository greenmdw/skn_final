# 사용기 분석 추출 정확도 평가 — 실행 기록과 절차

기획: `사용기분석_추출정확도_평가기획.md`(2026-10-14). 이 폴더는 그 기획을 실행하는 파일이다.

## 지금 상태 (2026-10-14)

| 단계 | 상태 | 산출물 |
|---|---|---|
| 말뭉치 선정·동결 | 완료(40편 + 지시문 글 5편 미작성) | `manifest.json` (post_id·본문 해시·종류·출처, 프롬프트 동결 해시) |
| 모델 추출 3회 | 완료(40편 × 3회) | `model_runs/<글번호>.json` (raw + confirmed) |
| 라벨 시트 | 완료 | `label_sheets_A.xlsx`, `label_sheets_B.xlsx` (글 번호를 가린 P01~P40, 순서 섞음) |
| 정답 라벨링(2명) | **미완료 — 사람이 해야 한다** | 라벨러가 채운 시트 2벌 |
| 합의 정답·κ | 미완료 | `gold.json` |
| 채점 M1~M13 | 정답이 필요 없는 지표(M9·M13)만 | `report.md` |

## 절차

1. 라벨러 2명에게 `label_sheets_A.xlsx` / `label_sheets_B.xlsx` 를 **따로** 준다. `label_key.json`(P번호 → 글 번호)과 `model_runs/` 는 주지 않는다.
2. 두 사람이 서로 보지 않고 채운다(기획 4장). 다 채우면 파일을 `label_sheets_A_done.xlsx` 처럼 저장해 가져온다.
3. 일치도와 임시 채점:

   ```bash
   python scripts/eval_extraction_score.py --gold-xlsx data/eval_extraction/label_sheets_A_done.xlsx --gold-xlsx data/eval_extraction/label_sheets_B_done.xlsx
   ```

   불일치는 두 사람이 합의해 `gold.json` 으로 확정한다(형식은 `src/engine/peripheral_post_eval_metrics.py` 맨 위 docstring).
4. 확정 정답으로 채점: `python scripts/eval_extraction_score.py --gold data/eval_extraction/gold.json` → `report.md`.
5. 글이 바뀌지 않았는지: `python scripts/eval_extraction_corpus.py --check`.

## 다시 돌릴 때(프롬프트를 고친 뒤, 기획 11장)

```bash
python scripts/eval_extraction_corpus.py                 # 새 동결 기록
python scripts/eval_extraction_run.py --reps 3 --workers 6   # MOCK_MODE=0, PERIPHERAL_POST_AGENT=1 필요 · DB 에 쓰지 않는다
python scripts/eval_extraction_score.py --gold data/eval_extraction/gold.json
```

## 알려진 공백(기획 12장에 그대로 적을 것)

- 지시문이 섞인 글(C) 5편이 예시 글에 없다 → M12 는 그 글을 적재한 뒤 측정한다.
- 본문 4,000자 근처 긴 글이 없다(예시 글 1,300~2,000자) → 잘림(E10)을 못 본다.
- 실제 사용자 글이 없다 → 모두 예시 글 기준이다. 출처별 분리 보고는 실제 글이 생긴 뒤.
- 동결 시점 작업 트리에 미커밋 변경이 있었다(`manifest.json` 의 `freeze`). 커밋 후 다시 동결 기록을 남기는 것이 안전하다.

# 사용기 분석 추출 정확도 평가 보고서(초안)

- 말뭉치: 40편 · 모델 결과 40편 · 동결: git `7678cc1125` (작업 트리에 미커밋 변경 있음)
- 동결 파일 해시: {'src/agent/peripheral_post_agent.py': '50946459dba946ea', 'src/engine/peripheral_post_contract.py': 'c304fad6657d9542', 'src/engine/peripheral_post_text.py': 'f604a15e24b9c311', 'config/peripherals.yaml': 'ad66ebdcee7b0acb'}

## 정답이 필요 없는 지표

| 항목 | 값 |
|---|---|
| 글 · 호출 · 오류 | 40 · 120 · 0 |
| 원래 추출(raw) 항목 / 최종(confirmed) 항목 | 2041 / 1365 |
| M9 본문에 없는 문장(raw) | 5 |
| M13 재현성(같은 글 회차 간 최종 항목 Jaccard 평균) | 69% |

## 정답 비교

정답(라벨 시트)이 아직 없어 M1~M8·M10~M12 는 계산하지 않았다.


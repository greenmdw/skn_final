"""peripheral_sensitivity.py 를 세 가지 설정으로 돌린 결과(summary.json)를 나란히 비교한다.
  ① 적용 전: 조건 스펙 가중 ×1                     (outputs/peripheral_sensitivity_m1)
  ② ×2:      조건 스펙 가중 ×2                     (outputs/peripheral_sensitivity)
  ③ 감점만: ×1 + 근거 부족 감점 λ=0.10(5건 미만)     (outputs/peripheral_sensitivity_lam)
  ④ ×2 + 근거 부족 감점 λ=0.10                      (outputs/peripheral_sensitivity_combo)

실행(PowerShell):
  uv run --group review-analysis python scripts/peripheral_sensitivity.py --spec-cond-mult 1 --out outputs/peripheral_sensitivity_m1
  uv run --group review-analysis python scripts/peripheral_sensitivity.py --spec-cond-mult 2
  uv run --group review-analysis python scripts/peripheral_sensitivity.py --spec-cond-mult 2 --evidence-lambda 0.10 --no-review-penalty 0 --out outputs/peripheral_sensitivity_combo
  uv run python scripts/peripheral_compare_runs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTS = ROOT / "outputs"
RUNS = [("① 적용 전", OUTS / "peripheral_sensitivity_m1"),
        ("② ×2", OUTS / "peripheral_sensitivity"),
        ("③ 감점만(×1 + λ=0.10)", OUTS / "peripheral_sensitivity_lam"),
        ("④ ×2 + 근거 부족 감점", OUTS / "peripheral_sensitivity_combo")]
OUT = OUTS / "peripheral_sensitivity_combo" / "combo_compare.md"
KINDS = ["keyboard", "monitor", "mouse", "speaker"]


def pct(x):
    return f"{x:.0%}"


def f2(x):
    return f"{x:.2f}"


def chain(vals, fmt=pct):
    return " → ".join(fmt(v) for v in vals)


def main():
    R = [json.loads((d / "summary.json").read_text(encoding="utf-8")) for _, d in RUNS]
    L = []
    P = L.append
    P("# 조건 스펙 가중 + 근거 부족 감점 조합 재측정\n")
    P("같은 요청 1,000개(품목당 250개), 같은 시드로 네 설정을 비교했다. 표의 값은 ① → ② → ③ → ④ 순서다. ③은 조건 스펙 가중 없이 근거 부족 감점만 적용해, ④의 개선이 ×2 때문인지 감점 때문인지 가르기 위한 설정이다.\n")
    P("| 설정 | 조건 스펙 가중 | 근거 부족 감점 |")
    P("|---|---|---|")
    for (name, _), r in zip(RUNS, R):
        lam = r.get("evidence_lambda", 0)
        P(f"| {name} | ×{r['spec_cond_mult']:g} | {'λ=%.2f (관측 5건 미만에 λ × (1 − 관측/5))' % lam if lam else '없음'} |")
    P("\n- 1·4·5장의 지표는 요청별로 후보 풀을 만든 뒤 가중치를 흔들어 잰 값이며, ③·④에서는 근거 부족 감점이 점수에 들어간다(①·②는 감점 없음).")
    P("- 쏠림·기본값 지표(2·3·6장)의 ①·②는 '리뷰 0건 감점 0.05'를, ③·④는 근거 부족 감점(리뷰 0건이면 0.10)을 쓴다.\n")

    P("## 1. 안정성\n")
    P("| 품목 | 1위 유지율 ±20% | 1위 유지율 ±50% | 접전(점수 차 0.01 미만) |")
    P("|---|---|---|---|")
    for k in KINDS + ["전체"]:
        c = [r["cells"][k] for r in R]
        P(f"| {k} | {chain([x['mean20'] for x in c])} | {chain([x['mean50'] for x in c])} | {chain([x['close'] for x in c])} |")
    P("")
    P("## 2. 1위 쏠림\n")
    P("| 품목 | 최다 1위 상품 점유율 | 유효 상품 수 | 서로 다른 1위 상품 수 |")
    P("|---|---|---|---|")
    for k in KINDS:
        c = [r["conc"][k] for r in R]
        P(f"| {k} | {chain([x['top_share'] for x in c])} | {chain([x['eff'] for x in c], lambda v: f'{v:.1f}')} | {chain([x['distinct'] for x in c], str)} |")
    P("")
    P("④가 ①·②·③과 1위가 같은 요청 비율:\n")
    P("| 품목 | ④ vs ① | ④ vs ② | ④ vs ③ |")
    P("|---|---:|---:|---:|")
    for k in KINDS:
        n = [r["cells"][k]["top1_names"] for r in R]
        P(f"| {k} | {pct(np.mean([a == b for a, b in zip(n[3], n[0])]))} | {pct(np.mean([a == b for a, b in zip(n[3], n[1])]))} | {pct(np.mean([a == b for a, b in zip(n[3], n[2])]))} |")
    P("")
    P("## 3. 1위가 어떤 상품인가\n")
    P("가격·리뷰 위치는 후보 풀 안에서 0 = 가장 싼/리뷰 값이 낮은 쪽, 1 = 가장 비싼/높은 쪽이다.\n")
    P("| 품목 | 1위의 가격 위치 | 1위의 리뷰 위치 | 리뷰 근거 3건 미만인 1위 |")
    P("|---|---|---|---|")
    for k in KINDS:
        c = [r["cells"][k] for r in R]
        P(f"| {k} | {chain([x['top1_price_pos'] for x in c], f2)} | {chain([x['top1_review_pos'] for x in c], f2)} | {chain([x['thin_top1'] for x in c])} |")
    P("")
    P("## 4. 리뷰 반영과 한 축 흔들기\n")
    P("| 품목 | 리뷰를 켜면 1위가 바뀜 | 리뷰 0.2~0.4에서 1위 불변 | 스펙 가중치를 크게 바꿔 1위가 바뀜 | 리뷰 가중치를 크게 바꿔 1위가 바뀜 | 가격 가중치를 크게 바꿔 1위가 바뀜 |")
    P("|---|---|---|---|---|---|")
    for k in KINDS + ["전체"]:
        c = [r["cells"][k] for r in R]
        P(f"| {k} | {chain([x['review_off_changes'] for x in c])} | {chain([x['review_mid_stable'] for x in c])} | {chain([x['flip_spec_wide'] for x in c])} | "
          f"{chain([x['flip_review_wide'] for x in c])} | {chain([x['flip_price_wide'] for x in c])} |")
    P("")
    P("## 5. 접전의 크기\n")
    P("| 품목 | 1·2위 점수 차 중앙값 | 0.01 미만 | 0.02 미만 |")
    P("|---|---|---|---|")
    for k in KINDS:
        g = [np.array(r["cells"][k]["gaps"]) for r in R]
        P(f"| {k} | {chain([float(np.median(x)) for x in g], lambda v: f'{v:.3f}')} | {chain([float((x < 0.01).mean()) for x in g])} | {chain([float((x < 0.02).mean()) for x in g])} |")
    P("")
    P("## 6. 현재 기본값에서의 지표 (가중치 격자 탐색의 기준점)\n")
    P("| 품목 | 유지율 | 접전 | 가격 강조 요청의 1위 가격 위치 | 리뷰 강조 요청의 1위 리뷰 위치 | 리뷰 없는 1위 |")
    P("|---|---|---|---|---|---|")
    for k in KINDS:
        c = [r["cells"][k]["reco"] for r in R]
        P(f"| {k} | {chain([x['keep'] for x in c])} | {chain([x['close'] for x in c])} | {chain([x['price_pos'] for x in c], f2)} | "
          f"{chain([x['rev_pos'] for x in c], f2)} | {chain([x['norev'] for x in c])} |")
    P("")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"완료: {OUT}")


if __name__ == "__main__":
    main()

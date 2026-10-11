"""모니터·스피커 1위 쏠림을 줄이는 방법 비교 — peripheral_sensitivity.py 의 요청·점수식을 그대로 가져와
점수식을 조금씩 바꾼 변형을 같은 요청 1,000개에서 비교한다. src/ 와 DB 는 건드리지 않는다.

비교하는 변형(모두 '리뷰 없는 상품 감점 0.05'를 깔고 시작한다)
- 가격 곡선(γ): 가격 값 = 1 − x^γ (x = 가격의 위치 0~1). γ>1 이면 싼 쪽 끝의 차이가 줄어 '가장 싼 상품'의 이점이 줄어든다.
- 근거 부족 감점(λ): 리뷰 관측이 N0건 미만이면 λ × (1 − 관측/N0) 감점. 리뷰 0건만이 아니라 얇은 근거도 감점한다.
- 조건 스펙 가중(m): 사용자가 조건을 말한 스펙 축의 가중치를 m배(강조 배수와 별개).
- 조합: 위 셋의 조합.
- 대안 다양화(1위는 그대로): 상위 3개를 점수 순이 아니라 '점수가 가까운 후보 중 가장 싼 것 / 리뷰가 가장 좋은 것'으로 구성.

실행(PowerShell): $env:PYTHONPATH="."; $env:PYTHONIOENCODING="utf-8"; uv run --group review-analysis python scripts/peripheral_concentration.py
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import peripheral_sensitivity as ps  # noqa: E402

ROOT = ps.ROOT
NR_PEN = 0.05   # --sweep 모드에서는 0 (근거 부족 감점이 0건 감점을 대신한다)


def pct(x):
    return f"{x:.0%}"


def conc(counter):
    tot = sum(counter.values())
    sh = np.array([v / tot for v in counter.values()])
    return dict(top=float(sh.max()), eff=float(1 / (sh ** 2).sum()), distinct=len(counter))


class Item:
    def __init__(self, persona, S, rng, trials):
        self.p, self.S = persona, S
        self.n = len(S.rows)
        self.U = rng.uniform(0.8, 1.2, (trials, len(S.axes)))
        self.price = np.array([c.price for c, _, _, _ in S.rows])
        self.price_pct = np.array([(self.price < x).sum() / (self.n - 1) for x in self.price])
        rv = S.V_raw[:, S.axes.index("리뷰")]
        self.rev = rv
        self.rev_pct = np.array([(rv < x).sum() / (self.n - 1) for x in rv])
        self.names = [S.name(i) for i in range(self.n)]
        self.spec_axes = [a for a, cs in (persona.get("spec") or {}).items() if any(c["w"] >= 2 for c in cs)]   # 직접 말한 조건이 있는 기준
        self.emph = persona.get("emphasis", [])


def variant_arrays(it, var):
    S = it.S
    V = S.V.copy()
    pi = S.axes.index("가격")
    if var.get("gamma", 1) != 1:
        V[:, pi] = 1 - (1 - V[:, pi]) ** var["gamma"]
    pen = S.pen.copy()
    if var.get("lam", 0):
        pen = pen + var["lam"] * np.maximum(0.0, 1 - S.nobs / var.get("n0", 5))
    w = S.base_weights()
    if var.get("m", 1) != 1:
        for a in it.spec_axes:
            w[a] *= var["m"]
        w = ps.normalize(w)
    return V, pen, S.vec(w)


def run_variant(items, var, base_top1=None):
    top1_names, rows = Counter(), []
    for idx, it in enumerate(items):
        V, pen, v = variant_arrays(it, var)
        sc = V @ v - pen - it.S.tb
        order = np.argsort(-sc)
        t1 = int(order[0])
        W = v[None, :] * it.U
        W = W / W.sum(axis=1, keepdims=True)
        keep = float(((V @ W.T).T - pen - it.S.tb).argmax(axis=1).__eq__(t1).mean())
        top1_names[it.names[t1]] += 1
        rows.append(dict(
            name=it.names[t1], keep=keep, close=bool(sc[order[0]] - sc[order[1]] < 0.01), nobs=int(it.S.nobs[t1]),
            price_pct=float(it.price_pct[t1]), rev_pct=float(it.rev_pct[t1]), n=it.n,
            emph_price="가격" in it.emph, emph_rev="리뷰" in it.emph, score=float(sc[t1])))
    out = dict(conc=conc(top1_names), keep=np.mean([r["keep"] for r in rows]), close=np.mean([r["close"] for r in rows]),
               norev=np.mean([r["nobs"] == 0 for r in rows]), thin=np.mean([r["nobs"] < 3 for r in rows]),
               price_pos=np.mean([r["price_pct"] for r in rows]),
               price_pos_emph=np.mean([r["price_pct"] for r in rows if r["emph_price"]]),
               rev_pos_emph=np.mean([r["rev_pct"] for r in rows if r["emph_rev"]]),
               top3=top1_names.most_common(3), names=[r["name"] for r in rows], rows=rows)
    if base_top1 is not None:
        out["same"] = float(np.mean([a == b for a, b in zip(out["names"], base_top1)]))
    return out


def diversified_lists(items, eps):
    """상위 3개를 (1위, 점수가 가까운 후보 중 최저가, 점수가 가까운 후보 중 리뷰 최고)로 구성."""
    base_cnt, div_cnt, loss, changed, cheaper, better_rev = Counter(), Counter(), [], 0, 0, 0
    for it in items:
        V, pen, v = variant_arrays(it, {})
        sc = V @ v - pen - it.S.tb
        order = [int(i) for i in np.argsort(-sc)]
        t3 = order[:3]
        t1 = order[0]
        near = [i for i in order[1:] if sc[t1] - sc[i] <= eps]
        picks = [t1]
        if near:
            picks.append(min(near, key=lambda i: (it.price[i], i)))
        rest = [i for i in near if i not in picks]
        if rest:
            picks.append(max(rest, key=lambda i: (it.rev[i], -i)))
        for i in order[1:]:
            if len(picks) >= 3:
                break
            if i not in picks:
                picks.append(i)
        picks = picks[:3]
        for i in t3:
            base_cnt[it.names[i]] += 1
        for i in picks:
            div_cnt[it.names[i]] += 1
        loss.append(float(sum(sc[t3]) - sum(sc[picks])))
        changed += set(picks) != set(t3)
        cheaper += any(it.price[i] < it.price[t1] for i in picks[1:])
        better_rev += any(it.rev[i] > it.rev[t1] + 1e-9 for i in picks[1:])
    n = len(items)
    return dict(base=conc(base_cnt), div=conc(div_cnt), loss=float(np.mean(loss)), changed=changed / n, cheaper=cheaper / n, better_rev=better_rev / n)


def sweep(items, kinds, out, args):
    LAMS = [0.05, 0.10, 0.15, 0.20, 0.30]
    N0S = [3, 5, 10, 20]
    L = []
    P = L.append
    P("# 근거 부족 감점 크기(λ)와 기준 건수(N0) 재측정\n")
    P("조건 스펙 가중 ×2를 깔고, 근거 부족 감점 `λ × max(0, 1 − n / N0)`의 λ와 N0를 바꿔 가며 같은 요청 1,000개(품목당 250개)에서 비교했다. "
      "리뷰 0건 감점 0.05는 쓰지 않는다(근거 부족 감점이 대신한다). 현재 기획서 값은 λ=0.10, N0=5다. "
      f"유지율은 가중치 ±20% 흔들기 {args.trials}회.\n")
    P("- 기준 ①: 적용 전(조건 스펙 가중 ×1, 감점 없음), 기준 ②: 조건 스펙 가중 ×2만(감점 없음).\n")
    METR = [("conc_top", "최다 1위 상품 점유율", pct), ("close", "접전(점수 차 0.01 미만)", pct), ("keep", "1위 유지율 ±20%", pct),
            ("thin", "리뷰 근거 3건 미만인 1위", pct), ("norev", "리뷰 0건인 1위", pct), ("price_pos", "1위의 가격 위치(0 = 가장 싼 쪽)", lambda x: f"{x:.2f}"),
            ("same", "②와 1위가 같은 요청", pct)]
    res = {}
    for k in kinds:
        refs = {"①": run_variant(items[k], {}), "②": run_variant(items[k], {"m": 2})}
        base2 = refs["②"]["names"]
        grid = {}
        for lam in LAMS:
            for n0 in N0S:
                grid[(lam, n0)] = run_variant(items[k], {"m": 2, "lam": lam, "n0": n0}, base2)
        res[k] = (refs, grid)

    def val(r, key):
        if key == "conc_top":
            return r["conc"]["top"]
        if key == "same":
            return r.get("same", 1.0)
        return r[key]

    for k in kinds:
        refs, grid = res[k]
        P(f"## {k}\n")
        P("기준값: " + " / ".join(f"{n} " + ", ".join(f"{lab} {fmt(val(r, key))}" for key, lab, fmt in METR[:6]) for n, r in refs.items()) + "\n")
        for key, lab, fmt in METR:
            P(f"**{lab}** — 행: λ, 열: N0\n")
            P("| λ＼N0 | " + " | ".join(str(n) for n in N0S) + " |")
            P("|---|" + "---:|" * len(N0S))
            for lam in LAMS:
                P(f"| {lam:.2f} | " + " | ".join(fmt(val(grid[(lam, n0)], key)) for n0 in N0S) + " |")
            P("")
    P("## 모니터·마우스·스피커 평균\n")
    P("키보드는 98%의 상품에 리뷰가 있어 감점의 영향이 거의 없어 제외했다.\n")
    avg_k = [k for k in kinds if k != "keyboard"]
    for key, lab, fmt in METR:
        P(f"**{lab}**\n")
        P("| λ＼N0 | " + " | ".join(str(n) for n in N0S) + " |")
        P("|---|" + "---:|" * len(N0S))
        for lam in LAMS:
            P(f"| {lam:.2f} | " + " | ".join(fmt(float(np.mean([val(res[k][1][(lam, n0)], key) for k in avg_k]))) for n0 in N0S) + " |")
        P("")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"완료: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--per-kind", type=int, default=250)
    ap.add_argument("--seed", type=int, default=20261005)
    ap.add_argument("--sweep", action="store_true", help="근거 부족 감점의 λ와 기준 건수(N0)를 격자로 재측정한다")
    args = ap.parse_args()
    out = ROOT / "outputs" / "peripheral_sensitivity" / ("lambda_sweep.md" if args.sweep else "concentration.md")
    pyrng, nprng = random.Random(args.seed), np.random.default_rng(args.seed)

    cands = ps.load_peripheral_candidates_from_csv(ROOT / "data" / "peripherals", filename_template="{kind}_processed.csv")
    specs = {c.product_key: ps.derive(k, c) for k, v in cands.items() for c in v}
    rev = ps.load_reviews(cands)
    kinds = list(cands)
    items = {}
    for k in kinds:   # peripheral_sensitivity 와 같은 순서·시드로 같은 요청을 만든다
        personas, _, _ = ps.generate_personas(k, cands[k], specs, rev[k], args.per_kind, pyrng)
        items[k] = [Item(p, ps.Setup(p, cands[k], specs, rev[k], no_review_penalty=0.0 if args.sweep else NR_PEN), nprng, args.trials) for p in personas]
    if args.sweep:
        sweep(items, kinds, out, args)
        return

    L: list[str] = []
    P = L.append
    P("# 모니터·스피커 1위 쏠림 줄이기 — 방법 비교\n")
    P(f"요청 {sum(len(v) for v in items.values())}개(품목당 {args.per_kind}개), 가중치는 현재 기본값, 리뷰 없는 상품 감점 0.05를 깐 상태에서 출발한다. 유지율은 가중치 ±20% 흔들기 {args.trials}회.\n")

    # 0. 진단
    P("## 0. 왜 쏠리는가 — 진단\n")
    P("| 품목 | 가장 자주 1위인 상품 | 점유율 | 가격 / 리뷰 관측 | 그 상품이 후보 풀에 든 요청 중 1위 비율 | 2위보다 가격·리뷰가 모두 우세한 비율 | 후보 풀 크기(중앙값) |")
    P("|---|---|---:|---|---:|---:|---:|")
    for k in kinds:
        base = run_variant(items[k], {})
        dom = Counter(base["names"]).most_common(1)[0][0]
        in_pool = sum(dom in it.names for it in items[k])
        wins = sum(n == dom for n in base["names"])
        par = tot = 0
        info = ""
        for it, r in zip(items[k], base["rows"]):
            if r["name"] != dom:
                continue
            V, pen, v = variant_arrays(it, {})
            sc = V @ v - pen - it.S.tb
            o = np.argsort(-sc)
            i, j = int(o[0]), int(o[1])
            ri, pi = it.S.axes.index("리뷰"), it.S.axes.index("가격")
            par += V[i, ri] >= V[j, ri] and V[i, pi] >= V[j, pi]
            tot += 1
            info = f"{it.price[i]:,}원 / {int(it.S.nobs[i])}건"
        P(f"| {k} | {dom} | {pct(wins / len(items[k]))} | {info} | {pct(wins / max(in_pool, 1))} | {pct(par / max(tot, 1))} | {int(np.median([it.n for it in items[k]]))} |")
    P("")
    P("**후보 풀 크기별 쏠림** (요청을 후보 풀 크기의 중앙값 기준으로 반으로 나눔):\n")
    P("| 품목 | 구분 | 요청 수 | 최다 1위 점유율 | 유효 상품 수 |")
    P("|---|---|---:|---:|---:|")
    for k in kinds:
        med = np.median([it.n for it in items[k]])
        base = run_variant(items[k], {})
        for label, cond in (("작은 풀(중앙값 이하)", lambda n: n <= med), ("큰 풀(중앙값 초과)", lambda n: n > med)):
            sub = Counter(r["name"] for r in base["rows"] if cond(r["n"]))
            if sub:
                c = conc(sub)
                P(f"| {k} | {label} | {sum(sub.values())} | {pct(c['top'])} | {c['eff']:.1f} |")
    P("")

    # 1. 변형 비교
    VARIANTS = [("기준(현재)", {}),
                ("가격 곡선 γ=1.5", {"gamma": 1.5}), ("가격 곡선 γ=2", {"gamma": 2}), ("가격 곡선 γ=3", {"gamma": 3}),
                ("근거 부족 감점 λ=0.05 (5건 미만)", {"lam": 0.05}), ("근거 부족 감점 λ=0.10", {"lam": 0.10}),
                ("근거 부족 감점 λ=0.15", {"lam": 0.15}), ("근거 부족 감점 λ=0.20", {"lam": 0.20}),
                ("조건 스펙 가중 ×1.5", {"m": 1.5}), ("조건 스펙 가중 ×2", {"m": 2}), ("조건 스펙 가중 ×3", {"m": 3}),
                ("조합 A: γ=2 + λ=0.10", {"gamma": 2, "lam": 0.10}),
                ("조합 B: γ=2 + λ=0.10 + ×2", {"gamma": 2, "lam": 0.10, "m": 2}),
                ("조합 C: ×2 + λ=0.10", {"m": 2, "lam": 0.10}),
                ("조합 D: ×2 + γ=1.5", {"m": 2, "gamma": 1.5})]
    P("## 1. 변형별 비교\n")
    P("- **최다 1위 점유율 / 유효 상품 수 / 서로 다른 1위**: 쏠림 지표(낮은 점유율, 큰 유효 상품 수가 다양함).")
    P("- **유지율, 접전**: 안정성 지표. **리뷰 근거 얇은 1위**는 1위의 리뷰 관측이 3건 미만인 요청 비율.")
    P("- **기준과 1위 동일**: 기준 방식과 같은 상품이 1위인 요청 비율. 낮을수록 순위가 많이 바뀐 것.")
    P("- **가격 강조 요청의 1위 가격 위치**: 0 = 가장 싼 쪽. 가격을 강조했는데 이 값이 크게 오르면 기대와 어긋난다.\n")
    results = {}
    for k in kinds:
        base = run_variant(items[k], {})
        results[k] = {}
        P(f"### {k}\n")
        P("| 변형 | 최다 1위 점유율 | 유효 상품 수 | 서로 다른 1위 | 유지율 | 접전 | 리뷰 근거 얇은 1위 | 기준과 1위 동일 | 1위 가격 위치 | 가격 강조 요청의 1위 가격 위치 |")
        P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for label, var in VARIANTS:
            r = run_variant(items[k], var, base["names"])
            results[k][label] = r
            P(f"| {label} | {pct(r['conc']['top'])} | {r['conc']['eff']:.1f} | {r['conc']['distinct']} | {pct(r['keep'])} | {pct(r['close'])} | "
              f"{pct(r['thin'])} | {pct(r.get('same', 1.0))} | {r['price_pos']:.2f} | {r['price_pos_emph']:.2f} |")
        P("")

    # 2. 대안 다양화
    P("## 2. 대안 다양화 — 1위는 그대로 두고 상위 3개 구성을 바꾼다\n")
    P("1위는 점수 1등을 그대로 둔다. 2위·3위 자리를 점수 순이 아니라 '1위와 점수 차가 ε 이내인 후보 중 가장 싼 것'과 '가장 리뷰가 좋은 것'으로 채웠다. 쏠림을 직접 줄이지는 못하지만, 사용자에게 보이는 후보의 다양성과 선택지를 늘린다.\n")
    P("| 품목 | ε | 점수 순 상위3의 유효 상품 수 | 다양화 상위3의 유효 상품 수 | 점수 합 손실(평균) | 상위3 구성이 바뀐 요청 | 1위보다 싼 대안이 있는 요청 | 1위보다 리뷰가 좋은 대안이 있는 요청 |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in kinds:
        for eps in (0.03, 0.05, 0.08):
            d = diversified_lists(items[k], eps)
            P(f"| {k} | {eps:.2f} | {d['base']['eff']:.1f} | {d['div']['eff']:.1f} | {d['loss']:.3f} | {pct(d['changed'])} | {pct(d['cheaper'])} | {pct(d['better_rev'])} |")
    P("")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"완료: {out}")


if __name__ == "__main__":
    main()

"""주변기기 추천 점수식 민감도 시뮬레이션 — docs/주변기기_추천알고리즘_기획.md 3~4장의 점수식을 그대로 옮겨,
가중치·강조 배수·리뷰 비중·가격대 등을 흔들었을 때 1위가 얼마나 바뀌는지 잰다.

- 읽기 전용이다. src/ 엔진과 DB는 건드리지 않는다. 카탈로그 로더(peripheral_catalog)와 선언형 평가기
  (spec_rules)만 가져다 쓴다. 기획의 점수식(스펙 기준 분리·브랜드·무상 AS·리뷰 가중치)은 아직 엔진에
  구현돼 있지 않아서 이 스크립트가 따로 계산한다.
- 입력: data/peripherals/*_processed.csv(카탈로그), data/review_seed(리뷰 관측; 실제 리뷰 번들).
- 출력: outputs/peripheral_sensitivity/report.md + CSV. outputs/ 는 git 추적 대상이 아니다.
- 성향 차원(키압 등)은 아직 관측 데이터가 없어 다루지 않는다. 등록된 5개 속성(품질 차원)만 쓴다.

요청은 두 묶음이다. 품목마다 조건 조합(용도·배열·연결·손 크기·해상도 등 × 예산 5단계 × 강조 4가지)을 섞어 자동 생성한
요청(기본 250개/품목)과, 사람이 정한 대표 요청 20개.

실행(PowerShell): $env:PYTHONPATH="."; $env:PYTHONIOENCODING="utf-8"; python scripts/peripheral_sensitivity.py [--per-kind 250] [--trials 1000] [--seed 20261005]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from src.engine import spec_rules
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv

ROOT = Path(__file__).resolve().parent.parent
K_SMOOTH = 4            # 기획 4.3절: Q = (P + k*0.5) / (P + N + k)
PENDING_PENALTY = 0.20  # 기획 3.8절
EMPHASIS_MULT = 1.5     # 기획 3.3절
EVIDENCE_LAMBDA = 0.0    # 근거 부족 감점: 리뷰 관측이 N0건 미만이면 λ × (1 − 관측/N0) 감점. --evidence-lambda 로 바꾼다
EVIDENCE_N0 = 5
SPEC_COND_MULT = 1.0    # 기획 3.3절 "조건 스펙 가중"(2026-10-05 확정 시 2.0). --spec-cond-mult 로 바꾼다

# 기획 3.2절 품목별 기본 가중치(잠정). 키 = 축 이름, 스펙 기준은 품목마다 다르다.
BASE_WEIGHTS = {
    "keyboard": {"스위치·소음": 0.12, "배열·크기": 0.10, "연결": 0.08, "리뷰": 0.35, "가격": 0.27, "브랜드": 0.04, "AS": 0.04},
    "mouse":    {"손 맞춤": 0.15, "연결": 0.07, "기능": 0.08, "리뷰": 0.35, "가격": 0.27, "브랜드": 0.04, "AS": 0.04},
    "monitor":  {"화면": 0.20, "움직임": 0.10, "화질 사양": 0.10, "연결": 0.05, "리뷰": 0.22, "가격": 0.23, "브랜드": 0.04, "AS": 0.06},
    "speaker":  {"형태·크기": 0.15, "출력·채널": 0.10, "연결·전원": 0.10, "리뷰": 0.25, "가격": 0.32, "브랜드": 0.04, "AS": 0.04},
}
NON_SPEC = ("리뷰", "가격", "브랜드", "AS")
ASPECTS = {  # 등록된 속성(리뷰 관측의 aspect_code)
    "keyboard": ["typing_feel", "typing_noise", "connection_stability", "controls_usability", "physical_usability"],
    "mouse": ["tracking_input", "ergonomics", "connection_stability", "controls_usability", "battery_runtime"],
    "monitor": ["image_quality", "motion_response", "connection_stability", "controls_ergonomics", "functional_reliability"],
    "speaker": ["sound_quality", "output_level", "unwanted_noise", "connection_controls", "functional_reliability"],
}


def C(key, op, value, w=2):  # 스펙 조건 하나. w: 사용자가 직접 말했으면 2, 용도에서 유도했으면 1
    return {"key": key, "op": op, "value": value, "w": w}


def RANGE(key, lo, hi, step=5.0, pen=0.2, w=2):  # 범위 안이면 1, 벗어나면 step마다 pen씩 깎는다(기획 5.3절)
    return {"type": "range", "key": key, "lo": lo, "hi": hi, "step": step, "pen": pen, "w": w}


# 대표 요청(페르소나). budget = 상한 금액. emphasis = 강조 축(×1.5). boost = {속성: 중요도 가산}(기획 4.6절).
PERSONAS = [
    # ── 키보드 ──
    dict(id="KB1", kind="keyboard", label="타건감 묵직한 키보드, 10만 원 이하", budget=100000, emphasis=["리뷰"],
         boost={"typing_feel": 3}),
    dict(id="KB2", kind="keyboard", label="야간·사무용 조용한 키보드, 15만 원 이하", budget=150000, emphasis=["리뷰"],
         spec={"스위치·소음": [C("clicky", "equals", False)]}, boost={"typing_noise": 3}),
    dict(id="KB3", kind="keyboard", label="FPS 게임용 텐키리스·래피드 트리거, 30만 원 이하", budget=300000, emphasis=["스위치·소음"],
         spec={"스위치·소음": [C("rapid_trigger", "equals", True), C("switch_magnetic", "equals", True, 1)],
               "배열·크기": [RANGE("kb_length_mm", 340, 420, step=20)]}),
    dict(id="KB4", kind="keyboard", label="가성비 사무용 풀배열, 7만 원 이하", budget=70000, emphasis=["가격"],
         spec={"배열·크기": [RANGE("kb_length_mm", 420, 520, step=20)]}),
    dict(id="KB5", kind="keyboard", label="무선·블루투스 휴대용 컴팩트, 15만 원 이하", budget=150000, emphasis=[],
         spec={"연결": [C("connectivity_bluetooth", "equals", True)], "배열·크기": [RANGE("kb_length_mm", 0, 360, step=20)]}),
    # ── 마우스 ──
    dict(id="MS1", kind="mouse", label="손 작은 게이머(길이 107~124mm), 5만 원 이하", budget=50000, emphasis=["손 맞춤"],
         spec={"손 맞춤": [RANGE("length_mm", 107, 124), C("weight_g", "max", 80, 1)]}, boost={"ergonomics": 2}),
    dict(id="MS2", kind="mouse", label="손 큰 사무용 무선(길이 127~146mm), 10만 원 이하", budget=100000, emphasis=[],
         spec={"손 맞춤": [RANGE("length_mm", 127, 146)], "연결": [C("connectivity_wireless", "equals", True)]}),
    dict(id="MS3", kind="mouse", label="손목이 편하고 클릭이 조용한 마우스, 10만 원 이하", budget=100000, emphasis=["리뷰"],
         spec={"기능": [C("switch_click_raw", "contains_any", ["Quiet", "Silent", "무소음", "저소음"], 1)]},
         boost={"ergonomics": 3}),
    dict(id="MS4", kind="mouse", label="가벼운 FPS 마우스(80g 이하, 1000Hz+), 15만 원 이하", budget=150000, emphasis=["기능"],
         spec={"손 맞춤": [C("weight_g", "max", 80)], "기능": [C("polling_hz_max", "min", 1000)]}, boost={"tracking_input": 2}),
    dict(id="MS5", kind="mouse", label="가성비 무선 마우스, 3만 원 이하", budget=30000, emphasis=["가격"],
         spec={"연결": [C("connectivity_wireless", "equals", True)]}),
    # ── 모니터 ──
    dict(id="MN1", kind="monitor", label="FPS 게임용 24~27인치 144Hz 이상, 60만 원 이하", budget=600000, emphasis=["움직임"],
         hard=[C("refresh_hz", "min", 144)], spec={"화면": [RANGE("screen_size_inch", 24, 27, step=2, pen=0.5)],
         "움직임": [C("refresh_hz", "min", 240, 1), C("response_ms_gtg", "max", 2, 1)]}, boost={"motion_response": 2}),
    dict(id="MN2", kind="monitor", label="사무용 27인치 IPS, 40만 원 이하", budget=400000, emphasis=["가격"],
         spec={"화면": [RANGE("screen_size_inch", 26.5, 27.5, step=2, pen=0.5)], "화질 사양": [C("panel_raw", "contains_any", ["IPS"])]}),
    dict(id="MN3", kind="monitor", label="사진·디자인 작업용 27~32인치 4K IPS/OLED, 100만 원 이하", budget=1000000, emphasis=["리뷰", "화질 사양"],
         hard=[C("resolution_class", "member_of", ["UHD"])],
         spec={"화면": [RANGE("screen_size_inch", 27, 32, step=2, pen=0.5)], "화질 사양": [C("panel_raw", "contains_any", ["IPS", "OLED"])]},
         boost={"image_quality": 3}),
    dict(id="MN4", kind="monitor", label="가성비 QHD 165Hz 게이밍, 50만 원 이하", budget=500000, emphasis=["가격"],
         hard=[C("resolution_class", "member_of", ["QHD"]), C("refresh_hz", "min", 165)], spec={}),
    dict(id="MN5", kind="monitor", label="프리미엄 OLED 게이밍(70만 원 초과 가격대)", tier=(700000, None), emphasis=["리뷰"],
         spec={"화질 사양": [C("panel_raw", "contains_any", ["OLED"])], "움직임": [C("refresh_hz", "min", 240)]},
         boost={"image_quality": 2}),
    # ── 스피커 ──
    dict(id="SP1", kind="speaker", label="사무용 사운드바(USB 전원), 10만 원 이하", budget=100000, emphasis=[],
         spec={"형태·크기": [C("speaker_form_raw", "contains_any", ["사운드바"])], "연결·전원": [C("power_source_raw", "contains_any", ["USB"])]}),
    dict(id="SP2", kind="speaker", label="음악 감상 북셸프, 30만 원 이하", budget=300000, emphasis=["리뷰"],
         spec={"형태·크기": [C("speaker_form_raw", "contains_any", ["북셸프"])], "출력·채널": [C("output_w", "min", 40, 1)]},
         boost={"sound_quality": 3}),
    dict(id="SP3", kind="speaker", label="저음 중시 2.1 채널, 20만 원 이하", budget=200000, emphasis=["출력·채널"],
         spec={"출력·채널": [C("channels", "min", 2.1)]}, boost={"sound_quality": 2}),
    dict(id="SP4", kind="speaker", label="블루투스 소형 스피커, 5만 원 이하", budget=50000, emphasis=[],
         spec={"연결·전원": [C("connectivity_bluetooth", "equals", True)], "형태·크기": [C("weight_g", "max", 1500)]}),
    dict(id="SP5", kind="speaker", label="가성비 스피커, 3만 원 이하", budget=30000, emphasis=["가격"], spec={}),
]


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def floats(raw):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", raw or "")]


def derive(kind, cand):
    """엔진 specs에 없는 값(크기·클릭형 여부)을 이 스크립트가 파생한다."""
    s = dict(cand.specs)
    nums = floats(s.get("size_mm_raw"))
    if kind == "keyboard":
        if nums:
            s["kb_length_mm"] = nums[0]
        kind_txt = f"{s.get('switch_kind_raw') or ''} {s.get('switch_method_raw') or ''}"
        known = bool(s.get("switch_kind_raw") and s.get("switch_kind_raw") != "—")
        s["clicky"] = (any(t in kind_txt for t in ("Clicky", "Blue", "청축", "클릭")) if known else None)
    if kind == "mouse" and len(nums) >= 2:
        s["width_mm"], s["length_mm"] = nums[0], nums[1]
    return s


def load_reviews(cands_by_kind):
    """product_id → 후보 매칭은 모델명 정규화 일치. 반환: {kind: {cand.product_key: {aspect: [P, N, mixed]}}}"""
    base = ROOT / "data" / "review_seed"
    docs = json.loads((base / "documents.json").read_text(encoding="utf-8"))
    obs = json.loads((base / "consolidated_observation_drafts.json").read_text(encoding="utf-8"))
    pid_model = {d["product_id"]: (d["part_type"], norm(d["product_model"])) for d in docs}
    out = {k: defaultdict(lambda: defaultdict(lambda: [0, 0, 0])) for k in cands_by_kind}
    index = {k: {norm(c.name[len(c.brand):].strip()): c.product_key for c in v} for k, v in cands_by_kind.items()}
    for o in obs:
        kind = o["part_type"]
        if kind not in out or o["product_id"] not in pid_model:
            continue
        key = index[kind].get(pid_model[o["product_id"]][1])
        if key is None:
            continue
        slot = {"positive": 0, "negative": 1, "mixed": 2}[o["direction"]]
        out[kind][key][o["aspect_code"]][slot] += 1
    return out


def q_value(p, n, k=K_SMOOTH):
    return (p + k * 0.5) / (p + n + k)


def cond_value(cond, specs):
    """충족 1 / 미충족 0 / 정보 없음 0.5 (기획 3.4절). 범위 조건은 벗어난 만큼 연속으로 깎는다."""
    if cond.get("type") == "range":
        v = specs.get(cond["key"])
        if v is None:
            return 0.5, "Pending"
        gap = max(cond["lo"] - v, v - cond["hi"], 0.0)
        return max(0.0, 1.0 - cond["pen"] * (gap / cond["step"])), ("Pass" if gap == 0 else "Fail")
    verdict, _ = spec_rules.evaluate({k: cond[k] for k in ("key", "op", "value")}, specs)
    return {"Pass": 1.0, "Pending": 0.5, "Fail": 0.0}[verdict], verdict


def normalize_column(col, mode):
    """후보 풀 안에서 한 축의 값을 0~1로 늘린다. 값이 모두 같으면 0.5(변별 없음).
    minmax: (x - 최소) / (최대 - 최소).  rank: 순위 백분위(동순위는 평균)."""
    n = len(col)
    if n < 2 or float(col.max() - col.min()) < 1e-12:
        return np.full(n, 0.5)
    if mode == "minmax":
        return (col - col.min()) / (col.max() - col.min())
    less = np.array([(col < x).sum() + ((col == x).sum() - 1) / 2 for x in col])
    return less / (n - 1)


class Setup:
    """요청 하나에 대해 후보별 축 값을 한 번 계산해 둔다. 가중치만 바꾸는 실험은 행렬 곱만 다시 하면 된다."""

    def __init__(self, persona, cands, specs, reviews, *, boost_scale=1.0, k=K_SMOOTH, budget_scale=1.0, mult=EMPHASIS_MULT, norm="none",
                 review_min_obs=0, no_review_penalty=0.0):
        self.p, self.kind = persona, persona["kind"]
        self.mult = mult
        self.spec_cond_axes = [a for a, cs in (persona.get("spec") or {}).items() if any(c["w"] >= 2 for c in cs)]
        self.axes = list(BASE_WEIGHTS[self.kind])
        budget = persona.get("budget")
        budget = budget * budget_scale if budget else None
        lo, hi = (persona.get("tier") or (0, budget))
        hi = hi if hi is not None else max(c.price for c in cands)
        alpha = {a: 1.0 for a in ASPECTS[self.kind]}
        for a, b in (persona.get("boost") or {}).items():
            alpha[a] += b * boost_scale
        tot = sum(alpha.values())
        self.rows = []
        for c in cands:
            sp = specs[c.product_key]
            if budget and c.price > budget:
                continue
            if persona.get("tier") and c.price < lo:
                continue
            pend, fail = 0, False
            for h in persona.get("hard", []):
                _, verdict = cond_value(h, sp)
                fail |= verdict == "Fail"
                pend += verdict == "Pending"
            if fail:
                continue
            n_obs = review_count(reviews, self.kind, c.product_key)
            if n_obs < review_min_obs:
                continue
            pend_extra = no_review_penalty if n_obs == 0 else 0.0
            if EVIDENCE_LAMBDA:
                pend_extra += EVIDENCE_LAMBDA * max(0.0, 1 - n_obs / EVIDENCE_N0)
            vals = {}
            for axis in self.axes:
                if axis in NON_SPEC:
                    continue
                conds = (persona.get("spec") or {}).get(axis, [])
                if not conds:
                    vals[axis] = 0.5
                    continue
                num = den = 0.0
                for cd in conds:
                    v, _ = cond_value(cd, sp)
                    num += cd["w"] * v
                    den += cd["w"]
                vals[axis] = num / den
            rev = reviews.get(c.product_key, {})
            vals["리뷰"] = sum(alpha[a] / tot * q_value(rev.get(a, [0, 0, 0])[0], rev.get(a, [0, 0, 0])[1], k) for a in alpha)
            span = (hi - lo) or 1
            vals["가격"] = max(0.0, min(1.0, 1 - (c.price - lo) / span))
            vals["브랜드"] = 1.0 if c.brand in persona.get("brand_like", ()) else 0.5
            vals["AS"] = 0.5   # 무상 AS 데이터는 아직 없다(기획 3.7절) — 모두 같은 값이라 순위에 영향 없음
            self.rows.append((c, vals, 0.20 * pend + pend_extra, n_obs))
        order = sorted(range(len(self.rows)), key=lambda i: (self.rows[i][0].price, self.rows[i][0].product_key))
        tb = np.zeros(len(self.rows))
        for rank, i in enumerate(order):
            tb[i] = rank
        self.tb = tb * 1e-9                                  # 동점이면 싼 쪽 → product_key 순
        self.V = np.array([[v[a] for a in self.axes] for _, v, _, _ in self.rows])
        self.V_raw = self.V.copy()
        if norm != "none" and len(self.rows):
            self.V = np.apply_along_axis(lambda col: normalize_column(col, norm), 0, self.V)
        self.pen = np.array([pn for _, _, pn, _ in self.rows])
        self.nobs = np.array([no for _, _, _, no in self.rows])

    def base_weights(self):
        w = dict(BASE_WEIGHTS[self.kind])
        for axis in self.p.get("emphasis", []):
            w[axis] *= self.mult
        for axis in self.spec_cond_axes:
            w[axis] *= SPEC_COND_MULT
        s = sum(w.values())
        out = {a: v / s for a, v in w.items()}
        assert abs(sum(out.values()) - 1) < 1e-9
        return out

    def vec(self, w):
        return np.array([w[a] for a in self.axes])

    def scores(self, W):
        """W: (T, A) 가중치 행렬 → (T, n) 후보 점수."""
        return W @ self.V.T - self.pen - self.tb

    def top1(self, w):
        return int(np.argmax(self.scores(self.vec(w)[None, :])[0]))

    def name(self, i):
        return self.rows[i][0].name


def normalize(w):
    s = sum(w.values())
    return {a: v / s for a, v in w.items()}


def with_review_weight(setup, r):
    w = setup.base_weights()
    others = {a: v for a, v in w.items() if a != "리뷰"}
    s = sum(others.values())
    out = {a: v * (1 - r) / s for a, v in others.items()}
    out["리뷰"] = r
    return out


def pct(x):
    return f"{x:.0%}"


REVIEW_GRID = [round(i * 0.05, 2) for i in range(0, 13)]


def analyze(persona, cands, specs, reviews, trials, rng, norm="none", **skw):
    """요청 하나의 모든 민감도 지표를 계산한다."""
    kind = persona["kind"]
    S = Setup(persona, cands, specs, reviews, norm=norm, **skw)
    n = len(S.rows)
    w0 = S.base_weights()
    v0 = S.vec(w0)
    base_scores = S.scores(v0[None, :])[0]
    order = np.argsort(-base_scores)
    base1 = int(order[0])
    base3 = set(int(i) for i in order[:3])
    gap = float(base_scores[order[0]] - base_scores[order[1]]) if n > 1 else float("nan")
    res = dict(n=n, base1=S.name(base1), gap=gap, order=[int(i) for i in order[:5]], ranked=[(S.rows[i][0], float(base_scores[i])) for i in order[:3]], S=S, w0=w0)
    rv = S.V_raw[:, S.axes.index("리뷰")]
    res["range"] = float(base_scores.max() - base_scores.min()) or 1.0
    res["review_spread"] = float(rv.max() - rv.min())
    price = np.array([c.price for c, _, _, _ in S.rows])
    res["price_pct"] = float((price < price[base1]).sum() / max(n - 1, 1))
    res["review_pct"] = float((rv < rv[base1]).sum() / max(n - 1, 1))
    res["base1_idx"] = base1
    res["top1_nobs"] = int(S.nobs[base1])
    res["top1_price"] = S.rows[base1][0].price

    # 무작위 흔들기
    for delta in (0.2, 0.5):
        W = v0[None, :] * rng.uniform(1 - delta, 1 + delta, (trials, len(v0)))
        W = W / W.sum(axis=1, keepdims=True)
        sc = S.scores(W)
        res[f"keep{int(delta * 100)}"] = float((sc.argmax(axis=1) == base1).mean())
        if delta == 0.2:
            t3 = np.argsort(-sc, axis=1)[:, :3]
            res["jac20"] = float(np.mean([len(base3 & set(row)) / len(base3 | set(row)) for row in t3.tolist()]))

    # 한 축 그룹만 흔들기
    flips = {}
    for group in ("스펙", "리뷰", "가격", "브랜드"):
        hit = []
        for f in (0.5, 0.75, 1.25, 1.5, 2.0):
            w = dict(w0)
            for a in w:
                if (group == "스펙" and a not in NON_SPEC) or a == group:
                    w[a] *= f
            if S.top1(normalize(w)) != base1:
                hit.append(f)
        flips[group] = hit
    res["flips"] = flips

    # 리뷰 가중치 스윕
    winners = {r: S.top1(with_review_weight(S, r)) for r in REVIEW_GRID}
    r0 = w0["리뷰"]
    i0 = REVIEW_GRID.index(min(REVIEW_GRID, key=lambda g: abs(g - r0)))
    lo = hi = i0
    while lo > 0 and winners[REVIEW_GRID[lo - 1]] == winners[REVIEW_GRID[i0]]:
        lo -= 1
    while hi < len(REVIEW_GRID) - 1 and winners[REVIEW_GRID[hi + 1]] == winners[REVIEW_GRID[i0]]:
        hi += 1
    res["review_range"] = (REVIEW_GRID[lo], REVIEW_GRID[hi])
    res["review_r0"] = r0
    res["review_off_changes"] = winners[0.0] != base1
    res["review_mid_stable"] = all(winners[r] == base1 for r in REVIEW_GRID if 0.2 <= r <= 0.4)
    res["review_winners"] = {r: S.name(i) for r, i in winners.items()}

    # 강조 배수 · 속성 가산 · k · 예산
    def win_for(**kw):
        s2 = Setup(persona, cands, specs, reviews, norm=norm, **{**skw, **kw})
        return s2.name(s2.top1(s2.base_weights())) if s2.rows else "후보 0건"

    res["mult_win"] = {m: win_for(mult=m) for m in (1.0, 1.25, 1.5, 2.0, 3.0)} if persona.get("emphasis") else {}
    res["boost_win"] = {b: win_for(boost_scale=b) for b in (0, 0.5, 1, 1.5)} if persona.get("boost") else {}
    res["k_win"] = {k: win_for(k=k) for k in (1, 2, 4, 8, 16)}
    res["budget_win"] = {bs: win_for(budget_scale=bs) for bs in (0.8, 0.9, 1.0, 1.1, 1.2)} if persona.get("budget") else {}
    return res


# ───────────────────────── 요청 자동 생성 ─────────────────────────
def _round_budget(v, unit):
    return max(unit, int(round(v / unit)) * unit)


def _budget_options(cands, unit):
    prices = sorted(c.price for c in cands)
    qs = []
    for q in (0.2, 0.4, 0.6, 0.8):
        qs.append((f"가격 하위 {int(q * 100)}%", _round_budget(prices[int(q * (len(prices) - 1))], unit)))
    qs.append(("예산 제한 없음", None))
    return qs


def build_options(kind, cands):
    """품목별 조건 선택지. 각 선택지 = (이름, 스펙 조건 {축: [조건]}, 하드 조건 [조건], 속성 가산 {속성: 가산})."""
    if kind == "keyboard":
        return {
            "용도": [("용도 없음", {}, [], {}),
                    ("게임", {"스위치·소음": [C("rapid_trigger", "equals", True), C("switch_magnetic", "equals", True, 1)]}, [], {}),
                    ("조용(사무·야간)", {"스위치·소음": [C("clicky", "equals", False)]}, [], {"typing_noise": 3})],
            "배열": [("배열 상관없음", {}, [], {}),
                    ("풀배열", {"배열·크기": [RANGE("kb_length_mm", 420, 520, step=20)]}, [], {}),
                    ("텐키리스", {"배열·크기": [RANGE("kb_length_mm", 340, 420, step=20)]}, [], {}),
                    ("컴팩트", {"배열·크기": [RANGE("kb_length_mm", 0, 360, step=20)]}, [], {})],
            "연결": [("연결 상관없음", {}, [], {}),
                    ("무선", {"연결": [C("connectivity_wireless", "equals", True)]}, [], {}),
                    ("블루투스", {"연결": [C("connectivity_bluetooth", "equals", True)]}, [], {})],
        }, 5000
    if kind == "mouse":
        return {
            "손 크기": [("손 크기 말 안 함", {}, [], {}),
                      ("손 작음", {"손 맞춤": [RANGE("length_mm", 107, 124)]}, [], {"ergonomics": 1}),
                      ("손 보통", {"손 맞춤": [RANGE("length_mm", 116, 132)]}, [], {"ergonomics": 1}),
                      ("손 큼", {"손 맞춤": [RANGE("length_mm", 127, 146)]}, [], {"ergonomics": 1})],
            "용도": [("용도 없음", {}, [], {}),
                    ("게임(가볍고 고폴링)", {"손 맞춤": [C("weight_g", "max", 80, 1)], "기능": [C("polling_hz_max", "min", 1000)]}, [], {"tracking_input": 2}),
                    ("조용·편안", {"기능": [C("switch_click_raw", "contains_any", ["Quiet", "Silent", "무소음", "저소음"], 1)]}, [], {"ergonomics": 3})],
            "연결": [("연결 상관없음", {}, [], {}),
                    ("무선", {"연결": [C("connectivity_wireless", "equals", True)]}, [], {})],
        }, 5000
    if kind == "monitor":
        return {
            "해상도": [("해상도 상관없음", {}, [], {}),
                      ("QHD", {}, [C("resolution_class", "member_of", ["QHD"])], {}),
                      ("4K", {}, [C("resolution_class", "member_of", ["UHD"])], {})],
            "주사율": [("주사율 상관없음", {}, [], {}),
                      ("144Hz 이상", {"움직임": [C("refresh_hz", "min", 144)]}, [C("refresh_hz", "min", 144)], {"motion_response": 2}),
                      ("240Hz 이상", {"움직임": [C("refresh_hz", "min", 240)]}, [C("refresh_hz", "min", 240)], {"motion_response": 2})],
            "패널": [("패널 상관없음", {}, [], {}),
                    ("IPS", {"화질 사양": [C("panel_raw", "contains_any", ["IPS"])]}, [], {"image_quality": 2}),
                    ("OLED", {"화질 사양": [C("panel_raw", "contains_any", ["OLED"])]}, [], {"image_quality": 2})],
            "크기": [("크기 상관없음", {}, [], {}),
                    ("24~27인치", {"화면": [RANGE("screen_size_inch", 24, 27, step=2, pen=0.5)]}, [], {}),
                    ("27~32인치", {"화면": [RANGE("screen_size_inch", 27, 32, step=2, pen=0.5)]}, [], {})],
        }, 10000
    return {
        "형태": [("형태 상관없음", {}, [], {}),
               ("사운드바", {"형태·크기": [C("speaker_form_raw", "contains_any", ["사운드바"])]}, [], {}),
               ("북셸프", {"형태·크기": [C("speaker_form_raw", "contains_any", ["북셸프"])]}, [], {}),
               ("새틀라이트", {"형태·크기": [C("speaker_form_raw", "contains_any", ["새틀라이트"])]}, [], {})],
        "채널": [("채널 상관없음", {}, [], {}),
               ("2.1 채널(저음)", {"출력·채널": [C("channels", "min", 2.1)]}, [], {"sound_quality": 2})],
        "연결·전원": [("연결 상관없음", {}, [], {}),
                   ("블루투스", {"연결·전원": [C("connectivity_bluetooth", "equals", True)]}, [], {}),
                   ("USB 전원", {"연결·전원": [C("power_source_raw", "contains_any", ["USB"])]}, [], {})],
    }, 5000


def generate_personas(kind, cands, specs, reviews, n_target, rng, min_pool=3):
    """선택지의 모든 조합(예산 5단계 × 강조 4가지 포함)을 섞은 뒤, 후보가 min_pool개 이상 남는 것만 n_target개까지 채운다."""
    import itertools
    opts, unit = build_options(kind, cands)
    budgets = _budget_options(cands, unit)
    dims = list(opts)
    combos = list(itertools.product(*[opts[d] for d in dims], budgets, ("없음", "리뷰", "가격", "스펙")))
    rng.shuffle(combos)
    out, skipped = [], 0
    for combo in combos:
        *picked, (bname, budget), emph = combo
        spec, hard, boost = {}, [], {}
        for _, sp, hd, bo in picked:
            for axis, conds in sp.items():
                spec.setdefault(axis, []).extend(conds)
            hard += hd
            for a, v in bo.items():
                boost[a] = boost.get(a, 0) + v
        spec_axes = [a for a in spec]
        emphasis = {"없음": [], "리뷰": ["리뷰"], "가격": ["가격"], "스펙": spec_axes}[emph]
        if emph == "스펙" and not spec_axes:
            emph_label = "없음"
        else:
            emph_label = emph
        if emph == "리뷰" and not boost:   # 느낌 표현으로 리뷰를 강조한 경우: 속성 하나를 가산
            boost = {rng.choice(ASPECTS[kind]): 3}
        persona = dict(id=f"G-{kind[:2].upper()}{len(out) + 1:03d}", kind=kind, budget=budget, emphasis=emphasis if emph_label != "없음" else [],
                       spec=spec, hard=hard, boost=boost,
                       label=" · ".join([p[0] for p in picked] + [bname, f"강조:{emph_label}"]),
                       tags={**{d: p[0] for d, p in zip(dims, picked)}, "예산": bname, "강조": emph_label})
        S = Setup(persona, cands, specs, reviews)
        if len(S.rows) < min_pool:
            skipped += 1
            continue
        out.append(persona)
        if len(out) >= n_target:
            break
    return out, skipped, len(combos)


# ───────────────────────── 리포트 ─────────────────────────
def review_count(reviews, kind, key):
    rev = reviews.get(key, {})
    return sum(rev.get(a, [0, 0, 0])[0] + rev.get(a, [0, 0, 0])[1] for a in ASPECTS[kind])


def diagnose_close(persona, res, reviews):
    """1위와 2위의 점수 차를 축별 기여로 쪼개 접전의 원인을 분류한다."""
    S, w0 = res["S"], res["w0"]
    i, j = res["order"][0], res["order"][1]
    contrib = {a: w0[a] * (S.V[i, k] - S.V[j, k]) for k, a in enumerate(S.axes)}
    pen = float(S.pen[j] - S.pen[i])                       # Pending 감점 차이(2위가 더 깎였으면 1위에 유리)
    pos = {a: v for a, v in contrib.items() if v > 1e-9}
    neg = {a: v for a, v in contrib.items() if v < -1e-9}
    if not pos and not neg and abs(pen) < 1e-9:
        cause, pair = "축 값이 전부 같음(동점)", ""
    elif pos and neg:
        a_pos, a_neg = max(pos, key=pos.get), min(neg, key=neg.get)
        cause, pair = "축끼리 상쇄", f"{a_pos}(1위 우세) ↔ {a_neg}(2위 우세)"
    else:
        only = max({**pos, **{a: -v for a, v in neg.items()}}.items(), key=lambda t: abs(t[1]))[0] if (pos or neg) else "Pending 감점"
        cause, pair = "한 축의 근소한 차이", only
    ci, cj = S.rows[i][0], S.rows[j][0]
    ni, nj = review_count(reviews, persona["kind"], ci.product_key), review_count(reviews, persona["kind"], cj.product_key)
    return dict(cause=cause, pair=pair, no_rev_both=(ni == 0 and nj == 0), no_rev_one=((ni == 0) != (nj == 0)),
                top1=ci.name, top2=cj.name, price1=ci.price, price2=cj.price, gap=res["gap"],
                no_spec_cond=not any(persona.get("spec", {}).values()))


def summarize(results):
    keep20 = np.array([r["keep20"] for r in results])
    keep50 = np.array([r["keep50"] for r in results])
    return dict(
        n=len(results), mean20=keep20.mean(), median20=float(np.median(keep20)), p10_20=float(np.percentile(keep20, 10)),
        mean50=keep50.mean(), ge90=float((keep20 >= 0.9).mean()), jac=float(np.mean([r["jac20"] for r in results])),
        close=float(np.mean([r["gap"] < 0.01 for r in results])), pool=int(np.median([r["n"] for r in results])),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1000, help="요청마다 가중치를 무작위로 흔드는 횟수")
    ap.add_argument("--per-kind", type=int, default=250, help="품목마다 자동 생성할 요청 수")
    ap.add_argument("--seed", type=int, default=20261005)
    ap.add_argument("--no-review-penalty", type=float, default=0.05, help="가중치 격자 탐색(11장)에서 리뷰 0건 상품에 줄 감점")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "peripheral_sensitivity"))
    ap.add_argument("--spec-cond-mult", type=float, default=2.0, help="조건 스펙 가중(기획 3.3절). 1이면 적용 전")
    ap.add_argument("--evidence-lambda", type=float, default=0.0, help="근거 부족 감점 λ(0이면 적용 안 함)")
    ap.add_argument("--evidence-n0", type=int, default=5, help="근거 부족 감점이 사라지는 리뷰 관측 수")
    args = ap.parse_args()
    global SPEC_COND_MULT, EVIDENCE_LAMBDA, EVIDENCE_N0
    SPEC_COND_MULT = args.spec_cond_mult
    EVIDENCE_LAMBDA, EVIDENCE_N0 = args.evidence_lambda, args.evidence_n0
    SJ = {"spec_cond_mult": args.spec_cond_mult, "evidence_lambda": args.evidence_lambda, "conc": {}, "cells": {}}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pyrng = random.Random(args.seed)
    nprng = np.random.default_rng(args.seed)

    cands_by_kind = load_peripheral_candidates_from_csv(ROOT / "data" / "peripherals", filename_template="{kind}_processed.csv")
    specs = {c.product_key: derive(k, c) for k, v in cands_by_kind.items() for c in v}
    reviews_all = load_reviews(cands_by_kind)
    kinds = list(cands_by_kind)

    L: list[str] = []
    P = L.append
    P("# 주변기기 추천 점수식 민감도 시뮬레이션 결과\n")
    P(f"- 시드 {args.seed}. 점수식은 기획서 3~4장(잠정 가중치)을 그대로 쓴다. 요청마다 가중치를 {args.trials}회 무작위로 흔든다.")
    P("- 리뷰는 실제 리뷰 번들(A)의 품질 차원 5개 속성만 쓴다. 혼합(mixed) 관측은 Q 계산에 넣지 않는다. 성향 차원은 다루지 않는다.")
    P("- 무상 AS 축은 데이터가 없어 모두 0.5라 순위에 영향이 없다.")
    P("- 요청은 두 묶음이다. **자동 생성 요청**(품목마다 조건 조합을 섞어 뽑음)과 **대표 요청 20개**(사람이 손으로 정함).\n")

    # 0. 데이터 커버리지
    P("## 0. 리뷰 데이터 커버리지\n")
    P("| 품목 | 카탈로그 상품 | 리뷰 있는 상품 | 상품당 관측(중앙값) | 관측 0건 비율 |")
    P("|---|---:|---:|---:|---:|")
    for kind, v in cands_by_kind.items():
        n_with = [sum(x[0] + x[1] for a, x in reviews_all[kind].get(c.product_key, {}).items() if a in ASPECTS[kind]) for c in v]
        have = [n for n in n_with if n > 0]
        P(f"| {kind} | {len(v)} | {len(have)} | {statistics.median(have) if have else 0} | {1 - len(have) / len(v):.0%} |")
    P("")

    # 자동 생성 요청 분석
    gen_results = {}
    gen_info = {}
    for kind in kinds:
        personas, skipped, total = generate_personas(kind, cands_by_kind[kind], specs, reviews_all[kind], args.per_kind, pyrng)
        gen_info[kind] = (len(personas), skipped, total)
        gen_results[kind] = [(p, analyze(p, cands_by_kind[kind], specs, reviews_all[kind], args.trials, nprng)) for p in personas]
        print(f"{kind}: 생성 {len(personas)}개 (후보 3개 미만으로 제외 {skipped}, 전체 조합 {total})")

    P("## 1. 자동 생성 요청 — 구성\n")
    P("조건 선택지(용도·배열·연결·손 크기·해상도 등) × 예산 5단계(카탈로그 가격 하위 20/40/60/80% 지점, 제한 없음) × 강조 4가지(없음·리뷰·가격·스펙)의 모든 조합을 섞어서, 하드 필터와 예산을 거쳐 후보가 3개 이상 남는 요청만 뽑았다.\n")
    P("| 품목 | 생성한 요청 | 전체 조합 수 | 후보 3개 미만이라 건너뜀 | 요청당 남는 후보(중앙값) |")
    P("|---|---:|---:|---:|---:|")
    summ = {k: summarize([r for _, r in gen_results[k]]) for k in kinds}
    for k in kinds:
        n, sk, tot = gen_info[k]
        P(f"| {k} | {n} | {tot} | {sk} | {summ[k]['pool']} |")
    all_res = [r for k in kinds for _, r in gen_results[k]]
    S_all = summarize(all_res)
    P(f"| **합계** | **{S_all['n']}** | | | |\n")

    P("## 2. 가중치를 흔들어도 1위가 유지되는가\n")
    P("가중치를 ±20% / ±50% 범위에서 무작위로 흔든 뒤 다시 합 1로 맞춰 1위를 비교한 비율을 요청마다 구하고, 요청 전체에서 평균·분포를 냈다. 100%에 가까울수록 가중치에 둔감하다.\n")
    P("| 품목 | 평균 유지율 ±20% | 중앙값 | 하위 10% 지점 | 유지율 90% 이상인 요청 | 평균 유지율 ±50% | 상위3 겹침 ±20% | 1·2위 점수 차 0.01 미만(접전) |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in kinds:
        s = summ[k]
        P(f"| {k} | {pct(s['mean20'])} | {pct(s['median20'])} | {pct(s['p10_20'])} | {pct(s['ge90'])} | {pct(s['mean50'])} | {s['jac']:.2f} | {pct(s['close'])} |")
    P(f"| **전체** | **{pct(S_all['mean20'])}** | {pct(S_all['median20'])} | {pct(S_all['p10_20'])} | {pct(S_all['ge90'])} | **{pct(S_all['mean50'])}** | {S_all['jac']:.2f} | {pct(S_all['close'])} |\n")
    P("유지율 분포(±20%):\n")
    P("| 품목 | 99% 이상 | 95~99% | 90~95% | 80~90% | 80% 미만 |")
    P("|---|---:|---:|---:|---:|---:|")
    bins = [(0.99, 9), (0.95, 0.99), (0.90, 0.95), (0.80, 0.90), (-1, 0.80)]
    for k in kinds + ["전체"]:
        arr = np.array([r["keep20"] for r in (all_res if k == "전체" else [r for _, r in gen_results[k]])])
        P(f"| {k} | " + " | ".join(pct(float(((arr >= lo) & (arr < hi if hi < 9 else arr <= 1.0)).mean())) for lo, hi in bins) + " |")
    P("")

    P("## 3. 리뷰 가중치\n")
    P("현재 엔진은 리뷰 가중치가 0이다. 기획서대로 켜면 순위가 달라지는지, 리뷰 가중치를 얼마나 움직여도 1위가 같은지 본다.\n")
    P("| 품목 | 리뷰를 켜면(0 → 기준값) 1위가 바뀌는 요청 | 리뷰 가중치 0.20~0.40 구간에서 1위 불변인 요청 |")
    P("|---|---:|---:|")
    for k in kinds + ["전체"]:
        rs = all_res if k == "전체" else [r for _, r in gen_results[k]]
        P(f"| {k} | {pct(np.mean([r['review_off_changes'] for r in rs]))} | {pct(np.mean([r['review_mid_stable'] for r in rs]))} |")
    P("")

    P("## 4. 한 축만 흔들었을 때 1위가 바뀌는 요청의 비율\n")
    P("스펙(모든 스펙 기준 합)·리뷰·가격·브랜드 가중치를 한 그룹씩 바꿔 봤다. '작게'는 ×0.75~×1.25, '크게'는 ×0.5~×2.0 에서 한 번이라도 1위가 바뀐 요청의 비율이다.\n")
    P("| 품목 | 스펙 작게 | 스펙 크게 | 리뷰 작게 | 리뷰 크게 | 가격 작게 | 가격 크게 | 브랜드 크게 |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|")
    mild = lambda fl: any(0.75 <= f <= 1.25 for f in fl)
    for k in kinds + ["전체"]:
        rs = all_res if k == "전체" else [r for _, r in gen_results[k]]
        cells = []
        for g in ("스펙", "리뷰", "가격"):
            cells += [pct(np.mean([mild(r["flips"][g]) for r in rs])), pct(np.mean([bool(r["flips"][g]) for r in rs]))]
        cells.append(pct(np.mean([bool(r["flips"]["브랜드"]) for r in rs])))
        P(f"| {k} | " + " | ".join(cells) + " |")
    P("")

    P("## 5. 그 밖의 설정을 바꿨을 때 1위가 바뀌는 요청의 비율\n")
    P("강조 배수(1.0~3.0)는 강조한 축이 있는 요청, 속성 가산(0~1.5배)은 속성 가산이 있는 요청, 예산(±20%)은 예산이 있는 요청 중의 비율이다.\n")
    P("| 품목 | 강조 배수 | 속성 가산 | 평활 k(1~16) | 예산 ±20% |")
    P("|---|---:|---:|---:|---:|")
    chg = lambda d: len(set(d.values())) > 1
    for k in kinds + ["전체"]:
        rs = all_res if k == "전체" else [r for _, r in gen_results[k]]
        cells = []
        for key in ("mult_win", "boost_win", "k_win", "budget_win"):
            sub = [r for r in rs if r[key]]
            cells.append(pct(np.mean([chg(r[key]) for r in sub])) if sub else "—")
        P(f"| {k} | " + " | ".join(cells) + " |")
    P("")

    P("## 6. 어떤 조건에서 불안정한가\n")
    P("조건별로 묶은 평균 1위 유지율(±20%)이다. 낮을수록 그 조건의 요청이 가중치에 예민하다.\n")
    for k in kinds:
        P(f"### {k}\n")
        tag_keys = list(gen_results[k][0][0]["tags"])
        for tk in tag_keys:
            groups = defaultdict(list)
            for p, r in gen_results[k]:
                groups[p["tags"][tk]].append(r["keep20"])
            P(f"- **{tk}**: " + " / ".join(f"{name} {pct(np.mean(v))}(n={len(v)})" for name, v in sorted(groups.items())))
        P("")

    P("## 7. 가장 불안정한 요청 (품목별 하위 8개)\n")
    for k in kinds:
        P(f"**{k}**\n")
        P("| 요청 | 후보 수 | 기준 1위 | 1·2위 점수 차 | 유지율 ±20% | 유지율 ±50% |")
        P("|---|---:|---|---:|---:|---:|")
        for p, r in sorted(gen_results[k], key=lambda t: t[1]["keep20"])[:8]:
            P(f"| {p['label']} | {r['n']} | {r['base1']} | {r['gap']:.3f} | {pct(r['keep20'])} | {pct(r['keep50'])} |")
        P("")

    # 접전 요청 분석
    CLOSE = 0.01
    close = []
    for k in kinds:
        for p, r in gen_results[k]:
            if r["gap"] < CLOSE and len(r["order"]) > 1:
                close.append((k, p, r, diagnose_close(p, r, reviews_all[k])))
    P("## 8. 접전 요청 분석 (1·2위 점수 차 0.01 미만)\n")
    P(f"자동 생성 요청 {S_all['n']}개 중 **{len(close)}개({len(close) / S_all['n']:.0%})**가 접전이다. 1위와 2위의 점수 차를 축별 기여로 쪼개 원인을 나눴다.\n")
    P("점수 차 분포(요청 전체, 1·2위 점수 차):\n")
    P("| 품목 | 중앙값 | 하위 25% | 하위 10% | 0.001 미만 | 0.01 미만 | 0.02 미만 |")
    P("|---|---:|---:|---:|---:|---:|---:|")
    for k in kinds + ["전체"]:
        g = np.array([r["gap"] for kk in kinds for _, r in gen_results[kk] if (k == "전체" or kk == k)])
        P(f"| {k} | {np.median(g):.3f} | {np.percentile(g, 25):.3f} | {np.percentile(g, 10):.3f} | {pct(float((g < 0.001).mean()))} | {pct(float((g < 0.01).mean()))} | {pct(float((g < 0.02).mean()))} |")
    P("")
    P("### 8.1 접전의 원인\n")
    P("| 품목 | 접전 요청 | 축 값이 전부 같음(동점) | 축끼리 상쇄 | 한 축의 근소한 차이 | 1·2위 둘 다 리뷰 없음 | 한쪽만 리뷰 없음 | 스펙 조건이 아예 없는 요청 |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in kinds + ["전체"]:
        rows = [d for kk, _, _, d in close if k == "전체" or kk == k]
        n_ = max(len(rows), 1)
        cnt = Counter(d["cause"] for d in rows)
        P(f"| {k} | {len(rows)} | {pct(cnt['축 값이 전부 같음(동점)'] / n_)} | {pct(cnt['축끼리 상쇄'] / n_)} | {pct(cnt['한 축의 근소한 차이'] / n_)} | "
          f"{pct(np.mean([d['no_rev_both'] for d in rows]) if rows else 0)} | {pct(np.mean([d['no_rev_one'] for d in rows]) if rows else 0)} | {pct(np.mean([d['no_spec_cond'] for d in rows]) if rows else 0)} |")
    P("")
    P("### 8.2 상쇄가 어느 축 사이에서 일어나는가\n")
    pair_cnt = Counter(d["pair"] for _, _, _, d in close if d["cause"] == "축끼리 상쇄")
    P("| 1위가 앞선 축 ↔ 2위가 앞선 축 | 건수 |")
    P("|---|---:|")
    for pair, c in pair_cnt.most_common(8):
        P(f"| {pair} | {c} |")
    only_cnt = Counter(d["pair"] for _, _, _, d in close if d["cause"] == "한 축의 근소한 차이")
    if only_cnt:
        P("\n한 축의 근소한 차이로 갈린 경우의 축: " + ", ".join(f"{a} {c}건" for a, c in only_cnt.most_common(5)) + "\n")
    P("### 8.3 자주 붙는 접전 쌍\n")
    P("| 품목 | 1위 | 2위 | 가격(원) | 횟수 |")
    P("|---|---|---|---|---:|")
    pc = Counter((k, d["top1"], d["top2"], d["price1"], d["price2"]) for k, _, _, d in close)
    for (k, a, b, pa, pb), c in pc.most_common(10):
        P(f"| {k} | {a} | {b} | {pa:,} / {pb:,} | {c} |")
    P("")
    P("### 8.4 어떤 조건의 요청이 접전이 되기 쉬운가\n")
    P("조건별 접전 비율(해당 조건의 요청 대비)이다.\n")
    for k in kinds:
        P(f"**{k}**")
        P("")
        gs = defaultdict(lambda: [0, 0])
        for p, r in gen_results[k]:
            for tk, tv in p["tags"].items():
                gs[(tk, tv)][1] += 1
                gs[(tk, tv)][0] += r["gap"] < CLOSE
        by_tk = defaultdict(list)
        for (tk, tv), (a, b) in gs.items():
            by_tk[tk].append(f"{tv} {pct(a / b)}(n={b})")
        for tk, items in by_tk.items():
            P(f"- {tk}: " + " / ".join(sorted(items)))
        P("")
    P("### 8.5 원인별 해석\n")
    P("- **동점**: 후보들의 모든 축 값이 같아서 점수가 같고 가격 순으로 1위가 정해진 경우다. 요청 조건이 후보를 가르지 못하거나 상품 데이터가 거의 같다는 뜻이다.")
    P("- **상쇄**: 한 후보는 어떤 축에서, 다른 후보는 다른 축에서 앞서 총점이 비슷한 경우다. 정상적인 상충이므로 가중치가 바뀌면 순위가 뒤집힌다. 이때는 1위만 내놓지 말고 두 후보와 이유를 함께 보여주는 쪽이 맞다.")
    P("- **한 축의 근소한 차이**: 한 축에서 아주 조금 앞선 경우다.")
    P("- **리뷰 없음**: 둘 다 리뷰가 없으면 리뷰 축이 0.5로 같아 변별에 쓰이지 않는다. 데이터 보강이 필요한 경우다.\n")

    with (out_dir / "close_calls.csv").open("w", encoding="utf-8-sig", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(["품목", "id", "요청", "1위", "2위", "1위 가격", "2위 가격", "점수 차", "원인", "축", "둘 다 리뷰 없음", "한쪽만 리뷰 없음"])
        for k, p, r, d in close:
            wtr.writerow([k, p["id"], p["label"], d["top1"], d["top2"], d["price1"], d["price2"], f"{d['gap']:.4f}", d["cause"], d["pair"],
                          int(d["no_rev_both"]), int(d["no_rev_one"])])

    # 정규화 비교
    MODES = [("none", "정규화 없음(기존)"), ("minmax", "최소–최대 정규화"), ("rank", "순위 백분위 정규화")]
    mode_res = {"none": {k: [r for _, r in gen_results[k]] for k in kinds}}
    for mode, _ in MODES[1:]:
        mode_res[mode] = {k: [analyze(p, cands_by_kind[k], specs, reviews_all[k], args.trials, nprng, norm=mode) for p, _ in gen_results[k]] for k in kinds}
        print(f"정규화 {mode} 완료")
    REL_CLOSE = 0.05
    P("## 9. 정규화 비교\n")
    P("후보 풀(예산·하드 조건을 통과한 후보) 안에서 **축마다** 값을 0~1로 다시 늘려 점수를 계산했다. 같은 1,000개 요청, 같은 가중치, 같은 흔들기 조건이다.\n")
    P("- **최소–최대:** (값 − 최소) / (최대 − 최소). 후보 간 차이가 아주 작아도 0과 1로 벌어진다.")
    P("- **순위 백분위:** 값 대신 순위(0~1)를 쓴다. 값이 얼마나 차이 나는지는 버리고 순서만 쓴다.")
    P("- 후보 간 차이가 전혀 없는 축은 0.5로 둔다. Pending 감점(0.20)은 정규화하지 않는다.")
    P("- 정규화하면 점수 범위가 달라져서 '점수 차 0.01 미만' 기준은 비교할 수 없다. 접전은 **1·2위 점수 차가 후보 점수 범위(최고−최저)의 5% 미만**으로 다시 정의해 비교한다. 유지율은 가중치를 상대적으로 흔드는 값이라 그대로 비교된다.\n")
    P("### 9.1 안정성 비교\n")
    P("| 품목 | 방식 | 평균 유지율 ±20% | 평균 유지율 ±50% | 유지율 90% 이상 요청 | 접전(상대 5%) | 상위3 겹침 | 리뷰를 켜면 1위가 바뀜 | 리뷰 0.2~0.4에서 1위 불변 |")
    P("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in kinds + ["전체"]:
        for mode, label in MODES:
            rs = [r for kk in kinds for r in mode_res[mode][kk] if k == "전체" or kk == k]
            keep20 = np.array([r["keep20"] for r in rs])
            P(f"| {k} | {label} | {pct(keep20.mean())} | {pct(np.mean([r['keep50'] for r in rs]))} | {pct(float((keep20 >= 0.9).mean()))} | "
              f"{pct(np.mean([r['gap'] / r['range'] < REL_CLOSE for r in rs]))} | {np.mean([r['jac20'] for r in rs]):.2f} | "
              f"{pct(np.mean([r['review_off_changes'] for r in rs]))} | {pct(np.mean([r['review_mid_stable'] for r in rs]))} |")
    P("")
    P("### 9.2 정규화가 1위를 얼마나 바꾸는가\n")
    P("기존 방식의 1위와 비교해 같은 상품이 1위인 요청의 비율, 그리고 1위의 평균 위치(후보 풀 안에서 0 = 가장 싼/리뷰가 낮은, 1 = 가장 비싼/리뷰가 높은 쪽)이다.\n")
    P("| 품목 | 방식 | 기존과 1위 동일 | 1위의 가격 위치(평균) | 1위의 리뷰 위치(평균) |")
    P("|---|---|---:|---:|---:|")
    for k in kinds + ["전체"]:
        for mode, label in MODES:
            ks = kinds if k == "전체" else [k]
            same = [r["base1"] == b["base1"] for kk in ks for r, b in zip(mode_res[mode][kk], mode_res["none"][kk])]
            rs = [r for kk in ks for r in mode_res[mode][kk]]
            P(f"| {k} | {label} | {pct(np.mean(same))} | {np.mean([r['price_pct'] for r in rs]):.2f} | {np.mean([r['review_pct'] for r in rs]):.2f} |")
    P("")
    P("### 9.3 리뷰 값이 거의 안 갈리는 풀에서 정규화가 값을 부풀리는가\n")
    P("리뷰 축의 원래 값 차이(후보 중 최대 − 최소)가 0.10 미만인 요청은 리뷰가 후보를 거의 가르지 못하는 풀이다. 최소–최대 정규화는 이 작은 차이를 0과 1로 벌려 리뷰 가중치를 사실상 키운다.\n")
    P("| 품목 | 리뷰 값 차이 0.10 미만 요청 | 그중 최소–최대로 1위가 바뀐 비율 | 그 외 요청에서 1위가 바뀐 비율 |")
    P("|---|---:|---:|---:|")
    for k in kinds + ["전체"]:
        ks = kinds if k == "전체" else [k]
        rows = [(b, r) for kk in ks for r, b in zip(mode_res["minmax"][kk], mode_res["none"][kk])]
        flat = [(b["review_spread"] < 0.10, r["base1"] != b["base1"]) for b, r in rows]
        a = [c for f, c in flat if f]
        o = [c for f, c in flat if not f]
        P(f"| {k} | {pct(len(a) / len(flat))} | {pct(np.mean(a)) if a else '—'} | {pct(np.mean(o)) if o else '—'} |")
    P("")
    P("### 9.4 1위가 바뀐 예 (최소–최대, 품목별 6건)\n")
    for k in kinds:
        P(f"**{k}**\n")
        P("| 요청 | 기존 1위 (가격 / 리뷰 값) | 정규화 후 1위 (가격 / 리뷰 값) |")
        P("|---|---|---|")
        shown = 0
        for (p, _), b, r in zip(gen_results[k], mode_res["none"][k], mode_res["minmax"][k]):
            if r["base1"] == b["base1"] or shown >= 6:
                continue
            Sb, Sr = b["S"], r["S"]
            ri = Sb.axes.index("리뷰")
            cb, cr = Sb.rows[b["base1_idx"]][0], Sr.rows[r["base1_idx"]][0]
            P(f"| {p['label']} | {cb.name} ({cb.price:,} / {Sb.V_raw[b['base1_idx'], ri]:.2f}) | {cr.name} ({cr.price:,} / {Sr.V_raw[r['base1_idx'], ri]:.2f}) |")
            shown += 1
        P("")

    # 리뷰 없는 상품 처리 비교
    POLICIES = [("none", "기존(제한 없음)", {}),
                ("ex1", "리뷰 0건 제외", {"review_min_obs": 1}),
                ("ex3", "리뷰 3건 미만 제외", {"review_min_obs": 3}),
                ("ex5", "리뷰 5건 미만 제외", {"review_min_obs": 5}),
                ("pen05", "리뷰 0건 감점 0.05", {"no_review_penalty": 0.05}),
                ("pen10", "리뷰 0건 감점 0.10", {"no_review_penalty": 0.10})]
    pol_res = {"none": {k: [r for _, r in gen_results[k]] for k in kinds}}
    pol_skipped = {"none": {k: 0 for k in kinds}}
    for key, label, skw in POLICIES[1:]:
        pol_res[key], pol_skipped[key] = {}, {}
        for k in kinds:
            out, miss = [], 0
            for p, _ in gen_results[k]:
                probe = Setup(p, cands_by_kind[k], specs, reviews_all[k], **skw)
                if len(probe.rows) < 3:   # 남는 후보가 3개 미만이면 추천을 못 한다
                    out.append(None)
                    miss += 1
                else:
                    out.append(analyze(p, cands_by_kind[k], specs, reviews_all[k], args.trials, nprng, **skw))
            pol_res[key][k], pol_skipped[key][k] = out, miss
        print(f"정책 {key} 완료")

    P("## 10. 리뷰 없는 상품 처리 비교\n")
    P("기존 방식은 리뷰 관측이 없는 상품도 리뷰 값 0.5로 후보에 올린다. 이를 (1) 후보에서 빼거나 (2) 감점하면 순위·안정성이 어떻게 달라지는지 같은 1,000개 요청으로 비교했다. '리뷰 관측'은 등록된 5개 속성의 긍정+부정 관측 수의 합이다.\n")
    P("- 후보에서 빼면 남는 후보가 3개 미만인 요청은 **추천을 못 하는 요청**이 된다. 그 비율을 함께 본다.")
    P("- 안정성 지표는 정책별로 추천이 가능한 요청만으로 계산하고, 같은 요청에서의 기존 값을 옆에 둔다.\n")

    P("### 10.1 후보 풀에서 리뷰 없는 상품이 차지하는 몫\n")
    P("| 품목 | 카탈로그 상품 | 관측 1건 이상 | 3건 이상 | 5건 이상 | 기존 1위가 리뷰 0건인 요청 | 기존 1위가 3건 미만인 요청 |")
    P("|---|---:|---:|---:|---:|---:|---:|")
    for k in kinds:
        cnts = [review_count(reviews_all[k], k, c.product_key) for c in cands_by_kind[k]]
        base = pol_res["none"][k]
        P(f"| {k} | {len(cnts)} | {pct(np.mean([c >= 1 for c in cnts]))} | {pct(np.mean([c >= 3 for c in cnts]))} | {pct(np.mean([c >= 5 for c in cnts]))} | "
          f"{pct(np.mean([r['top1_nobs'] == 0 for r in base]))} | {pct(np.mean([r['top1_nobs'] < 3 for r in base]))} |")
    P("")

    P("### 10.2 정책별 비교\n")
    P("괄호 안은 같은 요청에서의 기존 방식 값이다. '추천 불가'는 후보가 3개 미만으로 남는 요청의 비율이다.\n")
    P("| 품목 | 정책 | 추천 불가 | 유지율 ±20% | 유지율 ±50% | 접전(점수 차 0.01 미만) | 기존과 1위 동일 | 1위 리뷰 관측(중앙값) | 1위 가격(기존 대비 중앙값) |")
    P("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in kinds + ["전체"]:
        ks = kinds if k == "전체" else [k]
        for key, label, _ in POLICIES:
            pairs = [(r, b) for kk in ks for r, b in zip(pol_res[key][kk], pol_res["none"][kk])]
            valid = [(r, b) for r, b in pairs if r is not None]
            miss = 1 - len(valid) / len(pairs)
            if not valid:
                P(f"| {k} | {label} | {pct(miss)} | — | — | — | — | — | — |")
                continue
            f20, f50 = np.mean([r["keep20"] for r, _ in valid]), np.mean([r["keep50"] for r, _ in valid])
            b20, b50 = np.mean([b["keep20"] for _, b in valid]), np.mean([b["keep50"] for _, b in valid])
            cl, bcl = np.mean([r["gap"] < 0.01 for r, _ in valid]), np.mean([b["gap"] < 0.01 for _, b in valid])
            same = np.mean([r["base1"] == b["base1"] for r, b in valid])
            nobs = int(np.median([r["top1_nobs"] for r, _ in valid]))
            pr = float(np.median([r["top1_price"] / b["top1_price"] for r, b in valid]))
            if key == "none":
                P(f"| {k} | {label} | 0% | {pct(f20)} | {pct(f50)} | {pct(cl)} | 100% | {nobs} | 1.00 |")
            else:
                P(f"| {k} | {label} | {pct(miss)} | {pct(f20)} ({pct(b20)}) | {pct(f50)} ({pct(b50)}) | {pct(cl)} ({pct(bcl)}) | {pct(same)} | {nobs} | {pr:.2f} |")
    P("")

    P("### 10.3 후보가 모자라 추천을 못 하게 되는 조건 (리뷰 0건 제외 기준)\n")
    P("조건별로 후보가 3개 미만이 되는 요청의 비율이다(높은 순 상위 5개).\n")
    for k in kinds:
        gs = defaultdict(lambda: [0, 0])
        for (p, _), r in zip(gen_results[k], pol_res["ex1"][k]):
            for tk, tv in p["tags"].items():
                gs[(tk, tv)][1] += 1
                gs[(tk, tv)][0] += r is None
        top = sorted(gs.items(), key=lambda t: -t[1][0] / t[1][1])[:5]
        P(f"- **{k}**: " + " / ".join(f"{tk}={tv} {pct(a / b)}(n={b})" for (tk, tv), (a, b) in top))
    P("")

    P("### 10.4 기존 1위가 리뷰 0건이었던 요청 — 제외 후 1위 (품목별 6건)\n")
    for k in kinds:
        P(f"**{k}**\n")
        P("| 요청 | 기존 1위 (가격) | 제외 후 1위 (가격 / 리뷰 관측 수) |")
        P("|---|---|---|")
        shown = 0
        for (p, _), b, r in zip(gen_results[k], pol_res["none"][k], pol_res["ex1"][k]):
            if b["top1_nobs"] != 0 or shown >= 6:
                continue
            if r is None:
                P(f"| {p['label']} | {b['base1']} ({b['top1_price']:,}) | 추천 불가(후보 3개 미만) |")
            else:
                P(f"| {p['label']} | {b['base1']} ({b['top1_price']:,}) | {r['base1']} ({r['top1_price']:,} / {r['top1_nobs']}건) |")
            shown += 1
        P("")

    # 가중치 최적 구간 탐색
    RW = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    PW = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    GRID_TRIALS = 500
    NR_PEN = args.no_review_penalty

    def grid_w(S, rw, pw):
        """리뷰 rw, 가격 pw를 기준 가중치로 두고, 나머지는 기본 가중치 비율대로 나눈 뒤 강조 배수를 적용해 합을 1로 맞춘다."""
        base = BASE_WEIGHTS[S.kind]
        rest = [a for a in base if a not in ("리뷰", "가격")]
        rest_sum = sum(base[a] for a in rest)
        w = {a: base[a] / rest_sum * (1 - rw - pw) for a in rest}
        w["리뷰"], w["가격"] = rw, pw
        for a in S.p.get("emphasis", []):
            w[a] *= S.mult
        for a in S.spec_cond_axes:
            w[a] *= SPEC_COND_MULT
        return normalize(w)

    def cell_metrics(items, wfun):
        """items: [(S, U)] 요청별 Setup과 공통 난수. 한 가중치 설정에 대한 요청 전체 지표."""
        keep, close, norev, pp_price, pp_rev = [], [], [], [], []
        for S, U, price_pct, rev_pct, emph in items:
            w = wfun(S)
            v = S.vec(w)
            sc = S.scores(v[None, :])[0]
            order = np.argsort(-sc)
            t1 = int(order[0])
            W = v[None, :] * U
            W = W / W.sum(axis=1, keepdims=True)
            keep.append(float((S.scores(W).argmax(axis=1) == t1).mean()))
            close.append(len(order) > 1 and sc[order[0]] - sc[order[1]] < 0.01)
            norev.append(S.nobs[t1] == 0)
            if "가격" in emph:
                pp_price.append(price_pct[t1])
            if "리뷰" in emph:
                pp_rev.append(rev_pct[t1])
        return dict(keep=np.mean(keep), close=np.mean(close), norev=np.mean(norev),
                    price_pos=np.mean(pp_price) if pp_price else float("nan"),
                    rev_pos=np.mean(pp_rev) if pp_rev else float("nan"))

    grid_items = {}
    for k in kinds:
        items = []
        for p, _ in gen_results[k]:
            S = Setup(p, cands_by_kind[k], specs, reviews_all[k], no_review_penalty=NR_PEN)
            n = len(S.rows)
            if n < 3:
                continue
            price = np.array([c.price for c, _, _, _ in S.rows])
            rv = S.V_raw[:, S.axes.index("리뷰")]
            price_pct = np.array([(price < x).sum() / (n - 1) for x in price])
            rev_pct = np.array([(rv < x).sum() / (n - 1) for x in rv])
            U = nprng.uniform(0.8, 1.2, (GRID_TRIALS, len(S.axes)))
            items.append((S, U, price_pct, rev_pct, p.get("emphasis", [])))
        grid_items[k] = items

    P("## 11. 가중치 최적 구간 탐색 (리뷰 × 가격)\n")
    P(f"리뷰 가중치와 가격 가중치를 격자로 바꿔 가며 같은 요청 {sum(len(v) for v in grid_items.values())}개에서 지표를 비교했다. "
      f"리뷰 없는 상품 감점 {NR_PEN}을 적용한 상태다(10장의 권장 처리). 나머지 가중치(스펙·브랜드·AS)는 기본 비율대로 남은 몫을 나누고, 요청의 강조 배수(×1.5)는 그대로 적용했다. "
      f"유지율은 요청마다 가중치를 ±20% 흔든 {GRID_TRIALS}회에서 1위가 유지되는 비율이며, 모든 격자점에서 같은 난수를 써서 격자점끼리 비교가 공정하다.\n")
    P("**'최적'을 정하는 방법에 대해.** 정답 데이터가 없어 한 지표를 최대화하는 최적점은 없다. 아래 네 가지 지표를 함께 보고, 현재 기본값보다 나빠지지 않는 범위를 '권장 구간'으로 잡았다.\n")
    P("| 지표 | 좋은 방향 | 뜻 |")
    P("|---|---|---|")
    P("| 유지율 | 높을수록 | 가중치를 흔들어도 1위가 유지 |")
    P("| 접전 | 낮을수록 | 1·2위 점수 차 0.01 미만인 요청 비율 |")
    P("| 가격 강조 요청의 1위 가격 위치 | 낮을수록 | 가격을 강조한 요청에서 1위가 후보 풀 안에서 얼마나 싼가(0 = 가장 싼) |")
    P("| 리뷰 강조 요청의 1위 리뷰 위치 | 높을수록 | 리뷰를 강조한 요청에서 1위의 리뷰 값이 후보 풀 안에서 얼마나 높은가 |")
    P("| 리뷰 없는 1위 | 낮을수록 | 1위가 리뷰 관측 0건인 요청 비율 |\n")
    DEFAULTS = {k: (BASE_WEIGHTS[k]["리뷰"], BASE_WEIGHTS[k]["가격"]) for k in kinds}
    recs = {}
    for k in kinds:
        items = grid_items[k]
        cells = {(rw, pw): cell_metrics(items, lambda S, rw=rw, pw=pw: grid_w(S, rw, pw)) for rw in RW for pw in PW}
        cur = cell_metrics(items, lambda S: S.base_weights())
        recs[k] = (cells, cur)
        P(f"### 11.{kinds.index(k) + 1} {k}  (현재 기본값: 리뷰 {DEFAULTS[k][0]:.2f}, 가격 {DEFAULTS[k][1]:.2f})\n")
        P(f"현재 기본값에서의 지표: 유지율 {pct(cur['keep'])}, 접전 {pct(cur['close'])}, 가격 강조 1위 가격 위치 {cur['price_pos']:.2f}, 리뷰 강조 1위 리뷰 위치 {cur['rev_pos']:.2f}, 리뷰 없는 1위 {pct(cur['norev'])}.\n")
        for key, title, fmt in (("keep", "유지율 (±20% 흔들기)", pct), ("close", "접전 비율", pct),
                                ("price_pos", "가격 강조 요청의 1위 가격 위치", lambda x: f"{x:.2f}"),
                                ("rev_pos", "리뷰 강조 요청의 1위 리뷰 위치", lambda x: f"{x:.2f}"),
                                ("norev", "리뷰 없는 1위 비율", pct)):
            P(f"**{title}** — 행: 리뷰 가중치, 열: 가격 가중치\n")
            P("| 리뷰＼가격 | " + " | ".join(f"{pw:.2f}" for pw in PW) + " |")
            P("|---|" + "---:|" * len(PW))
            for rw in RW:
                P(f"| {rw:.2f} | " + " | ".join(fmt(cells[(rw, pw)][key]) for pw in PW) + " |")
            P("")
        ok = [(rw, pw, m) for (rw, pw), m in cells.items()
              if m["keep"] >= cur["keep"] - 1e-9 and m["close"] <= cur["close"] + 1e-9 and m["norev"] <= cur["norev"] + 1e-9
              and (np.isnan(m["price_pos"]) or m["price_pos"] <= cur["price_pos"] + 0.03)
              and (np.isnan(m["rev_pos"]) or m["rev_pos"] >= cur["rev_pos"] - 0.03)]
        ok.sort(key=lambda t: (-t[2]["keep"], t[2]["close"]))
        P("**권장 구간 후보** (현재 기본값보다 유지율·접전·리뷰 없는 1위가 나빠지지 않고, 가격 강조 1위 가격 위치가 +0.03 이내, 리뷰 강조 1위 리뷰 위치가 −0.03 이내):\n")
        if ok:
            P("| 리뷰 | 가격 | 유지율 | 접전 | 가격 위치 | 리뷰 위치 | 리뷰 없는 1위 |")
            P("|---:|---:|---:|---:|---:|---:|---:|")
            for rw, pw, m in ok[:8]:
                P(f"| {rw:.2f} | {pw:.2f} | {pct(m['keep'])} | {pct(m['close'])} | {m['price_pos']:.2f} | {m['rev_pos']:.2f} | {pct(m['norev'])} |")
            P(f"\n해당 조건을 만족하는 격자점 {len(ok)}개 / {len(cells)}개.\n")
        else:
            P("조건을 모두 만족하는 격자점이 없다. 현재 기본값이 이 격자에서 이미 균형점에 가깝다.\n")
    # 요약: 리뷰 가중치를 올렸을 때의 비용(가격 가중치는 기본값에 가장 가까운 열)
    P("### 11.5 리뷰 가중치를 올릴 때의 득실 (가격 가중치 기본값에 가장 가까운 열)\n")
    P("| 품목 | 리뷰 가중치 | 유지율 | 접전 | 리뷰 없는 1위 | 가격 강조 1위 가격 위치 | 리뷰 강조 1위 리뷰 위치 |")
    P("|---|---:|---:|---:|---:|---:|---:|")
    for k in kinds:
        cells, _ = recs[k]
        pw_near = min(PW, key=lambda x: abs(x - DEFAULTS[k][1]))
        for rw in RW:
            m = cells[(rw, pw_near)]
            P(f"| {k} (가격 {pw_near:.2f}) | {rw:.2f} | {pct(m['keep'])} | {pct(m['close'])} | {pct(m['norev'])} | {m['price_pos']:.2f} | {m['rev_pos']:.2f} |")
    P("")

    # 1위 쏠림(다양성) 측정
    def top1_counter(items, wfun):
        c = Counter()
        for S, _, _, _, _ in items:
            sc = S.scores(S.vec(wfun(S))[None, :])[0]
            c[S.name(int(np.argmax(sc)))] += 1
        return c

    def conc(c):
        tot = sum(c.values())
        shares = np.array([v / tot for v in c.values()])
        return dict(distinct=len(c), top_share=float(shares.max()), eff=float(1 / (shares ** 2).sum()))

    P("### 11.6 1위가 몇몇 상품에 쏠리는가 (다양성)\n")
    P("리뷰 가중치를 올리면 리뷰가 많은 소수 상품이 계속 1위가 될 수 있다. 요청 전체에서 1위로 뽑힌 상품의 분포를 재서 확인했다.\n")
    P("- **서로 다른 1위 상품 수**: 요청 전체에서 1위가 된 상품의 종류. 많을수록 다양하다.")
    P("- **최다 1위 상품 점유율**: 가장 자주 1위가 된 상품이 차지하는 요청 비율. 낮을수록 다양하다.")
    P("- **유효 상품 수**: 1 / Σ(점유율²). 1위가 고르게 나뉜 정도를 '같은 비중으로 나뉜 상품 수'로 환산한 값이다. 클수록 다양하다.\n")
    DIV_REC = {"monitor": (0.40, 0.30), "speaker": (0.45, 0.30), "keyboard": (0.35, 0.25), "mouse": (0.40, 0.25)}
    for k in kinds:
        items = grid_items[k]
        n_cat = len(cands_by_kind[k])
        cells_c = {(rw, pw): conc(top1_counter(items, lambda S, rw=rw, pw=pw: grid_w(S, rw, pw))) for rw in RW for pw in PW}
        cur_c = top1_counter(items, lambda S: S.base_weights())
        cur_m = conc(cur_c)
        SJ["conc"][k] = cur_m
        P(f"**{k}** — 카탈로그 상품 {n_cat}개, 요청 {len(items)}개. 현재 기본값(리뷰 {DEFAULTS[k][0]:.2f}, 가격 {DEFAULTS[k][1]:.2f})에서 서로 다른 1위 {cur_m['distinct']}개, "
          f"최다 1위 점유율 {pct(cur_m['top_share'])}, 유효 상품 수 {cur_m['eff']:.1f}.\n")
        for key, title, fmt in (("top_share", "최다 1위 상품 점유율", pct), ("eff", "유효 상품 수", lambda x: f"{x:.1f}"), ("distinct", "서로 다른 1위 상품 수", lambda x: f"{x}")):
            P(f"{title} — 행: 리뷰 가중치, 열: 가격 가중치\n")
            P("| 리뷰＼가격 | " + " | ".join(f"{pw:.2f}" for pw in PW) + " |")
            P("|---|" + "---:|" * len(PW))
            for rw in RW:
                P(f"| {rw:.2f} | " + " | ".join(fmt(cells_c[(rw, pw)][key]) for pw in PW) + " |")
            P("")
        rw_r, pw_r = DIV_REC[k]
        rec_c = top1_counter(items, lambda S: grid_w(S, rw_r, pw_r))
        P(f"1위로 가장 자주 뽑힌 상품 5개 — 현재 기본값 vs 후보 구간(리뷰 {rw_r:.2f}, 가격 {pw_r:.2f}):\n")
        P("| 순위 | 현재 기본값 | 요청 비율 | 후보 구간 | 요청 비율 |")
        P("|---:|---|---:|---|---:|")
        a, b = cur_c.most_common(5), rec_c.most_common(5)
        tot = len(items)
        for i in range(5):
            ca = f"{a[i][0]} | {pct(a[i][1] / tot)}" if i < len(a) else " | "
            cb = f"{b[i][0]} | {pct(b[i][1] / tot)}" if i < len(b) else " | "
            P(f"| {i + 1} | {ca} | {cb} |")
        rec_m = conc(rec_c)
        P(f"\n후보 구간에서: 서로 다른 1위 {rec_m['distinct']}개, 최다 1위 점유율 {pct(rec_m['top_share'])}, 유효 상품 수 {rec_m['eff']:.1f}.\n")

    # 대표 요청 20개
    rep_results = []
    for persona in PERSONAS:
        r = analyze(persona, cands_by_kind[persona["kind"]], specs, reviews_all[persona["kind"]], args.trials, nprng)
        rep_results.append((persona, r))
    P("## 12. 대표 요청 20개 (손으로 정한 시나리오)\n")
    P("| ID | 요청 | 기준 1위 | 1·2위 점수 차 | 유지율 ±20% | 유지율 ±50% | 상위3 겹침 | 리뷰 기준값 | 1위가 안 바뀌는 리뷰 가중치 구간 | 리뷰 0이면 1위가 다른가 |")
    P("|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for p, r in rep_results:
        P(f"| {p['id']} | {p['label']} | {r['base1']} | {r['gap']:.3f} | {pct(r['keep20'])} | {pct(r['keep50'])} | {r['jac20']:.2f} | {r['review_r0']:.2f} | {r['review_range'][0]:.2f}~{r['review_range'][1]:.2f} | {'예' if r['review_off_changes'] else '아니오'} |")
    P("")
    P("한 축만 흔들었을 때 1위가 바뀌는 배수('—'은 전 구간 유지):\n")
    P("| ID | 스펙 | 리뷰 | 가격 | 브랜드 |")
    P("|---|---|---|---|---|")
    for p, r in rep_results:
        P(f"| {p['id']} | " + " | ".join((", ".join(f"×{f}" for f in r["flips"][g]) or "—") for g in ("스펙", "리뷰", "가격", "브랜드")) + " |")
    P("\n기준 상위 3개와 축별 값:\n")
    for p, r in rep_results:
        S, w0 = r["S"], r["w0"]
        P(f"**{p['id']} {p['label']}**  가중치: " + ", ".join(f"{a} {v:.2f}" for a, v in w0.items()))
        P("")
        axes = list(w0)
        P("| 순위 | 상품 | 가격 | 점수 | " + " | ".join(axes) + " |")
        P("|---:|---|---:|---:|" + "---:|" * len(axes))
        vals_by = {c.product_key: v for c, v, _, _ in S.rows}
        for i, (c, sc) in enumerate(r["ranked"], 1):
            v = vals_by[c.product_key]
            P(f"| {i} | {c.name} | {c.price:,} | {sc:.3f} | " + " | ".join(f"{v[a]:.2f}" for a in axes) + " |")
        P("")

    (out_dir / "report.md").write_text("\n".join(L), encoding="utf-8")
    with (out_dir / "generated_requests.csv").open("w", encoding="utf-8-sig", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(["id", "품목", "요청", "후보 수", "기준 1위", "1·2위 점수 차", "유지율 ±20%", "유지율 ±50%", "상위3 겹침", "리뷰 켜면 1위 바뀜", "리뷰 0.2~0.4 불변"])
        for k in kinds:
            for p, r in gen_results[k]:
                wtr.writerow([p["id"], k, p["label"], r["n"], r["base1"], f"{r['gap']:.4f}", f"{r['keep20']:.3f}", f"{r['keep50']:.3f}",
                              f"{r['jac20']:.3f}", int(r["review_off_changes"]), int(r["review_mid_stable"])])
    with (out_dir / "review_weight_sweep.csv").open("w", encoding="utf-8-sig", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(["id", "리뷰 가중치", "1위"])
        for p, r in rep_results:
            for rw, name in r["review_winners"].items():
                wtr.writerow([p["id"], rw, name])
    def jf(x):
        return float(x) if x is not None else None

    for k in kinds + ["전체"]:
        rs = all_res if k == "전체" else [r for _, r in gen_results[k]]
        sm = S_all if k == "전체" else summ[k]
        mild_ = lambda fl: any(0.75 <= f <= 1.25 for f in fl)
        SJ["cells"][k] = dict(
            n=len(rs), mean20=jf(sm["mean20"]), mean50=jf(sm["mean50"]), ge90=jf(sm["ge90"]), close=jf(sm["close"]), jac=jf(sm["jac"]),
            review_off_changes=jf(np.mean([r["review_off_changes"] for r in rs])), review_mid_stable=jf(np.mean([r["review_mid_stable"] for r in rs])),
            flip_spec_wide=jf(np.mean([bool(r["flips"]["스펙"]) for r in rs])), flip_review_wide=jf(np.mean([bool(r["flips"]["리뷰"]) for r in rs])),
            flip_price_wide=jf(np.mean([bool(r["flips"]["가격"]) for r in rs])), flip_price_mild=jf(np.mean([mild_(r["flips"]["가격"]) for r in rs])),
            flip_review_mild=jf(np.mean([mild_(r["flips"]["리뷰"]) for r in rs])), flip_spec_mild=jf(np.mean([mild_(r["flips"]["스펙"]) for r in rs])))
    for k in kinds:
        SJ["cells"][k]["top1_price_pos"] = jf(np.mean([r["price_pct"] for r in [x for _, x in gen_results[k]]]))
        SJ["cells"][k]["top1_review_pos"] = jf(np.mean([r["review_pct"] for r in [x for _, x in gen_results[k]]]))
        SJ["cells"][k]["thin_top1"] = jf(np.mean([r["top1_nobs"] < 3 for r in [x for _, x in gen_results[k]]]))
        SJ["cells"][k]["top1_names"] = [r["base1"] for _, r in gen_results[k]]
        SJ["cells"][k]["gaps"] = [float(r["gap"]) for _, r in gen_results[k]]
        SJ["cells"][k]["reco"] = {kk: (v if not isinstance(v, float) else float(v)) for kk, v in recs[k][1].items()}
    import json as _json
    (out_dir / "summary.json").write_text(_json.dumps(SJ, ensure_ascii=False), encoding="utf-8")
    print(f"완료: {out_dir / 'report.md'}")
    print(f"자동 생성 {S_all['n']}개: 평균 1위 유지율 ±20% {pct(S_all['mean20'])}, ±50% {pct(S_all['mean50'])}")


if __name__ == "__main__":
    main()

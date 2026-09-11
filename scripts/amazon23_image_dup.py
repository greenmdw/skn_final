#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이미지 재사용 축이 이 데이터로 열리는가 — 같은 사진이 다른 계정의 리뷰에 다시 나타나는가.

`scripts/amazon23_edges.py` 가 낸 `<cat>_images.tsv`(리뷰당 이미지 URL) 로 잰다.
아마존 이미지 URL 의 `/images/I/<ID>.` 가 파일 식별자다(크기 접미사 `._SL1600_` 는 뺀다).

**"다른 계정에서도 나타난다" 만 세면 틀린다 — 2026-09-11 에 실제로 틀렸다.**
Baby 에서 계정 2개+ 이미지 247건이 나왔는데, 전부 **같은 리뷰가 두 user_id 로 중복
기록된 것**이었다(타임스탬프 동일 243/247 · 평점 동일 247/247 · 본문 길이 동일 245/247).
데이터 산물이지 재사용이 아니다. 그래서 **게시 시각 차이가 1일을 넘는 쌍만** 후보로 센다.

실측 (2026-09-11):
  Baby         이미지 620,521 · 계정 2+ ID 247 → 시각 차 1일 초과 **0**  → 열리지 않는다
  Electronics  이미지 3,828,513 · 계정 2+ ID 649 → 시각 차 1일 초과 **100** (0.003%)
               최다: ID 하나가 7계정·7상품·973일에 걸쳐 등장(평점 4종) — 조작보다 공용 사진(스톡·스크린샷)
               에 가깝다. 축은 "열리기는 하나" 규모가 카드 한 줄 이상을 정당화하지 않는다

  → 인수인계 `데이터_표.md` 의 미확인 칸 "Amazon'23 사진 URL 중복 여부" 의 답: **실질적으로 없다.**
    Hollenbeck(22,911장 전부 고유)과 같은 결론이다.

사용:  uv run --with pandas python scripts/amazon23_image_dup.py data/amazon23/baby_images.tsv data/amazon23/baby_edges.tsv
"""
from __future__ import annotations

import argparse

import pandas as pd

DAY_MS = 86_400_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images_tsv")
    ap.add_argument("edges_tsv")
    ap.add_argument("--min-gap-days", type=float, default=1.0,
                    help="같은 이미지의 두 게시가 이보다 가까우면 중복 기록으로 보고 뺀다")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    d = pd.read_csv(a.images_tsv, sep="\t", dtype={"user_id": "string", "parent_asin": "string", "url": "string"})
    d["img"] = d.url.str.extract(r"/images/I/([^.]+)")[0]
    d = d.dropna(subset=["img"])
    n_img, n_ids = len(d), d.img.nunique()

    acct = d.groupby("img").user_id.nunique()
    multi = acct[acct >= 2].index
    x = d[d.img.isin(multi)]
    e = pd.read_csv(a.edges_tsv, sep="\t", dtype={"user_id": "string", "parent_asin": "string"},
                    usecols=["user_id", "parent_asin", "ts_ms", "rating", "text_len"])
    m = x.merge(e, on=["user_id", "parent_asin", "ts_ms"], how="left")
    pair = m.groupby("img").agg(
        n_acct=("user_id", "nunique"), n_prod=("parent_asin", "nunique"),
        gap_days=("ts_ms", lambda s: (s.max() - s.min()) / DAY_MS),
        n_rating=("rating", "nunique"), n_len=("text_len", "nunique"))
    dup_record = pair[pair.gap_days <= a.min_gap_days]
    real = pair[pair.gap_days > a.min_gap_days]

    print(f"이미지 {n_img:,}장 · 고유 ID {n_ids:,} · 계정 2개+ 에서 나타난 ID {len(pair):,}")
    print(f"  그중 게시 시각 차 {a.min_gap_days:g}일 이하 (같은 리뷰의 중복 기록으로 봄): {len(dup_record):,}"
          f"  — 평점 동일 {int((dup_record.n_rating == 1).sum()):,} · 본문 길이 동일 {int((dup_record.n_len == 1).sum()):,}")
    print(f"  시각 차 {a.min_gap_days:g}일 초과 (재사용 후보): {len(real):,}  ({100 * len(real) / max(n_ids, 1):.4f}% of IDs)")
    if len(real):
        print(f"\n재사용 후보 상위 {a.top} (계정 수 순)")
        print(real.sort_values(["n_acct", "gap_days"], ascending=False).head(a.top).round(1).to_string())
        top = real.sort_values("n_acct", ascending=False).index[0]
        print(f"\n확인 경로: {d[d.img == top].url.iloc[0]}")
    verdict = "열리지 않는다" if len(real) == 0 else ("규모가 작다 — 카드 한 줄 이상을 정당화하지 않는다"
                                                   if len(real) / max(n_ids, 1) < 1e-3 else "열린다")
    print(f"\n>>> 이미지 재사용 축: {verdict}")


if __name__ == "__main__":
    main()

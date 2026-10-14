#!/usr/bin/env python3
"""예시 글 정답표 점검 — 분석 결과(engine.peripheral_post_evidence)를 `data/community_examples/expectations.yaml` 과 맞춰 본다.

DB 를 **읽기만** 한다(모델 호출 없음). 분석은 먼저 `python -m src.workers.peripheral_post_analysis --once` 로 돌려 둔다.
`scripts/eval_peripheral_post_extraction.py`(손 크기·목적·상황·성향 쪽)와 짝이다 — 여기서는 평가 속성 적중률과 규칙 위반을 본다.

    python scripts/check_example_expectations.py
    python scripts/check_example_expectations.py --only A1-1,A2-1 --verbose
    python scripts/check_example_expectations.py --min-coverage 0.7        # 적중률이 이보다 낮으면 실패(종료 코드 1)

종료 코드: 규칙 위반(사용기가 아닌 글의 근거 · 조건을 숨긴 글의 조건 · 6개월 미만 글의 내구성 · 본문에 없는 문장)이 있으면 1.
적중률과 짐작 문장 의심은 보고만 한다(`--min-coverage` 를 주면 적중률도 판정한다).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import get_conn                                                  # noqa: E402
from src.engine import peripheral_post_expectations as ex                    # noqa: E402
from src.engine.peripheral_post_text import plain_text                       # noqa: E402

DEFAULT_EXPECTATIONS = ROOT / "data" / "community_examples" / "expectations.yaml"


def load_rows(conn) -> tuple[dict[str, list[dict]], dict[str, str], set[str]]:
    """예시 글의 근거 행(글 번호별), 본문, 적재된 글 번호."""
    with conn.cursor() as cur:
        cur.execute("SELECT external_id, body FROM community.post WHERE is_example AND external_id IS NOT NULL")
        bodies = {ext: body for ext, body in cur.fetchall()}
        cur.execute(
            """SELECT p.external_id, e.attribute, e.direction, e.side, e.hand_size, e.purposes, e.situations, e.sentence
               FROM engine.peripheral_post_evidence e JOIN community.post p ON p.id = e.post_id
               WHERE p.is_example AND p.external_id IS NOT NULL ORDER BY p.external_id, e.attribute, e.created_at""")
        rows = [{"post_id": r[0], "attribute": r[1], "direction": r[2], "side": r[3], "hand_size": r[4],
                 "purposes": list(r[5] or []), "situations": list(r[6] or []), "sentence": r[7]} for r in cur.fetchall()]
    return ex.group_by_post(rows), bodies, set(bodies)


def analyzed_posts(conn) -> set[str]:
    """분석이 끝난 글(대기 기록이 done)의 글 번호 — 근거가 0건이어도 "분석했는데 0건"과 "아직 안 한 것"을 가르려는 것."""
    with conn.cursor() as cur:
        cur.execute("""SELECT p.external_id FROM engine.peripheral_post_intake i JOIN community.post p ON p.id = i.post_id
                       WHERE i.status = 'done' AND p.external_id IS NOT NULL""")
        return {r[0] for r in cur.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(description="예시 글 정답표 점검(읽기 전용)")
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--only", help="쉼표로 구분한 글 번호만 비교한다")
    parser.add_argument("--min-coverage", type=float, default=None, help="평가 속성 적중률 하한(0~1). 주면 미달 시 실패")
    parser.add_argument("--verbose", action="store_true", help="글마다 맞은 것·놓친 것을 모두 보인다")
    args = parser.parse_args()

    data = ex.load_expectations(args.expectations)
    only = {s.strip() for s in args.only.split(",") if s.strip()} if args.only else None
    with get_conn() as conn:
        rows_by_post, bodies, loaded = load_rows(conn)
        done = analyzed_posts(conn)

    scope = {p for p in loaded if only is None or p in only}
    evidence = {p: r for p, r in rows_by_post.items() if p in scope}
    failures = 0

    # ① 평가 속성 적중률(분석이 끝난 글만)
    targets = {p for p in data["posts"] if p in scope and p in done}
    results = ex.check_posts(rows_by_post, data["posts"], only=targets)
    hit, total = ex.coverage(results)
    print(f"■ 평가 속성 적중률: {hit}/{total}" + (f" = {hit / total:.0%}" if total else "") +
          f"   (비교한 글 {len(results)}편 / 정답표 {len(data['posts'])}편, 분석 전 {len(set(data['posts']) - targets)}편 제외)")
    weak = sorted((r for r in results if r.misses), key=lambda r: (-len(r.misses), r.post_id))
    for r in (results if args.verbose else weak[:8]):
        if not r.misses and not args.verbose:
            continue
        miss = ", ".join(f"{a}={v}" for a, v in r.misses) or "-"
        print(f"   {r.post_id:<7} {len(r.hits)}/{r.total}  놓침: {miss}")
    if len(weak) > 8 and not args.verbose:
        print(f"   … 놓친 글 {len(weak)}편 중 8편만 표시(--verbose 로 전체)")
    if args.min_coverage is not None and total and hit / total < args.min_coverage:
        print(f"   ✗ 적중률 {hit / total:.0%} < 하한 {args.min_coverage:.0%}")
        failures += 1

    # ② 규칙 위반
    print("■ 규칙 위반")
    no_ev = [p for p in data["no_evidence"] if p in scope and p in done]
    bad = ex.check_no_evidence(evidence, no_ev)
    print(f"   사용기가 아닌 글의 근거: {'없음' if not bad else bad}  (분석 끝난 {len(no_ev)}편 확인)")
    failures += bool(bad)

    hidden = ex.check_conditions_hidden({p: r for p, r in evidence.items() if p in done})
    print(f"   조건을 숨긴 글(-4)의 조건: {'없음' if not hidden else hidden}")
    failures += bool(hidden)

    dur = ex.check_durability(evidence, data["durability_allowed"])
    print(f"   6개월 미만 글의 내구성 근거: {'없음' if not dur else dur}")
    failures += bool(dur)

    missing = ex.check_sentences_in_body(evidence, bodies, plain_text)
    print(f"   본문에 없는 근거 문장: {'없음' if not missing else missing[:3]}")
    failures += bool(missing)

    # ③ 의심(판정하지 않는다)
    spec = ex.find_speculation(evidence)
    print(f"■ 짐작·가정 문장으로 보이는 근거(사람이 확인): {len(spec)}건")
    for pid, attribute, sentence in spec[:8]:
        print(f"   {pid:<7} {attribute:<12} {sentence[:70]}")

    print("결과:", "통과" if not failures else f"실패 {failures}건")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

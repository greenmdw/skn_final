"""사용기 분석 결과를 예시 글 정답표와 맞춰 본다 — 손 크기·목적·상황·성향 쪽(`src/engine/peripheral_post_eval.py`).

DB 의 `engine.peripheral_post_evidence` 를 **읽기만** 한다(모델 호출 없음). 분석은 먼저
`python -m src.workers.peripheral_post_analysis --once` 로 돌려 둔다.

    python scripts/eval_peripheral_post_extraction.py
    python scripts/eval_peripheral_post_extraction.py --gold docs/local/예시_사용기_작성_기획.md --only A1-1,A1-2 --verbose
    python scripts/eval_peripheral_post_extraction.py --kind mouse --out /tmp/eval.md

정답표는 글쓴이가 그렇게 쓰도록 기획한 값이다. 불일치는 원문과 대조해 추출 오류인지 글이 기획과 다른지 사람이 가린다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import get_conn                                   # noqa: E402
from src.engine import peripheral_post_eval as ev              # noqa: E402
from src.engine.peripheral_rules import load_peripheral_rules, purposes, situations   # noqa: E402

DEFAULT_GOLD = ROOT / "docs" / "local" / "예시_사용기_작성_기획.md"


def load_rows(conn, post_ids: list[str]) -> dict[str, list[dict]]:
    sql = """SELECT p.external_id, e.attribute, e.direction, e.side, e.hand_size, e.purposes, e.situations, e.sentence
             FROM engine.peripheral_post_evidence e JOIN community.post p ON p.id = e.post_id
             WHERE p.external_id = ANY(%s) ORDER BY p.external_id, e.attribute, e.created_at"""
    out: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (post_ids,))
        for ext, attribute, direction, side, hand, purps, sits, sentence in cur.fetchall():
            out.setdefault(ext, []).append({
                "attribute": attribute, "direction": direction, "side": side, "hand_size": hand,
                "purposes": list(purps or []), "situations": list(sits or []), "sentence": sentence,
            })
    return out


def existing_posts(conn, post_ids: list[str]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT external_id FROM community.post WHERE external_id = ANY(%s)", (post_ids,))
        return {r[0] for r in cur.fetchall()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="정답표 Markdown")
    ap.add_argument("--only", help="글 번호 쉼표 목록(예: A1-1,A1-2). 없으면 DB 에 적재된 정답표 글 전부")
    ap.add_argument("--kind", choices=["mouse", "keyboard", "monitor", "speaker"])
    ap.add_argument("--verbose", action="store_true", help="글마다 추출된 속성·문장을 함께 낸다")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not args.gold.is_file():
        print(f"정답표 파일이 없다: {args.gold}", file=sys.stderr)
        return 2
    rules = load_peripheral_rules()
    pur = {k: {c: v["label"] for c, v in purposes(k, rules).items()} for k in ("mouse", "keyboard", "monitor", "speaker")}
    sit = {c: v["label"] for c, v in situations(rules).items()}
    gold = ev.parse_gold(args.gold.read_text(encoding="utf-8"), pur, sit)
    wanted = [g for g in gold.values() if (not args.kind or g.kind == args.kind)]
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        wanted = [g for g in wanted if g.post_id in keep]

    with get_conn() as conn:
        present = existing_posts(conn, [g.post_id for g in wanted])
        rows = load_rows(conn, [g.post_id for g in wanted if g.post_id in present])
    targets = [g for g in wanted if g.post_id in present]
    results = [ev.compare_post(g, rows.get(g.post_id, []), set(pur[g.kind])) for g in targets]
    by_id = {g.post_id: g for g in targets}

    lines: list[str] = []
    s = ev.summarize(results)
    lines += [f"# 사용기 분석 정답표 평가 — 글 {s['posts']}편 (정답표 {len(gold)}편 중 DB 에 적재된 것)", ""]
    if not results:
        lines.append("평가할 글이 없다. 적재(`db/seed_community_examples.py --apply`)와 분석(`--once`)을 먼저 한다.")
    else:
        hm = f"{s['hand_match']}/{s['hand_checked']}" if s["hand_checked"] else "-"
        lines += [
            "| 항목 | 값 |", "|---|---|",
            f"| 근거 문장 합계 / 그중 기타 | {s['evidence_total']} / {s['other_total']} |",
            f"| 근거가 하나도 없는 글 | {s['posts_without_evidence']} |",
            f"| 손 크기 일치 | {hm} |",
            f"| 목적 빠짐 / 덧붙음 | {s['purposes_missing']} / {s['purposes_extra']} |",
            f"| 다른 종류의 목적 코드가 붙은 수(예: 마우스 글의 docs) | {s['purposes_other_kind']} |",
            f"| 상황 빠짐 / 덧붙음 | {s['situations_missing']} / {s['situations_extra']} |",
            f"| 성향 쪽(일치·섞임·반대·없음) | {s['taste'].get('match', 0)} · {s['taste'].get('mixed', 0)} · "
            f"{s['taste'].get('conflict', 0)} · {s['taste'].get('missing', 0)} |",
            "", "## 글별 불일치", "",
        ]
        bad = 0
        for r in results:
            g = by_id[r.post_id]
            issues = []
            if r.evidence == 0:
                issues.append("근거 없음")
            if r.hand and r.hand[0] != r.hand[1]:
                issues.append(f"손 크기 정답 {r.hand[0]} / 추출 {r.hand[1]}")
            if r.purposes_missing:
                issues.append("목적 빠짐 " + ",".join(sorted(r.purposes_missing)))
            if r.purposes_extra:
                issues.append("목적 덧붙음 " + ",".join(sorted(r.purposes_extra)))
            if r.purposes_other_kind:
                issues.append("다른 종류의 목적 " + ",".join(sorted(r.purposes_other_kind)))
            if r.situations_missing:
                issues.append("상황 빠짐 " + ",".join(sorted(r.situations_missing)))
            if r.situations_extra:
                issues.append("상황 덧붙음 " + ",".join(sorted(r.situations_extra)))
            for attr, verdict in r.taste.items():
                if verdict != "match":
                    issues.append(f"성향 {attr}({g.taste[attr]}) {verdict}")
            if g.unmapped:
                issues.append("정답표 문구를 코드로 못 바꿈: " + ",".join(g.unmapped))
            if issues:
                bad += 1
                lines.append(f"- **{r.post_id}** ({g.author}): " + " · ".join(issues))
            if args.verbose:
                attrs = ", ".join(f"{a} {n}" for a, n in sorted(r.attributes.items()))
                lines.append(f"  - 추출 속성: {attrs or '없음'}")
        if not bad:
            lines.append("불일치 없음")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

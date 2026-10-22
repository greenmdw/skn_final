#!/usr/bin/env python3
"""사용기 분석 추출 정확도 평가 — 말뭉치 선정과 고정(`사용기분석_추출정확도_평가기획.md` 3장).

DB 를 읽기만 한다. 선정한 글의 post_id·본문 해시(content_hash)·출처·종류를 `manifest.json` 에 기록하고,
추출 프롬프트·계약 파일의 해시(동결 기록)도 함께 적는다. 평가 도중 글이 바뀌면 해시가 달라져 알 수 있다.

    python scripts/eval_extraction_corpus.py                        # 선정 + manifest 쓰기
    python scripts/eval_extraction_corpus.py --check                # 기록한 해시와 지금 글이 같은지 확인
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import get_conn                                  # noqa: E402
from src.repo import peripheral_post_source as source        # noqa: E402

OUT_DIR = ROOT / "data" / "eval_extraction"
MANIFEST = OUT_DIR / "manifest.json"

# (묶음, 종류, 글 번호, 비고). 선정 규칙: 기획 3장. 정상 사용기 30편(마우스 9·키보드 9·모니터 3·스피커 4·여러 제품 글 5),
# 사용기가 아닌 글 10편(사유별), 지시문 글 5편(예시 글에 없어 작성 필요).
A_NORMAL = {
    "mouse": ["A1-1", "A1-3", "A2-3", "A3-2", "A4-1", "A5-2", "A6-3", "A7-1", "A12-4"],
    "keyboard": ["B1-1", "B2-2", "B3-2", "B4-1", "B5-2", "B6-3", "B7-1", "B9-1", "B10-4"],
    "monitor": ["C1-1", "C3-2", "C6-4"],
    "speaker": ["D1-1", "D3-2", "D6-3", "D8-4"],
}
MULTI_PRODUCT = ["E1", "E5", "E10", "E15", "E20"]
# F 글의 정답 사유(예시_사용기_작성_기획.md 5장 F 표). 코드: question·chatter·ad·unboxing·planned·store_demo·hearsay·sale
NON_REVIEW = {
    "F1": "question", "F2": "unboxing", "F4": "ad", "F5": "chatter", "F6": "hearsay",
    "F10": "chatter", "F13": "planned", "F14": "hearsay", "F15": "store_demo", "F16": "sale",
}
INJECTION_PLACEHOLDERS = 5      # 지시문이 섞인 글은 예시 글에 없다 — 팀이 5편을 써서 적재해야 한다


def _file_sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]


def freeze_record() -> dict:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src/agent/peripheral_post_agent.py",
                                     "src/engine/peripheral_post_contract.py", "config/peripherals.yaml"],
                                    cwd=ROOT, capture_output=True, text=True).stdout.strip())
    except Exception:  # noqa: BLE001
        head, dirty = "", True
    files = ["src/agent/peripheral_post_agent.py", "src/engine/peripheral_post_contract.py",
             "src/engine/peripheral_post_text.py", "config/peripherals.yaml"]
    return {"git_head": head, "working_tree_dirty_for_frozen_files": dirty,
            "file_sha256_16": {f: _file_sha(f) for f in files}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="기록한 본문 해시와 지금 글을 비교한다")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    entries: list[dict] = []
    for kind, ids in A_NORMAL.items():
        entries += [{"post_id_ext": i, "group": "A", "kind": kind} for i in ids]
    entries += [{"post_id_ext": i, "group": "A", "kind": "multi", "multi_product": True} for i in MULTI_PRODUCT]
    entries += [{"post_id_ext": i, "group": "B", "kind": "non_review", "expected_reason": r} for i, r in NON_REVIEW.items()]

    with get_conn() as conn:
        for e in entries:
            row = conn.execute("SELECT id::text, is_example FROM community.post WHERE external_id=%s", (e["post_id_ext"],)).fetchone()
            if row is None:
                e["missing"] = True
                continue
            snap = source.load_snapshot(conn, row[0])
            post = source.load_post_input(conn, row[0])
            e.update(post_id=row[0], source="example" if row[1] else "real", content_hash=snap.content_hash if snap else None,
                     body_chars=len(post.body) if post else None, products=len(post.products) if post else None,
                     hidden_conditions=e["post_id_ext"].endswith("-4"))

    if args.check:
        old = json.loads(MANIFEST.read_text(encoding="utf-8"))
        changed = [o["post_id_ext"] for o in old["posts"]
                   if any(n["post_id_ext"] == o["post_id_ext"] and n.get("content_hash") != o.get("content_hash") for n in entries)]
        print("바뀐 글:", changed or "없음")
        return 1 if changed else 0

    missing = [e["post_id_ext"] for e in entries if e.get("missing")]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plan": "사용기분석_추출정확도_평가기획.md",
        "freeze": freeze_record(),
        "counts": {
            "normal": sum(1 for e in entries if e["group"] == "A"),
            "non_review": sum(1 for e in entries if e["group"] == "B"),
            "injection_needed": INJECTION_PLACEHOLDERS,
        },
        "gaps": [
            f"지시문이 섞인 글(C) {INJECTION_PLACEHOLDERS}편이 예시 글에 없다 — 작성·적재 필요(M12 는 그 전까지 측정 불가)",
            "본문 4,000자 근처의 긴 글이 없다(예시 글은 1,300~2,000자) — 잘림 동작(E10)은 이 말뭉치로 못 본다",
            "실제 사용자 글이 없다 — 지표는 예시 글 기준으로만 나온다(출처별 분리 보고는 실제 글이 생긴 뒤)",
        ],
        "missing_in_db": missing,
        "posts": entries,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"말뭉치 {len(entries)}편 기록 → {MANIFEST}")
    print("종류별:", {k: sum(1 for e in entries if e["kind"] == k) for k in ("mouse", "keyboard", "monitor", "speaker", "multi", "non_review")})
    if missing:
        print("DB 에 없는 글:", missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

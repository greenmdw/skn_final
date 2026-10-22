#!/usr/bin/env python3
"""담당자가 JSON 으로 낸 예시 글을 우리 글 형식(글 1편 = 마크다운 파일 1개, 머리말 + 본문)으로 풀어 쓴다.

입력 JSON 은 `{"meta": {...}, "posts": [ {id, board, author, is_example, written_at, title, products, body, ...}, ... ]}` 이다.
글마다 아래 규칙으로 파일을 만든다(만들 폴더는 `<출력 폴더>/<묶음 문자>/`, 묶음 문자는 글 번호의 앞 알파벳 — A11-1 → A, E3 → E).

- 파일 이름: JSON 의 `source_file` 이 있으면 그것, 없으면 `<글 번호>.md`.
- 수정본(`revision: edited`): 원글과 id 가 같으므로 `<출력 폴더>/revisions/` 에 둔다. 원글 적재 뒤에 `--update` 로 올린다.
- `products` 는 `brand`·`model`·`option`(있으면) 또는 `custom`·`kind`(카탈로그에 없는 제품)로 옮긴다.
- 같은 이름의 파일이 이미 있으면 덮어쓰지 않는다(`--overwrite` 로만 덮어씀).

JSON 은 글을 바꾸지 않고 형식만 옮긴다. 형식 점검은 이어서 적재 도구의 dry-run 으로 한다.

    python db/community_examples_from_json.py ~/Downloads/예시_사용기_담당5.json data/community_examples
    python db/seed_community_examples.py data/community_examples            # 점검
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


def _group(post_id: str) -> str:
    match = re.match(r"[A-Za-z]+", post_id)
    return match.group(0).upper() if match else "misc"


def _product(item: dict) -> dict:
    if str(item.get("custom") or "").strip():
        out = {"custom": str(item["custom"]).strip(), "kind": str(item.get("kind") or "").strip()}
        if item.get("option"):
            out["option"] = item["option"]
        return out
    return {"brand": item.get("brand"), "model": item.get("model"), "option": item.get("option")}


def front_matter(post: dict) -> dict:
    meta: dict = {
        "id": post["id"], "board": post["board"], "author": post["author"],
        "is_example": bool(post.get("is_example", True)),
    }
    if post.get("written_at"):
        meta["written_at"] = str(post["written_at"])
    meta["products"] = [_product(p) for p in (post.get("products") or [])]
    meta["title"] = str(post["title"]).strip()
    if post.get("tags"):
        meta["tags"] = [str(t) for t in post["tags"]]
    if post.get("images"):
        meta["images"] = [str(i) for i in post["images"]]
    return meta


def render(post: dict) -> str:
    head = yaml.safe_dump(front_matter(post), allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)
    return f"---\n{head}---\n\n{str(post['body']).strip()}\n"


def target_path(post: dict, out_root: Path) -> Path:
    name = str(post.get("source_file") or f"{post['id']}.md")
    if str(post.get("revision") or "") == "edited":
        return out_root / "revisions" / name
    return out_root / _group(str(post["id"])) / name


def convert(json_path: Path, out_root: Path, *, overwrite: bool = False) -> dict[str, list[str]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    posts = data["posts"] if isinstance(data, dict) else data
    report: dict[str, list[str]] = {"written": [], "skipped": []}
    for post in posts:
        path = target_path(post, out_root)
        if path.exists() and not overwrite:
            report["skipped"].append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(post), encoding="utf-8")
        report["written"].append(str(path))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="예시 글 JSON 을 마크다운 글 파일로 변환한다.")
    parser.add_argument("json", type=Path)
    parser.add_argument("out", type=Path, help="출력 폴더(예: data/community_examples)")
    parser.add_argument("--overwrite", action="store_true", help="이미 있는 파일도 덮어쓴다")
    args = parser.parse_args()
    report = convert(args.json, args.out, overwrite=args.overwrite)
    print(f"변환: 만든 파일 {len(report['written'])} · 건너뜀(이미 있음) {len(report['skipped'])}")
    for path in report["skipped"]:
        print(f"  건너뜀: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

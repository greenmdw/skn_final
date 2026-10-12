#!/usr/bin/env python3
"""예시 사용기 글(마크다운 + 머리말)을 community.post 에 한꺼번에 적재한다.

글 형식(예시_사용기_작성_기획.md 3장): 머리말(YAML) + 마크다운 본문. 글 한 편 = 파일 하나(`A1-1.md`).

    ---
    id: A1-1                # 필수 — 다시 적재해도 같은 글이 두 번 들어가지 않게 하는 키(community.post.external_id)
    board: review           # question | review | tip | free
    author: P06             # P01~P20 (아래 AUTHORS) — 계정이 없으면 만든다(로그인 불가 계정)
    is_example: true
    products:
      - brand: Logitech     # catalog.product.brand, model 과 글자까지 같아야 연결된다(모호하면 건너뛴다)
        model: G PRO X SUPERLIGHT 2
        option:             # 키보드 스위치 등(선택)
    title: "[4주 사용] 클로 그립으로 써본 G PRO X SUPERLIGHT 2"
    tags: [마우스, FPS]     # 선택
    ---
    본문…

사용 (기본은 점검만 한다 — 아무것도 쓰지 않는다):
    python db/seed_community_examples.py <글 폴더>                 # 점검(dry-run)
    python db/seed_community_examples.py <글 폴더> --apply         # 적재
    python db/seed_community_examples.py <글 폴더> --apply --update   # 이미 있는 글은 본문·제목·태그·제품도 갱신

멱등: 같은 id 는 두 번 들어가지 않는다(--update 가 없으면 건너뛴다). 글은 파일 이름 순서대로 1분 간격으로 과거에 게시한 것으로
적재해 목록 순서가 안정적이다. 직접 쓴(is_example: false) 글도 같은 형식으로 적재할 수 있다.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn  # noqa: E402
from src.repo.community_repo import CommunityRepo  # noqa: E402
from src.services.community_service import BOARD_TYPES, KIND_TO_TYPE, TYPE_TO_KIND  # noqa: E402

# 예시 글 작성자 20명(닉네임은 예시_사용기_작성_기획.md 4장). 로그인할 수 없는 계정(비밀번호 없음)으로 만든다.
AUTHORS = {
    "P01": "창가의클로그립", "P02": "새벽키감연구소", "P03": "큰손팜그립", "P04": "작은손사무러", "P05": "손목터널탈출",
    "P06": "랭크만돌림", "P07": "색감집착", "P08": "거실겸작업실", "P09": "기숙사2인실", "P10": "방송켜는사람",
    "P11": "밤에만게임", "P12": "장문타이피스트", "P13": "왼손잡이디자이너", "P14": "카페노마드", "P15": "차트보는사람",
    "P16": "리듬겜고인물", "P17": "침대옆영화관", "P18": "방구석작곡", "P19": "큰손개발자", "P20": "온가족PC",
}
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


def parse_file(path: Path) -> dict:
    """머리말과 본문을 읽는다. 형식이 틀리면 ValueError."""
    text = path.read_text(encoding="utf-8")
    m = _FRONT.match(text.replace("\r\n", "\n"))
    if not m:
        raise ValueError("머리말(---)이 없다")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    if not isinstance(meta, dict):
        raise ValueError("머리말 형식 오류")
    for key in ("id", "board", "author", "title"):
        if not str(meta.get(key) or "").strip():
            raise ValueError(f"머리말에 {key} 가 없다")
    if meta["board"] not in BOARD_TYPES:
        raise ValueError(f"board 는 {', '.join(BOARD_TYPES)} 중 하나여야 한다: {meta['board']}")
    if meta["author"] not in AUTHORS:
        raise ValueError(f"알 수 없는 작성자: {meta['author']}")
    if not body:
        raise ValueError("본문이 비어 있다")
    products = meta.get("products") or []
    if not isinstance(products, list):
        raise ValueError("products 는 목록이어야 한다")
    return {"id": str(meta["id"]).strip(), "board": meta["board"], "author": meta["author"], "title": str(meta["title"]).strip(),
            "is_example": bool(meta.get("is_example", False)), "tags": [str(t) for t in (meta.get("tags") or [])],
            "products": products, "body": body}


def _author_id(conn, code: str) -> "object":
    email = f"example-{code.lower()}@truefit.invalid"
    row = conn.execute("SELECT id FROM identity.app_user WHERE email_normalized = %s", (email,)).fetchone()
    if row:
        return row[0] if not isinstance(row, dict) else row["id"]
    row = conn.execute(
        "INSERT INTO identity.app_user (email_normalized, auth_subject, display_name, status) VALUES (%s, %s, %s, 'active') RETURNING id",
        (email, f"example:{code}", AUTHORS[code])).fetchone()
    return row[0] if not isinstance(row, dict) else row["id"]


def _resolve_products(repo: CommunityRepo, items: list) -> list[dict]:
    """머리말의 제품(brand + model)을 카탈로그에서 정확히 하나 찾는다. 없거나 여러 개면 ValueError."""
    resolved = []
    for order, item in enumerate(items):
        brand, model = str((item or {}).get("brand") or "").strip(), str((item or {}).get("model") or "").strip()
        if not brand or not model:
            raise ValueError(f"제품 {order + 1}: brand 와 model 이 필요하다")
        rows = repo._all("SELECT id, product_type FROM catalog.product WHERE brand = %s AND model = %s", (brand, model))
        if len(rows) != 1:
            raise ValueError(f"제품 {order + 1}: '{brand} {model}' 이(가) 카탈로그에서 {len(rows)}개 일치")
        ptype = rows[0]["product_type"]
        option = str((item or {}).get("option") or "").strip() or None
        resolved.append(dict(product_id=rows[0]["id"], product_kind=TYPE_TO_KIND.get(ptype, ptype), custom_product_name=None,
                             selected_option=option, match_status="matched", display_order=order))
    return resolved


def load_examples(conn, files: list[Path], *, apply: bool, update: bool = False,
                  base_time: datetime | None = None) -> Report:
    report = Report()
    repo = CommunityRepo(conn)
    base = base_time or datetime.now(timezone.utc)
    seen: set[str] = set()
    for index, path in enumerate(sorted(files)):
        try:
            post = parse_file(path)
            if post["id"] in seen:
                raise ValueError(f"같은 id 가 두 번 나온다: {post['id']}")
            seen.add(post["id"])
            products = _resolve_products(repo, post["products"])
            existing = repo.get_post_by_external_id(post["id"])
            if existing is not None and not update:
                report.skipped.append(post["id"])
                continue
            if not apply:
                (report.updated if existing else report.created).append(post["id"])
                continue
            published_at = base - timedelta(minutes=index)
            if existing is None:
                author = _author_id(conn, post["author"])
                post_id = repo.create_post(author_id=author, board_type=post["board"], title=post["title"], body=post["body"],
                                           tags=post["tags"], status="published", is_example=post["is_example"],
                                           external_id=post["id"], published_at=published_at)
                report.created.append(post["id"])
            else:
                post_id = existing["id"]
                repo.update_post(post_id, expected_version=None,
                                 fields={"board_type": post["board"], "title": post["title"], "body": post["body"],
                                         "tags": post["tags"], "is_example": post["is_example"]})
                repo.delete_all_products(post_id)
                report.updated.append(post["id"])
            for item in products:
                repo.add_product(post_id, **item)
        except Exception as exc:  # noqa: BLE001 — 글 하나의 문제가 나머지 적재를 막지 않게 한다
            report.errors.append((path.name, str(exc)))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="예시 사용기 글을 community.post 에 적재한다(기본은 점검만).")
    parser.add_argument("folder", type=Path, help="글 파일(.md)이 있는 폴더")
    parser.add_argument("--apply", action="store_true", help="실제로 적재한다")
    parser.add_argument("--update", action="store_true", help="이미 있는 글도 갱신한다")
    args = parser.parse_args()
    files = sorted(args.folder.glob("*.md"))
    if not files:
        print(f"글 파일이 없다: {args.folder}")
        return 1
    class _Abort(Exception):
        pass

    report: Report | None = None
    try:
        with get_conn() as conn:
            report = load_examples(conn, files, apply=args.apply, update=args.update)
            if report.errors and args.apply:
                raise _Abort()                        # 트랜잭션을 되돌린다 — 오류가 있으면 아무것도 저장하지 않는다
    except _Abort:
        print("오류가 있어 적재를 취소한다(아무것도 저장하지 않았다).")
    assert report is not None
    mode = "적재" if args.apply else "점검(dry-run)"
    print(f"{mode}: 새 글 {len(report.created)} · 갱신 {len(report.updated)} · 건너뜀 {len(report.skipped)} · 오류 {len(report.errors)}")
    for name, message in report.errors:
        print(f"  ✗ {name}: {message}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())

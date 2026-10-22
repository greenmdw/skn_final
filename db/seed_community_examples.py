#!/usr/bin/env python3
"""예시 사용기 글(마크다운 + 머리말)을 community.post 에 한꺼번에 적재한다.

글 형식(예시_사용기_작성_기획.md 3장): 머리말(YAML) + 마크다운 본문. 글 한 편 = 파일 하나(`A1-1.md`).

    ---
    id: A1-1                # 필수 — 다시 적재해도 같은 글이 두 번 들어가지 않게 하는 키(community.post.external_id)
    board: review           # question | review | tip | free
    author: P06             # P01~P20 (아래 AUTHORS) — 계정이 없으면 만든다(로그인 불가 계정)
    is_example: true
    written_at: 2026-08-16  # 선택 — 게시일(community.post.published_at). 없으면 적재 시각 기준으로 과거에 둔다. 미래 날짜는 오류
    products:
      - brand: Logitech     # catalog.product.brand, model 과 글자까지 같아야 연결된다(모호하면 건너뛴다)
        model: G PRO X SUPERLIGHT 2
        option:             # 키보드 스위치 등(선택)
      - custom: Slate 75    # 카탈로그에 없는 제품은 brand/model 대신 custom(제품명)과 kind(제품 종류)로 직접 입력한다
        kind: 키보드
    title: "[4주 사용] 클로 그립으로 써본 G PRO X SUPERLIGHT 2"
    tags: [마우스, FPS]     # 선택
    images: [a1-1_1.jpg, a1-1_2.png]   # 선택(본문 마커 ![설명](a1-1_1.jpg) 의 파일 이름은 모두 여기 있어야 하고, 적재할 때 이미지 id 로 바뀐다)
    # 선택 — 글 파일과 같은 폴더(하위 폴더 가능)의 이미지, 첫 장이 대표. 최대 5장, 장당 5MB
    ---
    본문…

폴더는 하위 폴더까지 읽는다(`A/`, `B/` … 묶음 폴더). 단 `revisions/`·`dump/`·`README.md`·`_` 로 시작하는 이름은 건너뛴다.
검증은 실제 사용자가 글을 올릴 때와 같은 규칙을 쓴다(제목·본문 길이, 금지어, 태그 정리, 제품 개수, 사용기의 제품 연결).

사용 (기본은 점검만 한다 — 아무것도 쓰지 않는다):
    python db/seed_community_examples.py <글 폴더>                 # 점검(dry-run)
    python db/seed_community_examples.py <글 폴더> --apply         # 적재
    python db/seed_community_examples.py <글 폴더> --apply --update   # 이미 있는 글은 본문·제목·태그·제품도 갱신

이미지: 글 화면에서 올릴 때와 같은 검증(JPEG·PNG·WebP, 5MB)·축소(긴 변 1600px)·EXIF 제거를 거쳐 저장 폴더(COMMUNITY_UPLOAD_DIR)에 넣는다.
점검(dry-run)에서도 파일이 있는지·올릴 수 있는지 확인한다. --update 는 글의 이미지를 머리말 목록으로 교체한다(머리말에 images 가 없으면 이미지는 그대로 둔다).

멱등: 같은 id 는 두 번 들어가지 않는다(--update 가 없으면 건너뛴다). 글은 파일 이름 순서대로 1분 간격으로 과거에 게시한 것으로
적재해 목록 순서가 안정적이다. 직접 쓴(is_example: false) 글도 같은 형식으로 적재할 수 있다.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import COMMUNITY_IMAGE_MAX_BYTES, COMMUNITY_IMAGE_MAX_PER_POST, COMMUNITY_IMAGE_MAX_SIDE_PX  # noqa: E402
from src.db import get_conn  # noqa: E402
from src.repo.community_repo import CommunityRepo  # noqa: E402
from src.errors import ValidationFailed  # noqa: E402
from src.services.community_service import (  # noqa: E402
    BOARD_TYPES, PRODUCT_MAX, TYPE_TO_KIND, _check_banned, _check_lengths, _clean_tags, _remove_files, _store, kind_to_type,
)
from src.storage.community_images import InvalidImage, process_image  # noqa: E402

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
    saved_keys: list[str] = field(default_factory=list)       # 이번 실행에서 저장한 이미지 파일 — 롤백하면 지운다
    stale_keys: list[str] = field(default_factory=list)       # 교체돼 빠진 이미지 파일 — 커밋된 뒤에 지운다


def _service_checks(title: str, body: str, board: str, tags: list[str], products: list) -> list[str]:
    """실제 사용자가 글을 올릴 때(`community_service.create_post`)와 같은 검증을 한다 — 길이, 금지어, 태그 정리,
    제품 개수, 사용기의 제품 연결. 예시 글이 사용자 글이라면 막혔을 내용을 통과시키지 않기 위해서다.
    정리한 태그를 돌려준다."""
    try:
        _check_lengths(title, body)
        _check_banned(title, body)
        cleaned = _clean_tags(tags)
    except ValidationFailed as exc:
        raise ValueError(exc.message) from exc
    if len(products) > PRODUCT_MAX:
        raise ValueError(f"제품은 최대 {PRODUCT_MAX}개까지 연결할 수 있다")
    if board == "review" and not products:
        raise ValueError("사용기(review)는 제품을 1개 이상 연결해야 한다")
    for item in products:
        option = str((item or {}).get("option") or "").strip()
        if len(option) > 60:
            raise ValueError("옵션은 60자 이하여야 한다")
    return cleaned


EXCLUDED_DIRS = {"revisions", "dump"}          # 폴더 아래로 내려갈 때 건너뛰는 하위 폴더(수정본·스냅샷)
EXCLUDED_FILES = {"readme.md"}


def collect_files(folder: Path) -> list[Path]:
    """폴더와 그 하위 폴더의 글 파일(.md)을 이름 순으로 모은다.

    `revisions/`(수정본)와 `dump/`(스냅샷)는 아래로 내려갈 때 건너뛴다 — 수정본은 원글 적재 뒤에 그 폴더를 직접 지정해
    `--update` 로 올린다. `README.md` 와 `_` 로 시작하는 파일·폴더도 글이 아니다. 폴더를 직접 지정하면
    (예: `.../revisions`) 그 안의 파일은 모두 읽는다."""
    files = []
    for path in folder.rglob("*.md"):
        rel = path.relative_to(folder).parts
        if any(part in EXCLUDED_DIRS or part.startswith("_") for part in rel[:-1]):
            continue
        if path.name.lower() in EXCLUDED_FILES or path.name.startswith("_"):
            continue
        files.append(path)
    return sorted(files)


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
    images = meta.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(isinstance(x, str) and x.strip() for x in images):
            raise ValueError("images 는 파일 이름 목록이어야 한다")
        if len(images) > COMMUNITY_IMAGE_MAX_PER_POST:
            raise ValueError(f"이미지는 글당 최대 {COMMUNITY_IMAGE_MAX_PER_POST}장이다")
        images = [x.strip() for x in images]
    written_at = meta.get("written_at")
    if isinstance(written_at, str):                                       # "2026-08-16"처럼 따옴표로 쓴 날짜(JSON)도 받는다
        try:
            written_at = date.fromisoformat(written_at.strip())
        except ValueError:
            raise ValueError(f"written_at 은 날짜(YYYY-MM-DD)여야 한다: {written_at}") from None
    if written_at is not None:
        if isinstance(written_at, datetime):
            written_at = written_at if written_at.tzinfo else written_at.replace(tzinfo=timezone.utc)
        elif isinstance(written_at, date):
            written_at = datetime.combine(written_at, time(3, 0), tzinfo=timezone.utc)      # 한국 시간 낮 12시
        else:
            raise ValueError(f"written_at 은 날짜(YYYY-MM-DD)여야 한다: {written_at}")
        if written_at > datetime.now(timezone.utc):
            raise ValueError("written_at 이 미래 날짜다")
    title = str(meta["title"]).strip()
    tags = _service_checks(title, body, meta["board"], [str(t) for t in (meta.get("tags") or [])], products)
    return {"images": images, "id": str(meta["id"]).strip(), "board": meta["board"], "author": meta["author"], "title": title,
            "is_example": bool(meta.get("is_example", False)), "tags": tags,
            "products": products, "body": body, "written_at": written_at}


def _author_id(conn, code: str) -> "object":
    email = f"example-{code.lower()}@truefit.invalid"
    row = conn.execute("SELECT id FROM identity.app_user WHERE email_normalized = %s", (email,)).fetchone()
    if row:
        return row[0] if not isinstance(row, dict) else row["id"]
    row = conn.execute(
        "INSERT INTO identity.app_user (email_normalized, auth_subject, display_name, status) VALUES (%s, %s, %s, 'active') RETURNING id",
        (email, f"example:{code}", AUTHORS[code])).fetchone()
    return row[0] if not isinstance(row, dict) else row["id"]


def _load_images(path: Path, names: list[str]) -> list:
    """머리말의 이미지 파일을 읽고 검증·가공한다(글 파일이 있는 폴더 밖은 읽지 않는다)."""
    base = path.parent.resolve()
    processed = []
    for name in names:
        file = (base / name).resolve()
        if base != file and base not in file.parents:
            raise ValueError(f"이미지 '{name}' 이(가) 글 폴더 밖에 있다")
        if not file.is_file():
            raise ValueError(f"이미지 '{name}' 파일이 없다")
        raw = file.read_bytes()
        if len(raw) > COMMUNITY_IMAGE_MAX_BYTES:
            raise ValueError(f"이미지 '{name}' 이(가) {COMMUNITY_IMAGE_MAX_BYTES // (1024 * 1024)}MB 를 넘는다")
        try:
            processed.append(process_image(raw, max_side=COMMUNITY_IMAGE_MAX_SIDE_PX))
        except InvalidImage as exc:
            raise ValueError(f"이미지 '{name}': {exc}") from exc
    return processed


_FILE_MARKER_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def _check_markers(body: str, names: list[str] | None) -> None:
    """본문의 `![설명](파일이름)` 마커는 모두 머리말 images 에 있는 파일이어야 한다(적재할 때 이미지 id 로 바뀐다).
    머리말에는 있는데 본문에 마커가 없는 이미지는 허용한다 — 본문 맨 아래에 붙는다."""
    listed = set(names or [])
    for _alt, target in _FILE_MARKER_RE.findall(body):
        if target.startswith("image:"):
            raise ValueError(f"본문에 이미지 id 마커({target})를 직접 쓰지 않는다 — 파일 이름을 쓴다")
        if target not in listed:
            raise ValueError(f"본문 마커 '{target}' 이(가) 머리말 images 에 없다")


def _replace_markers(body: str, names: list[str], ids: list) -> str:
    by_name = {name: str(image_id) for name, image_id in zip(names, ids)}
    return _FILE_MARKER_RE.sub(lambda m: f"![{m.group(1)}](image:{by_name[m.group(2)]})", body)


def _store_images(repo: CommunityRepo, report: Report, owner_id, images: list) -> list:
    """이미지 파일을 저장하고 id 를 돌려준다(아직 글에 붙이지 않는다 — 본문 마커를 id 로 바꾼 뒤 붙인다)."""
    store = _store()
    ids = []
    for item in images:
        key = store.new_key(item.content_type)
        store.save(key, item.data)
        report.saved_keys.append(key)
        ids.append(repo.insert_image(owner_id=owner_id, storage_key=key, content_type=item.content_type, width=item.width,
                                     height=item.height, byte_size=len(item.data))["id"])
    return ids


def _resolve_products(repo: CommunityRepo, items: list) -> list[dict]:
    """머리말의 제품(brand + model)을 카탈로그에서 정확히 하나 찾는다. 없거나 여러 개면 ValueError."""
    resolved = []
    for order, item in enumerate(items):
        custom = str((item or {}).get("custom") or "").strip()
        if custom:                                                  # 카탈로그에 없는 제품 — 화면의 "목록에 없는 제품"과 같은 처리
            ptype = kind_to_type(str((item or {}).get("kind") or "").strip())
            if ptype is None:
                raise ValueError(f"제품 {order + 1}: custom 제품은 kind(제품 종류)가 필요하다")
            option = str((item or {}).get("option") or "").strip() or None
            similar = repo.similar_catalog_product(ptype, custom)
            resolved.append(dict(product_id=None, product_kind=TYPE_TO_KIND[ptype], custom_product_name=custom[:120], selected_option=option,
                                 match_status="review_needed" if similar else "unmatched", display_order=order))
            continue
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
            images = _load_images(path, post["images"]) if post["images"] is not None else None
            _check_markers(post["body"], post["images"])
            existing = repo.get_post_by_external_id(post["id"])
            if existing is not None and not update:
                report.skipped.append(post["id"])
                continue
            if not apply:
                (report.updated if existing else report.created).append(post["id"])
                continue
            published_at = (post["written_at"] or base) - timedelta(minutes=index)
            body = post["body"]
            if existing is None:
                author = _author_id(conn, post["author"])
                owner = author
                image_ids = _store_images(repo, report, owner, images) if images is not None else None
                if image_ids is not None:
                    body = _replace_markers(body, post["images"], image_ids)
                post_id = repo.create_post(author_id=author, board_type=post["board"], title=post["title"], body=body,
                                           tags=post["tags"], status="published", is_example=post["is_example"],
                                           external_id=post["id"], published_at=published_at)
                report.created.append(post["id"])
            else:
                post_id = existing["id"]
                owner = existing["author_user_id"]
                image_ids = _store_images(repo, report, owner, images) if images is not None else None
                if image_ids is not None:
                    body = _replace_markers(body, post["images"], image_ids)
                repo.update_post(post_id, expected_version=None,
                                 fields={"board_type": post["board"], "title": post["title"], "body": body,
                                         "tags": post["tags"], "is_example": post["is_example"]})
                repo.delete_all_products(post_id)
                report.updated.append(post["id"])
            for item in products:
                repo.add_product(post_id, **item)
            if image_ids is not None:
                report.stale_keys.extend(repo.attach_images(post_id, image_ids))
        except Exception as exc:  # noqa: BLE001 — 글 하나의 문제가 나머지 적재를 막지 않게 한다
            report.errors.append((path.name, str(exc)))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="예시 사용기 글을 community.post 에 적재한다(기본은 점검만).")
    parser.add_argument("folder", type=Path, help="글 파일(.md)이 있는 폴더")
    parser.add_argument("--apply", action="store_true", help="실제로 적재한다")
    parser.add_argument("--update", action="store_true", help="이미 있는 글도 갱신한다")
    args = parser.parse_args()
    files = collect_files(args.folder)
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
        _remove_files(report.saved_keys)                  # 롤백된 글의 이미지 파일도 지운다
        report.stale_keys.clear()
    assert report is not None
    _remove_files(report.stale_keys)                      # 커밋된 뒤에 교체돼 빠진 파일을 지운다
    mode = "적재" if args.apply else "점검(dry-run)"
    print(f"{mode}: 새 글 {len(report.created)} · 갱신 {len(report.updated)} · 건너뜀 {len(report.skipped)} · 오류 {len(report.errors)}")
    for name, message in report.errors:
        print(f"  ✗ {name}: {message}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())

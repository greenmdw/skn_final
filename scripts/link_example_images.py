#!/usr/bin/env python3
"""예시 글 이미지를 JPEG 로 바꾸고 글에 연결한다(머리말 `images:` + 본문 중간 마커).

폴더(A~F)마다 이미지 파일 이름에서 글 번호를 읽어(`A1-1.png`, `B1-2-image.png`, `c1-3_1.png`, `e22_1.png` …) 글에 붙인다.
- 이미지는 JPEG(품질 85)로 바꿔 `<글번호 소문자>_<순번>.jpg` 로 저장한다. 원본은 `--originals` 폴더로 옮긴다(저장소 밖 보관).
- 머리말에 `images: [..]` 를 쓰고, 본문에는 `![설명](파일이름)` 마커를 글 흐름에 맞는 자리에 넣는다.
  첫 장: 스펙 표(없으면 도입 문단) 뒤. 둘째 장부터: 소제목 앞(첫 소제목 앞은 건너뛰고 둘째 소제목부터).
- 마커의 파일 이름은 적재 도구가 이미지 id 로 바꿔 저장한다(`db/seed_community_examples.py`).

    python scripts/link_example_images.py data/community_examples --originals data/community_example_images_original
    python scripts/link_example_images.py data/community_examples --dry-run
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
POST_RE = re.compile(r"^([a-f]\d+(?:-\d+)?)(?:[_-](?:image|\d+))?$", re.I)
SPLIT_RE = re.compile(r"^(?P<id>[a-f]\d+(?:-\d+)?)(?:_(?P<n>\d+)|-image)?(?:-v(?P<v>\d+))?$", re.I)


def split_front_matter(text: str) -> tuple[str, str, str]:
    m = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)(.*)$", text, re.S)
    if not m:
        raise ValueError("머리말(---) 형식이 아니다")
    return m.group(1) + m.group(2), m.group(3), m.group(4)


def _blocks(body: str) -> list[str]:
    return re.split(r"\n{2,}", body.strip("\n"))


def insert_markers(body: str, markers: list[str]) -> str:
    """마커 줄(앞뒤 빈 줄)을 글 흐름에 맞는 자리에 넣는다. 표·소제목 안에는 넣지 않는다."""
    if not markers:
        return body
    blocks = _blocks(body.replace("\r\n", "\n"))
    heading_idx = [i for i, b in enumerate(blocks) if b.startswith("#")]
    # 첫 장: 스펙 표 뒤, 없으면 첫 일반 문단(면책 인용문 제외) 뒤
    first = None
    for i, b in enumerate(blocks):
        if heading_idx and i >= heading_idx[0]:
            break
        if b.startswith("|"):
            first = i + 1
            break
    if first is None:
        for i, b in enumerate(blocks):
            if not b.startswith(">") and not b.startswith("#") and not b.startswith("|"):
                first = i + 1
                break
    first = first if first is not None else len(blocks)
    positions = [first]
    # 둘째 장부터: 첫 소제목은 건너뛰고(첫 장 바로 뒤) 이어지는 소제목 앞에 하나씩
    candidates = [h for h in heading_idx if h >= first][1:]       # 첫 소제목은 첫 장이 바로 앞에 있어 건너뛴다
    for k in range(1, len(markers)):
        if k - 1 < len(candidates):
            positions.append(candidates[k - 1])
        else:
            positions.append(len(blocks))
    out: list[str] = []
    for i, b in enumerate(blocks):
        for pos, mk in zip(positions, markers):
            if pos == i:
                out.append(mk)
        out.append(b)
    for pos, mk in zip(positions, markers):
        if pos >= len(blocks):
            out.append(mk)
    return "\n\n".join(out) + "\n"


def first_product_name(head: str) -> str | None:
    brand = re.search(r"^\s*-\s*brand:\s*(.+)$", head, re.M)
    model = re.search(r"^\s*model:\s*(.+)$", head, re.M)
    custom = re.search(r"^\s*-\s*custom:\s*(.+)$", head, re.M)
    if brand and model:
        return f"{brand.group(1).strip()} {model.group(1).strip()}"
    if custom:
        return custom.group(1).strip()
    return None


def set_images_header(head: str, names: list[str]) -> str:
    line = f"images: [{', '.join(names)}]"
    if re.search(r"^images:.*$", head, re.M):
        return re.sub(r"^images:.*$", line, head, count=1, flags=re.M)
    # title 줄 뒤(없으면 머리말 끝)에 넣는다
    m = re.search(r"^title:.*$", head, re.M)
    if m:
        return head[: m.end()] + "\n" + line + head[m.end():]
    return head + "\n" + line


def convert_to_jpeg(src: Path, dst: Path) -> None:
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(dst, "JPEG", quality=85, optimize=True, progressive=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="예시 글 루트(A~F 폴더가 있는 곳)")
    ap.add_argument("--originals", type=Path, help="원본 이미지를 옮겨 둘 폴더(저장소 밖 보관)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--groups", default="ABCDEF")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    total_before = total_after = 0
    problems: list[str] = []
    for group in args.groups:
        folder = args.root / group
        if not folder.is_dir():
            continue
        by_post: dict[str, list[tuple[int, Path]]] = {}
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() not in IMG_EXT:
                continue
            m = SPLIT_RE.match(p.stem)
            if not m:
                problems.append(f"{group}/{p.name}: 이름에서 글 번호를 읽지 못했다")
                continue
            by_post.setdefault(m.group("id").upper(), []).append((int(m.group("n") or 1), p, int(m.group("v") or 1)))
        for post_id, items in sorted(by_post.items()):
            md = folder / f"{post_id}.md"
            if not md.is_file():
                problems.append(f"{group}/{post_id}: 글 파일이 없다 ({[p.name for _, p in items]})")
                continue
            # 같은 순번에 재생성본(-v2 …)이 있으면 가장 높은 버전만 쓰고 나머지는 원본 보관으로 보낸다
            best: dict[int, tuple[int, Path, int]] = {}
            superseded: list[Path] = []
            for n, path_, ver in items:
                if n not in best or ver > best[n][2]:
                    if n in best:
                        superseded.append(best[n][1])
                    best[n] = (n, path_, ver)
                else:
                    superseded.append(path_)
            items = [(n, path_) for n, path_, _ in sorted(best.values(), key=lambda t: t[0])]
            for old in superseded:
                if not args.dry_run:
                    if args.originals:
                        target = args.originals / group / "superseded" / old.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(old), str(target))
                    else:
                        old.unlink()
            items.sort(key=lambda t: (t[0], t[1].name))
            raw = md.read_bytes().decode("utf-8")
            crlf = "\r\n" in raw
            text = raw.replace("\r\n", "\n")
            head, tail_sep, body = split_front_matter(text)
            n_products = len(re.findall(r"^\s*-\s*(?:brand|custom):", head, re.M))
            product = first_product_name(head) if n_products == 1 else None      # 여러 제품 글은 어느 제품인지 알 수 없다
            names: list[str] = []
            markers: list[str] = []
            for k, (_, src) in enumerate(items, start=1):
                name = f"{post_id.lower()}_{k}.jpg"
                names.append(name)
                base_alt = f"{product} 사용 장면" if product else "사용 장면"
                alt = base_alt if len(items) == 1 else f"{base_alt} {k}"
                markers.append(f"![{alt}](" + name + ")")
                dst = folder / name
                total_before += src.stat().st_size
                if not args.dry_run:
                    convert_to_jpeg(src, dst)
                    total_after += dst.stat().st_size
                    if src.resolve() != dst.resolve():
                        if args.originals:
                            target = args.originals / group / src.name
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(src), str(target))
                        else:
                            src.unlink()
            body = re.sub(r"\n*!\[[^\]]*\]\([^)]*\)\n*", "\n\n", body)         # 이전 마커가 있으면 걷어낸다(다시 실행 가능)
            new_head = set_images_header(head, names)
            new_body = insert_markers(body, markers)
            result = new_head + tail_sep + new_body.lstrip("\n")
            if not args.dry_run:
                md.write_bytes((result.replace("\n", "\r\n") if crlf else result).encode("utf-8"))
            print(f"{post_id}: 이미지 {len(items)}장 → {names}")
    mb = lambda n: f"{n/1024/1024:.1f}MB"      # noqa: E731
    print(f"\n원본 합계 {mb(total_before)}" + ("" if args.dry_run else f" → JPEG 합계 {mb(total_after)}"))
    for pr in problems:
        print("문제:", pr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

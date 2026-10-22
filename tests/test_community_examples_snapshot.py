"""예시 글 스냅샷(db/community_examples_snapshot.py) — 내보내기·복원·충돌 거절·제품 다시 찾기."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "db" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if DSN:
    from src.db import get_conn

    snap = _load("community_examples_snapshot", "community_examples_snapshot.py")
    seed = _load("seed_community_examples_for_snap", "seed_community_examples.py")


def _write(folder: Path, tag: str, n: int, brand: str, model: str) -> Path:
    path = folder / f"{tag}-{n}.md"
    path.write_text(
        f'---\nid: {tag}-{n}\nboard: review\nauthor: P0{n}\nis_example: true\nwritten_at: 2026-08-1{n}\n'
        f'title: "스냅샷 {tag}-{n}"\nproducts:\n  - brand: {brand}\n    model: {model}\n---\n\n본문 문장입니다. 직접 써 본 느낌입니다.\n',
        encoding="utf-8")
    return path


def _seed_with_evidence(tmp_path: Path, tag: str):
    files = [_write(tmp_path, tag, 1, "Logitech", "G PRO X SUPERLIGHT 2"), _write(tmp_path, tag, 2, "Razer", "Cobra")]
    vec = "[" + ",".join(["0.01"] * 1536) + "]"
    with get_conn() as conn:
        report = seed.load_examples(conn, files, apply=True)
        assert not report.errors
        posts = conn.execute("SELECT id, author_user_id, external_id FROM community.post WHERE external_id LIKE %s ORDER BY external_id",
                             (f"{tag}-%",)).fetchall()
        for post_id, author_id, ext in posts:
            product_id = conn.execute("SELECT product_id FROM community.post_product WHERE post_id = %s", (post_id,)).fetchone()[0]
            conn.execute("INSERT INTO engine.peripheral_post_intake (post_id, status) VALUES (%s, 'done')", (post_id,))
            ev = conn.execute(
                """INSERT INTO engine.peripheral_post_evidence (post_id, quote_id, product_id, kind, attribute, direction, author_id, sentence)
                   VALUES (%s, %s, %s, 'mouse', 'weight', 'good', %s, %s) RETURNING id""",
                (post_id, f"q-{ext}", product_id, author_id, f"{ext} 가볍습니다.")).fetchone()[0]
            conn.execute("INSERT INTO engine.peripheral_post_evidence_embedding (evidence_id, embedding, model) VALUES (%s, %s::vector, 'test')",
                         (ev, vec))
    return posts


def _state(tag: str) -> dict:
    with get_conn() as conn:
        like = f"{tag}-%"
        return {
            "posts": conn.execute("SELECT count(*) FROM community.post WHERE external_id LIKE %s", (like,)).fetchone()[0],
            "ids": sorted(str(r[0]) for r in conn.execute("SELECT id FROM community.post WHERE external_id LIKE %s", (like,)).fetchall()),
            "products": conn.execute(
                "SELECT count(*) FROM community.post_product pp JOIN community.post p ON p.id = pp.post_id "
                "WHERE p.external_id LIKE %s AND pp.match_status = 'matched'", (like,)).fetchone()[0],
            "evidence": conn.execute(
                "SELECT count(*) FROM engine.peripheral_post_evidence e JOIN community.post p ON p.id = e.post_id WHERE p.external_id LIKE %s",
                (like,)).fetchone()[0],
            "embeddings": conn.execute(
                "SELECT count(*) FROM engine.peripheral_post_evidence_embedding m JOIN engine.peripheral_post_evidence e ON e.id = m.evidence_id "
                "JOIN community.post p ON p.id = e.post_id WHERE p.external_id LIKE %s", (like,)).fetchone()[0],
            "evidence_products_match_post": conn.execute(
                "SELECT count(*) FROM engine.peripheral_post_evidence e JOIN community.post p ON p.id = e.post_id "
                "JOIN community.post_product pp ON pp.post_id = p.id AND pp.product_id = e.product_id WHERE p.external_id LIKE %s",
                (like,)).fetchone()[0],
            "intake": conn.execute(
                "SELECT count(*) FROM engine.peripheral_post_intake i JOIN community.post p ON p.id = i.post_id WHERE p.external_id LIKE %s",
                (like,)).fetchone()[0],
        }


def test_export_then_restore_brings_back_posts_evidence_and_vectors(tmp_path):
    import os as _os
    tag = f"S{_os.urandom(3).hex()}"
    _seed_with_evidence(tmp_path, tag)
    before = _state(tag)
    assert before["posts"] == 2 and before["evidence"] == 2 and before["embeddings"] == 2
    out = tmp_path / "dump"
    with get_conn() as conn:
        manifest = snap.export_snapshot(conn, out, prefix=tag)
    assert manifest["counts"]["community.post"] == 2
    assert manifest["counts"]["engine.peripheral_post_evidence_embedding"] == 2

    with get_conn() as conn:                                   # 다른 DB 처럼 비운다
        ids = [r[0] for r in conn.execute("SELECT id FROM community.post WHERE external_id LIKE %s", (f"{tag}-%",)).fetchall()]
        snap._delete_examples(conn, ids)
    assert _state(tag)["posts"] == 0

    with get_conn() as conn:
        restored = snap.restore_snapshot(conn, out)
    assert restored["community.post"] == 2
    after = _state(tag)
    assert after == before                                     # 글 id·연결 제품·근거·벡터가 그대로다
    assert after["evidence_products_match_post"] == 2


def test_restore_refuses_existing_examples_unless_replace(tmp_path):
    import os as _os
    tag = f"S{_os.urandom(3).hex()}"
    _seed_with_evidence(tmp_path, tag)
    out = tmp_path / "dump"
    with get_conn() as conn:
        snap.export_snapshot(conn, out, prefix=tag)
    with pytest.raises(ValueError, match="겹친다"):
        with get_conn() as conn:
            snap.restore_snapshot(conn, out)
    before = _state(tag)
    with get_conn() as conn:
        snap.restore_snapshot(conn, out, replace=True)
    assert _state(tag) == before


def test_restore_aborts_whole_when_a_product_is_missing(tmp_path):
    import os as _os
    tag = f"S{_os.urandom(3).hex()}"
    _seed_with_evidence(tmp_path, tag)
    out = tmp_path / "dump"
    with get_conn() as conn:
        snap.export_snapshot(conn, out, prefix=tag)
    ev = out / "peripheral_post_evidence.copy"
    ev.write_bytes(ev.read_bytes().replace(b"\tCobra", b"\tNoSuchModelX"))
    with get_conn() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM community.post WHERE external_id LIKE %s", (f"{tag}-%",)).fetchall()]
        snap._delete_examples(conn, ids)
    with pytest.raises(ValueError, match="제품"):
        with get_conn() as conn:
            snap.restore_snapshot(conn, out)
    assert _state(tag)["posts"] == 0                            # 아무것도 들어오지 않았다


@pytest.fixture()
def upload_dir(monkeypatch, tmp_path):
    from src.services import community_service as svc
    monkeypatch.setattr(svc, "COMMUNITY_UPLOAD_DIR", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


def _png(path: Path, color) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color).save(path, "PNG")


def _files_in(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _write_image_post(folder: Path, tag: str, images: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    post = folder / f"{tag}-1.md"
    lines = ["---", f"id: {tag}-1", "board: review", "author: P01", "is_example: true", "written_at: 2026-08-10",
             f'title: "스냅샷 사진 {tag}"', f"images: [{', '.join(images)}]", "products:", "  - brand: Razer", "    model: Cobra",
             "---", "", "본문 문장입니다.", ""]
    post.write_text("\n".join(lines), encoding="utf-8")
    return post


def test_images_travel_with_the_snapshot(tmp_path, upload_dir):
    import shutil
    tag = f"S{os.urandom(3).hex()}"
    src = tmp_path / "posts"
    _png(src / "a.png", (200, 10, 10)); _png(src / "b.png", (10, 200, 10))
    post = _write_image_post(src, tag, ["a.png", "b.png"])
    with get_conn() as conn:
        assert not seed.load_examples(conn, [post], apply=True).errors
        keys = sorted(r[0] for r in conn.execute(
            "SELECT i.storage_key FROM community.post_image i JOIN community.post p ON p.id = i.post_id WHERE p.external_id = %s",
            (f"{tag}-1",)).fetchall())
    assert len(keys) == 2 and _files_in(upload_dir) == set(keys)

    out = tmp_path / "dump"
    with get_conn() as conn:
        manifest = snap.export_snapshot(conn, out, prefix=tag)
    assert manifest["counts"]["community.post_image"] == 2 and sorted(manifest["images"]) == keys
    assert _files_in(out / "images") == set(keys)

    # 다른 컴퓨터처럼: 글과 이미지 파일을 모두 없앤다
    with get_conn() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM community.post WHERE external_id = %s", (f"{tag}-1",)).fetchall()]
        snap._delete_examples(conn, ids)
    shutil.rmtree(upload_dir)
    assert _files_in(upload_dir) == set()

    with get_conn() as conn:
        restored = snap.restore_snapshot(conn, out)
    assert restored["community.post_image"] == 2
    assert _files_in(upload_dir) == set(keys)
    with get_conn() as conn:
        again = sorted(r[0] for r in conn.execute(
            "SELECT i.storage_key FROM community.post_image i JOIN community.post p ON p.id = i.post_id WHERE p.external_id = %s",
            (f"{tag}-1",)).fetchall())
    assert again == keys


def test_restore_replace_reports_files_that_are_no_longer_used(tmp_path, upload_dir):
    from src.services import community_service as svc
    tag = f"S{os.urandom(3).hex()}"
    src = tmp_path / "posts"
    _png(src / "a.png", (1, 2, 3)); _png(src / "c.png", (9, 9, 9))
    post = _write_image_post(src, tag, ["a.png"])
    with get_conn() as conn:
        seed.load_examples(conn, [post], apply=True)
    out = tmp_path / "dump"
    with get_conn() as conn:
        snap.export_snapshot(conn, out, prefix=tag)
    # 이 DB 의 글에 다른 이미지로 교체(= 스냅샷과 다른 파일 키)해 둔다
    post = _write_image_post(src, tag, ["c.png"])
    with get_conn() as conn:
        report = seed.load_examples(conn, [post], apply=True, update=True)
    assert not report.errors
    svc._remove_files(report.stale_keys)                                  # 적재 도구가 커밋 뒤에 하는 일
    assert len(_files_in(upload_dir)) == 1
    stale: list[str] = []
    with get_conn() as conn:
        snap.restore_snapshot(conn, out, replace=True, stale_keys=stale)
    assert len(stale) == 1
    svc._remove_files(stale)
    assert _files_in(upload_dir) == _files_in(out / "images")           # 스냅샷의 파일만 남는다

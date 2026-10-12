"""예시 사용기 글 적재(db/seed_community_examples.py) — 형식 검사·멱등·제품 연결·작성자 계정."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from src.api import app
    from src.db import get_conn

    _spec = importlib.util.spec_from_file_location("seed_community_examples", Path(__file__).resolve().parents[1] / "db" / "seed_community_examples.py")
    seed = importlib.util.module_from_spec(_spec)
    sys.modules["seed_community_examples"] = seed            # dataclass 가 모듈 이름으로 자기 자신을 찾는다
    _spec.loader.exec_module(seed)


def _write(folder: Path, name: str, front: str, body: str = "본문 문장입니다. 직접 써 본 느낌을 적었습니다.") -> Path:
    path = folder / name
    path.write_text(f"---\n{front}\n---\n\n{body}\n", encoding="utf-8")
    return path


def _files(tmp_path: Path, tag: str) -> list[Path]:
    return [
        _write(tmp_path, f"{tag}-1.md", f'id: {tag}-1\nboard: review\nauthor: P06\nis_example: true\ntitle: "[4주 사용] {tag} 마우스"\n'
               'tags: [마우스, FPS]\nproducts:\n  - brand: Logitech\n    model: G PRO X SUPERLIGHT 2\n    option:'),
        _write(tmp_path, f"{tag}-2.md", f'id: {tag}-2\nboard: review\nauthor: P02\nis_example: true\ntitle: "{tag} 키보드"\n'
               'products:\n  - brand: Leopold\n    model: FC900RBT MX2A\n    option: 저소음 적축\n  - brand: Logitech\n    model: MX Keys S'),
        _write(tmp_path, f"{tag}-3.md", f"id: {tag}-3\nboard: question\nauthor: P11\nis_example: true\ntitle: {tag} 질문"),
    ]


def _count(tag: str) -> int:
    with get_conn() as conn:
        return conn.execute("SELECT count(*) FROM community.post WHERE external_id LIKE %s", (f"{tag}-%",)).fetchone()[0]


def test_dry_run_writes_nothing_and_apply_loads_once(tmp_path):
    tag = f"T{os.urandom(3).hex()}"
    files = _files(tmp_path, tag)
    with get_conn() as conn:
        report = seed.load_examples(conn, files, apply=False)
    assert len(report.created) == 3 and not report.errors and _count(tag) == 0
    with get_conn() as conn:
        report = seed.load_examples(conn, files, apply=True)
    assert len(report.created) == 3 and not report.errors and _count(tag) == 3
    with get_conn() as conn:                                              # 다시 실행해도 두 번 들어가지 않는다
        again = seed.load_examples(conn, files, apply=True)
    assert again.created == [] and len(again.skipped) == 3 and _count(tag) == 3


def test_loaded_posts_are_examples_with_author_accounts_and_linked_products(tmp_path):
    tag = f"T{os.urandom(3).hex()}"
    with get_conn() as conn:
        seed.load_examples(conn, _files(tmp_path, tag), apply=True)
    anon = TestClient(app)
    items = anon.get("/community/posts", params={"q": tag, "is_example": True, "page_size": 50}).json()["items"]
    assert len(items) == 3 and all(i["is_example"] for i in items)
    by_title = {i["title"]: i for i in items}
    mouse = by_title[f"[4주 사용] {tag} 마우스"]
    assert mouse["author"]["name"] == "랭크만돌림" and mouse["board_label"] == "사용기 · 마우스" and mouse["tags"] == ["마우스", "FPS"]
    keyboard = by_title[f"{tag} 키보드"]
    assert [p["match_status"] for p in keyboard["products"]] == ["matched", "matched"]
    assert [p["selected_option"] for p in keyboard["products"]] == ["저소음 적축", None]
    assert [p["display_order"] for p in keyboard["products"]] == [0, 1]
    # 작성자 계정은 로그인할 수 없다(비밀번호 없음)
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM identity.app_user WHERE email_normalized = 'example-p06@truefit.invalid'").fetchone()
    assert row[0] is None


def test_bad_files_are_reported_without_blocking_the_rest(tmp_path):
    tag = f"T{os.urandom(3).hex()}"
    good = _files(tmp_path, tag)[2]
    no_front = tmp_path / "bad1.md"; no_front.write_text("머리말 없음", encoding="utf-8")
    bad_board = _write(tmp_path, "bad2.md", f"id: {tag}-b2\nboard: news\nauthor: P01\ntitle: t")
    bad_author = _write(tmp_path, "bad3.md", f"id: {tag}-b3\nboard: free\nauthor: P99\ntitle: t")
    bad_product = _write(tmp_path, "bad4.md", f"id: {tag}-b4\nboard: review\nauthor: P01\ntitle: t\nproducts:\n  - brand: 없는회사\n    model: 없는모델")
    dup = _write(tmp_path, "zdup.md", f"id: {tag}-3\nboard: free\nauthor: P01\ntitle: 같은 id")
    with get_conn() as conn:
        report = seed.load_examples(conn, [good, no_front, bad_board, bad_author, bad_product, dup], apply=True)
    assert report.created == [f"{tag}-3"]
    assert {name for name, _ in report.errors} == {"bad1.md", "bad2.md", "bad3.md", "bad4.md", "zdup.md"}


def test_update_flag_refreshes_existing_posts(tmp_path):
    tag = f"T{os.urandom(3).hex()}"
    first = _write(tmp_path, f"{tag}.md", f"id: {tag}-1\nboard: question\nauthor: P01\ntitle: {tag} 처음 제목")
    with get_conn() as conn:
        seed.load_examples(conn, [first], apply=True)
    changed = _write(tmp_path, f"{tag}.md", f"id: {tag}-1\nboard: question\nauthor: P01\ntitle: {tag} 바뀐 제목", body="바뀐 본문")
    with get_conn() as conn:
        assert seed.load_examples(conn, [changed], apply=True).skipped == [f"{tag}-1"]                  # 기본은 건너뜀
        assert seed.load_examples(conn, [changed], apply=True, update=True).updated == [f"{tag}-1"]
    items = TestClient(app).get("/community/posts", params={"q": tag}).json()["items"]
    assert [i["title"] for i in items] == [f"{tag} 바뀐 제목"]


# ── 이미지 ───────────────────────────────────────────────────────────────────────────
def _img(folder: Path, name: str, size=(400, 300), fmt="PNG") -> None:
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (20, 120, 220)).save(folder / name, fmt)


@pytest.fixture()
def upload_dir(monkeypatch, tmp_path):
    from src.services import community_service as svc
    monkeypatch.setattr(svc, "COMMUNITY_UPLOAD_DIR", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


def _stored(upload_dir: Path) -> int:
    return sum(1 for p in upload_dir.rglob("*") if p.is_file()) if upload_dir.exists() else 0


def test_images_are_validated_in_dry_run_and_loaded_on_apply(tmp_path, upload_dir):
    tag = f"T{os.urandom(3).hex()}"
    src = tmp_path / "posts"
    src.mkdir()
    _img(src, "a.png"); _img(src / "pics", "b.jpg", (3000, 1000), "JPEG")
    post = _write(src, f"{tag}-1.md", f"id: {tag}-1\nboard: free\nauthor: P01\nis_example: true\ntitle: {tag} 사진 글\nimages: [pics/b.jpg, a.png]")
    with get_conn() as conn:
        report = seed.load_examples(conn, [post], apply=False)
    assert report.created == [f"{tag}-1"] and not report.errors and _stored(upload_dir) == 0
    with get_conn() as conn:
        report = seed.load_examples(conn, [post], apply=True)
    assert not report.errors and _stored(upload_dir) == 2
    item = TestClient(app).get("/community/posts", params={"q": tag}).json()["items"][0]
    assert item["image_count"] == 2
    detail = TestClient(app).get(f"/community/posts/{item['id']}").json()
    assert [(i["width"], i["height"]) for i in detail["images"]] == [(1600, 533), (400, 300)]       # 첫 장(b.jpg)이 대표, 긴 변 1600px
    assert TestClient(app).get(detail["images"][0]["url"]).headers["content-type"] == "image/jpeg"


def test_image_problems_are_reported_per_post(tmp_path, upload_dir):
    tag = f"T{os.urandom(3).hex()}"
    src = tmp_path / "posts"
    src.mkdir()
    (src / "fake.png").write_bytes(b"not an image")
    outside = tmp_path / "outside.png"
    _img(tmp_path, "outside.png")
    files = [
        _write(src, f"{tag}-1.md", f"id: {tag}-1\nboard: free\nauthor: P01\ntitle: t1\nimages: [missing.png]"),
        _write(src, f"{tag}-2.md", f"id: {tag}-2\nboard: free\nauthor: P01\ntitle: t2\nimages: [fake.png]"),
        _write(src, f"{tag}-3.md", f"id: {tag}-3\nboard: free\nauthor: P01\ntitle: t3\nimages: ['../outside.png']"),
        _write(src, f"{tag}-4.md", f"id: {tag}-4\nboard: free\nauthor: P01\ntitle: t4\nimages: [a, b, c, d, e, f]"),
        _write(src, f"{tag}-5.md", f"id: {tag}-5\nboard: free\nauthor: P01\ntitle: t5"),
    ]
    assert outside.exists()
    with get_conn() as conn:
        report = seed.load_examples(conn, files, apply=False)
    messages = {name: msg for name, msg in report.errors}
    assert len(messages) == 4 and report.created == [f"{tag}-5"]
    assert "파일이 없다" in messages[f"{tag}-1.md"] and "이미지" in messages[f"{tag}-2.md"]
    assert "폴더 밖" in messages[f"{tag}-3.md"] and "최대" in messages[f"{tag}-4.md"]


def test_update_replaces_images_and_failed_apply_leaves_no_files(tmp_path, upload_dir):
    tag = f"T{os.urandom(3).hex()}"
    src = tmp_path / "posts"
    src.mkdir()
    _img(src, "a.png"); _img(src, "b.png"); _img(src, "c.png")
    path = _write(src, f"{tag}-1.md", f"id: {tag}-1\nboard: free\nauthor: P01\ntitle: {tag} 글\nimages: [a.png, b.png]")
    with get_conn() as conn:
        seed.load_examples(conn, [path], apply=True)
    assert _stored(upload_dir) == 2
    _write(src, f"{tag}-1.md", f"id: {tag}-1\nboard: free\nauthor: P01\ntitle: {tag} 글\nimages: [c.png]")
    with get_conn() as conn:
        report = seed.load_examples(conn, [path], apply=True, update=True)
    assert report.updated == [f"{tag}-1"] and not report.errors
    seed._remove_files(report.stale_keys)                       # main() 이 커밋 뒤에 하는 일
    assert _stored(upload_dir) == 1
    item = TestClient(app).get("/community/posts", params={"q": tag}).json()["items"][0]
    assert item["image_count"] == 1
    # images 를 생략하고 갱신하면 이미지는 그대로
    _write(src, f"{tag}-1.md", f"id: {tag}-1\nboard: free\nauthor: P01\ntitle: {tag} 글 수정")
    with get_conn() as conn:
        seed.load_examples(conn, [path], apply=True, update=True)
    assert TestClient(app).get("/community/posts", params={"q": tag}).json()["items"][0]["image_count"] == 1

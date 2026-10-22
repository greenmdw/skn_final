"""예시 글 JSON → 마크다운 변환(db/community_examples_from_json.py) — DB 없이 도는 테스트."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "db" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


conv = _load("community_examples_from_json", "community_examples_from_json.py")
seed = _load("seed_for_json_test", "seed_community_examples.py")

POSTS = {
    "meta": {"count": 4},
    "posts": [
        {"id": "A11-1", "board": "review", "author": "P08", "is_example": True, "written_at": "2025-12-30",
         "title": "[2개월 사용] 큰 손 DeathAdder", "source_file": "A11-1.md",
         "products": [{"brand": "Razer", "model": "DeathAdder V2 X HyperSpeed", "option": None}],
         "body": "본문 첫 문단입니다.\n\n| 크기 | 무게 |\n|---|---|\n| 1 | 2 |\n\n## 소제목\n\n둘째 문단입니다."},
        {"id": "E8", "board": "review", "author": "P11", "is_example": True, "written_at": "2026-10-02",
         "title": "[2종 비교] 키보드", "source_file": "E8.md",
         "products": [{"brand": "Logitech", "model": "MX Keys S"}, {"brand": "Logitech", "model": "MX Mechanical", "option": "Tactile Quiet"}],
         "body": "비교 글 본문입니다."},
        {"id": "F12", "board": "review", "author": "P16", "is_example": True, "written_at": "2026-07-13", "revision": "initial",
         "title": "원글", "source_file": "F12.md", "products": [{"brand": "Razer", "model": "Cobra"}], "body": "원글 본문."},
        {"id": "F12", "board": "review", "author": "P16", "is_example": True, "written_at": "2026-07-13", "revision": "edited",
         "title": "원글", "source_file": "F12-edited.md", "products": [{"brand": "Razer", "model": "Cobra"}], "body": "수정한 본문."},
    ],
}


def _run(tmp_path: Path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(POSTS, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    return out, conv.convert(src, out)


def test_posts_are_split_into_group_folders_and_revisions(tmp_path):
    out, report = _run(tmp_path)
    assert len(report["written"]) == 4 and report["skipped"] == []
    got = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md"))
    assert got == ["A/A11-1.md", "E/E8.md", "F/F12.md", "revisions/F12-edited.md"]


def test_converted_files_are_read_by_the_loader_with_the_same_content(tmp_path):
    out, _ = _run(tmp_path)
    a = seed.parse_file(out / "A" / "A11-1.md")
    assert a["id"] == "A11-1" and a["author"] == "P08" and a["written_at"].date().isoformat() == "2025-12-30"
    assert a["products"] == [{"brand": "Razer", "model": "DeathAdder V2 X HyperSpeed", "option": None}]
    assert a["body"] == POSTS["posts"][0]["body"]                      # 본문은 한 글자도 바뀌지 않는다
    e = seed.parse_file(out / "E" / "E8.md")
    assert [p["model"] for p in e["products"]] == ["MX Keys S", "MX Mechanical"]
    assert e["products"][1]["option"] == "Tactile Quiet"
    assert seed.parse_file(out / "revisions" / "F12-edited.md")["id"] == "F12"


def test_collect_files_keeps_revisions_out_of_the_main_load(tmp_path):
    out, _ = _run(tmp_path)
    names = [p.name for p in seed.collect_files(out)]
    assert "F12-edited.md" not in names and names.count("F12.md") == 1


def test_existing_files_are_not_overwritten_unless_asked(tmp_path):
    out, _ = _run(tmp_path)
    path = out / "A" / "A11-1.md"
    path.write_text("손으로 고친 내용", encoding="utf-8")
    src = tmp_path / "in.json"
    again = conv.convert(src, out)
    assert str(path) in again["skipped"] and path.read_text(encoding="utf-8") == "손으로 고친 내용"
    conv.convert(src, out, overwrite=True)
    assert path.read_text(encoding="utf-8") != "손으로 고친 내용"


def test_custom_product_is_carried_over(tmp_path):
    post = {"id": "F11", "board": "review", "author": "P07", "is_example": True, "written_at": "2026-01-02", "title": "t",
            "products": [{"custom": "노르달 펄스 M2", "kind": "마우스"}], "body": "본문입니다."}
    out = tmp_path / "out"
    src = tmp_path / "one.json"
    src.write_text(json.dumps({"posts": [post]}, ensure_ascii=False), encoding="utf-8")
    conv.convert(src, out)
    got = seed.parse_file(out / "F" / "F11.md")
    assert got["products"] == [{"custom": "노르달 펄스 M2", "kind": "마우스"}]

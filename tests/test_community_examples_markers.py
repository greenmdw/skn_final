"""예시 글 이미지 연결 — 본문 마커 치환(적재 도구)과 마커 삽입 위치(이미지 연결 스크립트). DB 불필요."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


seed = _load("seed_community_examples_under_test", "db/seed_community_examples.py")
link = _load("link_example_images_under_test", "scripts/link_example_images.py")

BODY = """도입 문단입니다.

| 크기 | 무게 |
|---|---|
| 125mm | 60g |

## 첫째 소제목

첫째 본문.

## 둘째 소제목

둘째 본문.

## 셋째 소제목

셋째 본문.
"""


def test_markers_must_be_listed_in_the_front_matter_images():
    """적재 도구(`_check_markers`): 본문 마커의 파일 이름은 모두 머리말 images 에 있어야 한다."""
    seed._check_markers("앞\n\n![a](a1-1_1.jpg)\n", ["a1-1_1.jpg"])               # 통과
    seed._check_markers("마커 없는 글", ["a1-1_1.jpg"])                               # 머리말에만 있는 이미지는 허용(글 아래에 붙음)
    for bad in ("![x](other.jpg)", "![x](image:0a1b)"):
        try:
            seed._check_markers(bad, ["a1-1_1.jpg"])
        except ValueError:
            continue
        raise AssertionError(f"{bad} 는 거절돼야 한다")


def test_replace_markers_with_image_ids_in_order():
    body = "앞\n\n![책상 위](a1-1_1.jpg)\n\n중간\n\n![두 번째](a1-1_2.jpg)\n"
    out = seed._replace_markers(body, ["a1-1_1.jpg", "a1-1_2.jpg"], ["ID1", "ID2"])
    assert "![책상 위](image:ID1)" in out and "![두 번째](image:ID2)" in out and "jpg" not in out


def test_link_script_output_is_accepted_by_the_seed_tool():
    """우리 연결 스크립트가 만든 본문·머리말은 적재 도구의 마커 검사를 통과한다(두 도구가 같은 규칙을 쓴다)."""
    names = ["e22_1.jpg", "e22_2.jpg"]
    body = link.insert_markers(BODY, [f"![사용 장면 {i}]({n})" for i, n in enumerate(names, 1)])
    seed._check_markers(body, names)


def test_first_image_goes_after_the_spec_table_before_the_first_heading():
    out = link.insert_markers(BODY, ["![사용 장면](a1-1_1.jpg)"])
    assert out.index("|---|---|") < out.index("![사용 장면]") < out.index("## 첫째 소제목")
    assert "\n\n![사용 장면](a1-1_1.jpg)\n\n" in out                 # 앞뒤 빈 줄


def test_later_images_go_before_following_headings_not_inside_sections():
    out = link.insert_markers(BODY, ["![1](a_1.jpg)", "![2](a_2.jpg)", "![3](a_3.jpg)"])
    assert out.index("![1]") < out.index("## 첫째 소제목") < out.index("첫째 본문.")
    assert out.index("![2]") < out.index("## 둘째 소제목") and out.index("첫째 본문.") < out.index("![2]")
    assert out.index("![3]") < out.index("## 셋째 소제목") and out.index("둘째 본문.") < out.index("![3]")


def test_no_table_uses_the_first_plain_paragraph_and_skips_the_notice():
    body = "> 가상 예시 사용기입니다.\n\n첫 문단입니다.\n\n## 소제목\n\n본문."
    out = link.insert_markers(body, ["![x](a.jpg)"])
    assert out.index("첫 문단입니다.") < out.index("![x]") < out.index("## 소제목")


def test_header_images_line_is_inserted_after_title_and_replaced_on_rerun():
    head = '---\nid: A1-1\ntitle: "제목"\ntags: [a]'
    once = link.set_images_header(head, ["a1-1_1.jpg"])
    assert 'title: "제목"\nimages: [a1-1_1.jpg]' in once
    again = link.set_images_header(once, ["a1-1_1.jpg", "a1-1_2.jpg"])
    assert again.count("images:") == 1 and "a1-1_2.jpg" in again

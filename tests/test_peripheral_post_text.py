"""글자 본문(`peripheral_post_text.plain_text`) — Markdown 서식과 이미지 마커를 걷어낸 분석 입력.

DB 불필요. 예시 글(`A1-1.md`) 형식(도입 문단 → 스펙 4칸 표 → 소제목 → 이미지 마커)을 고정 입력으로 쓴다.
"""
from __future__ import annotations

from datetime import datetime

from src.agent import peripheral_post_agent as agent
from src.engine import peripheral_post_contract as pc
from src.engine.peripheral_post_text import plain_text

IMG = "![책상 위에 올려 둔 모습](image:7f3c2a1e-5b9d-4a6e-8c1f-2d4e6a8b0c1d)"

MARKDOWN = f"""G PRO X SUPERLIGHT 2를 4주 썼습니다. **클로 그립**으로 씁니다.

{IMG}

| 항목 | 값 |
|---|---|
| 무게 | 60g |
| 연결 | 무선 |

## 그립과 무게
- 큰 스윙 뒤 멈추기 쉽습니다.
- 무선 지연을 못 느낍니다.

> 엄지 받칠 곳이 없어 아쉽습니다.

### 아쉬운 점
1. 클릭 소리가 또렷합니다.
2. [제조사 페이지](https://example.com/a)는 스펙만 있습니다.
"""

EXPECTED = """G PRO X SUPERLIGHT 2를 4주 썼습니다. 클로 그립으로 씁니다.

항목 값
무게 60g
연결 무선

그립과 무게
큰 스윙 뒤 멈추기 쉽습니다.
무선 지연을 못 느낍니다.

엄지 받칠 곳이 없어 아쉽습니다.

아쉬운 점
클릭 소리가 또렷합니다.
제조사 페이지는 스펙만 있습니다.
"""


def test_markdown_is_reduced_to_plain_sentences():
    assert plain_text(MARKDOWN) == EXPECTED


def test_image_marker_line_is_removed_with_one_surrounding_blank_line():
    out = plain_text(f"앞 문단입니다.\n\n{IMG}\n\n뒤 문단입니다.")
    assert out == "앞 문단입니다.\n\n뒤 문단입니다."


def test_image_alt_text_never_reaches_the_analysis_input():
    alt = "![배터리가 정말 오래갑니다 5점 만점](image:abc)"
    assert "배터리" not in plain_text(f"본문입니다.\n\n{alt}\n\n끝.")
    assert "배터리" not in plain_text(f"본문 중간에 {alt} 이미지가 있다.")


def test_plain_text_post_is_unchanged_byte_for_byte():
    """서식이 없는 기존 글은 그대로여야 이미 분석한 글의 해시가 바뀌지 않는다."""
    body = ("PRO X 마우스를 두 달 썼습니다.  그립이 안정적입니다.\r\n\r\n\r\n무게는 63g입니다. #후기 \n"
            "2026. 10. 13 에 샀습니다.\n5*5 키로 눌러 봤습니다.\n    들여쓴 줄입니다. ")
    assert plain_text(body) == body


def test_hash_tag_without_space_is_not_a_heading():
    assert plain_text("#가성비 좋습니다") == "#가성비 좋습니다"


def test_empty_and_none():
    assert plain_text("") == "" and plain_text(None) == ""


def test_is_idempotent():
    once = plain_text(MARKDOWN)
    assert plain_text(once) == once


# ── 분석 입력으로 쓸 때 ────────────────────────────────────────────────────
def _post(body: str) -> pc.PostInput:
    return pc.PostInput(
        post_id="p1", author_id="u1", board="review", body=body, written_at=datetime(2026, 5, 1),
        products=[pc.LinkedProduct(index=0, product_id="pid-mouse", kind="mouse", name="PRO X")],
    )


def test_moving_an_image_only_does_not_change_the_content_hash():
    """이미지 위치만 바꾼 수정(version 은 오른다)은 해시가 같아 다시 분석하지 않는다."""
    a = f"첫 문단입니다.\n\n{IMG}\n\n둘째 문단입니다."
    b = f"첫 문단입니다.\n\n둘째 문단입니다.\n\n{IMG}"
    c = f"첫 문단입니다.\n\n둘째 문단입니다."
    hashes = {agent.content_hash(_post(plain_text(x))) for x in (a, b, c)}
    assert len(hashes) == 1


def test_changing_a_sentence_changes_the_content_hash():
    a = agent.content_hash(_post(plain_text("**그립이** 안정적입니다.")))
    b = agent.content_hash(_post(plain_text("**그립이** 불안정합니다.")))
    assert a != b


def test_sentence_check_matches_text_that_had_formatting():
    """서식 때문에 원문 일치 확인(sentence_not_in_body)이 실패하지 않는다 — 추출·확인 모두 글자 본문 기준."""
    body = plain_text("## 그립\n- **클로 그립**에서 손바닥 뒤쪽 지지가 적당합니다.")
    assert "클로 그립에서 손바닥 뒤쪽 지지가 적당합니다." in body


# ── 예시 글 면책 문구 ───────────────────────────────────────────────────────
def test_example_notice_line_is_removed_with_its_blank_line():
    from src.engine.peripheral_post_text import strip_example_notice

    body = "> 가상 예시 사용기입니다. 실제 구매자가 작성한 후기가 아닙니다.\n\n기숙사 책상에서 3주 썼습니다.\n\n## 소제목\n본문"
    assert strip_example_notice(body) == "기숙사 책상에서 3주 썼습니다.\n\n## 소제목\n본문"
    assert plain_text(strip_example_notice(body)).startswith("기숙사 책상에서")


def test_text_without_the_notice_is_unchanged():
    from src.engine.peripheral_post_text import strip_example_notice

    body = "그립이 안정적입니다.\n\n> 인용문입니다.\n끝"
    assert strip_example_notice(body) == body
    assert strip_example_notice(None) == ""

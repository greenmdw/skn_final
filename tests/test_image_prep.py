"""견적 사진 전처리·품질 검사 — 작은 사진은 키우고, 작거나 흐린 사진은 알리되 분석을 막지 않는다. LLM·DB 없이 돈다."""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFilter

from src.engine import image_prep


def _png(image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _text_image(width: int, height: int) -> Image.Image:
    """글씨 비슷한 가는 선이 많은 그림(윤곽선이 또렷)."""
    rng = random.Random(7)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for _ in range(width * height // 400):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.line((x, y, x + rng.randrange(2, 9), y), fill="black", width=1)
    return image


def test_a_narrow_photo_is_scaled_up_to_the_minimum_width_and_returned_as_png():
    ct, data = image_prep.prepare_for_reading("image/jpeg", _png(_text_image(600, 300)))
    assert ct == "image/png" and Image.open(io.BytesIO(data)).size == (image_prep.MIN_WIDTH, 800)


def test_a_wide_enough_photo_and_an_unreadable_file_are_returned_unchanged():
    wide = _png(_text_image(1700, 100))
    assert image_prep.prepare_for_reading("image/png", wide) == ("image/png", wide)
    assert image_prep.prepare_for_reading("image/png", b"not an image") == ("image/png", b"not an image")


def test_scale_up_is_capped_so_a_tiny_photo_is_not_blown_up_without_limit():
    _, data = image_prep.prepare_for_reading("image/png", _png(_text_image(100, 50)))
    assert Image.open(io.BytesIO(data)).size[0] == 300           # 최대 3배


def test_quality_flags_small_and_blurry_photos_but_not_a_sharp_one():
    sharp = _text_image(1200, 700)
    assert image_prep.assess_quality(_png(sharp))["low"] is False
    small = image_prep.assess_quality(_png(_text_image(500, 400)))
    assert small["low"] is True and small["reason"] == "small"
    blurry = image_prep.assess_quality(_png(sharp.filter(ImageFilter.GaussianBlur(6))))
    assert blurry["low"] is True and blurry["reason"] == "blurry"


def test_quality_does_not_judge_a_file_it_cannot_open():
    assert image_prep.assess_quality(b"junk")["low"] is False


def test_a_low_quality_photo_is_trusted_only_when_enough_parts_were_read_clearly():
    clean = [{"category": "CPU", "raw_text": f"part {n}"} for n in range(5)]
    assert image_prep.reading_is_unreliable(False, clean[:1]) is False                              # 품질이 괜찮으면 개수와 상관없다
    assert image_prep.reading_is_unreliable(True, clean) is False                                    # 흐려도 또렷하게 충분히 읽힘
    assert image_prep.reading_is_unreliable(True, clean[:3]) is True                                 # 너무 적게 읽힘
    assert image_prep.reading_is_unreliable(True, [*clean, {"category": "GPU", "raw_text": "RTX 5?80"}]) is True
    assert image_prep.reading_is_unreliable(True, [*clean, {"category": "GPU", "raw_text": "RTX 5080", "uncertain": True}]) is True


def test_a_huge_but_tiny_file_is_not_decoded(monkeypatch):
    """파일은 작아도 펼치면 수천만 화소인 사진(압축 폭탄)은 열어 보지 않는다 — 전처리·품질 검사가 메모리를 쓰지 않게."""
    data = _png(Image.new("L", (9000, 6000), 255))           # 54M 화소, 파일은 수십 KB
    assert image_prep.prepare_for_reading("image/png", data) == ("image/png", data)
    assert image_prep.assess_quality(data)["low"] is False

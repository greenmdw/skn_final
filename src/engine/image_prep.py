"""견적 사진을 비전 모델에 넘기기 전의 전처리와 품질 검사 — Pillow 만 쓰는 순수 함수(LLM·DB 없음).

- `prepare_for_reading`: 가로가 좁은 사진은 글씨가 작아 오독이 늘므로 가로 `MIN_WIDTH` 까지 키우고 약하게 선명하게 한다.
  이미 충분히 크면 원본 그대로 돌려준다. 어떤 이유로든 실패하면 원본을 돌려준다(전처리가 인식을 막지 않는다).
- `assess_quality`: 너무 작거나 흐린 사진인지. 흐림은 가로 800px 로 맞춘 뒤 윤곽선의 분산으로 잰다(실측: 또렷한 견적 캡처 1,300 이상,
  흐리게 만든 사진 360~520). 이 판정은 안내와 "자동 확정하지 않음"에만 쓰고 분석을 막지 않는다."""
from __future__ import annotations

import io
import logging
from typing import Any

log = logging.getLogger(__name__)

MIN_WIDTH = 1600           # 이보다 좁은 사진은 이 폭까지 키운다
_MAX_SCALE = 3.0           # 너무 작은 사진을 무한정 키우지 않는다
_MAX_PIXELS = 12_000_000   # 키운 결과가 이보다 크면 키우지 않는다
_TOO_SMALL_WIDTH = 640     # 이보다 좁으면 글씨를 읽기 어렵다
_BLUR_VAR_MIN = 800.0      # 가로 800px 기준 윤곽선 분산이 이보다 낮으면 흐리다
_BLUR_WIDTH = 800


def prepare_for_reading(content_type: str, data: bytes) -> tuple[str, bytes]:
    """(content_type, bytes) — 작은 사진은 키우고 선명하게 한 PNG, 아니면 입력 그대로."""
    try:
        from PIL import Image, ImageFilter, ImageOps

        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            if width >= MIN_WIDTH or width < 1 or height < 1:
                return content_type, data
            scale = min(MIN_WIDTH / width, _MAX_SCALE)
            if int(width * scale) * int(height * scale) > _MAX_PIXELS:
                return content_type, data
            image = image.convert("RGB").resize((int(width * scale), int(height * scale)), Image.LANCZOS)
            image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
            out = io.BytesIO()
            image.save(out, format="PNG")
            return "image/png", out.getvalue()
    except Exception:  # noqa: BLE001 — 전처리 실패는 원본으로 인식한다
        log.warning("image prep failed, using the original", exc_info=True)
        return content_type, data


def assess_quality(data: bytes) -> dict[str, Any]:
    """{"low": bool, "reason": "small"|"blurry"|None, "width": int, "blur": float|None}. 열 수 없으면 low=False(판단하지 않는다)."""
    try:
        from PIL import Image, ImageFilter, ImageOps, ImageStat

        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("L")
            width, height = image.size
            if width < _TOO_SMALL_WIDTH:
                return {"low": True, "reason": "small", "width": width, "blur": None}
            small = image.resize((_BLUR_WIDTH, max(1, int(height * _BLUR_WIDTH / width))))
            blur = float(ImageStat.Stat(small.filter(ImageFilter.FIND_EDGES)).var[0])
            return {"low": blur < _BLUR_VAR_MIN, "reason": "blurry" if blur < _BLUR_VAR_MIN else None, "width": width, "blur": round(blur, 1)}
    except Exception:  # noqa: BLE001
        return {"low": False, "reason": None, "width": 0, "blur": None}


WARNINGS = {
    "small": "사진이 작아 글씨를 읽기 어려워요. 더 크게 찍어 다시 올리면 정확해져요.",
    "blurry": "사진이 흐려 글씨를 정확히 읽지 못했을 수 있어요. 선명하게 다시 올리면 정확해져요.",
}
NOT_CONFIRMED_NOTE = " 글자가 확실하지 않아 읽은 부품은 자동으로 확정하지 않고 후보로만 보여 드려요."
_MIN_ITEMS_FOR_TRUST = 4     # 흐린 사진에서 이보다 적게 읽히면(견적 한 장은 보통 부품 5개 이상) 읽은 것도 믿기 어렵다


def reading_is_unreliable(quality_low: bool, items: list[dict]) -> bool:
    """품질이 낮은 사진에서 읽은 결과를 자동 확정하지 말아야 하는가. 흐려도 부품이 모두 또렷하게 읽혔으면(물음표·불확실 표시 없고
    충분히 읽힘) 확정해도 된다 — 실측: 흐리게 만든 사진 중 오확정이 난 것은 전부 부품이 몇 개밖에 안 읽히거나 '?'가 섞인 사진이었다."""
    if not quality_low:
        return False
    return len(items) < _MIN_ITEMS_FOR_TRUST or any(i.get("uncertain") or "?" in i["raw_text"] for i in items)

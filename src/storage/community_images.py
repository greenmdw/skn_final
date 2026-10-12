"""커뮤니티 첨부 이미지 — 검증·정리(process_image)와 파일 저장(LocalImageStore).

저장소는 `ImageStore` 모양(save/read/delete)만 지키면 되므로, 나중에 S3 로 옮길 때 이 파일의 구현체만 바꾼다.
업로드 바이트는 믿지 않는다 — 파일 앞부분으로 실제 형식을 확인하고(JPEG·PNG·WebP 만), 디코드해서 긴 변을 줄인 뒤
다시 인코드한다. 다시 인코드하면 촬영 위치(EXIF GPS) 같은 메타데이터가 빠진다.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_PIXELS = 40_000_000          # 디코드 폭탄 방지(가로×세로)


class InvalidImage(ValueError):
    """이미지가 아니거나 허용하지 않는 형식·크기."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int


def process_image(raw: bytes, *, max_side: int) -> ProcessedImage:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            if fmt not in ALLOWED_FORMATS:
                raise InvalidImage("JPEG, PNG, WebP 이미지만 올릴 수 있습니다.")
            if getattr(probe, "is_animated", False):
                raise InvalidImage("움직이는 이미지는 올릴 수 없습니다.")
            probe.load()
            image = ImageOps.exif_transpose(probe)       # 회전 정보를 픽셀에 반영한 뒤 메타데이터는 버린다
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError) as exc:
        raise InvalidImage("이미지를 읽을 수 없습니다. 다른 파일을 올려 주세요.") from exc
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    if fmt == "JPEG":
        image.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
    elif fmt == "PNG":
        image.save(out, "PNG", optimize=True)
    else:
        image.save(out, "WEBP", quality=85)
    return ProcessedImage(out.getvalue(), ALLOWED_FORMATS[fmt], image.width, image.height)


class LocalImageStore:
    """서버 디스크에 `<root>/<aa>/<uuid>.<ext>` 로 저장한다. key 는 root 기준 상대 경로."""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def new_key(self, content_type: str) -> str:
        name = uuid4().hex
        return f"{name[:2]}/{name}.{_EXT[content_type]}"

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("잘못된 저장 위치")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

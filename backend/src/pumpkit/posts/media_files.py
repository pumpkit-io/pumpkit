"""
What Pumpkit takes as Media and the rules X sets for it, checked from the file's own bytes, and
the preview the web app shows of each file. Pure: no database, no storage.
"""

import io
from dataclasses import dataclass
from typing import BinaryIO, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from pumpkit.core.errors import RefusedError
from pumpkit.posts.models import MEDIA_IMAGE, MediaKind

IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGES_PER_PART = 4
# Shown on the web app's tiles too, so they name X's rule the same way.
X_MEDIA_RULE = "X takes up to 4 images, or 1 GIF, or 1 video, per post."

# Larger images are refused before decoding, so a small file can't expand to gigabytes.
_MAX_PIXELS = 8192 * 8192
_PREVIEW_MAX_SIDE = 1200
PREVIEW_CONTENT_TYPE = "image/webp"
# Enough for every signature below.
SNIFF_BYTES = 16

_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


class MediaRefused(RefusedError):
    pass


def media_type_refused() -> MediaRefused:
    return MediaRefused("Pumpkit takes JPEG, PNG or WEBP images.", code="MEDIA_TYPE_UNSUPPORTED")


def media_too_large() -> MediaRefused:
    return MediaRefused("This image is larger than 5 MB, the most X takes.", code="MEDIA_TOO_LARGE")


def media_unreadable() -> MediaRefused:
    return MediaRefused(
        "This image can't be read. Save it again as JPEG, PNG or WEBP.", code="MEDIA_UNREADABLE"
    )


def part_full(where: str) -> MediaRefused:
    """`where` names the Part as a sentence starts: "Part 2", or "This post"."""
    return MediaRefused(f"{where} holds 4 images already. {X_MEDIA_RULE}", code="MEDIA_PART_FULL")


def content_type_of(head: bytes) -> Optional[str]:
    """The type of an image Pumpkit takes, from the file's first `SNIFF_BYTES`; None otherwise."""
    for signature, content_type in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class CheckedMedia:
    kind: MediaKind
    content_type: str
    byte_size: int
    width: int
    height: int
    # Always PREVIEW_CONTENT_TYPE.
    preview: bytes


def check_image(source: BinaryIO, byte_size: int) -> CheckedMedia:
    """
    The image `source` holds, once it is one Pumpkit takes and X allows, with its preview.
    Raises `MediaRefused` naming the reason otherwise. Reads `source` from where it stands.
    """
    content_type = content_type_of(source.read(SNIFF_BYTES))
    if content_type is None:
        raise media_type_refused()
    if byte_size > IMAGE_MAX_BYTES:
        raise media_too_large()
    source.seek(0)
    try:
        with Image.open(source) as opened:
            width, height = opened.size
            if width * height > _MAX_PIXELS:
                raise media_unreadable()
            upright = ImageOps.exif_transpose(opened)
            width, height = upright.size
            preview = _preview(upright)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise media_unreadable() from None
    return CheckedMedia(
        kind=MEDIA_IMAGE,
        content_type=content_type,
        byte_size=byte_size,
        width=width,
        height=height,
        preview=preview,
    )


def _preview(image: Image.Image) -> bytes:
    shown = image.convert("RGBA" if _has_transparency(image) else "RGB")
    shown.thumbnail((_PREVIEW_MAX_SIDE, _PREVIEW_MAX_SIDE))
    buffer = io.BytesIO()
    shown.save(buffer, format="WEBP", quality=80)
    return buffer.getvalue()


def _has_transparency(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info

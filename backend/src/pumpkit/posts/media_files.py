"""
What Pumpkit takes as Media and the rules X sets for it, checked from the file's own bytes, and
the preview the web app shows of each file. Pure: no database, no storage.
"""

import io
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from pumpkit.core.errors import RefusedError
from pumpkit.posts.models import MEDIA_GIF, MEDIA_IMAGE, MEDIA_VIDEO, MediaKind

MB = 1024 * 1024
# The most X takes of each kind, which an upload is refused past while it streams.
MAX_BYTES: dict[MediaKind, int] = {MEDIA_IMAGE: 5 * MB, MEDIA_GIF: 15 * MB, MEDIA_VIDEO: 512 * MB}
# A video's first frame, which the web app sends with it as its preview.
POSTER_MAX_BYTES = 5 * MB
IMAGES_PER_PART = 4
# X's limit on an image or GIF's alt text.
ALT_TEXT_MAX_CHARS = 1000
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
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
# The `ftyp` brands MP4 and MOV videos start with. Other ISO media files share the box (HEIC,
# AVIF, M4A, Motion JPEG 2000, 3GP); a generic brand may still hold only audio, which X refuses.
_VIDEO_BRANDS: dict[bytes, str] = {
    **dict.fromkeys(
        [b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"mmp4"],
        "video/mp4",
    ),
    **dict.fromkeys([b"M4V ", b"M4VH", b"M4VP"], "video/mp4"),
    b"qt  ": "video/quicktime",
}
# A QuickTime movie made before `ftyp` existed starts with its movie or media data atom, or with
# an empty 8-byte `wide`, `free` or `skip` atom right before one.
_QUICKTIME_ATOMS = {b"moov", b"mdat"}
_QUICKTIME_PADDING_ATOMS = {b"wide", b"free", b"skip"}
_KINDS: dict[str, MediaKind] = {
    "image/jpeg": MEDIA_IMAGE,
    "image/png": MEDIA_IMAGE,
    "image/webp": MEDIA_IMAGE,
    "image/gif": MEDIA_GIF,
    "video/mp4": MEDIA_VIDEO,
    "video/quicktime": MEDIA_VIDEO,
}
_NAMES: dict[MediaKind, str] = {MEDIA_IMAGE: "image", MEDIA_GIF: "GIF", MEDIA_VIDEO: "video"}


class MediaRefused(RefusedError):
    pass


def cleaned_alt_text(value: Optional[str]) -> Optional[str]:
    """Alt text as stored: stripped, and None when nothing is left. Raises ValueError past X's limit."""
    stripped = value.strip() if value is not None else ""
    if len(stripped) > ALT_TEXT_MAX_CHARS:
        raise ValueError(f"Alt text can be up to {ALT_TEXT_MAX_CHARS:,} characters.")
    return stripped or None


def alt_text_unsupported() -> MediaRefused:
    return MediaRefused("Alt text is for images and GIFs.", code="MEDIA_ALT_TEXT_UNSUPPORTED")


def media_type_refused() -> MediaRefused:
    return MediaRefused(
        "Pumpkit takes JPEG, PNG, WEBP or GIF images, and MP4 or MOV videos.",
        code="MEDIA_TYPE_UNSUPPORTED",
    )


def media_too_large(kind: MediaKind) -> MediaRefused:
    return MediaRefused(
        f"This {_NAMES[kind]} is larger than {MAX_BYTES[kind] // MB} MB, the most X takes.",
        code="MEDIA_TOO_LARGE",
    )


def media_unreadable() -> MediaRefused:
    return MediaRefused(
        "This image can't be read. Save it again as JPEG, PNG or WEBP.", code="MEDIA_UNREADABLE"
    )


def part_full(where: str, holds: Sequence[MediaKind]) -> MediaRefused:
    """
    `where` names the Part as a sentence starts: "Part 2", or "This post". `holds` is the Media
    already on it.
    """
    if MEDIA_GIF in holds or MEDIA_VIDEO in holds:
        held = f"a {_NAMES[MEDIA_GIF if MEDIA_GIF in holds else MEDIA_VIDEO]}"
    elif len(holds) >= IMAGES_PER_PART:
        held = f"{IMAGES_PER_PART} images"
    else:
        held = "images"
    return MediaRefused(f"{where} holds {held} already. {X_MEDIA_RULE}", code="MEDIA_PART_FULL")


def takes_more(holds: Sequence[MediaKind], kind: Optional[MediaKind] = None) -> bool:
    """Whether one X post holding `holds` takes Media of `kind` too, or of some kind when None."""
    return not over_x_rule([*holds, kind or MEDIA_IMAGE])


def over_x_rule(kinds: Sequence[MediaKind]) -> bool:
    """Whether one X post can't carry Media of these kinds."""
    if any(kind != MEDIA_IMAGE for kind in kinds):
        return len(kinds) > 1
    return len(kinds) > IMAGES_PER_PART


def content_type_of(head: bytes) -> Optional[str]:
    """The type of a file Pumpkit takes, from the file's first `SNIFF_BYTES`; None otherwise."""
    for signature, content_type in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    box = head[4:8]
    if box == b"ftyp":
        return _VIDEO_BRANDS.get(head[8:12])
    if box in _QUICKTIME_ATOMS:
        return "video/quicktime"
    if (
        box in _QUICKTIME_PADDING_ATOMS
        and head[:4] == b"\0\0\0\x08"
        and head[12:16] in _QUICKTIME_ATOMS
    ):
        return "video/quicktime"
    return None


def kind_of(content_type: str) -> MediaKind:
    """The kind of a type `content_type_of` answers; a KeyError for any other."""
    return _KINDS[content_type]


@dataclass(frozen=True)
class CheckedMedia:
    kind: MediaKind
    content_type: str
    byte_size: int
    width: Optional[int]
    height: Optional[int]
    # Always PREVIEW_CONTENT_TYPE; None for a video sent without its first frame.
    preview: Optional[bytes]
    # A video's length as the browser read it.
    duration_ms: Optional[int] = None


def check_media(
    source: BinaryIO,
    byte_size: int,
    *,
    duration_ms: Optional[int] = None,
    poster: Optional[bytes] = None,
) -> CheckedMedia:
    """
    The Media `source` holds from where it stands, with its preview, or `MediaRefused`. A video is
    never decoded: its preview is `poster` when that is an image, its length `duration_ms`.
    """
    content_type = content_type_of(source.read(SNIFF_BYTES))
    if content_type is None:
        raise media_type_refused()
    kind = kind_of(content_type)
    if byte_size > MAX_BYTES[kind]:
        raise media_too_large(kind)
    if kind != MEDIA_VIDEO:
        source.seek(0)
        return _check_image(source, kind, content_type, byte_size)
    shown = _poster(poster) if poster is not None else None
    return CheckedMedia(
        kind=kind,
        content_type=content_type,
        byte_size=byte_size,
        width=shown.width if shown else None,
        height=shown.height if shown else None,
        preview=shown.preview if shown else None,
        duration_ms=duration_ms,
    )


def _poster(data: bytes) -> Optional[CheckedMedia]:
    """The video's first frame as a checked image, or None when it isn't one Pumpkit reads."""
    content_type = content_type_of(data[:SNIFF_BYTES])
    if content_type is None or kind_of(content_type) != MEDIA_IMAGE:
        return None
    try:
        return _check_image(io.BytesIO(data), MEDIA_IMAGE, content_type, len(data))
    except MediaRefused:
        return None


def _check_image(
    source: BinaryIO, kind: MediaKind, content_type: str, byte_size: int
) -> CheckedMedia:
    """An image or a GIF, decoded far enough for its size and a preview of its first frame."""
    try:
        with Image.open(source) as opened:
            width, height = opened.size
            if width * height > _MAX_PIXELS:
                raise media_unreadable()
            upright = ImageOps.exif_transpose(opened)
            width, height = upright.size
            preview = _preview(upright)
    # Pillow raises more than its own errors on broken headers and metadata, such as EXIF.
    except (
        UnidentifiedImageError,
        OSError,
        EOFError,
        Image.DecompressionBombError,
        SyntaxError,
        ValueError,
        struct.error,
        KeyError,
        TypeError,
        IndexError,
    ):
        raise media_unreadable() from None
    return CheckedMedia(
        kind=kind,
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

"""Small real files for tests that attach Media, made with Pillow so the backend can decode them."""

from io import BytesIO

from PIL import Image

MB = 1024 * 1024


def image(kind: str = "PNG", width: int = 40, height: int = 30, mode: str = "RGB") -> bytes:
    buffer = BytesIO()
    Image.new(mode, (width, height), (200, 80, 40)).save(buffer, format=kind)
    return buffer.getvalue()


def png(width: int = 40, height: int = 30) -> bytes:
    return image("PNG", width, height)


def jpeg(width: int = 40, height: int = 30) -> bytes:
    return image("JPEG", width, height)


def webp(width: int = 40, height: int = 30) -> bytes:
    return image("WEBP", width, height)


def gif() -> bytes:
    return image("GIF", mode="P")


def padded(data: bytes, total: int) -> bytes:
    """`data` with zero bytes after it up to `total`: still decodes, but weighs `total`."""
    return data + b"\0" * (total - len(data))

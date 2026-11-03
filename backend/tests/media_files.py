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


def padded(data: bytes, total: int) -> bytes:
    """`data` with zero bytes after it up to `total`: still decodes, but weighs `total`."""
    return data + b"\0" * (total - len(data))


def animated_gif(frames: int = 3, width: int = 40, height: int = 30) -> bytes:
    buffer = BytesIO()
    shown = [Image.new("P", (width, height), shade) for shade in range(frames)]
    shown[0].save(buffer, format="GIF", save_all=True, append_images=shown[1:], duration=100)
    return buffer.getvalue()


def mp4(total: int = 64) -> bytes:
    """Only the start of an MP4, which is all Pumpkit reads of a video: X decodes the rest."""
    return padded(b"\0\0\0\x18ftypmp42\0\0\0\0mp42isom", total)


def mov(total: int = 64) -> bytes:
    """Only the start of a QuickTime movie, as an iPhone records one."""
    return padded(b"\0\0\0\x14ftypqt  \0\0\x02\0qt  ", total)

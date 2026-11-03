"""
Receiving a Media file from a multipart upload. The body is read as it streams and refused once
the file is larger than its kind may be, so an oversize upload never lands on disk whole.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Optional, cast

from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.datastructures import UploadFile

from pumpkit.core.errors import BadRequestError
from pumpkit.posts.media_files import (
    MAX_BYTES,
    POSTER_MAX_BYTES,
    SNIFF_BYTES,
    content_type_of,
    kind_of,
    media_too_large,
    media_type_refused,
)
from pumpkit.posts.models import MEDIA_VIDEO, MediaKind

FILE_FIELD = "file"
# What the web app read of a video in the browser, sent beside it; the server never reads a video.
DURATION_FIELD = "duration_ms"
POSTER_FIELD = "poster"
_FIELD_MAX_BYTES = {DURATION_FIELD: 16, POSTER_FIELD: POSTER_MAX_BYTES}
# Room for the multipart headers and boundaries around the file.
_ENVELOPE_BYTES = 64 * 1024
_SPOOL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ReceivedMedia:
    file: BinaryIO
    # Counted as the body streamed, never taken from a header.
    byte_size: int
    duration_ms: Optional[int] = None
    poster: Optional[bytes] = None


class IncomingMedia:
    """A Media file as it arrives, its head sniffed for its kind before the rest is kept."""

    def __init__(self) -> None:
        self.upload = UploadFile(file=cast(BinaryIO, SpooledTemporaryFile(max_size=_SPOOL_BYTES)))
        self.head = b""
        self.kind: Optional[MediaKind] = None
        # Hears the kind once the file's first bytes name it.
        self.on_kind: Optional[Callable[[MediaKind], None]] = None
        self.size = 0
        self.ended = False

    async def take(self, data: bytes) -> None:
        self.size += len(data)
        if self.kind is None:
            self.head = (self.head + data)[:SNIFF_BYTES]
            if len(self.head) >= SNIFF_BYTES:
                self._limit_by_kind()
        if self.kind is not None and self.size > MAX_BYTES[self.kind]:
            raise media_too_large(self.kind)
        await self.upload.write(data)

    def end(self) -> None:
        if self.kind is None:
            self._limit_by_kind()
        self.ended = True

    def _limit_by_kind(self) -> None:
        content_type = content_type_of(self.head)
        if content_type is None:
            raise media_type_refused()
        self.kind = kind_of(content_type)
        if self.on_kind is not None:
            self.on_kind(self.kind)


async def receive_media(request: Request) -> AsyncIterator[ReceivedMedia]:
    """
    FastAPI dependency: the upload's `file` field, spooled and rewound, with a video's optional
    `duration_ms` and `poster` image. Refuses an upload with no file, with any other field or a
    field twice, or larger than the most X takes of the file's kind.
    """
    _, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if not boundary:
        raise BadRequestError("Send the file as a multipart upload.")

    part: Optional[IncomingMedia] = None
    pending: list[bytes] = []
    fields: dict[str, bytearray] = {}
    in_field: Optional[bytearray] = None
    field_name = ""
    disposition = b""
    header_name = b""
    header_value = b""
    in_file = False

    def on_header_field(data: bytes, start: int, end: int) -> None:
        nonlocal header_name
        header_name += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        nonlocal header_value
        header_value += data[start:end]

    def on_header_end() -> None:
        nonlocal disposition, header_name, header_value
        if header_name.lower() == b"content-disposition":
            disposition = header_value
        header_name = header_value = b""

    def on_headers_finished() -> None:
        nonlocal part, disposition, in_file, in_field, field_name
        _, options = parse_options_header(disposition)
        disposition = b""
        name = options.get(b"name", b"").decode("latin-1")
        if name == FILE_FIELD and part is None:
            part = IncomingMedia()
            in_file = True
        elif name in _FIELD_MAX_BYTES and name not in fields:
            field_name, in_field = name, bytearray()
            fields[name] = in_field
        else:
            raise BadRequestError(
                f"Send one file, as the `{FILE_FIELD}` field, with at most a video's "
                f"`{DURATION_FIELD}` and `{POSTER_FIELD}`."
            )

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if in_file:
            pending.append(data[start:end])
        elif in_field is not None:
            in_field.extend(data[start:end])
            if len(in_field) > _FIELD_MAX_BYTES[field_name]:
                raise BadRequestError(f"The `{field_name}` field is too large.")

    def on_part_end() -> None:
        nonlocal in_file, in_field
        in_file = False
        in_field = None

    parser = MultipartParser(
        boundary,
        {
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    most_bytes = max(MAX_BYTES.values()) + sum(_FIELD_MAX_BYTES.values()) + _ENVELOPE_BYTES
    read = 0
    try:
        async for chunk in request.stream():
            read += len(chunk)
            if read > most_bytes:
                # Only the largest kind can reach this before its own limit.
                raise media_too_large(part.kind if part and part.kind else MEDIA_VIDEO)
            parser.write(chunk)
            for data in pending:
                assert part is not None
                await part.take(data)
            pending.clear()
            if part is not None and not in_file and not part.ended:
                part.end()
        parser.finalize()
        if part is None or not part.ended:
            raise BadRequestError(f"Send the file as the `{FILE_FIELD}` field.")
        await part.upload.seek(0)
        poster = fields.get(POSTER_FIELD)
        yield ReceivedMedia(
            file=part.upload.file,
            byte_size=part.size,
            duration_ms=_duration(fields.get(DURATION_FIELD)),
            poster=bytes(poster) if poster else None,
        )
    except MultipartParseError:
        raise BadRequestError("This upload isn't a well-formed multipart form.") from None
    finally:
        if part is not None:
            await part.upload.close()


def _duration(value: Optional[bytearray]) -> Optional[int]:
    if value is None:
        return None
    text = value.decode("ascii", errors="replace").strip()
    if not text.isdigit():
        raise BadRequestError(f"Send `{DURATION_FIELD}` as a whole number of milliseconds.")
    return int(text)

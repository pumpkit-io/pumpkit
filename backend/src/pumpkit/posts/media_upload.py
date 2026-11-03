"""
Receiving a Media file from a multipart upload. The body is read as it streams and refused once
the file is larger than its kind may be, so an oversize upload never lands on disk whole.
"""

from collections.abc import AsyncIterator
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
    SNIFF_BYTES,
    content_type_of,
    kind_of,
    media_too_large,
    media_type_refused,
)

FILE_FIELD = "file"
# Room for the multipart headers and boundaries around the file.
_ENVELOPE_BYTES = 64 * 1024
_SPOOL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ReceivedMedia:
    file: BinaryIO
    # Counted as the body streamed, never taken from a header.
    byte_size: int


class IncomingMedia:
    """A Media file as it arrives, its head sniffed for its kind before the rest is kept."""

    def __init__(self) -> None:
        self.upload = UploadFile(file=cast(BinaryIO, SpooledTemporaryFile(max_size=_SPOOL_BYTES)))
        self.head = b""
        self.max_bytes: Optional[int] = None
        self.size = 0
        self.ended = False

    async def take(self, data: bytes) -> None:
        self.size += len(data)
        if self.max_bytes is None:
            self.head = (self.head + data)[:SNIFF_BYTES]
            if len(self.head) >= SNIFF_BYTES:
                self._limit_by_kind()
        if self.max_bytes is not None and self.size > self.max_bytes:
            raise media_too_large()
        await self.upload.write(data)

    def end(self) -> None:
        if self.max_bytes is None:
            self._limit_by_kind()
        self.ended = True

    def _limit_by_kind(self) -> None:
        content_type = content_type_of(self.head)
        if content_type is None:
            raise media_type_refused()
        self.max_bytes = MAX_BYTES[kind_of(content_type)]


async def receive_media(request: Request) -> AsyncIterator[ReceivedMedia]:
    """
    FastAPI dependency: the upload's `file` field, spooled and rewound. Refuses an upload with no
    file, with any other field, or larger than the most X takes of the file's kind.
    """
    _, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if not boundary:
        raise BadRequestError("Send the file as a multipart upload.")

    part: Optional[IncomingMedia] = None
    pending: list[bytes] = []
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
        nonlocal part, disposition, in_file
        _, field = parse_options_header(disposition)
        disposition = b""
        if field.get(b"name") != FILE_FIELD.encode() or part is not None:
            raise BadRequestError(f"Send one file, as the `{FILE_FIELD}` field, and nothing else.")
        part = IncomingMedia()
        in_file = True

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if in_file:
            pending.append(data[start:end])

    def on_part_end() -> None:
        nonlocal in_file
        in_file = False

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
    most_bytes = max(MAX_BYTES.values()) + _ENVELOPE_BYTES
    read = 0
    try:
        async for chunk in request.stream():
            read += len(chunk)
            if read > most_bytes:
                raise media_too_large()
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
        yield ReceivedMedia(file=part.upload.file, byte_size=part.size)
    except MultipartParseError:
        raise BadRequestError("This upload isn't a well-formed multipart form.") from None
    finally:
        if part is not None:
            await part.upload.close()

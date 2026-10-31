"""
Writes the Author directory's seed data file from the Operator's seed CSV, for a developer to run
once and commit. Every Instance then seeds its directory from that file, without a twitterapi.io
key (migration 0030). Run from `backend/`:

    TWITTERAPI_IO_API_KEY=... uv run python scripts/write_author_seeds.py SEEDS.csv

The CSV has `handle` and `name` columns; any other column is dropped. Each handle's profile is
looked up on twitterapi.io for its photo, and handles that are missing, suspended or private are
left out and listed on stderr. The name stays the CSV's: X's display name is often a slogan.
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from pumpkit.authors.handles import normalize_handle
from pumpkit.authors.x_reader import (
    HandleNotFoundError,
    HandleSuspendedError,
    TwitterApiIoReader,
    XReaderError,
)

OUTPUT = Path(__file__).parents[1] / "alembic" / "data" / "author_seeds.json"
_ATTEMPTS = 4
# twitterapi.io throttles bursts, so lookups run one at a time, a little apart.
_PAUSE_SECONDS = 0.5


async def _look_up(reader: TwitterApiIoReader, handle: str):
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return await reader.look_up_profile(handle)
        except HandleNotFoundError:
            raise
        except XReaderError:
            if attempt == _ATTEMPTS:
                raise
            await asyncio.sleep(5 * attempt)


async def main(csv_path: Path) -> None:
    reader = TwitterApiIoReader()
    seeds: list[dict] = []
    dropped: list[tuple[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    seen: set[str] = set()
    for row in rows:
        handle = normalize_handle(row["handle"])
        if handle in seen:
            dropped.append((handle, "duplicate in the CSV"))
            continue
        seen.add(handle)
        try:
            profile = await _look_up(reader, handle)
        except HandleSuspendedError:
            dropped.append((handle, "suspended"))
            continue
        except HandleNotFoundError:
            dropped.append((handle, "missing"))
            continue
        finally:
            await asyncio.sleep(_PAUSE_SECONDS)
        if profile.protected:
            dropped.append((handle, "private"))
            continue
        name = row["name"].strip() or profile.name
        seeds.append({"handle": handle, "name": name, "photo_url": profile.photo_url})

    OUTPUT.write_text(json.dumps(seeds, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(seeds)} seeds to {OUTPUT}", file=sys.stderr)
    for handle, reason in dropped:
        print(f"Dropped @{handle}: {reason}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write the Author directory's seed data file.")
    parser.add_argument("csv", type=Path)
    asyncio.run(main(parser.parse_args().csv))

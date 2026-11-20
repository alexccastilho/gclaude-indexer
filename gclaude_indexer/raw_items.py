"""`raw_items.jsonl`: the classified items, one JSON object per line.

Classification appends to it (`classification.classify_windows`), the
import reads it whole on every run (`import_items`), and three places
rewrite it: the incremental update drops the items of discarded windows
(`invalidation`), the local engine drops the windows the Rules engine only
stood in for (`engine_local.requeue_fallback_windows`), and opening an old
project reads which windows were already answered (`windows_prep`).

The keys of a line are a recorded contract: projects on disk carry them,
and a key renamed on the way in makes every reader miss the old lines
without any error. They live here so no module spells them on its own.

Read line by line, never whole: on a large collection the file has
gigabytes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import IO

from .paths import RAW_ITEMS_FILE_NAME

FILE_NAME = RAW_ITEMS_FILE_NAME

# Keys read back by something other than the import.
WINDOW = "window"
GROUP = "group"
# Written on the lines of a window the Rules engine classified because the
# model was down, so the next run gives it back to the model.
FALLBACK = "fallback"

# The `files` field: the item's file names joined by `", "`. A name with a
# comma in it reads back as two names.
_FILES_SEPARATOR = ", "


def path_in(output_folder: Path | str) -> Path:
    return Path(output_folder) / FILE_NAME


def files_field(files: Iterable[str]) -> str:
    return _FILES_SEPARATOR.join(files)


def files_from_field(value: object) -> list[str]:
    """The file names of a `files` field, stripped, empty ones dropped."""
    return [name.strip() for name in str(value).split(_FILES_SEPARATOR.strip()) if name.strip()]


def make_line(
    window: str,
    group: str,
    *,
    ref_start,
    ref_end,
    order_start,
    order_end,
    type,
    date,
    author,
    summary,
    has_table,
    has_image,
    engine,
    confidence,
    files: Iterable[str],
) -> dict:
    """One line, keys in the order they are written. The values go as
    given: normalizing them is the caller's job (`classification.
    item_to_dict`). Fields an engine adds (`FALLBACK`) come after these."""
    return {
        WINDOW: window,
        GROUP: group,
        "ref_start": ref_start,
        "ref_end": ref_end,
        "order_start": order_start,
        "order_end": order_end,
        "type": type,
        "date": date,
        "author": author,
        "summary": summary,
        "has_table": has_table,
        "has_image": has_image,
        "engine": engine,
        "confidence": confidence,
        "files": files_field(files),
    }


def open_for_append(path: Path) -> IO[str]:
    return open(path, "a", encoding="utf-8")


def append(file: IO[str], line: dict) -> None:
    file.write(json.dumps(line, ensure_ascii=False) + "\n")


def iter_lines(path: Path) -> Iterator[tuple[int, str]]:
    """`(line number, text)` of each non-blank line, stripped, read one at a
    time. Numbers count the blank lines too, so they match an editor's.

    Lines end at `\\n` only (after the usual `\\r\\n` translation): never
    `str.splitlines()`, which also breaks on U+0085, U+2028 and U+2029, and
    `json.dumps(ensure_ascii=False)` leaves those unescaped inside strings.
    Text from HTML decoded as latin-1 carries U+0085, and each one cut an
    item in two "corrupt" lines (1.5.9)."""
    with open(path, encoding="utf-8") as file:
        for number, text in enumerate(file, start=1):
            text = text.strip()
            if text:
                yield number, text


def parse(text: str) -> dict | None:
    """The line as a dict, or `None` when it is not a JSON object."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def prune(path: Path, is_stale: Callable[[dict], bool], *, temporary_suffix: str = ".tmp") -> int:
    """Drops the lines `is_stale` accepts. Returns how many were dropped.

    Only a line that parses as an object and that `is_stale` accepts goes:
    unparseable and blank lines stay, because the import already reports
    them and quietly deleting what cannot be read is not this function's
    call. The kept lines are copied byte for byte (`newline=""` on both
    sides), without their line endings rewritten.

    The new file is written beside the real one and renamed over it only
    once complete: a half-written file would lose the items of windows that
    are still valid, and those exist nowhere else. With nothing to drop the
    file is left as it was. On any failure the temporary file goes and the
    error is raised (`ValueError` includes `UnicodeDecodeError` from a
    corrupted file)."""
    if not path.exists():
        return 0
    temporary = path.with_name(path.name + temporary_suffix)
    dropped = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as source, open(
            temporary, "w", encoding="utf-8", newline=""
        ) as target:
            for text in source:
                line = parse(text)
                if line is not None and is_stale(line):
                    dropped += 1
                else:
                    target.write(text)

        if dropped:
            temporary.replace(path)
        else:
            temporary.unlink(missing_ok=True)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dropped

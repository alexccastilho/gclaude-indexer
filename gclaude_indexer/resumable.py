# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Intermediates that take long enough to be stopped halfway and resumed.

An Outlook archive or an hour of audio is converted page by page into
`<destination>.partial`, and `<destination>.progress` records how far it
got. Stop keeps both; the next conversion goes on from there, as long as
the source file is the same (size and modification time) and the partial
still holds the bytes the progress counts. Only the finished text is moved
to `<destination>`, so a half-written file is never read as a whole one.

The `.progress` format is what earlier versions wrote: a conversion stopped
before an upgrade resumes after it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .light_formats import MBOX_PAGE_SEPARATOR

PROGRESS_SUFFIX = ".progress"
PARTIAL_SUFFIX = ".partial"
MAX_PAGE_CHARS = 2_000_000


class Interrupted(Exception):
    """Parar foi pedido; o progresso já está gravado."""


def partial_path(destination: Path) -> Path:
    return destination.with_name(destination.name + PARTIAL_SUFFIX)


def progress_path(destination: Path) -> Path:
    return destination.with_name(destination.name + PROGRESS_SUFFIX)


def read_progress(destination: Path, source: Path, **must_match) -> dict | None:
    """The saved progress, when it still describes this source file, these
    `must_match` values (the transcription model, say) and a partial that
    has the bytes it counts; otherwise `None`. The caller reads its own
    fields from the returned dict (a missing or malformed one: `None` too,
    when it raises `KeyError`, `TypeError` or `ValueError` there)."""
    try:
        data = json.loads(progress_path(destination).read_text(encoding="utf-8"))
        stat = source.stat()
        if (
            data["size"] == stat.st_size and data["mtime_ns"] == stat.st_mtime_ns
            and all(data[key] == value for key, value in must_match.items())
            and partial_path(destination).stat().st_size >= data["bytes"]
        ):
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def write_progress(destination: Path, source: Path, **fields) -> None:
    """Records the progress atomically: a stop in the middle of the write
    leaves the previous one."""
    stat = source.stat()
    progress = progress_path(destination)
    temporary = progress.with_name(progress.name + ".tmp")
    temporary.write_text(
        json.dumps({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, **fields}), encoding="utf-8",
    )
    os.replace(temporary, progress)


def discard(destination: Path) -> None:
    partial_path(destination).unlink(missing_ok=True)
    progress_path(destination).unlink(missing_ok=True)


class PageWriter:
    """Appends pages to the partial from where the saved progress left it.

    The form feed separates pages in the intermediate, so it never stays
    inside one; and no page grows past `MAX_PAGE_CHARS` (a third-party file
    must not exhaust memory)."""

    def __init__(self, destination: Path, size: int = 0, pages: int = 0) -> None:
        self.size = size
        self.pages = pages
        self._handle = open(partial_path(destination), "ab")
        self._handle.truncate(size)
        self._handle.seek(size)

    def write(self, text: str) -> None:
        page = text.replace("\x0c", " ")[:MAX_PAGE_CHARS]
        chunk = ((MBOX_PAGE_SEPARATOR if self.pages else "") + page).encode("utf-8")
        self._handle.write(chunk)
        self.size += len(chunk)
        self.pages += 1

    def flush(self) -> None:
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> PageWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def finish(destination: Path, pages: int) -> int:
    """Moves the finished partial to `destination` and drops the progress.
    Nothing written (an empty mailbox, only silence): one empty page, as an
    empty file. Returns the page count."""
    partial = partial_path(destination)
    if pages == 0:
        partial.write_text("", encoding="utf-8")
        pages = 1
    os.replace(partial, destination)
    try:
        progress_path(destination).unlink(missing_ok=True)
    except OSError:
        pass  # preso pelo Drive: a próxima conversão o descarta pela origem
    return pages

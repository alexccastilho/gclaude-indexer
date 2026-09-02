# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Telling the user when the running server is older than the code on disk.

Python loads a module into memory once, when the process starts. Editing
the file afterwards changes nothing for a server already running — it goes
on executing what it read at startup, indefinitely, with no outward sign.

That is not a theoretical concern here. It happened: a server started at
02:09 was still running at 08:03 with code that had been corrected at
05:40, and it spent those hours producing an index with a defect that had
already been fixed. The only clue was a log line the user happened to read
and find odd. Nothing on any screen said the two were out of step.

**Compared by content, not by modification time.** The project folder is
synced by Google Drive, and a sync client rewrites timestamps on files
whose bytes never changed — comparing dates would cry wolf often enough to
be ignored, which is the worst thing a warning can be. Hashing every `.py`
in the package costs a few milliseconds on some 300 KB and never reports a
change that is not real.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Fingerprint of the source as it was when this process loaded it. Filled
# in by `record_loaded_source()` at server startup; `None` means nobody
# recorded it, and `is_stale()` then answers `False` rather than guessing.
_loaded_fingerprint: str | None = None


def _package_folder() -> Path:
    return Path(__file__).resolve().parent


def source_fingerprint() -> str:
    """A hash of every `.py` in the package, as it is on disk right now.

    Sorted by path so the result depends on the content and not on the
    order the filesystem happens to return. Unreadable files are skipped
    rather than raising: this runs on a synced folder, where a file can be
    briefly locked, and a warning that crashes the page it warns on would
    be worse than no warning.
    """
    digest = hashlib.sha256()
    for path in sorted(_package_folder().rglob("*.py")):
        try:
            digest.update(path.relative_to(_package_folder()).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()


def record_loaded_source() -> str:
    """Records the fingerprint of what this process is running.

    Called once, at server startup, after the modules are imported — so it
    describes the code actually in memory.
    """
    global _loaded_fingerprint
    _loaded_fingerprint = source_fingerprint()
    return _loaded_fingerprint


def loaded_fingerprint() -> str | None:
    return _loaded_fingerprint


def is_stale() -> bool:
    """Whether the code on disk differs from what this server is running.

    `False` when nothing was recorded (a test, an embedding caller): an
    unanswerable question is not a reason to put a warning on the screen.
    Never raises.
    """
    if _loaded_fingerprint is None:
        return False
    try:
        return source_fingerprint() != _loaded_fingerprint
    except Exception:
        return False

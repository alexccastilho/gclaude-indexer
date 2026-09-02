# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Scan of the source folder (section 5, step 1 of the specification).

Walks the source folder recursively, computes each file's hash, derives the
group key according to the configuration, and writes the inventory to the
`file` table. A file with no content change under the same path is only
recounted (idempotency — acceptance criteria 1 and 2). A file whose content
already exists under another path is written with `status = 'duplicate'`
(not reprocessed, but present in the inventory — without this row, the
progress bar never reached 100%). An extension outside the configured list
is marked `skipped`, with an event.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .file_types import is_extension_allowed

HASH_BLOCK_SIZE = 1024 * 1024


@dataclass
class ScanResult:
    total_found: int = 0
    discovered: int = 0
    updated: int = 0
    ignored: int = 0
    skipped: int = 0


def compute_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(HASH_BLOCK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_group_key(relative_path: str, source_dir: Path, config: ProjectConfig) -> str | None:
    """Derives the file's group key according to `config.group_mode`."""
    parts = Path(relative_path).parts

    if config.group_mode == "all_together":
        return source_dir.name

    if config.group_mode == "subfolder":
        # More than one segment: the first is the immediate subfolder. A
        # file loose at the root of the source folder forms its own group.
        return parts[0] if len(parts) > 1 else source_dir.name

    if config.group_mode == "name_pattern":
        name = Path(relative_path).name
        match = re.search(config.group_pattern, name)
        if not match:
            return None
        if match.groups():
            return match.group(1)
        return match.group(0)

    raise ValueError(f"unknown group_mode: {config.group_mode!r}")


def _list_known_files(conn: sqlite3.Connection) -> tuple[set[str], dict[str, sqlite3.Row]]:
    rows = conn.execute("SELECT relative_path, sha256 FROM file").fetchall()
    known_hashes = {row["sha256"] for row in rows}
    by_path = {row["relative_path"]: row for row in rows}
    return known_hashes, by_path


def _insert_file(
    conn: sqlite3.Connection,
    relative_path: str,
    name: str,
    extension: str,
    size: int,
    file_hash: str,
    group_key: str | None,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO file
            (relative_path, name, extension, size, sha256, group_key, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (relative_path, name, extension, size, file_hash, group_key, status),
    )


def _update_file(
    conn: sqlite3.Connection,
    relative_path: str,
    name: str,
    extension: str,
    size: int,
    file_hash: str,
    group_key: str | None,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE file
        SET name = ?, extension = ?, size = ?, sha256 = ?, group_key = ?,
            status = ?, error = NULL, page_count = NULL, needs_ocr = 0
        WHERE relative_path = ?
        """,
        (name, extension, size, file_hash, group_key, status, relative_path),
    )


# Files the operating system, the sync client or an editor writes into a
# folder without anyone putting them there. Matched by exact name (lower
# case) or by prefix, and never indexed.
_SYSTEM_FILE_NAMES = frozenset({
    "desktop.ini", "thumbs.db", "ehthumbs.db", ".ds_store",
    ".dropbox", ".dropbox.attr", "albumartsmall.jpg",
    ".dropbox", ".dropbox.attr", "folder.jpg", "albumartsmall.jpg",
})
_SYSTEM_FILE_PREFIXES = ("~$", ".~lock.", "albumart_")


def is_system_file(path: Path) -> bool:
    """Whether `path` is operating-system or sync bookkeeping.

    Deliberately a small, explicit list rather than a rule like "hidden
    files": a collection can legitimately contain a document whose name
    starts with a dot, and refusing to index it because of that would be a
    silent loss of the user's own material. Everything here is a file no
    person put in the folder.
    """
    name = path.name.lower()
    if name in _SYSTEM_FILE_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _SYSTEM_FILE_PREFIXES)


def scan(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    should_stop: Callable[[], bool] | None = None,
    language: str | None = None,
) -> ScanResult:
    """`should_stop`: a no-argument function returning True to cooperatively
    interrupt between one file and the next (see `run_control.py`) —
    the step is resumable, so stopping here loses nothing.

    `language`: interface language for the events recorded here (Task 12,
    Phase 14) — falls back to `DEFAULT_LANGUAGE` in `record_event` itself
    when not given."""
    source_dir = Path(config.source_folder).resolve()
    output_dir = Path(config.output_folder).resolve()

    known_hashes, known_paths = _list_known_files(conn)

    result = ScanResult()

    paths = sorted(
        (path for path in source_dir.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(source_dir)).lower(),
    )

    for path in paths:
        if should_stop is not None and should_stop():
            break

        if path.is_relative_to(output_dir):
            continue

        if is_system_file(path):
            # Bookkeeping the operating system and the sync client leave
            # behind, never part of the collection. They slip in through
            # the "all extensions" option, and a real run turned a
            # `desktop.ini` into item number one of an index of course
            # material, summarised as "operating system configuration
            # file". Skipped before `total_found` so the count reflects
            # documents, not clutter.
            continue

        result.total_found += 1

        relative_path = path.relative_to(source_dir).as_posix()
        name = path.name
        extension = path.suffix.lower()
        size = path.stat().st_size
        file_hash = compute_hash(path)

        existing_row = known_paths.get(relative_path)

        if existing_row is not None and existing_row["sha256"] == file_hash:
            result.skipped += 1
            continue

        if existing_row is None and file_hash in known_hashes:
            # Same content already indexed under another path (copy/duplicate).
            # It enters the table with status = 'duplicate' instead of vanishing:
            # without this row, the progress bar's numerator (COUNT(*) FROM
            # file) never reached the denominator (count of files in the
            # folder), and the bar stalled below 100%. `conversion.py` only
            # selects 'discovered' and `extraction.py` only selects
            # 'converted'/'extracted' — neither picks up 'duplicate', which
            # stays out of processing as before, only visible in the
            # inventory.
            extension_no_dot = extension.lstrip(".")
            _insert_file(
                conn, relative_path, name, extension_no_dot, size, file_hash, None, "duplicate"
            )
            result.skipped += 1
            conn.commit()
            known_hashes.add(file_hash)
            known_paths[relative_path] = {"relative_path": relative_path, "sha256": file_hash}
            continue

        allowed = is_extension_allowed(extension, config.extensions)
        status = "discovered" if allowed else "skipped"
        group_key = (
            derive_group_key(relative_path, source_dir, config) if allowed else None
        )
        extension_no_dot = extension.lstrip(".")

        if existing_row is None:
            _insert_file(
                conn, relative_path, name, extension_no_dot, size, file_hash, group_key, status
            )
            if allowed:
                result.discovered += 1
            else:
                result.ignored += 1
                record_event(
                    conn,
                    "scan",
                    "warning",
                    "log.scan.extension_not_allowed",
                    {"name": name, "extension": extension_no_dot},
                    language=language,
                )
        else:
            _update_file(
                conn, relative_path, name, extension_no_dot, size, file_hash, group_key, status
            )
            result.updated += 1
            record_event(
                conn, "scan", "warning", "log.scan.content_changed", {"name": name}, language=language
            )

        # Commit per file (not just at the end): without this, the Execution
        # screen's progress bar — which reads from a separate connection —
        # saw no new row until the whole scan finished, staying stuck at 0%
        # on large source folders.
        conn.commit()

        known_hashes.add(file_hash)
        known_paths[relative_path] = {"relative_path": relative_path, "sha256": file_hash}

    conn.commit()

    record_event(
        conn,
        "scan",
        "info",
        "log.scan.summary",
        {
            "new": result.discovered, "updated": result.updated,
            "ignored": result.ignored, "unchanged": result.skipped,
        },
        language=language,
    )

    return result

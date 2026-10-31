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
recounted (idempotency — acceptance criteria 1 and 2); when its size and
modification time match the inventory, its bytes are not even read. A file whose content
already exists under another path is written with `status = 'duplicate'`
(not reprocessed, but present in the inventory — without this row, the
progress bar never reached 100%). An extension outside the configured list
is marked `skipped`, with an event.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .db import BatchWriter
from .events import record_event
from .file_types import is_extension_allowed
from .i18n import DEFAULT_LANGUAGE, translate
from .worker_pool import CallTimedOut, StepStalledError, call_with_deadline, deadline_for_size

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
    rows = conn.execute("SELECT relative_path, size, sha256, mtime FROM file").fetchall()
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
    mtime: float,
    group_key: str | None,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO file
            (relative_path, name, extension, size, sha256, mtime, group_key, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (relative_path, name, extension, size, file_hash, mtime, group_key, status),
    )
    # Back in the folder, so no longer "removed" — otherwise `review.md`
    # would go on listing a document that is right there in the index.
    conn.execute("DELETE FROM removed_file WHERE relative_path = ?", (relative_path,))


def _update_file(
    conn: sqlite3.Connection,
    relative_path: str,
    name: str,
    extension: str,
    size: int,
    file_hash: str,
    mtime: float,
    group_key: str | None,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE file
        SET name = ?, extension = ?, size = ?, sha256 = ?, mtime = ?, group_key = ?,
            status = ?, error = NULL, page_count = NULL, needs_ocr = 0
        WHERE relative_path = ?
        """,
        (name, extension, size, file_hash, mtime, group_key, status, relative_path),
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

    Bookkeeping files (such as desktop.ini) that slip in through the "all
    extensions" option are never indexed; a real run turned a `desktop.ini`
    into item number one of an index of course material, summarised as
    "operating system configuration file".
    """
    name = path.name.lower()
    if name in _SYSTEM_FILE_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _SYSTEM_FILE_PREFIXES)


FOLDER_LISTING_DEADLINE_SECONDS = 600.0
STAT_DEADLINE_SECONDS = 600.0
MAX_CONSECUTIVE_TIMEOUTS = 3


class SourceFolderStalled(RuntimeError):
    """A folder of the collection never answered its listing, twice.

    Raised, never skipped: a walk that left a folder out would describe a
    collection without those files, and the update plan reads a missing
    file as a removed one."""

    def __init__(self, folder: Path):
        super().__init__(str(folder))
        self.folder = folder


def _list_folder(folder: Path) -> list[os.DirEntry]:
    """`os.scandir(folder)` with a deadline (1.5.6). A Google Drive folder
    that never answers its listing froze the walk, and with it the scan's
    count, for good. One retry, on a fresh thread, then
    `SourceFolderStalled`."""
    for attempt in (1, 2):
        try:
            return call_with_deadline(
                lambda: list(os.scandir(folder)), deadline=FOLDER_LISTING_DEADLINE_SECONDS,
            )
        except CallTimedOut:
            if attempt == 2:
                raise SourceFolderStalled(folder) from None
    raise AssertionError("unreachable")


def walk_source_files(
    source_dir: Path,
    output_dir: Path,
    on_found: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[tuple[Path, int]]:
    """`(path, size)` of every file of the collection, in the order the scan
    walks them.

    `os.scandir` rather than `rglob` + `stat`: on Windows the directory
    listing already carries each file's size, and on a Google Drive folder
    of 145,000 files the extra `stat` per file is what turns the walk into
    minutes. `on_found(n)` is called with the running count after each file
    — the Execution screen shows it, so a long walk never looks frozen.
    `should_stop` interrupts the walk (pause); what was found so far is
    returned.
    """
    output_dir = output_dir.resolve()
    found: list[tuple[Path, int]] = []
    pending = [source_dir]
    while pending:
        if should_stop is not None and should_stop():
            break
        current = pending.pop()
        if current.resolve() == output_dir:
            continue
        try:
            entries = _list_folder(current)
        except OSError:
            continue  # unreadable folder: same as `rglob`, which skips it
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file():
                    continue
                size = entry.stat().st_size
            except OSError:
                continue
            path = Path(entry.path)
            if is_system_file(path):
                continue
            found.append((path, size))
            if on_found is not None:
                on_found(len(found))
    found.sort(key=lambda item: str(item[0].relative_to(source_dir)).lower())
    return found


def source_files(source_dir: Path, output_dir: Path) -> list[Path]:
    """Files of the collection, in the order the scan walks them.

    Extracted from `scan()` (Phase 17) so the update plan
    (`update_plan.py`) walks by exactly the same criteria. Two walks that
    disagree would make the plan describe a folder the scan does not see.
    """
    return [path for path, _size in walk_source_files(source_dir, output_dir)]


def scan(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    should_stop: Callable[[], bool] | None = None,
    language: str | None = None,
    files: list[Path] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """`should_stop`: a no-argument function returning True to cooperatively
    interrupt between one file and the next (see `run_control.py`) —
    the step is resumable, so stopping here loses nothing.

    `language`: interface language for the events recorded here (Task 12,
    Phase 14) — falls back to `DEFAULT_LANGUAGE` in `record_event` itself
    when not given.

    `files`: the walk already made by the caller (`walk_source_files`, in
    order), so a large folder is not walked a second time before the
    first file is hashed. `None` walks it here.

    `on_progress(files_done, bytes_done)`: called before each file and once
    at the end, so the progress bar can follow a scan that adds no rows —
    a second scan of an unchanged folder, which the row count saw as
    "0 / N" from start to finish."""
    source_dir = Path(config.source_folder).resolve()
    output_dir = Path(config.output_folder).resolve()

    known_hashes, known_paths = _list_known_files(conn)

    result = ScanResult()

    if files is None:
        files = source_files(source_dir, output_dir)

    writer = BatchWriter(conn)
    try:
        _scan_files(
            writer, conn, config, source_dir, files, known_hashes, known_paths, result,
            should_stop, language, on_progress,
        )
        writer.flush()
    except BaseException as exc:
        if isinstance(exc, sqlite3.Error):
            writer.discard()
        else:
            try:
                writer.flush()  # what was already checked stays checked
            except Exception:
                writer.discard()
        raise

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


def _scan_files(
    writer: BatchWriter, conn, config: ProjectConfig, source_dir: Path, files, known_hashes, known_paths,
    result: ScanResult, should_stop, language, on_progress,
) -> None:
    """The scan's loop. 1.5.6: every call that touches a file (`stat`, the
    hash) has a deadline, so a file Google Drive never answers costs that
    file, not the scan; writes go through `BatchWriter` (see `db.py`)."""
    bytes_done = 0
    consecutive_timeouts = 0

    for path in files:
        if should_stop is not None and should_stop():
            break

        if on_progress is not None:
            on_progress(result.total_found, bytes_done)

        result.total_found += 1

        relative_path = path.relative_to(source_dir).as_posix()
        name = path.name
        extension = path.suffix.lower()
        try:
            file_stat = call_with_deadline(path.stat, deadline=STAT_DEADLINE_SECONDS)
            size = file_stat.st_size
            mtime = file_stat.st_mtime
            existing_row = known_paths.get(relative_path)
            unchanged = (
                existing_row is not None
                and existing_row["size"] == size
                and existing_row["mtime"] == mtime
            )
            file_hash = None if unchanged else call_with_deadline(
                compute_hash, path, deadline=deadline_for_size(size),
            )
        except CallTimedOut as timeout:
            # Left out of this scan, untouched in the inventory: the next
            # scan looks at it again. Several in a row with nothing in
            # between is the drive, not the file — stop instead of walking
            # the whole collection one deadline at a time.
            consecutive_timeouts += 1
            minutes = max(1, round(timeout.args[0] / 60))
            writer.add(lambda c, name=name, minutes=minutes: record_event(
                c, "scan", "warning", "log.scan.file_timed_out", {"name": name, "minutes": minutes},
                language=language, commit=False,
            ))
            if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                raise StepStalledError(
                    translate(language or DEFAULT_LANGUAGE, "log.pool_stalled", name=name)
                ) from None
            continue
        consecutive_timeouts = 0
        bytes_done += size

        if unchanged:
            result.skipped += 1
            writer.flush_if_due()
            continue

        _record_scanned_file(
            writer, config, source_dir, relative_path, name, extension, size, mtime, file_hash,
            existing_row, known_hashes, known_paths, result, language,
        )

    if on_progress is not None:
        on_progress(result.total_found, bytes_done)


def _record_scanned_file(
    writer: BatchWriter, config: ProjectConfig, source_dir: Path, relative_path: str, name: str,
    extension: str, size: int, mtime: float, file_hash: str, existing_row, known_hashes, known_paths,
    result: ScanResult, language,
) -> None:
    """Records one hashed file. (Same size and time under the same path
    never gets here: unchanged without reading the bytes — the rule
    `update_plan.detect_changes` already follows. Hashing every file on
    every scan made a second scan of a 145,000-file Google Drive folder
    reopen each file one by one, for hours, only to learn nothing had
    changed.)

    Every write is a `writer.add` op; `known_hashes`/`known_paths` are
    updated here, in memory, once, so a replayed batch cannot double them."""
    if existing_row is not None and existing_row["sha256"] == file_hash:
        result.skipped += 1
        # The one write on the unchanged path, and it is not about
        # correctness: `file.mtime` is what lets `update_plan` decide
        # a file is unchanged without reading its bytes. Only the
        # insert and update branches below ever wrote it, so a
        # project created by 1.0.1 kept `mtime` NULL forever — the
        # scan skips unchanged files and the plan is read-only —
        # and every open of the Execution screen re-hashed the whole
        # collection, pulling a Drive-synced acervo down byte by
        # byte. The same applies to any single file whose mtime Drive
        # rewrote without changing the content: the mismatch would be
        # permanent. §8.1 promises "da segunda em diante a detecção é
        # rápida"; this is what delivers it.
        # `size` too: Google Drive can answer `st_size = 16384` right
        # after a file is written. A wrong size stored once would send
        # the file down this hashing path on every scan.
        if existing_row["mtime"] != mtime or existing_row["size"] != size:
            writer.add(lambda c: c.execute(
                "UPDATE file SET mtime = ?, size = ? WHERE relative_path = ?",
                (mtime, size, relative_path),
            ))
        return

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
        writer.add(lambda c: _insert_file(
            c, relative_path, name, extension_no_dot, size, file_hash,
            mtime, None, "duplicate"
        ))
        result.skipped += 1
        known_hashes.add(file_hash)
        known_paths[relative_path] = {
            "relative_path": relative_path, "size": size, "sha256": file_hash, "mtime": mtime,
        }
        return

    allowed = is_extension_allowed(extension, config.extensions)
    status = "discovered" if allowed else "skipped"
    group_key = (
        derive_group_key(relative_path, source_dir, config) if allowed else None
    )
    extension_no_dot = extension.lstrip(".")

    if existing_row is None:
        def op(c) -> None:
            _insert_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, group_key, status
            )
            if not allowed:
                record_event(
                    c,
                    "scan",
                    "warning",
                    "log.scan.extension_not_allowed",
                    {"name": name, "extension": extension_no_dot},
                    language=language,
                    commit=False,
                )

        if allowed:
            result.discovered += 1
        else:
            result.ignored += 1
    else:
        def op(c) -> None:
            _update_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, group_key, status
            )
            record_event(
                c, "scan", "warning", "log.scan.content_changed", {"name": name},
                language=language, commit=False,
            )

        result.updated += 1

    # Committed within a second (`BatchWriter`), not only at the end:
    # the Execution screen's progress bar reads from a separate
    # connection and must see the new rows while the scan runs.
    writer.add(op)

    known_hashes.add(file_hash)
    known_paths[relative_path] = {
        "relative_path": relative_path, "size": size, "sha256": file_hash, "mtime": mtime,
    }

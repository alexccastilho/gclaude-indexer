# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Comparing the source folder with the index, without writing anything.

Phase 17. The plan is the read-only half of the update: it answers "what
changed in the folder, and what would that cost", and nothing it does can
alter the project. That is what lets it run every time the Execution
screen opens.

**Detection is cheap on purpose.** Hashing every file of a Drive-synced
collection on each open would force the client to download files the user
never asked for. Size and modification time decide first; the hash is
computed only for the few candidates that differ. The hash still has the
last word, because Drive rewrites the modification time of files whose
bytes never changed — the same lesson already recorded in `staleness.py`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .scanning import compute_hash, source_files


class SourceFolderUnavailable(RuntimeError):
    """The source folder cannot be read, so no plan can be trusted.

    Without this the plan would read an unreachable folder as "every
    document was removed" and offer to delete the whole index. A
    disconnected Drive, a moved folder or a changed drive letter must
    never reach the confirmation screen as a removal.
    """


@dataclass(frozen=True)
class FileChange:
    relative_path: str
    kind: str  # "new" | "changed" | "removed"
    name: str
    size: int


def _fingerprint(entries: list[tuple[str, int, float]]) -> str:
    """Cheap identity of the folder as the plan saw it.

    Re-checked before the invalidation writes: applying a plan built from
    a folder that has since changed would write one thing having shown
    another.
    """
    digest = hashlib.sha256()
    for relative_path, size, mtime in sorted(entries):
        digest.update(f"{relative_path}|{size}|{mtime:.6f}\n".encode("utf-8"))
    return digest.hexdigest()


def detect_changes(
    conn, config: ProjectConfig
) -> tuple[list[FileChange], int, str]:
    """New, changed and removed files; how many are unchanged; and the
    folder's fingerprint.

    Raises `SourceFolderUnavailable` when the source folder is missing, or
    empty while the index is not.
    """
    source_dir = Path(config.source_folder)
    if not source_dir.is_dir():
        raise SourceFolderUnavailable(str(source_dir))

    output_dir = Path(config.output_folder).resolve()
    paths = source_files(source_dir.resolve(), output_dir)

    known = {
        row["relative_path"]: row
        for row in conn.execute("SELECT relative_path, size, sha256, mtime FROM file")
    }

    if not paths and known:
        raise SourceFolderUnavailable(str(source_dir))

    changes: list[FileChange] = []
    unchanged = 0
    entries: list[tuple[str, int, float]] = []
    seen: set[str] = set()

    for path in paths:
        relative_path = path.relative_to(source_dir.resolve()).as_posix()
        stat = path.stat()
        entries.append((relative_path, stat.st_size, stat.st_mtime))
        seen.add(relative_path)

        row = known.get(relative_path)
        if row is None:
            changes.append(FileChange(relative_path, "new", path.name, stat.st_size))
            continue

        if row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
            unchanged += 1
            continue

        # Size or time moved. Only now is reading the bytes worth it.
        if compute_hash(path) == row["sha256"]:
            unchanged += 1
            continue

        changes.append(FileChange(relative_path, "changed", path.name, stat.st_size))

    for relative_path in sorted(set(known) - seen):
        changes.append(
            FileChange(relative_path, "removed", Path(relative_path).name, 0)
        )

    return changes, unchanged, _fingerprint(entries)

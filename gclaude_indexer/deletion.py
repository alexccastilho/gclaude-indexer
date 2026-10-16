# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Project deletion (explicit user request): takes the project out of the
local catalog and, optionally, also deletes everything generated in the
output folder — including the folder itself.

Never touches the source folder: only the output folder
(`config.output_folder`) is a candidate for deletion, and only when
`delete_files=True`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .catalog import CatalogEntry, remove_project
from .managed_block import BACKUP_SUFFIX, without_managed_block

PROJECT_DB_NAME = "project.db"

# Everything the system writes into an output folder — and only that. The
# folder itself can be one the user picked with their own files in it.
GENERATED_FOLDERS = ("converted", "blocks", "windows", "logs")
GENERATED_FILES = (
    "project.db", "project.db-journal", "project.db-wal", "project.db-shm",
    "project.lock", "raw_items.jsonl",
    "index.md", "index-*.md", "timeline.md", "review.md",
)
SHARED_FILES = ("project_instructions.md", "CLAUDE.md")


@dataclass
class DeletionResult:
    folder_deleted: bool
    folder: str | None


def delete_project(entry: CatalogEntry, delete_files: bool) -> DeletionResult:
    """Removes `entry` from the catalog and, if `delete_files`, deletes
    the whole output folder with `shutil.rmtree`. Call only after
    closing/releasing the sqlite connection and this folder's lock (Windows
    will not let you delete an open file)."""
    remove_project(entry.id)

    if not delete_files:
        return DeletionResult(folder_deleted=False, folder=None)

    folder = Path(entry.output_folder)
    # No `project.db`, no project: whatever this folder is (Documents, the
    # source folder, a path a shared catalog was tampered into pointing
    # at), the system did not create it and deletes nothing there.
    if not (folder / PROJECT_DB_NAME).is_file():
        return DeletionResult(folder_deleted=False, folder=None)

    for name in GENERATED_FOLDERS:
        path = folder / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
    for pattern in GENERATED_FILES:
        for path in folder.glob(pattern):
            if path.is_file():
                _remove_quietly(path)
    for name in SHARED_FILES:
        _strip_generated_block(folder / name)

    # Only an emptied folder goes: anything the user kept in it stays,
    # and so does the folder holding it.
    try:
        folder.rmdir()
    except OSError:
        pass

    return DeletionResult(folder_deleted=True, folder=str(folder))


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _strip_generated_block(path: Path) -> None:
    """Instruction files are shared with the user (see `managed_block.py`):
    the generated block goes, their own text stays. A file left with
    nothing but the block was entirely ours and is deleted."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    remaining = without_managed_block(text)
    if remaining.strip():
        if remaining != text:
            path.write_text(remaining, encoding="utf-8")
    else:
        _remove_quietly(path)
    _remove_quietly(path.with_name(path.name + BACKUP_SUFFIX))

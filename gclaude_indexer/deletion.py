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

from . import workdir
from .catalog import CatalogEntry, remove_project
from .events import LOG_FOLDER_NAME
from .lock import LOCK_FILE_NAME
from .managed_block import BACKUP_SUFFIX, without_managed_block
from .output_names import (
    CLAUDE_MD_FILENAME,
    GROUP_INDEX_GLOB,
    GROUP_TIMELINE_GLOB,
    INDEX_FILENAME,
    LEGACY_LEGISLATION_GLOB,
    NORMS_FILENAME,
    PROJECT_DB_SIDECARS,
    PROJECT_INSTRUCTIONS_FILENAME,
    REVIEW_FILENAME,
    SEARCH_LAUNCHER_FILENAME,
    TIMELINE_FILENAME,
)
from .paths import PROJECT_DB_NAME, RAW_ITEMS_FILE_NAME


# Everything the system writes into an output folder — and only that. The
# folder itself can be one the user picked with their own files in it.
GENERATED_FOLDERS = (workdir.CONVERTED_FOLDER, workdir.BLOCKS_FOLDER, "windows", LOG_FOLDER_NAME)
GENERATED_FILES = (
    PROJECT_DB_NAME, *PROJECT_DB_SIDECARS,
    LOCK_FILE_NAME, RAW_ITEMS_FILE_NAME,
    INDEX_FILENAME, GROUP_INDEX_GLOB, TIMELINE_FILENAME, REVIEW_FILENAME,
    # Fase 31: a legislação do Planalto e a cronologia por grupo. Sem
    # estes, "excluir com os arquivos" deixava a pasta de saída de pé.
    # Fase 38: `legislacao-*.md` fica só para apagar o que versões antigas
    # deixaram; `normas-citadas.md` é o que o substituiu.
    LEGACY_LEGISLATION_GLOB, GROUP_TIMELINE_GLOB, NORMS_FILENAME, SEARCH_LAUNCHER_FILENAME,
)
SHARED_FILES = (PROJECT_INSTRUCTIONS_FILENAME, CLAUDE_MD_FILENAME)


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
    # The intermediates this machine kept for the project.
    local = workdir.work_folder(folder)
    if local.is_dir() and not local.is_symlink():
        shutil.rmtree(local, ignore_errors=True)
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
    # And the dated copies left when the update screen replaced the
    # user's part (`managed_block.replace_user_part`).
    for backup in path.parent.glob(f"{path.name}.*{BACKUP_SUFFIX}"):
        _remove_quietly(backup)

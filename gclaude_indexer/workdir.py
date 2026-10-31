# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Where a project's intermediate files live (1.5.8).

`converted/` (the OCR'd PDFs and each file's extracted text) and `blocks/`
(the slices of large PDFs) used to sit in the output folder. That folder is
normally inside Google Drive, and Drive creates files almost one at a time:
measured on a real collection, ~800 ms to write each small `.txt`, against
0.3 ms on the local disk — the whole conversion of 144 thousand HTML files
was waiting on it with the CPU idle.

They now go to a per-machine work folder,
`%LOCALAPPDATA%\\GClaudeIndexer\\work\\<key>\\`, where `<key>` is derived
from the output folder's path. Nothing the user takes away from a project
needs them: the pages and the full-text search are in `project.db`, the
indexes are `.md` files in the output folder, and the windows the Claude
Code engine reads stay there too. On another computer a file whose
intermediate is missing is simply converted again when it is needed.

Projects converted before 1.5.8 keep their intermediates in the output
folder; `intermediate_path` still finds them there, so nothing is redone.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .paths import machine_local_folder

INTERMEDIATE_SUBFOLDERS: tuple[str, ...] = ("converted", "blocks")
WORK_FOLDER_NAME = "work"
ORIGIN_FILE_NAME = "origin.txt"


def _normalized(output_folder: str | Path) -> str:
    path = os.path.normpath(os.path.abspath(str(output_folder)))
    return os.path.normcase(path)


def work_folder(output_folder: str | Path) -> Path:
    """The local folder holding this project's intermediates.

    Keyed by the output folder's path, not by the project's id in the
    catalog: the id is per machine, the path is what identifies the
    project's files. `origin.txt` inside says which project it belongs to,
    for whoever opens the folder by hand."""
    normalized = _normalized(output_folder)
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    name = Path(normalized).name or "project"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "project"
    return work_root() / f"{safe[:40]}-{key}"


WORK_FOLDER_ENV = "GCLAUDE_INDEXER_WORK_FOLDER"


def work_root() -> Path:
    r"""`%LOCALAPPDATA%\GClaudeIndexer\work`, or the folder named by
    `GCLAUDE_INDEXER_WORK_FOLDER` (the test suite points it at a temporary
    folder; it is read from the environment so the conversion's worker
    processes see it too)."""
    override = os.environ.get(WORK_FOLDER_ENV, "").strip()
    if override:
        return Path(override)
    return machine_local_folder() / WORK_FOLDER_NAME


def ensure_work_folder(output_folder: str | Path) -> Path:
    folder = work_folder(output_folder)
    folder.mkdir(parents=True, exist_ok=True)
    origin = folder / ORIGIN_FILE_NAME
    if not origin.exists():
        try:
            origin.write_text(str(output_folder) + "\n", encoding="utf-8")
        except OSError:
            pass  # a label for humans; never worth failing the step over
    return folder


def local_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where a new intermediate is written: always the local work folder."""
    return work_folder(output_folder) / subfolder / Path(relative_path).with_suffix(suffix)


def legacy_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where versions before 1.5.8 wrote the same intermediate."""
    return Path(output_folder) / subfolder / Path(relative_path).with_suffix(suffix)


def intermediate_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where to read an intermediate from: the local copy, else the one an
    older version left in the output folder, else the local path (which
    does not exist — the caller's existence check then says so)."""
    local = local_path(output_folder, subfolder, relative_path, suffix)
    if local.exists():
        return local
    legacy = legacy_path(output_folder, subfolder, relative_path, suffix)
    if legacy.exists():
        return legacy
    return local


def destination(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """`local_path` with its parent folder created, ready to be written."""
    path = local_path(output_folder, subfolder, relative_path, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def intermediate_roots(output_folder: str | Path) -> list[Path]:
    """Every folder that may hold this project's intermediates, local and
    legacy — what cleanup and project deletion have to cover."""
    roots = [work_folder(output_folder) / name for name in INTERMEDIATE_SUBFOLDERS]
    roots += [Path(output_folder) / name for name in INTERMEDIATE_SUBFOLDERS]
    return roots

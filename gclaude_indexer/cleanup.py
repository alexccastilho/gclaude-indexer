# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Cleanup of the output folder's intermediate files.

`converted/` (OCR'd PDFs and per-file text) and `blocks/` (the slices)
account for almost all of the space a project takes up, and should only be
deleted after the `.md` artifacts and `project.db` are ready: the removal is
final for this project, because `converter()` only processes files with
status `'discovered'` — once successfully converted they never go back to
that status, so running the conversion again would not regenerate them.

Never touches the database, the artifacts, `raw_items.jsonl` or `logs/`
— and never the source folder. Unlike `exclusao.py`, which deletes the
whole project, here the work's result is preserved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import resolve_within

INTERMEDIATE_FOLDERS: tuple[str, ...] = ("converted", "blocks")


def _target_folders(output_folder: str) -> list[Path]:
    """Resolves the intermediate folders inside the output folder, refusing
    any escape (spec section 7) — `resolve_within` raises `ValueError`."""
    base = Path(output_folder)
    targets = []
    for name in INTERMEDIATE_FOLDERS:
        path = resolve_within(base, name)
        if path.is_dir():
            targets.append(path)
    return targets


def intermediates_size(output_folder: str) -> int:
    """Sum, in bytes, of what `clear_intermediates` would delete right now."""
    total = 0
    for folder in _target_folders(output_folder):
        for path in folder.rglob("*"):
            if path.is_file():
                # The file can disappear between `is_file()` and `stat()` —
                # the Result screen is reachable while conversion is still
                # writing to these folders. Not a real error: just skip it.
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
    return total


def clear_intermediates(output_folder: str) -> int:
    """Deletes `converted/` and `blocks/` entirely. Returns the bytes freed.
    Calling it on a folder that no longer has them returns `0` with no error."""
    before = intermediates_size(output_folder)
    for folder in _target_folders(output_folder):
        shutil.rmtree(folder, ignore_errors=True)
    # Recomputed after `rmtree` (which ignores errors): computing it before
    # and returning that number would make the screen lie about bytes freed
    # if `rmtree` fails silently (e.g. file in use on Windows).
    freed = before - intermediates_size(output_folder)
    return freed

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
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)

    return DeletionResult(folder_deleted=True, folder=str(folder))

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Path resolution without relying on a fixed absolute path or drive letter.

Rule from spec section 11.5: the application root is located from the
running file's own position, never hard-coded as an absolute path in code
or in the database. Every relative-path resolution against a base is
validated to prevent escaping it (including via `..`), per section 7.
"""

from __future__ import annotations

import os
from pathlib import Path


def app_root() -> Path:
    """Application package root, derived from this file's own location."""
    return Path(__file__).resolve().parent.parent


# Overrides the folder below. Set by the elevated sensor helper, which
# receives it on its command line (`sensor_service.py`): elevating with a
# *different* administrator account than the logged-on one changes
# `%LOCALAPPDATA%`, and the helper would then publish its reading into a
# folder the server never looks at. The server's own value is passed down
# so both processes agree on one folder no matter whose token is running.
LOCAL_FOLDER_ENV = "GCLAUDE_INDEXER_LOCAL_FOLDER"


def machine_local_folder() -> Path:
    """Per-machine local folder for what cannot live in the Drive-synced
    folder: venv, Ollama models, downloaded installers (section 11.1).
    Resolved at runtime from `%LOCALAPPDATA%`, never hard-coded as a literal
    path."""
    override = os.environ.get(LOCAL_FOLDER_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "GClaudeIndexer"


def resolve_within(base: Path, relative: str) -> Path:
    """Resolves `relative` inside `base`, refusing any escape attempt.

    Raises `ValueError` if the resulting path is not contained in `base`
    (for example, through `..` or a disguised absolute path).
    """
    resolved_base = Path(base).resolve()
    candidate = (resolved_base / relative).resolve()

    try:
        common = os.path.commonpath([str(resolved_base), str(candidate)])
    except ValueError:
        # Different Windows drive letters — there's no way to be contained.
        raise ValueError(
            f"Path '{relative}' is outside the allowed folder '{resolved_base}'"
        )

    if common != str(resolved_base):
        raise ValueError(
            f"Path '{relative}' is outside the allowed folder '{resolved_base}'"
        )

    return candidate

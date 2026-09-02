# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Preferences that belong to this machine, not to a project.

Exactly one so far: which folder holds the shared project catalog. That
setting has to live locally by definition — it is the pointer *into* the
synced world, so it cannot itself be synced, and each computer names the
same Drive folder with its own drive letter (section 11.5).

Kept apart from `catalog.py` because the two answer different questions:
this module says *where* the catalog is, `catalog.py` says what is in it.
Never raises on a malformed or missing file — a preference that cannot be
read falls back to its default, and the system runs exactly as it did
before anyone set it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import machine_local_folder

SETTINGS_FILE_NAME = "settings.json"

# The one key so far. Empty string = not configured: the catalog stays
# local to this machine, which is the behaviour every existing install has.
SHARED_CATALOG_FOLDER = "shared_catalog_folder"

_DEFAULTS: dict = {SHARED_CATALOG_FOLDER: ""}


def settings_path() -> Path:
    return machine_local_folder() / SETTINGS_FILE_NAME


def load_settings() -> dict:
    """Every preference, with defaults filled in. Never raises."""
    values = dict(_DEFAULTS)
    try:
        raw = settings_path().read_text(encoding="utf-8")
        stored = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return values
    if isinstance(stored, dict):
        for key in _DEFAULTS:
            value = stored.get(key)
            if isinstance(value, str):
                values[key] = value
    return values


def save_settings(values: dict) -> None:
    """Writes the preferences, keeping any key this version does not know."""
    current = {}
    try:
        current = json.loads(settings_path().read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        current = {}

    current.update({key: value for key, value in values.items() if isinstance(value, str)})
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def shared_catalog_folder() -> Path | None:
    """The configured shared catalog folder, or `None`.

    `None` also when the folder is configured but not reachable right now —
    the Drive client has not finished mounting, the machine is offline with
    a cloud-only folder, someone renamed it. The caller then falls back to
    the local catalog rather than failing: a project list that is
    incomplete for a minute is recoverable; a Projects screen that will not
    open is not.
    """
    configured = load_settings().get(SHARED_CATALOG_FOLDER, "").strip()
    if not configured:
        return None
    folder = Path(configured)
    try:
        return folder if folder.is_dir() else None
    except OSError:
        return None


def configured_shared_catalog_folder() -> str:
    """What the user configured, verbatim — reachable or not.

    The screen shows this rather than `shared_catalog_folder()`: a field
    that silently empties itself because Drive is still starting up would
    look like the setting had been lost.
    """
    return load_settings().get(SHARED_CATALOG_FOLDER, "").strip()


def set_shared_catalog_folder(folder: str) -> None:
    """Sets (or clears, with an empty string) the shared catalog folder."""
    save_settings({SHARED_CATALOG_FOLDER: (folder or "").strip()})

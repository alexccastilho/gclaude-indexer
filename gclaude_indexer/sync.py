# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Incomplete-sync warning (spec section 11.4).

Each machine keeps, locally (never in the synced folder — section 11.1),
the most recent modification date it has seen for each project's
`project.db`. On reopening, if the file appears older than it was the last
time this same machine looked at it, that is the typical sign that Google
Drive has not finished downloading the latest version yet — and the UI
warns before letting it continue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import PROJECT_DB_NAME, machine_local_folder, write_text_atomic

REGISTRY_FILE_NAME = "sincronizacao.json"
SLACK_SECONDS = 1.0  # tolerance for minimal mtime differences between filesystems


@dataclass
class SyncCheckResult:
    ok: bool
    # Key + parameters, not rendered text — same reasoning as `lock.py`.
    message_key: str
    message_params: dict[str, object] = field(default_factory=dict)


def _registry_path() -> Path:
    return machine_local_folder() / REGISTRY_FILE_NAME


def _read_registry() -> dict:
    """The registry, or `{}` when it is missing, unreadable (no permission,
    not UTF-8) or not a JSON object. It only feeds a warning: a registry
    that cannot be read must not keep every project from opening."""
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_registry(registry: dict) -> None:
    write_text_atomic(_registry_path(), json.dumps(registry, ensure_ascii=False, indent=2))


def _key(output_folder) -> str:
    return str(Path(output_folder).resolve())


def check_sync(output_folder) -> SyncCheckResult:
    """Compares `project.db`'s modification date with the last one known to
    this machine. Does not update the registry on its own when it finds a
    sign of incomplete sync — only after the user confirms
    (`mark_synced`), so it can warn again if reopened without being
    resolved."""
    db_path = Path(output_folder) / PROJECT_DB_NAME
    if not db_path.exists():
        return SyncCheckResult(True, "")

    current_mtime = db_path.stat().st_mtime
    known_mtime = _read_registry().get(_key(output_folder))

    if known_mtime is not None and current_mtime < known_mtime - SLACK_SECONDS:
        return SyncCheckResult(False, "sync.incomplete")

    return SyncCheckResult(True, "")


def mark_synced(output_folder) -> None:
    """Records the current modification date as the new "last known" one
    for this machine — called on a successful open (no warning) or when the
    user confirms they want to continue despite the warning."""
    db_path = Path(output_folder) / PROJECT_DB_NAME
    if not db_path.exists():
        return
    registry = _read_registry()
    registry[_key(output_folder)] = db_path.stat().st_mtime
    try:
        _write_registry(registry)
    except OSError:
        # Disk full or no permission in the local folder. The date not
        # recorded only makes the next warning less sensitive (the known
        # date stays older); failing here would leave the project unopenable.
        pass


def rename_key(old_folder, new_folder) -> None:
    """A pasta de saída mudou de lugar (`relocation.py`): a data conhecida
    passa para a chave nova, para o aviso de sincronização incompleta
    continuar valendo."""
    registry = _read_registry()
    old_key, new_key = _key(old_folder), _key(new_folder)
    if old_key not in registry or old_key == new_key:
        return
    value = registry.pop(old_key)
    registry.setdefault(new_key, value)
    _write_registry(registry)

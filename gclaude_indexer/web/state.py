# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""What this server process holds on the projects it serves: the
cross-machine locks, the one-operation-per-project slot, and letting go
of a project before its folder is deleted, moved or taken over."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from ..catalog import catalog_folder, list_projects
from ..lock import LockManager
from ..paths import folder_key
from .background_runs import task_manager
from .readers import reader_pool


# The port this server was started on; `start_server()` records it. The
# `Host` guard of the sensor request (`routes_run`) compares against it,
# so a server started on another port is still only reachable by its own
# pages. Read as `state.SERVER_PORT`: a name imported from here would
# keep the default.
SERVER_PORT = 8000

# Cross-machine database lock (section 11.3): one per project opened in this
# server session, with its own heartbeat. All removed on shutdown.
lock_manager = LockManager()


# --- what keeps a project busy, and letting go of it ---------------------------
#
# Two kinds of work hold a project, and this is the one place that knows
# both: a pipeline step, in `task_manager` (`background_runs.py`), and a long
# operation (import and generate, update, delete, clearing intermediates,
# search indexing, dedup, folder move) holding the project's slot below.
# Each route asks the question it needs: `_step_in_progress`,
# `_operation_in_progress`, or both, as `_project_busy` does.
#
# The slot: one long operation per project at a time. Seen live before it
# existed: 4 concurrent "import and generate" runs on a 5230-item project,
# each repeating `DELETE FROM item` plus thousands of inserts. The value says
# *which* operation holds it and since when (fase 32), so a page loaded in
# the middle of it (an F5, another tab) can show the activity bar with the
# real name and the real elapsed time. The instant is `time.monotonic()`
# (fase 33): wall-clock time can be set back by Windows or by NTP in the
# middle of a generation, and nothing reads this value across processes.
_OPERATIONS_IN_PROGRESS: dict[int, tuple[str, float]] = {}
_SLOTS_LOCK = threading.Lock()
# How many times each project's slot was taken or let go, under `_SLOTS_LOCK`.
# The idle fragments' cache key (`caches._activity_key`) reads it: an
# operation of `_generation_slot` leaves no entry in `_OPERATIONS`, so without
# this the key after it was the key before it, and the screen kept the
# fragment from before the operation.
_SLOT_CHANGES: dict[int, int] = {}


def _step_in_progress(project_id: int) -> bool:
    task = task_manager.latest_for_project(project_id)
    return task is not None and task.running


def _operation_in_progress(project_id: int) -> bool:
    with _SLOTS_LOCK:
        return project_id in _OPERATIONS_IN_PROGRESS


def _operation_holding(project_id: int) -> tuple[str, float] | None:
    """`(i18n key, monotonic start)` of the operation holding the slot."""
    with _SLOTS_LOCK:
        return _OPERATIONS_IN_PROGRESS.get(project_id)


def _claim_slot_locked(project_id: int, key: str, started_at: float) -> bool:
    """Takes the project's slot if it is free. The caller holds
    `_SLOTS_LOCK`, so `_start_operation` registers its operation in the
    same breath."""
    if project_id in _OPERATIONS_IN_PROGRESS:
        return False
    _OPERATIONS_IN_PROGRESS[project_id] = (key, started_at)
    _SLOT_CHANGES[project_id] = _SLOT_CHANGES.get(project_id, 0) + 1
    return True


def _release_slot(project_id: int) -> None:
    with _SLOTS_LOCK:
        if _OPERATIONS_IN_PROGRESS.pop(project_id, None) is not None:
            _SLOT_CHANGES[project_id] = _SLOT_CHANGES.get(project_id, 0) + 1


def _release_project(output_folder, project_id: int | None = None, *, keep_lock_file: bool = False) -> None:
    """Lets go of everything this server holds on the project folder before
    its files are deleted, moved or taken over, in the order that matters:
    the steps are asked to stop (when `project_id` is given), then the read
    connections close, then the lock goes, last, because Windows will not
    delete or rename a file that is still open.

    `keep_lock_file`: stop looking after the lock without deleting
    `project.lock` (`LockManager.forget`): a folder move carries the file
    along, and a take-over writes a new one over it."""
    if project_id is not None:
        task_manager.pause(project_id)
    reader_pool.close(output_folder)
    if keep_lock_file:
        lock_manager.forget(output_folder)
    else:
        lock_manager.close(output_folder)


def _release_all_projects() -> None:
    """Server shutdown: every read connection, then every lock."""
    reader_pool.close_all()
    lock_manager.close_all()


def _project_busy(output_folder) -> bool:
    """Whether a step of the project is running in the background — with
    no screen open, it still needs the lock.

    The lock was opened with the folder `find_project` resolved for this
    machine, so each entry is resolved the same way before comparing: the
    shared catalog keeps the absolute path of the machine that registered
    the project, which on another drive letter never matches. Compared by
    `folder_key`: `H:` and `h:` are the same folder."""
    key = folder_key(output_folder)
    folder = catalog_folder()
    for entry in list_projects():
        if folder_key(entry.resolved_output_folder(folder)) == key:
            return _step_in_progress(entry.id) or _operation_in_progress(entry.id)
    return False


lock_manager.set_keep_alive(_project_busy)


@contextmanager
def _generation_slot(project_id: int, operation_key: str):
    """One report generation per project at a time. Yields `False` when
    another one is under way — the caller sends the user to the result
    instead of starting a duplicate: two generations writing and deleting
    the same files at once end in `PermissionError` on Windows, and a
    regeneration during an import would read a half-imported `item` table.
    The same slot as `_start_operation`, held for the length of the
    request; `_project_busy` reads it for the lock keep-alive.

    `operation_key` is the i18n key of the button that started it — what
    `project_activity` reports back to the screen (fase 32)."""
    with _SLOTS_LOCK:
        claimed = _claim_slot_locked(project_id, operation_key, time.monotonic())
    try:
        yield claimed
    finally:
        if claimed:
            _release_slot(project_id)

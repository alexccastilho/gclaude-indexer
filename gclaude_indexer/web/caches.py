# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Answers kept between requests while their inputs have not moved: the
Execution screen's idle fragments and the per-project summaries
(quality, pending items, run comparison)."""

from __future__ import annotations

import threading
import time

from ..config import ProjectConfig
from ..quality import quality_summary
from .background_runs import task_manager
from ..file_status import FAILED, WINDOW_DONE, WINDOW_PENDING
from .operations import _OPERATIONS
from .state import _OPERATIONS_IN_PROGRESS, _SLOTS_LOCK


# The Execution screen asks for the steps table and the progress box
# every two seconds. With nothing running, the answer cannot change except
# through an action of this server (a step, an update, a generation), and
# on a large project on Google Drive each answer cost about a second of
# reads through the drive, competing with every other screen. While idle,
# the same answer is reused for a while; anything that starts or ends
# changes the key and forces a fresh one.
IDLE_FRAGMENT_SECONDS = 30.0
_idle_fragments: dict[tuple[int, str, str], tuple[tuple, float, str]] = {}
_idle_fragments_lock = threading.Lock()


def _activity_key(project_id: int) -> tuple | None:
    """What would change the screen: `None` while something runs."""
    task = task_manager.latest_for_project(project_id)
    if task is not None and task.running:
        return None
    with _SLOTS_LOCK:
        if project_id in _OPERATIONS_IN_PROGRESS:
            return None
        operation = _OPERATIONS.get(project_id)
    return (
        id(task), getattr(task, "error", None),
        (operation.id, operation.status) if operation is not None else None,
    )


def _idle_fragment(project_id: int, name: str, language: str, build) -> str:
    key = _activity_key(project_id)
    cache_key = (project_id, name, language)
    now = time.monotonic()
    if key is not None:
        with _idle_fragments_lock:
            cached = _idle_fragments.get(cache_key)
        if cached is not None and cached[0] == key and now - cached[1] < IDLE_FRAGMENT_SECONDS:
            return cached[2]
    html = build()
    with _idle_fragments_lock:
        if key is None:
            _idle_fragments.pop(cache_key, None)
        else:
            _idle_fragments[cache_key] = (key, now, html)
    return html


# The steps table refreshes every two seconds and used to recompute
# the whole quality summary each time (every page, every item). Its inputs
# only change when items, windows, pages or failures do, so it is kept per
# project and recomputed when that cheap signature moves.
_quality_cache: dict[tuple[int, str], tuple[tuple, object]] = {}
_quality_cache_lock = threading.Lock()


def _quality_signature(conn, config: ProjectConfig) -> tuple:
    row = conn.execute(
        """
        SELECT (SELECT MAX(id) FROM item), (SELECT COUNT(*) FROM item),
               (SELECT COUNT(*) FROM window WHERE status = ?),
               (SELECT COUNT(*) FROM window WHERE status = ?),
               (SELECT MAX(id) FROM page),
               (SELECT COUNT(*) FROM file WHERE status = ?)
        """,
        (WINDOW_DONE, WINDOW_PENDING, FAILED),
    ).fetchone()
    return (tuple(row), config.classification_engine, config.local_model)


def _cached_quality_summary(project_id: int, conn, config: ProjectConfig) -> dict:
    return _cached_by_signature(project_id, "quality", conn, config, lambda: quality_summary(conn, config))


def _cached_by_signature(project_id: int, name: str, conn, config: ProjectConfig, compute):
    """A summary of the project, kept until the cheap signature moves
    (1.9.0: the Result screen of a large project on Google Drive
    took tens of seconds to recompute the quality, the pending items and the run
    comparison on every visit; their inputs had not changed)."""
    signature = _quality_signature(conn, config)
    key = (project_id, name)
    with _quality_cache_lock:
        cached = _quality_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    value = compute()
    with _quality_cache_lock:
        _quality_cache[key] = (signature, value)
    return value

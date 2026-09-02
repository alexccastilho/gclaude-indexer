# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Runs the steps in the background, with a progress bar, an estimated time
of arrival (ETA) and pause/interrupt — explicit user request.

Each step runs in its own thread, with its own sqlite connection (a
connection cannot be shared between threads). Progress is not reported by
the step functions themselves — it is computed on every poll by comparing
the current count in the database against a reference (baseline) count
recorded at the start, which requires no signature change to the step
functions beyond the cooperative `should_stop` (`run_control.py`).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import ProjectConfig
from ..run_control import StopSignal
from ..conversion import convert
from ..extraction import extract_pages
from ..windows_prep import prepare_windows
from ..engine_local import model_to_use
from ..orchestrator import resolve_effective_engine, run_classification
from ..project import load_project
from ..scanning import scan
from .eta import ProgressEstimator

STEP_ORDER = ("scan", "conversion", "extraction", "windows", "classification")

_STEP_FUNCTIONS = {
    "scan": lambda conn, config, should_stop, language: scan(
        conn, config, should_stop=should_stop, language=language
    ),
    "conversion": lambda conn, config, should_stop, language: convert(
        conn, config, should_stop=should_stop, language=language
    ),
    "extraction": lambda conn, config, should_stop, language: extract_pages(
        conn, config, should_stop=should_stop, language=language
    ),
    "windows": lambda conn, config, should_stop, language: prepare_windows(
        conn, config, should_stop=should_stop, language=language
    ),
    "classification": lambda conn, config, should_stop, language: run_classification(
        conn, config, should_stop=should_stop, language=language
    ),
}


@dataclass
class StepTask:
    step: str
    total: int
    baseline: int
    started_at: float = field(default_factory=time.monotonic)
    running: bool = True
    finished_ok: bool = False
    error: str | None = None
    stop_signal: StopSignal = field(default_factory=StopSignal)
    # Last count read successfully — used when a progress read fails with
    # "database is locked" (the step itself writes directly to its own
    # connection; only this concurrent read can collide with it, more
    # likely in a folder synced by Google Drive). Without this, a
    # transient lock made the bar "disappear"/drop back to 0% for an
    # instant instead of just keeping the last known value.
    last_count: int | None = None
    # Instant the step finished — freezes the duration so the elapsed time
    # does not keep growing indefinitely during polling (HTMX keeps
    # fetching the bar every 2s even after completion).
    finished_at: float | None = None
    # Work already done when the step started and the work it has to do,
    # in bytes, for the steps measured that way — see `eta.py` for why the
    # estimate is not computed from the file count the bar shows.
    # `weight_total` of 0 means "not measured in bytes"; the estimator then
    # receives the counts instead.
    weight_baseline: float = 0.0
    weight_total: float = 0.0
    estimator: ProgressEstimator = field(default_factory=ProgressEstimator)


def _scan_totals(config: ProjectConfig) -> tuple[int, int]:
    """`(files, bytes)` still to be scanned.

    Both come from one walk of the source folder: the count drives the
    progress bar the user reads, the byte total drives the time estimate
    (`eta.py`) — scanning hashes every file, so its cost tracks size, not
    file count.
    """
    source_folder = Path(config.source_folder).resolve()
    output_folder = Path(config.output_folder).resolve()
    files = 0
    total_bytes = 0
    for path in source_folder.rglob("*"):
        if path.is_file() and not path.is_relative_to(output_folder):
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass  # unreadable file: it will fail in the step itself
    return files, total_bytes


def _files_to_scan_count(config: ProjectConfig) -> int:
    return _scan_totals(config)[0]


def _current_count(conn, step: str) -> int:
    if step == "scan":
        return conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
    if step == "conversion":
        return conn.execute(
            "SELECT COUNT(*) FROM file WHERE status IN ('converted','extracted','failed')"
        ).fetchone()[0]
    if step == "extraction":
        return conn.execute("SELECT COUNT(*) FROM file WHERE status = 'extracted'").fetchone()[0]
    if step == "windows":
        return conn.execute("SELECT COUNT(DISTINCT group_key) FROM window").fetchone()[0]
    if step == "classification":
        return conn.execute("SELECT COUNT(*) FROM window WHERE status = 'done'").fetchone()[0]
    return 0


# Which `file.status` values mean "this step is done with this file", per
# step. Shared by the count and the weight queries so the two can never
# disagree about what counts as finished.
_DONE_STATUSES = {
    "scan": None,  # every row in `file` counts, whatever its status
    "conversion": ("converted", "extracted", "failed"),
    "extraction": ("extracted",),
}


def _weight_done(conn, step: str) -> float | None:
    """Bytes processed so far by `step`, or `None` when the step is not
    measured in bytes.

    `windows` and `classification` work on windows, which are built to a
    fixed page count and are therefore already comparable to each other —
    counting them is the right unit there, and `None` tells the caller to
    fall back to it.
    """
    statuses = _DONE_STATUSES.get(step, "unmeasured")
    if statuses == "unmeasured":
        return None
    try:
        if statuses is None:
            row = conn.execute("SELECT COALESCE(SUM(size), 0) FROM file").fetchone()
        else:
            placeholders = ",".join("?" for _ in statuses)
            row = conn.execute(
                f"SELECT COALESCE(SUM(size), 0) FROM file WHERE status IN ({placeholders})", statuses
            ).fetchone()
    except sqlite3.Error:
        return None
    return float(row[0] or 0)


def _weight_pending(conn, step: str) -> float | None:
    """Bytes still waiting for `step`, or `None` when not measured in bytes."""
    pending_status = {"conversion": "discovered", "extraction": "converted"}.get(step)
    if pending_status is None:
        return None
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(size), 0) FROM file WHERE status = ?", (pending_status,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return float(row[0] or 0)


def _weight_total_and_baseline(conn, config: ProjectConfig, step: str) -> tuple[float, float]:
    """`(baseline, total)` in bytes for the time estimate, or `(0, 0)` when
    this step is not measured in bytes.

    `(0, 0)` is the deliberate signal for "fall back to counting items":
    the windows and classification steps work on windows built to a fixed
    page count, which are already comparable units.
    """
    if step == "scan":
        _files, pending_bytes = _scan_totals(config)
        baseline = _weight_done(conn, step) or 0.0
        return baseline, float(pending_bytes)

    pending = _weight_pending(conn, step)
    if pending is None:
        return 0.0, 0.0
    return (_weight_done(conn, step) or 0.0), pending


def _total_and_baseline(conn, config: ProjectConfig, step: str) -> tuple[int, int]:
    if step == "scan":
        return _files_to_scan_count(config), conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
    if step == "conversion":
        baseline = conn.execute(
            "SELECT COUNT(*) FROM file WHERE status IN ('converted','extracted','failed')"
        ).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM file WHERE status = 'discovered'").fetchone()[0]
        return pending, baseline
    if step == "extraction":
        baseline = conn.execute("SELECT COUNT(*) FROM file WHERE status = 'extracted'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM file WHERE status = 'converted'").fetchone()[0]
        return pending, baseline
    if step == "windows":
        baseline = conn.execute("SELECT COUNT(DISTINCT group_key) FROM window").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(DISTINCT group_key) FROM file WHERE group_key IS NOT NULL AND status = 'extracted'"
        ).fetchone()[0]
        return pending, baseline
    if step == "classification":
        baseline = conn.execute("SELECT COUNT(*) FROM window WHERE status = 'done'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0]
        return pending, baseline
    return 0, 0


def compute_progress(output_folder: str, task: StepTask | None) -> dict:
    if task is None:
        return {"status": "none", "percentual": 0, "concluidos": 0, "total": 0, "eta_segundos": None, "error": None}

    weight_done: float | None = None
    try:
        config, conn = load_project(output_folder)
        try:
            current = _current_count(conn, task.step)
            if task.weight_total > 0:
                weight_done = _weight_done(conn, task.step)
        finally:
            conn.close()
        task.last_count = current
    except sqlite3.OperationalError:
        # "database is locked" — the step is writing at this very instant
        # (more likely while the folder is syncing through Drive). Not a
        # real error: use the last count read successfully and try again on
        # the next poll (2s later), instead of bringing down the screen.
        current = task.last_count if task.last_count is not None else task.baseline

    done = max(0, min(current - task.baseline, task.total))
    total = max(task.total, 0)
    percent = 100 if total == 0 else int(done * 100 / total)
    if not task.running and task.finished_ok:
        percent = 100

    eta = None
    if task.running and percent < 100:
        # Bytes when the step is measured that way, items otherwise. The
        # estimator only needs the two numbers to be in the same unit as
        # each other and stable across polls — see `eta.py`.
        if task.weight_total > 0 and weight_done is not None:
            eta = task.estimator.observe(
                max(0.0, weight_done - task.weight_baseline), task.weight_total
            )
        else:
            eta = task.estimator.observe(float(done), float(total))

    if task.error:
        situation = "error"
    elif task.running:
        situation = "running"
    elif task.finished_ok:
        situation = "done"
    else:
        situation = "stopped"

    return {
        "status": situation,
        "step": task.step,
        "percentual": percent,
        "concluidos": done,
        "total": total,
        "eta_segundos": eta,
        "error": task.error,
    }


class TaskManager:
    """One background task per (project, step) — the caller decides whether
    to reuse it (`get`) or create a new one (`start_step`)."""

    def __init__(self):
        self._tasks: dict[tuple[int, str], StepTask] = {}
        self._lock = threading.Lock()

    def get(self, project_id: int, step: str) -> StepTask | None:
        with self._lock:
            return self._tasks.get((project_id, step))

    def latest_for_project(self, project_id: int) -> StepTask | None:
        """The task worth showing in the bar: the one running, or — when
        none is — the last one that ran, so the box settles on
        "done"/"paused"/"error" instead of vanishing from the screen the
        instant the step ends."""
        with self._lock:
            of_project = [task for (pid, _step), task in self._tasks.items() if pid == project_id]
        if not of_project:
            return None
        running = [task for task in of_project if task.running]
        if running:
            return max(running, key=lambda task: task.started_at)
        return max(of_project, key=lambda task: task.started_at)

    def start_step(
        self, project_id: int, entry_output_folder: str, config: ProjectConfig, step: str,
        stop_signal: StopSignal | None = None, language: str | None = None,
    ) -> StepTask:
        existing = self.get(project_id, step)
        if existing is not None and existing.running:
            return existing

        read_config, read_conn = load_project(entry_output_folder)
        try:
            total, baseline = _total_and_baseline(read_conn, read_config, step)
            weight_baseline, weight_total = _weight_total_and_baseline(read_conn, read_config, step)
        finally:
            read_conn.close()

        task = StepTask(
            step=step, total=total, baseline=baseline, stop_signal=stop_signal or StopSignal(),
            weight_baseline=weight_baseline, weight_total=weight_total,
        )
        with self._lock:
            self._tasks[(project_id, step)] = task

        def body():
            run_id: int | None = None
            try:
                _, work_conn = load_project(entry_output_folder)
                try:
                    # Task 15 (Phase 13): time per step, for the engine/model
                    # benchmark (`quality.compare_runs`). Records the
                    # *effective* engine (via `resolve_effective_engine`,
                    # which resolves the "automatic" sentinel to the engine
                    # that will actually run) — not the configured one.
                    # Recording the configured one left `run.engine` as
                    # "automatic" (the default) while `item.engine` received
                    # the engine actually used (`rules` or `local`), and the
                    # benchmark — which groups by one and queries the other —
                    # never matched them up. Uses `work_conn` (opened on this
                    # same thread) instead of opening another connection:
                    # sqlite3 does not allow sharing a connection between
                    # threads.
                    engine = resolve_effective_engine(work_conn, config, language=language)
                    model = model_to_use(work_conn, config) if engine == "local" else None
                    cursor = work_conn.execute(
                        """
                        INSERT INTO run (step, engine, model, parallelism, started_at, items, ok)
                        VALUES (?, ?, ?, ?, ?, 0, 0)
                        """,
                        (step, engine, model, config.parallelism, datetime.now().isoformat(timespec="microseconds")),
                    )
                    work_conn.commit()
                    run_id = cursor.lastrowid

                    _STEP_FUNCTIONS[step](work_conn, config, task.stop_signal.should_stop, language)
                    task.finished_ok = True
                finally:
                    work_conn.close()
            except Exception as exc:  # never brings down the server
                task.error = str(exc)[:500]
            finally:
                task.finished_at = time.monotonic()
                task.running = False
                # Own connection (the `work_conn` above is already closed,
                # and cannot be reopened/shared between threads): same
                # pattern `compute_progress` already uses to read the
                # database outside the step itself.
                if run_id is not None:
                    try:
                        _, end_conn = load_project(entry_output_folder)
                        try:
                            items = max(0, _current_count(end_conn, step) - task.baseline)
                            end_conn.execute(
                                "UPDATE run SET finished_at = ?, items = ?, ok = ? WHERE id = ?",
                                (
                                    datetime.now().isoformat(timespec="microseconds"),
                                    items,
                                    int(task.finished_ok),
                                    run_id,
                                ),
                            )
                            end_conn.commit()
                        finally:
                            end_conn.close()
                    except Exception:
                        pass  # timing record never brings down the step itself

        threading.Thread(target=body, daemon=True).start()
        return task

    def start_all(
        self, project_id: int, entry_output_folder: str, config: ProjectConfig, language: str | None = None
    ) -> StopSignal:
        stop_signal = StopSignal()

        def body():
            for step in STEP_ORDER:
                if stop_signal.should_stop():
                    break
                if step == "classification" and config.classification_engine == "claude_code":
                    continue
                task = self.start_step(
                    project_id, entry_output_folder, config, step, stop_signal=stop_signal, language=language
                )
                while task.running:
                    time.sleep(0.3)
                if task.error or stop_signal.should_stop():
                    break

        threading.Thread(target=body, daemon=True).start()
        return stop_signal

    def pause(self, project_id: int, step: str | None = None) -> bool:
        """Pauses the given step, or — if `step` is None — every step
        currently running for this project (used by the single pause button
        on the Execution screen, which stops whatever is in progress)."""
        paused_any = False
        with self._lock:
            targets = [
                task for (pid, key), task in self._tasks.items()
                if pid == project_id and task.running and (step is None or key == step)
            ]
        for task in targets:
            task.stop_signal.request_stop()
            paused_any = True
        return paused_any


task_manager = TaskManager()

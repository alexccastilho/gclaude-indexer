# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The chain of steps, without the interface: their order, what runs before
and after each one, and the `run` table (time per step, effective engine,
model) that `quality.compare_runs` reads.

The interface (`web/background_runs.py`) adds threads, progress and the
pause button around it; `tools/indexar_pasta.py` runs it from start to
finish on one connection. Both go through here, so a step that gains a
"before" or an "after" gains it for both.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .auto_settings import resolve_auto_settings
from .config import ProjectConfig
from .conversion import convert
from .extraction import extract_pages
from .file_status import CONVERSION_FINISHED, EXTRACTION_FINISHED, WINDOW_DONE, in_params
from .invalidation import apply_pending_changes
from .orchestrator import EngineDecision, decide_engine, run_classification
from .run_control import OperationCancelled
from .scanning import scan
from .update_plan import SourceFolderUnavailable, stale_page_paths
from .windows_prep import prepare_windows

STEP_ORDER: tuple[str, ...] = ("scan", "conversion", "extraction", "windows", "classification")


class SourceFolderMissing(Exception):
    """The project opens with its source folder offline (pen drive, network,
    another machine's Drive); the steps do not: they read the originals, and
    a missing folder would look like an empty collection."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


def _apply_pending_changes(
    conn, config, *, should_stop=None, language=None, listed=None, warn_unverified=True,
) -> bool:
    """1.10.3: what changed in the folder is invalidated before the scan
    records it (see `invalidation.apply_pending_changes`). An unreachable
    folder or a pause leaves the index as it was: the scan right after
    finds the same folder, or stops at once. `False` nesse caso: o aviso dos
    não conferidos pode não ter saído."""
    try:
        apply_pending_changes(
            conn, config, language=language, should_stop=should_stop, listed=listed,
            warn_unverified=warn_unverified,
        )
    except (SourceFolderUnavailable, OperationCancelled):
        return False
    return True


# Every step function takes the same keyword-only options and ignores the
# ones it has no use for:
#   should_stop      cooperative pause (`run_control.py`);
#   language         language of the log;
#   files            scan only: the walk the caller already made;
#   on_progress      scan only: `(files_done, bytes_done)`;
#   run_state        dict shared by the steps of one execution;
#   decision         classification only: the engine decided for this run;
#   resolve_settings scan only: resolve window, overlap, characters per page
#                    and OCR language from what the scan found.


def _scan_step(
    conn, config, *, should_stop=None, language=None, files=None, on_progress=None, run_state=None,
    resolve_settings=True, **_options,
):
    applied = _apply_pending_changes(conn, config, should_stop=should_stop, language=language, listed=files)
    if applied and run_state is not None:
        # O aviso dos não conferidos desta execução já saiu (ou não havia).
        run_state["unverified_warned"] = True
    result = scan(conn, config, should_stop=should_stop, language=language, files=files, on_progress=on_progress)
    if resolve_settings and (should_stop is None or not should_stop()):
        # 2.0.0: janela, sobreposição, caracteres por página e idioma do OCR
        # saem do que a varredura achou (`auto_settings.py`). Uma varredura
        # pausada não resolve: o inventário está pela metade, e a próxima,
        # que o completa, é quem decide.
        resolve_auto_settings(conn, config, language=language)
    return result


def _conversion_step(conn, config, *, should_stop=None, language=None, **_options):
    return convert(conn, config, should_stop=should_stop, language=language)


def _extraction_step(conn, config, *, should_stop=None, language=None, run_state=None, **_options):
    # "Continue" starts the chain here, past the scan: a database 1.10.2
    # left with stale pages would stop on them again. Repaired files go
    # back to 'discovered' and are read again by the next run.
    if stale_page_paths(conn):
        # O aviso dos não conferidos só sai aqui quando a execução começou
        # pela extração; a varredura da mesma cadeia já o deu.
        warned = bool(run_state and run_state.get("unverified_warned"))
        _apply_pending_changes(
            conn, config, should_stop=should_stop, language=language, warn_unverified=not warned,
        )
    return extract_pages(conn, config, should_stop=should_stop, language=language)


def _windows_step(conn, config, *, should_stop=None, language=None, **_options):
    return prepare_windows(conn, config, should_stop=should_stop, language=language)


def _classification_step(conn, config, *, should_stop=None, language=None, decision=None, **_options):
    return run_classification(conn, config, should_stop=should_stop, language=language, decision=decision)


STEP_FUNCTIONS: dict[str, Callable] = {
    "scan": _scan_step,
    "conversion": _conversion_step,
    "extraction": _extraction_step,
    "windows": _windows_step,
    "classification": _classification_step,
}


# Which `file.status` values mean "this step is done with this file", per
# step. Shared by the `run` record and the interface's count, total and
# weight queries, so they can never disagree about what counts as finished.
DONE_STATUSES: dict[str, tuple[str, ...]] = {
    "conversion": CONVERSION_FINISHED,
    "extraction": EXTRACTION_FINISHED,
}


def count_files_in(conn, statuses: tuple[str, ...]) -> int:
    marks, values = in_params(statuses)
    return conn.execute(f"SELECT COUNT(*) FROM file WHERE status IN ({marks})", values).fetchone()[0]


def done_count(conn, step: str) -> int:
    """How much of `step`'s work the database shows as done: rows in `file`
    for the scan, finished files for conversion and extraction, groups with
    windows, classified windows. The difference across a step is the
    `items` of its `run` row."""
    if step == "scan":
        return conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
    if step in DONE_STATUSES:
        return count_files_in(conn, DONE_STATUSES[step])
    if step == "windows":
        return conn.execute("SELECT COUNT(DISTINCT group_key) FROM window").fetchone()[0]
    if step == "classification":
        return conn.execute("SELECT COUNT(*) FROM window WHERE status = ?", (WINDOW_DONE,)).fetchone()[0]
    return 0


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


@dataclass(frozen=True)
class StepRun:
    """A step that has started: its open `run` row, the count it started
    from and the engine decided for it."""

    step: str
    run_id: int
    baseline: int
    decision: EngineDecision


@dataclass(frozen=True)
class StepResult:
    run: StepRun
    value: object  # what the step function returned


def begin_step(
    conn, config: ProjectConfig, step: str, *, language: str | None = None,
    decision: EngineDecision | None = None,
) -> StepRun:
    """Checks the source folder, decides the engine and opens the step's
    `run` row. A missing folder raises `SourceFolderMissing` before
    anything is recorded.

    Task 15: `run.engine` is the *effective* engine (`decide_engine`
    resolves the "automatic" sentinel to the engine that will run), not the
    configured one: recording "automatic" while `item.engine` received
    `rules` or `local` left the benchmark (`quality.compare_runs`), which
    groups by one and queries the other, unable to match them. The
    classification step receives this same decision instead of deciding
    again. `decision` passed in: the caller already decided for the whole
    execution."""
    if not Path(config.source_folder).is_dir():
        raise SourceFolderMissing(config.source_folder)
    if decision is None:
        decision = decide_engine(conn, config, language=language)
    baseline = done_count(conn, step)
    cursor = conn.execute(
        """
        INSERT INTO run (step, engine, model, parallelism, started_at, items, ok)
        VALUES (?, ?, ?, ?, ?, 0, 0)
        """,
        (step, decision.engine, decision.model, config.parallelism, _now()),
    )
    conn.commit()
    return StepRun(step=step, run_id=cursor.lastrowid, baseline=baseline, decision=decision)


def call_step(conn, config: ProjectConfig, run: StepRun, **options):
    """Runs the step function itself, with the decision `begin_step` took.
    Looked up at call time, so a test that swaps an entry of
    `STEP_FUNCTIONS` reaches every caller."""
    return STEP_FUNCTIONS[run.step](conn, config, decision=run.decision, **options)


def finish_step(conn, run: StepRun, *, ok: bool) -> None:
    """Closes the step's `run` row. Never raises: the timing record never
    brings down the step itself."""
    try:
        items = max(0, done_count(conn, run.step) - run.baseline)
        conn.execute(
            "UPDATE run SET finished_at = ?, items = ?, ok = ? WHERE id = ?",
            (_now(), items, int(ok), run.run_id),
        )
        conn.commit()
    except Exception:
        pass


def run_step(
    conn, config: ProjectConfig, step: str, *,
    should_stop: Callable[[], bool] | None = None,
    language: str | None = None,
    decision: EngineDecision | None = None,
    **options,
) -> StepResult:
    """One step on one connection, from `begin_step` to `finish_step`.

    A step that raises leaves its uncommitted writes out (rolled back, as
    closing the connection would) and its `run` row closed with `ok = 0`;
    the exception goes on to the caller."""
    run = begin_step(conn, config, step, language=language, decision=decision)
    ok = False
    try:
        value = call_step(conn, config, run, should_stop=should_stop, language=language, **options)
        ok = True
    finally:
        if not ok:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        finish_step(conn, run, ok=ok)
    return StepResult(run=run, value=value)

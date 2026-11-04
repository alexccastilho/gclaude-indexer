# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Step state with no language text at all.

This module returns *stable keys* (`"concluida"`, `"scan"`), never screen
text. The text comes from `i18n.py`, chosen in the template by the user's
language. This separation exists because the key has three consumers with
different requirements: the displayed text (translatable), the CSS class
(must be ASCII) and the comparison in `next_pending_step` (must not depend
on the language — that coupling used to make the "Run next step" button
reprocess the first step whenever the text changed).

The step keys (`"scan"`, `"conversao"`, ...) were translated to English in
Task 9: they are written to `run.step` by the pipeline modules
(`scanning.py`, `conversion.py`, ...), compared here, and displayed via the
i18n keys `step.<key>.title`/`step.<key>.count` — all three had to change
together, or the log and the step table would stop matching.

The step *status* codes (`"concluida"`, `"pendente"`, ...) were originally
left in Portuguese on the same reasoning `parallelism.py` uses for its mode
values — enum-like tokens with zero user-visible effect. Task 9c
revisited that: the status is not an isolated token, it is one link in a
chain built by string concatenation (`t('status.' + etapa.status)` in
`_steps.html`, `t('project.status.' + p.status_key)` in `projects.html`,
`.status-{{ etapa.status }}` for the CSS class) and compared by equality in
`_progress.html` and `app.py`. Translating only the i18n *keys* while
leaving these *values* in Portuguese silently breaks every `{% elif %}`
that compares against them — no error, just a badge or bar that never
matches. So the status codes were translated to English along with the
keys, in the same pass. `chave` (the step key, e.g. `"scan"`) was left
alone: it is a different pair, out of this task's scope.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from ..conversion import ocr_retry_count
from ..project import DB_NAME, load_project

STEPS: tuple[str, ...] = ("scan", "conversion", "extraction", "windows", "classification")
STATUSES: tuple[str, ...] = ("not_started", "pending", "running", "done")


def step_status(conn, is_running: Callable[[str], bool]) -> list[dict]:
    """Status of each step from the counts in the database.

    `is_running(key)` answers whether there is an active background task for
    the step — passed in from outside so this module does not depend on
    `background_runs`.
    """
    # `total_files` counts every row of the table, `status = 'duplicate'`
    # included — a deliberate decision: this count feeds
    # "N file(s)" of the "scan" step and has to match the denominator of the
    # progress bar (`_scan_totals` in `background_runs.py`, which
    # counts every file found in the source folder, copy or not). Later
    # steps don't inherit this "problem": `conversion` and `extraction`
    # filter by their own status ('discovered' and 'converted'/'extracted'),
    # which a duplicate never has — so a duplicate shows up in the scan
    # total but never inflates any count afterward.
    # One pass over `file` instead of five COUNTs: on a large
    # project on Google Drive each pass re-reads the table through the
    # drive (about 700 ms for the five, 94 ms for this one).
    by_status = dict(conn.execute("SELECT status, COUNT(*) FROM file GROUP BY status").fetchall())
    total_files = sum(by_status.values())
    # Plus the files whose OCR failed: the next conversion sends
    # them back to the queue, so the step is not done while they wait.
    discovered = by_status.get("discovered", 0) + ocr_retry_count(conn)
    converted = by_status.get("converted", 0) + by_status.get("extracted", 0)
    failed = by_status.get("failed", 0)
    extracted = by_status.get("extracted", 0)
    total_pages = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]
    # The full-text search is indexed at the end of the extraction
    # step; the step is not done while files wait for it. Before, a pause
    # during the indexing left the step "done" and "Run next step" moved
    # on, with the search never finished.
    fulltext_pending = max(0, extracted - conn.execute(
        "SELECT COUNT(*) FROM fulltext_file JOIN file ON file.id = fulltext_file.file_id"
        " WHERE file.status = 'extracted'"
    ).fetchone()[0])
    total_windows = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
    windows_done = conn.execute("SELECT COUNT(*) FROM window WHERE status = 'done'").fetchone()[0]
    windows_pending = total_windows - windows_done

    def done_or(ready: bool, started: bool) -> str:
        if ready:
            return "done"
        return "pending" if started else "not_started"

    raw = [
        ("scan", done_or(total_files > 0, total_files > 0), {"total": total_files}),
        ("conversion", done_or(total_files > 0 and discovered == 0, total_files > 0),
         {"converted": converted, "failed": failed, "pending": discovered}),
        ("extraction",
         done_or(converted > 0 and converted == extracted and fulltext_pending == 0, converted > 0),
         {"pages": total_pages}),
        ("windows", done_or(total_windows > 0 and extracted > 0, total_windows > 0),
         {"windows": total_windows}),
        ("classification", done_or(total_windows > 0 and windows_pending == 0, total_windows > 0),
         {"done": windows_done, "pending": windows_pending}),
    ]

    # `chave`/`status`/`vars` are the wire-format dict keys read directly by
    # `_steps.html`/`_progress.html`/`app.py` (`etapa.chave`, `etapa.status`).
    # `chave` stays in Portuguese (out of this task's scope, see the module
    # docstring); `status` was translated together with its values in Task 9c.
    return [
        {"chave": key, "status": "running" if is_running(key) else status, "vars": variables}
        for key, status, variables in raw
    ]


def next_pending_step(steps: list[dict]) -> str | None:
    """First step that has neither finished nor is in progress."""
    for step in steps:
        if step["status"] not in ("done", "running"):
            return step["chave"]
    return None


_status_cache: dict[str, tuple[tuple[int, int], tuple[str, dict[str, int]]]] = {}
_status_cache_lock = threading.Lock()


def _db_signature(output_folder: str) -> tuple[int, int] | None:
    try:
        info = os.stat(os.path.join(str(output_folder), DB_NAME))
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


def project_status(output_folder: str) -> tuple[str, dict[str, int]]:
    """Summary of one row for the Projects screen: key and variables.

    Kept per project while `project.db` is the same file (size and
    modification time). The screen used to open every project's database
    on each visit, and on Google Drive that is the whole wait; a project
    nobody touched since the last visit now costs one `stat`."""
    signature = _db_signature(output_folder)
    key = str(output_folder)
    if signature is not None:
        with _status_cache_lock:
            cached = _status_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1][0], dict(cached[1][1])
    result = _project_status(output_folder)
    # Taken again after the read: opening may upgrade the schema.
    signature = _db_signature(output_folder)
    if signature is not None and result[0] != "unavailable":
        with _status_cache_lock:
            _status_cache[key] = (signature, (result[0], dict(result[1])))
    return result


def last_known_status(output_folder: str) -> str | None:
    """The status the Projects screen last computed for this project, or
    `None`. For the side bar, which shows it on every screen: it
    never opens a database nor touches the disk; a project not seen yet on
    the Projects screen simply has no dot."""
    with _status_cache_lock:
        cached = _status_cache.get(str(output_folder))
    return cached[1][0] if cached else None


def _project_status(output_folder: str) -> tuple[str, dict[str, int]]:
    try:
        _config, conn = load_project(output_folder)
    except Exception:
        return "unavailable", {}
    try:
        total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
        windows_pending = conn.execute(
            "SELECT COUNT(*) FROM window WHERE status = 'pending'"
        ).fetchone()[0]
        total_files = conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
    finally:
        conn.close()

    if total_files == 0:
        return "not_started", {}
    if total_items > 0:
        return "imported", {"items": total_items}
    if windows_pending > 0:
        return "classification_pending", {"windows": windows_pending}
    return "in_progress", {}

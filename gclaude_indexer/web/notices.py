# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The notices the Execution, Update and Result screens share: out-of-date
reports, work still pending, and instructions that repeat the managed block."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..artifacts import stale_artifacts
from ..instructions_dedup import detect as dedup_detect
from ..managed_block import user_part
from ..output_names import PROJECT_INSTRUCTIONS_FILENAME
from ..file_status import AWAITING_PROCESSING, WINDOW_PENDING, in_params


def _reports_to_regenerate(conn):
    """Out-of-date reports, but only once there is nothing left to process.

    Two different questions share the word "pending" and must not share a
    predicate. `_pipeline_has_pending_work` below deliberately ignores
    pending *windows*, so that someone who stops classification part-way
    still sees the update banner. Here the opposite holds: nudging "generate
    the reports" while windows are still waiting for the model would produce
    reports that are incomplete the moment they are written, and stale again
    a minute later. So this one does consult them.

    The nudge is only a nudge. The button itself is always on the Execution
    screen, so a user who deliberately stopped half-way and wants reports
    for what is done can still ask for them.
    """
    if _pipeline_has_pending_work(conn):
        return None
    if conn.execute("SELECT 1 FROM window WHERE status = ? LIMIT 1", (WINDOW_PENDING,)).fetchone():
        return None
    return stale_artifacts(conn)


def _stale_context(staleness) -> dict:
    """The numbers the two notices interpolate, or an empty dict."""
    if staleness is None:
        return {"stale": None, "stale_numbers": {}}
    return {
        "stale": staleness,
        "stale_numbers": {
            "generated_at": staleness.generated_at,
            "was_files": staleness.recorded.files,
            "was_windows": staleness.recorded.windows_done,
            "was_items": staleness.recorded.items,
            "now_files": staleness.current.files,
            "now_windows": staleness.current.windows_done,
            "now_items": staleness.current.items,
        },
    }


def _pipeline_has_pending_work(conn) -> bool:
    """Whether documents are still waiting to be converted or extracted.

    Used only to silence the update banner, and only for that one case:
    while a file sits in `'discovered'` or `'converted'`, the honest next
    action is to run the steps — `convert()` selects the first,
    `extract_pages()` the second — not to diagnose the folder again. It
    is deliberately *not* "did an update just happen": nothing records
    that, and inferring it from a flag would be one more value derived
    twice.

    Statuses left out on purpose. `'extracted'` is a finished file;
    `'failed'`, `'skipped'` and `'duplicate'` are terminal for this run —
    no step picks them up, so a collection holding only those has no
    pending work and the notice is honest again.

    Pending *windows* are not consulted, though the classification
    engines do select `window.status = 'pending'`. The only transition
    in the codebase is `pending -> 'done'` on success, so a user who
    stops classification part-way — an ordinary thing to do at roughly
    thirty seconds a window, and the Execution screen offers the button
    — would leave windows pending forever and never see the banner
    again for that project. Nor did the clause earn its place: after an
    apply of a pure addition nothing is `'discovered'` or `'converted'`
    and the discarded tail windows are gone, so the predicate was
    already False and the banner returned anyway. Applying the same plan
    twice is prevented by the key-based layout comparison in
    `update_plan._layout_disagrees`, not by this guard.
    """
    marks, values = in_params(AWAITING_PROCESSING)
    return conn.execute(f"SELECT 1 FROM file WHERE status IN ({marks}) LIMIT 1", values).fetchone() is not None


def _dedup_report(config):
    """The user's part of the instructions repeating the managed block
, or `None` when it does not."""
    own = user_part(Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME)
    if not own:
        return None
    report = dedup_detect(own, config.subject)
    return report if report.has_findings else None


def _dedup_kept(conn, fingerprint: str) -> bool:
    """The person chose "keep as it is" for this exact text."""
    try:
        row = conn.execute(
            "SELECT 1 FROM event WHERE message_key = 'log.instructions.dedup_kept'"
            " AND message_params LIKE ? LIMIT 1",
            (f"%{fingerprint}%",),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _dedup_notice(conn, config) -> bool:
    """Whether the Execution and Result screens point to the clean-up."""
    try:
        report = _dedup_report(config)
    except Exception:
        return False
    return report is not None and not _dedup_kept(conn, report.fingerprint)

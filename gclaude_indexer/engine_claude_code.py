# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""`claude_code` engine (spec section 5, step 6) — asynchronous by nature:
`CLAUDE.md` and the windows were already generated in phase 4, and it is
Claude Code itself (outside this process) that reads `windows/*.txt` and
writes `raw_items.jsonl` when the user types the trigger phrase.

This engine is entirely optional: the `rules` and `local` engines work with
no external tool besides Ollama (and `rules` needs no tool at all). Use
`claude_code` only if you already have Claude Code installed and prefer to
run classification through it.

This module covers the part that runs here: preparing the copyable command
(section 6, "Execução" screen), syncing progress by re-reading
`raw_items.jsonl` (same dedup criterion by `chave`, documented in
`CLAUDE.md`, now also applied to the window's status in the database) and
triggering the import when the user signals that they are done.

Trigger phrase and language (Task 11, Phase 14): the phrase this module
hands the user to copy is never compared, in this codebase, against what
the user actually types — that matching happens entirely inside the
external, real Claude Code session that reads `CLAUDE.md`'s instructions in
natural language. The only real risk is *documentation* drift: if
`CLAUDE.md`'s prose is now translated (see `windows_prep.py`) but only
documented the phrase in one language, a user who generated `CLAUDE.md` in
one interface language and later switched languages (or simply remembers
the phrase from a previous session) could type a phrase the external Claude
Code process would not recognize — silently, with no error and no failing
test, exactly the failure mode this task's brief warned about. There is no
persisted per-project language (only the `language` cookie, read fresh on
each request), so tying the accepted phrase strictly to "the project's
language" would not close that gap either.

Decision: `CLAUDE.md` documents all three phrasings as equally valid
triggers (`windows_prep.py`'s `_CLAUDE_MD_CONTENT`), regardless of which
language the rest of its prose is in — the external Claude Code engine
recognizes any of them. `USER_COMMANDS` below is only for display: the copy
button shows the phrase in the interface's *current* language, for a
consistent user experience, via `command_for_language()`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .i18n import _REFERENCE_LANGUAGE
from .import_items import RAW_ITEMS_FILE_NAME, ImportResult, import_and_consolidate
from .windows_prep import CLAUDE_MD_FILENAME, generate_claude_md

# Every phrase here is documented as an accepted trigger in `CLAUDE.md`
# regardless of the language it was generated in (see module docstring) —
# this dict only decides which one the copy button shows, in the
# interface's current language.
USER_COMMANDS: dict[str, str] = {
    "pt": "processe as janelas",
    "en": "process the windows",
    "es": "procese las ventanas",
}


def command_for_language(language: str) -> str:
    """The copyable command in `language`, falling back to
    `_REFERENCE_LANGUAGE` ("pt", the table guaranteed complete — same
    reasoning as `i18n.py::translate()`) for an unrecognized language."""
    return USER_COMMANDS.get(language, USER_COMMANDS[_REFERENCE_LANGUAGE])


@dataclass
class ClaudeCodeStatus:
    command: str
    windows_pending: int
    windows_done: int
    claude_md_path: Path
    raw_items_path: Path


def _count_windows(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM window GROUP BY status").fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    return {"windows_pending": counts.get("pending", 0), "windows_done": counts.get("done", 0)}


def prepare(conn: sqlite3.Connection, config: ProjectConfig, language: str) -> ClaudeCodeStatus:
    """Ensures `CLAUDE.md` exists (written in `language`, see
    `windows_prep.py`) and returns the command to copy plus the current
    state of the windows."""
    claude_md_path = generate_claude_md(config, language)
    return ClaudeCodeStatus(
        command=command_for_language(language),
        claude_md_path=claude_md_path,
        raw_items_path=Path(config.output_folder) / RAW_ITEMS_FILE_NAME,
        **_count_windows(conn),
    )


def sync_progress(conn: sqlite3.Connection, config: ProjectConfig, language: str) -> ClaudeCodeStatus:
    """"Recheck whether the windows are done" button (section 6): reads
    `raw_items.jsonl`, finds out which window `chave` already have at
    least one item written and marks those windows as `done` in the
    database."""
    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    keys_with_item: set[str] = set()

    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = data.get("window")
            if key:
                keys_with_item.add(key)

    counts_before = _count_windows(conn)

    if keys_with_item:
        placeholders = ", ".join("?" for _ in keys_with_item)
        conn.execute(
            f"UPDATE window SET status = 'done' WHERE status = 'pending' AND key IN ({placeholders})",
            tuple(keys_with_item),
        )
        conn.commit()

    counts = _count_windows(conn)
    # Pre-existing defect, fixed here while touching `record_event` anyway
    # (Task 12, Phase 14): this function used to log unconditionally, but
    # it is called on every load of the Execution screen (`run_screen`) —
    # with nothing new done since the last call, it kept appending
    # identical "N done, M pending" lines to the log. Only recording the
    # event when the counts actually changed keeps the log meaningful
    # without losing any real progress update.
    if counts != counts_before:
        record_event(
            conn, "classification", "info", "log.claude_code.sync_status",
            {"done": counts["windows_done"], "pending": counts["windows_pending"]},
            language=language,
        )
    return ClaudeCodeStatus(
        command=command_for_language(language),
        claude_md_path=Path(config.output_folder) / CLAUDE_MD_FILENAME,
        raw_items_path=jsonl_path,
        **counts,
    )


def finish(conn: sqlite3.Connection, config: ProjectConfig, language: str) -> ImportResult:
    """Called when the user signals they are done: syncs the windows'
    status and imports/consolidates everything in `raw_items.jsonl`."""
    sync_progress(conn, config, language)
    return import_and_consolidate(conn, config, language=language)

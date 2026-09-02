# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Event recording in the `event` table (sections 4 and 6 — live log panel).

Section 7: log with no document content, only file name and count — whoever
calls `record_event` is responsible for not passing document text in the
message.

By explicit user request, every event is also appended to a log file inside
the output folder (`logs/execucao.log`), in addition to the `event` table.
This diverges from section 11.1 of the original spec, which lists "execution
logs" as something that stays local only, per machine, outside the synced
folder — a decision explicitly overridden by the user.

Translatable messages (Task 12, Phase 14): `record_event`'s fourth argument
is normally one of the `log.*` keys in `i18n.py` (core, so importing it here
does not invert the core -> web dependency — see that module's docstring),
rendered through `translate()` with `params` into the stored `message`. The
`message_key`/`message_params` (JSON) columns are kept alongside it so
`list_events` can retranslate into a different language on read — pass a
literal string with no matching key (ad hoc/legacy events, and any caller
that predates this task) and it is stored/shown exactly as given, in every
language, forever: "com chave, traduz; sem chave, mostra `message`."

`message` itself is always populated, key or not: the on-disk log file
below is written at the moment of the event and needs real text right then,
in whatever language the caller (or `DEFAULT_LANGUAGE`, absent a caller
that knows better) resolves to at that instant — it is never retranslated
after the fact.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .i18n import DEFAULT_LANGUAGE, _NESTED_KEY_MARKER, _NESTED_PARAMS_MARKER, has_key, translate

LEVELS = {"info", "warning", "error"}
LOG_FOLDER_NAME = "logs"
LOG_FILE_NAME = "execucao.log"


def _render_params(language: str, params: dict[str, object]) -> dict[str, object]:
    """Resolves any `i18n.nested(...)` marker in `params` into real,
    language-correct text before it is substituted into the outer
    template — see `nested()`'s docstring for why this indirection exists.
    Plain values pass through unchanged."""
    rendered: dict[str, object] = {}
    for name, value in params.items():
        if isinstance(value, dict) and _NESTED_KEY_MARKER in value:
            nested_params = value.get(_NESTED_PARAMS_MARKER) or {}
            rendered[name] = translate(language, value[_NESTED_KEY_MARKER], **_render_params(language, nested_params))
        else:
            rendered[name] = value
    return rendered


def _output_folder_path(conn: sqlite3.Connection) -> Path | None:
    """Derives the output folder from the path of the already-open database
    file itself (``<output_folder>/project.db``) — no need to thread the
    config through just to log. `None` for in-memory databases (e.g.
    `:memory:` in tests)."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    db_path = row[2]
    if not db_path:
        return None
    return Path(db_path).resolve().parent


def _write_to_log_file(conn: sqlite3.Connection, step: str, level: str, message: str, created_at: str) -> None:
    output_folder = _output_folder_path(conn)
    if output_folder is None:
        return
    try:
        logs_folder = output_folder / LOG_FOLDER_NAME
        logs_folder.mkdir(parents=True, exist_ok=True)
        with open(logs_folder / LOG_FILE_NAME, "a", encoding="utf-8") as file:
            file.write(f"[{created_at}] {level.upper():5s} {step}: {message}\n")
    except OSError:
        pass  # the file log is a bonus; it must never bring down the run


def record_event(
    conn: sqlite3.Connection,
    step: str,
    level: str,
    key: str,
    params: dict[str, object] | None = None,
    *,
    language: str | None = None,
) -> int:
    """Records an event under `step`/`level`.

    `key` is normally a `log.*` translation key (see `i18n.py`) and
    `params` its interpolation values — `message` is rendered from them in
    `language` (falling back to `DEFAULT_LANGUAGE` when the caller has no
    access to the interface's chosen language, e.g. deep processing helpers
    reached from a background thread). `key`/`params` are also stored
    (`message_key`/`message_params`, as JSON) for `list_events` to
    retranslate later.

    `key` may also be arbitrary literal text with no entry in the
    translation table — ad hoc/legacy events, and any caller from before
    this task. It is then stored as `message` verbatim, with
    `message_key`/`message_params` left `NULL`, exactly like an event with
    no key: shown as-is, regardless of language.
    """
    if level not in LEVELS:
        raise ValueError(f"invalid level: {level!r} (options: {sorted(LEVELS)})")

    params = params or {}
    if has_key(key):
        resolved_language = language or DEFAULT_LANGUAGE
        message = translate(resolved_language, key, **_render_params(resolved_language, params))
        stored_key = key
        stored_params = json.dumps(params, ensure_ascii=False) if params else None
    else:
        message = key
        stored_key = None
        stored_params = None

    created_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO event (step, level, message, message_key, message_params, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (step, level, message, stored_key, stored_params, created_at),
    )
    conn.commit()
    _write_to_log_file(conn, step, level, message, created_at)
    return cursor.lastrowid


def list_events(conn: sqlite3.Connection, step: str | None = None, language: str | None = None) -> list[dict]:
    """Lists events, oldest first (optionally filtered by `step`).

    `language`, when given, retranslates every event that has a
    `message_key` into it — `message` then reflects the interface's
    *current* language, even if it differs from the one running when the
    event was recorded. Without `language`, `message` is returned exactly
    as stored (the language in effect at write time) — the on-disk log
    file already behaves this way (section 11.1), so this default keeps
    both readings consistent for a caller with no language of its own
    (tests included)."""
    if step is None:
        cursor = conn.execute("SELECT * FROM event ORDER BY id")
    else:
        cursor = conn.execute("SELECT * FROM event WHERE step = ? ORDER BY id", (step,))

    rows = [dict(row) for row in cursor.fetchall()]
    if language is not None:
        for row in rows:
            message_key = row.get("message_key")
            if message_key:
                params = json.loads(row["message_params"]) if row.get("message_params") else {}
                row["message"] = translate(language, message_key, **_render_params(language, params))
    return rows

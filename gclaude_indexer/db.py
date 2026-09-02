# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""SQLite connection and database schema (spec section 4).

Important (section 11.3): the database lives in a folder synced by Google
Drive. Always open with `journal_mode=DELETE` and `synchronous=FULL`; never
WAL, whose auxiliary files do not survive the sync.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    subject       TEXT,
    source_folder TEXT NOT NULL,
    output_folder TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file (
    id            INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    extension     TEXT NOT NULL,
    size          INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    group_key     TEXT,
    page_count    INTEGER,
    needs_ocr     INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS page (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES file(id),
    number        INTEGER NOT NULL,
    reference     TEXT NOT NULL,
    char_count    INTEGER NOT NULL,
    image_count   INTEGER NOT NULL,
    has_table     INTEGER NOT NULL,
    text          TEXT NOT NULL,
    UNIQUE (file_id, number)
);

CREATE TABLE IF NOT EXISTS window (
    id            INTEGER PRIMARY KEY,
    key           TEXT NOT NULL UNIQUE,
    group_key     TEXT NOT NULL,
    start_ref     TEXT NOT NULL,
    end_ref       TEXT NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item (
    id            INTEGER PRIMARY KEY,
    group_key     TEXT NOT NULL,
    start_ref     TEXT NOT NULL,
    end_ref       TEXT NOT NULL,
    start_order   INTEGER NOT NULL,
    end_order     INTEGER NOT NULL,
    type          TEXT,
    date          TEXT,
    author        TEXT,
    summary       TEXT,
    has_table     INTEGER NOT NULL DEFAULT 0,
    has_image     INTEGER NOT NULL DEFAULT 0,
    engine        TEXT NOT NULL,
    confidence    TEXT NOT NULL,
    files         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
    id            INTEGER PRIMARY KEY,
    step          TEXT NOT NULL,
    level         TEXT NOT NULL,
    message       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- Task 15 (Phase 13): duration of each step, to compare engines/models
-- by time too, not just by quality (`quality.py`). `parallelism` was not
-- in this table's original design, but without it two times measured in
-- different modes (e.g. "economical" vs "maximum") would look comparable
-- without being so — `compare_runs` uses this column to warn when the
-- mode changed between runs.
CREATE TABLE IF NOT EXISTS run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    step          TEXT NOT NULL,
    engine        TEXT,
    model         TEXT,
    parallelism   TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    items         INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_file_status ON file(status);
CREATE INDEX IF NOT EXISTS idx_page_file_id ON page(file_id);
CREATE INDEX IF NOT EXISTS idx_item_group_key_order ON item(group_key, start_order);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Opens the project database connection with the pragmas that are safe for Drive."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # High timeout (sqlite3's default is 5s): the folder is synced by
    # Google Drive, whose client can briefly hold a file during sync —
    # without this, a concurrent read (e.g. the Execution screen's
    # progress bar, which opens its own connection) could fail with
    # "database is locked" right in the middle of a long step.
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Creates section 4's tables and indexes, idempotent."""
    conn.executescript(SCHEMA_SQL)
    _ensure_event_message_columns(conn)
    conn.commit()


def _ensure_event_message_columns(conn: sqlite3.Connection) -> None:
    """Adds `event.message_key`/`event.message_params` (Task 12, Phase 14):
    `record_event` now stores a translation key plus its parameters (JSON)
    alongside the already-rendered `message`, so a later read can
    retranslate an event into a different language — see `events.py`.

    `CREATE TABLE IF NOT EXISTS` above only creates the table the first
    time; it never adds a column to one that already exists, so a plain
    `ALTER TABLE` is needed here too. Guarded by `PRAGMA table_info`
    instead of try/except so calling `init_schema` twice — which happens
    routinely, see `project.load_project` — never raises "duplicate column
    name"."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(event)").fetchall()}
    if "message_key" not in existing_columns:
        conn.execute("ALTER TABLE event ADD COLUMN message_key TEXT")
    if "message_params" not in existing_columns:
        conn.execute("ALTER TABLE event ADD COLUMN message_params TEXT")

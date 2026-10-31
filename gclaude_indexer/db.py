# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""SQLite connection and database schema (spec section 4).

Important (section 11.3): the database lives in a folder synced by Google
Drive. Always open with a rollback journal (`journal_mode=TRUNCATE`) and
`synchronous=FULL`; never WAL, whose auxiliary files do not survive the sync.

TRUNCATE, not DELETE (1.5.5): both are rollback journals with the same
crash safety, but DELETE creates and deletes `project.db-journal` on every
commit, and on a Google Drive folder each create/delete pair cost ~0.3 s —
measured 0.285 s per commit against 0.009 s with TRUNCATE on the same
folder. At one commit per file that was hours of a 145,000-file conversion
spent only on the journal, and the file churn is what the Drive client
fights over. TRUNCATE leaves a zero-byte journal behind after each commit:
nothing for the sync to carry.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
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

-- Phase 17: a document that left the source folder. This is state, not a log:
-- `review.md` reports removals, and an event would vanish if the log were cleared.
CREATE TABLE IF NOT EXISTS removed_file (
    id            INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL,
    name          TEXT NOT NULL,
    removed_at    TEXT NOT NULL
);

-- Phase 18: the state the four artifacts describe, written when they are
-- generated. One row, always id 1.
--
-- Without it there is no way to tell a current report from one written
-- before the last classification finished, and the difference is invisible
-- to the eye: a collection gained three documents, the pipeline converted,
-- extracted and classified all of them, and `review.md` went on reporting
-- the previous thirteen files and 307 windows because generating the
-- reports is a separate step nobody had run yet. Comparing counts is exact
-- and costs three `COUNT(*)`; comparing the files' modification times would
-- not work here, since the output folder is synced by Google Drive and the
-- client rewrites timestamps on files whose bytes never changed (the same
-- trap `update_plan.py` documents for detection).
CREATE TABLE IF NOT EXISTS artifact_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at  TEXT NOT NULL,
    files         INTEGER NOT NULL,
    windows_done  INTEGER NOT NULL,
    items         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_status ON file(status);
CREATE INDEX IF NOT EXISTS idx_page_file_id ON page(file_id);
CREATE INDEX IF NOT EXISTS idx_item_group_key_order ON item(group_key, start_order);

-- Full-text search (`fulltext.py`): the whole text of every file, untruncated,
-- in passages that know where they are. Accents are folded, so "vigencia"
-- finds "vigência".
CREATE VIRTUAL TABLE IF NOT EXISTS fulltext USING fts5(
    text,
    file_id UNINDEXED,
    locator UNINDEXED,
    line UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS fulltext_file (
    file_id     INTEGER PRIMARY KEY,
    -- 1.5.9: the file's passages are rowids first..last of `fulltext`,
    -- so removing it never scans the table (`fulltext.remove_file`).
    first_rowid INTEGER,
    last_rowid  INTEGER
);
-- The Execution screen counts windows by status every two seconds, and
-- review.md lists the error events: both scanned the whole table.
CREATE INDEX IF NOT EXISTS idx_window_status ON window(status);
CREATE INDEX IF NOT EXISTS idx_event_level ON event(level);
"""


WRITER_TIMEOUT_SECONDS = 30.0
# The Execution screen polls every two seconds. A poll that waits 30 s for a
# busy database ties up a server thread and shows nothing; one that gives up
# after a few seconds keeps the last picture on screen and tries again.
READER_TIMEOUT_SECONDS = 5.0


def connect(db_path: Path, timeout: float = WRITER_TIMEOUT_SECONDS) -> sqlite3.Connection:
    """Opens the project database connection with the pragmas that are safe for Drive."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # High timeout for the steps (sqlite3's default is 5s): the folder is
    # synced by Google Drive, whose client can briefly hold a file during
    # sync. The screens' polls pass `READER_TIMEOUT_SECONDS` instead.
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.execute("PRAGMA journal_mode=TRUNCATE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def is_lock_error(exc: BaseException) -> bool:
    """`database is locked` / `database is busy`: another connection holds
    the file. Worth waiting for, unlike every other database error."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


# How long a step keeps retrying one batch while the database stays locked
# before it gives up with an error. Long on purpose: the lock is someone
# else's (a screen reading, the Drive client syncing) and always ends.
LOCK_RETRY_SECONDS = 600.0


class BatchWriter:
    """Groups a step's writes into one transaction per batch.

    One commit per file was the 1.5.4 pattern, and it failed two ways on a
    large collection in a Drive folder. Throughput: every commit is a disk
    round trip the whole step waits on. Robustness: a commit that met a
    locked database raised, the step left its loop with the transaction
    still open, and the open transaction then locked every screen out
    (31/10/2026, 144,000 files).

    Each write is an `op(conn)` that only touches the database. It runs
    immediately, so reads on the same connection see it. Ops are kept until
    the batch commits, and that is what makes a locked database harmless:
    on `database is locked` the batch is rolled back and **every op is
    applied again** before the next commit. Never retry a bare `commit()`
    after a failed statement; that would commit half a batch.

    The batch commits after `max_items` ops or `max_seconds` since its first
    op, whichever comes first. The progress bar reads committed counts, so
    `max_seconds` is how stale it can get. 1.5.9: 2 s and 500 ops (were
    1 s and 200): on a 400 MB database in Drive a commit takes seconds, and
    one per second left the screens' reads locked out ~40% of the time.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        max_items: int = 500,
        max_seconds: float = 2.0,
        retry_seconds: float = LOCK_RETRY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.conn = conn
        self._max_items = max_items
        self._max_seconds = max_seconds
        self._retry_seconds = retry_seconds
        self._sleep = sleep
        self._clock = clock
        self._ops: list[Callable[[sqlite3.Connection], object]] = []
        self._first_at: float | None = None

    @property
    def pending(self) -> int:
        return len(self._ops)

    def add(self, op: Callable[[sqlite3.Connection], object]) -> None:
        self._ops.append(op)
        if self._first_at is None:
            self._first_at = self._clock()
        try:
            op(self.conn)
        except sqlite3.OperationalError as exc:
            if not is_lock_error(exc):
                raise
            self._replay_until_committed()
            return
        self.flush_if_due()

    def flush_if_due(self) -> None:
        if not self._ops:
            return
        if len(self._ops) >= self._max_items or self._clock() - self._first_at >= self._max_seconds:
            self.flush()

    def flush(self) -> None:
        if not self._ops:
            return
        try:
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            if not is_lock_error(exc):
                raise
            self._replay_until_committed()
            return
        self._reset()

    def discard(self) -> None:
        """Rolls back whatever is pending. Safe to lose: a step only marks
        work done inside its ops, so the next run redoes it."""
        try:
            self.conn.rollback()
        finally:
            self._reset()

    def _reset(self) -> None:
        self._ops = []
        self._first_at = None

    def _replay_until_committed(self) -> None:
        deadline = self._clock() + self._retry_seconds
        delay = 0.25
        while True:
            # Releases our own locks too: a commit that failed on a busy
            # database keeps a PENDING lock, which shuts out new readers.
            self.conn.rollback()
            self._sleep(delay)
            try:
                for op in self._ops:
                    op(self.conn)
                self.conn.commit()
            except sqlite3.OperationalError as exc:
                if not is_lock_error(exc) or self._clock() >= deadline:
                    self.discard()
                    raise
                delay = min(delay * 2, 5.0)
                continue
            self._reset()
            return


def init_schema(conn: sqlite3.Connection) -> None:
    """Creates section 4's tables and indexes, idempotent."""
    conn.executescript(SCHEMA_SQL)
    _ensure_event_message_columns(conn)
    _ensure_file_mtime_column(conn)
    _ensure_file_ocr_failed_column(conn)
    _ensure_file_group_key_index(conn)
    _ensure_fulltext_file_range_columns(conn)
    _ensure_file_ocr_failed_index(conn)
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


def _ensure_file_mtime_column(conn: sqlite3.Connection) -> None:
    """Adds `file.mtime` (Phase 17): the update plan compares size and
    modification time before hashing, so opening a project does not read
    every byte of a Drive-synced collection. Same guard as
    `_ensure_event_message_columns` — `CREATE TABLE IF NOT EXISTS` never
    adds a column to a table that already exists, and `init_schema` runs
    on every project load."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(file)").fetchall()}
    if "mtime" not in existing_columns:
        conn.execute("ALTER TABLE file ADD COLUMN mtime REAL")


def _ensure_file_group_key_index(conn: sqlite3.Connection) -> None:
    """1.5.8: the windows step and every classification engine read a
    group's pages by `file.group_key`; without an index each read scanned
    the whole file table (144 thousand rows on a real collection). Guarded
    by column, like the migrations above: a table older than `group_key`
    has nothing to index."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(file)").fetchall()}
    if "group_key" in columns:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_group_key ON file(group_key)")


def _ensure_fulltext_file_range_columns(conn: sqlite3.Connection) -> None:
    """Adds `fulltext_file.first_rowid`/`last_rowid` (1.5.9). Files indexed
    before keep NULL and are removed the old, slower way."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(fulltext_file)").fetchall()}
    if columns and "first_rowid" not in columns:
        conn.execute("ALTER TABLE fulltext_file ADD COLUMN first_rowid INTEGER")
    if columns and "last_rowid" not in columns:
        conn.execute("ALTER TABLE fulltext_file ADD COLUMN last_rowid INTEGER")


def _ensure_file_ocr_failed_index(conn: sqlite3.Connection) -> None:
    """1.5.9: the steps table counts the files waiting for an OCR retry
    every two seconds (`conversion.ocr_retry_count`); without an index that
    read the whole file table. Partial: only the few flagged rows."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(file)").fetchall()}
    if "ocr_failed" in columns:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_ocr_failed ON file(ocr_failed) WHERE ocr_failed = 1"
        )


def _ensure_file_ocr_failed_column(conn: sqlite3.Connection) -> None:
    """Adds `file.ocr_failed` (1.5.7): set when `ocrmypdf` failed on the
    file, so the next conversion tries it again
    (`conversion.requeue_ocr_failures`).

    The column is added once per database, and that is also the one moment
    the files that failed before 1.5.7 can be found and flagged — from the
    two traces older versions left:
    - a whole-file failure kept the message in `file.error`, always
      starting with "ocrmypdf falhou" (the wording since the first release);
    - a file with native text whose scanned pages failed stayed 'converted'
      with no error, and only a `log.conversion.ocr_pages_failed` event
      names it. Event parameters carry the name, not the path, so a
      same-named PDF may be flagged too; it costs one more conversion of
      that file, nothing else.
    Doing it here, inside the guard, keeps it a one-time recovery: running
    it on every load would flag the same files again from the old events."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(file)").fetchall()}
    if "ocr_failed" in existing_columns:
        return
    conn.execute("ALTER TABLE file ADD COLUMN ocr_failed INTEGER NOT NULL DEFAULT 0")
    if not {"name", "extension", "error"} <= existing_columns:
        return  # a table older than any OCR failure: nothing to recover
    conn.execute(
        "UPDATE file SET ocr_failed = 1 WHERE status = 'failed' AND error LIKE 'ocrmypdf falhou%'"
    )
    names: set[str] = set()
    for (params,) in conn.execute(
        "SELECT message_params FROM event WHERE message_key = 'log.conversion.ocr_pages_failed'"
    ).fetchall():
        try:
            name = json.loads(params or "{}").get("name")
        except (ValueError, AttributeError):
            continue
        if isinstance(name, str) and name:
            names.add(name)
    for name in names:
        conn.execute(
            "UPDATE file SET ocr_failed = 1 WHERE name = ? AND extension = 'pdf'"
            " AND status IN ('converted', 'extracted')",
            (name,),
        )

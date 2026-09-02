# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Project creation: output folder, database and row in `project` (spec sections 4 and 6)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import ProjectConfig, load_config, config_to_json
from .db import connect, init_schema
from .events import record_event

DB_NAME = "project.db"


@dataclass
class ProjectSummary:
    """What is inside a `project.db`, read without touching it.

    The output folder *is* the project: the database in it holds the
    configuration, every file scanned, every page extracted and every item
    classified. Nothing else is needed to identify a project — which is why
    reopening one on a new machine is a matter of reading this folder, not
    of recreating anything.
    """

    output_folder: str
    name: str
    subject: str
    source_folder: str
    created_at: str
    files: int
    pages: int
    items: int
    # How many rows the `project` table holds. More than one means the
    # database went through the defect described in `load_project` below.
    config_rows: int = 1


def describe_project(output_folder: str | Path) -> ProjectSummary | None:
    """Reads the project in `output_folder`, or `None` if there is not one.

    **Opens the database read-only and creates nothing.** This is called to
    answer "is there already a project here?", including from the New
    project form, and a check that answers by creating an empty database in
    the folder it was asked about would be worse than no check at all.

    Never raises: a folder that does not exist, a file that is not a
    database, a database from a future version — all of them are "no
    project here", which is exactly what the caller needs to know.
    """
    path = Path(output_folder) / DB_NAME
    try:
        if not path.is_file():
            return None
    except OSError:
        return None

    try:
        # `mode=ro` through a URI: SQLite then refuses to create or modify
        # anything, so this cannot be the call that brings a stray database
        # into existence.
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None

    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT name, subject, source_folder, created_at FROM project ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        config_rows = conn.execute("SELECT COUNT(*) FROM project").fetchone()[0]
        return ProjectSummary(
            output_folder=str(output_folder),
            name=row["name"] or "",
            subject=row["subject"] or "",
            source_folder=row["source_folder"] or "",
            created_at=row["created_at"] or "",
            files=_count(conn, "file"),
            pages=_count(conn, "page"),
            items=_count(conn, "item"),
            config_rows=config_rows,
        )
    except (sqlite3.Error, KeyError, IndexError):
        return None
    finally:
        conn.close()


def _count(conn: sqlite3.Connection, table: str) -> int:
    """Row count, or 0 when the table is not there.

    A database written by an older version may predate a table this one
    knows about; a missing count is a zero, not a failure to read the
    project.
    """
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def _record_once(conn: sqlite3.Connection, key: str, params: dict) -> None:
    """Records a warning at most once per project database.

    `load_project` runs on every request — the Execution screen alone calls
    it four times every two seconds through its polling fragments. A
    condition of the database itself, as opposed to something that just
    happened, has to be reported once and not turned into a wall of
    identical lines that buries the run's real log.
    """
    try:
        already = conn.execute(
            "SELECT 1 FROM event WHERE message_key = ? LIMIT 1", (key,)
        ).fetchone()
    except sqlite3.Error:
        return
    if already:
        return
    record_event(conn, "diagnostics", "warning", key, params)


def create_project(config: ProjectConfig) -> tuple[sqlite3.Connection, int]:
    """Creates the output folder (if needed), the database and the `project` row.

    Returns the open connection and the id of the created project. Closing
    the connection when done is the caller's responsibility.
    """
    output_folder = Path(config.output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    conn = connect(output_folder / DB_NAME)
    init_schema(conn)

    created_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO project (name, subject, source_folder, output_folder, config_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            config.name,
            config.subject,
            config.source_folder,
            config.output_folder,
            config_to_json(config),
            created_at,
        ),
    )
    conn.commit()

    return conn, cursor.lastrowid


def load_project(output_folder: Path) -> tuple[ProjectConfig, sqlite3.Connection]:
    """Reopens an existing project from its output folder: reads the config
    stored in `project.config_json` and rebuilds `ProjectConfig` (revalidating
    — see section 11.4, incomplete-sync or different-machine warning)."""
    conn = connect(Path(output_folder) / DB_NAME)
    # Phase 13 Task 15: projects created before a new table existed (here,
    # `execucao`) only get it if `init_schema` also runs on reopen,
    # not only on create — `CREATE TABLE IF NOT EXISTS` is idempotent, so
    # calling it again on an already up-to-date database costs nothing.
    init_schema(conn)

    # `ORDER BY id` — the *first* row, which is the project as it was
    # created. This used to read `ORDER BY id DESC`, the last row, and that
    # is what made a second defect destructive.
    #
    # There was no way to reopen a project on a machine whose catalog did
    # not list it (a fresh install, a reformat, a folder received from
    # someone else). The natural gesture — "New project", pointing at the
    # output folder that already holds everything — was accepted in
    # silence: `create_project` INSERTed a second row, and this query then
    # preferred it. The scanned files, pages and items all survived, so it
    # looked like it had worked, while the saved configuration had been
    # replaced by whatever the form happened to contain. Structural values
    # went with it: a project whose windows were built at 8 pages each
    # would carry on at 16.
    #
    # Reading the first row restores the original configuration on every
    # database this already happened to. The extra rows are deliberately
    # *not* deleted — they are the only remaining record of the second
    # attempt, and a repair that destroys evidence to tidy up is not a
    # repair. `describe_project` reports how many there are, and the event
    # below says which one is in force.
    rows = conn.execute("SELECT id, config_json FROM project ORDER BY id").fetchall()
    if not rows:
        conn.close()
        raise ValueError(f"nenhum projeto encontrado em {output_folder}")

    row = rows[0]
    if len(rows) > 1:
        _record_once(conn, "log.project.duplicate_config", {"count": len(rows), "kept": row["id"]})

    data = json.loads(row["config_json"])

    # Projects saved before Phase 13 may have `classification_engine:
    # "openrouter"` — that engine was never implemented and the option was
    # removed from `CLASSIFICATION_ENGINES`. Without this conversion,
    # `load_config` below would raise `ConfigError` and the project would
    # become inaccessible because of a cleanup on our end. The conversion is
    # silent (equivalent to the old behavior, which already fell back to
    # `rules`), but is recorded as a warning event so it doesn't disappear
    # without a trace.
    if data.get("classification_engine") == "openrouter":
        data["classification_engine"] = "rules"
        # `load_project` has no request-scoped language to thread through
        # here (Task 12, Phase 14) — it is called from everywhere, on every
        # request, well before any endpoint reads the `language` cookie; a
        # rare legacy-conversion warning does not justify rewiring every
        # call site. `record_event` falls back to `DEFAULT_LANGUAGE`.
        record_event(
            conn, "diagnostics", "warning", "log.project.classification_engine_converted",
            {"engine": "openrouter", "replacement": "rules"},
        )

    config = load_config(data)
    return config, conn

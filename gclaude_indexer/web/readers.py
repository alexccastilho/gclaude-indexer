# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""One read-only connection kept open per project in use.

Every screen used to open a fresh connection to `project.db` and close it at
the end of the request. On a project stored on Google Drive that throws away
SQLite's page cache each time, so every count re-reads the table through the
drive: measured on a project of a few gigabytes, 10 to 80 times slower than the same
query on a connection that stays open (the Execution screen's polls about
0.8 s instead of 40 ms).

The connection here is read-only (`mode=ro`) and only for the screens that
read. Steps, imports and updates keep their own writing connections. Three
rules keep it from ever showing stale data or getting in the way:

- SQLite itself invalidates the cache when another connection commits.
- On top of that, the connection is reopened whenever the database file
  changes on disk (size or modification time). That covers what SQLite
  cannot see: Google Drive replacing the file with one synced from another
  computer. While a step is writing, this means a fresh connection per
  request, exactly as before; the gain is for the idle project, which is
  when people navigate.
- It is closed after a couple of minutes without use, and whenever the
  project is closed, deleted or taken over, so it never holds the file
  open for Windows or for the Drive client.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..db import READER_TIMEOUT_SECONDS
from ..lock import LockManager
from ..project import DB_NAME, load_project

# 64 MB of page cache: measured enough for the full gain on a project with
# over a hundred thousand files (128, 256 and 512 MB gave the same times).
CACHE_KIB = 65536
IDLE_CLOSE_SECONDS = 120.0


def _signature(db_path: Path) -> tuple[int, int] | None:
    try:
        info = os.stat(db_path)
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


@dataclass
class Reader:
    folder_key: str
    conn: sqlite3.Connection
    config: object
    signature: tuple[int, int]
    last_used: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class ReaderPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readers: dict[str, Reader] = {}
        self._sweeper: threading.Thread | None = None
        self.enabled = True

    def acquire(self, output_folder) -> Reader | None:
        """The project's reader, locked for this request; `None` when it
        cannot be had (the caller falls back to a normal connection)."""
        if not self.enabled:
            return None
        key = LockManager._key(output_folder)
        db_path = Path(output_folder) / DB_NAME
        signature = _signature(db_path)
        if signature is None:
            return None
        with self._lock:
            reader = self._readers.get(key)
            if reader is not None and reader.signature != signature:
                self._readers.pop(key, None)
                stale = reader
            else:
                stale = None
        if stale is not None:
            with stale.lock:
                stale.conn.close()
            reader = None
        if reader is None:
            reader = self._open(key, output_folder, db_path, signature)
            if reader is None:
                return None
            with self._lock:
                existing = self._readers.get(key)
                if existing is not None and existing.signature == signature:
                    reader.conn.close()
                    reader = existing
                else:
                    self._readers[key] = reader
            self._start_sweeper()
        reader.lock.acquire()
        reader.last_used = time.monotonic()
        return reader

    def release(self, reader: Reader) -> None:
        reader.last_used = time.monotonic()
        reader.lock.release()

    def _open(self, key: str, output_folder, db_path: Path, signature) -> Reader | None:
        try:
            # The configuration goes through the normal path once, with its
            # conversions and checks; only the reading is done read-only.
            config, writer = load_project(output_folder, timeout=READER_TIMEOUT_SECONDS)
            writer.close()
            conn = sqlite3.connect(
                f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                timeout=READER_TIMEOUT_SECONDS, check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA cache_size=-{CACHE_KIB}")
        except Exception:
            return None
        # `load_project` may have written (a schema upgrade, an event): take
        # the signature as it is now, after that.
        return Reader(key, conn, config, _signature(db_path) or signature, time.monotonic())

    def close(self, output_folder) -> None:
        key = LockManager._key(output_folder)
        with self._lock:
            reader = self._readers.pop(key, None)
        if reader is not None:
            with reader.lock:
                reader.conn.close()

    def close_all(self) -> None:
        with self._lock:
            readers = list(self._readers.values())
            self._readers.clear()
        for reader in readers:
            with reader.lock:
                reader.conn.close()

    def close_idle(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            idle = [r for r in self._readers.values() if now - r.last_used > IDLE_CLOSE_SECONDS]
            for reader in idle:
                self._readers.pop(reader.folder_key, None)
        for reader in idle:
            with reader.lock:
                reader.conn.close()

    def _start_sweeper(self) -> None:
        if self._sweeper is not None and self._sweeper.is_alive():
            return

        def sweep() -> None:
            while True:
                time.sleep(30)
                self.close_idle()

        self._sweeper = threading.Thread(target=sweep, name="reader-sweeper", daemon=True)
        self._sweeper.start()


reader_pool = ReaderPool()

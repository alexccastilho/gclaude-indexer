# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Cross-machine database lock (spec section 11.3).

When a project is opened, creates `project.lock` (in the output folder,
alongside `project.db`) with the machine name, the user and the time —
updated every minute (heartbeat) while the application is open. Finding a
lock from another machine less than 10 minutes old, refuses to open and
explains which machine is using it. A lock older than that is considered
abandoned and can only be taken over with the user's explicit confirmation.
The lock is removed on close.
"""

from __future__ import annotations

import getpass
import json
import socket
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

LOCK_FILE_NAME = "project.lock"
MINUTES_UNTIL_ABANDONED = 10
HEARTBEAT_INTERVAL_S = 60


@dataclass
class LockInfo:
    machine: str
    user: str
    created_at: str
    updated_at: str


@dataclass
class LockCheckResult:
    # "bloqueada"/"abandonada" were translated to "blocked"/"abandoned" in
    # Task 9c: they are compared by equality in `app.py` to decide which
    # HTTP error to raise, same hazard as the step-status chain in
    # `step_state.py`. "livre"/"propria_maquina" were left as-is back then —
    # never compared, only shown in `message` or asserted directly in tests —
    # but Task 9d (Phase 14) translated them too, for consistency with the
    # rest of this dataclass and the wider push for English identifiers.
    status: str  # "free" | "same_machine" | "blocked" | "abandoned"
    trava: LockInfo | None
    # Translation key plus its parameters, never rendered text: `check_lock()`
    # runs before any request-scoped language is known, and the three lock
    # screens have to read in the interface's language like everything else
    # (user requirement 3). Same shape `config.py` uses for validation
    # errors and `events.py` for the log.
    message_key: str
    message_params: dict[str, object] = field(default_factory=dict)


def machine_identity() -> tuple[str, str]:
    return socket.gethostname(), getpass.getuser()


def lock_path(output_folder) -> Path:
    return Path(output_folder) / LOCK_FILE_NAME


def read_lock(output_folder) -> LockInfo | None:
    path = lock_path(output_folder)
    if not path.exists():
        return None
    try:
        return LockInfo(**json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None  # corrupted/unreadable lock -> treat as absent


def _write(output_folder, lock: LockInfo) -> None:
    lock_path(output_folder).write_text(json.dumps(asdict(lock), ensure_ascii=False), encoding="utf-8")


def create_lock(output_folder) -> LockInfo:
    machine, user = machine_identity()
    now = datetime.now().isoformat(timespec="seconds")
    lock = LockInfo(machine=machine, user=user, created_at=now, updated_at=now)
    _write(output_folder, lock)
    return lock


def refresh_lock(output_folder, lock: LockInfo) -> LockInfo:
    """Heartbeat: updates only `updated_at`, keeping the rest."""
    updated = LockInfo(
        machine=lock.machine, user=lock.user, created_at=lock.created_at,
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    _write(output_folder, updated)
    return updated


def remove_lock(output_folder) -> None:
    lock_path(output_folder).unlink(missing_ok=True)


def check_lock(output_folder) -> LockCheckResult:
    lock = read_lock(output_folder)
    if lock is None:
        return LockCheckResult("free", None, "lock.free")

    current_machine, _ = machine_identity()
    if lock.machine == current_machine:
        return LockCheckResult(
            "same_machine", lock, "lock.same_machine", {"machine": lock.machine},
        )

    try:
        updated_at = datetime.fromisoformat(lock.updated_at)
    except ValueError:
        updated_at = datetime.min
    age = datetime.now() - updated_at
    minutes = max(int(age.total_seconds() // 60), 0)

    if age < timedelta(minutes=MINUTES_UNTIL_ABANDONED):
        return LockCheckResult(
            "blocked", lock, "lock.blocked",
            {"machine": lock.machine, "user": lock.user, "minutes": minutes,
             "timeout": MINUTES_UNTIL_ABANDONED},
        )

    return LockCheckResult(
        "abandoned", lock, "lock.abandoned",
        {"machine": lock.machine, "user": lock.user, "minutes": minutes},
    )


class LockManager:
    """Keeps, for the server process, the lock of each project opened in
    this session — and the heartbeat that refreshes it every minute while
    the application is open (spec section 11.3)."""

    def __init__(self, heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S):
        self._interval = heartbeat_interval_s
        self._locks: dict[str, LockInfo] = {}
        self._internal_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def _key(output_folder) -> str:
        return str(Path(output_folder).resolve())

    def is_open(self, output_folder) -> bool:
        with self._internal_lock:
            return self._key(output_folder) in self._locks

    def open(self, output_folder) -> LockInfo:
        key = self._key(output_folder)
        with self._internal_lock:
            if key not in self._locks:
                self._locks[key] = create_lock(output_folder)
                self._ensure_thread()
            return self._locks[key]

    def take_over(self, output_folder) -> LockInfo:
        """Replaces an abandoned lock with a new one from this machine —
        should only be called after the user's explicit confirmation."""
        key = self._key(output_folder)
        with self._internal_lock:
            self._locks[key] = create_lock(output_folder)
            self._ensure_thread()
            return self._locks[key]

    def close(self, output_folder) -> None:
        key = self._key(output_folder)
        with self._internal_lock:
            if key in self._locks:
                remove_lock(output_folder)
                del self._locks[key]

    def close_all(self) -> None:
        self._stop.set()
        with self._internal_lock:
            for folder in list(self._locks):
                remove_lock(folder)
            self._locks.clear()

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval):
            with self._internal_lock:
                for folder, lock in list(self._locks.items()):
                    self._locks[folder] = refresh_lock(folder, lock)

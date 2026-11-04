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
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

LOCK_FILE_NAME = "project.lock"
MINUTES_UNTIL_ABANDONED = 10
HEARTBEAT_INTERVAL_S = 60
# The lock is let go this long after the last sign of use (see
# `LockManager`). Five minutes, not one: a browser throttles the timers of
# a tab in the background to about one a minute, and a computer under
# load answers late.
IDLE_RELEASE_S = 5 * 60


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
    # but Task 9d translated them too, for consistency with the
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
    the project is in use (spec section 11.3).

    "in use" means a screen of the project open in the browser
    (each screen asks the server every minute, see `base.html`), a request
    being answered, or a step running in the background (`keep_alive`).
    Before, the lock was refreshed for as long as the server lived, and the
    server goes on living after the browser is closed (it has no window):
    the other computer saw "in use, last activity 1 minute ago" forever.
    Now, once nothing uses the project for `IDLE_RELEASE_S`, the lock is
    removed and the project is free elsewhere; the next screen opened here
    takes it again, through the same check as the first time."""

    def __init__(
        self,
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        idle_release_s: float = IDLE_RELEASE_S,
        keep_alive=None,
    ):
        self._interval = heartbeat_interval_s
        self._idle_release_s = idle_release_s
        self._keep_alive = keep_alive
        self._locks: dict[str, LockInfo] = {}
        self._last_use: dict[str, float] = {}
        self._in_use: dict[str, int] = {}
        self._internal_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def _key(output_folder) -> str:
        return str(Path(output_folder).resolve())

    def set_keep_alive(self, keep_alive) -> None:
        """`keep_alive(output_folder) -> bool`: whether work the browser
        does not see (a step running in the background) still needs the
        project."""
        self._keep_alive = keep_alive

    def is_open(self, output_folder) -> bool:
        with self._internal_lock:
            return self._key(output_folder) in self._locks

    def touch(self, output_folder) -> None:
        """Records that the project is being used now."""
        key = self._key(output_folder)
        with self._internal_lock:
            if key in self._locks:
                self._last_use[key] = time.monotonic()

    def begin_use(self, output_folder) -> None:
        """A request is working on the project: the lock stays while it
        lasts, however long (an import of over a hundred thousand items takes minutes)."""
        key = self._key(output_folder)
        with self._internal_lock:
            self._in_use[key] = self._in_use.get(key, 0) + 1
            self._last_use[key] = time.monotonic()

    def end_use(self, output_folder) -> None:
        key = self._key(output_folder)
        with self._internal_lock:
            count = self._in_use.get(key, 0) - 1
            if count > 0:
                self._in_use[key] = count
            else:
                self._in_use.pop(key, None)
            self._last_use[key] = time.monotonic()

    def open(self, output_folder) -> LockInfo:
        key = self._key(output_folder)
        with self._internal_lock:
            if key not in self._locks:
                self._locks[key] = create_lock(output_folder)
                self._ensure_thread()
            self._last_use[key] = time.monotonic()
            return self._locks[key]

    def take_over(self, output_folder) -> LockInfo:
        """Replaces an abandoned lock with a new one from this machine —
        should only be called after the user's explicit confirmation."""
        key = self._key(output_folder)
        with self._internal_lock:
            self._locks[key] = create_lock(output_folder)
            self._last_use[key] = time.monotonic()
            self._ensure_thread()
            return self._locks[key]

    def close(self, output_folder) -> None:
        key = self._key(output_folder)
        with self._internal_lock:
            if key in self._locks:
                remove_lock(output_folder)
                del self._locks[key]
            self._last_use.pop(key, None)

    def close_all(self) -> None:
        self._stop.set()
        with self._internal_lock:
            for folder in list(self._locks):
                remove_lock(folder)
            self._locks.clear()
            self._last_use.clear()

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._thread.start()

    def _still_needed(self, folder: str, now: float) -> bool:
        if self._in_use.get(folder, 0) > 0:
            return True
        if now - self._last_use.get(folder, now) < self._idle_release_s:
            return True
        if self._keep_alive is not None:
            try:
                return bool(self._keep_alive(folder))
            except Exception:
                return True  # in doubt, keep the lock: two writers is the worse failure
        return False

    def heartbeat(self) -> None:
        """One beat: refreshes the lock of the projects in use and removes
        the others'."""
        # The lock file is written *outside* the internal lock. The
        # write goes to Google Drive (close to a second), and every request
        # of every screen waited behind it in `is_open`/`begin_use`. The
        # refreshed entry only replaces the one it came from: a project
        # closed or reopened in the meantime keeps what that action left.
        now = time.monotonic()
        with self._internal_lock:
            snapshot = list(self._locks.items())
        for folder, lock in snapshot:
            if self._still_needed(folder, now):
                refreshed = refresh_lock(folder, lock)
                with self._internal_lock:
                    if self._locks.get(folder) is lock:
                        self._locks[folder] = refreshed
                continue
            with self._internal_lock:
                if self._locks.get(folder) is not lock or self._in_use.get(folder, 0) > 0:
                    continue
                remove_lock(folder)
                del self._locks[folder]
                self._last_use.pop(folder, None)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.heartbeat()

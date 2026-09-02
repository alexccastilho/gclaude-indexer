# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The elevated sensor helper (Phase 15, Task 3).

CPU temperature and power draw are the one thing in this system that
cannot be read without administrator rights: LibreHardwareMonitor loads a
kernel driver to talk to the chip, and without ring 0 every CPU sensor
comes back 0.0 (see `sensors.py`). GPU sensors need none of that and are
read normally either way.

**Elevation is an option here, never a requirement.** `Indexer.bat` and
`Indexer.vbs` start exactly as they always did, unprivileged; the user who
wants the CPU sensor opts in through a second desktop shortcut, and pays
one UAC prompt at startup for it.

What gets elevated is the narrow part. This module is a whole process
whose entire job is: read five numbers, write them to a file, sleep,
repeat. The server, uvicorn, every document parser, Ghostscript, Tesseract,
the Ollama client and every file the user indexes stay on an ordinary
token. Relaunching the *server* elevated would have been three lines of
batch file and would have put all of that on an administrator token in
order to read a thermometer — on a program whose day job is opening
untrusted documents. `install.ps1` already refuses the same trade for the
same reason: it elevates the two operations that need `C:\\Program Files`,
not the whole installation, so the venv and the shortcut are not left
owned by a token the user cannot manage.

Lifetime is bound to the server's, not to a timeout: the helper is given
the server's PID, opens a handle to that exact process, and waits on it.
When the server exits — cleanly or not — the wait completes, the helper
deletes its snapshot and exits. No orphaned administrator process outlives
the window that asked for it, and a recycled PID cannot fool it, because
the handle refers to a process instance and not to a number.

Nothing here parses input from a lower-privileged process. The only thing
this process reads from outside is its own command line, written by the
server that spawned it; the snapshot file is write-only from this side.
That is the direction that matters: data flows down from the elevated
process to the unprivileged one, never up.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

from . import paths, sensors
from .paths import app_root, machine_local_folder

# Set by `Indexer.bat --cpu-sensor` (which the "GClaude Indexer (CPU
# sensor)" desktop shortcut passes through `Indexer.vbs`). Its absence is
# the default, and the default is no elevation at all.
ELEVATION_REQUEST_ENV = "GCLAUDE_INDEXER_CPU_SENSOR"

# Spelled out rather than taken from `__name__`: under `python -m ...` this
# module *is* `__main__`, and a helper that respawned itself as `-m
# __main__` would fail in a way that only shows up in production.
MODULE_NAME = "gclaude_indexer.sensor_service"

# How often the helper republishes. Matches the Run screen's own 2s polling
# and `resources.ContinuousSampler`'s collection pace — reading faster would
# only spin the kernel driver for values nobody looks at.
POLL_INTERVAL_S = 2.0

# `Start-Process -Verb RunAs` equivalent, in the terms `ShellExecuteW` uses.
_SW_HIDE = 0
_SE_ERR_ACCESSDENIED = 5
_SHELL_EXECUTE_SUCCESS_FLOOR = 32

# `OpenProcess`/`WaitForSingleObject` constants (winnt.h / synchapi.h).
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102


def elevation_requested(environment: dict | None = None) -> bool:
    """Whether this run was started by the CPU-sensor shortcut.

    Anything other than the exact opt-in values is treated as "no": the
    fail-safe direction for a switch whose only effect is to ask for
    administrator rights.
    """
    source = os.environ if environment is None else environment
    return str(source.get(ELEVATION_REQUEST_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


# Where the helper is run from, and why it is not the project folder.
#
# The project lives in a Google Drive folder, which Drive for Desktop
# mounts as a virtual drive (`H:` on the machine this was found on). That
# mount belongs to the *logged-on user's session token*. An elevated
# process runs under the administrator half of the same account's split
# token, and Windows does not carry drive mappings across that boundary —
# so `H:\...` simply does not exist for the elevated child. `python -m
# gclaude_indexer.sensor_service` with a working directory on `H:` fails
# with "No module named gclaude_indexer" before it executes a line of ours,
# and because the helper is started with `pythonw.exe` and `SW_HIDE` there
# is no console for that message to appear on: the CPU sensors just stay
# empty, exactly as if nothing had been installed.
#
# `%LOCALAPPDATA%` is on a real local drive and readable by both halves of
# the token, so the four modules the helper actually needs are mirrored
# there and it runs from that copy. Copies, not a rewrite: the elevated
# reading must stay the same code as the unprivileged one, or the two
# quietly drift apart.
HELPER_FOLDER_NAME = "helper"
HELPER_MODULES = ("__init__.py", "paths.py", "sensors.py", "sensor_service.py")

# Why the helper could not be started, for the About screen to show. The
# server writes it; nothing reads it back into a decision.
LAUNCH_STATUS_FILE_NAME = "sensor_helper_status.txt"


def helper_folder() -> Path:
    """Local copy the elevated helper runs from."""
    return machine_local_folder() / HELPER_FOLDER_NAME


def stage_helper_modules(destination: Path | None = None) -> Path:
    """Copies the modules the helper needs into a locally-readable folder.

    Returns the folder to use as the helper's working directory (the parent
    of the `gclaude_indexer` package copy). Overwrites on every launch:
    copying four small files costs nothing next to a UAC prompt, and it
    removes any chance of an elevated process running yesterday's code
    after an update.
    """
    root = Path(destination) if destination is not None else helper_folder()
    package = root / "gclaude_indexer"
    package.mkdir(parents=True, exist_ok=True)
    source_package = Path(__file__).resolve().parent
    for module_name in HELPER_MODULES:
        source = source_package / module_name
        if source.is_file():
            shutil.copy2(source, package / module_name)
    return root


def write_launch_status(outcome: str) -> None:
    """Records the helper's launch outcome where the About screen can read
    it. Never raises — a diagnostic that breaks the startup it describes is
    worse than no diagnostic."""
    try:
        path = machine_local_folder() / LAUNCH_STATUS_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outcome, encoding="utf-8")
    except OSError:
        pass


def read_launch_status() -> str | None:
    """The last recorded launch outcome, or `None`."""
    try:
        text = (machine_local_folder() / LAUNCH_STATUS_FILE_NAME).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def _windowless_python(executable: str) -> str:
    """`pythonw.exe` beside `executable` when it exists, else `executable`.

    The helper has no console to show and nothing to say on one; launching
    it with `python.exe` would flash a black window over the user's desktop
    every time the system starts.
    """
    candidate = Path(executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else executable


def helper_command(parent_pid: int, executable: str | None = None) -> tuple[str, list[str]]:
    """`(program, arguments)` for the elevated child.

    `-B` is passed explicitly rather than relying on
    `PYTHONDONTWRITEBYTECODE`: the elevated process is created by the
    Windows AppInfo service and its environment is not this process's to
    guarantee, while the project folder is synced by Google Drive and must
    never receive a `__pycache__` (section 11.1) — least of all one written
    by an administrator token.
    """
    program = _windowless_python(executable or sys.executable)
    return program, [
        "-B",
        "-m",
        MODULE_NAME,
        "--parent-pid",
        str(int(parent_pid)),
        # The server's own local folder, not the child's idea of it. If the
        # user is a standard account and elevates with a *different*
        # administrator's credentials, `%LOCALAPPDATA%` in the child points
        # at that other profile — the helper would faithfully publish its
        # reading into a folder this server never reads, and the screen
        # would stay empty with nothing visibly wrong.
        "--local-folder",
        str(machine_local_folder()),
    ]


def _shell_execute_runas(program: str, arguments: str, working_directory: str) -> int:
    """`ShellExecuteW` with the `runas` verb — the UAC prompt.

    Isolated in its own function so the tests can substitute it: there is
    no way to exercise a refusal for real on a machine whose
    `ConsentPromptBehaviorAdmin` is 0.
    """
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(None, "runas", program, arguments, working_directory, _SW_HIDE)
    return int(result or 0)


def start_elevated_helper(parent_pid: int | None = None) -> str:
    """Asks for the elevated helper, if this run asked for it.

    Returns what happened, as a code for the caller to log — never raises,
    and never blocks: the server carries on either way.

    * `not_requested` — the ordinary launcher. Nothing was asked of anyone.
    * `already_elevated` — the whole system is already running as
      administrator, so `sensors.py` reads the CPU in-process and a helper
      would be a second reader of the same driver for nothing.
    * `started` — the helper is coming up.
    * `refused` — the user said No to the UAC prompt, or policy forbids it.
      **This is a decision, not a failure.** The system goes on exactly as
      the unprivileged launcher would: the Run screen shows GPU data, shows
      "not measured" for the CPU sensors, and shows the same note it always
      shows. No dialog, no traceback, nothing in the user's face.
    * `unavailable` — not Windows, or `ShellExecuteW` failed for some other
      reason. Degrades identically to `refused`.
    """
    if not elevation_requested():
        return "not_requested"
    if sys.platform != "win32":
        write_launch_status("unavailable")
        return "unavailable"
    try:
        if sensors._is_admin():
            write_launch_status("already_elevated")
            return "already_elevated"
    except Exception:
        pass

    program, arguments = helper_command(parent_pid if parent_pid is not None else os.getpid())
    quoted = " ".join(f'"{argument}"' if " " in argument else argument for argument in arguments)

    # The elevated child cannot see the project folder when it is a Google
    # Drive virtual drive (see `HELPER_FOLDER_NAME` above), so it is run
    # from a local mirror. `app_root()` stays as the fallback for the case
    # where the mirror cannot be written — on a machine whose project
    # folder is on a real local disk, that path works exactly as it always
    # did.
    try:
        working_directory = str(stage_helper_modules())
    except OSError:
        working_directory = str(app_root())

    try:
        result = _shell_execute_runas(program, quoted, working_directory)
    except Exception:
        write_launch_status("unavailable")
        return "unavailable"

    if result > _SHELL_EXECUTE_SUCCESS_FLOOR:
        write_launch_status("started")
        return "started"
    if result == _SE_ERR_ACCESSDENIED:
        write_launch_status("refused")
        return "refused"
    write_launch_status("unavailable")
    return "unavailable"


def _open_parent_handle(parent_pid: int):
    """A handle to wait on the server process, or `None` if it is gone.

    `SYNCHRONIZE` only — the helper never reads, writes or terminates the
    server, it just waits for it to end.
    """
    open_process = ctypes.windll.kernel32.OpenProcess
    open_process.restype = ctypes.c_void_p
    handle = open_process(_SYNCHRONIZE, False, int(parent_pid))
    return handle or None


def _wait_for_parent(handle, timeout_ms: int) -> bool:
    """Sleeps up to `timeout_ms`. `True` when the server has exited.

    The sleep and the liveness check are the same call on purpose: a helper
    that slept and then polled would keep a stale reading published for up
    to one interval after the server was gone.
    """
    wait = ctypes.windll.kernel32.WaitForSingleObject
    wait.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    wait.restype = ctypes.c_uint32
    return wait(handle, timeout_ms) == _WAIT_OBJECT_0


def _close_handle(handle) -> None:
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close(handle)


def run_helper(parent_pid: int, interval_s: float = POLL_INTERVAL_S, max_cycles: int | None = None) -> str:
    """The helper's whole life. Returns why it stopped.

    `max_cycles` exists for the tests; in production the loop ends only
    when the server it serves does.
    """
    handle = _open_parent_handle(parent_pid)
    if handle is None:
        # The server died between spawning us and our getting here. Nothing
        # to serve; do not publish a reading nobody will read.
        return "parent_gone"

    cycles = 0
    try:
        while True:
            try:
                sensors.write_snapshot(sensors.read_sensors())
            except OSError:
                # A transient failure writing the snapshot (the folder
                # momentarily locked, disk full) is not a reason to abandon
                # the run: the reading simply goes stale and the screen
                # falls back, and the next cycle may well succeed.
                pass

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return "max_cycles"
            if _wait_for_parent(handle, int(interval_s * 1000)):
                return "parent_exited"
    finally:
        sensors.clear_snapshot()
        _close_handle(handle)


def main(argv: list[str] | None = None) -> int:
    """`python -B -m gclaude_indexer.sensor_service --parent-pid N`."""
    import argparse

    parser = argparse.ArgumentParser(description="Elevated CPU sensor reader for GClaude Indexer.")
    parser.add_argument(
        "--parent-pid",
        type=int,
        required=True,
        help="PID of the server process to serve; the helper exits when it does.",
    )
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL_S)
    parser.add_argument(
        "--local-folder",
        default="",
        help="Folder to publish the snapshot into; the server's own, so a different administrator "
             "profile cannot send the reading somewhere the server never reads.",
    )
    arguments = parser.parse_args(argv)

    if arguments.local_folder:
        # Set before the first `sensors` call: `machine_local_folder()`
        # reads it on every call, and both the DLL path and the snapshot
        # path go through it.
        os.environ[paths.LOCAL_FOLDER_ENV] = arguments.local_folder

    run_helper(arguments.parent_pid, interval_s=arguments.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())

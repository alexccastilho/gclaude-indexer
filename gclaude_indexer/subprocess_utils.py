# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Running external commands without ever opening a console window.

Requirement from section 10: "the installer handles everything and reports
progress in the UI, never in a console window." Used by `hardware.py` and
`install_diagnostics.py` for `nvidia-smi`, PowerShell/WMI and the
`--version` checks, and — through `popen_hidden` — by every process
this code starts itself: LibreOffice, ffmpeg/whisper.cpp, `msiexec`, the
OCR runner (Tesseract, Ghostscript) and `ollama serve`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from .no_window import hidden_startupinfo


def _hidden_kwargs(extra_flags: int = 0, new_session: bool = False) -> dict:
    """The arguments that keep a child without a console: a hidden
    `STARTUPINFO` plus `CREATE_NO_WINDOW` on Windows (with `extra_flags`
    OR-ed in). Off Windows, `new_session` puts the child in its own process
    group, which is what lets `kill_tree` reach its children there."""
    if sys.platform == "win32":
        return {
            "startupinfo": hidden_startupinfo(),
            "creationflags": subprocess.CREATE_NO_WINDOW | extra_flags,
        }
    return {"start_new_session": True} if new_session else {}


def popen_hidden(
    command, *, extra_flags: int = 0, new_session: bool = False, **kwargs
) -> subprocess.Popen:
    """`subprocess.Popen` without a shell and without a console window.

    `command` goes to `Popen` as it is (a list, or the hand-quoted string
    `msiexec` needs). `extra_flags` adds Windows creation flags (e.g.
    `DETACHED_PROCESS` for a server that outlives the request). Pass
    `new_session=True` for a child that may be ended with `kill_tree`."""
    return subprocess.Popen(command, shell=False, **_hidden_kwargs(extra_flags, new_session), **kwargs)


def run_hidden(
    command: list[str], timeout: int | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """`subprocess.run` with an argument list, `shell=False`, no console."""
    kwargs = _hidden_kwargs()
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(command, shell=False, capture_output=True, text=True, timeout=timeout, **kwargs)


def start_in_background(
    command: list[str], env: dict | None = None, log_path=None
) -> subprocess.Popen:
    """`subprocess.Popen` with no console, detached from this process — to
    bring up a background server (e.g. `ollama serve`) without waiting for
    it to finish and without any window. Used by `engine_local.py` to try to
    restart Ollama on its own when it doesn't respond.

    `env` replaces the child's environment entirely (it is not merged —
    build the full mapping, as `gpu_budget.server_environment()` does).
    Ollama reads the settings that decide how much of the model fits on the
    GPU once, at server startup, so they can only be applied here.
    """
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if log_path is not None:
        # Output appended to `log_path` (stdout and stderr), when
        # given. The child keeps its own handle; ours is closed right away.
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "ab")
        except OSError:
            log_file = None
        if log_file is not None:
            kwargs["stdout"] = log_file
            kwargs["stderr"] = subprocess.STDOUT
    if env is not None:
        kwargs["env"] = env
    detached = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    try:
        return popen_hidden(command, extra_flags=detached, **kwargs)
    finally:
        if kwargs.get("stdout") not in (None, subprocess.DEVNULL):
            kwargs["stdout"].close()


def kill_tree(process: subprocess.Popen) -> None:
    """Kills the process and its children. Killing only the parent left an
    orphan `soffice.bin` holding its temporary profile and the memory."""
    if sys.platform == "win32":
        try:
            run_hidden(["taskkill", "/T", "/F", "/PID", str(process.pid)], timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass

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
`installer.py` for `nvidia-smi`, PowerShell/WMI, `winget`, silent installers
and the `--version` checks.
"""

from __future__ import annotations

import subprocess
import sys


def run_hidden(command: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    """`subprocess.run` with an argument list, `shell=False`, no console."""
    kwargs: dict = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, shell=False, capture_output=True, text=True, timeout=timeout, **kwargs)


def start_in_background(command: list[str], env: dict | None = None) -> subprocess.Popen:
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
    if env is not None:
        kwargs["env"] = env
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    return subprocess.Popen(command, shell=False, **kwargs)

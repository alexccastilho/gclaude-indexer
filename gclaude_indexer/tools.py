# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Finding the external programs, without depending on `PATH`.

This exists because of a reported behaviour with an ordinary explanation:
after installing on a new computer, nothing worked until the machine was
rebooted.

`install.ps1` adds Tesseract, Ghostscript and Ollama to the user's `PATH`
in the registry and broadcasts `WM_SETTINGCHANGE` so running programs pick
the change up. Explorer, in practice, frequently does not — and every
process Explorer starts (the desktop shortcut, `Indexer.vbs`,
`Indexer.bat`, the server, every subprocess of the server) inherits the
environment Explorer had **when it started**, which is the one from before
the install. So `shutil.which("ollama")` returns `None`, the OCR engine
cannot find Tesseract, and the whole thing looks broken until something
restarts Explorer — which is what logging out or rebooting does. It is not
that the install needs a reboot; it is that the *variable* needs one to
reach the processes that were already running.

Two independent fixes, and this module is one of them (the other is in
`Indexer.bat`, which now rebuilds `PATH` from the registry before starting
the server, so even a stale Explorer cannot poison the run):

1. `install.ps1` writes the absolute path of everything it installed into
   `%LOCALAPPDATA%\\GClaudeIndexer\\tools.json`, at the moment it installs
   it — when it knows exactly where the file went, with no environment
   variable in between.
2. `find()` here consults that file first, then `PATH`, then the standard
   install locations. Any one of the three is enough.

Nothing in this module raises, and none of it is required: a machine whose
`PATH` is fine takes the second branch and behaves exactly as before.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .paths import machine_local_folder

TOOLS_FILE_NAME = "tools.json"

# Where each program normally lands, searched when neither `tools.json` nor
# `PATH` has it. Relative to the environment variables that name the
# folders, never a literal `C:\...` (section 11.5): the system drive is not
# always `C:`, and `%LOCALAPPDATA%` differs per user.
#
# Ghostscript is the awkward one: its executable sits in a version-numbered
# folder (`gs10.06.0\bin\gswin64c.exe`), so the version is globbed rather
# than assumed — this file must not need editing every time Ghostscript
# releases.
_KNOWN_LOCATIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "tesseract": (
        ("PROGRAMFILES", "Tesseract-OCR/tesseract.exe"),
        ("PROGRAMFILES(X86)", "Tesseract-OCR/tesseract.exe"),
        ("LOCALAPPDATA", "Programs/Tesseract-OCR/tesseract.exe"),
    ),
    "gswin64c": (
        ("PROGRAMFILES", "gs/gs*/bin/gswin64c.exe"),
        ("LOCALAPPDATA", "GClaudeIndexer/gs/gs*/bin/gswin64c.exe"),
        ("LOCALAPPDATA", "GClaudeIndexer/gs/bin/gswin64c.exe"),
    ),
    "ollama": (
        ("LOCALAPPDATA", "Programs/Ollama/ollama.exe"),
        ("PROGRAMFILES", "Ollama/ollama.exe"),
    ),
    "nvidia-smi": (
        ("PROGRAMFILES", "NVIDIA Corporation/NVSMI/nvidia-smi.exe"),
        ("WINDIR", "System32/nvidia-smi.exe"),
    ),
}


def tools_path() -> Path:
    return machine_local_folder() / TOOLS_FILE_NAME


def recorded_tools() -> dict:
    """What `install.ps1` recorded. `{}` when there is nothing usable."""
    try:
        data = json.loads(tools_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}


def record_tool(name: str, path: str) -> None:
    """Records where `name` lives. Used by the tests and by any future
    caller that resolves a program the installer did not."""
    recorded = recorded_tools()
    recorded[name] = path
    destination = tools_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(recorded, ensure_ascii=False, indent=2), encoding="utf-8")


def _from_known_locations(name: str) -> str | None:
    for variable, relative in _KNOWN_LOCATIONS.get(name, ()):
        base = os.environ.get(variable)
        if not base:
            continue
        pattern = Path(base) / relative
        if "*" in relative:
            try:
                # Newest version first: `gs10.06.0` sorts after `gs10.02.1`,
                # and a machine with two Ghostscripts should use the newer.
                matches = sorted(Path(base).glob(relative), reverse=True)
            except OSError:
                matches = []
            for match in matches:
                if match.is_file():
                    return str(match)
            continue
        try:
            if pattern.is_file():
                return str(pattern)
        except OSError:
            continue
    return None


def find(name: str) -> str | None:
    """Absolute path of the program `name`, or `None`.

    Order: what the installer recorded, then `PATH`, then the standard
    locations. The recorded path comes first deliberately — it is the only
    one written by the process that actually put the file there, and it is
    the branch that removes the reboot.
    """
    recorded = recorded_tools().get(name)
    if recorded:
        try:
            if Path(recorded).is_file():
                return recorded
        except OSError:
            pass

    on_path = shutil.which(name)
    if on_path:
        return on_path

    return _from_known_locations(name)


def bin_folders() -> list[str]:
    """Folders holding the programs we know about, for adding to a child
    process's `PATH`.

    ocrmypdf looks up `tesseract` and `gswin64c` through `PATH` itself, from
    inside its own process — it takes no configuration for either. Handing
    the OCR subprocess a `PATH` that contains them is how the recorded
    locations reach a library that only knows how to search."""
    folders: list[str] = []
    for name in ("tesseract", "gswin64c"):
        found = find(name)
        if not found:
            continue
        folder = str(Path(found).parent)
        if folder not in folders:
            folders.append(folder)
    return folders


def path_with_tools(base: str | None = None) -> str:
    """`base` (default: this process's `PATH`) with the tool folders added.

    Appended, not prepended: a machine whose `PATH` is already correct
    keeps resolving exactly what it resolved before, and this only ever
    supplies what was missing. Folders already present are not duplicated.
    """
    current = os.environ.get("PATH", "") if base is None else base
    entries = [entry for entry in current.split(os.pathsep) if entry]
    lowered = {entry.rstrip("\\/").casefold() for entry in entries}
    for folder in bin_folders():
        if folder.rstrip("\\/").casefold() not in lowered:
            entries.append(folder)
    return os.pathsep.join(entries)


def ensure_on_path() -> None:
    """Puts the tool folders on *this* process's `PATH`.

    Called once when the server starts. `pytesseract` resolves
    `tesseract.exe` through `PATH` from inside this process and takes no
    configuration for it, so a fresh install whose `PATH` change has not
    reached Explorer yet would fail at the first image — the reboot the
    user should not have needed. Every subprocess inherits the corrected
    value from here.
    """
    os.environ["PATH"] = path_with_tools()

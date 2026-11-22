# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Windows' native folder picker, triggered by the form via HTMX.

Runs inside the server's own process because, in this tool, server and
browser are always on the same machine (local use, single user) — there is
no way to open a native picker from the browser itself. `tkinter` is part
of the Python standard library, no new dependency.
"""

from __future__ import annotations

import sys
import threading

_COINIT_APARTMENTTHREADED = 0x2


def choose_folder(title: str, initial: str = "") -> str | None:
    """Opens the picker in a thread of its own, with COM in STA.

    The caller is a server pool thread, and those are reused: one that
    already ran .NET code through pythonnet (the LibreHardwareMonitor
    sensors) has COM in MTA. There Tk falls back to the old Windows folder
    dialog, which never shows up — Browse opened nothing and the request
    hung. A fresh thread starts with no COM state, so STA is guaranteed.
    """
    outcome: dict = {}

    def body() -> None:
        com_ready = False
        if sys.platform == "win32":
            import ctypes
            # S_OK or S_FALSE; anything else (negative) leaves COM alone.
            com_ready = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED) >= 0
        try:
            outcome["folder"] = _ask(title, initial)
        except BaseException as error:  # re-raised in the caller
            outcome["error"] = error
        finally:
            if com_ready:
                ctypes.windll.ole32.CoUninitialize()

    thread = threading.Thread(target=body, name="folder-picker", daemon=True)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("folder")


def _ask(title: str, initial: str) -> str | None:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        folder = filedialog.askdirectory(title=title, initialdir=initial or None)
    finally:
        root.destroy()
    return folder or None

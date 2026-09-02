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


def choose_folder(title: str, initial: str = "") -> str | None:
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

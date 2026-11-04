# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Process-wide suppression of console windows on Windows.

`subprocess_utils.run_hidden` already hides every command *this* code
starts. It cannot hide the ones our dependencies start: `pytesseract` calls
`tesseract.exe` through its own `subprocess.Popen`, and `ocrmypdf` spawns
`tesseract`, `gswin64c` (Ghostscript), `pngquant` and `jbig2` from inside
its own pipeline. None of those calls pass `CREATE_NO_WINDOW`, and none of
them is ours to change.

That matters more than it looks. A process created with `CREATE_NO_WINDOW`
has no console attached; when it then starts a *console* subprocess with no
flags of its own, Windows does not silently reuse anything — it allocates a
brand-new console for the child **and shows it**. So the server being
windowless is precisely what makes each grandchild flash a black window on
the user's desktop, one per file, for the length of an OCR run. That is the
behaviour reported after the install on a second machine ("several windows
kept popping up on screen during the OCR and Ghostscript conversion").

The fix is to make the suppression a property of the *process*, not of
individual call sites: `install()` wraps `subprocess.Popen.__init__` so
every process created from this interpreter — ours, `pytesseract`'s,
`ocrmypdf`'s — gets `CREATE_NO_WINDOW` and a hidden `STARTUPINFO` unless
the caller deliberately asked for something else.

Three properties this deliberately keeps:

* **Idempotent.** Calling it twice does not stack two wrappers (the
  conversion pool's initializer and `start_server` can both call it).
* **Never overrides an explicit choice.** A caller that already passed
  `creationflags` with a console flag (`CREATE_NEW_CONSOLE`,
  `DETACHED_PROCESS`) or its own `STARTUPINFO` keeps it — the flags are
  merged, never replaced.
* **No-op off Windows.** `CREATE_NO_WINDOW` and `STARTUPINFO` do not exist
  there, and the tests run on both.
"""

from __future__ import annotations

import subprocess
import sys

_ALREADY_INSTALLED_MARKER = "_gclaude_no_window_installed"

# Where `startupinfo` and `creationflags` sit in `Popen.__init__`'s
# positional parameters, `self` excluded. A test reads them back out of
# `inspect.signature` so a future CPython that reorders them is caught here
# rather than in a `TypeError` during someone's OCR run.
_STARTUPINFO_INDEX = 12
_CREATIONFLAGS_INDEX = 13

# Flags that mean "the caller wants its own console arrangement". Adding
# CREATE_NO_WINDOW on top of either is contradictory (Windows rejects
# CREATE_NEW_CONSOLE | CREATE_NO_WINDOW), so those calls are left alone.
_CONSOLE_FLAGS = 0
if sys.platform == "win32":  # pragma: no branch - trivial
    _CONSOLE_FLAGS = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS


def hidden_startupinfo() -> "subprocess.STARTUPINFO | None":
    """A `STARTUPINFO` that asks for a hidden window, or `None` off Windows.

    Belt and braces alongside `CREATE_NO_WINDOW`: a few programs create
    their own top-level window rather than a console, and `SW_HIDE` is what
    covers those.
    """
    if sys.platform != "win32":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def is_installed() -> bool:
    return bool(getattr(subprocess.Popen.__init__, _ALREADY_INSTALLED_MARKER, False))


def install() -> bool:
    """Suppresses console windows for every subprocess of this interpreter.

    Returns `True` if it installed the wrapper now, `False` if it was
    already in place or the platform does not need it. Never raises: a
    failure here must not stop a conversion — the worst case is the flashing
    window we are trying to remove, not a lost document.
    """
    if sys.platform != "win32":
        return False
    if is_installed():
        return False

    original_init = subprocess.Popen.__init__

    def patched_init(self, *args, **kwargs):
        # Positional indices in `Popen.__init__`, `self` excluded (measured,
        # not assumed): `startupinfo` is 12 and `creationflags` is 13. A
        # caller that passed that many positionally has stated both
        # explicitly and is left exactly as it is — injecting a keyword for
        # a parameter already filled positionally would raise `TypeError`.
        if len(args) <= _CREATIONFLAGS_INDEX:
            kwargs["creationflags"] = _merge_flags(kwargs.get("creationflags", 0))
        if len(args) <= _STARTUPINFO_INDEX and kwargs.get("startupinfo") is None:
            kwargs["startupinfo"] = hidden_startupinfo()
        return original_init(self, *args, **kwargs)

    setattr(patched_init, _ALREADY_INSTALLED_MARKER, True)
    # Kept so a test (or a future caller with a genuine need for a console)
    # can put the original back.
    setattr(patched_init, "_gclaude_original_init", original_init)
    subprocess.Popen.__init__ = patched_init
    return True


def uninstall() -> bool:
    """Puts the original `Popen.__init__` back. Only used by the tests."""
    original = getattr(subprocess.Popen.__init__, "_gclaude_original_init", None)
    if original is None:
        return False
    subprocess.Popen.__init__ = original
    return True


def _merge_flags(creationflags: int) -> int:
    """`creationflags` plus `CREATE_NO_WINDOW`, unless the caller asked for
    a console of its own."""
    if sys.platform != "win32":
        return creationflags
    if creationflags & _CONSOLE_FLAGS:
        return creationflags
    return creationflags | subprocess.CREATE_NO_WINDOW

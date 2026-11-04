# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Applies `no_window.install()` to every Python interpreter that inherits
our OCR environment.

`_ocr_runner.py` covers the interpreter that ocrmypdf's command line runs
in. It does not cover the interpreters ocrmypdf itself starts: with
`--jobs N` it builds a process pool, and on Windows those workers are
`spawn`ed as fresh interpreters that import only what they need — the
runner's `install()` call is not part of that. Each of those workers is the
direct parent of a `tesseract.exe`, so without this file the flashing
console windows come back the moment `--jobs` is greater than 1.

`sitecustomize` is the standard library's own hook for exactly this: the
`site` module imports it, by that name, from `sys.path`, in every
interpreter, before any user code runs. `conversion.py` puts this folder on
the `PYTHONPATH` of the OCR subprocess only, and `spawn` passes the
environment down — so the hook reaches every descendant of an OCR run and
nothing else on the machine.

Silent and total in its failure handling on purpose: a machine that already
has its own `sitecustomize`, an unexpected Python build, anything at all —
the worst outcome allowed here is the console window we were trying to
hide, never a failed conversion.
"""

try:
    from gclaude_indexer import no_window

    no_window.install()
except Exception:  # pragma: no cover - defensive; never break an interpreter
    pass

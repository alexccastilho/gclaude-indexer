# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""`ocrmypdf`'s command line, with console windows suppressed.

`conversion.py` runs OCR as `python -m gclaude_indexer._ocr_runner ...`
instead of `python -m ocrmypdf ...`. The arguments are identical and are
forwarded untouched; the only thing this module adds is a call to
`no_window.install()` **before** ocrmypdf imports anything, so that every
process ocrmypdf then starts — `tesseract.exe` once per page,
`gswin64c.exe` once or twice per file, plus `pngquant`/`jbig2` when
present — inherits `CREATE_NO_WINDOW` and never flashes a console over the
user's desktop.

Doing it here rather than inside the worker process is what makes it
complete: the flag has to be set in the interpreter that is the *direct
parent* of tesseract and Ghostscript, and that interpreter is this one.
See `no_window.py` for why a windowless parent is precisely what makes its
console children visible.
"""

from __future__ import annotations

import sys

# The project folder is synced by Google Drive — never write __pycache__
# into it (section 11.1). This process is started fresh for every OCR'd
# file, so it has to repeat what the server's entry point already does.
sys.dont_write_bytecode = True


# 2.1.3: teto da resolução em que o ocrmypdf rasteriza uma página. Ele usa a
# maior resolução das imagens dela, e um ícone de 700×600 px desenhado em
# 11×10 pontos (toda página dos processos do órgão) dá 4.500 DPI: a folha A4
# virava 1,96 gigapixel, o Pillow recusava como "decompression bomb" e o OCR
# do arquivo inteiro falhava. O Tesseract lê bem a partir de 300 DPI.
MAX_RASTER_DPI = 400.0


def limit_raster_dpi() -> None:
    """Limita a `MAX_RASTER_DPI` a resolução que o ocrmypdf calcula para a
    página. Todo uso dela (rasterizar, endireitar, o OCR) passa por
    `_pipeline.calculate_image_dpi`, e as páginas rodam em threads deste
    processo (`use_threads`, o padrão), então trocar a função aqui vale para
    todas."""
    from ocrmypdf import _pipeline
    from ocrmypdf.helpers import Resolution

    original = _pipeline.calculate_image_dpi
    if getattr(original, "_gclaude_limited", False):
        return

    def limited(page_context):
        dpi = original(page_context)
        return Resolution(min(dpi.x or 0.0, MAX_RASTER_DPI), min(dpi.y or 0.0, MAX_RASTER_DPI))

    limited._gclaude_limited = True
    _pipeline.calculate_image_dpi = limited


def main(argv: list[str] | None = None) -> int:
    from . import no_window

    no_window.install()
    limit_raster_dpi()

    arguments = sys.argv[1:] if argv is None else argv
    from ocrmypdf.__main__ import run

    # `run(args=...)` takes the argument list directly, so nothing depends
    # on `sys.argv` still holding this module's own name.
    return int(run(args=list(arguments)) or 0)


if __name__ == "__main__":
    sys.exit(main())

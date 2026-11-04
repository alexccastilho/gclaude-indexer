# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Busca por tema numa pasta de saída, a partir do código-fonte (fase 38).

    python tools/buscar.py "<pasta de saída>" saneamento
    python tools/buscar.py "<pasta de saída>" "segurança alimentar" --so-legislacao --lexml

É o mesmo `gclaude_indexer.search_cli` que o `buscar.bat` de cada pasta de
saída chama; este invólucro só serve para quem roda a partir do repositório.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from gclaude_indexer.search_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

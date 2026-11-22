# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""O `servidor.log` do servidor sem console, com tamanho limitado.

`run_server.py` importa isto antes de qualquer coisa que imprima, então
este módulo não importa nada do resto do pacote.

2.1.3: o arquivo era aberto em modo de acréscimo a cada início e só crescia.
A tela de Execução consulta o servidor cinco vezes a cada 2 s, e cada
consulta deixa uma linha de acesso: numa máquina em uso passou de 19 MB.
Agora, acima de `MAX_BYTES` no início, o atual vira `servidor.log.1` (que
substitui o anterior) e começa um novo. As linhas de acesso ficam: são elas
que mostram, depois, o que a tela pediu e quando.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

LOG_NAME = "servidor.log"
MAX_BYTES = 5 * 1024 * 1024


def open_server_log(folder: Path | str) -> TextIO:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    try:
        if path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_name(LOG_NAME + ".1"))
    except OSError:
        # Sem o arquivo, ou outro processo com ele aberto: segue acrescentando.
        pass
    return open(path, "a", encoding="utf-8", buffering=1)

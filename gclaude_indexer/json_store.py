# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Leitura e gravação dos registros JSON desta máquina: catálogos (local e
compartilhado), sincronização, conjuntos, preferências, diário e adiamento
da mudança de pasta.

Quem chama diz o caminho; este módulo nunca procura a pasta local sozinho.
É assim que os testes isolam os registros reais: trocam a pasta no módulo
dono de cada registro (`catalog.machine_local_folder`,
`relocation._journal_path`...), e a troca vale aqui também.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .paths import write_text_atomic

# Uma leitura ou gravação de registro por vez no processo. No NTFS,
# `os.replace` falha enquanto outra thread tem o arquivo aberto para ler, e
# as telas leem o catálogo a cada pedido.
_LOCK = threading.RLock()


def read_json(path: Path, default):
    """O conteúdo de `path`, ou `default` se o arquivo faltar, não puder ser
    lido, não for UTF-8 ou não for JSON. O tipo do conteúdo quem confere é
    quem chama."""
    with _LOCK:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return default


def write_json(path: Path, data) -> None:
    """Grava `data` no formato de sempre dos registros (recuo de 2, acentos
    sem escape) com troca atômica (`paths.write_text_atomic`)."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with _LOCK:
        write_text_atomic(path, text)

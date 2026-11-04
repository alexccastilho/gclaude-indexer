"""Ponto de entrada: sobe a interface web do GClaude Indexer em 127.0.0.1.

Uso:
    python run_server.py
"""

import os
import sys

# A pasta do projeto é sincronizada pelo Google Drive — nunca gravar
# __pycache__ nela (seção 11.1). O conftest.py faz isso pelos testes; aqui
# é preciso repetir, porque este é o ponto de entrada de verdade.
#
# As duas formas, e não só a primeira: `sys.dont_write_bytecode` vale para
# este interpretador e não alcança os que a conversão cria. No Windows o
# `ProcessPoolExecutor` usa `spawn`, então cada worker é um interpretador
# novo que reimporta `gclaude_indexer` — e, sem a variável de ambiente (que
# ele herda, ao contrário do atributo), grava um `__pycache__` dentro da
# pasta sincronizada. O `Indexer.bat` já define a variável; quem chama
# `python run_server.py` na mão, não.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Lançado sem console (pythonw.exe, via Indexer.vbs — versão 1.0, pedido
# explícito do usuário para não haver janela do servidor) o Windows nunca dá
# um stdout/stderr de verdade a este processo: ficam `None`. O primeiro
# `print()` ou log do próprio uvicorn bateria em `None.write(...)` e
# derrubaria o processo na hora, sem deixar rastro nenhum — é exatamente o
# que fazia o servidor "sumir" ao abrir pelo atalho. Redireciona os dois
# para um arquivo local (fora da pasta sincronizada, como o resto do que é
# só desta máquina) antes de importar qualquer coisa que possa imprimir.
if sys.stdout is None or sys.stderr is None:
    _pasta_log = os.path.join(os.environ.get("LOCALAPPDATA", "."), "GClaudeIndexer")
    os.makedirs(_pasta_log, exist_ok=True)
    _arquivo_log = open(os.path.join(_pasta_log, "servidor.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = _arquivo_log
    sys.stderr = _arquivo_log

from gclaude_indexer.web.app import start_server  # noqa: E402

if __name__ == "__main__":
    start_server()

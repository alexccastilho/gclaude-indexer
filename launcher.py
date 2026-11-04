"""Iniciador: garante o ambiente desta máquina antes de subir o servidor
(seção 11.2). É o ponto de entrada recomendado — `run_server.py`
assume que o ambiente já está pronto.

Roda primeiro com qualquer Python disponível no sistema — usa só a
biblioteca padrão até aqui, porque fastapi/uvicorn/etc. só existem depois
de garantidos no ambiente virtual local:

1. Existe `%LOCALAPPDATA%\\GClaudeIndexer\\venv`? Não existindo, cria.
2. O hash de `requirements.txt` mudou desde a última instalação? Mudando
   (ou na primeira vez), roda `pip install -r requirements.txt` e grava o
   novo hash.
3. Tesseract e Ghostscript estão presentes? Faltando, dispara a instalação
   silenciosa da seção 10.
4. Sobe o servidor usando o Python do ambiente virtual.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

# A pasta do projeto é sincronizada pelo Google Drive — nunca gravar
# __pycache__ nela (seção 11.1).
sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gclaude_indexer.paths import machine_local_folder, app_root  # noqa: E402
from gclaude_indexer.subprocess_utils import run_hidden  # noqa: E402

NOME_ARQUIVO_HASH_REQUIREMENTS = "requirements.sha256"


def _python_do_venv(pasta_venv: Path) -> Path:
    if sys.platform == "win32":
        return pasta_venv / "Scripts" / "python.exe"
    return pasta_venv / "bin" / "python"


def _ja_estamos_no_venv(pasta_venv: Path) -> bool:
    try:
        return Path(sys.executable).resolve() == _python_do_venv(pasta_venv).resolve()
    except OSError:
        return False


def _garantir_venv(pasta_venv: Path) -> None:
    if pasta_venv.exists():
        return
    print(f"[iniciador] criando ambiente virtual em {pasta_venv} ...")
    resultado = run_hidden([sys.executable, "-m", "venv", str(pasta_venv)], timeout=300)
    if resultado.returncode != 0:
        raise RuntimeError(f"não foi possível criar o ambiente virtual: {resultado.stderr}")


def _hash_arquivo(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _garantir_dependencias(pasta_venv: Path, caminho_requirements: Path, caminho_hash: Path) -> bool:
    """Devolve True se instalou/reinstalou algo."""
    hash_atual = _hash_arquivo(caminho_requirements)
    hash_anterior = caminho_hash.read_text(encoding="utf-8").strip() if caminho_hash.exists() else None

    if hash_atual == hash_anterior:
        return False

    print("[iniciador] requirements.txt mudou (ou é a primeira vez) — instalando dependências...")
    python_venv = _python_do_venv(pasta_venv)
    resultado = run_hidden(
        [str(python_venv), "-m", "pip", "install", "-r", str(caminho_requirements)], timeout=1800,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"'pip install -r requirements.txt' falhou:\n{resultado.stderr}")

    caminho_hash.parent.mkdir(parents=True, exist_ok=True)
    caminho_hash.write_text(hash_atual, encoding="utf-8")
    print("[iniciador] dependências instaladas.")
    return True


def preparar_ambiente() -> Path:
    """Passos 1-3 da seção 11.2. Devolve o Python do venv local, pronto
    para rodar o servidor."""
    pasta_venv = machine_local_folder() / "venv"
    _garantir_venv(pasta_venv)

    caminho_requirements = app_root() / "requirements.txt"
    caminho_hash = machine_local_folder() / NOME_ARQUIVO_HASH_REQUIREMENTS
    _garantir_dependencias(pasta_venv, caminho_requirements, caminho_hash)

    # Tesseract, Ghostscript, Ollama e as bibliotecas de sensores ficam a
    # cargo do `install.ps1`, que o `Indexer.bat` chama sozinho quando o
    # ambiente ainda não existe. Este módulo já tentou instalá-los por conta
    # própria, com uma segunda implementação em Python: ela ficou para trás
    # (rodava o instalador do Ghostscript com `/S` e esperava 900 s por uma
    # janela que espera um clique) justamente porque duplicava o trabalho e
    # ninguém olhava as duas. Um instalador só.
    return _python_do_venv(pasta_venv)


def main() -> None:
    pasta_venv = machine_local_folder() / "venv"

    if _ja_estamos_no_venv(pasta_venv):
        # Já rodando com o Python certo (fomos relançados pelo passo abaixo,
        # ou chamados diretamente de dentro do venv): sobe o servidor.
        from gclaude_indexer.web.app import start_server

        start_server()
        return

    python_venv = preparar_ambiente()
    print(f"[iniciador] ambiente pronto. Subindo o servidor com {python_venv} ...")
    ambiente_filho = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([str(python_venv), str(Path(__file__).resolve())], shell=False, env=ambiente_filho)


if __name__ == "__main__":
    main()

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Formatos antigos (`.doc .ppt .wpd .wps .pub .vsd`…) pelo LibreOffice (2.0.0).

Nenhuma biblioteca Python lê esses formatos; o LibreOffice lê. Ele vira um
componente baixado sob demanda (`components`, nome `libreoffice`), só quando
o acervo tem um desses arquivos, e converte cada um para PDF: dali em diante
é o caminho do PDF (texto nativo, OCR das páginas sem texto).

Como a conversão é feita:
- `soffice --headless --convert-to pdf`, lista de argumentos, sem shell e
  sem janela;
- um perfil temporário só daquela execução (`-env:UserInstallation`): nunca
  o perfil do usuário, nunca um que sobra de uma execução travada;
- o arquivo é copiado para um nome simples dentro de uma pasta temporária
  (o LibreOffice engasga com alguns caminhos e o Google Drive pode estar
  segurando o original); espaços e acentos do caminho de origem não chegam a
  ele;
- uma conversão por vez neste processo (cada `soffice` carrega centenas de
  megabytes, e dois no mesmo perfil de instalação se atropelam);
- tempo limite por arquivo; passado dele, a árvore inteira de processos é
  morta (o `soffice.exe` é só um lançador do `soffice.bin`).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import components

COMPONENT_NAME = "libreoffice"
# Onde o executável fica dentro do componente extraído.
SOFFICE_RELATIVE = "program/soffice.exe"
CONVERT_TIMEOUT_S = 120

_STANDARD_LOCATIONS = (
    "ProgramFiles", "ProgramFiles(x86)",
)

_lock = threading.Lock()


class LegacyOfficeError(Exception):
    """Falha ao converter. A mensagem não leva conteúdo de documento."""


def soffice_path() -> Path | None:
    """O `soffice` que existe agora: o do componente baixado, senão um
    LibreOffice já instalado na máquina (pasta padrão do instalador deles).
    `None` quando nenhum existe."""
    folder = components.path_of(COMPONENT_NAME)
    if folder is not None:
        candidate = folder / SOFFICE_RELATIVE
        if candidate.is_file():
            return candidate
    for variable in _STANDARD_LOCATIONS:
        base = os.environ.get(variable)
        if not base:
            continue
        candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.is_file():
            return candidate
    return None


def ensure_available() -> Path | None:
    """O `soffice`, baixando o componente se faltar. `None` quando não foi
    possível (sem rede, download recusado): quem chama deixa o arquivo
    pendente."""
    found = soffice_path()
    if found is not None:
        return found
    components.ensure([COMPONENT_NAME])
    return soffice_path()


# --- processo ----------------------------------------------------------------


def _popen(command: list[str], env: dict) -> subprocess.Popen:
    """O único ponto que cria o processo (a suíte o troca por um simulador)."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, shell=False, env=env, **kwargs)


def _kill_tree(process: subprocess.Popen) -> None:
    """Mata o processo e os filhos dele. Sem isso o `soffice.bin` órfão
    continua segurando o perfil temporário e a memória."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                shell=False, capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def _command(soffice: Path, profile: Path, outdir: Path, source: Path) -> list[str]:
    return [
        str(soffice), "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--convert-to", "pdf", "--outdir", str(outdir), str(source),
    ]


def convert_to_pdf_bytes(source: Path, soffice: Path, timeout: float = CONVERT_TIMEOUT_S) -> bytes:
    """O documento como PDF. Levanta `LegacyOfficeError` (tempo limite,
    arquivo que o LibreOffice não abre, saída que não é PDF)."""
    with _lock, tempfile.TemporaryDirectory(prefix="gclaude-lo-", ignore_cleanup_errors=True) as work:
        work_path = Path(work)
        profile = work_path / "perfil"
        outdir = work_path / "saida"
        indir = work_path / "entrada"
        for folder in (profile, outdir, indir):
            folder.mkdir()
        # Nome simples, mantendo só a extensão: o LibreOffice escolhe o filtro
        # de importação por ela.
        copy = indir / ("documento" + source.suffix.lower())
        try:
            shutil.copyfile(source, copy)
        except OSError as exc:
            raise LegacyOfficeError(f"não foi possível ler o arquivo: {exc.strerror or 'erro de leitura'}") from exc

        try:
            process = _popen(_command(soffice, profile, outdir, copy), dict(os.environ))
        except OSError as exc:
            raise LegacyOfficeError(f"não foi possível iniciar o LibreOffice: {exc.strerror or 'erro'}") from exc
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            raise LegacyOfficeError(
                f"o LibreOffice passou de {int(timeout)} s e foi encerrado (arquivo travado, protegido ou corrompido)"
            ) from None
        except BaseException:
            _kill_tree(process)
            raise

        produced = outdir / (copy.stem + ".pdf")
        if code != 0 or not produced.is_file():
            raise LegacyOfficeError("o LibreOffice não conseguiu converter o arquivo (protegido por senha ou corrompido)")
        data = produced.read_bytes()
        if not data.startswith(b"%PDF"):
            raise LegacyOfficeError("o LibreOffice não produziu um PDF")
        return data

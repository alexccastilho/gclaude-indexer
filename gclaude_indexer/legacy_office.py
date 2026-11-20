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
- o perfil nasce já travado (`registrymodifications.xcu`, ver `PROFILE_LOCKDOWN`):
  macros desligadas, vínculos, campos e gráficos externos sem atualização ao
  abrir, vínculos de origem não confiável bloqueados e a verificação de
  atualização do próprio LibreOffice desligada. Isso fecha os caminhos mais
  comuns para um documento de terceiros ler arquivos locais ou fazer o
  computador acessar a rede, mas não é uma garantia de que o LibreOffice
  nunca busque nada (o mesmo que o SECURITY.md promete: macros, vínculos e
  atualizador desligados); o LibreOffice ainda é isolado do perfil do usuário;
- uma conversão por vez neste processo (cada `soffice` carrega centenas de
  megabytes, e dois no mesmo perfil de instalação se atropelam);
- tempo limite por arquivo; passado dele, a árvore inteira de processos é
  morta (o `soffice.exe` é só um lançador do `soffice.bin`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import components
from .subprocess_utils import kill_tree

COMPONENT_NAME = "libreoffice"
# Onde o executável fica dentro do componente extraído.
SOFFICE_RELATIVE = "program/soffice.exe"
CONVERT_TIMEOUT_S = 120

_STANDARD_LOCATIONS = (
    "ProgramFiles", "ProgramFiles(x86)",
)

# Um LibreOffice já instalado na máquina só serve se for desta versão ou
# mais nova (as anteriores têm filtros de importação com falhas de segurança
# corrigidas depois); abaixo disso, ou sem versão legível, o componente
# baixado é o único aceito. O componente, quando existe, sempre vem antes.
MIN_SYSTEM_VERSION = (7, 6)

# (caminho da configuração, nome, tipo, valor): vai para o perfil de cada
# execução antes de o `soffice` abrir. Só chaves que existem no esquema do
# LibreOffice (conferidas em `share/registry/main.xcd` da 26.2).
PROFILE_LOCKDOWN: tuple[tuple[str, str, str, str], ...] = (
    # Nunca atualizar vínculos, campos e gráficos ao abrir o documento
    # (Calc/Writer: 2 = nunca).
    ("/org.openoffice.Office.Calc/Content/Update", "Link", "int", "2"),
    ("/org.openoffice.Office.Writer/Content/Update", "Link", "int", "2"),
    ("/org.openoffice.Office.Writer/Content/Update", "Field", "boolean", "false"),
    ("/org.openoffice.Office.Writer/Content/Update", "Chart", "boolean", "false"),
    # Macros: nível "muito alto" e execução desligada.
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "int", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "boolean", "true"),
    # Vínculos que vêm de outro documento ou de fora não são seguidos.
    ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "boolean", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "CheckDocumentEvents", "boolean", "true"),
    # Sem verificação de atualização do próprio LibreOffice pela rede.
    ("/org.openoffice.Office.Update/Update", "Enabled", "boolean", "false"),
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
            version = _version_of(candidate)
            if version is not None and version >= MIN_SYSTEM_VERSION:
                return candidate
    return None


def _version_of(soffice: Path) -> tuple[int, int] | None:
    """`(major, minor)` lida do `bootstrap.ini` ao lado do `soffice`
    (`ProductKey=LibreOffice 26.2`). `None` se ilegível."""
    import re

    try:
        text = (soffice.parent / "bootstrap.ini").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = re.search(r"^ProductKey\s*=\s*LibreOffice\s+(\d+)\.(\d+)", text, re.MULTILINE | re.IGNORECASE)
    return (int(found.group(1)), int(found.group(2))) if found else None


def write_profile(profile: Path) -> Path:
    """Grava o `registrymodifications.xcu` travado em `<profile>/user/`,
    onde o LibreOffice o lê ao criar o perfil. Devolve o caminho."""
    from xml.sax.saxutils import quoteattr

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry"'
        ' xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    ]
    for path, name, kind, value in PROFILE_LOCKDOWN:
        lines.append(
            f'<item oor:path={quoteattr(path)}><prop oor:name={quoteattr(name)} oor:op="fuse">'
            f"<value>{value}</value></prop></item>"
        )
    lines.append("</oor:items>")
    target = profile / "user" / "registrymodifications.xcu"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def ensure_available(should_stop=None, on_download=None) -> Path | None:
    """O `soffice`, baixando o componente se faltar. `None` quando não foi
    possível (sem rede, download recusado, Parar no meio do download): quem
    chama deixa o arquivo pendente. `should_stop` e `on_download` vão para
    `components.ensure`."""
    found = soffice_path()
    if found is not None:
        return found
    components.ensure([COMPONENT_NAME], should_stop=should_stop, on_download=on_download)
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
        # Antes de o `soffice` abrir: ele lê estas chaves ao criar o perfil.
        write_profile(profile)
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
            kill_tree(process)
            raise LegacyOfficeError(
                f"o LibreOffice passou de {int(timeout)} s e foi encerrado (arquivo travado, protegido ou corrompido)"
            ) from None
        except BaseException:
            kill_tree(process)
            raise

        produced = outdir / (copy.stem + ".pdf")
        if code != 0 or not produced.is_file():
            raise LegacyOfficeError("o LibreOffice não conseguiu converter o arquivo (protegido por senha ou corrompido)")
        data = produced.read_bytes()
        if not data.startswith(b"%PDF"):
            raise LegacyOfficeError("o LibreOffice não produziu um PDF")
        return data

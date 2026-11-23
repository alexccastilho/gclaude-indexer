# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Path resolution without relying on a fixed absolute path or drive letter.

Rule from spec section 11.5: the application root is located from the
running file's own position, never hard-coded as an absolute path in code
or in the database. Every relative-path resolution against a base is
validated to prevent escaping it (including via `..`), per section 7.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import threading
import time
from pathlib import Path


def app_root() -> Path:
    """Application package root, derived from this file's own location."""
    return Path(__file__).resolve().parent.parent


# Overrides the folder below. Set by the elevated sensor helper, which
# receives it on its command line (`sensor_service.py`): elevating with a
# *different* administrator account than the logged-on one changes
# `%LOCALAPPDATA%`, and the helper would then publish its reading into a
# folder the server never looks at. The server's own value is passed down
# so both processes agree on one folder no matter whose token is running.
LOCAL_FOLDER_ENV = "GCLAUDE_INDEXER_LOCAL_FOLDER"


def machine_local_folder() -> Path:
    """Per-machine local folder for what cannot live in the Drive-synced
    folder: venv, Ollama models, downloaded installers (section 11.1).
    Resolved at runtime from `%LOCALAPPDATA%`, never hard-coded as a literal
    path."""
    override = os.environ.get(LOCAL_FOLDER_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "GClaudeIndexer"


def resolve_within(base: Path, relative: str) -> Path:
    """Resolves `relative` inside `base`, refusing any escape attempt.

    Raises `ValueError` if the resulting path is not contained in `base`
    (for example, through `..` or a disguised absolute path).
    """
    resolved_base = Path(base).resolve()
    candidate = (resolved_base / relative).resolve()

    try:
        common = os.path.commonpath([str(resolved_base), str(candidate)])
    except ValueError:
        # Different Windows drive letters — there's no way to be contained.
        raise ValueError(
            f"Path '{relative}' is outside the allowed folder '{resolved_base}'"
        )

    if common != str(resolved_base):
        raise ValueError(
            f"Path '{relative}' is outside the allowed folder '{resolved_base}'"
        )

    return candidate


def natural_sort_key(text: str) -> list[int | str]:
    """Sort key where "doc10" comes after "doc2", not before it.

    Lived in `extraction.py` as `_natural_sort_key` until Phase 17, when
    `windows_prep.pages_for_group` needed the same ordering: the windows
    and the classification slice the group's pages by position, so the two
    must agree on what that position is.
    """
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


# --- Pastas de um projeto novo (2.0.0) ---------------------------------------

# A pasta de saída sugerida é irmã da origem: `<pai>\<nome>-AI`. Ela nunca
# fica dentro da origem, senão o próprio índice gerado seria lido como
# documento do acervo na reindexação.
OUTPUT_FOLDER_SUFFIX = "AI"
PROJECT_DB_NAME = "project.db"
# What the classification engines write, one item per line, and the import
# step reads back into the database.
RAW_ITEMS_FILE_NAME = "raw_items.jsonl"
# Marcador que os Conjuntos gravam na pasta de destino (que não tem
# `project.db`): é o que faz a varredura de qualquer projeto reconhecer a
# pasta como saída gerada e não indexá-la como documento.
OUTPUT_MARKER_NAME = ".gclaude-output"
_WRITE_PROOF_NAME = ".gclaude-escrita-teste"


def _normalize_folder(text: str) -> Path | None:
    """Caminho absoluto e resolvido, ou `None` se o texto não for absoluto.

    `H:XYZ` (unidade sem barra) é relativo ao diretório corrente daquela
    unidade e, resolvido, cairia numa pasta qualquer; por isso é recusado
    em vez de "consertado". O Windows descarta ponto e espaço no fim do
    último componente ao criar a pasta, então `resolve` sozinho deixaria
    `Acervo.` e `Acervo` parecerem pastas diferentes."""
    text = (text or "").strip()
    if not text or not Path(text).is_absolute():
        return None
    path = Path(text).resolve(strict=False)
    stripped = path.name.rstrip(" .")
    if stripped and stripped != path.name:
        path = path.with_name(stripped)
    return path


def folder_key(folder) -> str:
    """Identidade de uma pasta para "é a mesma pasta?": absoluta, resolvida
    pelo disco (nome curto 8.3, junção, unidade de `subst`, `..`, barra no
    fim) e sem distinção de maiúsculas, que no Windows não distinguem pastas
    (`normcase`, não `casefold`: `Straße` e `STRASSE` são pastas
    diferentes). `strict=False`: a pasta pode não existir (já mudou de
    lugar). É a chave gravada no diário e no adiamento da mudança de pasta:
    mudar a normalização perde os registros que já existem."""
    try:
        resolved = Path(os.path.abspath(str(folder))).resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(str(folder)))
    return os.path.normcase(os.path.normpath(str(resolved)))


def folder_spelling_key(folder) -> str:
    """A pasta como foi escrita: absoluta, normalizada (`..`, barras, barra
    no fim) e sem distinção de maiúsculas, *sem* perguntar ao disco. Para
    quando a grafia é o que conta: achar uma junção (que `folder_key`
    seguiria), decidir se a pasta aberta é a gravada, e o nome da pasta de
    trabalho (`workdir.work_folder`), que é derivado desta chave e não pode
    mudar."""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(folder))))


def resolved_folder(folder) -> str:
    """A pasta resolvida pelo disco, na grafia que ele devolve (no Google
    Drive, a caixa digitada fica). Chave gravada em `sincronizacao.json` e
    usada em memória pela trava e pelos leitores das telas, que a usam
    também como caminho; por isso não passa por `normcase`."""
    return str(Path(folder).resolve())


def _key(path: Path) -> Path:
    return Path(folder_spelling_key(path))


def _same_folder(a: Path, b: Path) -> bool:
    if _key(a) == _key(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def is_inside_folder(child: Path, parent: Path) -> bool:
    """`child` está em `parent` (ou é ele). Compara os caminhos resolvidos e,
    para pegar junctions, links e nomes curtos 8.3, também cada ancestral
    existente de `child` com `os.path.samefile`. Unidades diferentes nunca
    se contêm."""
    if _key(child).is_relative_to(_key(parent)):
        return True
    for ancestor in (child, *child.parents):
        if ancestor.exists() and parent.exists() and _same_folder(ancestor, parent):
            return True
    return False


def holds_generated_output(entry_names) -> bool:
    """Uma pasta com `project.db` ou com o marcador dos Conjuntos é saída
    gerada. Recebe os nomes que a listagem da pasta já trouxe, para a
    varredura não pagar uma consulta ao disco por pasta."""
    names = {name.lower() for name in entry_names}
    return PROJECT_DB_NAME in names or OUTPUT_MARKER_NAME in names


def _is_root(path: Path) -> bool:
    # Raiz de unidade (`H:\`) ou de compartilhamento UNC (`\\srv\share`):
    # `anchor` cobre os dois e não existe pasta-irmã de uma raiz.
    return path == Path(path.anchor)


def _is_free(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


# O Google Drive para computador mostra cada pasta compartilhada comigo (e
# alcançada por um atalho) em `<unidade>\.shortcut-targets-by-id\<id>\<pasta>`.
# A pasta `<id>` só aceita a pasta compartilhada: criar qualquer outra coisa ali
# falha ("Função incorreta"). A irmã `<pasta>-AI` então vai para o "Meu Drive"
# da mesma unidade, cujo nome depende do idioma da conta.
_DRIVE_SHORTCUT_TARGETS = ".shortcut-targets-by-id"
_MY_DRIVE_NAMES = ("Meu Drive", "My Drive", "Mi unidad", "Mon Drive", "Meine Ablage", "Il mio Drive")


def _in_shortcut_container(folder: Path) -> bool:
    """`folder` fica direto na pasta `<id>` de um atalho do Drive, onde nada
    além da pasta compartilhada pode ser criado."""
    return folder.parent.parent.name.lower() == _DRIVE_SHORTCUT_TARGETS


def _shortcut_target(lnk: Path) -> str | None:
    """O destino de um atalho `.lnk` do Windows, pelo próprio Windows. Na
    unidade virtual do Drive o arquivo do atalho não abre para leitura
    (`Errno 22`), então ler o formato direto não serve. `None` se falhar."""
    if os.name != "nt":
        return None
    import subprocess

    # O caminho vai por variável de ambiente: nada dele é lido como código. A
    # saída em UTF-8: o PowerShell 5.1 escreveria na página de código OEM e um
    # caminho com acento ("C:\Users\João\...") voltaria estragado.
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "(New-Object -ComObject WScript.Shell).CreateShortcut($env:GCLAUDE_LNK).TargetPath"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            env={**os.environ, "GCLAUDE_LNK": str(lnk)},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    target = (result.stdout or "").strip()
    return target or None


def _my_drive_folder(shortcut_target: Path) -> Path | None:
    drive_root = shortcut_target.parent.parent.parent
    for name in _MY_DRIVE_NAMES:
        candidate = drive_root / name
        if candidate.is_dir():
            return candidate
    # 2.1.4: "Meu Drive" espelhado numa pasta local; na unidade do Drive fica
    # só o atalho `Meu Drive.lnk` apontando para ela.
    for name in _MY_DRIVE_NAMES:
        lnk = drive_root / f"{name}.lnk"
        if not lnk.exists():
            continue
        target = _shortcut_target(lnk)
        if target and Path(target).is_dir():
            return Path(target)
    return None


def suggest_output_folder(source: str) -> str | None:
    """`<pai>/<nome>-AI`, ou `-AI-2`, `-AI-3`... se já existir e não estiver
    vazia. Para pasta compartilhada do Google Drive, o pai é o "Meu Drive".
    `None` para origem que não é caminho absoluto, é raiz ou é pasta
    compartilhada numa unidade sem "Meu Drive" reconhecível."""
    origin = _normalize_folder(source)
    if origin is None or _is_root(origin):
        return None
    parent = origin.parent
    if _in_shortcut_container(origin):
        parent = _my_drive_folder(origin)
        if parent is None:
            return None
    base = f"{origin.name}-{OUTPUT_FOLDER_SUFFIX}"
    candidate = parent / base
    number = 2
    while not _is_free(candidate):
        candidate = parent / f"{base}-{number}"
        number += 1
    return str(candidate)


def check_new_project_folders(source: str, output: str) -> list:
    """Regras de pasta da *criação* de um projeto. Fica de fora de
    `config._validate` de propósito (devolve `ConfigErrorMessage`): aquela roda a cada abertura de projeto,
    e um projeto criado na 1.10 com a saída dentro da origem tem de seguir
    abrindo."""
    origin = _normalize_folder(source)
    destination = _normalize_folder(output)
    # Importado aqui, e por nome: este módulo é copiado sozinho para o leitor
    # de sensores elevado (`sensor_service.HELPER_MODULES`), que não tem
    # `config`, e o teste dessa lista procura as importações relativas do arquivo.
    ConfigErrorMessage = importlib.import_module(f"{__package__}.config").ConfigErrorMessage

    errors: list = []
    if origin is None:
        errors.append(ConfigErrorMessage("config_error.output_not_absolute", {"path": source}))
    if destination is None:
        errors.append(ConfigErrorMessage("config_error.output_not_absolute", {"path": output}))
    if origin is None or destination is None:
        return errors

    if _is_root(origin):
        return [ConfigErrorMessage("config_error.source_is_drive_root", {"path": str(origin)})]

    if _same_folder(destination, origin):
        return [ConfigErrorMessage("config_error.output_same_as_source", {"path": str(destination)})]
    if is_inside_folder(destination, origin):
        return [ConfigErrorMessage("config_error.output_inside_source", {"path": str(destination)})]
    if is_inside_folder(origin, destination):
        return [ConfigErrorMessage("config_error.source_inside_output", {"path": str(destination)})]

    if not destination.exists() and _in_shortcut_container(destination):
        return [
            ConfigErrorMessage(
                "config_error.output_in_shortcut_container",
                {"path": str(destination), "suggestion": suggest_output_folder(str(origin)) or ""},
            )
        ]

    if destination.exists() and not (destination / PROJECT_DB_NAME).exists():
        if not destination.is_dir():
            return [ConfigErrorMessage("config_error.output_not_writable", {"path": str(destination)})]
        if not _is_free(destination):
            return [
                ConfigErrorMessage(
                    "config_error.output_not_empty",
                    {"path": str(destination), "suggestion": suggest_output_folder(str(origin)) or ""},
                )
            ]
    return []


def ensure_writable_folder(folder: str) -> bool:
    """Cria a pasta (se faltar) e prova que dá para gravar nela. Devolve se
    foi *criada agora*, para o chamador desfazer se o resto falhar. Levanta
    `OSError` (sem permissão, unidade ausente, nome inválido)."""
    path = Path(folder)
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    proof = path / _WRITE_PROOF_NAME
    try:
        proof.write_text("", encoding="utf-8")
    except OSError:
        if created:
            _remove_if_empty(path)
        raise
    try:
        proof.unlink()
    except OSError:
        pass
    return created


def _remove_if_empty(path: Path) -> None:
    try:
        path.rmdir()  # só remove pasta vazia
    except OSError:
        pass


# Duas gravações ao mesmo tempo dividiam o mesmo `.tmp` (as rotas rodam em
# várias threads) e quase todas falhavam; uma de cada vez basta, os arquivos
# são pequenos.
_ATOMIC_WRITE_LOCK = threading.Lock()
# No NTFS, `os.replace` sobre um arquivo que alguém tem aberto para leitura
# (outra rota lendo o catálogo, o antivírus, o cliente do Drive) dá
# `PermissionError`, coisa que `write_text` não dava. A leitura dura
# milissegundos: tentar de novo por menos de um segundo resolve.
_REPLACE_RETRY_SECONDS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5)


def write_text_atomic(path: Path, text: str) -> None:
    """Grava num temporário ao lado, força para o disco (`fsync`) e troca
    com `os.replace`: uma queda no meio deixa o arquivo antigo inteiro,
    nunca um pela metade nem um vazio. Usado pelos registros JSON da
    máquina (catálogos, sincronização, conjuntos, preferências, diário e
    adiamento da mudança de pasta)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with _ATOMIC_WRITE_LOCK:
        with open(temporary, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        for wait in (*_REPLACE_RETRY_SECONDS, None):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if wait is None:
                    with contextlib.suppress(OSError):
                        temporary.unlink()
                    raise
                time.sleep(wait)


def sqlite_readonly_uri(path) -> str:
    """URI `file:` de só leitura para `sqlite3.connect(..., uri=True)`, com
    o caminho escapado. Montada à mão (`f"file:{caminho}"`), um `#` no nome
    de uma pasta começava um fragmento: o SQLite abria o caminho truncado
    *sem* `mode=ro`, podendo criar um arquivo vazio; `%20` e afins eram
    decodificados. Caminho UNC (`//servidor/pasta`) vira `file:////servidor/...`
    (autoridade vazia), que é o que o SQLite aceita no Windows."""
    from urllib.parse import quote

    posix = Path(os.path.abspath(str(path))).as_posix()
    if not posix.startswith("/"):
        posix = "/" + posix
    return "file://" + quote(posix, safe="/:") + "?mode=ro"

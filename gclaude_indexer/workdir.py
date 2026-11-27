# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Where a project's intermediate files live.

`converted/` (the OCR'd PDFs and each file's extracted text) and `blocks/`
(the slices of large PDFs) used to sit in the output folder. That folder is
normally inside Google Drive, and Drive creates files almost one at a time:
measured on a large collection, ~800 ms to write each small `.txt`, against
0.3 ms on the local disk — the whole conversion of a hundred thousand HTML
files was waiting on it with the CPU idle.

They now go to a per-machine work folder,
`%LOCALAPPDATA%\\GClaudeIndexer\\work\\<key>\\`, where `<key>` is derived
from the output folder's path. Nothing the user takes away from a project
needs them: the pages and the full-text search are in `project.db`, the
indexes are `.md` files in the output folder, and the windows the Claude
Code engine reads stay there too. On another computer a file whose
intermediate is missing is simply converted again when it is needed.

Projects converted before 1.5.8 keep their intermediates in the output
folder; `intermediate_path` still finds them there, so nothing is redone.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from .file_types import PDF_CATEGORY, READ_AS_PDF_CATEGORIES, SIGNED_CATEGORY, TEXT_CATEGORY, category_of_extension
from .paths import folder_spelling_key, machine_local_folder

# Extensões que já existiam antes da 2.0.0: o texto intermediário delas
# continua `<nome>.txt`, para não refazer a conversão de projetos existentes.
# Toda extensão nova ganha `<nome>.<ext>.txt`: `Planilha.xls` e `Planilha.xlsx`,
# `IMG_1.HEIC` e `IMG_1.JPG` não podem disputar o mesmo arquivo.
_ORIGINAL_EXTENSIONS = frozenset({
    "docx", "xlsx", "pptx", "jpg", "jpeg", "png", "tif", "tiff", "bmp", "gif", "webp",
    "txt", "md", "log", "csv", "html", "htm", "xhtml", "xht", "shtml", "mht", "mhtml", "xml", "json",
    "eml", "msg",
})

# Separador das páginas no texto intermediário de um documento com uma página
# por mensagem, anexo ou trecho de mídia (`.mbox`, `.pst`, áudio e vídeo:
# `file_types.CategoryTraits.page_per_message`), gravado por
# `light_formats.extract_text_mbox` e `resumable.PageWriter` e lido por
# `light_formats.iter_pages`. O form feed não aparece em e-mail de verdade; é
# tirado do corpo, por garantia.
PAGE_SEPARATOR = "\n\x0c\n"

WORK_FOLDER_NAME = "work"
ORIGIN_FILE_NAME = "origin.txt"

# Subpastas da pasta de trabalho (e da pasta de saída, nos projetos
# anteriores à 1.5.8). `blocks/` só existe em projetos antigos.
CONVERTED_FOLDER = "converted"
BLOCKS_FOLDER = "blocks"
INTERMEDIATE_FOLDERS: tuple[str, ...] = (CONVERTED_FOLDER, BLOCKS_FOLDER)

# Dentro de `converted/`, a pasta de um documento: `<documento>/anexos`
# (anexos de um `.pst`/`.ost`) e `<documento>/midia` (trechos de áudio).
ATTACHMENTS_FOLDER = "anexos"
MEDIA_FOLDER = "midia"


def work_folder(output_folder: str | Path) -> Path:
    """The local folder holding this project's intermediates.

    Keyed by the output folder's path, not by the project's id in the
    catalog: the id is per machine, the path is what identifies the
    project's files. `origin.txt` inside says which project it belongs to,
    for whoever opens the folder by hand."""
    # A grafia, sem resolver: é o que sempre deu nome a estas pastas.
    normalized = folder_spelling_key(output_folder)
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    name = Path(normalized).name or "project"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "project"
    return work_root() / f"{safe[:40]}-{key}"


WORK_FOLDER_ENV = "GCLAUDE_INDEXER_WORK_FOLDER"


def work_root() -> Path:
    r"""`%LOCALAPPDATA%\GClaudeIndexer\work`, or the folder named by
    `GCLAUDE_INDEXER_WORK_FOLDER` (the test suite points it at a temporary
    folder; it is read from the environment so the conversion's worker
    processes see it too)."""
    override = os.environ.get(WORK_FOLDER_ENV, "").strip()
    if override:
        return Path(override)
    return machine_local_folder() / WORK_FOLDER_NAME


def ensure_work_folder(output_folder: str | Path) -> Path:
    folder = work_folder(output_folder)
    folder.mkdir(parents=True, exist_ok=True)
    origin = folder / ORIGIN_FILE_NAME
    if not origin.exists():
        try:
            origin.write_text(str(output_folder) + "\n", encoding="utf-8")
        except OSError:
            pass  # a label for humans; never worth failing the step over
    return folder


def _named(relative_path: str, suffix: str) -> Path:
    """The intermediate's path inside its subfolder: the document's path
    with its last extension replaced by `suffix`. Every name written and
    read under `converted/` goes through here."""
    return Path(relative_path).with_suffix(suffix)


def local_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where a new intermediate is written: always the local work folder."""
    return work_folder(output_folder) / subfolder / _named(relative_path, suffix)


def legacy_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where versions before 1.5.8 wrote the same intermediate."""
    return Path(output_folder) / subfolder / _named(relative_path, suffix)


def intermediate_path(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """Where to read an intermediate from: the local copy, else the one an
    older version left in the output folder, else the local path (which
    does not exist — the caller's existence check then says so)."""
    local = local_path(output_folder, subfolder, relative_path, suffix)
    if local.exists():
        return local
    legacy = legacy_path(output_folder, subfolder, relative_path, suffix)
    if legacy.exists():
        return legacy
    return local


def destination(output_folder: str | Path, subfolder: str, relative_path: str, suffix: str) -> Path:
    """`local_path` with its parent folder created, ready to be written."""
    path = local_path(output_folder, subfolder, relative_path, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# --- Nomes dentro de `converted/` -------------------------------------------
# Quem grava (`conversion`) e quem lê (`converted_artifact_path`) montam o
# nome pelas mesmas funções. Os nomes são contrato: projetos existentes têm
# esses arquivos, e mudar um sufixo aqui faz a conversão ser refeita.


def _bare(extension: str) -> str:
    return extension.lstrip(".").lower()


def _tagged_pdf_suffix(extension: str) -> str:
    return f".{_bare(extension)}.pdf"


def _tagged_text_suffix(extension: str) -> str:
    return f".{_bare(extension)}.txt"


def pdf_suffix(extension: str) -> str:
    """Sufixo do PDF intermediário: `<nome>.pdf` para um PDF (a cópia com
    OCR), `<nome>.<ext>.pdf` para o que não é PDF e é lido como PDF."""
    extension = _bare(extension)
    if category_of_extension("." + extension) == PDF_CATEGORY:
        return ".pdf"
    return _tagged_pdf_suffix(extension)


def raw_pdf_suffix(extension: str) -> str:
    """`<nome>.<ext>.raw.pdf`: o PDF recém-convertido, antes do OCR (o
    `ocrmypdf` não lê e escreve o mesmo arquivo). Some ao fim da conversão."""
    return f".{_bare(extension)}.raw.pdf"


def text_suffix(extension: str) -> str:
    """Sufixo do `.txt` intermediário de uma extensão."""
    extension = _bare(extension)
    if category_of_extension("." + extension) is not None and extension not in _ORIGINAL_EXTENSIONS:
        return _tagged_text_suffix(extension)
    return ".txt"


def converted_path(output_folder: str | Path, relative_path: str, suffix: str) -> Path:
    """`local_path` em `converted/`."""
    return local_path(output_folder, CONVERTED_FOLDER, relative_path, suffix)


def converted_destination(output_folder: str | Path, relative_path: str, suffix: str) -> Path:
    """`destination` em `converted/`."""
    return destination(output_folder, CONVERTED_FOLDER, relative_path, suffix)


def _converted_intermediate(output_folder: str | Path, relative_path: str, suffix: str) -> Path:
    return intermediate_path(output_folder, CONVERTED_FOLDER, relative_path, suffix)


def attachments_folder(output_folder: str | Path, relative_path: str) -> Path:
    """`converted/<documento>/anexos`: os anexos de um `.pst`/`.ost`."""
    return work_folder(output_folder) / CONVERTED_FOLDER / relative_path / ATTACHMENTS_FOLDER


def media_work_folder(output_folder: str | Path, relative_path: str) -> Path:
    """`converted/<documento>/midia`: os trechos de áudio de uma mídia."""
    return work_folder(output_folder) / CONVERTED_FOLDER / relative_path / MEDIA_FOLDER


# --- A regra do assinado ----------------------------------------------------
# O intermediário de um `.p7m`/`.p7s` é PDF ou texto conforme o conteúdo
# envelopado. Só um dos dois existe: `signed_intermediate`, chamado por quem
# converte, apaga o outro; `converted_artifact_path` acha o que existe e
# `category_to_read` diz como lê-lo.


def signed_intermediate(
    output_folder: str | Path, relative_path: str, extension: str, read_as: str | None,
) -> Path | None:
    """Prepara o intermediário de um assinado lido como `read_as`
    (`PDF_CATEGORY` ou `TEXT_CATEGORY`; `None`: nenhum, o conteúdo não é
    lido) e apaga o da outra forma. Devolve onde gravar: o PDF (quem grava
    cria a pasta) ou o texto (pasta já criada); `None` com `read_as=None`."""
    pdf_path = converted_path(output_folder, relative_path, pdf_suffix(extension))
    text_path = converted_path(output_folder, relative_path, _tagged_text_suffix(extension))
    if read_as == PDF_CATEGORY:
        text_path.unlink(missing_ok=True)
        return pdf_path
    if read_as == TEXT_CATEGORY:
        pdf_path.unlink(missing_ok=True)
        return converted_destination(output_folder, relative_path, _tagged_text_suffix(extension))
    for stale in (pdf_path, text_path):
        stale.unlink(missing_ok=True)
    return None


def category_to_read(category: str | None, intermediate: Path | None) -> str | None:
    """A categoria pela qual o intermediário é lido. Igual à do arquivo,
    salvo o assinado: o que veio dentro decide (PDF, páginas de verdade, ou
    texto), e isso está no nome do intermediário que existe."""
    if category == SIGNED_CATEGORY:
        return PDF_CATEGORY if intermediate.suffix.lower() == ".pdf" else TEXT_CATEGORY
    return category


def converted_artifact_path(
    output_folder: str | Path,
    relative_path: str,
    extension: str,
    needs_ocr: bool,
) -> Path | None:
    """The intermediate `extraction` re-reads this file from, or `None`
    when it reads the original document in the source folder.

    The single place that answers "does this file have an intermediate on
    disk". `conversion._process_file` writes it and
    `extraction._extract_file_pages` reads it, so a third party that needs
    to know whether it is still there — the incremental update, which
    sends a merely-renumbered file back to `'converted'` precisely so
    extraction can re-read the intermediate instead of paying OCR again —
    must agree with both. Agreeing means asking here, not restating the
    rule: `cleanup.py` deletes `converted/` permanently, and a guess that
    says "the artifact is there" when it is not costs the document.

    A PDF that already had a text layer is the one case with no
    intermediate: nothing was written to `converted/` for it and
    extraction opens the original, so there is nothing `cleanup.py` could
    have taken away.
    """
    extension = _bare(extension)
    category = category_of_extension("." + extension)
    if category == PDF_CATEGORY:
        # `file.needs_ocr` (gravado pela conversão: "precisou de OCR") lido
        # como "há cópia com OCR em converted/": um PDF com needs_ocr=1 tem o
        # PDF com OCR gravado — `conversion._ocr_pdf_pages` só devolve
        # needs_ocr verdadeiro depois de escrever o destino.
        has_ocr_copy = needs_ocr
        if not has_ocr_copy:
            return None
        return _converted_intermediate(output_folder, relative_path, pdf_suffix(extension))
    if category in READ_AS_PDF_CATEGORIES:
        # Os outros lidos como PDF: sempre há um PDF intermediário (o
        # original não é PDF).
        return _converted_intermediate(output_folder, relative_path, pdf_suffix(extension))
    if category == SIGNED_CATEGORY:
        as_pdf = _converted_intermediate(output_folder, relative_path, pdf_suffix(extension))
        if as_pdf.exists():
            return as_pdf
        return _converted_intermediate(output_folder, relative_path, _tagged_text_suffix(extension))
    return _converted_intermediate(output_folder, relative_path, text_suffix(extension))


# --- Marca de tabela de um `.docx` (2.1.6) -----------------------------------
# A conversão já abre o `.docx` para tirar o texto; a extração o reabria na
# pasta de origem (no Drive, ~200 ms por arquivo) só para saber se havia
# tabela. A resposta fica ao lado do intermediário, com o tamanho dele: um
# intermediário regravado por outra versão não casa e a extração volta a
# perguntar ao original.

TABLE_FLAG_SUFFIX = ".tables"


def table_flag_path(intermediate: Path) -> Path:
    return intermediate.with_name(intermediate.name + TABLE_FLAG_SUFFIX)


def write_table_flag(intermediate: Path, has_table: bool) -> None:
    table_flag_path(intermediate).write_text(f"{int(has_table)} {intermediate.stat().st_size}", encoding="ascii")


def read_table_flag(intermediate: Path) -> bool | None:
    """`True`/`False` as the conversion recorded, or `None` when there is no
    mark (converted before 2.1.6) or it belongs to another intermediate."""
    try:
        flag, size = table_flag_path(intermediate).read_text(encoding="ascii").split()
        if int(size) != intermediate.stat().st_size or flag not in ("0", "1"):
            return None
    except (OSError, ValueError):
        return None
    return flag == "1"


# --- Reconhecer o que está em `converted/` ----------------------------------


def converted_names(relative_path: str) -> tuple[str, ...]:
    """Os nomes (com `/`, relativos a `converted/`) que este módulo grava,
    ou gravou em versões anteriores, para um documento: `<nome>.pdf`,
    `<nome>.txt`, `<nome>.<ext>.pdf`, `<nome>.<ext>.raw.pdf` e
    `<nome>.<ext>.txt`. Todas as formas, qualquer que seja a categoria de
    hoje: um projeto antigo pode ter convertido a extensão por outra regra."""
    extension = Path(relative_path).suffix
    suffixes = [".pdf", ".txt"]
    if extension:
        suffixes += [_tagged_pdf_suffix(extension), raw_pdf_suffix(extension), _tagged_text_suffix(extension)]
    names: list[str] = []
    for suffix in suffixes:
        try:
            names.append(_named(relative_path, suffix).as_posix())
        except ValueError:
            continue
    # A marca de tabela de cada intermediário de texto (2.1.6).
    names += [name + TABLE_FLAG_SUFFIX for name in names if name.endswith(".txt")]
    return tuple(names)


def document_folders(relative_path: str) -> tuple[str, ...]:
    """As pastas de um documento dentro de `converted/` (com `/`)."""
    base = PurePosixPath(Path(relative_path).as_posix())
    return ((base / ATTACHMENTS_FOLDER).as_posix(), (base / MEDIA_FOLDER).as_posix())


def converted_entry_matcher(documents: Iterable[str]) -> Callable[[str], bool]:
    """Para os documentos de um projeto (caminhos relativos), um predicado
    que diz se um arquivo de `converted/` (caminho relativo a ela) é um dos
    que este módulo grava: um intermediário (`converted_names`) ou qualquer
    coisa dentro das pastas de um documento (`document_folders`). Sem
    distinguir maiúsculas."""
    names: set[str] = set()
    folders: set[str] = set()
    for document in documents:
        document = str(document).replace("\\", "/").lower()
        names.update(converted_names(document))
        folders.update(document_folders(document))

    def matches(relative: str) -> bool:
        path = PurePosixPath(str(relative).replace("\\", "/").lower())
        if path.as_posix() in names:
            return True
        return any(parent.as_posix() in folders for parent in path.parents)

    return matches

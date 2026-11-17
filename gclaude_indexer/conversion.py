# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Conversion by type and OCR (section 5, steps 2 and 3). PDFs are no longer
sliced (2.0.0): extraction reads the pages straight from the PDF.

Every file with `status = "discovered"` is processed once. The original is
never read for writing nor altered — all output (OCR'd PDF,
extracted text) goes to `output_folder`. A corrupted file, or one that fails
at any step, gets `status = "failed"`, has the error recorded in `file.error`
and in an event, and processing moves on to the next file.
"""

from __future__ import annotations

import email
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from email import policy
from pathlib import Path

import fitz  # PyMuPDF

from . import language_detect, legacy_office, light_formats, media, no_window, ocr_detection, outlook, tools, workdir
from .config import ProjectConfig
from .db import BatchWriter
from .events import record_event
from .i18n import DEFAULT_LANGUAGE, translate
from .worker_pool import (
    ERROR, OK, TIMED_OUT, DaemonThreadExecutor, PoolStalledError, ResilientPool, StepStalledError,
    deadline_for_size,
)
from .parallelism import _physical_cores, io_workers_for, workers_for
from .file_types import (
    ALWAYS_BLOCKED_EXTENSIONS, ARCHIVE_EXTENSIONS, EXTENSION_CATEGORIES, GOOGLE_DOC_EXTENSIONS, REASON_BINARY,
    REASON_COMPONENT_UNAVAILABLE, REASON_SIGNATURE_DETACHED, REASON_UNSUPPORTED, SECRET_EXTENSIONS,
    HEAD_BYTES, category_of_extension, file_extension, has_private_key_marker, index_decision, looks_binary,
)
from .html_text import STRUCK_MARK, html_to_text, looks_like_html, mark_struck
from .text_decoding import decode_bytes, decode_markup

MIN_AVG_CHARS_PER_PAGE = 100
# How much of an unknown-extension file is checked for a NUL byte.
_BINARY_SNIFF_BYTES = 8192
# Categories whose conversion may run OCR — the CPU-bound queue.
# Os paginados e os assinados (`.p7m` com PDF dentro) passam pelo mesmo OCR
# do PDF; os formatos antigos (LibreOffice) também, depois de virarem PDF.
OCR_CATEGORIES = frozenset({"pdf", "imagens", "paginados", "assinados", "legados"})
LEGACY_CATEGORY = "legados"
# Arquivos do Outlook: fila própria, lida em fluxo neste processo (`_convert_outlook`).
OUTLOOK_CATEGORY = "outlook"
# Áudio e vídeo (`midia`): fila própria, transcrita em fluxo neste processo (`_convert_media`).
MEDIA_CATEGORY = "midia"
# Extensões que já existiam antes da 2.0.0: o texto intermediário delas
# continua `<nome>.txt`, para não refazer a conversão de projetos existentes.
# Toda extensão nova ganha `<nome>.<ext>.txt`: `Planilha.xls` e `Planilha.xlsx`,
# `IMG_1.HEIC` e `IMG_1.JPG` não podem disputar o mesmo arquivo.
_ORIGINAL_EXTENSIONS = frozenset({
    "docx", "xlsx", "pptx", "jpg", "jpeg", "png", "tif", "tiff", "bmp", "gif", "webp",
    "txt", "md", "log", "csv", "html", "htm", "xhtml", "xht", "shtml", "mht", "mhtml", "xml", "json",
    "eml", "msg",
})
ERROR_MESSAGE_CHAR_LIMIT = 500


@dataclass
class ConversionResult:
    converted: int = 0
    ocr_applied: int = 0
    failed: int = 0


class ConversionError(Exception):
    """Failure converting a file. The message must not contain document content."""


class OcrError(ConversionError):
    """`ocrmypdf` itself failed. Kept apart from every other
    conversion failure because it is the one worth trying again: a file
    that failed this way gets `file.ocr_failed = 1` and goes back to the
    queue at the start of the next conversion (`requeue_ocr_failures`),
    while a corrupt or password-protected file stays failed."""


def _destination_path(output_dir: Path, subfolder: str, relative_path: str, new_extension: str) -> Path:
    # In the per-machine work folder, never in the (Drive-synced)
    # output folder — see `workdir.py`.
    return workdir.destination(output_dir, subfolder, relative_path, new_extension)


def converted_artifact_path(
    output_folder: str | Path,
    relative_path: str,
    extension: str,
    needs_ocr: bool,
) -> Path | None:
    """The intermediate `extraction` re-reads this file from, or `None`
    when it reads the original document in the source folder.

    The single place that answers "does this file have an intermediate on
    disk". `_process_file` below writes it and
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
    extension = extension.lstrip(".").lower()
    category = category_of_extension("." + extension)
    if category == "pdf":
        if not needs_ocr:
            return None
        return workdir.intermediate_path(output_folder, "converted", relative_path, ".pdf")
    if category in ("paginados", "legados"):
        # Sempre há um PDF intermediário (o original não é PDF).
        return workdir.intermediate_path(output_folder, "converted", relative_path, f".{extension}.pdf")
    if category == "assinados":
        # Só o conteúdo envelopado diz qual: PDF dentro, PDF aqui; qualquer
        # outro tipo vira texto. Quem converte apaga o outro.
        as_pdf = workdir.intermediate_path(output_folder, "converted", relative_path, f".{extension}.pdf")
        if as_pdf.exists():
            return as_pdf
        return workdir.intermediate_path(output_folder, "converted", relative_path, f".{extension}.txt")
    return workdir.intermediate_path(output_folder, "converted", relative_path, text_suffix(extension))


def text_suffix(extension: str) -> str:
    """Sufixo do `.txt` intermediário de uma extensão."""
    extension = extension.lstrip(".").lower()
    if category_of_extension("." + extension) is not None and extension not in _ORIGINAL_EXTENSIONS:
        return f".{extension}.txt"
    return ".txt"


def _pdf_pages_needing_ocr(path: Path) -> tuple[list[int], int]:
    """Returns `(pages, page_count)`: the 1-based pages with fewer than 100
    characters of text, which need OCR (section 5, step 2).

    Decided page by page, not by the file's average: a native-text PDF
    with a few scanned pages in the middle (a signed minute, an annex) has
    an average well above the threshold, and those pages used to reach the
    index blank.

    A page with little text and nothing drawn on it — no image, no vector
    drawing (text converted to outlines is a drawing) — has nothing for OCR
    to find: the blank verso or the "Chapter 2" divider of a book. It does
    not count, or a whole native book would go through OCR for it."""
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise ConversionError(f"PDF ilegível ou corrompido: {exc}") from exc

    try:
        page_count = document.page_count
        if page_count == 0:
            raise ConversionError("PDF sem páginas")

        pages = [
            number for number, page in enumerate(document, start=1)
            if len(page.get_text().strip()) < MIN_AVG_CHARS_PER_PAGE
            and (page.get_images() or page.get_drawings())
        ]
        return pages, page_count
    finally:
        document.close()


def _ocr_environment() -> dict:
    """Environment for the OCR subprocess, with the console-window hook on
    its `PYTHONPATH`.

    Two entries, both needed and for different reasons:

    * the project root, so `python -m gclaude_indexer._ocr_runner` resolves
      at all — the worker process that builds this command may have been
      `spawn`ed with a different working directory;
    * `_nowindow_site`, whose `sitecustomize.py` the `site` module imports
      into **every** interpreter started with this environment. That is
      what reaches ocrmypdf's own `--jobs` pool workers, which are the
      direct parents of `tesseract.exe` and would otherwise each flash a
      console window (see `no_window.py`).
    """
    package_folder = Path(__file__).resolve().parent
    entries = [str(package_folder.parent), str(package_folder / "_nowindow_site")]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        entries.append(existing)
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(entries),
        "PYTHONDONTWRITEBYTECODE": "1",
        # ocrmypdf finds `tesseract` and `gswin64c` through `PATH` and
        # takes no configuration for either, so the locations the installer
        # recorded have to reach it this way (see `tools.py`).
        "PATH": tools.path_with_tools(),
    }


def _run_ocrmypdf(
    source: Path, destination: Path, ocr_language: str, jobs: int = 1, pages: list[int] | None = None,
    rotate: bool = False,
) -> None:
    if destination.exists():
        destination.unlink()

    # With `pages`, only those are OCR'd — and forced: `--skip-text` would
    # skip a scanned page carrying a stamp or a "fl. 2" as text. The other
    # pages pass through untouched, native text included.
    if pages:
        page_options = ["--force-ocr", "--pages", ",".join(str(number) for number in pages)]
    else:
        page_options = ["--skip-text"]

    command = [
        sys.executable,
        # `-B` as well as `PYTHONDONTWRITEBYTECODE` in the environment: the
        # variable is the one that reaches ocrmypdf's own pool workers, but
        # it can be lost if a caller rebuilds the environment, and the
        # project folder is synced by Google Drive and must never receive a
        # `__pycache__` (section 11.1). The flag cannot be lost.
        "-B",
        "-m",
        # Not `ocrmypdf` directly: `_ocr_runner` is the same command line
        # with console windows suppressed first — see its docstring and
        # `no_window.py`. Ghostscript and Tesseract are started by this
        # process, and a windowless parent is exactly what makes each of
        # them pop a black window on the desktop.
        "gclaude_indexer._ocr_runner",
        *page_options,
        "--language",
        ocr_language,
        # 2.0.0: página de lado ou de cabeça para baixo é endireitada pelo OSD
        # do Tesseract antes do OCR. Só com o `osd.traineddata` presente: sem
        # ele o `ocrmypdf` para com erro em vez de pular a rotação.
        *(["--rotate-pages"] if rotate else []),
        "--deskew",
        # The OCR'd copy lives in the output folder and is only read for its
        # text; the signed original is never touched. Without this a signed
        # minute or ordinance is refused outright.
        "--invalidate-digital-signatures",
        "--jobs",
        str(max(1, jobs)),
        # A plain PDF, not PDF/A. The copy is only read for its text,
        # and the PDF/A conversion (Ghostscript) refuses a PDF with an
        # unusual color space (`ColorConversionNeededError`) — which threw
        # away the OCR of every page of the file. Skipping it is also faster.
        "--output-type",
        "pdf",
        # Section 5 also asks for "--clean", but that option depends on the
        # `unpaper` binary, which has no official Windows distribution and
        # is not on the installable dependency list in section 10.3. Omitted
        # here so OCR works on this platform; revisit if `unpaper` becomes
        # installable on Windows.
        str(source),
        str(destination),
    ]
    result = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        env=_ocr_environment(),
        startupinfo=no_window.hidden_startupinfo(),
        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
    )

    if result.returncode != 0:
        raise OcrError(
            f"ocrmypdf falhou (código {result.returncode}): "
            f"{result.stderr.strip()[-ERROR_MESSAGE_CHAR_LIMIT:]}"
        )


def _docx_paragraph_text(paragraph) -> str:
    """The paragraph's text with struck runs marked `~~`. Goes through
    `iter_inner_content()` because `paragraph.runs` skips the runs inside
    hyperlinks — a cross-reference to another law would lose its text."""
    segments = []
    for item in paragraph.iter_inner_content():
        for run in getattr(item, "runs", [item]):
            struck = bool(run.font.strike or run.font.double_strike)
            segments.append((run.text, struck))
    return mark_struck(segments)


def _extract_text_docx(path: Path) -> str:
    document = light_formats.open_docx(path)
    parts = [text for text in map(_docx_paragraph_text, document.paragraphs) if text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append("\t".join(
                "\n".join(_docx_paragraph_text(p) for p in cell.paragraphs) for cell in row.cells
            ))
    return "\n".join(parts)


def _extract_text_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    text_rows = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            cells = []
            for cell in row:
                value = getattr(cell, "value", None)
                text = "" if value is None else str(value)
                font = getattr(cell, "font", None) if text.strip() else None
                if font is not None and font.strike:
                    text = f"{STRUCK_MARK}{text.strip()}{STRUCK_MARK}"
                cells.append(text)
            text_rows.append("\t".join(cells))
    workbook.close()
    return "\n".join(text_rows)


def _pptx_run_struck(run) -> bool:
    # python-pptx has no `font.strike`; the attribute lives on `<a:rPr>`.
    properties = run._r.rPr
    return properties is not None and properties.get("strike") in ("sngStrike", "dblStrike")


def _extract_text_pptx(path: Path) -> str:
    presentation = light_formats.open_pptx(path)
    parts = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = mark_struck([(run.text, _pptx_run_struck(run)) for run in paragraph.runs])
                    if text:
                        parts.append(text)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            parts.append(slide.notes_slide.notes_text_frame.text)
    return "\n".join(parts)


# Mora em `light_formats` (a caixa `.mbox` lê mensagens do mesmo jeito).
_message_part_text = light_formats.message_part_text


def _extract_text_eml(path: Path) -> str:
    with open(path, "rb") as file:
        message = email.message_from_binary_file(file, policy=policy.default)

    parts = [f"From: {message.get('From', '')}", f"Subject: {message.get('Subject', '')}"]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        parts.append(_message_part_text(body))
    return "\n\n".join(parts)


def _extract_text_msg(path: Path) -> str:
    import extract_msg

    message = extract_msg.Message(str(path))
    try:
        parts = [f"From: {message.sender or ''}", f"Subject: {message.subject or ''}"]
        if message.body:
            parts.append(message.body)
        elif message.htmlBody:
            text, _ = decode_markup(message.htmlBody)
            parts.append(html_to_text(text))
        return "\n\n".join(parts)
    finally:
        message.close()


_HTML_EXTENSIONS = {"html", "htm", "xhtml", "xht", "shtml"}
_MHTML_EXTENSIONS = {"mht", "mhtml"}


def _extract_text_mhtml(data: bytes) -> str:
    """A page saved by a browser as a single file: MIME, like an e-mail.
    The first HTML part is the page; images and styles are ignored."""
    message = email.message_from_bytes(data, policy=policy.default)
    plain = None
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_type() == "text/html":
            return _message_part_text(part)
        if plain is None and part.get_content_type() == "text/plain":
            plain = part
    if plain is not None:
        return _message_part_text(plain)
    text, _ = decode_markup(data)
    return html_to_text(text)


def _extract_text_web(path: Path, extension: str) -> str:
    data = path.read_bytes()
    if extension in _MHTML_EXTENSIONS:
        return _extract_text_mhtml(data)
    if extension == "json":
        return decode_bytes(data)[0]
    text, _ = decode_markup(data)
    if extension in _HTML_EXTENSIONS or looks_like_html(text):
        return html_to_text(text)
    return text


def _register_heif() -> None:
    """Ensina o Pillow a abrir `.heic`/`.heif` (`pillow-heif`). Idempotente.
    Sem a biblioteca, o arquivo falha ao abrir, como qualquer imagem corrompida."""
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()


# Teto do `tesseract` numa imagem inteira. Sem ele, uma imagem que trava o
# Tesseract travava a conversão: as imagens comuns e as de dentro de um `.p7m`
# rodam num processo do conjunto, mas os anexos de imagem de um PST rodam
# neste processo, sem nenhum outro prazo por cima. Estourar levanta
# `RuntimeError`: falha daquele arquivo (ou só daquele anexo), não da conversão.
IMAGE_OCR_TIMEOUT_S = 300


def _extract_text_image(path: Path, ocr_language: str, rotate: int = 0) -> str:
    """O OCR de uma imagem. `rotate`: graus no sentido horário que o OSD
    mandou girar (o `pytesseract` não endireita sozinho, como o `ocrmypdf`)."""
    from PIL import Image
    import pytesseract

    _register_heif()
    with Image.open(path) as image:
        image.load()
        if rotate:
            if image.mode not in ("L", "RGB"):
                image = image.convert("RGB")
            image = image.rotate(-rotate, expand=True, fillcolor="white")
        return pytesseract.image_to_string(image, lang=ocr_language, timeout=IMAGE_OCR_TIMEOUT_S)


_TEXT_CATEGORIES = frozenset({
    "docx", "xlsx", "pptx", "text", "web_dados", "email", "opendocument", "rtf", "mbox", "cad", "legendas",
})


def _extract_light_text(category: str, extension: str, source_path: Path) -> str:
    """O texto de um arquivo que vira uma página (ou, na caixa `.mbox`, uma
    página por mensagem, separadas por `MBOX_PAGE_SEPARATOR`)."""
    if category == "docx":
        return _extract_text_docx(source_path)
    if category == "xlsx":
        if extension == "xls":
            return light_formats.extract_text_xls(source_path)
        return _extract_text_xlsx(source_path)
    if category == "pptx":
        return _extract_text_pptx(source_path)
    if category == "web_dados":
        return _extract_text_web(source_path, extension)
    if category == "text":
        return decode_bytes(source_path.read_bytes())[0]
    if category == "opendocument":
        return light_formats.extract_text_opendocument(source_path)
    if category == "rtf":
        return light_formats.extract_text_rtf(source_path)
    if category == "mbox":
        return light_formats.extract_text_mbox(source_path)
    if category == "cad":
        return light_formats.extract_text_dxf(source_path)
    if category == "legendas":
        return light_formats.extract_text_subtitles(source_path)
    if extension == "msg":
        return _extract_text_msg(source_path)
    return _extract_text_eml(source_path)


# 2.0.0: página com imagem cujo OCR devolveu menos que isto é lida mais uma
# vez, com o modelo da escrita que o OSD achou nela (ver `_reread_model`).
REREAD_MIN_CHARS = 100
# Quantas páginas de um mesmo arquivo passam pelo OSD para isso: o OSD e o
# OCR de cada uma custam segundos, e um livro escaneado ilegível inteiro não
# merece centenas deles.
REREAD_MAX_PAGES = 30


def _reread_model(image, used: list[str], usable) -> tuple[str | None, int, bool]:
    """`(modelo, graus a girar, falta o modelo)` para ler de novo uma página
    cujo OCR deu pouco texto: o modelo da escrita que o OSD vê nela
    (`ocr_detection.osd_image`, o mesmo da detecção de idioma). `None` quando
    o OSD não diz a escrita ou o modelo dela já foi o usado (ler de novo com
    o mesmo modelo daria o mesmo texto). O que falta nesta máquina não é
    baixado aqui: quem chama marca o arquivo e a próxima conversão baixa."""
    found = ocr_detection.osd_image(image)
    if found is None or found[0] is None:
        return None, 0, False
    script, degrees = found
    model = language_detect.script_model(script)
    if not model or model in used:
        return None, degrees, False
    return model, degrees, usable is not None and model not in set(usable)


def _ocr_pages_text(document, pages: list[int]) -> dict[int, int]:
    return {number: len(document[number - 1].get_text().strip()) for number in pages}


def _reread_weak_pdf_pages(
    name: str, source_pdf: Path, destination: Path, ocr_pages: list[int], used: list[str], usable,
    jobs: int, rotate: bool, events: list, notes: dict,
) -> tuple[list[str], bool]:
    """Lê de novo, uma vez, as páginas escaneadas que o OCR deixou com menos
    de `REREAD_MIN_CHARS` caracteres, cada uma com o modelo da escrita dela.
    Devolve `(modelos que faltam aqui, se algo foi lido)`. O `ocrmypdf` roda
    sobre a cópia já lida, só nessas páginas (`--force-ocr --pages`: as outras
    passam intactas), uma vez por modelo, como o plano com grupos de
    páginas."""
    try:
        document = fitz.open(destination)
        try:
            weak = [n for n, size in _ocr_pages_text(document, ocr_pages).items() if size < REREAD_MIN_CHARS]
        finally:
            document.close()
    except Exception:
        return [], False
    if not weak:
        return [], False

    groups: dict[str, list[int]] = {}
    missing: list[str] = []
    source = fitz.open(source_pdf)
    try:
        for number in weak[:REREAD_MAX_PAGES]:
            image = ocr_detection._prepared(ocr_detection._render(source, number))
            model, _degrees, absent = _reread_model(image, used, usable)
            if model is None:
                continue
            if absent:
                if model not in missing:
                    missing.append(model)
                continue
            groups.setdefault(model, []).append(number)
    finally:
        source.close()

    done_models: list[str] = []
    current = destination
    temporaries: list[Path] = []
    try:
        for index, (model, pages) in enumerate(groups.items()):
            target = destination.with_name(f"{destination.name}.releitura{index}.pdf")
            temporaries.append(target)
            try:
                _run_ocrmypdf(current, target, model, jobs=jobs, pages=pages, rotate=rotate)
            except OcrError as exc:
                events.append((
                    "conversion", "warning", "log.conversion.ocr_pages_failed",
                    {"name": name, "pages": len(pages), "total": len(ocr_pages),
                     "error": str(exc)[:ERROR_MESSAGE_CHAR_LIMIT]},
                ))
                continue
            # O OSD de uma página quase vazia não é confiável: o texto novo só
            # entra nas páginas em que ficou MAIOR que o que já havia; nas
            # outras volta a página de antes.
            merged = destination.with_name(f"{destination.name}.mescla{index}.pdf")
            temporaries.append(merged)
            try:
                kept = _keep_longer_pages(current, target, pages, merged)
            except Exception:
                kept = 0
            if not kept:
                continue
            current = merged
            done_models.append(f"{model} ({kept})")
        if current != destination:
            os.replace(current, destination)
            temporaries.remove(current)
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
    if done_models:
        events.append((
            "conversion", "info", "log.conversion.ocr_reread",
            {"name": name, "models": ", ".join(done_models)},
        ))
    return missing, bool(done_models)


def _keep_longer_pages(old: Path, new: Path, pages: list[int], output: Path) -> int:
    """Grava em `output` o PDF `new`, trocando de volta pela página de `old`
    cada uma de `pages` cujo texto novo não ficou mais longo. Devolve quantas
    páginas ficaram com o texto novo."""
    document_old = fitz.open(old)
    document_new = fitz.open(new)
    try:
        kept = 0
        for number in pages:
            if len(document_new[number - 1].get_text().strip()) > len(document_old[number - 1].get_text().strip()):
                kept += 1
                continue
            document_new.delete_page(number - 1)
            document_new.insert_pdf(document_old, from_page=number - 1, to_page=number - 1, start_at=number - 1)
        if kept:
            document_new.save(output)
        return kept
    finally:
        document_new.close()
        document_old.close()


def _plan_with_models(plan: str, extra: list[str]) -> str | None:
    """O plano de idiomas do arquivo com os modelos que faltam, para a
    próxima conversão os baixar e ler com eles. Só um plano de um grupo só
    (`"por"`, `"deu+eng"`); com grupos de páginas, `None`: não se mexe."""
    groups = ocr_detection.parse_plan(plan)
    if len(groups) != 1 or groups[0][0] is not None:
        return None
    models = list(dict.fromkeys([*groups[0][1], *extra]))[: language_detect.MAX_LANGUAGES]
    return "+".join(models)


def _reread_image(
    path: Path, text: str, languages: str, rotate: int, usable, events: list, name: str
) -> tuple[str, list[str]]:
    """`(texto, modelos que faltam)`: a imagem de OCR curto lida de novo
    com o modelo da escrita; fica o texto mais longo."""
    from PIL import Image

    try:
        _register_heif()
        with Image.open(path) as image:
            image.load()
            prepared = ocr_detection._prepared(image)
    except Exception:
        return text, []
    try:
        model, degrees, absent = _reread_model(prepared, languages.split("+"), usable)
    except Exception:
        return text, []
    if model is None:
        return text, []
    if absent:
        return text, [model]
    try:
        again = _extract_text_image(path, model, rotate=rotate or degrees)
    except Exception:
        return text, []
    events.append(("conversion", "info", "log.conversion.ocr_reread", {"name": name, "models": model}))
    return (again if len(again.strip()) > len(text.strip()) else text), []


def _row_plan(config: ProjectConfig, row: dict | None) -> tuple[str, bool]:
    """`(plano de idiomas, se falta idioma)` que o processo principal mandou
    para este arquivo (`convert`); sem plano (chamada direta, projeto sem a
    passada de detecção), o idioma do projeto, como antes da 2.0.0."""
    if row is not None and "ocr_plan" in row:
        return row["ocr_plan"] or "", bool(row.get("ocr_short"))
    return config.ocr_language or "", False


def _detect_in_worker(native: str, plan: str, short: bool, usable, notes: dict) -> tuple[str, bool]:
    """Os formatos que só viram PDF na conversão (paginados, assinados,
    antigos) não passam pela detecção anterior ao OCR: o texto nativo do PDF
    convertido diz aqui o idioma, e as páginas escaneadas já são lidas nele
    (uma passada só). O `py3langid` carrega neste processo só por este
    caminho, e só com texto nativo bastante; PDFs e imagens têm o idioma
    decidido no processo principal, antes da fila. Sem idioma pelo texto, a
    escrita: CJK por ela mesma; outra escrita que o plano não lê, o modelo
    dela. O que não está nesta máquina não é baixado aqui: o arquivo fica
    marcado e a próxima conversão baixa o que ele pediu (`file.ocr_lang`)."""
    if not ocr_detection.native_is_enough(native):
        return plan, short
    sample = native[:_GROUP_SAMPLE_CHARS]
    notes["language_sample"] = sample
    found = language_detect.detect_languages(sample)
    if found:
        # Da mesma amostra que `_resolve_language` lê: simplificado e
        # tradicional saem iguais nos dois processos.
        wanted = "+".join(language_detect.tesseract_languages(found, sample))
        notes["language"] = ",".join(found)
    else:
        script = language_detect.dominant_script(sample)
        if script is None:
            return plan, short
        if script in language_detect.CJK_SCRIPTS:
            code = language_detect.east_asian_language(sample)
            wanted = "+".join(language_detect.tesseract_languages([code], sample)) if code else ""
        elif any(language_detect.model_script(model) == script for model in ocr_detection.plan_models(plan)):
            return plan, short
        else:
            wanted = language_detect.script_model(script) or ""
    if not wanted:
        return plan, short
    notes["ocr_lang"] = wanted
    if usable is None:  # sem saber o que o Tesseract tem: como antes, tenta
        return wanted, False
    restricted, missing = ocr_detection.restrict_plan(wanted, set(usable))
    if not missing:
        return restricted, False
    # Falta o modelo do idioma: o da escrita, se estiver aqui, lê por ora; o
    # arquivo fica marcado e volta quando o modelo chegar.
    scripts = {language_detect.model_script(model) for model in ocr_detection.plan_models(wanted)}
    stand_ins = [
        model for model in (language_detect.script_model(script) for script in scripts if script)
        if model and model in set(usable)
    ]
    if restricted:
        return "+".join(dict.fromkeys(ocr_detection.plan_models(restricted) + stand_ins)), True
    if stand_ins:
        return "+".join(stand_ins), True
    return plan, True


def _ocr_pdf_pages(
    config: ProjectConfig, name: str, source_pdf: Path, destination: Path, ocrmypdf_jobs: int, events: list,
    row: dict | None = None, notes: dict | None = None,
) -> tuple[bool, bool, bool, int]:
    """Decide e faz o OCR das páginas sem texto de um PDF. Devolve
    `(needs_ocr, ocr_failed, ocr_applied, page_count)`. Com OCR feito, o
    resultado está em `destination`; sem ele, nada é escrito lá.

    2.0.0: os idiomas vêm do plano do arquivo (`row["ocr_plan"]`, ver
    `ocr_detection`). Um plano com grupos de páginas roda o `ocrmypdf` uma
    vez por grupo, cada vez sobre a saída da anterior (ele não lê e escreve
    o mesmo arquivo); as páginas de fora de um grupo passam intactas."""
    notes = notes if notes is not None else {}
    ocr_failed = False
    ocr_applied = False
    native = ""
    detect = row is not None and bool(row.get("ocr_detect"))
    if row is not None and row.get("ocr_pages") is not None and row.get("page_count"):
        ocr_pages, page_count = list(row["ocr_pages"]), int(row["page_count"])
    elif detect:
        # Uma leitura só: as páginas sem texto e a amostra do texto nativo.
        try:
            ocr_pages, page_count, native = ocr_detection.scan_pdf(source_pdf, MIN_AVG_CHARS_PER_PAGE)
        except Exception as exc:
            raise ConversionError(f"PDF ilegível ou corrompido: {exc}") from exc
        if page_count == 0:
            raise ConversionError("PDF sem páginas")
    else:
        ocr_pages, page_count = _pdf_pages_needing_ocr(source_pdf)
    needs_ocr = bool(ocr_pages)
    plan, short = _row_plan(config, row)
    if needs_ocr and detect:
        plan, short = _detect_in_worker(native, plan, short, row.get("ocr_usable"), notes)
    rotate = bool(row is not None and row.get("ocr_rotate"))

    wanted_pages = set(ocr_pages)
    runs: list[tuple[list[int], str]] = []
    left_out = False
    for pages, models in ocr_detection.parse_plan(plan):
        selected = ocr_pages if pages is None else [number for number in ocr_pages if number in set(pages)]
        if not selected:
            continue
        if not models:
            left_out = True  # nenhum idioma deste grupo está aqui: fica para depois
            continue
        runs.append((selected, "+".join(models)))
        wanted_pages -= set(selected)

    if needs_ocr and not runs:
        # Task 7: no OCR language could be had (no network, download
        # refused) — `convert` already warned which one. The native
        # text is read as it is and `ocr_failed` brings the file back
        # once the language is there; the file is never failed for it.
        needs_ocr = False
        ocr_failed = True
    elif needs_ocr:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = len(ocr_pages) < page_count
        current = source_pdf
        done = 0
        temporaries: list[Path] = []
        try:
            for index, (pages, languages) in enumerate(runs):
                last = index == len(runs) - 1
                target = destination if last else destination.with_name(f"{destination.name}.parte{index}.pdf")
                if not last:
                    temporaries.append(target)
                try:
                    _run_ocrmypdf(current, target, languages, jobs=ocrmypdf_jobs, pages=pages, rotate=rotate)
                except OcrError as exc:
                    # A file with native text used to skip OCR altogether; one
                    # failed scanned page must not cost the rest of it. Read the
                    # original (or what the groups before this one already
                    # read), as before, and say which pages stayed blank.
                    # `ocr_failed` brings it back on the next conversion.
                    if not partial and done == 0:
                        raise
                    if done:
                        os.replace(current, destination)
                    needs_ocr = done > 0
                    ocr_failed = True
                    events.append((
                        "conversion", "warning", "log.conversion.ocr_pages_failed",
                        {"name": name, "pages": sum(len(group) for group, _ in runs[index:]),
                         "total": page_count, "error": str(exc)[:ERROR_MESSAGE_CHAR_LIMIT]},
                    ))
                    break
                current = target
                done += 1
        finally:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)
        if done:
            ocr_applied = True
            notes["ocr_used"] = "+".join(dict.fromkeys(
                model for _pages, languages in runs[:done] for model in languages.split("+")
            ))
            used = ", ".join(languages for _pages, languages in runs[:done])
            if partial:
                events.append((
                    "conversion", "info", "log.conversion.ocr_applied_pages",
                    {"name": name, "pages": sum(len(group) for group, _ in runs[:done]), "total": page_count,
                     "ocr_language": used},
                ))
            else:
                events.append((
                    "conversion", "info", "log.conversion.ocr_applied",
                    {"name": name, "ocr_language": used},
                ))
    if ocr_applied and not ocr_failed and not left_out and not wanted_pages and not short:
        # 2.0.0: página com imagem e menos de 100 caracteres depois do OCR:
        # uma leitura a mais, com o modelo da escrita. O que falta aqui é
        # pedido ao plano do arquivo e o arquivo volta à fila (`ocr_failed`),
        # a mesma via de um idioma que ainda não chegou.
        used = [model for _pages, languages in runs for model in languages.split("+")]
        try:
            absent, _read = _reread_weak_pdf_pages(
                name, source_pdf, destination, ocr_pages, used,
                row.get("ocr_usable") if row is not None else None, ocrmypdf_jobs, rotate, events, notes,
            )
        except Exception:
            # A releitura é um extra: nunca derruba a conversão que já deu certo.
            absent = []
        if absent:
            wanted_plan = _plan_with_models(plan, absent)
            if wanted_plan:
                notes["ocr_lang"] = wanted_plan
                ocr_failed = True
    if left_out or wanted_pages or short:
        # Parte das páginas foi lida sem o idioma certo (ou ficou sem OCR):
        # bom o bastante por ora, refeito quando o idioma chegar.
        ocr_failed = ocr_failed or bool(ocr_pages)
    return needs_ocr, ocr_failed, ocr_applied, page_count


def _store_pdf_intermediate(
    config: ProjectConfig, name: str, pdf_bytes: bytes, output_dir: Path, relative_path: str,
    extension: str, ocrmypdf_jobs: int, events: list, row: dict | None = None, notes: dict | None = None,
) -> tuple[bool, bool, bool, int]:
    """Grava o PDF de um formato que não é PDF em `converted/<nome>.<ext>.pdf`
    (com o OCR das páginas sem texto) e devolve o mesmo que `_ocr_pdf_pages`.

    Passa por um arquivo `.raw.pdf` ao lado, porque o `ocrmypdf` não lê e
    escreve o mesmo arquivo; sem OCR, o `.raw.pdf` vira o destino."""
    extension = extension.lstrip(".").lower()
    destination = workdir.local_path(output_dir, "converted", relative_path, f".{extension}.pdf")
    raw = workdir.destination(output_dir, "converted", relative_path, f".{extension}.raw.pdf")
    raw.write_bytes(pdf_bytes)
    try:
        # As páginas que a passada de detecção contou são as do original, não
        # deste PDF convertido: aqui elas são contadas de novo.
        pdf_row = None if row is None else {**row, "ocr_pages": None, "page_count": None}
        result = _ocr_pdf_pages(config, name, raw, destination, ocrmypdf_jobs, events, pdf_row, notes)
        if not result[2]:  # sem OCR aplicado, o PDF convertido é o intermediário
            os.replace(raw, destination)
        return result
    finally:
        raw.unlink(missing_ok=True)


def _detached_sibling(source_path: Path, relative_path: str) -> str | None:
    """O arquivo que uma assinatura destacada assina: `X.pdf.p7s` assina
    `X.pdf`; `X.p7s` assina o único outro arquivo de nome `X.*` na pasta.
    Devolve o caminho relativo dele (com `/`), ou `None`."""
    try:
        entries = [entry for entry in source_path.parent.iterdir() if entry.is_file()]
    except OSError:
        return None
    stem = source_path.stem.lower()
    chosen = [entry for entry in entries if entry.name.lower() == stem and entry != source_path]
    if not chosen:
        chosen = [
            entry for entry in entries
            if entry != source_path and entry.suffix.lower() not in (".p7s", ".p7m")
            and entry.stem.lower() == stem
        ]
        if len(chosen) != 1:
            return None
    folder = relative_path.rpartition("/")[0]
    return f"{folder}/{chosen[0].name}" if folder else chosen[0].name


def _signed_content_text(kind: str, content: bytes, config: ProjectConfig) -> tuple[str, bool]:
    """Texto do conteúdo envelopado de um tipo que não é PDF, e se o OCR
    ficou pendente (imagem sem idioma de OCR)."""
    import tempfile

    if kind == "text":
        text, _ = decode_markup(content)
        return (html_to_text(text) if looks_like_html(text) else decode_bytes(content)[0]), False
    suffixes = {
        "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx", "odf": ".odt", "rtf": ".rtf", "xls": ".xls",
        "image": ".img",
    }
    # Pasta temporária do sistema: o conteúdo é de terceiros e nunca fica no
    # projeto (que o Google Drive sincroniza).
    with tempfile.TemporaryDirectory(prefix="gclaude-p7m-") as folder:
        inner = Path(folder) / ("conteudo" + suffixes[kind])
        inner.write_bytes(content)
        if kind == "docx":
            return _extract_text_docx(inner), False
        if kind == "xlsx":
            return _extract_text_xlsx(inner), False
        if kind == "pptx":
            return _extract_text_pptx(inner), False
        if kind == "odf":
            return light_formats.extract_text_opendocument(inner), False
        if kind == "rtf":
            return light_formats.extract_text_rtf(inner), False
        if kind == "xls":
            return light_formats.extract_text_xls(inner), False
        if config.ocr_language:
            return _extract_text_image(inner, config.ocr_language), False
        return "", True


def _convert_signed(
    config: ProjectConfig, row: dict, source_path: Path, output_dir: Path, ocrmypdf_jobs: int, events: list,
    notes: dict | None = None,
) -> dict:
    """`.p7m`/`.p7s` (ICP-Brasil): o conteúdo envelopado é indexado pelo tipo
    real (detectado pelos bytes) e quem assinou vai para `file_signature`.
    Uma assinatura destacada não tem conteúdo: ela é registrada no arquivo
    irmão e o `.p7s` em si sai do índice."""
    relative_path = row["relative_path"]
    extension = row["extension"].lower()
    signed = light_formats.signed_content_of(source_path.read_bytes())

    def signatures_for(target: str, source: str) -> list[dict]:
        return [
            {"relative_path": target, "source": source, "signer": item.signer,
             "holder_document": item.holder_document, "signed_at": item.signed_at}
            for item in signed.signatures
        ]

    skipped_sql = (
        "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0, ocr_failed = 0"
        " WHERE id = ?"
    )
    if signed.content is None:
        sibling = _detached_sibling(source_path, relative_path)
        return {
            "sql": skipped_sql, "params": (REASON_SIGNATURE_DETACHED, row["id"]), "ocr_applied": False,
            "signatures": signatures_for(sibling, f"detached:{row['name']}") if sibling else [],
        }

    signatures = signatures_for(relative_path, "embedded")
    kind = light_formats.sniff_content_type(signed.content)
    content = signed.content
    if kind == "epub":
        import tempfile

        with tempfile.TemporaryDirectory(prefix="gclaude-p7m-") as folder:
            inner = Path(folder) / "conteudo.epub"
            inner.write_bytes(content)
            content = light_formats.convert_to_pdf_bytes(inner)
        kind = "pdf"

    pdf_path = workdir.local_path(output_dir, "converted", relative_path, f".{extension}.pdf")
    text_path = workdir.local_path(output_dir, "converted", relative_path, f".{extension}.txt")
    if kind == "binary":
        for stale in (pdf_path, text_path):
            stale.unlink(missing_ok=True)
        return {
            "sql": skipped_sql, "params": (REASON_BINARY, row["id"]), "ocr_applied": False,
            "signatures": signatures,
        }
    if kind == "pdf":
        text_path.unlink(missing_ok=True)
        needs_ocr, ocr_failed, ocr_applied, page_count = _store_pdf_intermediate(
            config, row["name"], content, output_dir, relative_path, extension, ocrmypdf_jobs, events, row, notes
        )
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        return {
            "sql": sql, "params": (page_count, int(needs_ocr), int(ocr_failed), row["id"]),
            "ocr_applied": ocr_applied, "signatures": signatures,
        }

    try:
        text, ocr_pending = _signed_content_text(kind, content, config)
    except light_formats.LightFormatError:
        if kind != "xls":
            raise
        # OLE que não é planilha (um `.doc`, um `.ppt`): sem leitor aqui.
        for stale in (pdf_path, text_path):
            stale.unlink(missing_ok=True)
        return {
            "sql": skipped_sql, "params": (REASON_BINARY, row["id"]), "ocr_applied": False,
            "signatures": signatures,
        }
    pdf_path.unlink(missing_ok=True)
    destination = workdir.destination(output_dir, "converted", relative_path, f".{extension}.txt")
    destination.write_text(text, encoding="utf-8")
    is_image = kind == "image"
    if is_image and not ocr_pending:
        events.append((
            "conversion", "info", "log.conversion.ocr_applied",
            {"name": row["name"], "ocr_language": config.ocr_language},
        ))
    sql = (
        "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = ?,"
        " ocr_failed = ? WHERE id = ?"
    )
    return {
        "sql": sql, "params": (int(is_image), int(ocr_pending), row["id"]),
        "ocr_applied": is_image and not ocr_pending, "signatures": signatures,
    }


def _process_file(config: ProjectConfig, row: dict, ocrmypdf_jobs: int) -> dict:
    """Converts one file and returns what the main process needs to write to
    the database — never touches `conn`.

    Runs both on the sequential path (direct call) and inside a
    `ProcessPoolExecutor` worker process (via `pickle`, on Windows with
    `spawn`): that's why it's a module-level function, takes only
    serializable arguments (`config` is a plain dataclass; `row` is a
    `dict`, not a `sqlite3.Row`/`sqlite3.Connection`), and never receives
    `conn`.
    """
    relative_path = row["relative_path"]
    name = row["name"]
    extension_with_dot = "." + row["extension"]
    category = category_of_extension(extension_with_dot)
    source_path = Path(config.source_folder) / relative_path
    output_dir = Path(config.output_folder)

    # (step, level, i18n key, params) — rendered by `_apply_result`, which
    # runs in the main process and has `conn`/`language`; this function may
    # run in a worker process (see the docstring above) and never does.
    events: list[tuple[str, str, str, dict]] = []
    # Idioma detectado aqui (`file.ocr_lang`, `file.language`): gravado por
    # `_apply_result`, no processo principal.
    notes: dict = {}
    ocr_applied = False
    ocr_failed = False

    if category == "pdf":
        destination = workdir.local_path(output_dir, "converted", relative_path, ".pdf")
        needs_ocr, ocr_failed, ocr_applied, page_count = _ocr_pdf_pages(
            config, name, source_path, destination, ocrmypdf_jobs, events, row, notes
        )
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (page_count, int(needs_ocr), int(ocr_failed), row["id"])

    elif category == "paginados":
        # O PyMuPDF faz o PDF; dali em diante é o caminho do PDF (texto
        # nativo, OCR das páginas sem texto).
        needs_ocr, ocr_failed, ocr_applied, page_count = _store_pdf_intermediate(
            config, name, light_formats.convert_to_pdf_bytes(source_path), output_dir, relative_path,
            row["extension"], ocrmypdf_jobs, events, row, notes,
        )
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (page_count, int(needs_ocr), int(ocr_failed), row["id"])

    elif category == LEGACY_CATEGORY:
        soffice = legacy_office.soffice_path()
        if soffice is None:
            # O LibreOffice não pôde ser obtido (sem rede): o arquivo não
            # falha. Fica pendente e volta à fila na próxima conversão; o
            # aviso (uma vez só) sai em `convert`.
            return {
                "id": row["id"], "name": name, "events": [], "ocr_applied": False,
                "sql": (
                    "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0,"
                    " ocr_failed = 1 WHERE id = ?"
                ),
                "params": (REASON_COMPONENT_UNAVAILABLE, row["id"]),
            }
        needs_ocr, ocr_failed, ocr_applied, page_count = _store_pdf_intermediate(
            config, name, legacy_office.convert_to_pdf_bytes(source_path, soffice), output_dir,
            relative_path, row["extension"], ocrmypdf_jobs, events, row, notes,
        )
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (page_count, int(needs_ocr), int(ocr_failed), row["id"])

    elif category == "assinados":
        signed = _convert_signed(config, row, source_path, output_dir, ocrmypdf_jobs, events, notes)
        return {
            "id": row["id"], "name": name, "sql": signed["sql"], "params": signed["params"],
            "events": events, "ocr_applied": signed["ocr_applied"], "signatures": signed["signatures"],
            **_language_update(notes),
        }

    elif category == "imagens":
        plan, short = _row_plan(config, row)
        # A imagem tem um grupo só; um plano com grupos (não acontece) vale
        # pelos idiomas de todos.
        languages = "+".join(ocr_detection.plan_models(plan))
        rotate = int(row.get("image_rotate") or 0)
        if languages:
            text = _extract_text_image(source_path, languages, rotate=rotate)
            ocr_applied = True
            ocr_failed = short
            if not short and len(text.strip()) < REREAD_MIN_CHARS:
                text, absent = _reread_image(source_path, text, languages, rotate, row.get("ocr_usable"), events, name)
                wanted_plan = _plan_with_models(plan, absent) if absent else None
                if wanted_plan:
                    notes["ocr_lang"] = wanted_plan
                    ocr_failed = True
            events.append((
                "conversion", "info", "log.conversion.ocr_applied",
                {"name": name, "ocr_language": languages},
            ))
        else:
            # Task 7: same as the scanned PDF above — no text for now,
            # done again when the OCR language is there.
            text = ""
            ocr_failed = True
        destination = _destination_path(output_dir, "converted", relative_path, text_suffix(row["extension"]))
        destination.write_text(text, encoding="utf-8")
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 1,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (int(ocr_failed), row["id"])

    elif category in _TEXT_CATEGORIES:
        extension = row["extension"].lower()
        text = _extract_light_text(category, extension, source_path)
        destination = _destination_path(output_dir, "converted", relative_path, text_suffix(extension))
        destination.write_text(text, encoding="utf-8")
        # A caixa `.mbox` tem uma página por mensagem.
        pages = text.count(light_formats.MBOX_PAGE_SEPARATOR) + 1 if category == "mbox" else 1
        sql = "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = 0 WHERE id = ?"
        params = (pages, row["id"])

    else:
        # Extension with no category ("all" rule). Audio and video (`midia`)
        # never get here: they have their own queue (`_convert_media`).
        # The scan already refused binary content by the first
        # bytes; the check stays here for rows an older version left as
        # `discovered`, but only the start is read to decide — the whole
        # file is read only once it is known to be text.
        with open(source_path, "rb") as source_file:
            head = source_file.read(_BINARY_SNIFF_BYTES)
        if looks_binary(head):
            text = ""
        else:
            text = decode_bytes(source_path.read_bytes())[0]
        destination = _destination_path(output_dir, "converted", relative_path, ".txt")
        destination.write_text(text, encoding="utf-8")
        sql = "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 0 WHERE id = ?"
        params = (row["id"],)

    return {
        "id": row["id"],
        "name": name,
        "sql": sql,
        "params": params,
        "events": events,
        "ocr_applied": ocr_applied,
        **_language_update(notes),
    }


def _language_update(notes: dict) -> dict:
    """O idioma achado na conversão, para `_apply_result` gravar (e a
    amostra, para o processo principal decidir o idioma: `_resolve_language`)."""
    update: dict = {}
    if notes.get("ocr_lang") or notes.get("language"):
        update["language_update"] = (notes.get("ocr_lang"), notes.get("language"))
    if notes.get("language_sample"):
        update["language_sample"] = notes["language_sample"]
        update["ocr_used"] = notes.get("ocr_used") or ""
    return update


def _resolve_language(info: dict) -> tuple[tuple[str | None, str | None] | None, bool]:
    """`(language_update, refazer)`. Para os formatos que detectam no
    trabalhador (`_detect_in_worker`), o idioma da amostra é decidido aqui,
    no processo principal; se o OCR foi feito sem o modelo desse idioma, o
    plano certo fica em `file.ocr_lang` e `ocr_failed` traz o arquivo de
    volta na próxima conversão."""
    update = info.get("language_update")
    sample = info.get("language_sample")
    if not sample:
        return update, False
    found = language_detect.detect_languages(sample)
    if not found:
        return update, False
    wanted = language_detect.tesseract_languages(found, sample)
    used = ocr_detection.plan_models(info.get("ocr_used"))
    redo = bool(info.get("ocr_applied")) and not _covers(used, wanted)
    return ("+".join(wanted) or None, ",".join(found)), redo


def _covers(used: list[str], wanted: list[str]) -> bool:
    """Se o OCR feito com `used` leu o que `wanted` pede: cada modelo pedido
    está lá, ou está o modelo da escrita dele (posto quando o do idioma
    faltava; aí o arquivo já voltou marcado pelo trabalhador)."""
    present = set(used)
    for model in wanted:
        if model in present:
            continue
        script = language_detect.model_script(model)
        if script is None or language_detect.script_model(script) not in present:
            return False
    return True


def _store_signatures(conn, signatures) -> None:
    """Grava os signatários lidos de um `.p7m`/`.p7s` em `file_signature`,
    no arquivo assinado. Refazer a conversão substitui o que a mesma origem
    gravou antes (cada `.p7s` destacado tem a sua)."""
    if not signatures:
        return
    ids: dict[str, int | None] = {}
    for item in signatures:
        path = item["relative_path"]
        if path not in ids:
            found = conn.execute("SELECT id FROM file WHERE relative_path = ?", (path,)).fetchone()
            ids[path] = found["id"] if found is not None else None
    cleared: set[tuple[int, str]] = set()
    for item in signatures:
        file_id = ids[item["relative_path"]]
        if file_id is None:
            continue
        if (file_id, item["source"]) not in cleared:
            conn.execute(
                "DELETE FROM file_signature WHERE file_id = ? AND source = ?", (file_id, item["source"])
            )
            cleared.add((file_id, item["source"]))
        conn.execute(
            "INSERT INTO file_signature (file_id, signer, holder_document, signed_at, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (file_id, item["signer"], item["holder_document"], item["signed_at"], item["source"]),
        )


def _apply_result(writer: BatchWriter, result: ConversionResult, info: dict, language: str | None = None) -> None:
    # Fora da operação do gravador: a primeira detecção carrega o modelo.
    language_update, redo = _resolve_language(info)

    def op(conn) -> None:
        conn.execute(info["sql"], info["params"])
        if language_update:
            ocr_lang, detected = language_update
            conn.execute(
                "UPDATE file SET ocr_lang = COALESCE(?, ocr_lang), language = COALESCE(?, language) WHERE id = ?",
                (ocr_lang, detected, info["id"]),
            )
        if redo:
            conn.execute("UPDATE file SET ocr_failed = 1 WHERE id = ?", (info["id"],))
        _store_signatures(conn, info.get("signatures", ()))
        for step, level, key, params in info["events"]:
            record_event(conn, step, level, key, params, language=language, commit=False)

    writer.add(op)
    result.converted += 1
    result.ocr_applied += int(info["ocr_applied"])


def _record_failure(
    writer: BatchWriter, result: ConversionResult, row, error_message: str, language: str | None = None,
    ocr_failed: bool = False,
) -> None:
    error_message = error_message[:ERROR_MESSAGE_CHAR_LIMIT]

    def op(conn) -> None:
        conn.execute(
            "UPDATE file SET status = 'failed', error = ?, ocr_failed = ? WHERE id = ?",
            (error_message, int(ocr_failed), row["id"]),
        )
        record_event(
            conn, "conversion", "error", "log.conversion.failed",
            {"name": row["name"], "error": error_message}, language=language, commit=False,
        )

    writer.add(op)
    result.failed += 1


def _record_event_op(step: str, level: str, key: str, params: dict | None = None, language: str | None = None):
    return lambda conn: record_event(conn, step, level, key, params, language=language, commit=False)


def _convert_sequential(
    conn, config: ProjectConfig, rows, ocrmypdf_jobs: int, should_stop, result, language: str | None = None
) -> None:
    """Economy mode and single files: one file at a time, in this process.

    Under the same `ResilientPool` as the parallel path, with a
    `DaemonThreadExecutor` instead of worker processes. A file frozen on
    Google Drive is abandoned at its deadline instead of freezing the step,
    and the rest of the behaviour (deadlines, retries, stall detection)
    is the parallel path's."""
    _convert_guarded(
        conn, config, rows, 1, ocrmypdf_jobs, should_stop, result, language, DaemonThreadExecutor,
    )


def _convert_in_parallel(
    conn, config: ProjectConfig, rows, workers: int, ocrmypdf_jobs: int, should_stop, result,
    language: str | None = None,
) -> None:
    _convert_guarded(
        conn, config, rows, workers, ocrmypdf_jobs, should_stop, result, language,
        lambda: ProcessPoolExecutor(max_workers=workers, initializer=no_window.install),
    )


def _convert_guarded(
    conn, config: ProjectConfig, rows, workers: int, ocrmypdf_jobs: int, should_stop, result,
    language: str | None, executor_factory: Callable[[], object],
) -> None:
    """One file per worker (a process, or a daemon thread in economy mode,
    see `_convert_sequential`). `sqlite3.Connection` never crosses a
    process boundary — each worker only returns the result (a serializable
    dict); the one that always writes to the database is this main process.

    `initializer=no_window.install`: each worker is `spawn`ed as a fresh
    interpreter, so the main process's console-window suppression does not
    carry over on its own. A worker that handles an image calls
    `pytesseract`, which starts `tesseract.exe` through a `subprocess.Popen`
    of its own that we do not control — without the initializer that is one
    visible console window per image.

    `ResilientPool` (see `worker_pool.py`) instead of a bare
    `with ProcessPoolExecutor(...)`, whose exit waited forever for workers
    stuck on a Google Drive file, and `BatchWriter` instead of one commit
    per file."""
    writer = BatchWriter(conn)
    crash_reported = False

    def on_restart(reason: str, row) -> None:
        nonlocal crash_reported
        if reason == "stalled":
            writer.add(_record_event_op(
                "conversion", "warning", "log.worker_restarted",
                {"name": row["name"], "minutes": _minutes(deadline_for_size(row["size"]))}, language,
            ))
        elif not crash_reported:
            # A worker died (e.g. `MemoryError` on a large PDF) and took the
            # pool down with it. The pool is
            # rebuilt and the files it held are tried again; a file caught
            # in two crashes keeps its 'discovered' status for the next run
            # instead of being failed, since a crash does not say which
            # file caused it.
            crash_reported = True
            writer.add(_record_event_op("conversion", "error", "log.pool_broken", language=language))

    def submit(executor, row):
        return executor.submit(_process_file, config, dict(row), ocrmypdf_jobs)

    try:
        with ResilientPool(
            executor_factory,
            workers,
            deadline_for=lambda row: deadline_for_size(row["size"]),
            should_stop=should_stop,
            on_restart=on_restart,
            on_idle=writer.flush_if_due,
        ) as pool:
            for outcome in pool.run(rows, submit):
                row = outcome.item
                if outcome.kind == OK:
                    _apply_result(writer, result, outcome.value, language=language)
                elif outcome.kind == ERROR:
                    _record_failure(
                        writer, result, row, str(outcome.value), language=language,
                        ocr_failed=isinstance(outcome.value, OcrError),
                    )
                elif outcome.kind == TIMED_OUT:
                    _record_failure(
                        writer, result, row,
                        translate(language or DEFAULT_LANGUAGE, "error.file_timed_out", minutes=_minutes(outcome.value)),
                        language=language,
                    )
                # CRASHED: left 'discovered' on purpose (see `on_restart`).
        writer.flush()
    except PoolStalledError as exc:
        writer.add(_record_event_op(
            "conversion", "error", "log.pool_stalled", {"name": exc.item["name"]}, language,
        ))
        writer.flush()
        raise StepStalledError(
            translate(language or DEFAULT_LANGUAGE, "log.pool_stalled", name=exc.item["name"])
        ) from exc
    except BaseException as exc:
        # Work already done is good whatever went wrong elsewhere; a database
        # error, though, means the batch itself cannot be trusted.
        if isinstance(exc, sqlite3.Error):
            writer.discard()
        else:
            try:
                writer.flush()
            except Exception:
                writer.discard()
        raise


def _minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def component_ready(extension: str) -> bool:
    """Se o componente de que um arquivo desta extensão depende está nesta
    máquina agora — o LibreOffice (o baixado ou um do sistema) para os
    formatos antigos, ffmpeg/whisper.cpp/modelo para a mídia. Nunca usa a
    rede. Extensão que não depende de componente: `True`.

    É a mesma pergunta que a conversão faz antes de marcar o arquivo como
    `component_unavailable`; se as duas discordassem, o plano de
    atualização apontaria o arquivo, a conversão o marcaria de novo, e o
    grupo perderia as janelas em toda execução (revisão final, I1)."""
    category = category_of_extension("." + extension.lstrip("."))
    if category == LEGACY_CATEGORY:
        return legacy_office.soffice_path() is not None
    if category == MEDIA_CATEGORY:
        return media.tools_present()
    return True


def _groups_with_windows(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT DISTINCT group_key FROM window")}


def _waiting_component(row, windowed: set[str]) -> bool:
    """Arquivo que espera um componente num grupo que já tem janelas.

    Fica fora da fila, como o `extracted` cujo OCR falhou: as páginas
    novas entrariam no meio do grupo sem que as janelas fossem refeitas.
    Quem o traz de volta é o plano de atualização, que só o aponta quando
    o componente está nesta máquina (`update_plan.detect_changes`) e
    então refaz as janelas do grupo junto."""
    return (
        row["status"] == "skipped"
        and row["error"] == REASON_COMPONENT_UNAVAILABLE
        and row["group_key"] in windowed
    )


def _ocr_retry_candidates(conn) -> tuple[list, list[str]]:
    """`(rows to requeue, names held back)` — see `requeue_ocr_failures`.
    Files waiting for a component in a group with windows are in neither
    list (`components_held_back`)."""
    has_windows = conn.execute("SELECT 1 FROM window LIMIT 1").fetchone() is not None
    windowed = _groups_with_windows(conn) if has_windows else set()
    rows = conn.execute(
        "SELECT id, name, status, error, group_key, extension FROM file WHERE ocr_failed = 1"
        " AND (status IN ('converted', 'extracted', 'failed')"
        # Um `skipped` só volta à fila se foi a falta do componente que o
        # deixou assim; o que a varredura recusou (segredo, binário,
        # compactado…) nunca é reaberto por aqui.
        f" OR (status = 'skipped' AND error = '{REASON_COMPONENT_UNAVAILABLE}')) ORDER BY relative_path"
    ).fetchall()
    rows = [row for row in rows if not _waiting_component(row, windowed)]
    requeue = [row for row in rows if not (row["status"] == "extracted" and has_windows)]
    held_back = [row["name"] for row in rows if row["status"] == "extracted" and has_windows]
    return requeue, held_back


def components_held_back(conn) -> list:
    """Os arquivos que esperam um componente fora da fila (ver
    `_waiting_component`), em ordem de caminho."""
    windowed = _groups_with_windows(conn)
    if not windowed:
        return []
    rows = conn.execute(
        "SELECT id, name, status, error, group_key, extension FROM file"
        f" WHERE status = 'skipped' AND error = '{REASON_COMPONENT_UNAVAILABLE}' ORDER BY relative_path"
    ).fetchall()
    return [row for row in rows if _waiting_component(row, windowed)]


def ocr_retry_count(conn) -> int:
    """How many files the next conversion will send back to the queue —
    the Execution screen counts them as pending conversion."""
    return len(_ocr_retry_candidates(conn)[0])


def requeue_ocr_failures(conn, language: str | None = None) -> int:
    """Sends every file whose OCR failed (`file.ocr_failed = 1`) back to
    'discovered', so this conversion tries it again. Only OCR
    failures: a corrupt or protected file would fail the same way forever.

    The flag stays set until a conversion succeeds, so a file that keeps
    failing is retried on every run — at the cost of one more attempt.

    An 'extracted' file is only requeued while the project has no windows.
    Its pages are already inside window text files, which the windows step
    never rewrites (`prepare_windows` keeps a `.txt` that exists); sending
    it back would silently leave the old blank pages in those windows.
    Those files are named in a warning instead — the project update is the
    path that discards windows correctly."""
    from .fulltext import remove_file as remove_from_search

    rows, held_back = _ocr_retry_candidates(conn)
    requeued = 0
    try:
        for row in rows:
            remove_from_search(conn, row["id"])
            conn.execute("DELETE FROM page WHERE file_id = ?", (row["id"],))
            # Same reset as a changed file in `invalidation.apply_update`.
            conn.execute(
                "UPDATE file SET status = 'discovered', page_count = NULL, error = NULL WHERE id = ?",
                (row["id"],),
            )
            requeued += 1
        if requeued:
            record_event(
                conn, "conversion", "info", "log.conversion.ocr_retry",
                {"count": requeued}, language=language, commit=False,
            )
        if held_back:
            record_event(
                conn, "conversion", "warning", "log.conversion.ocr_retry_held",
                {"count": len(held_back), "names": ", ".join(held_back[:20])},
                language=language, commit=False,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return requeued


def component_display_name(name: str) -> str:
    """O nome de um componente do manifesto como o log o mostra."""
    if name == legacy_office.COMPONENT_NAME:
        return "LibreOffice"
    return media.DISPLAY_NAMES.get(name, name)


def _announce_download(conn, language):
    """`on_download` de `components.ensure`: antes de um download de
    centenas de megabytes começar, o log diz o que vem e de que tamanho.
    Antes disso a conversão ficava parada, sem aviso, por minutos."""
    def on_download(component) -> None:
        record_event(
            conn, "conversion", "info", "log.conversion.component_downloading",
            {"component": component_display_name(component.name), "size_mb": max(1, round(component.size / 1_000_000))},
            language=language,
        )

    return on_download


def _obtain_held_components(conn, should_stop, language) -> None:
    """Tenta obter o componente dos arquivos que esperam fora da fila
    (`components_held_back`) e diz no log por que eles ficaram de fora.

    Sem isto ninguém mais pediria o download: só a fila da conversão chama
    `legacy_office.ensure_available`/`media.prepare`, e esses arquivos não
    voltam à fila. Com o componente obtido aqui, a próxima execução (ou
    "Atualizar") os aponta como alterados e refaz as janelas do grupo."""
    held = components_held_back(conn)
    if not held:
        return
    legacy = [row["name"] for row in held if category_of_extension("." + row["extension"]) == LEGACY_CATEGORY]
    media_names = [row["name"] for row in held if category_of_extension("." + row["extension"]) == MEDIA_CATEGORY]
    fetch = {"should_stop": should_stop, "on_download": _announce_download(conn, language)}
    for names, component, obtain in (
        (legacy, "LibreOffice", lambda: legacy_office.ensure_available(**fetch)),
        (media_names, "ffmpeg/whisper.cpp", lambda: media.prepare(**fetch)),
    ):
        if not names or (should_stop is not None and should_stop()):
            continue
        try:
            obtain()
        except Exception:
            # `ensure` nunca levanta; isto é só para que um imprevisto aqui
            # não derrube a conversão dos outros arquivos.
            pass
        if should_stop is not None and should_stop():
            return
        record_event(
            conn, "conversion", "warning", "log.conversion.component_held",
            {"component": component, "count": len(names), "names": ", ".join(names[:20])},
            language=language,
        )


def _convert_heavy(conn, config: ProjectConfig, heavy, should_stop, result, language) -> None:
    """The files that may need OCR, one per physical core."""
    workers = workers_for(config.parallelism)
    # With 0 or 1 file there's nothing to parallelize — spawning processes
    # would cost more than processing directly (Windows' `spawn` has a real
    # startup cost), so the sequential path is used even with an
    # "automatic"/"maximum" mode configured.
    if workers <= 1 or len(heavy) <= 1:
        # With no pool of processes competing for the same cores, `--jobs 1`
        # avoids the whole problem below at no cost (it's a single file).
        _convert_sequential(conn, config, heavy, 1, should_stop, result, language=language)
    else:
        # Each pool worker runs its own `ocrmypdf --jobs N`. The two axes of
        # parallelism (pool processes x ocrmypdf threads) multiply: using the
        # same value for both (original Task 14 decision) gives, in "maximum"
        # mode with 8 cores, 8 processes x `--jobs 8` = up to 64 simultaneous
        # tesseracts competing for 8 cores. Task 14 measured a 6.73x gain with
        # 3-page PDFs — little RAM per file; a real scanned collection has far
        # more pages per file, and memory per tesseract scales by a different
        # order of magnitude. Combined with I3 (one worker running out of
        # memory took down the whole pool and condemned the rest of the
        # collection), overallocating threads was doubly risky. Splitting the
        # physical cores across the pool's workers keeps the product
        # (processes x jobs) close to the machine's core count.
        #
        # Floor of 2, not 1: dividing with no floor gives `--jobs 1` in
        # "maximum" mode (physical // workers = 8 // 8), which the C1/
        # parallelism defect review measured as too conservative — it dropped
        # the gain from 6.43x to 5.06x (a 27% drop) on a corpus of 12 3-page
        # PDFs. With a floor of 2, 8 workers x 2 jobs = 16 threads on 8 cores:
        # 2x oversubscription, the usual pattern for a mixed CPU/IO workload,
        # far from the 64 tesseracts of the original behavior.
        ocrmypdf_jobs = max(2, _physical_cores() // workers)
        _convert_in_parallel(conn, config, heavy, workers, ocrmypdf_jobs, should_stop, result, language=language)


# --- Outlook (`.pst`, `.ost`) ---------------------------------------------------------


def _pdf_native_text(data: bytes) -> str:
    """O texto nativo de um PDF (sem OCR: um anexo escaneado não entra)."""
    document = fitz.open(stream=data, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def _renamed_for(path: Path, accepted: set[str], canonical: str) -> Path:
    """O anexo com a extensão que o extrator do tipo real espera, quando a
    que veio no nome não é uma delas (o tipo real manda, não o nome)."""
    if path.suffix.lower() in accepted:
        return path
    target = path.with_name(path.stem + canonical)
    path.replace(target)
    return target


def _attachment_text(path: Path, config: ProjectConfig, original_name: str | None = None) -> str | None:
    """O texto de um anexo gravado em `path`, pelo extrator do tipo real dele
    (pelos bytes, não pelo nome). `None` quando o tipo não é lido: compactado
    (continua ignorado, como no inventário), binário, executável, chave, ou
    imagem sem idioma de OCR.

    Vale a mesma regra da varredura (`index_decision`): o nome original do
    anexo (`.env`, `id_rsa`, `.pfx`…) e o começo do conteúdo (chave privada)
    barram o anexo; e o texto extraído passa de novo pela checagem da chave
    privada, porque um contêiner (DOCX, PDF) a esconde dos primeiros bytes."""
    name = original_name or path.name
    head = path.read_bytes()[:HEAD_BYTES] if path.stat().st_size else b""
    # `binary` não barra aqui: um anexo de extensão estranha mas conteúdo de PDF
    # ou DOCX vale pelo tipo real, e o que é binário de verdade o farejador
    # (`sniff_content_type`) recusa logo abaixo.
    # O nome original e o nome gravado em disco: se qualquer um é recusado, o
    # anexo é recusado.
    for candidate in (name, path.name):
        reason = index_decision(candidate, head, config.extensions)
        if reason is not None and reason != REASON_BINARY:
            return None
    text = _extract_attachment_text(path, config)
    if text and has_private_key_marker(text.encode("utf-8", errors="ignore")):
        return None
    return text


def _extract_attachment_text(path: Path, config: ProjectConfig) -> str | None:
    # `file_extension` (e não `Path.suffix`): `.env` é extensão, não nome.
    extension = file_extension(path.name)
    if (
        extension in ARCHIVE_EXTENSIONS or extension in ALWAYS_BLOCKED_EXTENSIONS
        or extension in SECRET_EXTENSIONS or extension in GOOGLE_DOC_EXTENSIONS
        or extension in EXTENSION_CATEGORIES["outlook"] or extension in EXTENSION_CATEGORIES["mbox"]
        or extension in EXTENSION_CATEGORIES["midia"]
    ):
        return None
    data = path.read_bytes()
    kind = light_formats.sniff_content_type(data)
    if kind == "pdf":
        return _pdf_native_text(data)
    if kind == "docx":
        return _extract_text_docx(_renamed_for(path, EXTENSION_CATEGORIES["docx"], ".docx"))
    if kind == "xlsx":
        return _extract_text_xlsx(_renamed_for(path, EXTENSION_CATEGORIES["xlsx"] - {".xls"}, ".xlsx"))
    if kind == "pptx":
        return _extract_text_pptx(_renamed_for(path, EXTENSION_CATEGORIES["pptx"], ".pptx"))
    if kind == "odf":
        return light_formats.extract_text_opendocument(_renamed_for(path, {".odt", ".ods", ".odp", ".odg"}, ".odt"))
    if kind == "epub":
        return _pdf_native_text(light_formats.convert_to_pdf_bytes(_renamed_for(path, {".epub"}, ".epub")))
    if kind == "rtf":
        return light_formats.extract_text_rtf(path)
    if kind == "image":
        if not config.ocr_language:
            return None
        return _extract_text_image(path, config.ocr_language)
    if kind == "xls":
        # O contêiner OLE2 antigo: o nome diz se é planilha, mensagem ou
        # documento do Office antigo (este só se o LibreOffice já está aí).
        if extension in (".xls", ".xlt"):
            return light_formats.extract_text_xls(path, data)
        if extension == ".msg":
            return _extract_text_msg(path)
        if extension in EXTENSION_CATEGORIES[LEGACY_CATEGORY]:
            soffice = legacy_office.soffice_path()
            if soffice is not None:
                return _pdf_native_text(legacy_office.convert_to_pdf_bytes(path, soffice))
        return None
    if kind == "text":
        if extension == ".eml":
            return _extract_text_eml(path)
        if extension in (".srt", ".vtt"):
            return light_formats.extract_text_subtitles(path)
        if extension == ".dxf":
            return light_formats.extract_text_dxf(path)
        if extension.lstrip(".") in _HTML_EXTENSIONS | _MHTML_EXTENSIONS | {"xml", "json"}:
            return _extract_text_web(path, extension.lstrip("."))
        return decode_bytes(data)[0]
    return None


def _process_outlook(config: ProjectConfig, row: dict, should_stop) -> dict | None:
    """Converte um `.pst`/`.ost`; `None` quando Parar foi pedido (o arquivo
    continua `discovered` e a conversão seguinte retoma da mensagem em que
    parou). Roda neste processo: a leitura em fluxo e a retomada dependem de
    um único dono do arquivo parcial."""
    name = row["name"]
    relative_path = row["relative_path"]
    extension = row["extension"].lower()
    output_dir = Path(config.output_folder)
    source_path = Path(config.source_folder) / relative_path
    destination = _destination_path(output_dir, "converted", relative_path, text_suffix(extension))
    attachments_root = workdir.work_folder(output_dir) / "converted" / relative_path / "anexos"
    events: list[tuple[str, str, str, dict]] = []
    skipped_attachments = 0

    def on_note(kind: str, params: dict) -> None:
        nonlocal skipped_attachments
        if kind == "attachment_too_large":
            skipped_attachments += 1

    try:
        result = outlook.convert_pst(
            source_path, destination, attachments_root, lambda path, name: _attachment_text(path, config, name),
            should_stop=should_stop, on_note=on_note,
        )
    except outlook.Interrupted:
        return None
    except outlook.ReaderUnavailable:
        return {
            "id": row["id"], "name": name, "events": [], "ocr_applied": False, "unavailable": True,
            "sql": (
                "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0,"
                " ocr_failed = 0 WHERE id = ?"
            ),
            "params": (REASON_UNSUPPORTED, row["id"]),
        }
    if result.truncated == "messages":
        events.append((
            "conversion", "warning", "log.conversion.outlook_truncated",
            {"name": name, "limit": outlook.MAX_MESSAGES},
        ))
    elif result.truncated == "output":
        events.append((
            "conversion", "warning", "log.conversion.outlook_output_limit",
            {"name": name, "limit_mb": outlook.MAX_OUTPUT_BYTES // (1024 * 1024)},
        ))
    if skipped_attachments:
        events.append((
            "conversion", "warning", "log.conversion.outlook_attachments_skipped",
            {"name": name, "count": skipped_attachments},
        ))
    return {
        "id": row["id"], "name": name, "events": events, "ocr_applied": False,
        "sql": "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = 0 WHERE id = ?",
        "params": (result.pages, row["id"]),
    }


def _convert_outlook(conn, config: ProjectConfig, rows, should_stop, result, language) -> None:
    """Um arquivo do Outlook por vez, neste processo, sem prazo por arquivo
    (um `.pst` de dezenas de gigabytes leva o tempo que levar; Parar vale a
    cada mensagem). Sem a biblioteca de leitura os arquivos ficam ignorados
    com o motivo `unsupported` e o log diz uma vez."""
    writer = BatchWriter(conn)
    unavailable = 0
    try:
        for row in rows:
            if should_stop is not None and should_stop():
                break
            try:
                info = _process_outlook(config, dict(row), should_stop)
            except Exception as exc:
                _record_failure(writer, result, row, str(exc) or exc.__class__.__name__, language=language)
                continue
            if info is None:
                break
            if info.get("unavailable"):
                unavailable += 1
            _apply_result(writer, result, info, language=language)
        if unavailable:
            writer.add(_record_event_op(
                "conversion", "warning", "log.conversion.outlook_unavailable", {"count": unavailable}, language,
            ))
    finally:
        try:
            writer.flush()
        except Exception:
            writer.discard()


def _process_media(config: ProjectConfig, row: dict, tools: media.Toolset, should_stop, on_estimate) -> dict | None:
    """Transcreve um áudio ou vídeo; `None` quando Parar foi pedido (o
    arquivo continua `discovered` e a conversão seguinte retoma do trecho em
    que parou). Roda neste processo: a retomada depende de um único dono do
    arquivo parcial."""
    name = row["name"]
    relative_path = row["relative_path"]
    extension = row["extension"].lower()
    output_dir = Path(config.output_folder)
    source_path = Path(config.source_folder) / relative_path
    destination = _destination_path(output_dir, "converted", relative_path, text_suffix(extension))
    work = workdir.work_folder(output_dir) / "converted" / relative_path / "midia"
    try:
        outcome = media.transcribe(source_path, destination, work, tools, should_stop, on_estimate)
    except media.Interrupted:
        return None
    except media.Postponed:
        # Passou do tempo previsto: o progresso ficou e o arquivo continua na
        # fila (`discovered`) para a próxima conversão, que retoma dele.
        return {"postponed": True, "name": name}
    except media.MediaRefused:
        # Lista de reprodução ou roteiro disfarçado de mídia: não é lido.
        return {
            "id": row["id"], "name": name, "events": [], "ocr_applied": False,
            "sql": (
                "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0,"
                " ocr_failed = 0 WHERE id = ?"
            ),
            "params": (REASON_UNSUPPORTED, row["id"]),
        }
    events: list[tuple[str, str, str, dict]] = []
    if outcome.no_audio:
        events.append(("conversion", "warning", "log.conversion.media_no_audio", {"name": name}))
    if outcome.language:
        events.append((
            "conversion", "info", "log.conversion.media_language",
            {"name": name, "lang": outcome.language},
        ))
    if outcome.truncated:
        events.append((
            "conversion", "warning", "log.conversion.media_truncated",
            {"name": name, "hours": media.MAX_AUDIO_SECONDS // 3600, "limit_mb": media.MAX_OUTPUT_BYTES // (1024 * 1024)},
        ))
    return {
        "id": row["id"], "name": name, "events": events, "ocr_applied": False,
        "sql": (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = 0,"
            " ocr_failed = 0 WHERE id = ?"
        ),
        "params": (outcome.pages, row["id"]),
        # O idioma da fala (whisper) vai para `file.language`, como o de
        # qualquer documento; até a Tarefa 12 ia para um `.idioma` ao lado.
        **({"language_update": (None, outcome.language)} if outcome.language else {}),
    }


def _convert_media(conn, config: ProjectConfig, rows, should_stop, result, language) -> None:
    """Áudio e vídeo (`midia`) pelo ffmpeg e pelo whisper.cpp, um arquivo por
    vez, neste processo, sem prazo fixo por arquivo (cada um tem o seu,
    proporcional à duração; Parar vale a cada trecho).

    Os componentes e o modelo escolhido pelo computador são baixados aqui,
    só porque o acervo tem mídia selecionada. Sem eles (sem rede, download
    recusado) ninguém falha: cada arquivo fica pendente, volta à fila na
    próxima conversão e o log diz uma vez o que faltou."""
    found, missing = media.prepare(should_stop=should_stop, on_download=_announce_download(conn, language))
    if found is None and should_stop is not None and should_stop():
        # Parar no meio do download: os arquivos continuam na fila.
        return
    writer = BatchWriter(conn)
    if found is None:
        def mark(row):
            return lambda c: c.execute(
                "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0, ocr_failed = 1"
                " WHERE id = ?",
                (REASON_COMPONENT_UNAVAILABLE, row["id"]),
            )

        try:
            for row in rows:
                writer.add(mark(row))
            writer.add(_record_event_op(
                "conversion", "warning", "log.conversion.media_component_unavailable",
                {"component": ", ".join(missing), "count": len(rows)}, language,
            ))
            writer.flush()
        except Exception:
            writer.discard()
        return

    def announce(name):
        def on_estimate(info: dict) -> None:
            record_event(
                conn, "conversion", "info", "log.conversion.media_estimate",
                {
                    "name": name, "model": info["model"], "device": "GPU (Vulkan)" if info["vulkan"] else "CPU",
                    "duration": media.format_clock(info["duration"]),
                    "minutes": max(1, round(info["estimate"] / 60)),
                },
                language=language,
            )

        return on_estimate

    try:
        for row in rows:
            if should_stop is not None and should_stop():
                break
            try:
                info = _process_media(config, dict(row), found, should_stop, announce(row["name"]))
            except Exception as exc:
                _record_failure(writer, result, row, str(exc) or exc.__class__.__name__, language=language)
                continue
            if info is None:
                break
            if info.get("postponed"):
                record_event(
                    conn, "conversion", "warning", "log.conversion.media_postponed",
                    {"name": info["name"]}, language=language,
                )
                continue
            _apply_result(writer, result, info, language=language)
    finally:
        try:
            writer.flush()
        except Exception:
            writer.discard()


def _convert_legacy(conn, config: ProjectConfig, rows, should_stop, result, language) -> None:
    """`.doc`, `.ppt`, `.wpd`… pelo LibreOffice, um por vez, neste processo.

    O componente é baixado aqui, só porque o acervo tem um destes arquivos.
    Sem ele (sem rede, download recusado) ninguém falha: cada arquivo fica
    pendente (`_process_file`), volta à fila na próxima conversão e o log
    diz uma vez o que faltou."""
    soffice = legacy_office.ensure_available(should_stop=should_stop, on_download=_announce_download(conn, language))
    if should_stop is not None and should_stop():
        # Parar no meio do download: os arquivos continuam na fila, sem o
        # aviso de "sem internet", que não seria verdade.
        return
    if soffice is None:
        record_event(
            conn, "conversion", "warning", "log.conversion.component_unavailable",
            {"component": "LibreOffice", "count": len(rows)}, language=language,
        )
    jobs = max(1, _physical_cores() // 2)
    _convert_sequential(conn, config, rows, jobs, should_stop, result, language=language)


# --- idioma do OCR por arquivo (2.0.0) ---------------------------------------------

# Categorias que a passada de detecção abre antes do OCR. As demais da fila
# pesada só viram PDF na conversão e detectam lá (`_detect_in_worker`).
_DETECTABLE_CATEGORIES = frozenset({"pdf", "imagens"})
_DETECT_IN_WORKER_CATEGORIES = frozenset({"paginados", "assinados", LEGACY_CATEGORY})
# Quantos textos de um grupo são lidos para dar o idioma do grupo a um
# escaneado de pouco texto, e quanto de cada um.
_GROUP_SAMPLE_FILES = 5
_GROUP_SAMPLE_CHARS = 4000


def _ensure_models(models: list[str], tesseract: str | None) -> list[str]:
    """`ocr_languages.ensure` para estes modelos; devolve os que faltaram.

    O `ensure` só aponta o Tesseract para a pasta privada quando nada falta;
    com um idioma impossível de baixar, os outros (baixados ali) ficariam
    invisíveis. Por isso, faltando algum, o que veio é garantido de novo, sem
    baixar."""
    from . import ocr_languages

    models = [model for model in dict.fromkeys(models) if model]
    if not models:
        return []
    missing = ocr_languages.ensure("+".join(models), tesseract)
    obtained = [model for model in models if model not in missing]
    if missing and obtained:
        ocr_languages.ensure("+".join(obtained), tesseract, download=False)
    return missing


def _run_detection(config: ProjectConfig, rows: list[dict], present: frozenset[str], osd_ready: bool, should_stop):
    """`ocr_detection.detect_file` de cada linha, no mesmo conjunto guardado da
    conversão (prazo por arquivo, Parar). Um arquivo que falha ou estoura o
    prazo fica sem detecção: vale o idioma do grupo ou do projeto."""
    results: dict[int, dict] = {}
    if not rows:
        return results
    workers = workers_for(config.parallelism)
    if workers <= 1 or len(rows) <= 1:
        factory, workers = DaemonThreadExecutor, 1
    else:
        def factory():
            return ProcessPoolExecutor(max_workers=workers, initializer=no_window.install)

    def submit(executor, row):
        return executor.submit(
            ocr_detection.detect_file, row, config.source_folder, present, osd_ready, MIN_AVG_CHARS_PER_PAGE,
        )

    try:
        with ResilientPool(
            factory, workers, deadline_for=lambda row: deadline_for_size(row["size"]), should_stop=should_stop,
        ) as pool:
            for outcome in pool.run(rows, submit):
                if outcome.kind == OK:
                    results[outcome.item["id"]] = outcome.value
    except PoolStalledError:
        pass
    return results


def _majority(values) -> str | None:
    """O primeiro idioma (ISO) mais frequente entre valores de `file.language`."""
    counts: Counter = Counter()
    for value in values:
        first = (value or "").split(",")[0].strip()
        if first:
            counts[first] += 1
    return counts.most_common(1)[0][0] if counts else None


def _group_language(conn, config: ProjectConfig, group_key: str) -> str | None:
    """O idioma da maioria do grupo: o que já se sabe dos arquivos dele e,
    sem nada, o texto de alguns dos já convertidos (que fica gravado)."""
    known = _majority(
        row[0] for row in conn.execute(
            "SELECT language FROM file WHERE group_key = ? AND language IS NOT NULL AND language != ''",
            (group_key,),
        )
    )
    if known:
        return known
    rows = conn.execute(
        "SELECT id, relative_path, extension, needs_ocr FROM file WHERE group_key = ?"
        " AND status IN ('converted', 'extracted') AND (language IS NULL OR language = '')"
        " ORDER BY relative_path",
        (group_key,),
    ).fetchall()
    found = []
    for row in rows:
        if len(found) >= _GROUP_SAMPLE_FILES:
            break
        if category_of_extension("." + row["extension"]) not in _TEXT_CATEGORIES:
            continue
        intermediate = converted_artifact_path(
            config.output_folder, row["relative_path"], row["extension"], bool(row["needs_ocr"])
        )
        try:
            with open(intermediate, encoding="utf-8", errors="replace") as handle:
                text = handle.read(_GROUP_SAMPLE_CHARS)
        except (OSError, TypeError):
            continue
        detected = language_detect.detect_languages(text)
        if detected:
            value = ",".join(detected)
            conn.execute("UPDATE file SET language = ? WHERE id = ?", (value, row["id"]))
            found.append(value)
    if found:
        conn.commit()
    return _majority(found)


def _fallback_plan(conn, config: ProjectConfig, row, cache: dict) -> str:
    """O idioma de um arquivo de pouco texto (ou cuja detecção não rodou): a
    maioria do grupo, depois a do projeto, e por último `config.ocr_language`
    (que a configuração automática também tira do acervo)."""
    group = row["group_key"]
    iso = None
    if group:
        key = ("group", group)
        if key not in cache:
            cache[key] = _group_language(conn, config, group)
        iso = cache[key]
    if not iso:
        if "project" not in cache:
            cache["project"] = _majority(
                value for (value,) in conn.execute(
                    "SELECT language FROM file WHERE language IS NOT NULL AND language != ''"
                )
            )
        iso = cache["project"]
    models = language_detect.tesseract_languages([iso]) if iso else []
    return "+".join(models) if models else (config.ocr_language or "")


def _decide_plan(raw: dict, fallback: Callable[[], str]) -> tuple[str | None, list[str], bool]:
    """`(plano, idiomas ISO, indisponível)` de um arquivo, pelo que a passada
    pesada achou. Plano `None`: nada a dizer (pouco texto), vale o
    `fallback`. Indisponível: a escrita foi vista mas nenhum modelo dela pôde
    ser obtido para a amostra."""
    native = raw.get("native") or ""
    if native and ocr_detection.native_is_enough(native):
        found = language_detect.detect_languages(native)
        if found:
            return "+".join(language_detect.tesseract_languages(found, native)), found, False
    scripts = raw.get("scripts") or {}
    if not scripts:
        return None, [], False
    pages = raw.get("ocr_pages") or [1]
    groups = ocr_detection.group_pages(pages, scripts)
    samples = raw.get("samples") or {}
    unavailable = False
    found_all: list[str] = []
    planned: list[tuple[list[int], list[str]]] = []
    for script, group in groups.items():
        text = samples.get(script, "")
        found = language_detect.detect_languages(text)
        if found:
            # A amostra de han é lida com o modelo do chinês simplificado, que
            # não escreve os caracteres tradicionais: ela não diz qual das duas
            # formas é, e o OCR final lê com as duas.
            models = language_detect.tesseract_languages(found, "" if script == "han" else text)
            found_all.extend(code for code in found if code not in found_all)
        else:
            if script not in samples:
                unavailable = True
            # Pouco texto na amostra: o idioma do grupo ou do projeto, se for da
            # mesma escrita; senão o modelo da escrita, que lê qualquer idioma
            # dela (um russo num acervo português não é lido em português).
            chosen = fallback()
            same = bool(chosen) and all(
                language_detect.model_script(model) == script for model in chosen.split("+")
            )
            models = chosen.split("+") if same else [language_detect.script_model(script) or ""]
        planned.append((group, [model for model in models if model]))
    if len(planned) == 1:
        return "+".join(planned[0][1]), found_all, unavailable
    return ocr_detection.format_plan(planned), found_all, unavailable


def _plan_languages(conn, config: ProjectConfig, rows, tesseract: str | None, should_stop, language) -> dict[int, dict]:
    """A passada de detecção antes da fila pesada (ver `ocr_detection`).

    Três rodadas de `ensure`, todas antes de o conjunto do OCR nascer (os
    processos herdam o `TESSDATA_PREFIX` ao nascer): o `osd` (já garantido
    com o idioma do projeto, por quem chama), os modelos de escrita que o OSD
    pediu (aqui) e os idiomas achados (por quem chama, na união de todos).
    Grava `file.ocr_lang` (o plano pedido, não o usado: a próxima conversão
    baixa o que faltou) e `file.language` conforme decide."""
    from . import ocr_languages

    candidates = [
        dict(row) for row in rows if category_of_extension("." + row["extension"]) in _DETECTABLE_CATEGORIES
    ]
    if not candidates:
        return {}
    present = ocr_languages.present_models(tesseract) if tesseract else frozenset()
    osd_ready = "osd" in present
    raw = _run_detection(config, candidates, present, osd_ready, should_stop)
    needs = sorted({model for result in raw.values() for model in result["needs"]})
    if needs and not (should_stop is not None and should_stop()):
        _ensure_models(needs, tesseract)
        present = ocr_languages.present_models(tesseract)
        again = [row for row in candidates if raw.get(row["id"], {}).get("needs")]
        raw.update(_run_detection(config, again, present, osd_ready, should_stop))
    still_missing = sorted({model for result in raw.values() for model in result["needs"]})

    cache: dict = {}
    infos: dict[int, dict] = {}
    counted: Counter = Counter()
    detected_files = 0
    unavailable_files = 0
    for row in candidates:
        result = raw.get(row["id"])
        if result is None:
            continue
        info: dict = {}
        if result.get("category") == "imagens":
            info["rotate"] = int((result.get("rotate") or {}).get(1, 0))
        if result.get("ocr_pages") is not None:
            info["ocr_pages"] = result["ocr_pages"]
            info["page_count"] = result["page_count"]
        if row.get("ocr_lang"):
            infos[row["id"]] = info  # plano de uma conversão anterior: vale ele
            continue
        plan, found, unavailable = _decide_plan(result, lambda row=row: _fallback_plan(conn, config, row, cache))
        detected = ",".join(found) or None
        if result.get("ocr_pages") == []:
            plan = None  # nenhuma página para o OCR: só o idioma, para o grupo
        if unavailable:
            info["unavailable"] = True
            unavailable_files += 1
        if plan:
            info["plan"] = plan
        stored_plan = plan if plan and not unavailable else None
        if stored_plan or detected:
            conn.execute(
                "UPDATE file SET ocr_lang = COALESCE(?, ocr_lang), language = COALESCE(?, language) WHERE id = ?",
                (stored_plan, detected, row["id"]),
            )
        if found:
            detected_files += 1
        for code in found:
            counted[code] += 1
        infos[row["id"]] = info
    conn.commit()
    if counted:
        record_event(
            conn, "conversion", "info", "log.conversion.languages_detected",
            {"files": detected_files, "languages": ", ".join(
                f"{code} ({count})" for code, count in counted.most_common()
            )},
            language=language,
        )
    if unavailable_files:
        record_event(
            conn, "conversion", "warning", "log.conversion.language_detection_unavailable",
            {"count": unavailable_files, "models": ", ".join(still_missing)}, language=language,
        )
    return infos


def _prepare_ocr(conn, config: ProjectConfig, heavy, legacy, should_stop, language):
    """Idiomas do OCR antes da fila pesada: a detecção por arquivo
    (`_plan_languages`), a união de tudo o que ela pediu (mais o idioma do
    projeto) baixada de uma vez pelo gerenciador (Tarefa 7), e o plano de
    cada arquivo restrito ao que o Tesseract tem. Devolve as filas como
    dicionários (com o plano de cada linha) e a configuração do resto
    (anexos do Outlook, conteúdo de imagem de um `.p7m`), com o idioma do
    projeto que deu para ter."""
    # The OCR language is installed here if the installer could
    # not (no administrator rights needed), before the OCR workers are
    # started — they inherit this process's `TESSDATA_PREFIX`.
    from . import ocr_languages

    tesseract = tools.find("tesseract")
    project_models = ocr_languages.wanted(config.ocr_language) if config.ocr_language else []
    # O idioma do projeto primeiro (o `ensure` traz o `osd` junto): a passada
    # de detecção precisa do OSD e das línguas já presentes.
    _ensure_models(project_models, tesseract)
    plans = _plan_languages(conn, config, heavy, tesseract, should_stop, language) if heavy else {}

    cache: dict = {}
    rows: list[dict] = []
    for row in list(heavy) + list(legacy):
        item = dict(row)
        info = plans.get(item["id"], {})
        category = category_of_extension("." + item["extension"])
        if info.get("ocr_pages") == [] and not item.get("ocr_lang"):
            plan = None  # todo nativo: sem OCR, nada a baixar para ele
        else:
            plan = item.get("ocr_lang") or info.get("plan") or _fallback_plan(conn, config, item, cache)
        item.update(
            ocr_plan=plan, ocr_short=bool(info.get("unavailable")), image_rotate=info.get("rotate", 0),
            ocr_detect=category in _DETECT_IN_WORKER_CATEGORIES and not item.get("ocr_lang"),
        )
        if "ocr_pages" in info:
            item.update(ocr_pages=info["ocr_pages"], page_count=info["page_count"])
        rows.append(item)

    union = list(project_models)
    for item in rows:
        union.extend(ocr_detection.plan_models(item["ocr_plan"]))
    missing = _ensure_models(union, tesseract)
    # Task 7: a language that could not be downloaded (no network, a
    # refused file) never fails a file. The OCR runs with the languages
    # Tesseract has (none: no OCR), the files that needed it are marked
    # `ocr_failed` and come back on the next conversion, and the log
    # says what was missing. Without Tesseract at all nothing changes:
    # that is an installation problem the About screen reports. Nor
    # when the data folder Tesseract reads cannot be told (no
    # `TESSDATA_PREFIX`, no `tessdata` beside the executable): then
    # `usable` would find nothing and skip OCR that may well work.
    folder_known = bool(tesseract) and ocr_languages.active_folder(tesseract) is not None
    present = ocr_languages.present_models(tesseract) if folder_known else frozenset()
    heavy_config = config
    if missing and folder_known:
        usable = set(ocr_languages.usable("+".join(dict.fromkeys(union)), tesseract))
        heavy_config = replace(config, ocr_language="+".join(m for m in project_models if m in usable))
        # 2.0.0: só os arquivos que pediram o que faltou voltam à fila, não a
        # fila pesada inteira (um idioma raro refaria o acervo todo a cada vez).
        for item in rows:
            item["ocr_plan"], short = ocr_detection.restrict_plan(item["ocr_plan"], usable)
            item["ocr_short"] = item["ocr_short"] or short
        record_event(
            conn, "conversion", "warning", "log.conversion.ocr_language_unavailable",
            {"languages": ", ".join(missing)}, language=language,
        )
    osd_ready = "osd" in present
    usable_models = sorted(present) if folder_known else None
    for item in rows:
        item["ocr_rotate"] = osd_ready
        item["ocr_usable"] = usable_models
    heavy_ids = {row["id"] for row in heavy}
    return (
        [item for item in rows if item["id"] in heavy_ids],
        [item for item in rows if item["id"] not in heavy_ids],
        heavy_config,
    )


def convert(
    conn, config: ProjectConfig, should_stop: Callable[[], bool] | None = None, language: str | None = None
) -> ConversionResult:
    # Covers the sequential path, which runs `pytesseract` (and therefore
    # `tesseract.exe`) inside this very process. The parallel path installs
    # it per worker instead, through the pool's initializer.
    no_window.install()
    # Fase 34: `pytesseract` finds `tesseract.exe` only through this
    # process's `PATH`. The server corrects `PATH` once at start-up, but a
    # conversion started any other way (the test suite, a shell whose
    # `PATH` never got the installer's entry — both seen in practice)
    # failed every image with "tesseract is not installed". Idempotent:
    # a `PATH` already correct is left exactly as it is.
    from . import tools

    tools.ensure_on_path()

    result = ConversionResult()
    workdir.ensure_work_folder(config.output_folder)

    requeue_ocr_failures(conn, language=language)
    _obtain_held_components(conn, should_stop, language)

    rows = conn.execute(
        "SELECT * FROM file WHERE status = 'discovered' ORDER BY relative_path"
    ).fetchall()

    # Two queues. OCR (PDFs, images) is CPU-bound and keeps the
    # per-core pool below; everything else waits on the disk and gets a far
    # larger pool (`parallelism.io_workers_for`). Light files first: they
    # are the bulk of a large collection and show progress at once.
    ocr_rows = [row for row in rows if category_of_extension("." + row["extension"]) in OCR_CATEGORIES]
    # Os formatos antigos formam uma fila própria: o LibreOffice roda um por
    # vez (cada `soffice` ocupa centenas de megabytes), fora do conjunto de
    # processos do OCR.
    legacy = [row for row in ocr_rows if category_of_extension("." + row["extension"]) == LEGACY_CATEGORY]
    legacy_ids = {row["id"] for row in legacy}
    heavy = [row for row in ocr_rows if row["id"] not in legacy_ids]
    # Largest first. In path order a PDF of hundreds of pages could start
    # last and run alone for minutes after every other file was done;
    # started first, it runs alongside the rest.
    heavy.sort(key=lambda row: row["size"] or 0, reverse=True)
    outlook_rows = [row for row in rows if category_of_extension("." + row["extension"]) == OUTLOOK_CATEGORY]
    media_rows = [row for row in rows if category_of_extension("." + row["extension"]) == MEDIA_CATEGORY]
    light = [
        row for row in rows
        if category_of_extension("." + row["extension"]) not in OCR_CATEGORIES | {OUTLOOK_CATEGORY, MEDIA_CATEGORY}
    ]

    if light:
        light_workers = io_workers_for(config.parallelism)
        if light_workers <= 1 or len(light) <= 1:
            _convert_sequential(conn, config, light, 1, should_stop, result, language=language)
        else:
            _convert_in_parallel(conn, config, light, light_workers, 1, should_stop, result, language=language)

    heavy_config = config
    if (heavy or legacy or outlook_rows) and not (should_stop is not None and should_stop()):
        # Depois dos leves: o idioma de um escaneado de pouco texto sai da
        # maioria do grupo, e os textos do grupo já estão convertidos.
        heavy, legacy, heavy_config = _prepare_ocr(conn, config, heavy, legacy, should_stop, language)

    if heavy and not (should_stop is not None and should_stop()):
        _convert_heavy(conn, heavy_config, heavy, should_stop, result, language)

    if legacy and not (should_stop is not None and should_stop()):
        _convert_legacy(conn, heavy_config, legacy, should_stop, result, language)

    if outlook_rows and not (should_stop is not None and should_stop()):
        _convert_outlook(conn, heavy_config, outlook_rows, should_stop, result, language)

    if media_rows and not (should_stop is not None and should_stop()):
        _convert_media(conn, heavy_config, media_rows, should_stop, result, language)

    record_event(
        conn,
        "conversion",
        "info",
        "log.conversion.summary",
        {
            "converted": result.converted, "ocr": result.ocr_applied,
            "failed": result.failed,
        },
        language=language,
    )

    return result

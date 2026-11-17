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
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from email import policy
from pathlib import Path

import fitz  # PyMuPDF

from . import legacy_office, light_formats, no_window, tools, workdir
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
    REASON_BINARY, REASON_COMPONENT_UNAVAILABLE, REASON_SIGNATURE_DETACHED, category_of_extension, looks_binary,
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
    source: Path, destination: Path, ocr_language: str, jobs: int = 1, pages: list[int] | None = None
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


def _extract_text_image(path: Path, ocr_language: str) -> str:
    from PIL import Image
    import pytesseract

    _register_heif()
    with Image.open(path) as image:
        image.load()
        return pytesseract.image_to_string(image, lang=ocr_language)


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


def _ocr_pdf_pages(
    config: ProjectConfig, name: str, source_pdf: Path, destination: Path, ocrmypdf_jobs: int, events: list,
) -> tuple[bool, bool, bool, int]:
    """Decide e faz o OCR das páginas sem texto de um PDF. Devolve
    `(needs_ocr, ocr_failed, ocr_applied, page_count)`. Com OCR feito, o
    resultado está em `destination`; sem ele, nada é escrito lá."""
    ocr_failed = False
    ocr_applied = False
    ocr_pages, page_count = _pdf_pages_needing_ocr(source_pdf)
    needs_ocr = bool(ocr_pages)

    if needs_ocr and not config.ocr_language:
        # Task 7: no OCR language could be had (no network, download
        # refused) — `convert` already warned which one. The native
        # text is read as it is and `ocr_failed` brings the file back
        # once the language is there; the file is never failed for it.
        needs_ocr = False
        ocr_failed = True
    elif needs_ocr:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = len(ocr_pages) < page_count
        try:
            _run_ocrmypdf(
                source_pdf, destination, config.ocr_language, jobs=ocrmypdf_jobs, pages=ocr_pages
            )
        except OcrError as exc:
            # A file with native text used to skip OCR altogether; one
            # failed scanned page must not cost the rest of it. Read the
            # original, as before, and say which pages stayed blank.
            # `ocr_failed` brings it back on the next conversion.
            if not partial:
                raise
            needs_ocr = False
            ocr_failed = True
            events.append((
                "conversion", "warning", "log.conversion.ocr_pages_failed",
                {"name": name, "pages": len(ocr_pages), "total": page_count,
                 "error": str(exc)[:ERROR_MESSAGE_CHAR_LIMIT]},
            ))
        else:
            ocr_applied = True
            if partial:
                events.append((
                    "conversion", "info", "log.conversion.ocr_applied_pages",
                    {"name": name, "pages": len(ocr_pages), "total": page_count,
                     "ocr_language": config.ocr_language},
                ))
            else:
                events.append((
                    "conversion", "info", "log.conversion.ocr_applied",
                    {"name": name, "ocr_language": config.ocr_language},
                ))
    return needs_ocr, ocr_failed, ocr_applied, page_count


def _store_pdf_intermediate(
    config: ProjectConfig, name: str, pdf_bytes: bytes, output_dir: Path, relative_path: str,
    extension: str, ocrmypdf_jobs: int, events: list,
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
        result = _ocr_pdf_pages(config, name, raw, destination, ocrmypdf_jobs, events)
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
            config, row["name"], content, output_dir, relative_path, extension, ocrmypdf_jobs, events
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
    ocr_applied = False
    ocr_failed = False

    if category == "pdf":
        destination = workdir.local_path(output_dir, "converted", relative_path, ".pdf")
        needs_ocr, ocr_failed, ocr_applied, page_count = _ocr_pdf_pages(
            config, name, source_path, destination, ocrmypdf_jobs, events
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
            row["extension"], ocrmypdf_jobs, events,
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
            relative_path, row["extension"], ocrmypdf_jobs, events,
        )
        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (page_count, int(needs_ocr), int(ocr_failed), row["id"])

    elif category == "assinados":
        signed = _convert_signed(config, row, source_path, output_dir, ocrmypdf_jobs, events)
        return {
            "id": row["id"], "name": name, "sql": signed["sql"], "params": signed["params"],
            "events": events, "ocr_applied": signed["ocr_applied"], "signatures": signed["signatures"],
        }

    elif category == "imagens":
        if config.ocr_language:
            text = _extract_text_image(source_path, config.ocr_language)
            ocr_applied = True
            events.append((
                "conversion", "info", "log.conversion.ocr_applied",
                {"name": name, "ocr_language": config.ocr_language},
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
        # Extension with no category ("all" rule), or audio/video chosen
        # through `midia`. Audio and video have no transcriber yet: they stay
        # in the index by name with no text, and are never read here (a film
        # on Google Drive would be downloaded whole for nothing).
        # For the rest, the scan already refused binary content by the first
        # bytes; the check stays here for rows an older version left as
        # `discovered`, but only the start is read to decide — the whole
        # file is read only once it is known to be text.
        if category == "midia":
            text = ""
        else:
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
    }


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
    def op(conn) -> None:
        conn.execute(info["sql"], info["params"])
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


def _ocr_retry_candidates(conn) -> tuple[list, list[str]]:
    """`(rows to requeue, names held back)` — see `requeue_ocr_failures`."""
    has_windows = conn.execute("SELECT 1 FROM window LIMIT 1").fetchone() is not None
    rows = conn.execute(
        "SELECT id, name, status FROM file WHERE ocr_failed = 1"
        " AND (status IN ('converted', 'extracted', 'failed')"
        # Um `skipped` só volta à fila se foi a falta do componente que o
        # deixou assim; o que a varredura recusou (segredo, binário,
        # compactado…) nunca é reaberto por aqui.
        f" OR (status = 'skipped' AND error = '{REASON_COMPONENT_UNAVAILABLE}')) ORDER BY relative_path"
    ).fetchall()
    requeue = [row for row in rows if not (row["status"] == "extracted" and has_windows)]
    held_back = [row["name"] for row in rows if row["status"] == "extracted" and has_windows]
    return requeue, held_back


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


def _convert_legacy(conn, config: ProjectConfig, rows, should_stop, result, language) -> None:
    """`.doc`, `.ppt`, `.wpd`… pelo LibreOffice, um por vez, neste processo.

    O componente é baixado aqui, só porque o acervo tem um destes arquivos.
    Sem ele (sem rede, download recusado) ninguém falha: cada arquivo fica
    pendente (`_process_file`), volta à fila na próxima conversão e o log
    diz uma vez o que faltou."""
    if legacy_office.ensure_available() is None:
        record_event(
            conn, "conversion", "warning", "log.conversion.component_unavailable",
            {"component": "LibreOffice", "count": len(rows)}, language=language,
        )
    jobs = max(1, _physical_cores() // 2)
    _convert_sequential(conn, config, rows, jobs, should_stop, result, language=language)


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
    light = [row for row in rows if category_of_extension("." + row["extension"]) not in OCR_CATEGORIES]

    heavy_config = config
    ocr_shortfall = False
    if heavy or legacy:
        # The OCR language is installed here if the installer could
        # not (no administrator rights needed), before the OCR workers are
        # started — they inherit this process's `TESSDATA_PREFIX`.
        from . import ocr_languages

        tesseract = tools.find("tesseract")
        missing = ocr_languages.ensure(config.ocr_language, tesseract)
        # Task 7: a language that could not be downloaded (no network, a
        # refused file) never fails a file. The OCR runs with the languages
        # Tesseract has (none: no OCR), the files that needed it are marked
        # `ocr_failed` and come back on the next conversion, and the log
        # says what was missing. Without Tesseract at all nothing changes:
        # that is an installation problem the About screen reports. Nor
        # when the data folder Tesseract reads cannot be told (no
        # `TESSDATA_PREFIX`, no `tessdata` beside the executable): then
        # `usable` would find nothing and skip OCR that may well work.
        if missing and tesseract and ocr_languages.active_folder(tesseract) is not None:
            ocr_shortfall = True
            usable = ocr_languages.usable(config.ocr_language, tesseract)
            heavy_config = replace(config, ocr_language="+".join(usable))
            record_event(
                conn, "conversion", "warning", "log.conversion.ocr_language_unavailable",
                {"languages": ", ".join(missing)}, language=language,
            )

    if light:
        light_workers = io_workers_for(config.parallelism)
        if light_workers <= 1 or len(light) <= 1:
            _convert_sequential(conn, config, light, 1, should_stop, result, language=language)
        else:
            _convert_in_parallel(conn, config, light, light_workers, 1, should_stop, result, language=language)

    if heavy and not (should_stop is not None and should_stop()):
        _convert_heavy(conn, heavy_config, heavy, should_stop, result, language)

    if legacy and not (should_stop is not None and should_stop()):
        _convert_legacy(conn, heavy_config, legacy, should_stop, result, language)

    if ocr_shortfall:
        # Read with only part of the languages: good enough for now,
        # done again in full once the rest is downloaded.
        conn.executemany(
            "UPDATE file SET ocr_failed = 1 WHERE id = ? AND status = 'converted' AND needs_ocr = 1",
            [(row["id"],) for row in heavy + legacy],
        )
        conn.commit()

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

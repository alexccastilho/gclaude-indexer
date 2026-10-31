# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Conversion by type, OCR, and slicing of large PDFs (section 5, steps 2 and 3).

Every file with `status = "discovered"` is processed once. The original is
never read for writing nor altered — all output (OCR'd PDF, sliced blocks,
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
from dataclasses import dataclass
from email import policy
from pathlib import Path

import fitz  # PyMuPDF

from . import no_window, tools, workdir
from .config import ProjectConfig
from .db import BatchWriter
from .events import record_event
from .i18n import DEFAULT_LANGUAGE, translate
from .worker_pool import (
    ERROR, OK, TIMED_OUT, DaemonThreadExecutor, PoolStalledError, ResilientPool, StepStalledError,
    deadline_for_size,
)
from .parallelism import _physical_cores, io_workers_for, workers_for
from .file_types import category_of_extension
from .html_text import STRUCK_MARK, html_to_text, looks_like_html, mark_struck
from .text_decoding import decode_bytes, decode_markup

MIN_AVG_CHARS_PER_PAGE = 100
# 1.5.9: how much of an unknown-extension file is checked for a NUL byte.
_BINARY_SNIFF_BYTES = 8192
# Categories whose conversion may run OCR — the CPU-bound queue (1.5.8).
OCR_CATEGORIES = frozenset({"pdf", "imagens"})
ERROR_MESSAGE_CHAR_LIMIT = 500


@dataclass
class ConversionResult:
    converted: int = 0
    ocr_applied: int = 0
    sliced: int = 0
    blocks_generated: int = 0
    failed: int = 0


class ConversionError(Exception):
    """Failure converting a file. The message must not contain document content."""


class OcrError(ConversionError):
    """`ocrmypdf` itself failed (1.5.7). Kept apart from every other
    conversion failure because it is the one worth trying again: a file
    that failed this way gets `file.ocr_failed = 1` and goes back to the
    queue at the start of the next conversion (`requeue_ocr_failures`),
    while a corrupt or password-protected file stays failed."""


def _destination_path(output_dir: Path, subfolder: str, relative_path: str, new_extension: str) -> Path:
    # 1.5.8: in the per-machine work folder, never in the (Drive-synced)
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
    category = category_of_extension("." + extension.lstrip("."))
    if category == "pdf":
        if not needs_ocr:
            return None
        return workdir.intermediate_path(output_folder, "converted", relative_path, ".pdf")
    return workdir.intermediate_path(output_folder, "converted", relative_path, ".txt")


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
        # 1.5.7: a plain PDF, not PDF/A. The copy is only read for its text,
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


def slice_pdf(source_path: Path, destination_dir: Path, base_name: str, pages_per_block: int) -> list[Path]:
    """Cuts `source_path` into blocks of at most `pages_per_block` pages.

    Block name: `<base>_p<start>-<end>.pdf`, preserving the real (1-based)
    page numbering of the source document in the name.
    """
    document = fitz.open(source_path)
    try:
        page_count = document.page_count
        blocks: list[Path] = []

        for start in range(0, page_count, pages_per_block):
            end = min(start + pages_per_block, page_count) - 1
            start_1based = start + 1
            end_1based = end + 1

            block = fitz.open()
            block.insert_pdf(document, from_page=start, to_page=end)
            destination_dir.mkdir(parents=True, exist_ok=True)
            block_path = destination_dir / f"{base_name}_p{start_1based}-{end_1based}.pdf"
            block.save(block_path)
            block.close()
            blocks.append(block_path)

        return blocks
    finally:
        document.close()


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
    from docx import Document

    document = Document(path)
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
    from pptx import Presentation

    presentation = Presentation(path)
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


def _message_part_text(part) -> str:
    """Text of one MIME part. Decodes the bytes itself instead of calling
    `get_content()`, which raises `LookupError` on a charset label Python
    does not know — a common sight in old mail — and would fail the file."""
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset()
    if part.get_content_type() == "text/html":
        text, _ = decode_markup(payload, charset)
        return html_to_text(text)
    return decode_bytes(payload, charset)[0]


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


def _extract_text_image(path: Path, ocr_language: str) -> str:
    from PIL import Image
    import pytesseract

    with Image.open(path) as image:
        image.load()
        return pytesseract.image_to_string(image, lang=ocr_language)


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
    sliced = False
    blocks_generated = 0

    if category == "pdf":
        ocr_pages, page_count = _pdf_pages_needing_ocr(source_path)
        needs_ocr = bool(ocr_pages)
        path_to_slice = source_path

        if needs_ocr:
            ocr_destination = _destination_path(output_dir, "converted", relative_path, ".pdf")
            partial = len(ocr_pages) < page_count
            try:
                _run_ocrmypdf(
                    source_path, ocr_destination, config.ocr_language, jobs=ocrmypdf_jobs, pages=ocr_pages
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
                path_to_slice = ocr_destination
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

        if page_count > config.pages_per_block:
            blocks_dir = workdir.work_folder(output_dir) / "blocks" / Path(relative_path).parent
            blocks = slice_pdf(path_to_slice, blocks_dir, Path(relative_path).stem, config.pages_per_block)
            sliced = True
            blocks_generated = len(blocks)
            events.append((
                "conversion", "info", "log.conversion.sliced", {"name": name, "blocks": len(blocks)},
            ))

        sql = (
            "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
            " ocr_failed = ? WHERE id = ?"
        )
        params = (page_count, int(needs_ocr), int(ocr_failed), row["id"])

    elif category == "imagens":
        text = _extract_text_image(source_path, config.ocr_language)
        destination = _destination_path(output_dir, "converted", relative_path, ".txt")
        destination.write_text(text, encoding="utf-8")
        ocr_applied = True
        events.append((
            "conversion", "info", "log.conversion.ocr_applied",
            {"name": name, "ocr_language": config.ocr_language},
        ))
        sql = "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 1 WHERE id = ?"
        params = (row["id"],)

    elif category in ("docx", "xlsx", "pptx", "text", "web_dados", "email"):
        extension = row["extension"]
        if category == "docx":
            text = _extract_text_docx(source_path)
        elif category == "xlsx":
            text = _extract_text_xlsx(source_path)
        elif category == "pptx":
            text = _extract_text_pptx(source_path)
        elif category == "web_dados":
            text = _extract_text_web(source_path, extension)
        elif category == "text":
            text = decode_bytes(source_path.read_bytes())[0]
        elif extension == "msg":
            text = _extract_text_msg(source_path)
        else:
            text = _extract_text_eml(source_path)

        destination = _destination_path(output_dir, "converted", relative_path, ".txt")
        destination.write_text(text, encoding="utf-8")
        sql = "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 0 WHERE id = ?"
        params = (row["id"],)

    else:
        # Only reached with the special "all" category selected (explicit
        # user request: index any non-binary/executable extension, even
        # without a dedicated extractor). Reads as text, best-effort — never
        # fails on a binary file with no extractor; worst case it produces a
        # low-quality result, not an error.
        data = source_path.read_bytes()
        # 1.5.9: a NUL byte near the start means a binary file (zip, mp3,
        # font, CAD drawing…), not text in an unknown extension. Read as
        # text it became a page of control characters that went into the
        # search and into classification summaries (31/10/2026: 22 such
        # pages). It stays in the index, by name, with no text.
        text = "" if b"\x00" in data[:_BINARY_SNIFF_BYTES] else decode_bytes(data)[0]
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
        "sliced": sliced,
        "blocks_generated": blocks_generated,
    }


def _apply_result(writer: BatchWriter, result: ConversionResult, info: dict, language: str | None = None) -> None:
    def op(conn) -> None:
        conn.execute(info["sql"], info["params"])
        for step, level, key, params in info["events"]:
            record_event(conn, step, level, key, params, language=language, commit=False)

    writer.add(op)
    result.converted += 1
    result.ocr_applied += int(info["ocr_applied"])
    result.sliced += int(info["sliced"])
    result.blocks_generated += info["blocks_generated"]


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

    1.5.6: under the same `ResilientPool` as the parallel path, with a
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

    1.5.5: `ResilientPool` (see `worker_pool.py`) instead of a bare
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
            # pool down with it (I3, Phase 13 final review). The pool is
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
        " AND status IN ('converted', 'extracted', 'failed') ORDER BY relative_path"
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
    'discovered', so this conversion tries it again (1.5.7). Only OCR
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


def convert(
    conn, config: ProjectConfig, should_stop: Callable[[], bool] | None = None, language: str | None = None
) -> ConversionResult:
    # Covers the sequential path, which runs `pytesseract` (and therefore
    # `tesseract.exe`) inside this very process. The parallel path installs
    # it per worker instead, through the pool's initializer.
    no_window.install()

    result = ConversionResult()
    workdir.ensure_work_folder(config.output_folder)

    requeue_ocr_failures(conn, language=language)

    rows = conn.execute(
        "SELECT * FROM file WHERE status = 'discovered' ORDER BY relative_path"
    ).fetchall()

    # 1.5.8: two queues. OCR (PDFs, images) is CPU-bound and keeps the
    # per-core pool below; everything else waits on the disk and gets a far
    # larger pool (`parallelism.io_workers_for`). Light files first: they
    # are the bulk of a large collection and show progress at once.
    heavy = [row for row in rows if category_of_extension("." + row["extension"]) in OCR_CATEGORIES]
    # 1.5.9: largest first. In path order an 809-page PDF started last
    # and ran alone for six minutes after every other file was done
    # (31/10/2026); started first, it runs alongside the rest.
    heavy.sort(key=lambda row: row["size"] or 0, reverse=True)
    light = [row for row in rows if category_of_extension("." + row["extension"]) not in OCR_CATEGORIES]

    if light:
        light_workers = io_workers_for(config.parallelism)
        if light_workers <= 1 or len(light) <= 1:
            _convert_sequential(conn, config, light, 1, should_stop, result, language=language)
        else:
            _convert_in_parallel(conn, config, light, light_workers, 1, should_stop, result, language=language)

    if heavy and not (should_stop is not None and should_stop()):
        _convert_heavy(conn, config, heavy, should_stop, result, language)

    record_event(
        conn,
        "conversion",
        "info",
        "log.conversion.summary",
        {
            "converted": result.converted, "ocr": result.ocr_applied,
            "sliced": result.sliced, "blocks": result.blocks_generated, "failed": result.failed,
        },
        language=language,
    )

    return result

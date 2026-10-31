# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Per-page extraction (section 5, step 4).

For each already-converted file, reads the text of each page (from the
final PDF — original or OCR'd — or from the `.txt` extracted in phase 3 for
the other formats), writes it to `page` with the text truncated at the
configured limit, character count, image count, and table detection.

Each page's citable reference follows the collection type:
- `processo`: "f. N", with N counting the document's real numbering — a
  running sum of pages across all files of the same group, in the order
  they appear (natural ordering by relative path).
- `biblioteca`: "p. N", restarting at 1 for each file.

Resumable: a file with `status = "extracted"` already has its pages written
and is skipped, but still counts toward the group's page tally so that the
following files keep numbering correctly.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .config import ProjectConfig
from .db import BatchWriter
from .events import record_event
from .i18n import DEFAULT_LANGUAGE, translate
from .worker_pool import (
    ERROR, OK, TIMED_OUT, DaemonThreadExecutor, PoolStalledError, ResilientPool, StepStalledError,
    deadline_for_size,
)
from .parallelism import workers_for
from .file_types import category_of_extension
from .fulltext import index_pending
from .paths import natural_sort_key

ERROR_MESSAGE_CHAR_LIMIT = 500


@dataclass
class ExtractionResult:
    files_processed: int = 0
    pages_written: int = 0
    failed: int = 0


def _read_pdf_pages(pdf_path: Path, limit: int) -> list[tuple[str, int, bool]]:
    document = fitz.open(pdf_path)
    try:
        pages = []
        for page in document:
            text = page.get_text()[:limit]
            image_count = len(page.get_images(full=True))
            try:
                has_table = len(page.find_tables().tables) > 0
            except Exception:
                has_table = False
            pages.append((text, image_count, has_table))
        return pages
    finally:
        document.close()


def _docx_has_table(path: Path) -> bool:
    from docx import Document

    return len(Document(path).tables) > 0


def _extract_file_pages(config: ProjectConfig, row) -> list[tuple[str, int, bool]]:
    # Truncate here, in the worker, not only in `_write_pages`: on the
    # parallel path the return value crosses `pickle` to the main process,
    # and without truncating first the **full** text of every page stayed in
    # RAM (and was serialized whole) until it was written — for a large
    # collection that's the entire collection's text in memory at once (I2,
    # Phase 13 final review). The sequential path never had this problem
    # (one file at a time), but truncates here too, at no extra cost.
    limit = config.chars_per_page
    category = category_of_extension("." + row["extension"])
    relative_path = row["relative_path"]
    output_dir = Path(config.output_folder)

    if category == "pdf":
        if row["needs_ocr"]:
            pdf_path = output_dir / "converted" / Path(relative_path).with_suffix(".pdf")
        else:
            pdf_path = Path(config.source_folder) / relative_path
        return _read_pdf_pages(pdf_path, limit)

    txt_path = output_dir / "converted" / Path(relative_path).with_suffix(".txt")
    text = txt_path.read_text(encoding="utf-8")[:limit]

    if category == "imagens":
        return [(text, 1, False)]
    if category == "xlsx":
        return [(text, 0, True)]
    if category == "docx":
        has_table = _docx_has_table(Path(config.source_folder) / relative_path)
        return [(text, 0, has_table)]
    return [(text, 0, False)]  # pptx, texto, email


def _write_pages(conn, config: ProjectConfig, row, pages: list[tuple[str, int, bool]], start_sheet: int) -> int:
    limit = config.chars_per_page
    library = config.collection_type == "biblioteca"
    sheet = start_sheet

    for index, (full_text, image_count, has_table) in enumerate(pages, start=1):
        sheet += 1
        truncated_text = full_text[:limit]
        reference = f"p. {index}" if library else f"f. {sheet}"

        conn.execute(
            """
            INSERT INTO page
                (file_id, number, reference, char_count, image_count, has_table, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], index, reference, len(truncated_text), image_count, int(has_table), truncated_text),
        )

    return sheet


def _page_row_count(conn, file_id: int) -> int:
    """Pages a file really has, counted from the `page` table.

    Never `file.page_count`. The column and the rows disagree in ordinary
    operation — `conversion` writes the count and a later extraction
    failure leaves it behind with zero rows; a re-scan nulls it without
    deleting the rows — and the whole of the incremental update reads
    page rows for exactly that reason (see
    `update_plan._stored_geometry`). The head of a group decides every
    `f. N` in the re-extracted tail, so measuring it with the column
    would silently number the tail from a total the pages never had.
    """
    return conn.execute(
        "SELECT COUNT(*) FROM page WHERE file_id = ?", (file_id,)
    ).fetchone()[0]


def _build_groups(conn) -> dict[str, list]:
    rows = conn.execute(
        "SELECT * FROM file WHERE status IN ('converted', 'extracted') ORDER BY relative_path"
    ).fetchall()

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        group_key = row["group_key"] or f"__no_group__{row['id']}"
        groups[group_key].append(row)

    for group_files in groups.values():
        group_files.sort(key=lambda r: natural_sort_key(r["relative_path"]))

    return groups


def _extract_sequential(
    conn, config: ProjectConfig, groups: dict[str, list], should_stop, result, language: str | None = None
) -> bool:
    """Economy mode and single files: one file at a time, in this process.

    1.5.6: the parallel path's machinery with one `DaemonThreadExecutor`
    thread (see `conversion._convert_sequential`). One worker returns
    results in submission order, so the per-group sheet numbering is the
    same as walking the groups by hand."""
    return _extract_guarded(conn, config, groups, 1, should_stop, result, language, DaemonThreadExecutor)


def _queue_failure(writer: BatchWriter, row, error_message: str, result: ExtractionResult, language) -> None:
    error_message = error_message[:ERROR_MESSAGE_CHAR_LIMIT]

    def op(conn) -> None:
        conn.execute(
            "UPDATE file SET status = 'failed', error = ? WHERE id = ?",
            (error_message, row["id"]),
        )
        record_event(
            conn, "extraction", "error", "log.extraction.failed",
            {"name": row["name"], "error": error_message}, language=language, commit=False,
        )

    writer.add(op)
    result.failed += 1


def _queue_pages(writer: BatchWriter, config: ProjectConfig, row, pages, start_sheet: int, result) -> int:
    """Writes a file's pages through the batch and returns the group's next
    sheet. The sheet is computed here, not read back from the database, so
    a batch replayed after a locked database numbers exactly as before."""

    def op(conn) -> None:
        _write_pages(conn, config, row, pages, start_sheet)
        conn.execute("UPDATE file SET status = 'extracted' WHERE id = ?", (row["id"],))

    writer.add(op)
    result.files_processed += 1
    result.pages_written += len(pages)
    return start_sheet + len(pages)


def _extract_in_parallel(
    conn, config: ProjectConfig, groups: dict[str, list], workers: int, should_stop, result,
    language: str | None = None,
) -> bool:
    return _extract_guarded(
        conn, config, groups, workers, should_stop, result, language,
        lambda: ProcessPoolExecutor(max_workers=workers),
    )


def _extract_guarded(
    conn, config: ProjectConfig, groups: dict[str, list], workers: int, should_stop, result,
    language: str | None, executor_factory: Callable[[], object],
) -> bool:
    """Page reading (PDF/tables — the CPU/IO-heavy part) runs in separate
    processes, one file per worker. Sheet numbering ("f. N") depends on file
    order within each group, so writing a file can only happen after every
    earlier file in the same group has been written.

    This doesn't require waiting for the whole collection to finish
    computing before writing anything (I1, Phase 13 final review): we keep,
    per group, a "next position to apply" pointer and a buffer of results
    already done out of order. Each result is applied (written and
    committed) as soon as its turn comes — the progress bar, which counts
    `status = 'extracted'`, starts moving during computation, not only at
    the end.

    `sqlite3.Connection` never crosses a process boundary: workers only read
    files from disk and return `list[tuple[str, int, bool]]`; the one that
    always writes to the database is this main process.

    1.5.5: `ResilientPool` (see `worker_pool.py`) instead of a bare
    `with ProcessPoolExecutor(...)`, and `BatchWriter` instead of one commit
    per file. "Applied as soon as its turn comes" now means queued in the
    batch, which commits at least once a second.
    """
    current_position: dict[str, int] = {key: 0 for key in groups}
    current_sheet: dict[str, int] = {key: 0 for key in groups}
    ready: dict[str, dict[int, tuple[str, object]]] = {key: {} for key in groups}
    writer = BatchWriter(conn)

    def _apply_ready(group_key: str) -> None:
        group_files = groups[group_key]
        while current_position[group_key] < len(group_files):
            index = current_position[group_key]
            row = group_files[index]

            if row["status"] == "extracted":
                current_sheet[group_key] += _page_row_count(conn, row["id"])
                current_position[group_key] += 1
                continue

            item = ready[group_key].pop(index, None)
            if item is None:
                return  # not here yet — retry when the next result arrives

            kind, value = item
            if kind == "error":
                _queue_failure(writer, row, str(value), result, language)
            else:
                current_sheet[group_key] = _queue_pages(
                    writer, config, row, value, current_sheet[group_key], result
                )

            current_position[group_key] += 1

    pending = [
        (group_key, index, row)
        for group_key, group_files in groups.items()
        for index, row in enumerate(group_files)
        if row["status"] != "extracted"
    ]

    crash_reported = False

    def on_restart(reason: str, item) -> None:
        nonlocal crash_reported
        if reason == "stalled":
            row = item[2]
            writer.add(lambda c: record_event(
                c, "extraction", "warning", "log.worker_restarted",
                {"name": row["name"], "minutes": _minutes(deadline_for_size(row["size"]))},
                language=language, commit=False,
            ))
        elif not crash_reported:
            # A worker died (e.g. `MemoryError` on a large PDF) and took the
            # pool down with it (I3, Phase 13 final review). The pool is
            # rebuilt and its files tried again; a file caught in two crashes
            # gets no result, which stalls its group right there and keeps
            # the original status ('converted') for the next run.
            crash_reported = True
            writer.add(lambda c: record_event(
                c, "extraction", "error", "log.pool_broken", language=language, commit=False,
            ))

    def submit(executor, item):
        return executor.submit(_extract_file_pages, config, dict(item[2]))

    try:
        with ResilientPool(
            executor_factory,
            workers,
            deadline_for=lambda item: deadline_for_size(item[2]["size"]),
            should_stop=should_stop,
            on_restart=on_restart,
            on_idle=writer.flush_if_due,
        ) as pool:
            for outcome in pool.run(pending, submit):
                group_key, index, _row = outcome.item
                if outcome.kind == OK:
                    ready[group_key][index] = ("ok", outcome.value)
                elif outcome.kind == ERROR:
                    ready[group_key][index] = ("error", outcome.value)
                elif outcome.kind == TIMED_OUT:
                    message = translate(
                        language or DEFAULT_LANGUAGE, "error.file_timed_out", minutes=_minutes(outcome.value)
                    )
                    ready[group_key][index] = ("error", message)
                else:
                    continue  # CRASHED: see `on_restart`
                _apply_ready(group_key)
        writer.flush()
    except PoolStalledError as exc:
        row = exc.item[2]
        writer.add(lambda c: record_event(
            c, "extraction", "error", "log.pool_stalled", {"name": row["name"]}, language=language, commit=False,
        ))
        writer.flush()
        raise StepStalledError(
            translate(language or DEFAULT_LANGUAGE, "log.pool_stalled", name=row["name"])
        ) from exc
    except BaseException as exc:
        if isinstance(exc, sqlite3.Error):
            writer.discard()
        else:
            try:
                writer.flush()
            except Exception:
                writer.discard()
        raise

    return any(current_position[key] < len(groups[key]) for key in groups)


def _minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def extract_pages(
    conn, config: ProjectConfig, should_stop: Callable[[], bool] | None = None, language: str | None = None
) -> ExtractionResult:
    groups = _build_groups(conn)
    result = ExtractionResult()

    workers = workers_for(config.parallelism)
    n_pending = sum(
        1 for group_files in groups.values() for row in group_files if row["status"] != "extracted"
    )
    # With 0 or 1 file pending there's nothing to parallelize — the
    # `ProcessPoolExecutor` startup cost (spawn, on Windows) outweighs any
    # gain.
    if workers <= 1 or n_pending <= 1:
        interrupted = _extract_sequential(conn, config, groups, should_stop, result, language=language)
    else:
        interrupted = _extract_in_parallel(conn, config, groups, workers, should_stop, result, language=language)

    summary_key = "log.extraction.summary_interrupted" if interrupted else "log.extraction.summary_completed"
    record_event(
        conn,
        "extraction",
        "info",
        summary_key,
        {"files": result.files_processed, "pages": result.pages_written, "failed": result.failed},
        language=language,
    )

    # The full text, untruncated, goes into the search (`fulltext.py`). Also
    # picks up files extracted by a version that had no search, or by a run
    # interrupted here — whatever is extracted and not yet indexed.
    if not interrupted:
        index_pending(conn, config, should_stop=should_stop, language=language)

    return result

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Life cycle of `file.status` and `window.status`: the values, the named
sets the steps select by, and the SQL of each transition.

The strings are stored in `project.db` (no `CHECK` in the schema), so they
are a recorded contract: never rename a value. A new status starts here, and
every set below has to be looked at for it.

    discovered --conversion--> converted --extraction--> extracted
         |                         |                         ^
         +--> failed / skipped     +--> failed               | (pages written)
    duplicate: a copy of a file already in the index (scan only)
    skipped:   left out by the scan, or by the conversion (see `error`)

A window is `pending` until an engine answers it, then `done`.

`tests/test_file_status.py` fails when a status literal appears in SQL or
in a status comparison anywhere else in the package. Elsewhere a status
reaches SQL as a `?` parameter (`in_params` for sets), never formatted in.
"""

from __future__ import annotations

from collections.abc import Iterable

from .file_types import REASON_COMPONENT_UNAVAILABLE

# --- file.status -------------------------------------------------------------

DISCOVERED = "discovered"
CONVERTED = "converted"
EXTRACTED = "extracted"
FAILED = "failed"
DUPLICATE = "duplicate"
SKIPPED = "skipped"

# Every value, in the order `review.md` lists them.
ALL_FILE_STATUSES: tuple[str, ...] = (DISCOVERED, CONVERTED, EXTRACTED, FAILED, DUPLICATE, SKIPPED)

# There is an intermediate in `converted/` to read text from (extraction's
# queue, the language sample of a group).
HAS_INTERMEDIATE: tuple[str, ...] = (CONVERTED, EXTRACTED)
# The conversion read the document without error: the "converted" figure of
# the Execution card, the document count of the instructions, the files the
# `ocr_failed` migration may flag.
CONVERSION_SUCCEEDED: tuple[str, ...] = (CONVERTED, EXTRACTED)
# The conversion is done with the file, well or not (progress bar numerator,
# files whose `ocr_failed` the OCR retry looks at).
CONVERSION_FINISHED: tuple[str, ...] = (CONVERTED, EXTRACTED, FAILED)
# The extraction is done with the file (progress bar numerator).
EXTRACTION_FINISHED: tuple[str, ...] = (EXTRACTED,)
# Not a document of the index: ignored by name/content or a copy.
OUT_OF_INDEX: tuple[str, ...] = (SKIPPED, DUPLICATE)
# Still waiting for a pipeline step (the "update first" warning).
AWAITING_PROCESSING: tuple[str, ...] = (DISCOVERED, CONVERTED)
# Page rows of a file in these statuses are not leftovers: `extracted` wrote
# them, `duplicate` is never read (`update_plan.stale_page_paths`).
STALE_PAGES_EXEMPT: tuple[str, ...] = (EXTRACTED, DUPLICATE)

# --- window.status -----------------------------------------------------------

WINDOW_PENDING = "pending"
WINDOW_DONE = "done"

def in_params(statuses: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """`("?, ?", (a, b))`: the marks for `status IN (...)` and the values to
    pass as parameters, in the same order."""
    values = tuple(statuses)
    return ", ".join("?" for _ in values), values


# --- waiting for a component -------------------------------------------------
# Not a status of its own: `skipped` plus `error = REASON_COMPONENT_UNAVAILABLE`.
# One rule for the scan, the conversion and the update plan.

# With WAITING_COMPONENT_PARAMS, in this order.
WAITING_COMPONENT_SQL = "(status = ? AND error = ?)"
WAITING_COMPONENT_PARAMS: tuple[str, str] = (SKIPPED, REASON_COMPONENT_UNAVAILABLE)


def is_waiting_component(status: str | None, error: str | None) -> bool:
    """O arquivo espera um componente (LibreOffice, ffmpeg/whisper) que
    faltava quando a conversão chegou a ele (o mesmo que
    `WAITING_COMPONENT_SQL`)."""
    return status == SKIPPED and error == REASON_COMPONENT_UNAVAILABLE


# --- transitions ---------------------------------------------------------------
# Plain literals (this module owns the values); parameters in the order of the
# `?`. Variants that differ in what they write keep separate names: merging them
# would change behavior.

# (page_count, needs_ocr, ocr_failed, id): PDF, paged, legacy, signed PDF.
MARK_CONVERTED = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = ?,"
    " ocr_failed = ? WHERE id = ?"
)
# (needs_ocr, ocr_failed, id): signed content read as text.
MARK_CONVERTED_ONE_PAGE = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = ?,"
    " ocr_failed = ? WHERE id = ?"
)
# (ocr_failed, id): an image, always one page read by OCR.
MARK_CONVERTED_IMAGE = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 1,"
    " ocr_failed = ? WHERE id = ?"
)
# (page_count, id): text formats and Outlook; `ocr_failed` is left as it was.
MARK_CONVERTED_TEXT_KEEP_OCR_FLAG = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = 0 WHERE id = ?"
)
# (id): extension with no category, one page; `ocr_failed` is left as it was.
MARK_CONVERTED_PLAIN_KEEP_OCR_FLAG = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = 1, needs_ocr = 0 WHERE id = ?"
)
# (page_count, id): audio/video transcript; clears `ocr_failed` (the retry flag
# a missing component had set).
MARK_CONVERTED_TEXT_CLEAR_OCR_FLAG = (
    "UPDATE file SET status = 'converted', error = NULL, page_count = ?, needs_ocr = 0,"
    " ocr_failed = 0 WHERE id = ?"
)

# (error, id): the conversion refused the file for good.
MARK_SKIPPED = (
    "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0,"
    " ocr_failed = 0 WHERE id = ?"
)
# (error, id): a component was missing; `ocr_failed = 1` puts it back in the
# queue (`conversion.requeue_ocr_failures`). The error is always
# REASON_COMPONENT_UNAVAILABLE (`WAITING_COMPONENT_SQL`).
MARK_SKIPPED_FOR_RETRY = (
    "UPDATE file SET status = 'skipped', error = ?, page_count = NULL, needs_ocr = 0,"
    " ocr_failed = 1 WHERE id = ?"
)

# (error, ocr_failed, id)
MARK_CONVERSION_FAILED = "UPDATE file SET status = 'failed', error = ?, ocr_failed = ? WHERE id = ?"
# (error, id): `ocr_failed` is left as the conversion set it.
MARK_EXTRACTION_FAILED = "UPDATE file SET status = 'failed', error = ? WHERE id = ?"
# (id)
MARK_EXTRACTED = "UPDATE file SET status = 'extracted' WHERE id = ?"

# Back to `discovered`. The copies differ on purpose (decisoes.md: merging is
# a behavior change), each says what it clears:
# (id): OCR retry and missing intermediate; keeps `ocr_lang`/`language`.
RESET_TO_DISCOVERED_KEEP_LANGUAGE = (
    "UPDATE file SET status = 'discovered', page_count = NULL, error = NULL WHERE id = ?"
)
# (id): content changed; the language was the old bytes', so it goes too.
RESET_TO_DISCOVERED_CLEAR_LANGUAGE = (
    "UPDATE file SET status = 'discovered', page_count = NULL,"
    " error = NULL, ocr_lang = NULL, language = NULL WHERE id = ?"
)
# (status, id): renumbering, to CONVERTED or DISCOVERED; keeps the language.
RESET_FOR_RENUMBER = "UPDATE file SET status = ?, page_count = NULL, error = NULL WHERE id = ?"

# (id): an engine answered the window.
MARK_WINDOW_DONE = "UPDATE window SET status = 'done' WHERE id = ?"

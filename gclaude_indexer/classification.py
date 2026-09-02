# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Common classification interface (spec section 5, step 6).

Every classification engine — `rules`, `local`, `claude_code` — receives the
text of one window and returns the same item structure, so that the import
step (phase 6) does not need to know which engine ran. This module defines
that common structure and the validation required by section 7 before any
item is written.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

VALID_ENGINES = {"rules", "local", "claude_code"}
VALID_CONFIDENCES = {"high", "medium", "low"}


@dataclass
class WindowPage:
    """One page inside a window — what the engines receive as input.
    `text` is already the truncated text written in phase 4."""

    reference: str
    file_name: str
    text: str
    has_table: bool
    image_count: int


@dataclass
class ClassifiedItem:
    """Output structure common to every engine — same shape as the `item`
    table (minus `id`/`group`, filled in by whoever orchestrates)."""

    start_ref: str
    end_ref: str
    start_order: int
    end_order: int
    type: str | None
    date: str | None
    author: str | None
    summary: str | None
    has_table: bool
    has_image: bool
    engine: str
    confidence: str
    files: list[str] = field(default_factory=list)


class ClassificationEngine(Protocol):
    """Single interface every classification engine implements."""

    def classify(self, pages: list[WindowPage]) -> list[ClassifiedItem]: ...


def reference_number(reference: str) -> int:
    """Extracts the numeric part of a reference ('f. 178' -> 178)."""
    match = re.search(r"(\d+)\s*$", reference)
    return int(match.group(1)) if match else 0


def load_window_pages(conn: sqlite3.Connection, window_row: sqlite3.Row) -> list[WindowPage]:
    """Rebuilds, from the database, exactly the pages that make up a
    window — the same slice used to write the `.txt` in phase 4."""
    from .windows_prep import pages_for_group  # late import avoids a cycle

    start, end = _key_positions(window_row["key"])
    all_pages = pages_for_group(conn, window_row["group_key"])
    block = all_pages[start - 1 : end]

    return [
        WindowPage(
            reference=row["reference"],
            file_name=row["file_name"],
            text=row["text"],
            has_table=bool(row["has_table"]),
            image_count=row["image_count"],
        )
        for row in block
    ]


def _key_positions(key: str) -> tuple[int, int]:
    match = re.search(r"::(\d+)-(\d+)$", key)
    if not match:
        raise ValueError(f"chave de janela em formato inesperado: {key!r}")
    return int(match.group(1)), int(match.group(2))


# Words a model sometimes returns instead of leaving `type` empty. Stored
# as-is they become their own document type in the index, sitting next to
# the real ones and inflating the "types found" count with nothing.
_EMPTY_TYPES = {"NULL", "NONE", "N/A", "NA", "-", "--", "?", "DESCONHECIDO", "INDEFINIDO", "SEM TIPO"}


def normalize_type(type_: object) -> str | None:
    """Canonical form of a document type, or `None`.

    Upper-cased and stripped, because a model is not consistent about case
    across windows: a real collection came back with both `ÍNDICE` and
    `Índice`, which the index then listed as two different kinds of
    document and the quality report counted twice. Case is not information
    here — the type is a label, and two labels differing only in case are
    the same label.
    """
    if not isinstance(type_, str):
        return None
    cleaned = " ".join(type_.split()).upper()
    if not cleaned or cleaned in _EMPTY_TYPES:
        return None
    return cleaned


def item_to_dict(item: ClassifiedItem, window_key: str, group: str) -> dict:
    return {
        "window": window_key,
        "group": group,
        "ref_start": item.start_ref,
        "ref_end": item.end_ref,
        "order_start": item.start_order,
        "order_end": item.end_order,
        "type": normalize_type(item.type),
        "date": item.date,
        "author": item.author,
        "summary": item.summary,
        "has_table": bool(item.has_table),
        "has_image": bool(item.has_image),
        "engine": item.engine,
        "confidence": item.confidence,
        "files": ", ".join(item.files),
    }


_ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_item(item: dict) -> list[str]:
    """Field-by-field validation required by section 7 before writing an
    item: type, range within the group, plausible ISO date. Returns the
    list of problems found (empty if valid)."""
    errors: list[str] = []

    if not item.get("group"):
        errors.append("agrupador ausente")

    if not item.get("ref_start") or not item.get("ref_end"):
        errors.append("ref_inicial/ref_final ausente")

    if not item.get("files"):
        errors.append("arquivos ausente")

    order_start = item.get("order_start")
    order_end = item.get("order_end")
    if not isinstance(order_start, int) or not isinstance(order_end, int):
        errors.append("ordem_inicial/ordem_final devem ser inteiros")
    elif order_start > order_end:
        errors.append("ordem_inicial maior que ordem_final")

    type_ = item.get("type")
    if type_ is not None and not isinstance(type_, str):
        errors.append("tipo deve ser texto ou nulo")

    date_str = item.get("date")
    if date_str is not None:
        if not isinstance(date_str, str) or not _ISO_DATE_REGEX.match(date_str):
            errors.append(f"data fora do formato ISO (AAAA-MM-DD): {date_str!r}")
        else:
            try:
                date.fromisoformat(date_str)
            except ValueError:
                errors.append(f"data não é uma data de calendário válida: {date_str!r}")

    if item.get("engine") not in VALID_ENGINES:
        errors.append(f"motor inválido: {item.get('engine')!r}")

    if item.get("confidence") not in VALID_CONFIDENCES:
        errors.append(f"confianca inválida: {item.get('confidence')!r}")

    return errors

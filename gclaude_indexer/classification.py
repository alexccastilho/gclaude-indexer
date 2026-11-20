# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Common classification interface (spec section 5, step 6).

Every classification engine — `rules`, `local` — receives the
text of one window and returns the same item structure, so that the import
step (phase 6) does not need to know which engine ran. This module defines
that common structure and the validation required by section 7 before any
item is written.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from .config import ProjectConfig
from .db import BatchWriter
from .engine_names import ENGINE_CLAUDE_CODE, ENGINE_LOCAL, ENGINE_RULES, ENGINE_STRUCTURED
from .events import record_event
from .file_status import MARK_WINDOW_DONE, WINDOW_PENDING
from .file_types import is_whole_document_file
from .paths import RAW_ITEMS_FILE_NAME
from .windows_prep import pages_for_group

VALID_ENGINES = {ENGINE_RULES, ENGINE_LOCAL, ENGINE_CLAUDE_CODE, ENGINE_STRUCTURED}
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
    # Position of the page in its group, 1-based — what `item.start_order`
    # and `end_order` mean. Not the number in `reference`: in a "biblioteca"
    # collection the reference restarts at "p. 1" in every file, so in a
    # group of many files that number repeats. 0 = unknown (a page built by
    # hand), and `page_order` falls back to the reference.
    order: int = 0
    # The `file.id` of the page, for the full text kept in the search index
    # (`fulltext.page_text`). 0 = unknown (a page built by hand).
    file_id: int = 0


def page_order(page: WindowPage) -> int:
    return page.order or reference_number(page.reference)


def starts_new_document(previous: WindowPage | None, page: WindowPage) -> bool:
    """Whether `page` must open a new item because the file changed and one
    of the two files is a whole document (HTML, DOCX, TXT, e-mail…).

    PDFs and images are left to the engine: a scanned document often spans
    several image files, and a case file several PDF volumes."""
    if previous is None or page.file_name == previous.file_name:
        return False
    return is_whole_document_file(previous.file_name) or is_whole_document_file(page.file_name)


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


def files_in_page_order(pages: Sequence[WindowPage]) -> list[str]:
    """The item's files in the order their pages appear (rules engine, the
    local engine's range mode, Planalto acts)."""
    return list(dict.fromkeys(page.file_name for page in pages))


def files_sorted(pages: Sequence[WindowPage]) -> list[str]:
    """The item's files in alphabetical order (the local engine's per-page
    mode, blank pages and coverage items). Differs from
    `files_in_page_order` only for an item over several files; which order
    is right is still open."""
    return sorted({page.file_name for page in pages})


def item_for_pages(
    pages: Sequence[WindowPage],
    *,
    engine: str,
    confidence: str,
    type_: str | None = None,
    date: str | None = None,
    author: str | None = None,
    summary: str | None = None,
    has_table: bool | None = None,
    has_image: bool | None = None,
    files: Callable[[Sequence[WindowPage]], list[str]] = files_in_page_order,
    order_of: Callable[[WindowPage], int] = page_order,
) -> ClassifiedItem:
    """The item spanning `pages` (in window order): references and orders
    from the first and last page, files by `files`. `has_table`/`has_image`
    left as `None` come from the pages themselves; an engine that saw more
    (or knows better) passes its own value.

    The fields the model or the rules fill in (`type_`, `date`...) go in as
    the engine made them: `item_to_dict` normalizes them on the way to
    `raw_items.jsonl`."""
    return ClassifiedItem(
        start_ref=pages[0].reference,
        end_ref=pages[-1].reference,
        start_order=order_of(pages[0]),
        end_order=order_of(pages[-1]),
        type=type_,
        date=date,
        author=author,
        summary=summary,
        has_table=any(page.has_table for page in pages) if has_table is None else has_table,
        has_image=any(page.image_count > 0 for page in pages) if has_image is None else has_image,
        engine=engine,
        confidence=confidence,
        files=files(pages),
    )


class ClassificationEngine(Protocol):
    """Single interface every classification engine implements."""

    def classify(self, pages: list[WindowPage]) -> list[ClassifiedItem]: ...


def reference_number(reference: str) -> int:
    """Extracts the numeric part of a reference ('f. 178' -> 178)."""
    match = re.search(r"(\d+)\s*$", reference)
    return int(match.group(1)) if match else 0


# How often the classification engines commit (`db.BatchWriter`).
# A window's "done" can wait this long to show on the progress bar.
CLASSIFICATION_BATCH_SECONDS = 2.0


class WindowPageLoader:
    """Loads the pages of window after window without rereading the group.

    `load_window_pages` alone rebuilds the whole group — every page, text
    included, naturally sorted — to slice out the 16 pages of one window.
    Classifying all of a group's windows that way reads the group once per
    window: for a group of a hundred thousand pages or more that is
    thousands of reads of half a gigabyte each. This keeps only the
    group's page ids in order (a few MB) and fetches each window's pages by
    id. Same order as `windows_prep.pages_for_group`, so the same slice.

    Valid while the pages do not change — the length of one classification
    run, which only ever writes windows and items."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # Every group seen so far: windows come in id order, and an update
        # appends a group's new windows after other groups' ones.
        self._ids: dict[str, list[int]] = {}

    def _ordered_ids(self, group_key: str) -> list[int]:
        if group_key not in self._ids:
            from .paths import natural_sort_key

            rows = self._conn.execute(
                """
                SELECT page.id, page.number, file.relative_path
                FROM page JOIN file ON file.id = page.file_id
                WHERE file.group_key = ?
                """,
                (group_key,),
            ).fetchall()
            rows.sort(key=lambda row: (natural_sort_key(row[2]), row[1]))
            self._ids[group_key] = [row[0] for row in rows]
        return self._ids[group_key]

    def load(self, window_row: sqlite3.Row) -> list[WindowPage]:
        start, end = _key_positions(window_row["key"])
        ids = self._ordered_ids(window_row["group_key"])[start - 1 : end]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        by_id = {
            row["id"]: row
            for row in self._conn.execute(
                f"SELECT page.*, file.name AS file_name FROM page"
                f" JOIN file ON file.id = page.file_id WHERE page.id IN ({placeholders})",
                ids,
            )
        }
        return [
            WindowPage(
                reference=by_id[page_id]["reference"],
                file_name=by_id[page_id]["file_name"],
                text=readable_text(by_id[page_id]["text"]),
                has_table=bool(by_id[page_id]["has_table"]),
                image_count=by_id[page_id]["image_count"],
                order=start + offset,
                file_id=by_id[page_id]["file_id"],
            )
            for offset, page_id in enumerate(ids)
        ]


def readable_text(text: str | None) -> str:
    """The page text, or `""` when it is the raw bytes of a binary file.

    1.5.9 stopped reading zip, font, audio and CAD files as text, but pages
    converted before that stayed in the database ("no change" in the scan).
    Sent to the model, those control characters made it repeat itself until
    Ollama aborted the answer ("token repeat limit reached", on a .zip
    file). An empty page is still indexed, by file name,
    through the coverage guarantee."""
    if text and "\x00" in text:
        return ""
    return text or ""


def load_window_pages(
    conn: sqlite3.Connection, window_row: sqlite3.Row, loader: WindowPageLoader | None = None
) -> list[WindowPage]:
    """Rebuilds, from the database, exactly the pages that make up a
    window — the same slice used to write the `.txt` in phase 4.

    Pass a `WindowPageLoader` when loading many windows in a row."""
    if loader is not None:
        return loader.load(window_row)
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
            order=start + offset,
            file_id=row["file_id"],
        )
        for offset, row in enumerate(block)
    ]


def _key_positions(key: str) -> tuple[int, int]:
    match = re.search(r"::(\d+)-(\d+)$", key)
    if not match:
        raise ValueError(f"chave de janela em formato inesperado: {key!r}")
    return int(match.group(1)), int(match.group(2))


# Teto do resumo de uma peça. O índice inteiro precisa caber no contexto de
# um projeto do Claude, e é a soma destes resumos que o ocupa — um resumo
# sem limite transformaria o índice numa segunda cópia do acervo, que é
# exatamente o que ele existe para evitar. Cada motor aplica do seu jeito:
# o local corta o resumo inteiro, o Planalto corta só a ementa (com "…"), o
# de regras não corta.
SUMMARY_CHAR_LIMIT = 600


def normalize_confidence(value: object, fallback: str = "low") -> str:
    """`value` when it is a valid confidence level, else `fallback`: an
    engine that did not report it properly is treated with suspicion."""
    return value if isinstance(value, str) and value in VALID_CONFIDENCES else fallback


# The `files` field of a `raw_items.jsonl` line: the item's file names
# joined by `", "`. A name with a comma in it reads back as two names.
_FILES_SEPARATOR = ", "


def files_field(files: Iterable[str]) -> str:
    return _FILES_SEPARATOR.join(files)


def files_from_field(value: object) -> list[str]:
    """The file names of a `files` field, stripped, empty ones dropped."""
    return [name.strip() for name in str(value).split(_FILES_SEPARATOR.strip()) if name.strip()]


# Words a model sometimes returns instead of leaving `type` empty. Stored
# as-is they become their own document type in the index, sitting next to
# the real ones and inflating the "types found" count with nothing.
_EMPTY_TYPES = {"NULL", "NONE", "N/A", "NA", "-", "--", "?", "DESCONHECIDO", "INDEFINIDO", "SEM TIPO"}


def normalize_type(type_: object) -> str | None:
    """Canonical form of a document type, or `None`.

    Upper-cased and stripped, because a model is not consistent about case
    across windows: one collection came back with both `ÍNDICE` and
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
        "date": normalize_date(item.date),
        "author": item.author,
        "summary": item.summary,
        "has_table": bool(item.has_table),
        "has_image": bool(item.has_image),
        "engine": item.engine,
        "confidence": item.confidence,
        "files": files_field(item.files),
    }


_ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH_REGEX = re.compile(r"^\d{4}-\d{2}$")
_ISO_YEAR_REGEX = re.compile(r"^\d{4}$")


def is_calendar_day(value: object) -> bool:
    """Whether `value` is an `AAAA-MM-DD` date that exists in the calendar."""
    if not (isinstance(value, str) and _ISO_DATE_REGEX.match(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def normalize_date(value: object) -> str | None:
    """A data na maior precisão que ela realmente sustenta, ou `None`.

    Documentos contábeis e administrativos datam por competência — "jan/
    2020", "exercício 2019" — e o modelo devolve `2020-01` porque é o que
    o documento diz. Exigir `AAAA-MM-DD` fazia a peça INTEIRA ser
    descartada por causa de um campo opcional: num acervo grande, peças
    inteiras se perdiam só por isso.

    A precisão reduzida é ISO 8601 legítima e, o que decide aqui, ordena
    corretamente na ordenação lexicográfica que `artifacts.py` usa na
    linha do tempo (`2019-12` < `2020-01` < `2020-01-05`). Então ela é
    guardada como veio, em vez de virar um dia 1 que o documento não
    afirma.

    Quando a precisão mais fina não se sustenta, cai um degrau em vez de
    sumir: `2021-09-31` (dia que não existe) vira `2021-09`, porque o mês
    continua confiável. O que não é data nenhuma — um intervalo, uma data
    em formato brasileiro — vira `None`, e a peça segue sem ela.
    """
    if not isinstance(value, str):
        return None

    text = value.strip()

    if _ISO_DATE_REGEX.match(text):
        if is_calendar_day(text):
            return text
        text = text[:7]  # o dia não existe; o mês ainda pode valer

    if _ISO_MONTH_REGEX.match(text):
        if 1 <= int(text[5:7]) <= 12:
            return text
        text = text[:4]  # mês impossível; sobra o ano

    if _ISO_YEAR_REGEX.match(text):
        return text

    return None


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
        # A forma canônica é o que `normalize_date` devolveria: AAAA,
        # AAAA-MM ou AAAA-MM-DD, esta última existindo no calendário.
        # Qualquer outra coisa não passou por `item_to_dict` e a
        # validação segue sendo a rede de segurança.
        canonical = normalize_date(date_str)
        if canonical is None:
            errors.append(f"data fora do formato ISO (AAAA, AAAA-MM ou AAAA-MM-DD): {date_str!r}")
        elif canonical != date_str:
            errors.append(f"data não é uma data de calendário válida: {date_str!r}")

    if item.get("engine") not in VALID_ENGINES:
        errors.append(f"motor inválido: {item.get('engine')!r}")

    if item.get("confidence") not in VALID_CONFIDENCES:
        errors.append(f"confianca inválida: {item.get('confidence')!r}")

    return errors


# --- the window loop both engines share --------------------------------------


@dataclass
class WindowRunCounts:
    """What every engine counts over a classification step."""

    windows_processed: int = 0
    items_generated: int = 0
    invalid_items: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0

    def count_written(self, confidence: str) -> None:
        self.items_generated += 1
        if confidence == "high":
            self.high_confidence += 1
        elif confidence == "medium":
            self.medium_confidence += 1
        else:
            self.low_confidence += 1


@dataclass
class WindowItems:
    """What an engine made of one window: its items, in order, and fields
    added to each of their lines in `raw_items.jsonl`."""

    items: list[ClassifiedItem]
    extra_fields: dict = field(default_factory=dict)


# Returned by a window callback to end the step there (asked to stop while
# waiting): that window and the ones after it stay pending.
STOP_CLASSIFYING = object()


def uncovered_pages(pages: list[WindowPage], items: list[ClassifiedItem]) -> list[WindowPage]:
    """Páginas da janela que nenhuma peça cobre, na ordem em que aparecem."""
    coberto: set[int] = set()
    for item in items:
        for numero in range(item.start_order, item.end_order + 1):
            coberto.add(numero)
    faltando = []
    for page in pages:
        numero = page_order(page)
        if numero not in coberto:
            faltando.append(page)
    return faltando


def classify_windows(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    classify_window: Callable,
    result: WindowRunCounts,
    *,
    invalid_item_event: Callable[[ClassifiedItem, str, list[str]], tuple[str, dict]],
    coverage: tuple[str, Callable[[list[WindowPage]], list[ClassifiedItem]]] | None = None,
    should_stop=None,
    language: str | None = None,
) -> None:
    """Classifies every `pending` window: the protocol both engines follow.

    Each window ends `done`, with every item that passed `validate_item` in
    `raw_items.jsonl` and an `error` event for each one refused, or stays
    `pending` when `classify_window` gives up on it (returns `None`) or
    stops the step (returns `STOP_CLASSIFYING`). The items are flushed to
    the file before the window is queued as done, so a commit never marks
    done a window whose items could still be lost.

    `classify_window(window, pages, writer)` returns a `WindowItems`. The
    `writer` is the step's `BatchWriter`: an event the engine records itself
    either joins the batch or follows a `writer.flush()`.

    `invalid_item_event(item, window_key, errors)` gives the event key and
    params of a refused item (each engine has its own).

    `coverage` (event key, items builder): pages no written item covers get
    items of their own, after validation, so a refused item never takes its
    pages out of the index. Only the local engine has it today.

    One commit every couple of seconds (`BatchWriter`) instead of one per
    window plus one per event: each commit on a Drive-synced database costs
    seconds and locks the screens out."""
    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    pending_windows = conn.execute(
        "SELECT * FROM window WHERE status = ? ORDER BY id", (WINDOW_PENDING,)
    ).fetchall()

    loader = WindowPageLoader(conn)  # One read of each group's order
    writer = BatchWriter(conn, max_seconds=CLASSIFICATION_BATCH_SECONDS)
    with open(jsonl_path, "a", encoding="utf-8") as jsonl_file:
        try:
            for window in pending_windows:
                if should_stop is not None and should_stop():
                    break

                pages = load_window_pages(conn, window, loader)
                outcome = classify_window(window, pages, writer)
                if outcome is STOP_CLASSIFYING:
                    break
                if outcome is None:
                    continue

                def write(item: ClassifiedItem, window=window, outcome=outcome) -> bool:
                    """Validates and writes the item. `False` when it was refused."""
                    item_dict = item_to_dict(item, window["key"], window["group_key"])
                    item_dict.update(outcome.extra_fields)
                    errors = validate_item(item_dict)
                    if errors:
                        result.invalid_items += 1
                        key, params = invalid_item_event(item, window["key"], errors)
                        writer.add(lambda c, key=key, params=params: record_event(
                            c, "classification", "error", key, params, language=language, commit=False,
                        ))
                        return False
                    jsonl_file.write(json.dumps(item_dict, ensure_ascii=False) + "\n")
                    result.count_written(item.confidence)
                    return True

                written = [item for item in outcome.items if write(item)]

                if coverage is not None:
                    # Garantia de cobertura (requisito central: nada pode
                    # faltar do índice). Depois da validação, e não antes:
                    # uma peça recusada não pode levar as páginas dela junto.
                    # Cada peça recusada por causa da data era uma faixa de
                    # páginas que sumiam do índice sem deixar rastro, porque
                    # a cobertura já tinha sido calculada contando com elas.
                    coverage_event, coverage_items = coverage
                    missing = uncovered_pages(pages, written)
                    if missing:
                        params = {"window": window["key"], "pages": len(missing)}
                        writer.add(lambda c, params=params: record_event(
                            c, "classification", "warning", coverage_event,
                            params, language=language, commit=False,
                        ))
                        for item in coverage_items(missing):
                            write(item)

                jsonl_file.flush()
                writer.add(lambda c, window_id=window["id"]: c.execute(MARK_WINDOW_DONE, (window_id,)))
                result.windows_processed += 1
            writer.flush()
        except BaseException:
            jsonl_file.flush()
            try:
                writer.flush()
            except Exception:
                writer.discard()
            raise

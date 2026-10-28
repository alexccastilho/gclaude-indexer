# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Full-text search: every word of every file, found where it is.

The index the system builds for Claude describes *items* — type, date,
summary — and classification only reads the first "characters per page" of
each page. That is the right budget for telling documents apart, and the
wrong one for finding things: a law of 500,000 characters was represented
by its first 2,000, and an article in the middle of it could not be found
by anything the program produced.

This keeps the whole text, untruncated, in an SQLite FTS5 table inside the
project database, split into passages that say where they are:

- a PDF or image page is one passage, located by its citable reference
  (`f. 12` / `p. 5`);
- a whole-document file (HTML, DOCX, TXT…) is split at its structure —
  each article, chapter or heading starts a passage when the current one
  is long enough — and every passage carries the nearest heading above it
  ("Art. 12", "CAPÍTULO II") and the line where it starts in the converted
  copy.

The tokenizer drops accents (`remove_diacritics 2`), so "vigencia" finds
"vigência". Struck text keeps its `~~` marks, and a result says whether
what it found is struck — revoked, in legislation.

Indexing runs at the end of the extraction step, one file at a time with a
commit per file, so it resumes where it stopped. Classification is not
involved: this costs disk, not model time.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .file_types import category_of_extension, is_whole_document_file

# A passage is cut at the next heading once it holds this many characters,
# and cut anyway at the next line once it holds the second number.
_SOFT_PASSAGE_CHARS = 600
_HARD_PASSAGE_CHARS = 2500

_HEADING = re.compile(
    r"^(?:~~)?\s*(?:#+\s*)?("
    r"Art\.?\s*\d+[º°]?(?:-[A-Z])?"
    r"|(?:CAP[ÍI]TULO|T[ÍI]TULO|LIVRO|PARTE|SE[ÇC][ÃA]O|Se[çc][ãa]o|SUBSE[ÇC][ÃA]O)\s+[IVXLCDM\d]+[A-Z-]*"
    r"|ANEXO(?:\s+[IVXLCDM\d]+)?"
    r")",
)
_MARKDOWN_HEADING = re.compile(r"^#+\s+(.{1,80})")
# Snippet highlight marks: control characters no document text contains,
# turned into `<mark>` by the search screen after HTML escaping.
MATCH_START = "\x02"
MATCH_END = "\x03"
_FTS_TOKEN = re.compile(r'"([^"]+)"|(\S+)')
_FTS_UNSAFE = re.compile(r'["*^:()\-+{}\[\]]')

@dataclass
class Passage:
    text: str
    locator: str
    line: int


@dataclass
class IndexingResult:
    files: int = 0
    passages: int = 0
    pending: int = 0
    interrupted: bool = False


@dataclass
class SearchHit:
    file_id: int
    name: str
    relative_path: str
    group_key: str | None
    locator: str
    line: int
    snippet: str
    struck: bool


# --- splitting ----------------------------------------------------------------


def _heading_of(line: str) -> str | None:
    match = _HEADING.match(line)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    match = _MARKDOWN_HEADING.match(line)
    return match.group(1).strip() if match else None


def split_document(text: str) -> list[Passage]:
    """Passages of a whole-document text, each with the heading in force
    where it starts and its first line (1-based)."""
    passages: list[Passage] = []
    lines: list[str] = []
    size = 0
    start_line = 1
    heading = ""
    label = ""

    def close() -> None:
        body = "\n".join(lines).strip()
        if body:
            passages.append(Passage(body, label, start_line))

    for number, line in enumerate(text.splitlines(), start=1):
        found = _heading_of(line)
        if lines and ((found and size >= _SOFT_PASSAGE_CHARS) or size >= _HARD_PASSAGE_CHARS):
            close()
            lines, size = [], 0
        if found:
            heading = found
        if not lines:
            start_line = number
            label = heading
        lines.append(line)
        size += len(line) + 1
    close()
    return passages


# --- reading a file's whole text --------------------------------------------------


def _pdf_passages(pdf_path: Path, references: dict[int, str]) -> list[Passage]:
    import fitz

    document = fitz.open(pdf_path)
    try:
        passages = []
        for number, page in enumerate(document, start=1):
            text = page.get_text().strip()
            if text:
                passages.append(Passage(text, references.get(number, f"p. {number}"), 0))
        return passages
    finally:
        document.close()


def passages_for_file(conn: sqlite3.Connection, config: ProjectConfig, row) -> list[Passage]:
    """Every passage of one extracted file, from the same sources extraction
    reads — the OCR'd copy or the original PDF, or the converted text."""
    output = Path(config.output_folder)
    relative = row["relative_path"]
    references = {
        number: reference
        for number, reference in conn.execute(
            "SELECT number, reference FROM page WHERE file_id = ?", (row["id"],)
        )
    }
    category = category_of_extension("." + row["extension"])

    if category == "pdf":
        if row["needs_ocr"]:
            pdf_path = output / "converted" / Path(relative).with_suffix(".pdf")
        else:
            pdf_path = Path(config.source_folder) / relative
        return _pdf_passages(pdf_path, references)

    text_path = output / "converted" / Path(relative).with_suffix(".txt")
    text = text_path.read_text(encoding="utf-8")
    if not is_whole_document_file(row["name"]):
        # A single image: one page, its OCR text.
        body = text.strip()
        return [Passage(body, references.get(1, "p. 1"), 0)] if body else []
    passages = split_document(text)
    reference = references.get(1, "")
    for passage in passages:
        passage.locator = " · ".join(part for part in (reference, passage.locator) if part)
    return passages


# --- indexing ---------------------------------------------------------------------


def remove_file(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("DELETE FROM fulltext WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM fulltext_file WHERE file_id = ?", (file_id,))


def index_file(conn: sqlite3.Connection, config: ProjectConfig, row) -> int:
    passages = passages_for_file(conn, config, row)
    remove_file(conn, row["id"])
    conn.executemany(
        "INSERT INTO fulltext (text, file_id, locator, line) VALUES (?, ?, ?, ?)",
        [(p.text, row["id"], p.locator, p.line) for p in passages],
    )
    conn.execute("INSERT INTO fulltext_file (file_id) VALUES (?)", (row["id"],))
    return len(passages)


def pending_files(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM file
        WHERE status = 'extracted'
          AND id NOT IN (SELECT file_id FROM fulltext_file)
        ORDER BY relative_path
        """
    ).fetchall()


def index_pending(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    should_stop: Callable[[], bool] | None = None,
    language: str | None = None,
    time_budget: float | None = None,
) -> IndexingResult:
    """Indexes every extracted file not yet in the search, committing per
    file. Stops early on `should_stop()` or after `time_budget` seconds,
    leaving the rest for the next call. A file whose text can no longer be
    read (converted copies cleared, original moved) is logged and skipped,
    never failing the step."""
    started = time.monotonic()
    result = IndexingResult()
    rows = pending_files(conn)
    for position, row in enumerate(rows):
        if (should_stop is not None and should_stop()) or (
            time_budget is not None and time.monotonic() - started > time_budget
        ):
            result.interrupted = True
            result.pending = len(rows) - position
            break
        try:
            result.passages += index_file(conn, config, row)
            result.files += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            record_event(
                conn, "extraction", "warning", "log.fulltext.file_failed",
                {"name": row["name"], "error": str(exc)[:300]}, language=language,
            )
    if result.files or result.interrupted:
        record_event(
            conn, "extraction", "info",
            "log.fulltext.summary_interrupted" if result.interrupted else "log.fulltext.summary",
            {"files": result.files, "passages": result.passages, "pending": result.pending},
            language=language,
        )
    return result


# --- searching --------------------------------------------------------------------


def fts_query(text: str) -> str:
    """The user's words as a safe FTS5 query: every word must appear, a
    "quoted phrase" must appear as written, `word*` matches by prefix.
    FTS5 operators typed by accident never raise a syntax error."""
    terms = []
    for phrase, word in _FTS_TOKEN.findall(text):
        if phrase:
            clean = _FTS_UNSAFE.sub(" ", phrase).strip()
            if clean:
                terms.append(f'"{clean}"')
            continue
        prefix = word.endswith("*")
        clean = _FTS_UNSAFE.sub(" ", word).strip()
        for part in clean.split():
            terms.append(f'"{part}"' + ("*" if prefix else ""))
    return " ".join(terms)


def search(conn: sqlite3.Connection, text: str, limit: int = 50, offset: int = 0) -> tuple[list[SearchHit], int]:
    """`(hits, total)` for the user's words, best match first."""
    query = fts_query(text)
    if not query:
        return [], 0
    total = conn.execute("SELECT COUNT(*) FROM fulltext WHERE fulltext MATCH ?", (query,)).fetchone()[0]
    rows = conn.execute(
        """
        SELECT fulltext.file_id, fulltext.locator, fulltext.line,
               snippet(fulltext, 0, ?, ?, ' … ', 40) AS snippet,
               file.name, file.relative_path, file.group_key
        FROM fulltext
        JOIN file ON file.id = fulltext.file_id
        WHERE fulltext MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?
        """,
        (MATCH_START, MATCH_END, query, limit, offset),
    ).fetchall()
    hits = [
        SearchHit(
            file_id=row["file_id"], name=row["name"], relative_path=row["relative_path"],
            group_key=row["group_key"], locator=row["locator"] or "", line=row["line"] or 0,
            snippet=row["snippet"], struck=_hit_is_struck(row["snippet"]),
        )
        for row in rows
    ]
    return hits, total


def _hit_is_struck(snippet: str) -> bool:
    """Whether the first match in the snippet sits inside a `~~...~~` span
    on its line."""
    position = snippet.find(MATCH_START)
    if position < 0:
        return False
    line_start = snippet.rfind("\n", 0, position) + 1
    return snippet[line_start:position].count("~~") % 2 == 1


def coverage(conn: sqlite3.Connection) -> tuple[int, int]:
    """`(files in the search, files extracted)`."""
    indexed = conn.execute(
        "SELECT COUNT(*) FROM fulltext_file JOIN file ON file.id = fulltext_file.file_id "
        "WHERE file.status = 'extracted'"
    ).fetchone()[0]
    extracted = conn.execute("SELECT COUNT(*) FROM file WHERE status = 'extracted'").fetchone()[0]
    return indexed, extracted

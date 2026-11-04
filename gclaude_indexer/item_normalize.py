# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Clean-up of the classified items on import, before they are
consolidated: one spelling per document type and the author of the Planalto
acts read from their whole text.

In a large collection the local model wrote hundreds of different types,
many of them the same one with and
without accents ("INDICE"/"ÍNDICE", "SESSAO"/"SESSÃO"), which split the
type filters of the index; and thousands of acts read by `planalto.py` had no author,
because the page the classifier sees stops at the project's page size and
a long law is signed past that point.

Both run on what is already in `raw_items.jsonl`: nothing is classified
again.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict

from . import planalto
from .windows_prep import pages_for_group

BLANK_PAGE_TYPE = "PÁGINA EM BRANCO"
_BLANK_MARKERS = ("página em branco", "pagina em branco", "página vazia", "pagina vazia")


def _plain(text: str) -> str:
    """Upper case without accents: the key two spellings share."""
    decomposed = unicodedata.normalize("NFD", text.upper())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _spellings(values) -> dict[str, str]:
    """For each accent-free key, the spelling every variant becomes.

    The most frequent one, except that an accented spelling beats a more
    frequent unaccented one when it has at least half its count: the model
    drops accents ("INDICE" 92 times, "ÍNDICE" 84) far more often than it
    invents one ("TEÓRIA" 30 times against "TEORIA" 91)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for value in values:
        counts[_plain(value)][value] += 1
    return {key: _pick(names, list(names)) for key, names in counts.items()}


def _pick(names: Counter, pool: list[str]) -> str:
    """The spelling, among `pool`, that the variants in `names` become: the
    most frequent, or an accented one with at least half its count."""
    best = max(pool, key=lambda name: (names[name], name))
    if best.upper() == _plain(best):
        accented = [name for name in pool if name.upper() != _plain(name)]
        if accented:
            runner = max(accented, key=lambda name: (names[name], name))
            if names[runner] * 2 >= names[best]:
                best = runner
    return best


def normalize_types(items: list[dict]) -> int:
    """Gives every item the canonical name of its type, in place, and
    returns how many changed.

    Spellings that differ only in accents become one (see `_spellings`);
    an item with no type whose summary says the page is blank becomes
    "PÁGINA EM BRANCO". Different names are never merged: "LEI FEDERAL"
    and "LEI" may mean something to whoever reads the index (federal next
    to state and municipal laws), so only the spelling is decided here."""
    names = [
        " ".join(item["type"].upper().split())
        for item in items
        if isinstance(item.get("type"), str) and item["type"].strip()
    ]
    canonical = _spellings(names)

    changed = 0
    for item in items:
        kind = item.get("type")
        if isinstance(kind, str) and kind.strip():
            new = canonical[_plain(" ".join(kind.upper().split()))]
        elif any(marker in str(item.get("summary") or "").lower() for marker in _BLANK_MARKERS):
            new = BLANK_PAGE_TYPE
        else:
            continue
        if new != kind:
            item["type"] = new
            changed += 1
    return changed


def _whole_text(conn: sqlite3.Connection, file_id: int) -> str:
    """The file's whole text, from the full-text search, which keeps all of
    it (the page table keeps only the first `chars_per_page` characters)."""
    found = conn.execute(
        "SELECT first_rowid, last_rowid FROM fulltext_file WHERE file_id = ?", (file_id,)
    ).fetchone()
    if found is None or found[0] is None or found[1] is None:
        return ""
    return "\n".join(
        row[0] or ""
        for row in conn.execute(
            "SELECT text FROM fulltext WHERE rowid BETWEEN ? AND ? ORDER BY rowid", (found[0], found[1])
        )
    )


# What the model writes when it has nothing to say. "null" came back
# as a string in dozens of items of one collection and was printed as the
# author's name.
_PLACEHOLDERS = {
    "null", "none", "nil", "undefined", "n/a", "na", "n.a.", "-", "--", "?",
    "nenhum", "nenhuma", "ninguno", "ninguna", "desconhecido", "desconocido",
    "unknown", "não informado", "nao informado", "no informado", "not informed",
    "sem autor", "sin autor", "no author",
}
_TEXT_FIELDS = ("type", "date", "author", "summary")

# An "author" that is the citation of a norm ("Lei nº 9.394/1996",
# "Decreto 7.892 de 2013"): the act a document refers to, not who wrote it.
# The word for the kind of act, then a number marker or a number.
_NORM_CITATION = re.compile(
    r"^\s*(lei|decreto|decreto-lei|portaria|resolu[cç][aã]o|resoluci[oó]n|"
    r"instru[cç][aã]o normativa|instrucci[oó]n|medida provis[oó]ria|"
    r"emenda constitucional|ato|ley|law|act|decree|ordinance|circular|"
    r"delibera[cç][aã]o|parecer|of[ií]cio|edital|regulamento|norma)\b"
    r"[^\n]{0,40}?\d",
    re.IGNORECASE,
)


def clean_placeholders(items: list[dict]) -> int:
    """Empties the text fields that only hold a placeholder ("null", "N/A",
    "-"). In place; returns how many fields were emptied."""
    cleaned = 0
    for item in items:
        for field_name in _TEXT_FIELDS:
            value = item.get(field_name)
            if isinstance(value, str) and value.strip().lower().strip(".") in {
                placeholder.strip(".") for placeholder in _PLACEHOLDERS
            }:
                item[field_name] = None
                cleaned += 1
            elif isinstance(value, str) and not value.strip():
                item[field_name] = None
    return cleaned


def is_norm_citation(author: str) -> bool:
    return bool(_NORM_CITATION.match(author))


def clean_authors(items: list[dict]) -> int:
    """The authors of the items not read by `planalto.py`, in place;
    returns how many changed.

    - A norm cited as the author ("Lei nº 9.394/1996") is dropped.
    - The same name written in different case ("LUIZ INÁCIO LULA DA
      SILVA" and "Luiz Inácio Lula da Silva") gets one spelling: the most
      frequent of those in mixed case, which keeps "da"/"de" and acronyms
      as the document wrote them. A name only ever written in capitals is
      left alone: turning "ASSOCIAÇÃO DE EXEMPLO" or "XPTO"
      into title case by rule would get acronyms wrong.
    - The same name with and without accents ("ANTONIO" and "ANTÔNIO")
      also gets one spelling, chosen as for the types (see `_pick`).
    """
    changed = 0
    others = [
        item for item in items
        if item.get("engine") != planalto.ENGINE and isinstance(item.get("author"), str)
    ]
    for item in others:
        if is_norm_citation(item["author"]):
            item["author"] = None
            changed += 1
    others = [item for item in others if item.get("author")]

    variants: dict[str, Counter] = defaultdict(Counter)
    for item in others:
        name = " ".join(item["author"].split())
        variants[_plain(name)][name] += 1
    chosen: dict[str, str] = {}
    for key, names in variants.items():
        mixed = [name for name in names if name != name.upper() and name != name.lower()]
        chosen[key] = _pick(names, mixed or list(names))
    for item in others:
        name = " ".join(item["author"].split())
        best = chosen[_plain(name)]
        if item["author"] != best:
            item["author"] = best
            changed += 1
    return changed


def fill_structured_authors(conn: sqlite3.Connection, items: list[dict]) -> int:
    """Finds the author of the Planalto acts that came without one, and
    gives every Planalto author one spelling. In place; returns how many
    authors were found."""
    missing = [
        item for item in items
        if item.get("engine") == planalto.ENGINE and not item.get("author")
    ]
    found = _find_missing_authors(conn, missing) if missing else 0

    # One spelling per signature: case first ("ERNESTO GEISEL"), then
    # accents ("Getulio Vargas" next to "Getúlio Vargas").
    signed = [item for item in items if item.get("engine") == planalto.ENGINE and item.get("author")]
    for item in signed:
        item["author"] = planalto.person_name(item["author"])
    chosen = _spellings(item["author"] for item in signed)
    for item in signed:
        item["author"] = chosen[_plain(item["author"])]
    return found


def _find_missing_authors(conn: sqlite3.Connection, missing: list[dict]) -> int:
    """Reads each act's whole text and takes its signature (in place)."""
    try:
        positions = {
            group: pages_for_group(conn, group, with_text=False)
            for group in {item["group"] for item in missing}
        }
    except sqlite3.Error:
        return 0

    found = 0
    texts: dict[int, str] = {}
    for item in missing:
        pages = positions.get(item["group"]) or []
        order = item.get("order_start")
        if not isinstance(order, int) or not 1 <= order <= len(pages):
            continue
        file_id = pages[order - 1]["file_id"]
        if file_id not in texts:
            try:
                texts[file_id] = _whole_text(conn, file_id)
            except sqlite3.Error:
                # No full-text search in this database (an old project, or
                # the step was never run): what the page had is all there is.
                texts[file_id] = ""
        author = planalto.find_author(texts[file_id], item.get("type"))
        if author:
            item["author"] = author
            found += 1
        if len(texts) > 256:
            texts.clear()
    return found

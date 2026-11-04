# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Accuracy of an index against a hand-checked answer key (fase 37).

`quality.py` summarises the confidence the engine *declares*; it says
nothing about whether a piece is right. This module measures that, against
a CSV where every page of a collection has a known piece, type, date and
author — the demo collection in `demo/` ships one.

Four questions, each a number a reader can act on:

- **Coverage** — which answer-key pages the index places in some piece.
- **Boundaries** — an answer-key piece counts as found when an index piece
  shares at least half of the union of their pages (Jaccard ≥ 0.5). The
  prompt asks for "one piece per unit of subject"; a 3-page piece returned
  as 2 + 1 is a boundary error, not an absence, and slicing versus merging
  stay visible in precision and recall separately.
- **Type / date / author** — only among the pieces found, so a boundary
  error is not charged twice.

Pages are mapped by *position in the group* (`item.start_order`), the same
definition `artifacts._physical_pages` uses. `start_ref` is never parsed:
"f. 40" may be page 4 of volume 2.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .windows_prep import group_page_positions

# Below this share of common pages two pieces are different pieces: a key
# piece split exactly in half still matches one half (0.5); a piece that
# merely touches its neighbour by one page does not.
JACCARD_THRESHOLD = 0.5

_HEADER = ("arquivo", "pagina_inicial", "pagina_final", "tipo", "data", "autor")


@dataclass(frozen=True)
class KeyPiece:
    file: str
    first_page: int
    last_page: int
    type: str
    date: str
    author: str

    @property
    def pages(self) -> frozenset[tuple[str, int]]:
        return frozenset((self.file, n) for n in range(self.first_page, self.last_page + 1))


@dataclass
class FieldScore:
    hits: int = 0
    total: int = 0

    @property
    def rate(self) -> float | None:
        return None if self.total == 0 else self.hits / self.total


@dataclass
class AccuracyReport:
    pages_total: int = 0
    pages_covered: int = 0
    key_pieces: int = 0
    index_pieces: int = 0
    matched: int = 0
    type_score: FieldScore = field(default_factory=FieldScore)
    date_score: FieldScore = field(default_factory=FieldScore)
    author_score: FieldScore = field(default_factory=FieldScore)
    by_group: dict[str, "AccuracyReport"] = field(default_factory=dict)
    mismatches: list[dict] = field(default_factory=list)
    unknown_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float | None:
        return None if self.pages_total == 0 else self.pages_covered / self.pages_total

    @property
    def precision(self) -> float | None:
        return None if self.index_pieces == 0 else self.matched / self.index_pieces

    @property
    def recall(self) -> float | None:
        return None if self.key_pieces == 0 else self.matched / self.key_pieces

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)


def load_answer_key(path: Path) -> list[KeyPiece]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _HEADER:
            raise ValueError(f"cabeçalho esperado: {','.join(_HEADER)}; lido: {reader.fieldnames}")
        return [
            KeyPiece(
                row["arquivo"].strip().replace("\\", "/"),
                int(row["pagina_inicial"]),
                int(row["pagina_final"]),
                (row["tipo"] or "").strip(),
                (row["data"] or "").strip(),
                (row["autor"] or "").strip(),
            )
            for row in reader
            if (row.get("arquivo") or "").strip()
        ]


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_type(value: str | None) -> str:
    return " ".join(_strip_accents(value or "").upper().split())


def author_matches(expected: str, actual: str | None) -> bool:
    """The surname or the acronym of the answer key appears in the index.

    The engine writes what the signature says ("M. Souza", "PGM"); the key
    writes the full form. Exact comparison would charge every abbreviation
    as a miss, so the test is containment of the last word with at least 3
    letters (skips "Li", "de") or of the acronym in parentheses.
    """
    if not expected or not actual:
        return False
    actual_norm = _strip_accents(actual).lower()
    acronym = re.search(r"\(([^)]+)\)", expected)
    if acronym and _strip_accents(acronym.group(1)).strip().lower() in actual_norm:
        return True
    words = re.findall(r"[a-z]+", _strip_accents(re.sub(r"\([^)]*\)", " ", expected)).lower())
    surname = next((w for w in reversed(words) if len(w) >= 3), None)
    return bool(surname) and re.search(rf"\b{re.escape(surname)}\b", actual_norm) is not None


@dataclass
class _IndexPiece:
    item_id: int
    group: str
    pages: frozenset[tuple[str, int]]
    type: str | None
    date: str | None
    author: str | None
    start_ref: str
    end_ref: str


def _index_pieces(conn) -> tuple[list[_IndexPiece], dict[str, str]]:
    """Index pieces as sets of (file, page), and the group of each file."""
    positions = group_page_positions(conn, with_text=False)
    file_group: dict[str, str] = {}
    for group, pages in positions.items():
        for page in pages:
            file_group[page["file_relative_path"]] = group
    pieces = []
    rows = conn.execute(
        "SELECT id, group_key, start_order, end_order, type, date, author, start_ref, end_ref"
        " FROM item ORDER BY group_key, start_order, end_order, id"
    ).fetchall()
    for row in rows:
        group_pages = positions.get(row["group_key"], [])
        pages = frozenset(
            (group_pages[pos - 1]["file_relative_path"], group_pages[pos - 1]["number"])
            for pos in range(row["start_order"], row["end_order"] + 1)
            if 1 <= pos <= len(group_pages)
        )
        pieces.append(_IndexPiece(
            row["id"], row["group_key"], pages, row["type"], row["date"], row["author"],
            row["start_ref"], row["end_ref"],
        ))
    return pieces, file_group


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _match(key: list[KeyPiece], index: list[_IndexPiece]) -> dict[int, tuple[int, float]]:
    """Key position → (index position, Jaccard): best pairs first, each
    piece used at most once."""
    candidates = [
        (_jaccard(k.pages, p.pages), ki, pi)
        for ki, k in enumerate(key)
        for pi, p in enumerate(index)
        if k.pages & p.pages
    ]
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    taken_key: set[int] = set()
    taken_index: set[int] = set()
    matches: dict[int, tuple[int, float]] = {}
    for score, ki, pi in candidates:
        if score < JACCARD_THRESHOLD:
            break
        if ki in taken_key or pi in taken_index:
            continue
        taken_key.add(ki)
        taken_index.add(pi)
        matches[ki] = (pi, score)
    return matches


def _fill(report: AccuracyReport, key: list[KeyPiece], key_ids: list[int], index_ids: list[int],
          index: list[_IndexPiece], matches: dict[int, tuple[int, float]], covered: frozenset) -> None:
    report.key_pieces = len(key_ids)
    report.index_pieces = len(index_ids)
    for ki in key_ids:
        k = key[ki]
        report.pages_total += len(k.pages)
        report.pages_covered += len(k.pages & covered)
        if ki not in matches:
            continue
        p = index[matches[ki][0]]
        report.matched += 1
        report.type_score.total += 1
        report.type_score.hits += normalize_type(k.type) == normalize_type(p.type)
        if k.date:
            report.date_score.total += 1
            report.date_score.hits += (p.date or "") == k.date
        if k.author:
            report.author_score.total += 1
            report.author_score.hits += author_matches(k.author, p.author)


def compare_with_answer_key(conn, key: list[KeyPiece]) -> AccuracyReport:
    index, file_group = _index_pieces(conn)
    matches = _match(key, index)
    covered = frozenset().union(*(p.pages for p in index)) if index else frozenset()

    key_files = {k.file for k in key}
    report = AccuracyReport(
        unknown_files=sorted(f for f in file_group if f not in key_files),
        missing_files=sorted(f for f in key_files if f not in file_group),
    )
    _fill(report, key, list(range(len(key))), list(range(len(index))), index, matches, covered)

    # A key file the database never saw has no group; its first folder is
    # the group the scan would have given it, so it still lands in a row.
    def group_of(piece: KeyPiece) -> str:
        return file_group.get(piece.file) or piece.file.split("/")[0]

    groups = list(dict.fromkeys([group_of(k) for k in key] + [p.group for p in index]))
    for group in groups:
        sub = AccuracyReport()
        _fill(
            sub, key, [ki for ki, k in enumerate(key) if group_of(k) == group],
            [pi for pi, p in enumerate(index) if p.group == group], index, matches, covered,
        )
        report.by_group[group] = sub

    matched_index = {pi for pi, _ in matches.values()}
    for ki, k in enumerate(key):
        where = {"file": k.file, "pages": f"{k.first_page}-{k.last_page}"}
        if ki not in matches:
            report.mismatches.append({"field": "missing", **where, "expected": k.type or "(sem tipo)", "actual": ""})
            continue
        pi, score = matches[ki]
        p = index[pi]
        if score < 1.0:
            report.mismatches.append({"field": "pages", **where, "expected": where["pages"],
                                      "actual": f"{p.start_ref} a {p.end_ref}"})
        if normalize_type(k.type) != normalize_type(p.type):
            report.mismatches.append({"field": "type", **where, "expected": k.type, "actual": p.type or ""})
        if k.date and (p.date or "") != k.date:
            report.mismatches.append({"field": "date", **where, "expected": k.date, "actual": p.date or ""})
        if k.author and not author_matches(k.author, p.author):
            report.mismatches.append({"field": "author", **where, "expected": k.author, "actual": p.author or ""})
    for pi, p in enumerate(index):
        if pi not in matched_index:
            files = sorted({f for f, _ in p.pages}) or [p.group]
            report.mismatches.append({"field": "extra", "file": ", ".join(files),
                                      "pages": f"{p.start_ref} a {p.end_ref}", "expected": "",
                                      "actual": p.type or "(sem tipo)"})
    return report


# --- Markdown -----------------------------------------------------------

_FIELD_LABELS = {
    "pages": "limites", "type": "tipo", "date": "data", "author": "autor",
    "missing": "peça não encontrada", "extra": "peça a mais no índice",
}


def _pct(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}".replace(".", ",") + "%"


def _duration(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(float(seconds)))
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def _row(label: str, r: AccuracyReport) -> str:
    return (
        f"| {label} | {r.pages_covered}/{r.pages_total} ({_pct(r.coverage)}) | {r.key_pieces}/{r.index_pieces}"
        f" | {_pct(r.precision)} | {_pct(r.recall)} | {_pct(r.f1)}"
        f" | {_pct(r.type_score.rate)} | {_pct(r.date_score.rate)} | {_pct(r.author_score.rate)} |"
    )


def render_report(report: AccuracyReport, context: dict) -> str:
    """Markdown in pt-BR, the language of the demo collection it measures."""
    lines = [
        "# Acerto do índice contra o gabarito",
        "",
        "| Motor | Modelo | Versão | Máquina | Data | Duração |",
        "|---|---|---|---|---|---|",
        f"| {context.get('engine') or '—'} | {context.get('model') or '—'} | {context.get('version') or '—'}"
        f" | {context.get('machine') or '—'} | {context.get('date') or '—'} | {_duration(context.get('duration_s'))} |",
        "",
        "| Grupo | Páginas cobertas | Peças (gabarito/índice) | Precisão | Revocação | F1 | Tipo | Data | Autor |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for group, sub in report.by_group.items():
        lines.append(_row(group, sub))
    lines.append(_row("**Total**", report))
    lines += [
        "",
        "Cobertura: páginas do gabarito que estão em alguma peça do índice. Peça encontrada: "
        "peça do índice com pelo menos metade das páginas em comum (Jaccard ≥ 0,5). Precisão: "
        "encontradas / peças do índice; revocação: encontradas / peças do gabarito. Tipo, data e "
        "autor são medidos só entre as peças encontradas; data e autor só onde o gabarito os tem.",
    ]
    if report.missing_files:
        lines += ["", "## Arquivos do gabarito que o índice não tem", ""]
        lines += [f"- `{f}`" for f in report.missing_files]
    if report.unknown_files:
        lines += ["", "## Arquivos do índice fora do gabarito", ""]
        lines += [f"- `{f}`" for f in report.unknown_files]
    if report.mismatches:
        lines += [
            "", f"## Divergências ({len(report.mismatches)})", "",
            "| Campo | Arquivo | Páginas | Gabarito | Índice |", "|---|---|---|---|---|",
        ]
        for m in report.mismatches:
            lines.append(
                f"| {_FIELD_LABELS.get(m['field'], m['field'])} | `{m['file']}` | {m['pages']}"
                f" | {m['expected']} | {m['actual']} |"
            )
    return "\n".join(lines) + "\n"

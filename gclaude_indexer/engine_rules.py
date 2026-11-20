# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""`rules` engine (spec section 5, step 6) — purely deterministic: no
network call, no model. The marker dictionary and date patterns come from
`config/classification_rules.json`, never hard-coded.

An item starts on a type marker, a preceding blank page, a protocol stamp,
or a change in a repeated header. A page with none of those signals joins
the previous item and forces `confidence = "low"` on it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import planalto
from .classification import (
    ClassifiedItem,
    WindowItems,
    WindowPage,
    WindowRunCounts,
    classify_windows,
    item_for_pages,
    starts_new_document,
)
from .config import ProjectConfig
from .engine_names import ENGINE_RULES
from .events import record_event
from .html_text import without_struck_text
from .paths import app_root

# Medido em `demo/acervo` (docs/QUALITY.md) e NÃO adotado: a base era pequena
# demais (2 peças `medium` contra 17 `low`) para dizer que `medium` acerta mais
# que `low`. Só vira `True` com uma medição que sustente.
CONTINUATION_KEEPS_MEDIUM = False
DEFAULT_RULES_PATH = app_root() / "config" / "classification_rules.json"


@dataclass
class ClassificationRules:
    types: dict[str, list[str]]
    protocol_markers: list[str]
    summary_markers: list[str]
    author_markers: list[str]
    date_patterns: list[dict]
    months: dict[str, int]
    blank_page_threshold: int
    summary_sentence_char_threshold: int
    type_search_chars: int
    # Headings that name a document's type only when they open a line, in
    # capitals — "LEI Nº 13.146, DE 6 DE JULHO DE 2015". `[type, regex]`
    # pairs, tried in order (the more specific first: "LEI COMPLEMENTAR"
    # before "LEI"). Case-sensitive on purpose: "nos termos da Lei nº 8.112"
    # in running text is a citation, not a heading.
    heading_types: list[tuple[str, re.Pattern]] = field(default_factory=list)
    heading_search_chars: int = 600


def load_rules(path: Path | None = None) -> ClassificationRules:
    path = path or DEFAULT_RULES_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return ClassificationRules(
        types=data["types"],
        protocol_markers=data["protocol_markers"],
        summary_markers=data["summary_markers"],
        author_markers=data["author_markers"],
        date_patterns=data["date_patterns"],
        months={key.lower(): value for key, value in data["months"].items()},
        blank_page_threshold=data["blank_page_threshold"],
        summary_sentence_char_threshold=data["summary_sentence_char_threshold"],
        type_search_chars=data["type_search_chars"],
        heading_types=[
            (type_, re.compile(pattern, re.MULTILINE))
            for type_, pattern in data.get("heading_types", [])
        ],
        heading_search_chars=data.get("heading_search_chars", 600),
    )


@dataclass
class _ItemInProgress:
    pages: list[WindowPage] = field(default_factory=list)
    types_per_page: list[str | None] = field(default_factory=list)
    dates_per_page: list[str | None] = field(default_factory=list)
    has_low_confidence: bool = False
    has_marked_type: bool = False
    # A peça nasceu de um marcador (tipo no cabeçalho ou carimbo de
    # protocolo), e não de uma página em branco, de um cabeçalho que mudou
    # ou de outro arquivo.
    opened_by_marker: bool = False


class RulesEngine:
    """Implements `ClassificationEngine` (see `classification.py`)."""

    def __init__(self, rules: ClassificationRules):
        self._rules = rules

    def classify(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        ready_items: list[_ItemInProgress] = []
        current_item: _ItemInProgress | None = None

        previous_header: str | None = None
        header_repeats = 0
        previous_page_blank = False
        previous_page: WindowPage | None = None

        for page in pages:
            # Struck text (`~~...~~`, from HTML/DOCX) is what was revoked: a
            # revoked date or heading must not become the item's.
            text = without_struck_text(page.text)
            stripped_text = text.strip()
            first_line = stripped_text.splitlines()[0].strip() if stripped_text else ""

            found_type = self._find_heading_type(text) or self._find_type(text)
            has_protocol = self._find_protocol(text)
            blank_page = len(stripped_text) < self._rules.blank_page_threshold
            header_changed = (
                bool(first_line)
                and previous_header is not None
                and header_repeats >= 2
                and first_line != previous_header
            )

            # A whole-document file (HTML, DOCX, TXT…) is one item by
            # construction: every law of the Planalto collection starts with
            # the same "Presidência da República", so without this the
            # header never changes and consecutive laws merge.
            new_file = starts_new_document(previous_page, page)
            any_signal = bool(found_type or has_protocol or previous_page_blank or header_changed or new_file)

            if current_item is None or new_file or (any_signal and not blank_page):
                if current_item is not None:
                    ready_items.append(current_item)
                current_item = _ItemInProgress(opened_by_marker=bool(found_type or has_protocol))

            if not any_signal:
                current_item.has_low_confidence = True
            if found_type:
                current_item.has_marked_type = True

            current_item.pages.append(page)
            current_item.types_per_page.append(found_type)
            current_item.dates_per_page.append(self._find_date(text))

            if first_line:
                if first_line == previous_header:
                    header_repeats += 1
                else:
                    previous_header = first_line
                    header_repeats = 1

            previous_page_blank = blank_page
            previous_page = page

        if current_item is not None:
            ready_items.append(current_item)

        return [self._finalize(item) for item in ready_items]

    def _find_heading_type(self, text: str) -> str | None:
        head = text[: self._rules.heading_search_chars]
        for type_, pattern in self._rules.heading_types:
            if pattern.search(head):
                return type_
        return None

    def _find_type(self, text: str) -> str | None:
        """The marker closest to the real start of the page wins — not the
        first one found in dictionary order. Without this, a marker that
        happens to appear later in the text (e.g. "conforme parecer técnico
        anexo") could beat a genuine marker right at the start of the page
        (e.g. "DESPACHO")."""
        start = text[: self._rules.type_search_chars].upper()
        best_type = None
        best_position = None
        for type_, markers in self._rules.types.items():
            for marker in markers:
                match = re.search(r"\b" + re.escape(marker.upper()) + r"\b", start)
                if match and (best_position is None or match.start() < best_position):
                    best_type = type_
                    best_position = match.start()
        return best_type

    def _find_protocol(self, text: str) -> bool:
        for pattern in self._rules.protocol_markers:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _find_date(self, text: str) -> str | None:
        for pattern in self._rules.date_patterns:
            match = re.search(pattern["regex"], text, re.IGNORECASE)
            if not match:
                continue
            values = dict(zip(pattern["groups"], match.groups()))
            try:
                day = int(values["day"])
                year = int(values["year"])
                if "month_name" in values:
                    month = self._rules.months.get(values["month_name"].lower())
                    if month is None:
                        continue
                else:
                    month = int(values["month"])
                return date(year, month, day).isoformat()
            except (ValueError, KeyError):
                continue
        return None

    def _find_summary(self, pages: list[WindowPage]) -> str | None:
        for page in pages:
            for line in without_struck_text(page.text).splitlines():
                stripped_line = line.strip()
                for marker in self._rules.summary_markers:
                    if stripped_line.lower().startswith(marker.lower()):
                        rest = stripped_line[len(marker):].strip(" :-")
                        if rest:
                            return rest

        limit = self._rules.summary_sentence_char_threshold
        full_text = " ".join(without_struck_text(p.text) for p in pages)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", full_text):
            sentence = sentence.strip()
            if len(sentence) > limit:
                return sentence
        return None

    def _find_author(self, pages: list[WindowPage]) -> str | None:
        for page in reversed(pages):
            lines = [line.strip() for line in without_struck_text(page.text).splitlines()]
            for index, line in enumerate(lines):
                for marker in self._rules.author_markers:
                    if line.lower().startswith(marker.lower()):
                        rest = line[len(marker):].strip(" :,-")
                        if rest:
                            return rest
                        for next_line in lines[index + 1 :]:
                            if next_line:
                                return next_line
        return None

    def _finalize(self, item: _ItemInProgress) -> ClassifiedItem:
        pages = item.pages

        type_ = next((t for t in item.types_per_page if t), None)
        date_value = next((d for d in item.dates_per_page if d), None)

        if item.has_low_confidence:
            # 2.0.0: a continuação de uma peça aberta por marcador (as folhas
            # seguintes de um parecer, de um contrato) não rebaixa a peça
            # inteira: o limite e o tipo vêm do marcador, só o fim é suposto.
            confidence = "medium" if CONTINUATION_KEEPS_MEDIUM and item.opened_by_marker else "low"
        elif item.has_marked_type:
            confidence = "high"
        else:
            confidence = "medium"

        # No summary cap here, unlike the local engine and the Planalto acts
        # (`classification.SUMMARY_CHAR_LIMIT`).
        return item_for_pages(
            pages, engine=ENGINE_RULES, confidence=confidence, type_=type_, date=date_value,
            author=self._find_author(pages), summary=self._find_summary(pages),
        )


@dataclass
class RulesClassificationResult(WindowRunCounts):
    pass


def classify_pending(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    rules: ClassificationRules | None = None,
    should_stop=None,
    language: str | None = None,
) -> RulesClassificationResult:
    """Classifies every `pending` window with the `rules` engine, writes the
    items to `raw_items.jsonl` (same format as the `local` engine) and
    marks the window as `done` (`classification.classify_windows`)."""
    rules = rules or load_rules()
    engine = RulesEngine(rules)
    result = RulesClassificationResult()

    def classify_window(window, pages, writer) -> WindowItems:
        # Planalto acts read from their own structure.
        structured_items, rest = planalto.split(pages)
        return WindowItems(structured_items + (engine.classify(rest) if rest else []))

    # No coverage fill here, unlike the local engine: a refused item's pages
    # leave the index (rare: this engine's dates are always valid).
    classify_windows(
        conn, config, classify_window, result,
        invalid_item_event=lambda _item, window_key, errors: (
            "log.rules.invalid_item", {"window": window_key, "errors": "; ".join(errors)}
        ),
        should_stop=should_stop, language=language,
    )

    record_event(
        conn,
        "classification",
        "info",
        "log.rules.summary",
        {
            "windows": result.windows_processed, "items": result.items_generated,
            "high": result.high_confidence, "medium": result.medium_confidence,
            "low": result.low_confidence, "invalid": result.invalid_items,
        },
        language=language,
    )

    return result

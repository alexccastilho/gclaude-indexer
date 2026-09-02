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

from .classification import (
    ClassifiedItem,
    WindowPage,
    load_window_pages,
    item_to_dict,
    reference_number,
    validate_item,
)
from .config import ProjectConfig
from .events import record_event
from .paths import app_root

RAW_ITEMS_FILE_NAME = "raw_items.jsonl"
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
    )


@dataclass
class _ItemInProgress:
    pages: list[WindowPage] = field(default_factory=list)
    types_per_page: list[str | None] = field(default_factory=list)
    dates_per_page: list[str | None] = field(default_factory=list)
    has_low_confidence: bool = False
    has_marked_type: bool = False


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

        for page in pages:
            text = page.text
            stripped_text = text.strip()
            first_line = stripped_text.splitlines()[0].strip() if stripped_text else ""

            found_type = self._find_type(text)
            has_protocol = self._find_protocol(text)
            blank_page = len(stripped_text) < self._rules.blank_page_threshold
            header_changed = (
                bool(first_line)
                and previous_header is not None
                and header_repeats >= 2
                and first_line != previous_header
            )

            any_signal = bool(found_type or has_protocol or previous_page_blank or header_changed)

            if current_item is None or (any_signal and not blank_page):
                if current_item is not None:
                    ready_items.append(current_item)
                current_item = _ItemInProgress()

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

        if current_item is not None:
            ready_items.append(current_item)

        return [self._finalize(item) for item in ready_items]

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
            for line in page.text.splitlines():
                stripped_line = line.strip()
                for marker in self._rules.summary_markers:
                    if stripped_line.lower().startswith(marker.lower()):
                        rest = stripped_line[len(marker):].strip(" :-")
                        if rest:
                            return rest

        limit = self._rules.summary_sentence_char_threshold
        full_text = " ".join(p.text for p in pages)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", full_text):
            sentence = sentence.strip()
            if len(sentence) > limit:
                return sentence
        return None

    def _find_author(self, pages: list[WindowPage]) -> str | None:
        for page in reversed(pages):
            lines = [line.strip() for line in page.text.splitlines()]
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
            confidence = "low"
        elif item.has_marked_type:
            confidence = "high"
        else:
            confidence = "medium"

        files = list(dict.fromkeys(p.file_name for p in pages))

        return ClassifiedItem(
            start_ref=pages[0].reference,
            end_ref=pages[-1].reference,
            start_order=reference_number(pages[0].reference),
            end_order=reference_number(pages[-1].reference),
            type=type_,
            date=date_value,
            author=self._find_author(pages),
            summary=self._find_summary(pages),
            has_table=any(p.has_table for p in pages),
            has_image=any(p.image_count > 0 for p in pages),
            engine="rules",
            confidence=confidence,
            files=files,
        )


@dataclass
class RulesClassificationResult:
    windows_processed: int = 0
    items_generated: int = 0
    invalid_items: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0


def classify_pending(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    rules: ClassificationRules | None = None,
    should_stop=None,
    language: str | None = None,
) -> RulesClassificationResult:
    """Classifies every `pending` window with the `rules` engine, writes the
    items to `raw_items.jsonl` (same format used by the `claude_code`
    engine, see `CLAUDE.md`) and marks the window as `done`."""
    rules = rules or load_rules()
    engine = RulesEngine(rules)

    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    result = RulesClassificationResult()

    pending_windows = conn.execute(
        "SELECT * FROM window WHERE status = 'pending' ORDER BY id"
    ).fetchall()

    with open(jsonl_path, "a", encoding="utf-8") as jsonl_file:
        for window in pending_windows:
            if should_stop is not None and should_stop():
                break

            pages = load_window_pages(conn, window)
            items = engine.classify(pages)

            for item in items:
                item_dict = item_to_dict(item, window["key"], window["group_key"])
                errors = validate_item(item_dict)
                if errors:
                    result.invalid_items += 1
                    record_event(
                        conn, "classification", "error", "log.rules.invalid_item",
                        {"window": window["key"], "errors": "; ".join(errors)}, language=language,
                    )
                    continue

                jsonl_file.write(json.dumps(item_dict, ensure_ascii=False) + "\n")
                result.items_generated += 1
                if item.confidence == "high":
                    result.high_confidence += 1
                elif item.confidence == "medium":
                    result.medium_confidence += 1
                else:
                    result.low_confidence += 1

            conn.execute("UPDATE window SET status = 'done' WHERE id = ?", (window["id"],))
            conn.commit()
            result.windows_processed += 1

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

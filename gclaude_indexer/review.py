# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Review mode (spec section 5, step 6): runs the `rules` engine on
everything and submits to the second engine only the windows that had some
item with low confidence. Reduces the use of the expensive engine while
keeping most of the quality gain — the second engine only steps in on the
windows where `rules` already flagged doubt.

The second engine does not replace `rules`'s items: it only adds its own
classification of the same window to `raw_items.jsonl`. Consolidation
(phase 6) already resolves the overlap by picking, per span, the fragment
with the highest confidence — so the second engine's result naturally wins
wherever it disagrees with `rules`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .classification import ClassificationEngine, load_window_pages, item_to_dict, validate_item
from .config import ProjectConfig
from .events import record_event
from .import_items import RAW_ITEMS_FILE_NAME
from .engine_rules import RulesClassificationResult, classify_pending as classify_pending_rules


@dataclass
class ReviewResult:
    windows_classified_by_rules: int
    windows_reviewed: int
    items_from_second_engine: int
    invalid_items: int


def _low_confidence_windows(jsonl_path: Path) -> set[str]:
    if not jsonl_path.exists():
        return set()

    keys = set()
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("confidence") == "low" and data.get("window"):
            keys.add(data["window"])
    return keys


def classify_with_review(
    conn, config: ProjectConfig, second_engine: ClassificationEngine, second_engine_name: str,
    should_stop=None, language: str | None = None,
) -> ReviewResult:
    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME

    rules_result: RulesClassificationResult = classify_pending_rules(
        conn, config, should_stop=should_stop, language=language
    )

    keys_to_review = _low_confidence_windows(jsonl_path)
    if not keys_to_review:
        record_event(conn, "classification", "info", "log.review.nothing_to_review", language=language)
        return ReviewResult(rules_result.windows_processed, 0, 0, 0)

    placeholders = ", ".join("?" for _ in keys_to_review)
    windows = conn.execute(
        f"SELECT * FROM window WHERE key IN ({placeholders})", tuple(keys_to_review)
    ).fetchall()

    percent = len(windows) * 100 // max(rules_result.windows_processed, 1)
    record_event(
        conn, "classification", "info", "log.review.submitting",
        {
            "reviewed": len(windows), "total": rules_result.windows_processed,
            "percent": percent, "engine": second_engine_name,
        },
        language=language,
    )

    result = ReviewResult(rules_result.windows_processed, len(windows), 0, 0)

    with open(jsonl_path, "a", encoding="utf-8") as jsonl_file:
        for window in windows:
            if should_stop is not None and should_stop():
                break

            pages = load_window_pages(conn, window)
            items = second_engine.classify(pages)

            for item in items:
                item_dict = item_to_dict(item, window["key"], window["group_key"])
                errors = validate_item(item_dict)
                if errors:
                    result.invalid_items += 1
                    record_event(
                        conn, "classification", "error", "log.review.invalid_item",
                        {"engine": second_engine_name, "window": window["key"], "errors": "; ".join(errors)},
                        language=language,
                    )
                    continue
                jsonl_file.write(json.dumps(item_dict, ensure_ascii=False) + "\n")
                result.items_from_second_engine += 1

    record_event(
        conn, "classification", "info", "log.review.summary",
        {
            "items": result.items_from_second_engine, "engine": second_engine_name,
            "invalid": result.invalid_items,
        },
        language=language,
    )
    return result

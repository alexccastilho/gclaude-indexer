# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Import and consolidation of `raw_items.jsonl` (spec section 5, step 7).

Reads the file line by line, validates it field by field (reusing
`classification.validate_item` and adding the range check within the
group), discards the duplicate from window overlap and glues an item split
across windows back together before writing it to `item`. An invalid line
becomes an error event and processing moves on to the next — it never
aborts the import.

The `item` table is always recomputed from scratch from the full
`raw_items.jsonl`: since deciding duplicate/fragment requires seeing
every item of a group at once, reimporting everything on every run is
simpler and more correct than attempting an incremental import.

Every event recorded here uses the step key `"import"` (Task 18, Phase 14 —
before this fix it was `"importacao"`, which had no `step.*.title` i18n
entry and leaked raw into the live log, in any language). `"import"` is
deliberately **not** added to `step_state.STEPS`: that tuple drives
`next_pending_step`/`step_status` for the "Run next step"/"Run all steps"
buttons, which only ever chain the five pipeline steps (scan through
classification) — the interface's own help text documents "5 etapas"
(`help.run.p1` in `i18n.py`) and import is started by its own separate
button (`run.import_and_generate`), never by "run all". Folding "import"
into `STEPS` would make it a candidate for `next_pending_step` and the
step-progress table, silently changing that behavior. Instead it gets its
own `step.import.title` i18n key and is added to the *display* whitelist
only (`web/app.py`'s `known_steps` passed to `_log.html`), so the log shows
a translated label without touching the pipeline's step machinery.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .classification import reference_number, validate_item
from .config import ProjectConfig
from .events import record_event

RAW_ITEMS_FILE_NAME = "raw_items.jsonl"
_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


@dataclass
class ImportResult:
    lines_read: int = 0
    invalid_lines: int = 0
    valid_items: int = 0
    consolidated_items: int = 0


def _validate_range_within_group(conn, item: dict) -> list[str]:
    """Rejects an item whose range is not contained in the group's actual
    pages — a sign of a made-up reference or a wrong window."""
    group = item.get("group")
    order_start = item.get("order_start")
    order_end = item.get("order_end")
    if group is None or not isinstance(order_start, int) or not isinstance(order_end, int):
        return []  # already reported by validate_item

    rows = conn.execute(
        """
        SELECT page.reference
        FROM page JOIN file ON file.id = page.file_id
        WHERE file.group_key = ?
        """,
        (group,),
    ).fetchall()

    if not rows:
        return [f"agrupador desconhecido ou sem páginas extraídas: {group!r}"]

    orders = [reference_number(row["reference"]) for row in rows]
    minimum, maximum = min(orders), max(orders)

    errors = []
    if not (minimum <= order_start <= maximum):
        errors.append(f"ordem_inicial {order_start} fora do intervalo do agrupador '{group}' ({minimum}-{maximum})")
    if not (minimum <= order_end <= maximum):
        errors.append(f"ordem_final {order_end} fora do intervalo do agrupador '{group}' ({minimum}-{maximum})")
    return errors


def _read_and_validate_lines(
    conn, jsonl_path: Path, result: ImportResult, language: str | None = None
) -> list[dict]:
    valid_items = []

    for line_number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        result.lines_read += 1

        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            result.invalid_lines += 1
            record_event(
                conn, "import", "error", "log.import.invalid_json",
                {"line": line_number, "error": str(exc)}, language=language,
            )
            continue

        if not isinstance(data, dict):
            result.invalid_lines += 1
            record_event(
                conn, "import", "error", "log.import.not_a_json_object",
                {"line": line_number}, language=language,
            )
            continue

        errors = validate_item(data) + _validate_range_within_group(conn, data)
        if errors:
            result.invalid_lines += 1
            record_event(
                conn, "import", "error", "log.import.invalid_item",
                {"line": line_number, "errors": "; ".join(errors)}, language=language,
            )
            continue

        result.valid_items += 1
        valid_items.append(data)

    return valid_items


def _types_compatible(type_a: str | None, type_b: str | None) -> bool:
    return type_a is None or type_b is None or type_a == type_b


def _merge(a: dict, b: dict) -> dict:
    """Merges two items whose ranges touch or overlap: covers both the pure
    duplicate (one range contained in the other, same content seen by two
    windows) and the item split across windows (a small fragment that just
    continues the other window's)."""
    best, worst = (
        (a, b) if _CONFIDENCE_ORDER.get(a["confidence"], 0) >= _CONFIDENCE_ORDER.get(b["confidence"], 0) else (b, a)
    )
    merged = dict(best)

    for field_name in ("type", "date", "author", "summary"):
        if not merged.get(field_name):
            merged[field_name] = worst.get(field_name)

    merged["has_table"] = bool(a.get("has_table")) or bool(b.get("has_table"))
    merged["has_image"] = bool(a.get("has_image")) or bool(b.get("has_image"))

    if a["order_start"] <= b["order_start"]:
        merged["order_start"], merged["ref_start"] = a["order_start"], a["ref_start"]
    else:
        merged["order_start"], merged["ref_start"] = b["order_start"], b["ref_start"]

    if a["order_end"] >= b["order_end"]:
        merged["order_end"], merged["ref_end"] = a["order_end"], a["ref_end"]
    else:
        merged["order_end"], merged["ref_end"] = b["order_end"], b["ref_end"]

    files_a = [name.strip() for name in str(a.get("files", "")).split(",") if name.strip()]
    files_b = [name.strip() for name in str(b.get("files", "")).split(",") if name.strip()]
    merged["files"] = ", ".join(dict.fromkeys(files_a + files_b))

    return merged


def _consolidate(items: list[dict]) -> list[dict]:
    by_group: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_group[item["group"]].append(item)

    consolidated: list[dict] = []

    for group_items in by_group.values():
        sorted_items = sorted(group_items, key=lambda p: (p["order_start"], p["order_end"]))
        current: dict | None = None

        for item in sorted_items:
            if (
                current is not None
                and item["order_start"] <= current["order_end"]
                and _types_compatible(current.get("type"), item.get("type"))
            ):
                current = _merge(current, item)
            else:
                if current is not None:
                    consolidated.append(current)
                current = dict(item)

        if current is not None:
            consolidated.append(current)

    consolidated.sort(key=lambda p: (p["group"], p["order_start"]))
    return consolidated


def _write_items(conn, items: list[dict]) -> None:
    conn.execute("DELETE FROM item")
    for item in items:
        conn.execute(
            """
            INSERT INTO item
                (group_key, start_ref, end_ref, start_order, end_order,
                 type, date, author, summary, has_table, has_image, engine, confidence, files)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["group"],
                item["ref_start"],
                item["ref_end"],
                item["order_start"],
                item["order_end"],
                item.get("type"),
                item.get("date"),
                item.get("author"),
                item.get("summary"),
                int(bool(item.get("has_table"))),
                int(bool(item.get("has_image"))),
                item["engine"],
                item["confidence"],
                item.get("files", ""),
            ),
        )
    conn.commit()


def import_and_consolidate(conn, config: ProjectConfig, language: str | None = None) -> ImportResult:
    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    result = ImportResult()

    if not jsonl_path.exists():
        record_event(conn, "import", "warning", "log.import.file_not_found", language=language)
        return result

    valid_items = _read_and_validate_lines(conn, jsonl_path, result, language=language)
    consolidated = _consolidate(valid_items)
    result.consolidated_items = len(consolidated)

    _write_items(conn, consolidated)

    record_event(
        conn,
        "import",
        "info",
        "log.import.summary",
        {
            "lines": result.lines_read, "invalid": result.invalid_lines,
            "valid": result.valid_items, "consolidated": result.consolidated_items,
        },
        language=language,
    )

    return result

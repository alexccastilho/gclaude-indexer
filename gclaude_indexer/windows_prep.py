# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Preparation of classification windows (section 5, step 5).

Each group has its pages (already extracted in phase 4) sliced into
overlapping windows, one row per window in the `window` table. A window
that already exists (same `key`, computed from the group and the position)
is not created again — resumable without duplicating work.

Until 1.x the windows were also written as `windows/*.txt` for the manual
Claude Code engine, which no longer exists (2.0.0): nothing writes those
files now, and `cleanup_legacy_window_files` removes the ones an older
version left behind.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .paths import natural_sort_key, resolve_within


@dataclass
class WindowsResult:
    created: int = 0
    existing: int = 0


def sanitize_group_name(name: str) -> str:
    """Normalize a group key into a safe filename prefix.

    Replaces sequences of non-word, non-hyphen characters with underscores,
    strips underscores from the ends, and falls back to "grupo" if the result
    is empty. Used to generate window file names and keys.
    """
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "grupo"


def window_spans(page_count: int, window_size: int, overlap: int) -> list[tuple[int, int]]:
    """`(start, end)` of each window over a group of `page_count` pages.

    `start` is 0-based and `end` exclusive, so the block is `pages[start:end]`.
    Extracted from `prepare_windows` so `update_plan.py` can
    predict the layout without duplicating the arithmetic: a plan that
    counts windows differently from the step that creates them is a plan
    that lies.

    The step has a floor of 1. An overlap greater than or equal to the
    window size would otherwise give a step of zero and loop forever;
    configuration validation should prevent it, but a pure function is
    where the guard costs nothing.
    """
    if page_count <= 0:
        return []

    step = max(1, window_size - overlap)
    spans: list[tuple[int, int]] = []
    start = 0
    while start < page_count:
        end = min(start + window_size, page_count)
        spans.append((start, end))
        if end == page_count:
            break
        start += step
    return spans


def window_key(base_name: str, start: int, end: int) -> str:
    """The window's identity in the `window` table: group plus position."""
    return f"{base_name}::{start + 1:06d}-{end:06d}"


def pages_for_group(conn, group_key: str, with_text: bool = True):
    """Pages of the group, in the order the windows and `RulesEngine` cite.

    Ordered by natural path and page number, not by `page.id`.
    The two coincide in a project built in one pass, because extraction
    writes group by group in that same order — but not after an update,
    where a re-extracted file's pages get the highest ids and would jump
    to the end of the group. Natural ordering is not expressible in SQL,
    so the final sort happens here, with the key `extraction` already uses.
    """
    # `with_text=False` for callers that only need where each page
    # is — the text is most of the table (hundreds of MB in a large collection).
    columns = (
        "page.*" if with_text
        else "page.id, page.file_id, page.number, page.reference"
    )
    rows = conn.execute(
        f"""
        SELECT {columns}, file.name AS file_name, file.relative_path AS file_relative_path
        FROM page
        JOIN file ON file.id = page.file_id
        WHERE file.group_key = ?
        """,
        (group_key,),
    ).fetchall()

    return sorted(
        rows,
        key=lambda row: (natural_sort_key(row["file_relative_path"]), row["number"]),
    )


def group_page_counts(conn, only_extracted_groups: bool = False) -> dict[str, int]:
    """How many pages each group has: the length of `pages_for_group`
    without reading a single page.

    The quality summary and the gap report wanted only this number,
    and got it by loading every page with its text (`pages_for_group`) and
    sorting it — on over a hundred thousand pages in a Drive-synced
    database, the Execution screen took over a minute to open and the steps table, refreshed every
    two seconds, as long. The count reads `idx_page_file_id` only."""
    sql = """
        SELECT file.group_key, COUNT(*)
        FROM page
        JOIN file ON file.id = page.file_id
        WHERE file.group_key IS NOT NULL
    """
    if only_extracted_groups:
        sql += """
          AND file.group_key IN (
              SELECT DISTINCT group_key FROM file
              WHERE group_key IS NOT NULL AND status = 'extracted'
          )
        """
    sql += " GROUP BY file.group_key"
    return {group: count for group, count in conn.execute(sql)}


def group_page_positions(conn, with_text: bool = True) -> dict[str, list]:
    """Every group's pages in group order — index 0 is position 1.

    The one definition of "position in the group" that `item.start_order`
    uses, shared by the import range check, the index's physical-page map,
    the gap report and the quality coverage. Each used to rebuild it from
    the number inside `page.reference`, which in a "biblioteca" collection
    restarts at 1 in every file.
    """
    groups = [
        row["group_key"]
        for row in conn.execute("SELECT DISTINCT group_key FROM file WHERE group_key IS NOT NULL")
    ]
    return {group: pages_for_group(conn, group, with_text=with_text) for group in groups}


def prepare_windows(
    conn, config: ProjectConfig, should_stop: Callable[[], bool] | None = None, language: str | None = None
) -> WindowsResult:
    group_keys = [
        row["group_key"]
        for row in conn.execute(
            "SELECT DISTINCT group_key FROM file WHERE group_key IS NOT NULL AND status = 'extracted'"
        ).fetchall()
    ]

    window_size = config.pages_per_window
    result = WindowsResult()

    for group_key in group_keys:
        if should_stop is not None and should_stop():
            break

        # Only where each page is, never its text: no engine reads a window
        # from a file any more.
        pages = pages_for_group(conn, group_key, with_text=False)
        page_count = len(pages)
        if page_count == 0:
            continue

        base_name = sanitize_group_name(group_key)
        new_rows: list[tuple] = []
        # One query per group, not one per window.
        existing_keys = {
            row[0] for row in conn.execute("SELECT key FROM window WHERE group_key = ?", (group_key,))
        }

        for start, end in window_spans(page_count, window_size, config.overlap):
            page_block = pages[start:end]
            start_ref = page_block[0]["reference"]
            end_ref = page_block[-1]["reference"]
            key = window_key(base_name, start, end)

            if key in existing_keys:
                result.existing += 1
            else:
                new_rows.append((key, group_key, start_ref, end_ref))
                result.created += 1

        # One commit per group, not per window.
        if new_rows:
            conn.executemany(
                """
                INSERT INTO window (key, group_key, start_ref, end_ref, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                new_rows,
            )
            conn.commit()

    record_event(
        conn,
        "windows",
        "info",
        "log.windows.summary",
        {"created": result.created, "existing": result.existing},
        language=language,
    )

    return result


# Exactly the name an older version gave a window file (`<group>_j<start>-<end>.txt`,
# see `invalidation._window_file_name`). Nothing else in `windows/` is ours.
LEGACY_WINDOW_FILE = re.compile(r".+_j\d{4,}-\d{4,}\.txt")


def cleanup_legacy_window_files(output_folder: Path | str, should_stop: Callable[[], bool] | None = None) -> int:
    """Removes the `windows/*.txt` left by the manual Claude Code engine
    (gone in 2.0.0) and the folder itself when that leaves it empty.

    Only names in the exact pattern are touched, each one resolved inside
    `windows/` (a name that escapes it, or a link out, is left alone), and
    the folder is only removed if empty: anything the user put there stays.
    Runs inside "Import and generate reports" (background, with Stop), never
    when a project is opened: in a Drive-synced folder this can be thousands
    of deletions. Returns how many files were removed.
    """
    windows_dir = Path(output_folder) / "windows"
    try:
        names = [entry.name for entry in os.scandir(windows_dir) if entry.is_file(follow_symlinks=False)]
    except OSError:
        return 0
    removed = 0
    for name in names:
        if should_stop is not None and should_stop():
            return removed
        if not LEGACY_WINDOW_FILE.fullmatch(name):
            continue
        try:
            target = resolve_within(windows_dir, name)
            if target.parent != windows_dir.resolve():
                continue
            target.unlink()
            removed += 1
        except (ValueError, OSError):
            continue
    try:
        windows_dir.rmdir()  # fails by itself unless empty
    except OSError:
        pass
    return removed


def mark_answered_windows(conn, output_folder: Path | str) -> int:
    """Marks as `done` the pending windows that already have a line in
    `raw_items.jsonl`: what the manual Claude Code engine answered before it
    was removed (2.0.0). Used once, when a project saved with that engine is
    opened, so the automatic classification does not redo them. Returns how
    many windows were marked."""
    from .import_items import RAW_ITEMS_FILE_NAME  # late import avoids a cycle

    jsonl_path = Path(output_folder) / RAW_ITEMS_FILE_NAME
    try:
        # `split("\n")`, not `splitlines()` (1.5.9, see `import_items`).
        lines = jsonl_path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return 0
    answered: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = data.get("window") if isinstance(data, dict) else None
        if isinstance(key, str) and key:
            answered.add(key)
    if not answered:
        return 0
    marked = 0
    keys = sorted(answered)
    # In slices: SQLite limits the number of variables in one statement.
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        cursor = conn.execute(
            f"UPDATE window SET status = 'done' WHERE status = 'pending' AND key IN ({placeholders})", chunk
        )
        marked += cursor.rowcount
    conn.commit()
    return marked

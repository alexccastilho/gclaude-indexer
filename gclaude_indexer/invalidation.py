# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Applying an `UpdatePlan`. The only thing in the project that deletes.

Phase 17. Everything here runs inside one transaction: either the database
ends consistent in the new state, or it stays consistent in the old one. A
half-applied invalidation — windows discarded but the pages that fed them
still numbered the old way — is worse than no update at all, because
nothing downstream can tell it happened.

Disk deletions are deliberately kept *outside* that transaction, and
strictly after it. A `.txt` unlinked before the commit could be lost to a
rollback that keeps its `window` row, leaving a window whose text file no
longer exists — a state the classification step cannot recover from on its
own. The doomed paths are collected while the transaction runs and
unlinked only once it has committed.

What it does NOT touch: `item`. `import_items` already wipes and rebuilds
that table on every run, so invalidating it here would be work done twice.

What it *does* have to touch, and for the opposite reason: the classified
items in `<output>/raw_items.jsonl`. That file is append-only and is
re-read whole on every import, so nothing else in the pipeline ever
removes anything from it — the rebuild of `item` faithfully rebuilds the
stale lines too. See `_prune_raw_items`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .import_items import RAW_ITEMS_FILE_NAME
from .paths import resolve_within
from .update_plan import UpdatePlan, build_update_plan, detect_changes
from .windows_prep import sanitize_group_name, window_key, window_spans


class PlanExpired(RuntimeError):
    """The folder changed between the diagnosis and the confirmation.

    The plan is a photograph, and Drive keeps syncing while the user reads
    the screen. Applying a stale plan would write one thing having shown
    another, so this is a safety property rather than an error path: the
    caller is expected to rebuild the plan and show it again.

    Nothing at all is written on this path — not even an event row. That
    is why the check uses `detect_changes` rather than
    `build_update_plan`, which can commit a layout-mismatch warning.
    """


@dataclass
class InvalidationResult:
    """What the application actually did — counted from the rows the
    database reported affected, not from what the plan predicted. The two
    can legitimately differ (a window the plan expected was never written
    to the table), and the honest number is the one that happened.

    `windows_orphaned` counts the `.txt` files whose row was deleted but
    whose unlink failed — see the loop at the end of `apply_update_plan`
    for why that is survivable and why it must still be visible.

    `items_pruned` counts the `raw_items.jsonl` lines dropped because the
    window that produced them was discarded; `prune_failures` counts the
    prunes that could not be written (0 or 1 today — there is one file).
    A failed prune is the more serious of the two failures here: it
    yields a wrong index, not an orphan file."""

    windows_deleted: int = 0
    windows_orphaned: int = 0
    items_pruned: int = 0
    prune_failures: int = 0
    pages_deleted: int = 0
    files_removed: int = 0
    files_reset: int = 0
    files_renumbered: int = 0


def _window_file_name(key: str) -> str | None:
    """The `.txt` name `windows_prep` wrote for the window with this `key`.

    The key is `{base}::{start + 1:06d}-{end:06d}` and the file is
    `{base}_j{start + 1:04d}-{end:04d}.txt` — two different widths for the
    same pair of numbers, so the name has to be rebuilt rather than
    derived by substitution. Deriving it from the *stored* key instead of
    from a freshly computed span matters in the `discard_whole_group`
    case: there the derived layout is precisely what cannot be trusted.

    Returns `None` for a key that does not follow the pattern (a row
    written by hand, or by a version that predates it). An unrecognized
    key costs an orphan text file; guessing a name for it could cost
    somebody else's.
    """
    base, separator, position = key.rpartition("::")
    if not separator:
        return None
    start_text, dash, end_text = position.partition("-")
    if not dash or not start_text.isdigit() or not end_text.isdigit():
        return None
    return f"{base}_j{int(start_text):04d}-{int(end_text):04d}.txt"


def _doom(windows_dir: Path, file_name: str | None, doomed: list[Path]) -> None:
    """Queues a window's text file for deletion after the commit.

    Containment is checked here, before the path is ever handed to
    `unlink`. A window's name derives from the group key, which under
    `name_pattern` grouping comes from a regular expression matched
    against a filename the collection brought in — that makes it data, not
    a constant. `resolve_within` refuses anything that would land outside
    the windows folder; on refusal the row still goes, the file stays. An
    orphan text file is a trivial cost, a delete outside the windows
    folder is not.
    """
    if file_name is None:
        return
    try:
        doomed.append(resolve_within(windows_dir, file_name))
    except ValueError:
        return


def _group_page_count(conn: sqlite3.Connection, group_key: str) -> int:
    """Pages the group actually has, counted from the `page` table.

    Never `file.page_count`: the column and the rows disagree in ordinary
    operation (a failed extraction leaves the old count behind, a re-scan
    nulls it without deleting pages), so the column would give a
    different geometry from the one the index was actually built with.

    The `duplicate` filter makes this count identical to the one
    `update_plan._stored_geometry` sums — the geometry the plan's
    `first_affected_window` is an index into. Without it the two could
    disagree, and an index computed over one layout and applied to
    another names the wrong window. (`pages_for_group` has no such
    filter; it is not the reference here, the plan's geometry is.)
    """
    return conn.execute(
        "SELECT COUNT(*) FROM page JOIN file ON file.id = page.file_id"
        " WHERE file.group_key = ? AND file.status != 'duplicate'",
        (group_key,),
    ).fetchone()[0]


def _delete_whole_group(
    conn: sqlite3.Connection,
    group_key: str,
    windows_dir: Path,
    doomed: list[Path],
) -> int:
    """Discards every window row the table holds for the group.

    Reached when the plan flagged `discard_whole_group`: the stored layout
    contradicts the one derived from the pages, so the derived spans are
    exactly the thing that cannot be used to find the rows. Deleting span
    by span would reach at most as many keys as the derived layout has —
    36 stored against 2 derived would leave 34 stale windows standing,
    inside the safety net meant to prevent that.

    The rows are read before they are deleted because their keys are the
    only record of which files on disk belong to them, and of which
    `raw_items.jsonl` lines were classified from them.
    """
    for row in conn.execute(
        "SELECT key FROM window WHERE group_key = ?", (group_key,)
    ).fetchall():
        _doom(windows_dir, _window_file_name(row["key"]), doomed)

    return conn.execute(
        "DELETE FROM window WHERE group_key = ?", (group_key,)
    ).rowcount


def _prune_raw_items(
    output_dir: Path, discarded_keys: set[str], discarded_groups: set[str]
) -> int:
    """Drops from `raw_items.jsonl` every item classified from a discarded
    window. Returns how many lines were dropped.

    `classify_pending` appends to this file and `import_and_consolidate`
    re-reads it whole on every run, so an item left behind by a discarded
    window keeps being imported — with sheet references that now point at
    different pages. `_validate_range_within_group` does not catch it,
    because the range still fits inside the group; `_consolidate` then
    merges the stale line into the live items, unions the `files` lists,
    and can impose its own type, date, author or summary through the
    confidence tie-break. A stale item touching no live item simply enters
    the index as a document that is not in the collection any more.

    Filtering at read time instead would not work. Window keys are
    positional and get reused: once invalidation deletes window `X` and
    `prepare_windows` recreates it, classification appends new lines under
    that same key while the old ones are still in the file, and nothing
    distinguishes the two. The file has to be pruned.

    Two criteria, because the two discard branches know different things.

    `discarded_keys` is the span-by-span branch: those windows are named
    individually, and only their own lines are stale.

    `discarded_groups` is the `discard_whole_group` branch, and it matches
    on the line's `group` field (`item_to_dict` writes
    `"group": window["group_key"]` on every line). Every line of that
    group is stale by definition — the whole group is going back to the
    model — so there is no need to name its windows one by one. That also
    makes the branch self-healing: if an earlier prune failed and left
    lines behind, their window rows are gone by now and their keys could
    never be reconstructed, but their `group` still identifies them.

    Only a line that positively parses as an object matching one of those
    two criteria is dropped. Unparseable lines and blank lines are kept:
    `import_and_consolidate` already reports those as errors, and
    quietly deleting what cannot be read is not this function's call.

    The file is streamed rather than read whole. Holding a multi-gigabyte
    `raw_items.jsonl` in memory to rewrite it is the one way this
    function could plausibly raise `MemoryError`, and it runs after the
    commit, where raising at all is the thing to avoid.
    """
    path = output_dir / RAW_ITEMS_FILE_NAME
    if not (discarded_keys or discarded_groups) or not path.exists():
        # A project that has never been classified has no file here. That
        # is the normal state before the first run, not an error.
        return 0

    def _is_stale(line: str) -> bool:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(item, dict):
            return False
        return (
            item.get("window") in discarded_keys
            or item.get("group") in discarded_groups
        )

    # Written beside the real file and renamed over it only once it is
    # complete: a half-written `raw_items.jsonl` would lose the items of
    # windows that are still valid, and those exist nowhere else.
    temporary = path.with_name(path.name + ".tmp")
    dropped = 0
    try:
        # `newline=""` on both sides: the kept lines are copied through
        # byte for byte, instead of having their line endings rewritten
        # by the platform translation on the way in and out.
        with open(path, "r", encoding="utf-8", newline="") as source, open(
            temporary, "w", encoding="utf-8", newline=""
        ) as target:
            for line in source:
                if _is_stale(line):
                    dropped += 1
                else:
                    target.write(line)

        if dropped:
            temporary.replace(path)
        else:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError):
        # `ValueError` covers `UnicodeDecodeError` from a corrupted file:
        # the read is as much a failure path as the write, and both have
        # to reach the caller's counted-and-warned channel rather than
        # escape past a commit that already succeeded.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dropped


def _record_removals(conn: sqlite3.Connection, plan: UpdatePlan) -> int:
    """Keeps a trace of what left the collection.

    `removed_file` is project state, not a clearable log: the report needs
    to be able to say a document used to be there and no longer is, which
    no other table can answer once the `file` row is gone.
    """
    moment = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for change in plan.removed:
        conn.execute(
            "INSERT INTO removed_file (relative_path, name, removed_at)"
            " VALUES (?, ?, ?)",
            (change.relative_path, change.name, moment),
        )
    return len(plan.removed)


def _file_id(conn: sqlite3.Connection, relative_path: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM file WHERE relative_path = ?", (relative_path,)
    ).fetchone()
    return None if row is None else row["id"]


def apply_update_plan(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    plan: UpdatePlan,
    language: str | None = None,
) -> InvalidationResult:
    """Invalidates exactly what the plan describes, in one transaction.

    Raises `PlanExpired` — writing nothing — when the source folder no
    longer matches the one the plan was built from.

    `plan` is used for one thing only: its fingerprint, as the witness
    that the user confirmed this folder. Everything actually applied is
    read from a plan derived here, for the reason spelled out below.

    The fingerprint is therefore checked twice, against two different
    guarantees. Neither check subsumes the other.
    """
    # First check, before anything can write. `detect_changes`, not
    # `build_update_plan`: the latter can commit a layout-mismatch
    # warning event, and an expired plan must leave the project
    # byte-for-byte untouched. This is also the cheap half of the work —
    # no group geometry, no window counting.
    _changes, _unchanged, fingerprint = detect_changes(conn, config)
    if fingerprint != plan.fingerprint:
        raise PlanExpired(plan.fingerprint)

    # Only now, and never the caller's plan from here on.
    # `first_affected_window` is an index into the layout that existed
    # when the plan was photographed, while the spans sliced below are
    # derived from the database as it stands at this instant. The
    # fingerprint covers the *source folder*, not the index — another
    # connection, or a step run from the progress screen, can move the
    # index underneath a plan whose fingerprint still matches. Slicing
    # fresh spans with stale indices would delete the wrong windows.
    # Walking the folder twice is the price; applying is a rare action
    # the user explicitly confirmed.
    current = build_update_plan(conn, config, language=language)

    # Second check, and a different guarantee: `current` came from its
    # own walk of the folder, so it is not the object the first check
    # validated. A Drive-synced file that blinks out of existence between
    # the two walks puts an entry in `current.removed` that the user
    # never saw and never confirmed — and this function would then delete
    # its pages, its `file` row, and log it as gone. The first check
    # protects "an expired plan writes nothing"; this one protects
    # "nothing is applied from a snapshot the user did not confirm".
    if current.fingerprint != plan.fingerprint:
        raise PlanExpired(plan.fingerprint)

    result = InvalidationResult()
    output_dir = Path(config.output_folder)
    windows_dir = output_dir / "windows"
    doomed_files: list[Path] = []
    discarded_keys: set[str] = set()
    discarded_groups: set[str] = set()

    try:
        conn.execute("BEGIN")

        # Windows first, and before any page is deleted: the plan's
        # `first_affected_window` indexes the layout derived from the
        # pages as they are *now*. Deleting pages first would shift that
        # layout and make the index name a different window.
        for group in current.groups:
            if group.discard_whole_group:
                result.windows_deleted += _delete_whole_group(
                    conn, group.group_key, windows_dir, doomed_files
                )
                # By group, not by key: every line of this group is
                # stale, and naming its windows one by one would lose
                # the lines an earlier failed prune left behind, whose
                # rows are gone and whose keys nothing can reconstruct.
                discarded_groups.add(group.group_key)
                continue

            page_count = _group_page_count(conn, group.group_key)
            base_name = sanitize_group_name(group.group_key)
            spans = window_spans(
                page_count, config.pages_per_window, config.overlap
            )

            # Always a slice, never an index: `first_affected_window` may
            # equal `len(spans)`, which means nothing is discarded — the
            # commonest happy path, an append whose last window was full.
            for start, end in spans[group.first_affected_window:]:
                key = window_key(base_name, start, end)
                result.windows_deleted += conn.execute(
                    "DELETE FROM window WHERE key = ?", (key,)
                ).rowcount
                _doom(
                    windows_dir,
                    f"{base_name}_j{start + 1:04d}-{end:04d}.txt",
                    doomed_files,
                )
                # Queued whether or not a row was actually deleted: a
                # `raw_items.jsonl` line under this key is stale either
                # way, and the row may have gone in an earlier apply.
                discarded_keys.add(key)

        for change in current.removed:
            file_id = _file_id(conn, change.relative_path)
            if file_id is None:
                continue
            result.pages_deleted += conn.execute(
                "DELETE FROM page WHERE file_id = ?", (file_id,)
            ).rowcount
            conn.execute("DELETE FROM file WHERE id = ?", (file_id,))
        result.files_removed = _record_removals(conn, current)

        for change in current.changed:
            file_id = _file_id(conn, change.relative_path)
            if file_id is None:
                continue
            result.pages_deleted += conn.execute(
                "DELETE FROM page WHERE file_id = ?", (file_id,)
            ).rowcount
            # Back to 'discovered': the bytes changed, so the converted
            # output on disk is stale and OCR has to run again. This is
            # the expensive half of the update, and the only half that
            # should be expensive.
            conn.execute(
                "UPDATE file SET status = 'discovered', page_count = NULL,"
                " error = NULL WHERE id = ?",
                (file_id,),
            )
            result.files_reset += 1

        changed_paths = {change.relative_path for change in current.changed}
        for group in current.groups:
            for relative_path in group.files_to_renumber:
                if relative_path in changed_paths:
                    continue
                file_id = _file_id(conn, relative_path)
                if file_id is None:
                    continue
                deleted = conn.execute(
                    "DELETE FROM page WHERE file_id = ?", (file_id,)
                ).rowcount
                if not deleted:
                    continue
                result.pages_deleted += deleted
                # Back to 'converted', not 'discovered': this file's bytes
                # did not change, only its position in the group did. The
                # OCR output is still in <output>/converted/, so
                # extraction re-reads it and renumbers without paying OCR
                # again. Sending it to 'discovered' instead would silently
                # make every update as expensive as a full reindex.
                conn.execute(
                    "UPDATE file SET status = 'converted' WHERE id = ?",
                    (file_id,),
                )
                result.files_renumbered += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Only now, with the database committed. Raising here would tell the
    # caller an update failed that in fact succeeded — the rows are
    # already gone — so the failure is swallowed. It is not swallowed
    # silently: `prepare_windows` skips writing a `.txt` that already
    # exists (`if not file_path.exists()`), so a survivor left by a Drive
    # lock can be reused as the text of a freshly created window with the
    # same span. The warning below is what makes that visible until the
    # regeneration step stops skipping.
    orphans: list[str] = []
    for path in doomed_files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            orphans.append(path.name)
    result.windows_orphaned = len(orphans)

    # Same side of the commit as the unlinks, and for a sharper version
    # of the same reason. Pruning before the commit would, on a
    # rollback, delete the items of windows that still exist and are
    # still marked `done` — nothing would ever reclassify them, so those
    # items would be gone for good.
    prune_error: str | None = None
    try:
        result.items_pruned = _prune_raw_items(
            output_dir, discarded_keys, discarded_groups
        )
    except (OSError, ValueError) as error:
        # Worse than a surviving `.txt`: this one produces a wrong index
        # rather than an orphan file, so it is reported in those terms.
        result.prune_failures = 1
        prune_error = str(error)

    # The log must never be able to invalidate a committed update, so
    # even recording it is guarded — `record_event` writes to the
    # database and to the on-disk log.
    try:
        if prune_error is not None:
            record_event(
                conn,
                "update",
                "warning",
                "log.update.raw_items_prune_failed",
                {"error": prune_error},
                language=language,
            )

        if orphans:
            record_event(
                conn,
                "update",
                "warning",
                "log.update.orphan_window_file",
                {"count": len(orphans), "files": ", ".join(sorted(orphans))},
                language=language,
            )

        record_event(
            conn,
            "update",
            "info",
            "log.update.applied",
            {
                "windows": result.windows_deleted,
                "removed": result.files_removed,
                "reset": result.files_reset,
                "renumbered": result.files_renumbered,
            },
            language=language,
        )
    except (sqlite3.Error, OSError):
        pass

    return result

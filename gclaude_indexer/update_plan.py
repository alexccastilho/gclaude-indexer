# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Comparing the source folder with the index, without writing anything.

Phase 17. The plan is the read-only half of the update: it answers "what
changed in the folder, and what would that cost", and nothing it does
touches the index — no file, page, window or item row is written, read
or moved. That is what lets it run every time the Execution screen
opens.

One deliberate exception, and only one: when a group's stored window
layout contradicts the layout derived from its pages, the plan records a
warning event. An event is a clearable log, not project state (see the
`removed_file` comment in `db.py` for that distinction), so the
guarantee above still holds for everything the update could damage — but
the write is real, and staying silent about a geometry the plan cannot
trust would be worse.

**Detection is cheap on purpose.** Hashing every file of a Drive-synced
collection on each open would force the client to download files the user
never asked for. Size and modification time decide first; the hash is
computed only for the few candidates that differ. The hash still has the
last word, because Drive rewrites the modification time of files whose
bytes never changed — the same lesson already recorded in `staleness.py`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .paths import natural_sort_key
from .scanning import compute_hash, derive_group_key, source_files
from .windows_prep import window_spans


class SourceFolderUnavailable(RuntimeError):
    """The source folder cannot be read, so no plan can be trusted.

    Without this the plan would read an unreachable folder as "every
    document was removed" and offer to delete the whole index. A
    disconnected Drive, a moved folder or a changed drive letter must
    never reach the confirmation screen as a removal.
    """


@dataclass(frozen=True)
class FileChange:
    relative_path: str
    kind: str  # "new" | "changed" | "removed"
    name: str
    size: int


def _fingerprint(entries: list[tuple[str, int, float]]) -> str:
    """Cheap identity of the folder as the plan saw it.

    Re-checked before the invalidation writes: applying a plan built from
    a folder that has since changed would write one thing having shown
    another.
    """
    digest = hashlib.sha256()
    for relative_path, size, mtime in sorted(entries):
        digest.update(f"{relative_path}|{size}|{mtime:.6f}\n".encode("utf-8"))
    return digest.hexdigest()


def detect_changes(
    conn: sqlite3.Connection, config: ProjectConfig
) -> tuple[list[FileChange], int, str]:
    """New, changed and removed files; how many are unchanged; and the
    folder's fingerprint.

    Raises `SourceFolderUnavailable` when the source folder is missing, or
    empty while the index is not.
    """
    source_dir = Path(config.source_folder)
    if not source_dir.is_dir():
        raise SourceFolderUnavailable(str(source_dir))

    output_dir = Path(config.output_folder).resolve()
    paths = source_files(source_dir.resolve(), output_dir)

    known = {
        row["relative_path"]: row
        for row in conn.execute("SELECT relative_path, size, sha256, mtime FROM file")
    }

    if not paths and known:
        raise SourceFolderUnavailable(str(source_dir))

    changes: list[FileChange] = []
    unchanged = 0
    entries: list[tuple[str, int, float]] = []
    seen: set[str] = set()

    for path in paths:
        relative_path = path.relative_to(source_dir.resolve()).as_posix()
        stat = path.stat()
        entries.append((relative_path, stat.st_size, stat.st_mtime))
        seen.add(relative_path)

        row = known.get(relative_path)
        if row is None:
            changes.append(FileChange(relative_path, "new", path.name, stat.st_size))
            continue

        if row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
            unchanged += 1
            continue

        # Size or time moved. Only now is reading the bytes worth it.
        if compute_hash(path) == row["sha256"]:
            unchanged += 1
            continue

        changes.append(FileChange(relative_path, "changed", path.name, stat.st_size))

    for relative_path in sorted(set(known) - seen):
        changes.append(
            FileChange(relative_path, "removed", Path(relative_path).name, 0)
        )

    return changes, unchanged, _fingerprint(entries)


@dataclass(frozen=True)
class GroupInvalidation:
    """What one group loses when the update is applied.

    `first_divergent_page` is 0-based and counted over the group's
    concatenated pages, the same coordinate `window_spans` works in.

    `discard_whole_group` exists because an index cannot say "everything
    the table holds for this group". `first_affected_window` is a
    position in the layout *derived* from the current pages, so deleting
    by `spans[first_affected_window:]` can only ever reach windows that
    layout describes. When the stored layout disagrees with the derived
    one, the rows that need deleting are precisely the ones the derived
    layout does not account for — 36 stored against 2 derived would
    delete at most 2 keys, and possibly none that exist, leaving 34
    stale windows behind. The flag lets the caller delete by
    `group_key` instead of span by span.

    When it is set, `windows_discarded` is the number of rows actually
    stored for the group — what will really be deleted — and
    `windows_kept` is 0. Reporting the derived count there would show
    the user 2 when 36 windows are going back to the model, understating
    exactly the cost this flag exists to make visible.
    """

    group_key: str
    first_divergent_page: int
    first_affected_window: int
    windows_discarded: int
    windows_kept: int
    files_to_renumber: tuple[str, ...]
    discard_whole_group: bool = False


@dataclass(frozen=True)
class UpdatePlan:
    new: tuple[FileChange, ...]
    changed: tuple[FileChange, ...]
    removed: tuple[FileChange, ...]
    groups: tuple[GroupInvalidation, ...]
    unchanged_count: int
    fingerprint: str

    @property
    def is_empty(self) -> bool:
        return not (self.new or self.changed or self.removed)

    @property
    def files_needing_ocr(self) -> int:
        """Only these pay OCR again. The files that merely get renumbered
        are re-read from `<output>/converted/`."""
        return len(self.new) + len(self.changed)

    @property
    def windows_to_reclassify(self) -> int:
        """Windows certain to go back to the model.

        Exact, and deliberately not the whole answer: the windows a *new*
        document will add depend on its page count, which nothing knows
        before extraction. The screen says so rather than estimating.
        """
        return sum(group.windows_discarded for group in self.groups)


def _infer_window_size(old_spans: list[tuple[int, int]]) -> int:
    """Window size implied by a layout, when the caller did not say.

    Exact whenever the group has two or more windows: a second window
    exists only if the first one did not already reach the end, so
    `spans[0]` is necessarily full-size and its width *is* the window
    size. With a single window the layout is `(0, page_count)` and the
    two cases are indistinguishable — a group shorter than one window and
    a group exactly one window long look identical. There we return a
    size one larger, which reads as "truncated" and discards that single
    window: the conservative answer, and the right one except in the
    knife-edge case where the collection happens to be exactly one window
    long.
    """
    if len(old_spans) == 1:
        start, end = old_spans[0]
        return end - start + 1
    return max(end - start for start, end in old_spans)


def first_affected_window(
    old_spans: list[tuple[int, int]],
    first_divergent_page: int,
    window_size: int | None = None,
) -> int:
    """Index of the first window that must be discarded.

    Everything from this index on goes back to the model; everything
    before it is preserved. The return value may equal `len(old_spans)`,
    meaning *nothing* is discarded — callers must slice (`spans[index:]`,
    which is empty) rather than index.

    Two conditions, not one. The obvious one is the window that covers the
    first divergent page: the loop below.

    The one that is easy to miss: the **last** window of a group is
    clamped by the total page count (`min(start + window_size,
    page_count)`), so it can change extent even when no page before it
    moved. The fallback covers that, and it is reached only when
    `first_divergent_page >= page_count` — no span satisfies
    `end > first_divergent_page` otherwise, since the last span always
    ends exactly at `page_count`.

    That is the pure-append case in all but one degenerate shape. A
    removed or changed file *can* reach the fallback if its own stored
    page count is zero and it sorts last: the divergence is then its
    start offset, which equals `page_count`. The outcome stays correct —
    a file with no pages contributes nothing, so the surviving layout is
    identical either way — but the branch is better described as "the
    divergence lies at or past the last page" than as "an append".

    In that branch the last window survives exactly when it was
    *full-size*. If `end == start + window_size`, then `start +
    window_size <= old_count <= new_count`, so the new layout re-derives
    the identical `end` at the same `start` — same span, same key, same
    pages, and discarding it would re-run the model over text that
    provably did not change. If instead it was truncated (`end - start <
    window_size`, i.e. it hit the clamp), more pages make `end` grow, the
    key changes, and it must go.

    Worked example, both halves: 500 pages at window 16 / overlap 2 gives
    36 windows whose last is `(490, 500)` — truncated, 10 pages wide — so
    appending 10 pages discards exactly 1 and preserves 35. But 30 pages
    at the same settings gives `[(0, 16), (14, 30)]`, whose last is
    full-size; appending there discards nothing.

    `window_size` is optional only so the pure function stays callable
    from a test with a layout and nothing else; pass it whenever the
    configuration is at hand, because a one-window group cannot be read
    back from its layout (see `_infer_window_size`).
    """
    if not old_spans:
        return 0

    for index, (_start, end) in enumerate(old_spans):
        if end > first_divergent_page:
            return index

    if window_size is None:
        window_size = _infer_window_size(old_spans)

    last_start, last_end = old_spans[-1]
    if last_end - last_start < window_size:
        return len(old_spans) - 1
    return len(old_spans)


def _divergence_page(
    stored: list[tuple[str, int]], intended: list[str], changed: set[str]
) -> int:
    """First page position at which the group stops matching the index.

    `stored` is `(relative_path, page_count)` in the group's current page
    order; `intended` the paths the group will have, naturally sorted.
    """
    page_offset = 0
    for index, (relative_path, page_count) in enumerate(stored):
        if index >= len(intended):
            return page_offset
        if intended[index] != relative_path or relative_path in changed:
            return page_offset
        page_offset += page_count or 0

    return page_offset


def _files_to_renumber(
    stored: list[tuple[str, int]],
    first_divergent_page: int,
    changed_paths: set[str],
    removed_paths: set[str],
) -> tuple[str, ...]:
    """Untouched files whose pages must nonetheless be renumbered.

    Bounded by the divergence on purpose. The invalidation step deletes
    the pages of every file named here so they can be re-inserted with new
    sheet numbers; naming every unchanged file of the group — as a first
    draft of this module did — would delete the pages of documents nothing
    touched and force the whole collection back through extraction and
    OCR. That is the exact cost the incremental update exists to avoid.

    A file that *starts* before the divergence keeps its pages and its
    numbering, because everything ahead of it is unchanged. A file that
    starts at or after it is shifted by whatever happened at the
    divergence, so its sheet numbers move even though its bytes did not.
    Files that changed or were removed are not listed: their pages are
    handled by re-extraction and deletion respectively. Nor is a file
    with no pages — a failed extraction leaves one behind, and it has
    nothing to renumber and no converted output to be re-read from.
    """
    renumber: list[str] = []
    page_offset = 0
    for relative_path, page_count in stored:
        if (
            page_count > 0
            and page_offset >= first_divergent_page
            and relative_path not in changed_paths
            and relative_path not in removed_paths
        ):
            renumber.append(relative_path)
        page_offset += page_count
    return tuple(renumber)


def _stored_window_count(conn: sqlite3.Connection, group_key: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM window WHERE group_key = ?", (group_key,)
    ).fetchone()[0]


def _layout_disagrees(stored_count: int, derived_count: int) -> bool:
    """Whether the layout on record contradicts the one derived here.

    Nothing else in this module reads the `window` table: the counts it
    reports are predictions about a layout recomputed from the pages. A
    prediction with nothing confirming it is how a wrong geometry stays
    invisible, so this compares the derived span count against the
    windows actually stored for the group.

    A group with *no* stored windows is not a disagreement. It has simply
    never been through `prepare_windows` — normal before the first
    classification — and there is no layout to contradict. Reporting it
    as a mismatch would discard nothing while telling the user that
    `derived_count` windows are going back to the model, inflating the
    very number this feature exists to keep honest.
    """
    return stored_count != 0 and stored_count != derived_count


def _stored_geometry(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[str, int]]]:
    """Each group's `(relative_path, page_count)` in the group's page order.

    The page counts are counted from the `page` table, never read from
    `file.page_count`. The two disagree in ordinary operation, and the
    windows that actually exist were built by
    `windows_prep.pages_for_group`, which counts page rows — so reading
    the column here would give this module a different geometry from the
    one the index was built with, and from the one the invalidation step
    will slice against.

    Two routes to the disagreement, both reachable without anything going
    wrong at the user's end:

    - `conversion.py` writes `page_count = N` on success; if extraction
      then fails, it writes only `status = 'failed'` and leaves that `N`
      behind with zero page rows. One unreadable PDF is enough.
    - `scanning._update_file` sets `page_count = NULL` on a re-scan
      without deleting the file's pages — the same disagreement in the
      opposite direction.

    A file with no pages stays in the list with a count of zero rather
    than being dropped. It contributes nothing to the geometry, but
    `_divergence_page` compares this list positionally against the
    intended membership, and silently omitting a file would shift every
    position after it and place the divergence too early.
    """
    rows = conn.execute(
        """
        SELECT file.relative_path AS relative_path,
               file.group_key     AS group_key,
               COUNT(page.id)     AS page_rows
        FROM file
        LEFT JOIN page ON page.file_id = file.id
        WHERE file.group_key IS NOT NULL AND file.status != 'duplicate'
        GROUP BY file.id
        """
    ).fetchall()

    stored_by_group: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        stored_by_group.setdefault(row["group_key"], []).append(
            (row["relative_path"], row["page_rows"])
        )

    # Natural order, not insertion order: this must be the same sequence
    # `pages_for_group` concatenates, or the page offsets computed here
    # would name positions the windows never had.
    for group_key in stored_by_group:
        stored_by_group[group_key].sort(key=lambda pair: natural_sort_key(pair[0]))

    return stored_by_group


def _intended_membership(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    source_dir: Path,
    new_files: list[FileChange],
    removed_paths: set[str],
) -> list[tuple[str, str]]:
    """`(relative_path, group_key)` the collection will have after the update."""
    members: list[tuple[str, str]] = []

    for row in conn.execute(
        "SELECT relative_path, group_key FROM file"
        " WHERE group_key IS NOT NULL AND status != 'duplicate'"
    ):
        if row["relative_path"] not in removed_paths:
            members.append((row["relative_path"], row["group_key"]))

    for change in new_files:
        group_key = derive_group_key(change.relative_path, source_dir, config)
        if group_key is not None:
            members.append((change.relative_path, group_key))

    return members


def build_update_plan(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    language: str | None = None,
) -> UpdatePlan:
    """The whole plan: what changed, and what invalidating it would cost.

    `language` is used only for the layout-mismatch warning described in
    the module docstring; it falls back to `DEFAULT_LANGUAGE` like every
    other `record_event` caller that cannot see the interface's choice.
    """
    changes, unchanged, fingerprint = detect_changes(conn, config)

    by_kind: dict[str, list[FileChange]] = {"new": [], "changed": [], "removed": []}
    for change in changes:
        by_kind[change.kind].append(change)

    changed_paths = {change.relative_path for change in by_kind["changed"]}
    removed_paths = {change.relative_path for change in by_kind["removed"]}

    source_dir = Path(config.source_folder).resolve()
    stored_by_group = _stored_geometry(conn)

    intended_by_group: dict[str, list[str]] = {}
    for relative_path, group_key in _intended_membership(
        conn, config, source_dir, by_kind["new"], removed_paths
    ):
        intended_by_group.setdefault(group_key, []).append(relative_path)
    for group_key in intended_by_group:
        intended_by_group[group_key].sort(key=natural_sort_key)

    groups: list[GroupInvalidation] = []
    for group_key, stored in stored_by_group.items():
        intended = intended_by_group.get(group_key, [])
        touched = any(
            path in changed_paths or path in removed_paths for path, _ in stored
        ) or intended != [path for path, _ in stored]
        if not touched:
            continue

        divergent_page = _divergence_page(stored, intended, changed_paths)
        page_count = sum(count for _, count in stored)
        old_spans = window_spans(page_count, config.pages_per_window, config.overlap)

        stored_windows = _stored_window_count(conn, group_key)

        if _layout_disagrees(stored_windows, len(old_spans)):
            # The derived layout is not the one on record, so no claim
            # about which windows survive can be trusted. Discarding the
            # whole group is the conservative-correct answer; the event
            # puts the cost in the log instead of letting it be silent.
            # Refusing the plan outright would block the user in a state
            # that reclassifying fully recovers.
            #
            # The counts below are the stored ones, not the derived
            # ones: the caller will delete by `group_key`, so what goes
            # back to the model is every row the table holds.
            record_event(
                conn,
                "update",
                "warning",
                "log.update.layout_mismatch",
                {
                    "group": group_key,
                    "stored": stored_windows,
                    "derived": len(old_spans),
                },
                language=language,
            )
            discard_whole_group = True
            affected = 0
            discarded = stored_windows
            kept = 0
        else:
            discard_whole_group = False
            affected = first_affected_window(
                old_spans, divergent_page, config.pages_per_window
            )
            discarded = max(0, len(old_spans) - affected)
            kept = affected

        groups.append(
            GroupInvalidation(
                group_key=group_key,
                first_divergent_page=divergent_page,
                first_affected_window=affected,
                windows_discarded=discarded,
                windows_kept=kept,
                files_to_renumber=_files_to_renumber(
                    stored, divergent_page, changed_paths, removed_paths
                ),
                discard_whole_group=discard_whole_group,
            )
        )

    return UpdatePlan(
        new=tuple(by_kind["new"]),
        changed=tuple(by_kind["changed"]),
        removed=tuple(by_kind["removed"]),
        groups=tuple(groups),
        unchanged_count=unchanged,
        fingerprint=fingerprint,
    )

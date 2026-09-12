# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Comparing the source folder with the index, without writing anything.

Phase 17. The plan is the read-only half of the update: it answers "what
changed in the folder, and what would that cost", and nothing it does can
alter the project. That is what lets it run every time the Execution
screen opens.

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
    """

    group_key: str
    first_divergent_page: int
    first_affected_window: int
    windows_discarded: int
    windows_kept: int
    files_to_renumber: tuple[str, ...]


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
    moved. The fallback covers that, and it is reached only in the
    pure-append case — no span satisfies `end > first_divergent_page`
    only when `first_divergent_page >= page_count`, and `_divergence_page`
    returns the full page count only when every stored file matched the
    intended list positionally and none of them changed. A removal cannot
    land here: it puts the divergence at the removed file's start offset,
    which is below `page_count`, so the loop fires instead.

    On a pure append the last window survives exactly when it was
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
    handled by re-extraction and deletion respectively.
    """
    renumber: list[str] = []
    page_offset = 0
    for relative_path, page_count in stored:
        if (
            page_offset >= first_divergent_page
            and relative_path not in changed_paths
            and relative_path not in removed_paths
        ):
            renumber.append(relative_path)
        page_offset += page_count or 0
    return tuple(renumber)


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


def build_update_plan(conn: sqlite3.Connection, config: ProjectConfig) -> UpdatePlan:
    """The whole plan: what changed, and what invalidating it would cost."""
    changes, unchanged, fingerprint = detect_changes(conn, config)

    by_kind: dict[str, list[FileChange]] = {"new": [], "changed": [], "removed": []}
    for change in changes:
        by_kind[change.kind].append(change)

    changed_paths = {change.relative_path for change in by_kind["changed"]}
    removed_paths = {change.relative_path for change in by_kind["removed"]}

    source_dir = Path(config.source_folder).resolve()
    stored_rows = conn.execute(
        "SELECT relative_path, group_key, page_count FROM file"
        " WHERE group_key IS NOT NULL AND status != 'duplicate'"
    ).fetchall()

    stored_by_group: dict[str, list[tuple[str, int]]] = {}
    for row in stored_rows:
        stored_by_group.setdefault(row["group_key"], []).append(
            (row["relative_path"], row["page_count"] or 0)
        )
    # Natural order, not insertion order: this must be the same sequence
    # `windows_prep.pages_for_group` concatenates, or the page offsets
    # computed here would name positions the windows never had.
    for group_key in stored_by_group:
        stored_by_group[group_key].sort(key=lambda pair: natural_sort_key(pair[0]))

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
        affected = first_affected_window(
            old_spans, divergent_page, config.pages_per_window
        )

        groups.append(
            GroupInvalidation(
                group_key=group_key,
                first_divergent_page=divergent_page,
                first_affected_window=affected,
                windows_discarded=max(0, len(old_spans) - affected),
                windows_kept=affected,
                files_to_renumber=_files_to_renumber(
                    stored, divergent_page, changed_paths, removed_paths
                ),
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

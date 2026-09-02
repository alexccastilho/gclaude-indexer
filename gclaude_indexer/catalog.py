# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Catalog of known projects, for the "Projects" screen (spec section 6).

Each project already keeps its own state in `project.db`, inside its output
folder — this catalog only remembers "which output folders have I opened",
so they can be listed and reopened.

It used to live only at `%LOCALAPPDATA%\\GClaudeIndexer\\projects.json`,
one per machine. That is where the reported problem came from: the projects
themselves are in Google Drive and sync perfectly, but the list of them did
not, so opening the same Drive on a second computer showed an empty
Projects screen with every project sitting right there on disk.

So the catalog can now live in a **folder on the Drive that the user
chooses** (`settings.shared_catalog_folder`), and then every machine
signed into that Drive sees, edits and deletes the same projects. The local
file stays as the fallback for an unconfigured machine, and as the store
for anything the shared catalog cannot describe.

**Paths are stored twice, and the relative one wins.** Section 11.5 warns
that the drive letter changes between machines — Drive for Desktop mounts
as `H:` here and `G:` there — so an absolute path copied from one computer
is meaningless on the next. Every entry therefore also carries its output
folder *relative to the catalog folder itself* (`..\\..\\Saidas\\Case X`),
which is identical on both machines because both paths are inside the same
synced tree. Reading resolves the relative path first and falls back to
the absolute one, so a project stored outside the Drive still opens on the
machine that has it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path

from . import settings
from .paths import machine_local_folder

CATALOG_FILE_NAME = "projects.json"


@dataclass
class CatalogEntry:
    # Field names translated to English in Task 9c: the catalog on disk
    # (`projects.json`) was empty at the time — nothing to strand by
    # changing the keys read back via `CatalogEntry(**item)`.
    id: int
    name: str
    output_folder: str
    created_at: str
    # Output folder relative to the folder holding the catalog. Empty when
    # the catalog is local (there is nothing portable to be relative to) or
    # when the project sits on a different drive from the catalog. Written
    # by `register_project`, read by `resolved_output_folder`.
    relative_output_folder: str = ""

    def resolved_output_folder(self, catalog_folder: Path | None) -> str:
        """Where this project actually is, on *this* machine.

        The relative path is tried first and only accepted if it points at
        something that exists: that is what makes the same entry open on a
        computer whose Drive is mounted under a different letter. Falling
        back to the absolute path covers projects stored outside the synced
        folder, which are correct exactly on the machine that holds them.
        """
        if catalog_folder is not None and self.relative_output_folder:
            candidate = (Path(catalog_folder) / self.relative_output_folder).resolve()
            try:
                if candidate.is_dir():
                    return str(candidate)
            except OSError:
                pass
        return self.output_folder

    def is_available(self, catalog_folder: Path | None) -> bool:
        """Whether this machine can currently reach the project's folder.

        A shared catalog legitimately lists projects that live on another
        computer's local disk; those are shown, and shown as unavailable,
        rather than hidden or presented as broken.
        """
        try:
            return Path(self.resolved_output_folder(catalog_folder)).is_dir()
        except OSError:
            return False


def _local_catalog_path() -> Path:
    return machine_local_folder() / CATALOG_FILE_NAME


def catalog_folder() -> Path | None:
    """Folder holding the catalog in use, or `None` when it is the local one."""
    return settings.shared_catalog_folder()


def catalog_path() -> Path:
    """The catalog file in use: the shared one when configured and
    reachable, the machine-local one otherwise."""
    shared = catalog_folder()
    if shared is not None:
        return shared / CATALOG_FILE_NAME
    return _local_catalog_path()


def _read(path: Path) -> list[CatalogEntry]:
    """Entries in `path`, tolerating anything that is not what we wrote.

    A catalog in a synced folder is written by other machines and other
    versions of this program: an unknown key must not raise
    `TypeError: unexpected keyword argument`, and a missing one must not
    lose the whole file. Unreadable entries are skipped individually.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    known = {item.name for item in fields(CatalogEntry)}
    required = {"id", "name", "output_folder", "created_at"}
    entries: list[CatalogEntry] = []
    for item in data:
        if not isinstance(item, dict) or not required.issubset(item):
            continue
        try:
            entries.append(CatalogEntry(**{k: v for k, v in item.items() if k in known}))
        except (TypeError, ValueError):
            continue
    return _with_unique_ids(entries)


def _with_unique_ids(entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """Reassigns ids that collide.

    Two machines can register a project offline and each pick the same
    `max + 1`; when the folder syncs, the losing entry would become
    unreachable because `find_project` returns the first match. Renumbering
    on read keeps every project openable. The id is a handle for the URL,
    not an identity — the output folder is the identity — so moving one is
    safe.
    """
    seen: set[int] = set()
    next_free = max((entry.id for entry in entries), default=0) + 1
    for entry in entries:
        if entry.id in seen:
            entry.id = next_free
            next_free += 1
        seen.add(entry.id)
    return entries


def list_projects() -> list[CatalogEntry]:
    """Every known project.

    With a shared catalog configured, that is the shared file plus any
    local-only entry it does not already contain — a machine that indexed
    something before the shared folder was set up does not lose it, and
    does not get it twice either.
    """
    shared_folder = catalog_folder()
    if shared_folder is None:
        return _read(_local_catalog_path())

    entries = _read(shared_folder / CATALOG_FILE_NAME)
    known_folders = {_folder_key(entry.output_folder) for entry in entries}
    for entry in _read(_local_catalog_path()):
        if _folder_key(entry.output_folder) not in known_folders:
            entries.append(entry)
    return _with_unique_ids(entries)


def _folder_key(folder: str) -> str:
    """Comparable form of a path, for "is this the same project".

    Case-folded because Windows paths are case-insensitive, and two entries
    differing only in case are the same folder — which is how a project
    could be registered twice.
    """
    try:
        return str(Path(folder).resolve()).casefold()
    except OSError:
        return str(folder).casefold()


def _relative_to_catalog(output_folder: str, folder: Path | None) -> str:
    """`output_folder` relative to the catalog folder, or `""`.

    `os.path.relpath`, not `Path.relative_to`: the project is normally a
    *sibling* of the catalog folder rather than inside it, and only the
    former can express that (`..\\..\\Saidas\\Case X`). Returns `""` when
    the two are on different drives, where no relative path exists.
    """
    if folder is None:
        return ""
    try:
        return os.path.relpath(str(Path(output_folder).resolve()), str(Path(folder).resolve()))
    except (ValueError, OSError):
        # ValueError: different Windows drives — the project is not in the
        # synced tree, so the absolute path is all there is, and it is
        # correct on the machine that holds it.
        return ""


def _write(entries: list[CatalogEntry]) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_project(name: str, output_folder: str) -> CatalogEntry:
    """Adds a project to the catalog, or returns the entry that already
    exists for the same output folder (avoids duplicating on recreate/reopen)."""
    entries = list_projects()
    folder = catalog_folder()
    key = _folder_key(output_folder)

    for entry in entries:
        if _folder_key(entry.resolved_output_folder(folder)) == key or _folder_key(entry.output_folder) == key:
            # An entry registered before a shared folder was configured has
            # no relative path yet. Filling it in here is what makes an
            # existing project become visible on the other machine, without
            # asking the user to recreate anything.
            if folder is not None and not entry.relative_output_folder:
                entry.relative_output_folder = _relative_to_catalog(entry.output_folder, folder)
                _write(entries)
            return entry

    new_id = max((entry.id for entry in entries), default=0) + 1
    entry = CatalogEntry(
        id=new_id,
        name=name,
        output_folder=str(output_folder),
        created_at=datetime.now().isoformat(timespec="seconds"),
        relative_output_folder=_relative_to_catalog(output_folder, folder),
    )
    entries.append(entry)
    _write(entries)
    return entry


def find_project(project_id: int) -> CatalogEntry | None:
    """The project, with `output_folder` already resolved for this machine.

    Resolving here rather than at each call site is deliberate: every
    caller — opening the database, taking the lock, checking the sync
    signal, deleting — needs the path *this* computer can use, and an entry
    written on a machine whose Drive is mounted under a different letter
    would otherwise hand each of them a path that does not exist.
    """
    folder = catalog_folder()
    for entry in list_projects():
        if entry.id == project_id:
            return replace(entry, output_folder=entry.resolved_output_folder(folder))
    return None


def remove_project(project_id: int) -> None:
    """Takes the project out of the catalog (explicit user request —
    "delete project"). Does not touch the output folder: whether that also
    gets deleted is decided by `gclaude_indexer.deletion.delete_project`,
    called before this by the web route.

    Removed from both files when a shared catalog is in use: an entry left
    behind in the local one would come back on the next listing, through
    the merge in `list_projects`."""
    remaining = [entry for entry in list_projects() if entry.id != project_id]
    _write(remaining)

    shared_folder = catalog_folder()
    if shared_folder is None:
        return
    local = _read(_local_catalog_path())
    removed_folders = {
        _folder_key(entry.output_folder)
        for entry in _read(shared_folder / CATALOG_FILE_NAME) + local
        if entry.id == project_id
    }
    if not removed_folders:
        return
    kept_local = [entry for entry in local if _folder_key(entry.output_folder) not in removed_folders]
    if len(kept_local) != len(local):
        path = _local_catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(entry) for entry in kept_local], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def adopt_local_projects() -> int:
    """Copies the machine's local entries into the shared catalog.

    Called right after the user points at a shared folder: without it, the
    projects they already have would only appear on the *other* computer
    after being opened again here. Returns how many were added.
    """
    folder = catalog_folder()
    if folder is None:
        return 0

    shared = _read(folder / CATALOG_FILE_NAME)
    known = {_folder_key(entry.output_folder) for entry in shared}
    added = 0
    for entry in _read(_local_catalog_path()):
        if _folder_key(entry.output_folder) in known:
            continue
        entry.relative_output_folder = _relative_to_catalog(entry.output_folder, folder)
        shared.append(entry)
        added += 1

    if added:
        _write(_with_unique_ids(shared))
    return added

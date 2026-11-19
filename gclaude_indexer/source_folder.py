# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The source folder as the scan and the update plan both see it.

Which files make up the collection (the walk, with its deadlines and the
folders it skips), what a file's content identity is (the hash) and which
group it belongs to. The scan and the update plan must agree on every one
of these — two walks that disagree would make the plan describe a folder
the scan does not see — so they live here, apart from either.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .config import ProjectConfig
from .file_types import is_system_file
from .paths import holds_generated_output
from .worker_pool import CallTimedOut, call_with_deadline

HASH_BLOCK_SIZE = 1024 * 1024


def compute_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(HASH_BLOCK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_group_key(relative_path: str, source_dir: Path, config: ProjectConfig) -> str | None:
    """Derives the file's group key according to `config.group_mode`."""
    parts = Path(relative_path).parts

    if config.group_mode == "all_together":
        return source_dir.name

    if config.group_mode == "subfolder":
        # More than one segment: the first is the immediate subfolder. A
        # file loose at the root of the source folder forms its own group.
        return parts[0] if len(parts) > 1 else source_dir.name

    if config.group_mode == "name_pattern":
        name = Path(relative_path).name
        match = re.search(config.group_pattern, name)
        if not match:
            return None
        if match.groups():
            return match.group(1)
        return match.group(0)

    raise ValueError(f"unknown group_mode: {config.group_mode!r}")


FOLDER_LISTING_DEADLINE_SECONDS = 600.0
STAT_DEADLINE_SECONDS = 600.0
MAX_CONSECUTIVE_TIMEOUTS = 3


class SourceFolderStalled(RuntimeError):
    """A folder of the collection never answered its listing, twice.

    Raised, never skipped: a walk that left a folder out would describe a
    collection without those files, and the update plan reads a missing
    file as a removed one."""

    def __init__(self, folder: Path):
        super().__init__(str(folder))
        self.folder = folder


def _list_folder(folder: Path) -> list[os.DirEntry]:
    """`os.scandir(folder)` with a deadline. A Google Drive folder
    that never answers its listing froze the walk, and with it the scan's
    count, for good. One retry, on a fresh thread, then
    `SourceFolderStalled`."""
    for attempt in (1, 2):
        try:
            return call_with_deadline(
                lambda: list(os.scandir(folder)), deadline=FOLDER_LISTING_DEADLINE_SECONDS,
            )
        except CallTimedOut:
            if attempt == 2:
                raise SourceFolderStalled(folder) from None
    raise AssertionError("unreachable")


class SourceFile(NamedTuple):
    """One file of the collection as the folder listing reported it."""

    path: Path
    size: int
    mtime: float


def relative_text(path: Path, root: Path) -> str:
    """`str(path.relative_to(root))`, by cutting the text of `root` off the
    front when `path` is written under it. `Path.relative_to` was
    most of the time of a walk over a large Google Drive folder, pure Python
    work; the slice gives the same text. Anything not written as a plain
    child of `root` takes the original, exact route."""
    text = str(path)
    prefix = str(root)
    if not prefix.endswith(("\\", "/")):
        prefix += os.sep
    if text.startswith(prefix) and len(text) > len(prefix):
        return text[len(prefix):]
    return str(path.relative_to(root))


class SourceListing(list):
    """A lista de `SourceFile` de uma varredura, com as pastas que ela pulou
    por serem saída gerada (a própria saída, outro projeto, um Conjunto):
    `skipped_folders` guarda cada uma como texto relativo à origem, com
    `/`. O plano de atualização usa isso para tirar do índice o que um
    1.x antigo indexou dali."""

    skipped_folders: list[str]

    def __init__(self, items=(), skipped_folders=()):
        super().__init__(items)
        self.skipped_folders = list(skipped_folders)


def walk_source_stats(
    source_dir: Path,
    output_dir: Path,
    on_found: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SourceListing:
    """Path, size and modification time of every file of the collection, in
    the order the scan walks them.

    `os.scandir` rather than `rglob` + `stat`: on Windows the directory
    listing already carries each file's size **and modification time**
    (`DirEntry.stat()` reads them from the listing, with no call to the
    drive). On a Google Drive folder with over a hundred thousand files the
    extra `stat` per file is what turns the walk into minutes: 1.8.1 took
    the update check of a large collection from minutes to seconds by using
    the listing's own values, which match the stored ones on every
    unchanged file, so nothing has to be hashed again.

    `on_found(n)` is called with the running count after each file — the
    Execution screen shows it, so a long walk never looks frozen.
    `should_stop` interrupts the walk (pause); what was found so far is
    returned.
    """
    output_dir = output_dir.resolve()
    found: list[SourceFile] = []
    skipped: list[str] = []
    pending = [source_dir]
    while pending:
        if should_stop is not None and should_stop():
            break
        current = pending.pop()
        if current.resolve() == output_dir:
            if current != source_dir:
                skipped.append(relative_text(current, source_dir).replace(os.sep, "/"))
            continue
        try:
            entries = _list_folder(current)
        except OSError:
            continue  # unreadable folder: same as `rglob`, which skips it
        # Saída gerada de qualquer projeto (`project.db`) ou de um Conjunto
        # (marcador) nunca é documento. A pasta de origem em si não entra
        # na regra: pular a raiz esvaziaria o acervo inteiro.
        if current != source_dir and holds_generated_output(entry.name for entry in entries):
            skipped.append(relative_text(current, source_dir).replace(os.sep, "/"))
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file():
                    continue
                info = entry.stat()
            except OSError:
                continue
            path = Path(entry.path)
            if is_system_file(path):
                continue
            found.append(SourceFile(path, info.st_size, info.st_mtime))
            if on_found is not None:
                on_found(len(found))
    found.sort(key=lambda item: relative_text(item.path, source_dir).lower())
    return SourceListing(found, skipped)


def walk_source_files(
    source_dir: Path,
    output_dir: Path,
    on_found: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[tuple[Path, int]]:
    """`(path, size)` of every file of the collection (see
    `walk_source_stats`, which also keeps the modification time)."""
    return [
        (item.path, item.size)
        for item in walk_source_stats(source_dir, output_dir, on_found, should_stop)
    ]


def source_files(source_dir: Path, output_dir: Path) -> list[Path]:
    """Files of the collection, in the order the scan walks them.

    Extracted from `scan()` so the update plan
    (`update_plan.py`) walks by exactly the same criteria. Two walks that
    disagree would make the plan describe a folder the scan does not see.
    """
    return [item.path for item in walk_source_stats(source_dir, output_dir)]

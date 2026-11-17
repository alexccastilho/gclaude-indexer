# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Scan of the source folder (section 5, step 1 of the specification).

Walks the source folder recursively, computes each file's hash, derives the
group key according to the configuration, and writes the inventory to the
`file` table. A file with no content change under the same path is only
recounted (idempotency — acceptance criteria 1 and 2); when its size and
modification time match the inventory, its bytes are not even read. A file whose content
already exists under another path is written with `status = 'duplicate'`
(not reprocessed, but present in the inventory — without this row, the
progress bar never reached 100%). An extension outside the configured list
is marked `skipped`, with an event.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from .config import ProjectConfig
from .db import BatchWriter
from .events import record_event
from .file_types import (
    HEAD_BYTES,
    REASON_NOT_SELECTED,
    REASON_UNREADABLE,
    index_decision,
    is_extension_allowed,
    is_unreadable_placeholder,
    is_waiting_component,
    name_decision,
    needs_head,
)
from .i18n import DEFAULT_LANGUAGE, translate
from .paths import holds_generated_output
from .worker_pool import CallTimedOut, StepStalledError, call_with_deadline, deadline_for_size

HASH_BLOCK_SIZE = 1024 * 1024


@dataclass
class ScanResult:
    total_found: int = 0
    discovered: int = 0
    updated: int = 0
    ignored: int = 0
    skipped: int = 0
    # Em espera de componente, editados: bytes novos gravados, sem voltar à
    # fila (não contam em `updated`).
    waiting_updated: int = 0
    # Ignorados desta execução, por motivo (`file_types.REASON_*`).
    ignored_by_reason: dict[str, int] = field(default_factory=dict)


def compute_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(HASH_BLOCK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_head(path: Path) -> bytes:
    """Só o começo do arquivo: o bastante para `index_decision` decidir sem
    baixar um arquivo grande do Drive."""
    with open(path, "rb") as file:
        return file.read(HEAD_BYTES)


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


def _list_known_files(conn: sqlite3.Connection) -> tuple[set[str], dict[str, sqlite3.Row]]:
    rows = conn.execute("SELECT relative_path, size, sha256, mtime, status, error FROM file").fetchall()
    # "" é o hash de quem foi ignorado sem ser lido: não identifica conteúdo.
    known_hashes = {row["sha256"] for row in rows if row["sha256"]}
    by_path = {row["relative_path"]: row for row in rows}
    return known_hashes, by_path


def _insert_file(
    conn: sqlite3.Connection,
    relative_path: str,
    name: str,
    extension: str,
    size: int,
    file_hash: str,
    mtime: float,
    group_key: str | None,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO file
            (relative_path, name, extension, size, sha256, mtime, group_key, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (relative_path, name, extension, size, file_hash, mtime, group_key, status, error),
    )
    # Back in the folder, so no longer "removed" — otherwise `review.md`
    # would go on listing a document that is right there in the index.
    conn.execute("DELETE FROM removed_file WHERE relative_path = ?", (relative_path,))


def _update_file(
    conn: sqlite3.Connection,
    relative_path: str,
    name: str,
    extension: str,
    size: int,
    file_hash: str,
    mtime: float,
    group_key: str | None,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE file
        SET name = ?, extension = ?, size = ?, sha256 = ?, mtime = ?, group_key = ?,
            status = ?, error = ?, page_count = NULL, needs_ocr = 0, ocr_lang = NULL, language = NULL,
            ocr_failed = CASE WHEN ? = 'skipped' THEN 0 ELSE ocr_failed END
        WHERE relative_path = ?
        """,
        (name, extension, size, file_hash, mtime, group_key, status, error, status, relative_path),
    )


# Files the operating system, the sync client or an editor writes into a
# folder without anyone putting them there. Matched by exact name (lower
# case) or by prefix, and never indexed.
_SYSTEM_FILE_NAMES = frozenset({
    "desktop.ini", "thumbs.db", "ehthumbs.db", ".ds_store",
    ".dropbox", ".dropbox.attr", "albumartsmall.jpg",
    ".dropbox", ".dropbox.attr", "folder.jpg", "albumartsmall.jpg",
})
_SYSTEM_FILE_PREFIXES = ("~$", ".~lock.", "albumart_")


def is_system_file(path: Path) -> bool:
    """Whether `path` is operating-system or sync bookkeeping.

    Deliberately a small, explicit list rather than a rule like "hidden
    files": a collection can legitimately contain a document whose name
    starts with a dot, and refusing to index it because of that would be a
    silent loss of the user's own material. Everything here is a file no
    person put in the folder.

    Bookkeeping files (such as desktop.ini) that slip in through the "all
    extensions" option are never indexed; otherwise a `desktop.ini` could
    become item number one of an index, summarised as
    "operating system configuration file".
    """
    name = path.name.lower()
    if name in _SYSTEM_FILE_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _SYSTEM_FILE_PREFIXES)


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


def scan(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    should_stop: Callable[[], bool] | None = None,
    language: str | None = None,
    files: list[Path] | list[SourceFile] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """`should_stop`: a no-argument function returning True to cooperatively
    interrupt between one file and the next (see `run_control.py`) —
    the step is resumable, so stopping here loses nothing.

    `language`: interface language for the events recorded here (Task 12,
    Phase 14) — falls back to `DEFAULT_LANGUAGE` in `record_event` itself
    when not given.

    `files`: the walk already made by the caller (`walk_source_stats`, in
    order; bare paths are accepted too), so a large folder is not walked a second time before the
    first file is hashed. `None` walks it here.

    `on_progress(files_done, bytes_done)`: called before each file and once
    at the end, so the progress bar can follow a scan that adds no rows —
    a second scan of an unchanged folder, which the row count saw as
    "0 / N" from start to finish."""
    source_dir = Path(config.source_folder).resolve()
    output_dir = Path(config.output_folder).resolve()

    known_hashes, known_paths = _list_known_files(conn)

    result = ScanResult()

    if files is None:
        files = walk_source_stats(source_dir, output_dir)

    writer = BatchWriter(conn)
    try:
        _scan_files(
            writer, conn, config, source_dir, files, known_hashes, known_paths, result,
            should_stop, language, on_progress,
        )
        writer.flush()
    except BaseException as exc:
        if isinstance(exc, sqlite3.Error):
            writer.discard()
        else:
            try:
                writer.flush()  # what was already checked stays checked
            except Exception:
                writer.discard()
        raise

    _record_ignored_summary(conn, result, language)
    record_event(
        conn,
        "scan",
        "info",
        "log.scan.summary",
        {
            "new": result.discovered, "updated": result.updated,
            "ignored": result.ignored, "unchanged": result.skipped,
        },
        language=language,
    )

    return result


def _record_ignored_summary(conn: sqlite3.Connection, result: ScanResult, language: str | None) -> None:
    """One event per run with the count by reason (it used to be one warning
    per file, which buried the log of a large folder). Google shortcuts get
    their own, because the fix is something the person has to do."""
    if not result.ignored_by_reason:
        return
    lang = language or DEFAULT_LANGUAGE
    detail = "; ".join(
        f"{translate(lang, 'ignored.reason.' + reason)}: {count}"
        for reason, count in sorted(result.ignored_by_reason.items(), key=lambda item: (-item[1], item[0]))
    )
    record_event(
        conn, "scan", "warning", "log.scan.ignored_summary",
        {"total": sum(result.ignored_by_reason.values()), "detail": detail}, language=language,
    )
    google = result.ignored_by_reason.get("google_doc", 0)
    if google:
        record_event(conn, "scan", "warning", "log.scan.google_docs", {"count": google}, language=language)


def _scan_files(
    writer: BatchWriter, conn, config: ProjectConfig, source_dir: Path, files, known_hashes, known_paths,
    result: ScanResult, should_stop, language, on_progress,
) -> None:
    """The scan's loop. 1.5.6: every call that touches a file (`stat`, the
    hash) has a deadline, so a file Google Drive never answers costs that
    file, not the scan; writes go through `BatchWriter` (see `db.py`)."""
    bytes_done = 0
    consecutive_timeouts = 0

    for item in files:
        if should_stop is not None and should_stop():
            break
        # The walk's own size and time when the caller has them (see
        # `walk_source_stats`); a bare path is still asked for its `stat`.
        listed = item if isinstance(item, SourceFile) else None
        path = item.path if listed is not None else item

        if on_progress is not None:
            on_progress(result.total_found, bytes_done)

        result.total_found += 1

        relative_path = path.relative_to(source_dir).as_posix()
        name = path.name
        extension = path.suffix.lower()
        existing_row = known_paths.get(relative_path)
        size = None
        try:
            if listed is not None:
                size, mtime = listed.size, listed.mtime
            else:
                file_stat = call_with_deadline(path.stat, deadline=STAT_DEADLINE_SECONDS)
                size = file_stat.st_size
                mtime = file_stat.st_mtime
            unchanged = (
                existing_row is not None
                and existing_row["size"] == size
                and existing_row["mtime"] == mtime
            )
            file_hash = None
            reason = None
            if not unchanged:
                # A decisão vem antes do hash: o que não pode ser indexado
                # não é lido (nem baixado do Drive, no caso de um vídeo).
                reason = _ignore_reason(path, name, config)
                if reason is None:
                    file_hash = call_with_deadline(
                        compute_hash, path, deadline=deadline_for_size(size),
                    )
        except CallTimedOut as timeout:
            # Left out of this scan, untouched in the inventory: the next
            # scan looks at it again. Several in a row with nothing in
            # between is the drive, not the file — stop instead of walking
            # the whole collection one deadline at a time.
            consecutive_timeouts += 1
            minutes = max(1, round(timeout.args[0] / 60))
            writer.add(lambda c, name=name, minutes=minutes: record_event(
                c, "scan", "warning", "log.scan.file_timed_out", {"name": name, "minutes": minutes},
                language=language, commit=False,
            ))
            if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                raise StepStalledError(
                    translate(language or DEFAULT_LANGUAGE, "log.pool_stalled", name=name)
                ) from None
            continue
        except OSError as error:
            # Lido e recusado (placeholder do Drive só na nuvem sem rede,
            # arquivo preso por outro programa, apagado no meio): o mesmo
            # tratamento do arquivo que não respondeu. Nada é gravado sobre
            # ele, então a próxima varredura o confere de novo; o plano de
            # atualização faz o mesmo (`update_plan._PlanReader`).
            writer.add(lambda c, name=name, error=error: record_event(
                c, "scan", "warning", "log.scan.file_unreadable",
                {"name": name, "error": error.strerror or str(error)},
                language=language, commit=False,
            ))
            if existing_row is None and size is not None:
                # Novo: entra no inventário sem hash e sem data, para a
                # contagem de arquivos da etapa bater com a pasta (como a
                # cópia, `duplicate`). Sem data, a próxima varredura o lê de
                # novo; um indexado que falha fica como estava.
                extension_no_dot = extension.lstrip(".")
                writer.add(lambda c, relative_path=relative_path, name=name,
                           extension_no_dot=extension_no_dot, size=size: _insert_file(
                    c, relative_path, name, extension_no_dot, size, "", None, None,
                    "skipped", REASON_UNREADABLE,
                ))
                known_paths[relative_path] = {
                    "relative_path": relative_path, "size": size, "sha256": "", "mtime": None,
                    "status": "skipped", "error": REASON_UNREADABLE,
                }
            continue
        consecutive_timeouts = 0
        bytes_done += size

        if unchanged:
            result.skipped += 1
            writer.flush_if_due()
            continue

        if reason is not None and _is_indexed_row(existing_row) and name_decision(
            name, config.extensions
        ) is not None:
            # Já indexado por uma versão anterior e agora recusado só pelo
            # nome: virar `skipped` aqui deixaria páginas e itens órfãos. Quem
            # tira o arquivo do índice é o plano de atualização, que pede
            # confirmação e invalida; a varredura o deixa como está.
            result.skipped += 1
            continue

        if reason is not None:
            _record_ignored_file(
                writer, relative_path, name, extension, size, mtime, reason,
                existing_row, known_paths, result, config.output_folder,
            )
            continue

        _record_scanned_file(
            writer, config, source_dir, relative_path, name, extension, size, mtime, file_hash,
            existing_row, known_hashes, known_paths, result, language,
        )

    if on_progress is not None:
        on_progress(result.total_found, bytes_done)


def _is_indexed_row(row) -> bool:
    """The stored row is a document in the index (not ignored, not a copy).
    Rows the scan itself added to `known_paths` carry no status: they are
    ignored files or fresh inserts of this run."""
    try:
        return row is not None and row["status"] not in ("skipped", "duplicate")
    except (KeyError, IndexError):
        return False


def _is_waiting_component(row) -> bool:
    """The stored row waits for a component (`file_types.is_waiting_component`).
    Rows the scan itself added to `known_paths` may carry no status."""
    try:
        return row is not None and is_waiting_component(row["status"], row["error"])
    except (KeyError, IndexError):
        return False


def _is_unreadable_placeholder(row) -> bool:
    """A linha de um arquivo novo que a varredura não conseguiu ler
    (`REASON_UNREADABLE`): para tudo o mais, ele ainda é novo."""
    try:
        return row is not None and is_unreadable_placeholder(row["status"], row["error"])
    except (KeyError, IndexError):
        return False


def _holds_old_data(conn: sqlite3.Connection, relative_path: str) -> bool:
    """O índice ainda guarda o que o arquivo era: ele não foi devolvido à
    fila (`discovered`) pela atualização, ou foi mas ficou com páginas (o
    estado que a 1.10.2 deixava, `update_plan.stale_page_paths`). Lido do
    banco agora, não da linha do começo: um descarte anterior nesta mesma
    varredura pode já ter mexido nele. Um documento que falhou (sem páginas)
    também conta: quando a leitura der certo, as páginas dele deslocam as
    janelas que vêm depois."""
    row = conn.execute(
        "SELECT status, EXISTS (SELECT 1 FROM page WHERE page.file_id = file.id) AS has_pages"
        " FROM file WHERE relative_path = ?",
        (relative_path,),
    ).fetchone()
    if row is None or row["status"] in ("skipped", "duplicate"):
        return False
    return row["status"] != "discovered" or bool(row["has_pages"])


def _drop_derived_data(conn: sqlite3.Connection, relative_path: str, output_folder: str | None) -> None:
    """Pages, full-text rows and converted intermediate of one file."""
    # Local imports: both modules import this one.
    from .conversion import converted_artifact_path
    from .fulltext import remove_file as remove_from_search

    row = conn.execute(
        "SELECT id, extension, needs_ocr FROM file WHERE relative_path = ?", (relative_path,)
    ).fetchone()
    if row is None:
        return
    remove_from_search(conn, row["id"])
    conn.execute("DELETE FROM page WHERE file_id = ?", (row["id"],))
    if output_folder:
        artifact = converted_artifact_path(output_folder, relative_path, row["extension"], bool(row["needs_ocr"]))
        if artifact is not None:
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass


def _ignore_reason(path: Path, name: str, config: ProjectConfig) -> str | None:
    """Why the file must not enter the index, or `None`. By name first (no
    read at all); only a text-like candidate has its first bytes read, to
    look for a private key or for binary content in an unknown extension."""
    reason = name_decision(name, config.extensions)
    if reason is not None:
        return reason
    extension = path.suffix.lower()
    if not is_extension_allowed(extension, config.extensions):
        return REASON_NOT_SELECTED
    if not needs_head(name, config.extensions):
        return None
    try:
        head = call_with_deadline(read_head, path, deadline=STAT_DEADLINE_SECONDS)
    except OSError:
        return None  # o hash, logo depois, relata o erro de leitura como sempre
    return index_decision(name, head, config.extensions)


def _record_ignored_file(
    writer: BatchWriter, relative_path: str, name: str, extension: str, size: int, mtime: float,
    reason: str, existing_row, known_paths, result: ScanResult, output_folder: str | None = None,
) -> None:
    """The file stays in the inventory as `skipped`, the reason in
    `file.error`, with an empty hash: it was never read, so it has no
    content identity (and cannot be "a copy" of anything)."""
    extension_no_dot = extension.lstrip(".")
    if existing_row is None:
        writer.add(lambda c: _insert_file(
            c, relative_path, name, extension_no_dot, size, "", mtime, None, "skipped", reason,
        ))
    else:
        def op(c) -> None:
            # A row that held a document (its content changed into a key, or
            # into binary) must not leave the old text behind: pages and
            # full-text rows go with the flip, and so does the intermediate
            # on disk. In the normal flow the update plan already did this
            # before the scan; this is the net under a direct scan.
            if _is_indexed_row(existing_row):
                _drop_derived_data(c, relative_path, output_folder)
            _update_file(
                c, relative_path, name, extension_no_dot, size, "", mtime, None, "skipped", reason,
            )

        writer.add(op)
    result.ignored += 1
    result.ignored_by_reason[reason] = result.ignored_by_reason.get(reason, 0) + 1
    known_paths[relative_path] = {
        "relative_path": relative_path, "size": size, "sha256": "", "mtime": mtime,
    }


def _record_scanned_file(
    writer: BatchWriter, config: ProjectConfig, source_dir: Path, relative_path: str, name: str,
    extension: str, size: int, mtime: float, file_hash: str, existing_row, known_hashes, known_paths,
    result: ScanResult, language,
) -> None:
    """Records one hashed file. (Same size and time under the same path
    never gets here: unchanged without reading the bytes — the rule
    `update_plan.detect_changes` already follows. Hashing every file on
    every scan made a second scan of a large Google Drive folder
    reopen each file one by one, for hours, only to learn nothing had
    changed.)

    Every write is a `writer.add` op; `known_hashes`/`known_paths` are
    updated here, in memory, once, so a replayed batch cannot double them."""
    if existing_row is not None and existing_row["sha256"] == file_hash:
        result.skipped += 1
        # The one write on the unchanged path, and it is not about
        # correctness: `file.mtime` is what lets `update_plan` decide
        # a file is unchanged without reading its bytes. Only the
        # insert and update branches below ever wrote it, so a
        # project created by 1.0.1 kept `mtime` NULL forever — the
        # scan skips unchanged files and the plan is read-only —
        # and every open of the Execution screen re-hashed the whole
        # collection, pulling a Drive-synced acervo down byte by
        # byte. The same applies to any single file whose mtime Drive
        # rewrote without changing the content: the mismatch would be
        # permanent. §8.1 promises "da segunda em diante a detecção é
        # rápida"; this is what delivers it.
        # `size` too: Google Drive can answer `st_size = 16384` right
        # after a file is written. A wrong size stored once would send
        # the file down this hashing path on every scan.
        if existing_row["mtime"] != mtime or existing_row["size"] != size:
            writer.add(lambda c: c.execute(
                "UPDATE file SET mtime = ?, size = ? WHERE relative_path = ?",
                (mtime, size, relative_path),
            ))
        return

    placeholder = _is_unreadable_placeholder(existing_row)
    if (existing_row is None or placeholder) and file_hash in known_hashes:
        # Same content already indexed under another path (copy/duplicate).
        # It enters the table with status = 'duplicate' instead of vanishing:
        # without this row, the progress bar's numerator (COUNT(*) FROM
        # file) never reached the denominator (count of files in the
        # folder), and the bar stalled below 100%. `conversion.py` only
        # selects 'discovered' and `extraction.py` only selects
        # 'converted'/'extracted' — neither picks up 'duplicate', which
        # stays out of processing as before, only visible in the
        # inventory.
        extension_no_dot = extension.lstrip(".")
        if placeholder:
            writer.add(lambda c: _update_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, None, "duplicate"
            ))
        else:
            writer.add(lambda c: _insert_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, None, "duplicate"
            ))
        result.skipped += 1
        known_hashes.add(file_hash)
        known_paths[relative_path] = {
            "relative_path": relative_path, "size": size, "sha256": file_hash, "mtime": mtime,
        }
        return

    if _is_waiting_component(existing_row):
        # Editado enquanto esperava o componente: só os bytes mudam aqui; o
        # arquivo continua em espera (`status`, `error`, `ocr_failed`). Se
        # virasse `discovered`, a conversão que obtém o componente na mesma
        # execução poria as páginas dele no grupo sem que as janelas já
        # feitas fossem descartadas — o que acontece quando a atualização
        # automática antes da varredura não rodou (pasta inalcançável num
        # instante, Parar). Quem o devolve à fila é a conversão, se o grupo
        # não tem janelas (`requeue_ocr_failures`), ou o plano de
        # atualização, com o componente presente, junto com as janelas.
        def waiting_op(c) -> None:
            c.execute(
                "UPDATE file SET size = ?, sha256 = ?, mtime = ? WHERE relative_path = ?",
                (size, file_hash, mtime, relative_path),
            )
            record_event(
                c, "scan", "warning", "log.scan.content_changed", {"name": name},
                language=language, commit=False,
            )

        writer.add(waiting_op)
        result.waiting_updated += 1
        known_hashes.add(file_hash)
        known_paths[relative_path] = {
            "relative_path": relative_path, "size": size, "sha256": file_hash, "mtime": mtime,
            "status": existing_row["status"], "error": existing_row["error"],
        }
        return

    status = "discovered"
    group_key = derive_group_key(relative_path, source_dir, config)
    extension_no_dot = extension.lstrip(".")

    if existing_row is None:
        def op(c) -> None:
            _insert_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, group_key, status
            )

        result.discovered += 1
    else:
        # Pré-filtro barato pela linha do começo da varredura: só um
        # documento do índice (não ignorado, não cópia) pode ter dados antigos.
        if _is_indexed_row(existing_row):
            # A rede da atualização: o documento mudou e o índice ainda tem o
            # que ele era (páginas, busca, janelas do grupo). Normalmente a
            # atualização automática antes da varredura já descartou isso;
            # quando ela não rodou ou não conseguiu ler o arquivo, a varredura
            # descarta aqui, pela mesma rotina, antes de devolvê-lo à fila.
            # Sem isso a extração parava em UNIQUE(page.file_id, page.number),
            # ou as páginas novas caíam por baixo de janelas já classificadas.
            # A consulta enxerga as escritas ainda não confirmadas desta
            # conexão; o commit só é pago quando há o que descartar (`_apply`
            # abre a própria transação). No fluxo normal o documento chega
            # aqui já `discovered` e sem páginas, e nada é confirmado antes.
            if _holds_old_data(writer.conn, relative_path):
                from .invalidation import discard_changed_file  # importa este módulo

                writer.flush()
                discard_changed_file(writer.conn, config, relative_path, name, size, language)

        def op(c) -> None:
            _update_file(
                c, relative_path, name, extension_no_dot, size, file_hash,
                mtime, group_key, status
            )
            record_event(
                c, "scan", "warning", "log.scan.content_changed", {"name": name},
                language=language, commit=False,
            )

        result.updated += 1

    # Committed within a second (`BatchWriter`), not only at the end:
    # the Execution screen's progress bar reads from a separate
    # connection and must see the new rows while the scan runs.
    writer.add(op)

    known_hashes.add(file_hash)
    known_paths[relative_path] = {
        "relative_path": relative_path, "size": size, "sha256": file_hash, "mtime": mtime,
    }

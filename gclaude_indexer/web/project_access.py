# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Opening a project for a request: the catalog entry or 404, the sync and
lock checks of the first visit (section 11), an interrupted folder move
settled first, and the read-only connection of the screens that only read."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException

from ..catalog import CatalogEntry, find_project
from ..config import ConfigError, ProjectConfig
from ..db import READER_TIMEOUT_SECONDS, WRITER_TIMEOUT_SECONDS
from .. import relocation
from ..project import load_project
from ..sync import check_sync, mark_synced
from ..lock import check_lock
from . import step_state
from .readers import reader_pool
from .i18n import DEFAULT_LANGUAGE, translate
from .caches import _idle_fragments, _idle_fragments_lock, _quality_cache, _quality_cache_lock
from .rendering import _side_bar_cache
from .state import _release_project, lock_manager


def _project_or_404(project_id: int) -> CatalogEntry:
    """The catalog entry (`find_project`, resolved for this machine), or
    the 404 every project route answers when it is not there."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    return entry


class _ProjectCheckError(Exception):
    # Carries the translation key and its parameters, not rendered text: the
    # check runs before the request's language is known, and the screen is
    # what renders it (user requirement 3).
    def __init__(self, entry: CatalogEntry, message_key: str, message_params: dict[str, object]):
        self.entry = entry
        self.message_key = message_key
        self.message_params = message_params


class LockBlockedError(_ProjectCheckError):
    """Another machine holds the project's lock and refreshed it recently
    (`lock_blocked.html`, 423)."""


class LockAbandonedError(_ProjectCheckError):
    """Another machine's lock, not refreshed for
    `lock.MINUTES_UNTIL_ABANDONED` minutes (`lock_abandoned.html`, 409)."""


class IncompleteSyncError(_ProjectCheckError):
    """`project.db` looks older than this machine last saw it: the sync
    has not finished downloading it (`incomplete_sync.html`, 409)."""


class RelocationNeededError(Exception):
    """2.0.0: a saída deste projeto está dentro da origem e o usuário ainda
    não escolheu entre mover e adiar (nesta máquina)."""

    def __init__(self, entry: CatalogEntry, source_folder: str):
        self.entry = entry
        self.source_folder = source_folder


class RelocationBusyError(Exception):
    """A pasta deste projeto está mudando de lugar agora."""


@contextmanager
def _open_project(project_id: int, timeout: float = WRITER_TIMEOUT_SECONDS):
    """Opens the project for use in this request. The first time, in this
    server session, that this project is touched: checks the incomplete
    sync signal (section 11.4) and the other machine's lock (section 11.3)
    before releasing it — later visits no longer repeat the check, because
    the lock is already ours.

    `timeout`: the Execution screen's polls pass `READER_TIMEOUT_SECONDS`, so
    a busy database costs them a few seconds, not thirty."""
    entry = _project_or_404(project_id)
    # Antes de abrir o banco: depois de uma queda no meio da mudança de
    # pasta, o `project.db` pode estar do outro lado, e abrir o caminho do
    # catálogo criaria um banco vazio no lugar.
    entry = _settle_relocation(project_id, entry)
    try:
        config, conn = load_project(entry.output_folder, timeout=timeout)
    except ConfigError as exc:
        # No request-scoped language available in this context manager (see
        # `config.py`'s docstring) — `DEFAULT_LANGUAGE`, same as every other
        # caller with no language of its own. This 500 is an internal-error
        # fallback (a project's saved config failed re-validation), not part
        # of the normal form-submission flow that Task 18 fixed.
        details = "; ".join(translate(DEFAULT_LANGUAGE, e.key, **e.params) for e in exc.errors)
        raise HTTPException(status_code=500, detail=f"Configuração do projeto inválida: {details}")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível abrir o projeto: {exc}")

    if not lock_manager.is_open(entry.output_folder):
        sync_result = check_sync(entry.output_folder)
        if not sync_result.ok:
            conn.close()
            raise IncompleteSyncError(entry, sync_result.message_key, sync_result.message_params)

        lock_result = check_lock(entry.output_folder)
        if lock_result.status == "blocked":
            conn.close()
            raise LockBlockedError(entry, lock_result.message_key, lock_result.message_params)
        if lock_result.status == "abandoned":
            conn.close()
            raise LockAbandonedError(entry, lock_result.message_key, lock_result.message_params)

        if _relocation_due(config) and not relocation.is_postponed(entry.output_folder):
            conn.close()
            raise RelocationNeededError(entry, config.source_folder)

        lock_manager.open(entry.output_folder)
        mark_synced(entry.output_folder)

    lock_manager.begin_use(entry.output_folder)
    try:
        yield entry, config, conn
    finally:
        lock_manager.end_use(entry.output_folder)
        conn.close()


@contextmanager
def _read_project(project_id: int, timeout: float = READER_TIMEOUT_SECONDS):
    """`_open_project` for the screens that only read: the same
    `(entry, config, conn)`, with `conn` the project's read-only connection
    that stays open between requests (see `readers.py`). The first visit of
    the session still goes through `_open_project`, which runs the sync and
    lock checks; anything that cannot use the reader falls back to it."""
    entry = _project_or_404(project_id)
    reader = reader_pool.acquire(entry.output_folder) if lock_manager.is_open(entry.output_folder) else None
    if reader is None:
        with _open_project(project_id, timeout=timeout) as opened:
            yield opened
        return
    lock_manager.begin_use(entry.output_folder)
    try:
        yield entry, reader.config, reader.conn
    finally:
        lock_manager.end_use(entry.output_folder)
        reader_pool.release(reader)


# --- 2.0.0: mudança da pasta de saída que está dentro da origem ----------------


def _relocation_due(config: ProjectConfig) -> bool:
    """A saída está dentro da origem (ou é ela). A suíte desliga isto por
    padrão (`conftest.py`): muitos testes antigos criam a saída dentro da
    pasta temporária que serve de origem."""
    return relocation.output_inside_source(config.source_folder, config.output_folder)


def _after_relocation(old: str, new: str) -> None:
    """O que a interface guarda pela pasta antiga e precisa esquecer."""
    _release_project(old, keep_lock_file=True)
    _side_bar_cache.clear()
    with step_state._status_cache_lock:
        step_state._status_cache.clear()
    with _idle_fragments_lock:
        _idle_fragments.clear()
    with _quality_cache_lock:
        _quality_cache.clear()


def _settle_relocation(project_id: int, entry: CatalogEntry) -> CatalogEntry:
    """Conclui ou desfaz uma mudança de pasta interrompida (o diário fica na
    pasta local da máquina) antes de qualquer acesso ao projeto."""
    if relocation.in_flight(entry.output_folder):
        raise RelocationBusyError()
    if relocation.pending_for(entry.output_folder) is None:
        return entry
    if not relocation.recover(entry.output_folder, on_finalize=_after_relocation):
        if relocation.in_flight(entry.output_folder):
            raise RelocationBusyError()
        raise HTTPException(
            status_code=503,
            detail=(
                "A mudança de pasta deste projeto foi interrompida e não pôde ser concluída nem "
                "desfeita agora (uma das pastas está inacessível). Conecte a unidade e abra de novo."
            ),
        )
    return _project_or_404(project_id)

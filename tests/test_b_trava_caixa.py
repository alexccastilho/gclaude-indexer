# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: a trava guardava a pasta pela grafia que o disco devolve, e no
Google Drive a caixa digitada fica (`H:` e `h:`, `Saida` e `saida`). A mesma
pasta escrita de dois jeitos virava duas travas, e `is_open`/`close`/o
keep-alive não achavam a aberta. A comparação passa a ser por
`paths.folder_key`; a chave gravada continua a mesma."""

from __future__ import annotations

from gclaude_indexer import lock as lock_mod
from gclaude_indexer.lock import LockManager, read_lock


def _como_no_drive(monkeypatch):
    # No Drive, `Path.resolve()` devolve a caixa digitada; no NTFS da suíte
    # ela é corrigida pelo disco, e o defeito não apareceria.
    monkeypatch.setattr(lock_mod, "resolved_folder", lambda folder: str(folder))


def test_mesma_pasta_com_outra_caixa_e_a_mesma_trava(tmp_path, monkeypatch):
    _como_no_drive(monkeypatch)
    pasta = tmp_path / "Saida"
    pasta.mkdir()
    maiuscula, minuscula = str(pasta), str(pasta).lower()
    gerente = LockManager(heartbeat_interval_s=3600)
    try:
        gerente.open(maiuscula)
        assert gerente.is_open(minuscula)
        gerente.open(minuscula)
        assert len(gerente._locks) == 1, "uma pasta, uma trava"
        # A chave gravada é a da primeira abertura.
        assert list(gerente._locks) == [maiuscula]
        gerente.close(minuscula)
        assert not gerente.is_open(maiuscula)
        assert read_lock(pasta) is None
    finally:
        gerente.close_all()


def test_uso_em_curso_vale_para_a_outra_grafia(tmp_path, monkeypatch):
    _como_no_drive(monkeypatch)
    pasta = tmp_path / "Saida"
    pasta.mkdir()
    gerente = LockManager(heartbeat_interval_s=3600, idle_release_s=0)
    try:
        gerente.open(str(pasta))
        gerente.begin_use(str(pasta).lower())
        gerente.heartbeat()
        assert gerente.is_open(str(pasta)), "o pedido em curso segura a trava"
        gerente.end_use(str(pasta).upper())
        gerente.heartbeat()
        assert not gerente.is_open(str(pasta))
    finally:
        gerente.close_all()


def test_keep_alive_compara_sem_caixa(tmp_path, monkeypatch):
    from gclaude_indexer.catalog import CatalogEntry
    from gclaude_indexer.web import state

    _como_no_drive(monkeypatch)
    pasta = tmp_path / "Saida"
    pasta.mkdir()
    entrada = CatalogEntry(id=77, name="x", output_folder=str(pasta), created_at="2026-01-01T00:00:00")
    monkeypatch.setattr(state, "list_projects", lambda: [entrada])
    monkeypatch.setattr(state, "catalog_folder", lambda: None)
    monkeypatch.setattr(state, "_step_in_progress", lambda project_id: project_id == 77)
    assert state._project_busy(str(pasta).lower())

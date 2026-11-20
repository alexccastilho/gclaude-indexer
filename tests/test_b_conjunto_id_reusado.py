# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: um Conjunto guarda o id do projeto no catálogo, e o id não é
identidade: o catálogo dá ao projeto novo o id do que foi excluído
(`max + 1`) e renumera ids que colidem. Excluir o projeto de maior id e
criar outro fazia o Conjunto passar a apontar para o projeto novo. O membro
passa a guardar também o carimbo de criação da entrada do catálogo, que a
mudança de pasta e a renumeração não tocam."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from gclaude_indexer import catalog as catalog_mod
from gclaude_indexer.catalog import list_projects, register_project, remove_project
from gclaude_indexer.combined_package import load_members
from gclaude_indexer.output_names import INDEX_FILENAME
from gclaude_indexer.sets import find_set


class _Relogio:
    """Um segundo a mais a cada entrada: criar e recriar no mesmo segundo
    daria carimbos iguais."""

    atual = datetime(2026, 1, 1, 10, 0, 0)

    @classmethod
    def now(cls):
        cls.atual += timedelta(seconds=1)
        return cls.atual


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "datetime", _Relogio)
    from gclaude_indexer.web.app import app
    from gclaude_indexer.web.state import lock_manager

    lock_manager.close_all()
    return TestClient(app)


def _projeto(tmp_path, nome):
    saida = tmp_path / nome
    saida.mkdir()
    (saida / INDEX_FILENAME).write_text("# índice\n", encoding="utf-8")
    return register_project(nome, str(saida))


def test_conjunto_nao_passa_a_apontar_para_o_projeto_que_herdou_o_id(cliente, tmp_path):
    b = _projeto(tmp_path, "Oficios")
    a = _projeto(tmp_path, "Atas")
    assert a.id > b.id
    resposta = cliente.post("/sets/new", data={
        "name": "Conselho", "personal_instructions": "",
        f"project_{a.id}": "1", f"alias_{a.id}": "atas",
        f"project_{b.id}": "1", f"alias_{b.id}": "oficios",
    }, follow_redirects=False)
    assert resposta.status_code == 303
    set_id = int(resposta.headers["location"].rsplit("/", 1)[1])

    remove_project(a.id)
    c = _projeto(tmp_path, "Contratos")
    assert c.id == a.id, "o cenário: o catálogo reaproveita o id"

    membros = {m.alias: m for m in load_members(find_set(set_id))}
    assert membros["atas"].catalog is None, "o membro excluído não pode virar o projeto novo"
    assert not membros["atas"].available
    assert membros["oficios"].catalog is not None and membros["oficios"].catalog.name == "Oficios"

    lista = cliente.get("/sets").text
    assert "atas (Contratos)" not in lista and f"atas (#{a.id})" in lista
    tela = cliente.get(f"/sets/{set_id}").text
    assert f'name="project_{c.id}" value="1" checked' not in tela


def test_conjunto_acompanha_o_id_renumerado(cliente, tmp_path):
    a = _projeto(tmp_path, "Atas")
    b = _projeto(tmp_path, "Oficios")
    resposta = cliente.post("/sets/new", data={
        "name": "Conselho", "personal_instructions": "",
        f"project_{a.id}": "1", f"alias_{a.id}": "atas",
        f"project_{b.id}": "1", f"alias_{b.id}": "oficios",
    }, follow_redirects=False)
    set_id = int(resposta.headers["location"].rsplit("/", 1)[1])

    # Outra máquina registrou um projeto offline com o mesmo id de "Atas" e
    # ele ficou antes no arquivo: na leitura, "Atas" é que é renumerado.
    entradas = list_projects()
    intruso = catalog_mod.CatalogEntry(
        id=a.id, name="Intruso", output_folder=str(tmp_path / "intruso"), created_at="2025-12-31T00:00:00",
    )
    catalog_mod._write([intruso] + entradas)
    renumerado = [e for e in list_projects() if e.name == "Atas"][0]
    assert renumerado.id != a.id

    membros = {m.alias: m for m in load_members(find_set(set_id))}
    assert membros["atas"].catalog is not None and membros["atas"].catalog.name == "Atas"

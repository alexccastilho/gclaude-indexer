# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: `/activity`, o que o painel de espera de toda tela lê, só via
as operações de `_start_operation`. Limpar intermediários, indexar a busca,
remover repetições das instruções e excluir o projeto tomam a vaga por
`_generation_slot` e ficavam invisíveis."""

from __future__ import annotations

from gclaude_indexer.i18n import translate
from gclaude_indexer.web import state
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def test_activity_mostra_a_operacao_que_segura_a_vaga(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path)
    with state._generation_slot(pid, "result.cleanup_button") as tomada:
        assert tomada
        operacoes = cliente.get("/activity", cookies={"language": "pt"}).json()["operations"]
        minhas = [op for op in operacoes if op["project_id"] == pid]
        assert len(minhas) == 1
        (op,) = minhas
        assert op["status"] == "running"
        assert op["operation"] == translate("pt", "result.cleanup_button")
        assert op["operation_key"] == "result.cleanup_button"
        assert op["project_name"] == "Projeto de teste"
        # Não há como parar esta operação: o painel não oferece o botão.
        assert op["stoppable"] is False
        assert isinstance(op["id"], int) and op["id"] != 0
    depois = cliente.get("/activity").json()["operations"]
    assert not [op for op in depois if op["project_id"] == pid]

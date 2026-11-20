# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: "Executar próxima etapa", "Executar tudo" e "Continuar" não
olhavam a vaga de operação: com uma importação, uma limpeza ou uma exclusão
em curso, começavam uma etapa no mesmo projeto. Agora fazem a mesma
checagem das outras rotas e respondem "ocupado"."""

from __future__ import annotations

import pytest

from gclaude_indexer.web import state
from gclaude_indexer.web.background_runs import task_manager
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


@pytest.mark.parametrize("rota", ["run-next", "run-all", "resume"])
def test_rota_de_execucao_responde_ocupado_com_operacao_em_curso(cliente, tmp_path, rota):
    pid = _criar_projeto(cliente, tmp_path)
    task_manager._tasks.clear()
    with state._generation_slot(pid, "result.cleanup_button") as tomada:
        assert tomada
        resposta = cliente.post(f"/projects/{pid}/{rota}", headers={"HX-Request": "true"}, follow_redirects=False)
        assert resposta.status_code == 409
        assert task_manager.latest_for_project(pid) is None, "nenhuma etapa pode começar"


@pytest.mark.parametrize("rota", ["run-next", "resume"])
def test_proxima_e_continuar_comecam_pela_etapa_pendente(cliente, tmp_path, rota):
    pid = _criar_projeto(cliente, tmp_path)
    task_manager._tasks.clear()
    resposta = cliente.post(f"/projects/{pid}/{rota}", headers={"HX-Request": "true"})
    assert resposta.status_code == 200
    tarefa = task_manager.latest_for_project(pid)
    assert tarefa is not None and tarefa.step == "scan"
    task_manager.pause(pid)

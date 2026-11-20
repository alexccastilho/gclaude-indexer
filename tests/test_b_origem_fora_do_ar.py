# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: com a origem fora do ar, só as etapas que leem os originais
(varredura, conversão, extração) ficam bloqueadas. Janelas e classificação
leem o banco, e "Importar e gerar relatórios" lê o banco e a saída: ficam
liberadas."""

from __future__ import annotations

import shutil
import time

import pytest

from gclaude_indexer.web.background_runs import task_manager
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def _rodar(projeto_id, saida, etapa):
    task_manager._tasks.clear()
    task_manager.start_step(projeto_id, str(saida), etapa, language="pt")
    limite = time.monotonic() + 30
    while task_manager.get(projeto_id, etapa).running and time.monotonic() < limite:
        time.sleep(0.05)
    return task_manager.get(projeto_id, etapa)


def _projeto_sem_origem(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    shutil.rmtree(tmp_path / "origem")
    return projeto_id, tmp_path / "Projeto_de_teste_indexado"


@pytest.mark.parametrize("etapa", ["windows", "classification"])
def test_etapa_que_nao_le_a_origem_roda_com_ela_fora_do_ar(cliente, tmp_path, etapa):
    projeto_id, saida = _projeto_sem_origem(cliente, tmp_path)
    tarefa = _rodar(projeto_id, saida, etapa)
    assert tarefa.error is None, tarefa.error
    assert tarefa.finished_ok


@pytest.mark.parametrize("etapa", ["scan", "conversion", "extraction"])
def test_etapa_que_le_a_origem_continua_bloqueada(cliente, tmp_path, etapa):
    projeto_id, saida = _projeto_sem_origem(cliente, tmp_path)
    tarefa = _rodar(projeto_id, saida, etapa)
    assert not tarefa.finished_ok
    assert str(tmp_path / "origem") in (tarefa.error or "")


def test_importar_e_gerar_com_a_origem_fora_do_ar(cliente, tmp_path):
    projeto_id, saida = _projeto_sem_origem(cliente, tmp_path)
    resposta = cliente.post(
        f"/projects/{projeto_id}/import-and-generate", headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert resposta.status_code < 400, resposta.text[:500]

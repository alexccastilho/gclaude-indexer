# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""2.1.6 — travas e integridade dos dados (auditoria externa, lote 1).

Cada bloco reproduz um defeito confirmado na leitura do código da 2.1.5:
etapas do mesmo projeto rodando ao mesmo tempo, o heartbeat do lock que
morre com um erro do Drive, a geometria do grupo quando um arquivo muda de
situação, a leitura de mensagens que derruba a etapa inteira e a pausa que
aparecia como "Concluído 100%".
"""

from __future__ import annotations

import time

from gclaude_indexer.web import background_runs
from gclaude_indexer.web.background_runs import TaskManager


# --- Item 5: pausar não é concluir ---------------------------------------------------
#
# As etapas leem `should_stop()` e retornam normalmente; `finished_ok` era
# gravado sempre que `call_step` voltava sem exceção, e o quadro mostrava
# "Concluído" com 100% depois de um Pausar.


class _ConexaoFalsa:
    def close(self):
        pass


def _gerente_com_etapa_falsa(monkeypatch, corpo):
    registro: dict = {}
    monkeypatch.setattr(TaskManager, "_measure", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(background_runs, "load_project", lambda _pasta: (None, _ConexaoFalsa()))
    monkeypatch.setattr(background_runs, "begin_step", lambda *a, **k: object())
    monkeypatch.setattr(background_runs, "call_step", corpo)
    monkeypatch.setattr(
        background_runs, "finish_step", lambda _conn, _run, *, ok: registro.setdefault("ok", ok)
    )
    return TaskManager(), registro


def _esperar(tarefa, limite=5.0):
    fim = time.monotonic() + limite
    while tarefa.running and time.monotonic() < fim:
        time.sleep(0.01)
    assert not tarefa.running


def test_etapa_pausada_nao_aparece_como_concluida(monkeypatch):
    tarefa_ref: list = []

    def etapa_que_para(_conn, _config, _run, *, should_stop, **_k):
        # O clique em Pausar chega no meio; a etapa sai do laço e retorna.
        tarefa_ref[0].stop_signal.request_stop()
        assert should_stop()

    gerente, registro = _gerente_com_etapa_falsa(monkeypatch, etapa_que_para)
    # A tarefa só existe depois de `start_step`; a thread fica adiada até a
    # etapa falsa ter a referência dela.
    monkeypatch.setattr(background_runs.threading, "Thread", _ThreadAdiada)
    tarefa = gerente.start_step(1, "pasta", "classification")
    tarefa_ref.append(tarefa)
    _ThreadAdiada.rodar_todas()
    _esperar(tarefa)

    assert tarefa.finished_ok is False, "pausa não é conclusão"
    tarefa.total = 241  # `_measure` foi trocado; o total real viria dele
    progresso = background_runs._progress_dict(tarefa, 10, None)
    assert progresso["status"] == "stopped"
    assert progresso["percentual"] < 100
    # O registro da execução continua dizendo "sem erro": a comparação de
    # motores soma o tempo das execuções interrompidas por pausa.
    assert registro["ok"] is True


def test_etapa_que_termina_continua_concluida(monkeypatch):
    gerente, registro = _gerente_com_etapa_falsa(monkeypatch, lambda *a, **k: None)
    tarefa = gerente.start_step(1, "pasta", "classification")
    _esperar(tarefa)
    assert tarefa.finished_ok is True
    assert background_runs._progress_dict(tarefa, 10, None)["status"] == "done"
    assert registro["ok"] is True


class _ThreadAdiada:
    """Segura o corpo da tarefa até o teste ter a referência dela."""

    pendentes: list = []

    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        _ThreadAdiada.pendentes.append(self._target)

    @classmethod
    def rodar_todas(cls):
        while cls.pendentes:
            cls.pendentes.pop(0)()

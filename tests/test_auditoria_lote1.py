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


# --- Item 2: o heartbeat do lock sobrevive a um erro do Drive -------------------------
#
# `remove_lock` ficava fora de `try`: um `PermissionError` (arquivo preso
# pelo Drive) ao soltar a trava de um projeto ocioso matava a thread, e
# nenhuma trava era renovada dali em diante — outra máquina passava a ver o
# projeto como abandonado.

from gclaude_indexer import lock as lock_mod


def test_erro_ao_remover_trava_ociosa_nao_derruba_o_heartbeat(tmp_path, monkeypatch):
    ocioso, ativo = tmp_path / "ocioso", tmp_path / "ativo"
    ocioso.mkdir()
    ativo.mkdir()
    gerente = lock_mod.LockManager(heartbeat_interval_s=3600, idle_release_s=0)
    gerente.open(ocioso)
    gerente.open(ativo)
    gerente.begin_use(ativo)

    def remocao_presa(pasta):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(lock_mod, "remove_lock", remocao_presa)
    renovadas: list = []
    original = lock_mod.refresh_lock
    monkeypatch.setattr(
        lock_mod, "refresh_lock", lambda pasta, trava: renovadas.append(pasta) or original(pasta, trava)
    )

    gerente.heartbeat()  # não pode levantar
    assert renovadas, "a trava em uso foi renovada mesmo com a outra presa"
    # A trava que não saiu continua sob cuidado: a próxima batida tenta de novo.
    assert gerente.is_open(ocioso)

    monkeypatch.setattr(lock_mod, "remove_lock", lambda pasta: None)
    gerente.heartbeat()
    assert not gerente.is_open(ocioso)


def test_excecao_inesperada_numa_batida_nao_encerra_o_laco(monkeypatch):
    gerente = lock_mod.LockManager(heartbeat_interval_s=0.01)
    batidas: list[int] = []

    def batida():
        batidas.append(1)
        if len(batidas) == 1:
            raise RuntimeError("falha qualquer")
        if len(batidas) >= 3:
            gerente._stop.set()

    monkeypatch.setattr(gerente, "heartbeat", batida)
    gerente._heartbeat_loop()  # volta quando `_stop` é ligado
    assert len(batidas) >= 3


# --- Item 1: uma etapa por projeto de cada vez -----------------------------------------
#
# `next_pending_step` pula a etapa "running" e devolve a seguinte: um 2º
# clique em "Rodar próxima etapa" durante a conversão começava a extração ao
# mesmo tempo; "Rodar tudo" no meio de uma etapa começava outra varredura, e
# "Importar e gerar" rodava durante a classificação. Excluir o projeto e
# limpar os intermediários pediam a parada e apagavam os arquivos sem
# esperar a etapa parar de fato.

import pytest

from gclaude_indexer.i18n import translate
from gclaude_indexer.web.background_runs import StepTask, task_manager
from tests.test_phase31 import _app_com_projeto


def _rodando(**campos) -> StepTask:
    base = dict(step="conversion", total=10, baseline=0)
    base.update(campos)
    return StepTask(**base)


@pytest.fixture
def com_etapa_rodando(tmp_path, monkeypatch):
    cliente, pid, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setitem(task_manager._tasks, (pid, "conversion"), _rodando())
    iniciadas: list = []
    monkeypatch.setattr(task_manager, "start_step", lambda *a, **k: iniciadas.append(("step", a, k)))
    monkeypatch.setattr(task_manager, "start_all", lambda *a, **k: iniciadas.append(("all", a, k)))
    yield cliente, pid, iniciadas
    conn.close()


@pytest.mark.parametrize("rota", ["run-next", "run-all", "resume"])
def test_botoes_de_etapa_nao_comecam_outra_com_uma_rodando(com_etapa_rodando, rota):
    cliente, pid, iniciadas = com_etapa_rodando
    resposta = cliente.post(f"/projects/{pid}/{rota}", cookies={"language": "pt"})
    assert resposta.status_code == 200, "a resposta é a tabela de etapas, como sempre"
    assert iniciadas == [], "nenhuma etapa nova começou"


def test_classificar_pendencias_nao_comeca_cadeia_com_etapa_rodando(com_etapa_rodando):
    cliente, pid, iniciadas = com_etapa_rodando
    resposta = cliente.post(f"/projects/{pid}/process-pending", follow_redirects=False)
    assert resposta.status_code == 303
    assert iniciadas == []


def test_importar_e_gerar_recusa_com_etapa_rodando(com_etapa_rodando, monkeypatch):
    from gclaude_indexer.web import routes_run

    cliente, pid, _iniciadas = com_etapa_rodando
    chamado: list = []
    monkeypatch.setattr(routes_run, "_start_operation", lambda *a, **k: chamado.append(a))
    resposta = cliente.post(f"/projects/{pid}/import-and-generate", cookies={"language": "pt"})
    assert resposta.status_code == 409
    assert chamado == []
    from markupsafe import escape

    assert str(escape(translate("pt", "run.step_busy.message"))) in resposta.text


def test_cadeia_entre_duas_etapas_conta_como_rodando(tmp_path, monkeypatch):
    """No intervalo de 0,3 s entre etapas do "Rodar tudo" nenhuma tarefa
    roda, mas a cadeia está prestes a começar a próxima."""
    cliente, pid, conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    from gclaude_indexer.run_control import StopSignal

    monkeypatch.setitem(task_manager._chains, pid, [StopSignal()])
    iniciadas: list = []
    monkeypatch.setattr(task_manager, "start_step", lambda *a, **k: iniciadas.append(a))
    monkeypatch.setattr(task_manager, "start_all", lambda *a, **k: iniciadas.append(a))
    cliente.post(f"/projects/{pid}/run-next")
    assert iniciadas == []
    conn.close()


def test_pausar_e_esperar_devolve_quando_a_tarefa_para(monkeypatch):
    import threading

    gerente = TaskManager()
    tarefa = _rodando()
    gerente._tasks[(7, "conversion")] = tarefa

    def parar_depois():
        time.sleep(0.2)
        tarefa.running = False

    threading.Thread(target=parar_depois).start()
    assert gerente.pause_and_wait(7, timeout_s=5) is True
    assert tarefa.stop_signal.should_stop()


def test_pausar_e_esperar_desiste_no_prazo():
    gerente = TaskManager()
    gerente._tasks[(7, "conversion")] = _rodando()
    inicio = time.monotonic()
    assert gerente.pause_and_wait(7, timeout_s=0.3) is False
    assert time.monotonic() - inicio < 2


@pytest.mark.parametrize("rota,dados", [("clear-intermediates", None), ("delete", {"delete_files": "keep"})])
def test_excluir_e_limpar_nao_apagam_com_a_etapa_ainda_rodando(com_etapa_rodando, monkeypatch, rota, dados):
    from gclaude_indexer.web import routes_projects, routes_result, state

    cliente, pid, _iniciadas = com_etapa_rodando
    monkeypatch.setattr(state, "RELEASE_WAIT_S", 0.2)
    apagou: list = []
    monkeypatch.setattr(routes_result, "clear_intermediates", lambda pasta: apagou.append(pasta))
    monkeypatch.setattr(routes_projects, "delete_project", lambda *a: apagou.append(a))

    resposta = cliente.post(f"/projects/{pid}/{rota}", data=dados, cookies={"language": "pt"}, follow_redirects=False)

    assert apagou == [], "nada é apagado enquanto a etapa não para"
    assert resposta.status_code == 409
    from markupsafe import escape

    assert str(escape(translate("pt", "run.step_busy.stopping"))) in resposta.text

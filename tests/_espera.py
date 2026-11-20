# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Espera por condição, para os testes que dependem de uma thread: em vez de
um `time.sleep` fixo (lento quando sobra, instável quando falta), pergunta de
novo a cada 50 ms até o prazo, e falha com `AssertionError` se ele estourar."""

from __future__ import annotations

import time

from gclaude_indexer.web.background_runs import task_manager


def esperar(condicao, timeout: float = 30, mensagem: str = "condição não atingida a tempo"):
    """Devolve o primeiro valor verdadeiro de `condicao()`."""
    fim = time.monotonic() + timeout
    while True:
        valor = condicao()
        if valor:
            return valor
        if time.monotonic() >= fim:
            raise AssertionError(mensagem)
        time.sleep(0.05)


def esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    """As rotas de execução só disparam a etapa em segundo plano e voltam na
    hora; o teste espera a tarefa terminar antes de conferir o resultado."""

    def terminada():
        tarefa = task_manager.get(projeto_id, etapa)
        return tarefa if tarefa is not None and not tarefa.running else None

    return esperar(terminada, timeout, f"etapa '{etapa}' do projeto {projeto_id} não terminou em {timeout}s")

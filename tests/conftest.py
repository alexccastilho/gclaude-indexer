# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

import os

import pytest


@pytest.fixture(autouse=True)
def _sem_placa_de_video_por_padrao(monkeypatch):
    """1.5.12: com placa de vídeo a classificação espera o Ollama para
    sempre. Os testes rodam sem Ollama, então partem de "sem placa"; quem
    quer a placa diz isso no próprio teste."""
    from gclaude_indexer import engine_local

    monkeypatch.setattr(engine_local, "_has_dedicated_gpu", lambda: False)


@pytest.fixture(autouse=True)
def _placa_pequena_por_padrao(monkeypatch):
    """1.5.14: o modelo automático depende da VRAM da máquina. Os testes
    partem de "sem placa" (modelo de 4B), seja qual for a máquina."""
    from gclaude_indexer import engine_local

    monkeypatch.setattr(engine_local, "gpu_vram_mb", lambda: 0)


@pytest.fixture(autouse=True)
def _idioma_do_ocr_sem_internet(monkeypatch):
    """1.5.19: o programa baixa o idioma do OCR que faltar. Nos testes,
    nada sai para a internet e `TESSDATA_PREFIX` volta ao que era."""
    from gclaude_indexer import ocr_languages

    monkeypatch.setattr(ocr_languages, "_download", lambda _lang, _target: False)
    atual = os.environ.get("TESSDATA_PREFIX")
    if atual is None:
        # setenv first: it records "absent" so the teardown removes a value
        # `ensure` may set; delenv alone would leave nothing to undo.
        monkeypatch.setenv("TESSDATA_PREFIX", "")
        monkeypatch.delenv("TESSDATA_PREFIX")
    else:
        monkeypatch.setenv("TESSDATA_PREFIX", atual)


@pytest.fixture(autouse=True)
def _ollama_em_porta_fechada(monkeypatch):
    """Fase 37: nenhum teste fala com o Ollama real da máquina. Antes, a
    suíte fazia centenas de pedidos 404 a 127.0.0.1:11434 com modelos
    falsos, e duas quedas do servidor em uso coincidiram com rodadas da
    suíte. A porta 9 (discard) recusa a conexão na hora; quem
    precisa de um servidor falso passa a própria URL."""
    from gclaude_indexer import engine_local

    monkeypatch.setattr(engine_local, "OLLAMA_BASE_URL", "http://127.0.0.1:9")


# Fase 37: the `ollama` CLI itself talks to the server named by OLLAMA_HOST —
# `ollama --version`, run by the About screen's install diagnostics, asks it
# `/api/version`. With the engine's URL already swapped, those were the 6
# lines per test_phase13 run still landing in the real server's log. Set once
# for the whole pytest process, not per test: a subprocess or a thread a test
# leaves running inherits it after the test's fixtures are torn down. The CLI
# prints "Warning: could not connect" and still exits 0, so the diagnostics
# keep reporting the client version.
from gclaude_indexer import engine_local as _engine_local  # noqa: E402

os.environ["OLLAMA_HOST"] = "127.0.0.1:9"
_engine_local.OLLAMA_BASE_URL = "http://127.0.0.1:9"


def _a_suite_nao_sobe_o_ollama(command, env=None, log_path=None):
    """With the port closed, `run_classification` finds Ollama down and
    `_try_restart_ollama` launched a REAL `ollama serve` — which, with the
    suite's OLLAMA_HOST, bound port 9 and served the fake models (an orphan
    process was left behind). It fails like a missing binary:
    `_try_restart_ollama` logs the attempt and returns False."""
    raise OSError("a suíte de testes não sobe o Ollama da máquina")


_engine_local.start_in_background = _a_suite_nao_sobe_o_ollama


@pytest.fixture(autouse=True)
def _operacoes_longas_terminam_dentro_do_pedido(monkeypatch):
    """1.9.0: "Atualizar" e "Importar e gerar relatórios" rodam numa thread,
    e o pedido espera por ela só `OPERATION_INLINE_WAIT_SECONDS`. Nos
    testes a espera é longa, para o POST voltar com o trabalho feito, como
    antes; quem testa o painel de espera e o Parar baixa o valor."""
    from gclaude_indexer.web import app as modulo_app

    monkeypatch.setattr(modulo_app, "OPERATION_INLINE_WAIT_SECONDS", 120.0)
    yield
    with modulo_app._IMPORTS_IN_PROGRESS_LOCK:
        modulo_app._OPERATIONS.clear()


@pytest.fixture(autouse=True)
def _telas_da_execucao_sem_reaproveitar(monkeypatch):
    """1.9.0: parada, a tela de Execução reaproveita a resposta por até 30 s.
    Os testes mudam o banco por fora e esperam ver a mudança na hora; o
    reaproveitamento tem teste próprio, que liga o prazo de novo."""
    from gclaude_indexer.web import app as modulo_app

    monkeypatch.setattr(modulo_app, "IDLE_FRAGMENT_SECONDS", 0.0)
    with modulo_app._idle_fragments_lock:
        modulo_app._idle_fragments.clear()
    with modulo_app._quality_cache_lock:
        modulo_app._quality_cache.clear()
    modulo_app._about_cache.clear()


@pytest.fixture(autouse=True)
def _leitores_fechados_ao_fim_do_teste():
    """1.9.1: as telas que só leem usam uma conexão que fica aberta entre os
    pedidos. Cada teste termina com elas fechadas, para a pasta temporária
    poder ser apagada no Windows e o teste seguinte começar do zero."""
    from gclaude_indexer.web.readers import reader_pool

    from gclaude_indexer.web import step_state

    reader_pool.close_all()
    step_state._status_cache.clear()
    yield
    reader_pool.close_all()

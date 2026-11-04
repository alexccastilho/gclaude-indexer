# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 33 — slot em toda operação longa e minors da revisão da 32.

Com o slot do projeto passando a cobrir cinco operações (importar e gerar,
atualizar, excluir, indexar busca, limpar intermediários), ele não pode
ficar preso: liberado em `finally` em qualquer saída e vazio no arranque
(pedido do usuário). O tempo decorrido vem de `monotonic()`.
"""

from __future__ import annotations

import pytest

from gclaude_indexer.web import app as modulo_app
from tests.test_phase31 import _app_com_projeto
from tests.test_phase32 import _arranque_isolado


# --- Task 1: o slot nunca fica preso ----------------------------------------------


def _slot_livre(pid):
    return pid not in modulo_app._IMPORTS_IN_PROGRESS and pid not in modulo_app._OPERATIONS_IN_PROGRESS


@pytest.mark.parametrize("saida", [RuntimeError("falhou no meio"), GeneratorExit(), KeyboardInterrupt()])
def test_slot_e_liberado_em_qualquer_saida(saida):
    with pytest.raises(type(saida)):
        with modulo_app._generation_slot(9001, "update.confirm") as claimed:
            assert claimed
            raise saida
    assert _slot_livre(9001)


def test_slot_e_liberado_no_retorno_normal():
    with modulo_app._generation_slot(9002, "delete.confirm") as claimed:
        assert claimed and 9002 in modulo_app._OPERATIONS_IN_PROGRESS
    assert _slot_livre(9002)


def test_arranque_descarta_residuo_do_slot(monkeypatch, tmp_path):
    _arranque_isolado(monkeypatch, tmp_path, ja_aberto=False)
    modulo_app._IMPORTS_IN_PROGRESS.add(7)
    modulo_app._OPERATIONS_IN_PROGRESS[7] = ("update.confirm", 0.0)
    try:
        modulo_app.start_server(port=8123)
        assert _slot_livre(7)
    finally:
        modulo_app._IMPORTS_IN_PROGRESS.discard(7)
        modulo_app._OPERATIONS_IN_PROGRESS.pop(7, None)


def test_tempo_decorrido_vem_do_relogio_monotonico(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    relogio = {"agora": 1000.0}
    monkeypatch.setattr(modulo_app.time, "monotonic", lambda: relogio["agora"])
    monkeypatch.setattr(modulo_app.time, "time", lambda: 0.0)  # relógio de parede "voltou": não pode importar
    with modulo_app._generation_slot(pid, "update.confirm"):
        relogio["agora"] = 1042.0
        dados = cliente.get(f"/projects/{pid}/activity", cookies={"language": "pt"}).json()
    assert dados["elapsed_s"] == 42 and dados["operation_key"] == "update.confirm"


# --- Task 2: atualizar, excluir, indexar busca e limpar intermediários ocupam o slot --
#
# Decisão 1 da fase 33: o usuário nunca aciona uma dessas com geração rodando;
# a exclusão mútua é rede de segurança (excluir durante uma geração apagaria
# arquivos sendo escritos). A chave do slot é a chave i18n do botão, que é o
# que a barra mostra no clique e na retomada pós-F5.

from gclaude_indexer.i18n import translate

_ROTAS = [
    ("update", {}, "apply_update_plan", "update.confirm"),
    ("delete", {"delete_files": "keep"}, "delete_project", "delete.confirm"),
    ("search/index", {"q": ""}, "index_fulltext", "search.index_missing"),
    ("clear-intermediates", {}, "clear_intermediates", "result.cleanup_button"),
]


def _ocupado_por_geracao(pid):
    return modulo_app._generation_slot(pid, "run.import_and_generate")


@pytest.mark.parametrize("rota, dados, _interno, _chave", _ROTAS)
def test_operacao_com_slot_ocupado_recebe_409_e_nao_faz_nada(tmp_path, monkeypatch, rota, dados, _interno, _chave):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    efeitos: list[str] = []
    for nome in ("apply_update_plan", "delete_project", "index_fulltext", "clear_intermediates"):
        monkeypatch.setattr(modulo_app, nome, lambda *a, _n=nome, **k: efeitos.append(_n))
    monkeypatch.setattr(modulo_app.task_manager, "pause", lambda *a, **k: efeitos.append("pause"))
    monkeypatch.setattr(modulo_app.lock_manager, "close", lambda *a, **k: efeitos.append("close"))

    with _ocupado_por_geracao(pid):
        resposta = cliente.post(f"/projects/{pid}/{rota}", data=dados, cookies={"language": "pt"})

    assert resposta.status_code == 409
    assert translate("pt", "run.import_and_generate") in resposta.text, "diz qual operação está rodando"
    assert efeitos == [], "recusada, a rota não pausou, não fechou lock e não tocou o disco"


@pytest.mark.parametrize("rota, dados, interno, chave", _ROTAS)
def test_operacao_ocupa_o_slot_com_a_chave_do_botao(tmp_path, monkeypatch, rota, dados, interno, chave):
    from pathlib import Path

    cliente, pid, _conn, config = _app_com_projeto(tmp_path, monkeypatch)
    # A fixture cria a pasta de origem vazia, e origem vazia com índice
    # cheio é "origem indisponível" para `build_update_plan`
    # (`update_plan.py`, `not paths and known`) — `update` recusaria antes
    # de chegar ao que este teste observa.
    Path(config.source_folder).mkdir(parents=True, exist_ok=True)
    (Path(config.source_folder) / "novo.pdf").write_text("novo", encoding="utf-8")
    vistos: list[str | None] = []

    def observa(*a, **k):
        vistos.append(modulo_app._OPERATIONS_IN_PROGRESS.get(pid, (None,))[0])
        return None

    monkeypatch.setattr(modulo_app, interno, observa)
    monkeypatch.setattr(modulo_app.task_manager, "pause", lambda *a, **k: None)
    monkeypatch.setattr(modulo_app.lock_manager, "close", lambda *a, **k: None)

    cliente.post(f"/projects/{pid}/{rota}", data=dados, follow_redirects=False)

    assert vistos == [chave], "durante a operação, /activity veria o texto do botão que a disparou"
    assert pid not in modulo_app._OPERATIONS_IN_PROGRESS


def test_textos_de_ocupado_nos_tres_idiomas():
    for idioma in ("pt", "en", "es"):
        for chave in ("activity.busy.title", "activity.busy.message"):
            assert translate(idioma, chave) != chave, (idioma, chave)
        assert "{operation}" in translate(idioma, "activity.busy.message")


# --- Task 3: token não-ASCII no botão de sensores é 403, não 500 -----------------


def test_token_nao_ascii_e_recusado_sem_excecao():
    """`hmac.compare_digest` levanta TypeError para str não-ASCII, e o
    Starlette decodifica cabeçalhos em latin-1: um byte ≥ 0x80 por socket
    cru virava traceback no servidor.log. A resposta certa é recusar."""
    from starlette.requests import Request

    escopo = {
        "type": "http", "method": "POST", "path": "/sensors/request-elevation", "query_string": b"",
        "headers": [
            (b"x-gclaude-sensor-token", b"\xe9\xe9"),
            (b"sec-fetch-site", b"same-origin"),
            (b"host", f"127.0.0.1:{modulo_app.SERVER_PORT}".encode()),
        ],
    }
    assert modulo_app._sensor_request_allowed(Request(escopo)) is False


# --- Task 5: só o SuperIO decide a ventoinha da CPU --------------------------------

from gclaude_indexer import sensors
from tests.test_phase32 import _Computer, _Hardware, _Sensor, _como_admin, _nct


def test_sub_hardware_que_nao_e_superio_nao_decide_a_ventoinha(monkeypatch):
    """Um controlador embarcado com header "CPU Optional" em 0, ao lado de um
    SuperIO sem ventoinha nomeada, não pode virar "parada": a regra de header
    fixo é de chips SuperIO (Nuvoton, ITE, Fintek, Winbond)."""
    ec = _Hardware("EmbeddedController", "EC",
                   [_Sensor("Fan", "CPU Optional", 0.0, "/lpc/ec/0/fan/0")], ident="/lpc/ec/0")
    placa = _Hardware("Motherboard", "X", sub=[ec, _nct((1, 0.0))], ident="/motherboard")
    gpu = _Hardware("GpuAmd", "RX", [_Sensor("Temperature", "GPU Core", 50.0, "/gpu-amd/0/temperature/0")],
                    ident="/gpu-amd/0")
    _como_admin(monkeypatch, _Computer(placa, gpu))

    assert sensors._read_library_sensors()["cpu_fan_rpm"] is None


class _SemTipo:
    """Sub-hardware sem `HardwareType` — o que um objeto .NET inesperado pareceria."""

    def __init__(self):
        self.Name, self.Identifier, self.Sensors, self.SubHardware = "estranho", "/lpc/x", [], []

    def Update(self):  # noqa: N802 — nome da API .NET
        pass


def test_sub_hardware_sem_tipo_nao_derruba_a_leitura(monkeypatch):
    placa = _Hardware("Motherboard", "X", sub=[_SemTipo(), _nct((1, 1276.0))], ident="/motherboard")
    gpu = _Hardware("GpuAmd", "RX", [_Sensor("Temperature", "GPU Core", 50.0, "/gpu-amd/0/temperature/0")],
                    ident="/gpu-amd/0")
    _como_admin(monkeypatch, _Computer(placa, gpu))

    leitura = sensors._read_library_sensors()

    assert leitura["gpu_temp_c"] == 50.0 and leitura["cpu_fan_rpm"] == 1276


# --- Revisão final: a única passada de correção -------------------------------------


def test_pagina_de_ocupado_mostra_a_barra_e_volta_ao_projeto(tmp_path, monkeypatch):
    """Important 1 da revisão: a mensagem manda olhar a barra no alto da
    tela, então a página 409 precisa ter a barra (ela só aparece quando a
    base conhece o projeto). E o link de volta diz para onde vai."""
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    with _ocupado_por_geracao(pid):
        resposta = cliente.post(f"/projects/{pid}/delete", data={"delete_files": "keep"}, cookies={"language": "pt"})

    assert resposta.status_code == 409
    assert 'id="wait-overlay"' in resposta.text, "a página que manda olhar o painel precisa ter o painel"
    assert f'/projects/{pid}/operation/stop' in resposta.text, "1.9.0: dá para parar daqui também"
    assert f'href="/projects/{pid}/result"' in resposta.text
    assert translate("pt", "activity.busy.back") in resposta.text


def test_ocupado_sem_dono_vai_para_o_resultado(tmp_path, monkeypatch):
    """Corrida estreita (Minor 4, dobrado): o dono liberou o slot entre a
    recusa e a leitura do nome — em vez de "ocupado com: ." a resposta é o
    redirecionamento normal para o resultado."""
    from starlette.requests import Request

    _cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    escopo = {"type": "http", "method": "POST", "path": f"/projects/{pid}/delete", "headers": [],
              "query_string": b"", "scheme": "http", "server": ("127.0.0.1", 8000), "root_path": ""}

    resposta = modulo_app._operation_busy_response(Request(escopo), pid)

    assert resposta.status_code == 303 and resposta.headers["location"] == f"/projects/{pid}/result"


def test_texto_de_voltar_da_pagina_de_ocupado_nos_tres_idiomas():
    for idioma in ("pt", "en", "es"):
        assert translate(idioma, "activity.busy.back") != "activity.busy.back", idioma

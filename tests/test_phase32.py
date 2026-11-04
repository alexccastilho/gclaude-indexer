# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 32 — ventoinhas em qualquer máquina e indicador de atividade.

Numa placa-mãe com SuperIO Nuvoton NCT6798D, a ventoinha da CPU fica
no SuperIO da placa-mãe, que `sensors.py` nunca abria; o LHM a expõe como `Fan #2`
(`/lpc/nct6798d/0/fan/1`, 1.276 RPM). A da GPU lia 0 RPM com controle 0 %
— parada de verdade, não ausência de leitura.
"""

from __future__ import annotations

from gclaude_indexer import sensors
from gclaude_indexer.sensors import cpu_fan_from_superio


# --- fakes mínimos do objeto .NET do LibreHardwareMonitor ----------------------


class _Sensor:
    def __init__(self, tipo, nome, valor, ident):
        self.SensorType, self.Name, self.Value, self.Identifier = tipo, nome, valor, ident


class _Hardware:
    def __init__(self, tipo, nome, sensores=(), sub=(), ident="/x/0"):
        self.HardwareType, self.Name, self.Identifier = tipo, nome, ident
        self.Sensors, self.SubHardware = list(sensores), list(sub)
        self.updated = 0

    def Update(self):  # noqa: N802 — nome da API .NET
        self.updated += 1


class _Computer:
    def __init__(self, *hardware):
        self.Hardware = list(hardware)


def _nct(*fans):
    """Um NCT6798D como o LHM o mostra: só `Fan #N`, sem dizer o que é o quê.
    `fans` são pares (índice do header, RPM)."""
    return _Hardware(
        "SuperIO", "Nuvoton NCT6798D",
        [_Sensor("Fan", f"Fan #{i + 1}", v, f"/lpc/nct6798d/0/fan/{i}") for i, v in fans],
        ident="/lpc/nct6798d/0",
    )


def _como_admin(monkeypatch, computador):
    monkeypatch.setattr(sensors, "_state", lambda: (computador, None))
    monkeypatch.setattr(sensors, "_is_admin", lambda: True)
    monkeypatch.setattr(sensors, "_with_dell_thermal", lambda leitura: leitura)


# --- Task 1: a ventoinha da CPU no SuperIO -------------------------------------


def test_nuvoton_sem_nome_usa_o_header_cpufan():
    chip = _nct((0, 0.0), (1, 1276.0), (5, 2393.6))
    assert cpu_fan_from_superio(chip.Sensors, chip.Identifier) == 1276


def test_nome_cpu_vence_o_indice():
    sensores = [
        _Sensor("Fan", "CPU Fan", 900.0, "/lpc/it8688e/0/fan/2"),
        _Sensor("Fan", "Fan #1", 1500.0, "/lpc/it8688e/0/fan/0"),
    ]
    assert cpu_fan_from_superio(sensores, "/lpc/it8688e/0") == 900


def test_chip_que_nao_e_nuvoton_usa_o_primeiro_header():
    sensores = [
        _Sensor("Fan", "Fan #1", 1100.0, "/lpc/it8688e/0/fan/0"),
        _Sensor("Fan", "Fan #2", 700.0, "/lpc/it8688e/0/fan/1"),
    ]
    assert cpu_fan_from_superio(sensores, "/lpc/it8688e/0") == 1100


def test_header_adivinhado_em_zero_e_nao_medido():
    chip = _nct((0, 800.0), (1, 0.0))
    assert cpu_fan_from_superio(chip.Sensors, chip.Identifier) is None


def test_nome_cpu_em_zero_e_parada():
    assert cpu_fan_from_superio([_Sensor("Fan", "CPU Fan", 0.0, "/lpc/x/0/fan/0")], "/lpc/x/0") == 0


def test_sem_sensor_de_ventoinha_e_nao_medido():
    so_temperatura = [_Sensor("Temperature", "Temperature #1", 34.0, "/lpc/nct6798d/0/temperature/1")]
    assert cpu_fan_from_superio(so_temperatura, "/lpc/nct6798d/0") is None


def test_leitura_completa_traz_a_ventoinha_da_cpu(monkeypatch):
    chip = _nct((1, 1276.0))
    placa = _Hardware("Motherboard", "Placa-mãe B550", sub=[chip], ident="/motherboard")
    cpu = _Hardware("Cpu", "AMD Ryzen 5 5600",
                    [_Sensor("Temperature", "Core (Tctl/Tdie)", 42.9, "/amdcpu/0/temperature/2")],
                    ident="/amdcpu/0")
    _como_admin(monkeypatch, _Computer(placa, cpu))

    leitura = sensors._read_library_sensors()

    assert leitura["cpu_fan_rpm"] == 1276
    assert leitura["cpu_temp_c"] == 42.9
    assert chip.updated >= 1, "o SubHardware precisa do seu próprio Update(): o da placa não desce"


def test_placa_mae_que_falha_nao_derruba_a_gpu(monkeypatch):
    class _Explode(_Hardware):
        def Update(self):  # noqa: N802
            raise RuntimeError("SuperIO indisponível")

    gpu = _Hardware("GpuAmd", "AMD Radeon RX 6700 XT", [
        _Sensor("Temperature", "GPU Core", 54.0, "/gpu-amd/0/temperature/0"),
        _Sensor("Fan", "GPU Fan", 0.0, "/gpu-amd/0/fan/0"),
    ], ident="/gpu-amd/0")
    _como_admin(monkeypatch, _Computer(_Explode("Motherboard", "X", ident="/motherboard"), gpu))

    leitura = sensors._read_library_sensors()

    assert leitura["gpu_temp_c"] == 54.0
    assert leitura["gpu_fan_rpm"] == 0, "0 RPM com a placa a 54 °C é a ventoinha parada, não falta de leitura"
    assert leitura["cpu_fan_rpm"] is None


def test_gpu_sem_sensor_de_ventoinha_fica_nao_medida(monkeypatch):
    igpu = _Hardware("GpuIntel", "Intel UHD", [
        _Sensor("Temperature", "GPU Core", 40.0, "/gpu-intel/0/temperature/0"),
    ], ident="/gpu-intel/0")
    _como_admin(monkeypatch, _Computer(igpu))

    assert sensors._read_library_sensors()["gpu_fan_rpm"] is None


# --- Task 2: o botão pede o leitor elevado — por uma rota com quatro guardas ---
#
# O servidor escuta em 127.0.0.1 e qualquer site aberto no navegador consegue
# fazer POST para lá. A rota só aceita o pedido com (1) o token desta
# execução do servidor, embutido só na página Executar, (2) `Sec-Fetch-Site:
# same-origin`, (3) o cabeçalho próprio `X-GClaude-Sensor-Token` (força
# preflight CORS em pedido de outra origem) e (4) `Host` igual ao do próprio
# servidor (contra DNS rebinding). Sem qualquer uma, 403 e nenhum UAC.

import json
import os
import time

import pytest

from gclaude_indexer import sensor_service
from gclaude_indexer.web import app as modulo_app
from tests.test_phase31 import _app_com_projeto


def _guardas():
    return {
        "X-GClaude-Sensor-Token": modulo_app.SENSOR_REQUEST_TOKEN,
        "Sec-Fetch-Site": "same-origin",
        "Host": f"127.0.0.1:{modulo_app.SERVER_PORT}",
    }


def _espera(condicao, segundos=3.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.02)
    return condicao()


def _sem_privilegio(monkeypatch, chamadas, resultado="started"):
    monkeypatch.setattr(sensor_service, "request_helper_now", lambda pid: chamadas.append(pid) or resultado)
    monkeypatch.setattr(sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensors, "read_snapshot", lambda: None)


@pytest.mark.parametrize("sem", ["X-GClaude-Sensor-Token", "Sec-Fetch-Site", "Host"])
def test_sem_qualquer_guarda_e_403_e_o_helper_nao_e_chamado(tmp_path, monkeypatch, sem):
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas)
    cabecalhos = {k: v for k, v in _guardas().items() if k != sem}
    if sem == "Host":
        cabecalhos["Host"] = "testserver"  # o que o TestClient manda por padrão

    assert cliente.post("/sensors/request-elevation", headers=cabecalhos).status_code == 403
    assert chamadas == []


@pytest.mark.parametrize("errado, camada", [
    ({"X-GClaude-Sensor-Token": "x"}, "rota"),
    ({"Sec-Fetch-Site": "cross-site"}, "middleware"),
    ({"Sec-Fetch-Site": "same-site"}, "middleware"),
    ({"Host": "atacante.example:8000"}, "middleware"),
    ({"Host": "127.0.0.1:9999"}, "rota"),
    ({"Host": "127.0.0.1.nip.io:8000"}, "middleware"),
])
def test_guarda_errada_e_403(tmp_path, monkeypatch, errado, camada):
    """Fase 33: cada caso diz qual camada barrou. O middleware `_only_own_pages`
    responde em texto; a guarda da rota responde o JSON do HTTPException."""
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas)

    resposta = cliente.post("/sensors/request-elevation", headers={**_guardas(), **errado})

    assert resposta.status_code == 403
    if camada == "rota":
        assert resposta.json() == {"detail": "Forbidden"}, "chegou à rota e foi a guarda dela que barrou"
    else:
        assert resposta.headers["content-type"].startswith("text/plain") and "Pedido recusado" in resposta.text
    assert chamadas == []


@pytest.mark.parametrize("host", ["127.0.0.1:{porta}", "localhost:{porta}"])
def test_so_com_as_quatro_guardas_o_helper_dispara(tmp_path, monkeypatch, host):
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas)

    resposta = cliente.post(
        "/sensors/request-elevation",
        headers={**_guardas(), "Host": host.format(porta=modulo_app.SERVER_PORT)},
    )

    assert resposta.status_code == 202
    assert resposta.json()["outcome"] == "requested"
    assert _espera(lambda: chamadas == [os.getpid()]), "o helper acompanha este servidor, numa thread"


def test_pedido_recusado_libera_novo_pedido(tmp_path, monkeypatch):
    """Review Focus 2: dizer não duas vezes não empilha consent.exe nem trava
    o botão — cada clique é um pedido, cada recusa é uma decisão."""
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas, resultado="refused")

    for vez in (1, 2):
        resposta = cliente.post("/sensors/request-elevation", headers=_guardas())
        assert resposta.status_code == 202 and resposta.json()["outcome"] == "requested"
        assert _espera(lambda: len(chamadas) == vez)
        # O pedido em voo segura a trava até o helper responder; o segundo
        # clique só conta como novo pedido depois disso (revisão final).
        assert _espera(lambda: not modulo_app._SENSOR_REQUEST_IN_FLIGHT.locked())
    assert chamadas == [os.getpid(), os.getpid()]


def test_com_helper_vivo_a_rota_nao_pede_de_novo(tmp_path, monkeypatch):
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas)
    monkeypatch.setattr(sensors, "read_snapshot", lambda: {chave: 1 for chave in sensors.KEYS})

    resposta = cliente.post("/sensors/request-elevation", headers=_guardas())

    assert resposta.status_code == 200 and resposta.json()["outcome"] == "already"
    time.sleep(0.1)
    assert chamadas == []


def test_request_helper_now_ignora_o_sinalizador_do_atalho(monkeypatch, tmp_path):
    monkeypatch.delenv(sensor_service.ELEVATION_REQUEST_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sensor_service.sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensor_service, "_shell_execute_runas", lambda *_a: 42)

    assert sensor_service.request_helper_now(4242) == "started"
    assert sensor_service.start_elevated_helper() == "not_requested", "o arranque continua a obedecer ao atalho"


def test_tela_executar_traz_o_token_e_o_botao(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/run").text
    assert modulo_app.SENSOR_REQUEST_TOKEN in html
    assert 'id="sensor-request"' in html and 'id="sensor-request-button"' in html


def test_resources_devolve_o_status_do_helper(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(modulo_app, "read_launch_status", lambda: "refused")
    assert cliente.get(f"/projects/{pid}/run/resources").json()["helper_status"] == "refused"


# --- Task 3: "parada", "requer administrador" e "não medido" são três coisas --


def test_textos_de_ventoinha_estao_na_tela(tmp_path, monkeypatch):
    from gclaude_indexer.i18n import translate

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/run").text
    # `tojson` escreve o texto como JSON: acentos e travessão saem escapados.
    assert json.dumps(translate("pt", "resources.fan_stopped")) in html
    assert json.dumps(translate("pt", "resources.sensors.needs_admin_short")) in html
    assert "function showFan(" in html


def test_textos_de_ventoinha_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        parada = translate(idioma, "resources.fan_stopped")
        admin = translate(idioma, "resources.sensors.needs_admin_short")
        assert parada not in ("", "resources.fan_stopped"), idioma
        assert admin not in ("", "resources.sensors.needs_admin_short"), idioma
        assert parada != admin, idioma
        assert "0" not in parada, "o rótulo substitui o número, não o repete"


# --- Task 4: o status do helper é desta execução, não da anterior -------------


def _arranque_isolado(monkeypatch, tmp_path, *, ja_aberto: bool):
    import uvicorn

    from gclaude_indexer import paths

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))
    (tmp_path / "local").mkdir()
    status = tmp_path / "local" / sensor_service.LAUNCH_STATUS_FILE_NAME
    status.write_text("started", encoding="utf-8")
    monkeypatch.setattr(sensor_service, "server_listening", lambda *_a: ja_aberto)
    monkeypatch.setattr(sensor_service, "pid_listening_on", lambda *_a: 4242)
    monkeypatch.setattr(sensor_service, "elevation_requested", lambda: False)
    monkeypatch.setattr(modulo_app, "_request_cpu_sensor_helper", lambda: "not_requested")
    monkeypatch.setattr(uvicorn, "run", lambda *_a, **_k: None)
    return status


def test_status_orfao_some_no_arranque(monkeypatch, tmp_path):
    """O arquivo dizia `started` de uma sessão morta, e a tela
    de um servidor que nunca pediu nada dizia "o leitor não respondeu"."""
    status = _arranque_isolado(monkeypatch, tmp_path, ja_aberto=False)
    monkeypatch.setattr(sensors, "read_snapshot", lambda: None)
    monkeypatch.setattr(sensors, "_state", lambda: (object(), "sem_privilegio"))

    modulo_app.start_server()

    assert not status.exists()
    assert sensors.unavailable_reason() == "sem_privilegio"


def test_status_de_outro_servidor_fica(monkeypatch, tmp_path):
    """Com o sistema já aberto noutro processo, o status é dele."""
    status = _arranque_isolado(monkeypatch, tmp_path, ja_aberto=True)

    modulo_app.start_server()

    assert status.read_text(encoding="utf-8") == "started"


def test_clear_launch_status_nunca_levanta(monkeypatch, tmp_path):
    from gclaude_indexer import paths

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "nao-existe"))
    sensor_service.clear_launch_status()  # pasta inexistente: silêncio


# --- Task 5: a barra de atividade diz o que roda e há quanto tempo -------------

from pathlib import Path as _Path

_TEMPLATES = _Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "templates"


def _formulario_marcado(html: str, action: str) -> bool:
    """O `<form>`/`<a>` dessa `action` tem `data-activity` na própria tag."""
    inicio = 0
    achou = False
    while True:
        pos = html.find(action, inicio)
        if pos < 0:
            return achou
        abre = html.rfind("<", 0, pos)
        fecha = html.find(">", pos)
        tag = html[abre:fecha]
        if tag.startswith("<form") or tag.startswith("<a"):
            achou = True
            if "data-activity" not in tag:
                return False
        inicio = fecha


def test_operacoes_longas_estao_marcadas(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    paginas = {
        f"/projects/{pid}/run": [f"/projects/{pid}/import-and-generate"],
        # (o "Gerar relatórios agora" da tela de resultado só aparece com
        # relatórios desatualizados; o arquivo é conferido abaixo)
        f"/projects/{pid}/result": [
            f"/projects/{pid}/result/claude-package", f"/projects/{pid}/clear-intermediates",
        ],
        f"/projects/{pid}/delete": [f"/projects/{pid}/delete"],
    }
    for pagina, acoes in paginas.items():
        html = cliente.get(pagina).text
        for acao in acoes:
            assert _formulario_marcado(html, acao), (pagina, acao)
    # Telas que dependem de estado difícil de montar aqui: o próprio arquivo.
    assert _formulario_marcado((_TEMPLATES / "search.html").read_text(encoding="utf-8"), "/search/index")
    assert _formulario_marcado((_TEMPLATES / "update_project.html").read_text(encoding="utf-8"), "/update\"")
    assert _formulario_marcado((_TEMPLATES / "result.html").read_text(encoding="utf-8"), "/import-and-generate")


def test_formularios_de_preferencia_nao_estao_marcados(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/run").text
    for acao in ("/preferences/language", "/preferences/theme", "/preferences/layout"):
        assert acao in html
        assert not _formulario_marcado(html, acao), acao
    assert not _formulario_marcado(html, f"/projects/{pid}/run-all"), "passo tem progresso próprio"


def test_barra_de_atividade_esta_na_base(tmp_path, monkeypatch):
    from gclaude_indexer.i18n import translate

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/result").text
    # 1.9.0: the bar became the waiting panel, and every screen asks the
    # server-wide `/activity`, not only the screens of a project.
    assert 'id="wait-overlay"' in html and 'id="wait-title"' in html
    assert json.dumps(translate("pt", "activity.running")) in html
    assert 'fetch("/activity"' in html, "ao carregar, a página pergunta ao servidor o que está rodando"


def test_slot_registra_a_operacao_e_limpa_ao_sair():
    pid = 987_001
    with modulo_app._generation_slot(pid, "run.import_and_generate") as claimed:
        assert claimed
        chave, inicio = modulo_app._OPERATIONS_IN_PROGRESS[pid]
        assert chave == "run.import_and_generate" and time.monotonic() - inicio < 5
        with modulo_app._generation_slot(pid, "run.import_and_generate") as segundo:
            assert segundo is False
            assert modulo_app._OPERATIONS_IN_PROGRESS[pid][0] == "run.import_and_generate", "o primeiro continua dono"
    assert pid not in modulo_app._OPERATIONS_IN_PROGRESS


def test_atividade_em_andamento_e_informada_com_o_tempo_real(tmp_path, monkeypatch):
    from gclaude_indexer.i18n import translate

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    assert cliente.get(f"/projects/{pid}/activity").json() == {"operation": None, "operation_key": None, "elapsed_s": 0}

    monkeypatch.setitem(modulo_app._OPERATIONS_IN_PROGRESS, pid, ("run.import_and_generate", time.monotonic() - 42))
    resposta = cliente.get(f"/projects/{pid}/activity", cookies={"language": "en"}).json()
    assert resposta["operation_key"] == "run.import_and_generate"
    assert resposta["operation"] == translate("en", "run.import_and_generate")
    assert 42 <= resposta["elapsed_s"] <= 50


# --- Revisão final: a única passada de correção --------------------------------


def _sem_privilegio_local(monkeypatch, computador):
    """O processo comum: a biblioteca abre, mas sem o driver todo header volta 0.0."""
    monkeypatch.setattr(sensors, "_state", lambda: (computador, "sem_privilegio"))
    monkeypatch.setattr(sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensors, "_with_dell_thermal", lambda leitura: leitura)


def test_sem_privilegio_o_header_nomeado_em_zero_nao_e_parada(monkeypatch):
    """Important 1 da revisão: sem o driver o SuperIO devolve 0.0 em todo
    header — também no que a placa chama "CPU Fan". Esse 0 não é "parada",
    é "requer administrador"; quem lê a ventoinha de verdade é o helper."""
    chip = _Hardware("SuperIO", "ITE IT8688E",
                     [_Sensor("Fan", "CPU Fan", 0.0, "/lpc/it8688e/0/fan/0")], ident="/lpc/it8688e/0")
    placa = _Hardware("Motherboard", "X", sub=[chip], ident="/motherboard")
    gpu = _Hardware("GpuAmd", "RX", [_Sensor("Temperature", "GPU Core", 54.0, "/gpu-amd/0/temperature/0")],
                    ident="/gpu-amd/0")
    _sem_privilegio_local(monkeypatch, _Computer(placa, gpu))

    leitura = sensors._read_library_sensors()

    assert leitura["gpu_temp_c"] == 54.0, "a GPU continua lida sem privilégio"
    assert leitura["cpu_fan_rpm"] is None


def test_open_que_falha_com_a_placa_mae_tenta_de_novo_sem_ela(monkeypatch, tmp_path):
    """Review Focus 1, segunda metade: ligar a placa-mãe é o que faz `Open()`
    tocar portas de I/O; se isso levanta, a GPU não pode sumir junto."""
    criados = []

    class _Computador:
        def __init__(self):
            self.IsCpuEnabled = self.IsGpuEnabled = False
            self.IsMotherboardEnabled = self.IsMemoryEnabled = False
            criados.append(self)

        def Open(self):  # noqa: N802 — nome da API .NET
            if self.IsMotherboardEnabled:
                raise RuntimeError("SuperIO: porta de I/O recusada")

    class _Biblioteca:
        Computer = _Computador

    dll = tmp_path / "LibreHardwareMonitorLib.dll"
    dll.write_bytes(b"")
    monkeypatch.setattr(sensors, "dll_path", lambda: dll)
    monkeypatch.setattr(sensors, "_import_library", lambda: _Biblioteca)
    monkeypatch.setattr(sensors, "_is_admin", lambda: True)
    sensors._state.cache_clear()
    try:
        computador, motivo = sensors._state()
    finally:
        sensors._state.cache_clear()

    assert motivo is None
    assert len(criados) == 2, "uma tentativa com a placa-mãe, outra sem"
    assert computador is criados[-1] and computador.IsMotherboardEnabled is False


def test_paginas_nao_podem_ser_enquadradas_por_outro_site(tmp_path, monkeypatch):
    """Important 2: as quatro guardas não impedem um site de enquadrar a tela
    Executar invisível e guiar o clique do usuário até o botão (clickjacking).
    O cabeçalho fecha isso em toda página, inclusive nos formulários antigos."""
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    resposta = cliente.get(f"/projects/{pid}/run")
    assert resposta.headers.get("x-frame-options") == "DENY"
    assert "frame-ancestors 'none'" in resposta.headers.get("content-security-policy", "")


def test_segundo_clique_com_pedido_em_voo_nao_abre_segundo_prompt(tmp_path, monkeypatch):
    """Important 3: `runas` bloqueia até o usuário responder; um segundo POST
    nesse meio-tempo não pode abrir um segundo consent.exe."""
    import threading

    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    libera = threading.Event()

    def helper_que_espera_o_usuario(pid):
        chamadas.append(pid)
        libera.wait(5)
        return "refused"

    _sem_privilegio(monkeypatch, chamadas)
    monkeypatch.setattr(sensor_service, "request_helper_now", helper_que_espera_o_usuario)
    try:
        primeiro = cliente.post("/sensors/request-elevation", headers=_guardas())
        assert primeiro.status_code == 202 and primeiro.json()["outcome"] == "requested"
        assert _espera(lambda: len(chamadas) == 1)
        segundo = cliente.post("/sensors/request-elevation", headers=_guardas())
        assert segundo.status_code == 202 and segundo.json()["outcome"] == "pending"
        time.sleep(0.1)
        assert chamadas == [os.getpid()]
    finally:
        libera.set()
    assert _espera(lambda: not modulo_app._SENSOR_REQUEST_IN_FLIGHT.locked())
    assert cliente.post("/sensors/request-elevation", headers=_guardas()).json()["outcome"] == "requested"
    assert _espera(lambda: len(chamadas) == 2)


def test_recusa_antiga_some_antes_do_novo_pedido(tmp_path, monkeypatch):
    """Important 3, outra metade: a tela lê o status do disco a cada 2 s; um
    `refused` da recusa anterior seria lido como resposta ao clique de agora
    enquanto o prompt do Windows ainda está aberto."""
    import threading

    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    sensor_service.write_launch_status("refused")
    assert sensor_service.read_launch_status() == "refused"
    chamadas: list[int] = []
    libera = threading.Event()
    _sem_privilegio(monkeypatch, chamadas)
    monkeypatch.setattr(sensor_service, "request_helper_now",
                        lambda pid: (chamadas.append(pid), libera.wait(5), "refused")[2])
    try:
        assert cliente.post("/sensors/request-elevation", headers=_guardas()).status_code == 202
        assert sensor_service.read_launch_status() is None, "apagado pela rota, antes de disparar"
    finally:
        libera.set()
    assert _espera(lambda: not modulo_app._SENSOR_REQUEST_IN_FLIGHT.locked())


def test_helper_que_levanta_deixa_o_status_unavailable(tmp_path, monkeypatch):
    """Minor 9 da revisão, dobrado no Important 4: uma exceção na thread não
    pode morrer no stderr sem status — é o beco sem saída "Pedido feito" eterno."""
    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[int] = []
    _sem_privilegio(monkeypatch, chamadas)

    def explode(pid):
        chamadas.append(pid)
        raise RuntimeError("helper_command falhou")

    monkeypatch.setattr(sensor_service, "request_helper_now", explode)

    assert cliente.post("/sensors/request-elevation", headers=_guardas()).status_code == 202
    assert _espera(lambda: sensor_service.read_launch_status() == "unavailable")
    assert _espera(lambda: not modulo_app._SENSOR_REQUEST_IN_FLIGHT.locked())


def test_botao_sai_dos_becos_sem_saida(tmp_path, monkeypatch):
    """Important 4: `unavailable` tem ramo próprio e `started` sem números
    tem prazo — depois dele o botão volta, em vez de ficar cinza até fechar
    o programa. (JS: o teste prende o contrato no texto da página.)"""
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/run").text
    assert 'helperStatus === "unavailable"' in html
    assert "SENSOR_WAIT_LIMIT_MS" in html


def test_documentacao_nao_promete_o_que_o_codigo_nao_faz():
    """Minor 2 da revisão, reclassificado: "uma vez por sessão" é falso (cada
    recusa libera novo pedido) e, depois de recusar, a tela diz "requer
    administrador", não "não medido nos dois sensores"."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    arquivos = ("README.md", "docs/README.pt-BR.md", "docs/README.es.md",
                "gclaude_indexer/web/templates/manual/pt.html",
                "gclaude_indexer/web/templates/manual/en.html",
                "gclaude_indexer/web/templates/manual/es.html")
    frases = ("once per session", "uma vez por sessão", "una vez por sesión",
              "nos dois sensores da CPU", "en los dos sensores de la", "for the two CPU sensors")
    for rel in arquivos:
        texto = (raiz / rel).read_text(encoding="utf-8")
        for frase in frases:
            assert frase not in texto, (rel, frase)


# --- Pós-revisão (pedido do usuário): dois minors com teste --------------------


def test_barra_nao_anuncia_o_relogio_a_cada_segundo(tmp_path, monkeypatch):
    """O leitor de tela ouvia o m:ss a cada segundo. A região viva anuncia só
    o início, cada minuto cheio e o fim; o relógio visível fica fora dela."""
    import re

    from gclaude_indexer.i18n import translate

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    html = cliente.get(f"/projects/{pid}/result").text

    relogio = re.search(r'<[^>]*id="wait-clock"[^>]*>', html).group(0)
    assert "aria-live" not in relogio and 'role="status"' not in relogio, "o relógio não pode estar numa região viva"
    anuncio = re.search(r'<[^>]*id="activity-announce"[^>]*>', html).group(0)
    assert 'aria-live="polite"' in anuncio
    assert json.dumps(translate("pt", "activity.minutes")) in html
    assert json.dumps(translate("pt", "activity.finished")) in html


def test_textos_de_anuncio_da_barra_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave in ("activity.minutes", "activity.finished"):
            texto = translate(idioma, chave)
            assert texto != chave and "{operation}" in texto, (idioma, chave)
        assert "{minutes}" in translate(idioma, "activity.minutes")


def test_rotulo_da_barra_e_o_mesmo_no_clique_e_na_retomada():
    """"Gerar relatórios agora" no clique e "Importar e gerar relatórios" depois
    do F5 eram a mesma operação com dois nomes: a retomada usa a chave do
    servidor (`run.import_and_generate`), então o formulário declara a mesma."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / "gclaude_indexer" / "web" / "templates"
    for nome in ("run.html", "result.html"):
        formularios = re.findall(r"<form[^>]*import-and-generate[^>]*>", (templates / nome).read_text(encoding="utf-8"))
        assert formularios, nome
        for formulario in formularios:
            assert "data-activity=\"{{ t('run.import_and_generate') }}\"" in formulario, (nome, formulario)

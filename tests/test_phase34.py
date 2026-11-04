# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 34 — OCR, pausa e VRAM em qualquer máquina.

O processamento de um projeto na 1.7.1 mostrou: OCR de PDF
falhando em toda página escaneada (a pasta privada do Tesseract não tinha
`configs/`), Pausar sem retorno e sem "Continuar", e a VRAM total somando
uma placa que não está mais na máquina. Tudo tem de valer em qualquer
computador, com qualquer placa ou sem placa de vídeo.
"""

from __future__ import annotations

import os
import threading

import pytest

from gclaude_indexer import ocr_languages
from tests.test_phase30 import _tesseract_falso

# --- Task 1: a pasta privada do Tesseract traz os `configs` ------------------------
#
# O ocrmypdf chama `tesseract -l por img out hocr txt`; `hocr` e `txt` são
# arquivos de `TESSDATA_PREFIX\configs`. Sem eles o Tesseract avisa
# ("read_params_file: Can't open hocr"), gera só o `.txt`, e o ocrmypdf
# quebra em `render_hocr_page` (código 15), deixando PDFs sem preparar e
# outros parciais. Com `configs/` na pasta, código 0.


def _com_configs(exe: str) -> None:
    pasta = ocr_languages.tesseract_folder(exe)
    (pasta / "configs").mkdir()
    (pasta / "configs" / "hocr").write_text("tessedit_create_hocr 1\nhocr_font_info 0\n")
    (pasta / "configs" / "txt").write_text("tessedit_create_txt 1\n")
    (pasta / "tessconfigs").mkdir()
    (pasta / "tessconfigs" / "batch.nochop").write_text("chop_enable 0\n")


def test_pasta_privada_ja_existente_sem_configs_e_reparada(tmp_path, monkeypatch):
    """A máquina do usuário: a pasta privada veio da 1.5.19 só com os
    `.traineddata`. A primeira conversão após atualizar precisa repará-la."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    exe = _tesseract_falso(tmp_path, ["eng", "osd"])
    _com_configs(exe)
    privada = tmp_path / "local" / "tessdata"
    privada.mkdir(parents=True)
    for idioma in ("eng", "osd", "por"):
        (privada / f"{idioma}.traineddata").write_bytes(idioma.encode())

    assert ocr_languages.ensure("por", exe) == []

    assert os.environ["TESSDATA_PREFIX"] == str(privada)
    assert (privada / "configs" / "hocr").read_text() == "tessedit_create_hocr 1\nhocr_font_info 0\n"
    assert (privada / "configs" / "txt").is_file()
    assert (privada / "tessconfigs" / "batch.nochop").is_file()


def test_prefixo_ja_apontando_para_a_privada_sem_configs_e_reparado(tmp_path, monkeypatch):
    """Segunda conversão no mesmo processo: `TESSDATA_PREFIX` já é a pasta
    privada. O retorno antecipado "a pasta atual tem os idiomas" não pode
    pular o reparo."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    exe = _tesseract_falso(tmp_path, ["eng"])
    _com_configs(exe)
    privada = tmp_path / "local" / "tessdata"
    privada.mkdir(parents=True)
    for idioma in ("eng", "osd", "por"):
        (privada / f"{idioma}.traineddata").write_bytes(idioma.encode())
    monkeypatch.setenv("TESSDATA_PREFIX", str(privada))

    assert ocr_languages.ensure("por", exe) == []

    assert (privada / "configs" / "hocr").is_file() and (privada / "configs" / "txt").is_file()


def test_tesseract_sem_configs_recebe_os_minimos(tmp_path, monkeypatch):
    """Uma distribuição portátil do Tesseract sem `configs/`: os quatro que
    o ocrmypdf e o pytesseract podem pedir são escritos com o conteúdo
    oficial de uma linha cada."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    exe = _tesseract_falso(tmp_path, ["eng", "osd"])
    monkeypatch.setattr(ocr_languages, "_download", lambda _lang, destino: destino.write_bytes(b"x") or True)

    assert ocr_languages.ensure("por", exe) == []

    configs = tmp_path / "local" / "tessdata" / "configs"
    assert (configs / "hocr").read_text() == "tessedit_create_hocr 1\n"
    assert (configs / "txt").read_text() == "tessedit_create_txt 1\n"
    assert (configs / "pdf").read_text() == "tessedit_create_pdf 1\n"
    assert (configs / "tsv").read_text() == "tessedit_create_tsv 1\n"


def test_tesseract_completo_continua_sem_redirecionamento(tmp_path, monkeypatch):
    """Idiomas e `configs` na pasta do próprio Tesseract: nada é copiado nem
    redirecionado — o comportamento da 1.5.19 para a máquina já pronta."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    exe = _tesseract_falso(tmp_path, ["eng", "por"])
    _com_configs(exe)

    assert ocr_languages.ensure("por", exe) == []

    assert "TESSDATA_PREFIX" not in os.environ
    assert not (tmp_path / "local" / "tessdata").exists()


def test_tesseract_com_idioma_mas_sem_configs_vai_para_a_privada(tmp_path, monkeypatch):
    """Ter o idioma não basta: sem `configs/` o ocrmypdf falha igual. A
    pasta do Tesseract sem eles não é "pronta"; a privada é montada."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    exe = _tesseract_falso(tmp_path, ["eng", "por"])

    assert ocr_languages.ensure("por", exe) == []

    privada = tmp_path / "local" / "tessdata"
    assert os.environ["TESSDATA_PREFIX"] == str(privada)
    assert (privada / "por.traineddata").is_file() and (privada / "configs" / "hocr").is_file()


def test_conversao_acha_o_tesseract_mesmo_fora_do_path(tmp_path, monkeypatch):
    """`pytesseract` só acha `tesseract.exe` pelo `PATH` do processo, e só o
    servidor o corrigia (no arranque). Uma conversão iniciada de outro jeito
    — a suíte de testes num shell sem a entrada do instalador —
    falhava toda imagem com "tesseract is not installed"."""
    import os

    from PIL import Image, ImageDraw

    from gclaude_indexer import tools
    from tests.test_phase3 import _preparar_projeto, convert, scan

    exe = tools.find("tesseract")
    if not exe:
        pytest.skip("sem Tesseract nesta máquina")
    pasta = str(os.path.dirname(exe)).casefold().rstrip("\/")
    sem_tesseract = os.pathsep.join(
        e for e in os.environ.get("PATH", "").split(os.pathsep) if e.casefold().rstrip("\/") != pasta
    )
    monkeypatch.setenv("PATH", sem_tesseract)
    origem, _saida, config, conn = _preparar_projeto(tmp_path)
    imagem = Image.new("RGB", (900, 300), "white")
    ImageDraw.Draw(imagem).text((30, 120), "FOTO DE DOCUMENTO PARA TESTE", fill="black")
    imagem.save(origem / "foto.jpg")
    scan(conn, config)

    resultado = convert(conn, config)

    assert (resultado.converted, resultado.failed) == (1, 0)
    conn.close()


# --- Task 2: Pausar dá retorno e Continuar retoma ----------------------------------
#
# Numa execução, o clique em Pausar chegou durante a carga do modelo; o
# pedido só é lido entre janelas, e por mais de um minuto nada
# mudou na tela: o botão redesenhava `#steps` (visualmente igual) e sumia
# quando o estado deixava de ser "rodando", sem nada no lugar que dissesse
# "continuar". E `TaskManager.pause` só sinalizava tarefas em execução —
# no intervalo de 0,3 s entre etapas do "Rodar tudo", o clique era ignorado.

from gclaude_indexer.i18n import translate
from gclaude_indexer.run_control import StopSignal
from gclaude_indexer.web import background_runs
from gclaude_indexer.web.background_runs import StepTask, task_manager
from tests.test_phase31 import _app_com_projeto


def _tarefa(**campos) -> StepTask:
    base = dict(step="classification", total=241, baseline=0)
    base.update(campos)
    return StepTask(**base)


def test_parada_pedida_aparece_como_parando_ate_a_tarefa_encerrar():
    tarefa = _tarefa()
    assert background_runs._progress_dict(tarefa, 1, None)["stop_requested"] is False
    tarefa.stop_signal.request_stop()
    progresso = background_runs._progress_dict(tarefa, 1, None)
    assert (progresso["status"], progresso["stop_requested"]) == ("running", True)
    # Erro continua tendo prioridade: um traceback não pode virar "parando".
    tarefa.error = "falhou"
    assert background_runs._progress_dict(tarefa, 1, None)["status"] == "error"
    # Encerrada de fato: "stopped", e o pedido já não é novidade.
    tarefa.error, tarefa.running = None, False
    progresso = background_runs._progress_dict(tarefa, 1, None)
    assert (progresso["status"], progresso["stop_requested"]) == ("stopped", False)


def test_contagem_e_busca_completa_tambem_mostram_parando():
    contando = _tarefa(step="scan", counting=True)
    contando.stop_signal.request_stop()
    assert background_runs.compute_progress("", contando)["stop_requested"] is True
    extraindo = _tarefa(step="extraction")
    extraindo.stop_signal.request_stop()
    assert background_runs._fulltext_progress_dict(extraindo, 3, 10)["stop_requested"] is True


def test_clique_em_pausar_devolve_o_quadro_de_progresso_parando(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    tarefa = _tarefa()
    monkeypatch.setitem(task_manager._tasks, (pid, "classification"), tarefa)

    resposta = cliente.post(f"/projects/{pid}/pause", cookies={"language": "pt"})

    assert resposta.status_code == 200
    assert tarefa.stop_signal.should_stop(), "o pedido chegou à tarefa"
    assert translate("pt", "run.stopping") in resposta.text, "a resposta é o quadro de progresso, já em 'parando'"
    assert "/pause" not in resposta.text, "sem segundo botão Pausar enquanto para"
    assert 'class="progress-box"' in resposta.text


def test_quadro_pausado_oferece_continuar(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    parada = _tarefa(running=False)
    monkeypatch.setitem(task_manager._tasks, (pid, "classification"), parada)

    resposta = cliente.get(f"/projects/{pid}/run/progress", cookies={"language": "pt"})

    assert translate("pt", "run.resume") in resposta.text
    assert f'hx-post="/projects/{pid}/resume"' in resposta.text, "continuar = a cadeia a partir da etapa pendente"
    from markupsafe import escape

    assert str(escape(translate("pt", "run.paused"))) in resposta.text, "as aspas do texto saem escapadas pelo Jinja"


def test_botao_pausar_troca_o_proprio_quadro(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setitem(task_manager._tasks, (pid, "classification"), _tarefa())

    resposta = cliente.get(f"/projects/{pid}/run/progress", cookies={"language": "pt"})

    assert f'hx-post="/projects/{pid}/pause" hx-target="#progress"' in resposta.text


def test_pausa_entre_etapas_impede_a_proxima_de_comecar(tmp_path, monkeypatch):
    """O clique no intervalo de 0,3 s entre etapas: nenhuma tarefa roda, e
    `pause` precisa alcançar o sinal da cadeia mesmo assim."""
    import threading

    from gclaude_indexer.config import ProjectConfig

    iniciadas: list[str] = []
    terminou = threading.Event()
    resultado_da_pausa: list[bool] = []

    def start_step_falso(project_id, _pasta, _config, step, stop_signal=None, language=None):
        iniciadas.append(step)
        # A etapa já terminou quando o clique chega — exatamente o intervalo.
        resultado_da_pausa.append(task_manager.pause(project_id))
        return _tarefa(step=step, running=False, finished_ok=True, stop_signal=stop_signal or StopSignal())

    monkeypatch.setattr(task_manager, "start_step", start_step_falso)
    original = background_runs.STEP_ORDER
    monkeypatch.setattr(background_runs, "STEP_ORDER", original)
    config = ProjectConfig(name="x", source_folder=str(tmp_path), output_folder=str(tmp_path))

    sinal = task_manager.start_all(9034, str(tmp_path), config)
    for _ in range(100):
        if 9034 not in task_manager._chains:
            terminou.set()
            break
        threading.Event().wait(0.02)

    assert terminou.is_set(), "a cadeia se desregistra ao terminar"
    assert iniciadas == [original[0]], "só a primeira etapa começou"
    assert resultado_da_pausa == [True] and sinal.should_stop()


def test_pausa_sem_nada_rodando_continua_dizendo_que_nao_pausou():
    assert task_manager.pause(9035) is False


def test_textos_de_parando_e_continuar_nos_tres_idiomas():
    for idioma in ("pt", "en", "es"):
        for chave in ("run.stopping", "run.resume"):
            assert translate(idioma, chave) != chave, (idioma, chave)
        assert "Rodar etapa seguinte" not in translate(idioma, "run.paused")
        assert "Run next step" not in translate(idioma, "run.paused")


# --- Task 3: VRAM total só da placa presente --------------------------------------
#
# O registro guarda a chave da placa removida (RX 5700 XT, 8176 MB) ao lado
# da atual (RX 6700 XT, 12272 MB); somar toda subchave da classe de vídeo
# dava 20448 MB para uma placa de 12 GB. O caminho agora parte dos
# controladores presentes (`Win32_VideoController`) e segue ao driver.

from gclaude_indexer import hardware, windows_counters


class _Saida:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


def test_so_o_adaptador_presente_entra_na_vram_total(monkeypatch):
    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: ["AMD Radeon RX 6700 XT;12868124672;4293918720"])
    assert windows_counters.present_adapters() == [("AMD Radeon RX 6700 XT", 12272)]
    assert windows_counters.vram_total_mb() == 12272


def test_sem_placa_de_video_a_vram_total_e_desconhecida(monkeypatch):
    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: [])
    assert windows_counters.vram_total_mb() is None
    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: None)
    assert windows_counters.vram_total_mb() is None


def test_linha_malformada_e_ignorada_e_adapterram_e_a_reserva():
    linhas = ["Intel UHD 630;0;1073741824", "lixo", "x;abc;def", ";123;456", "Sem memória;0;0"]
    assert windows_counters._parse_adapters(linhas) == [("Intel UHD 630", 1024)]


def test_igpu_e_dedicada_a_maior_da_o_nome_e_o_total(monkeypatch):
    """Num notebook a primeira linha do WMI costuma ser a integrada; a placa
    do diagnóstico é a de mais memória, e o total é o dela."""
    import json

    linhas = ["Intel UHD 770;1073741824;1073741824", "NVIDIA GeForce RTX 4070;12884901888;4293918720"]
    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: linhas)
    wmi = [
        {"Name": "Intel UHD 770", "AdapterRAM": 1073741824, "AdapterCompatibility": "Intel Corporation"},
        {"Name": "NVIDIA GeForce RTX 4070", "AdapterRAM": 4293918720, "AdapterCompatibility": "NVIDIA"},
    ]
    monkeypatch.setattr(hardware, "run_hidden", lambda *a, **k: _Saida(json.dumps(wmi)))
    monkeypatch.setattr(hardware.sys, "platform", "win32")

    gpu = hardware._detect_wmi_gpu()

    # Revisão final: o total é o do maior adaptador, não a soma (Important 5).
    assert (gpu.name, gpu.vendor, gpu.vram_mb) == ("NVIDIA GeForce RTX 4070", "NVIDIA", 12288)


def test_sem_chave_de_driver_o_diagnostico_cai_no_adapterram(monkeypatch):
    import json

    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: None)
    wmi = {"Name": "Placa X", "AdapterRAM": 2147483648, "AdapterCompatibility": "Y"}
    monkeypatch.setattr(hardware, "run_hidden", lambda *a, **k: _Saida(json.dumps(wmi)))
    monkeypatch.setattr(hardware.sys, "platform", "win32")

    gpu = hardware._detect_wmi_gpu()

    assert (gpu.name, gpu.vram_mb) == ("Placa X", 2048)


def test_sem_controlador_de_video_o_diagnostico_nao_inventa_placa(monkeypatch):
    monkeypatch.setattr(hardware, "run_hidden", lambda *a, **k: _Saida(""))
    monkeypatch.setattr(hardware.sys, "platform", "win32")
    assert hardware._detect_wmi_gpu() is None


# --- Task 4: VRAM usada entre os sensores da placa --------------------------------
#
# A biblioteca expõe nesta placa `GPU Memory Used` (8883 MB com o modelo
# carregado), `GPU Memory Free` e `GPU Memory Total` (12272 MB), tipo
# `SmallData`, preenchidos **sem** elevação — por isso essas chaves ficam
# fora do critério "tudo zero = sem privilégio".

from gclaude_indexer import sensors
from tests.test_phase32 import _Computer, _Hardware, _Sensor, _como_admin


def _gpu_com_memoria(temp=50.0, usada=8883.0, total=12272.0, d3d_usada=8800.0):
    return _Hardware("GpuAmd", "RX 6700 XT", [
        _Sensor("Temperature", "GPU Core", temp, "/gpu-amd/0/temperature/0"),
        _Sensor("SmallData", "D3D Dedicated Memory Used", d3d_usada, "/gpu-amd/0/smalldata/2"),
        _Sensor("SmallData", "GPU Memory Used", usada, "/gpu-amd/0/smalldata/0"),
        _Sensor("SmallData", "GPU Memory Total", total, "/gpu-amd/0/smalldata/1"),
        _Sensor("SmallData", "GPU Memory Free", total - usada, "/gpu-amd/0/smalldata/3"),
    ], ident="/gpu-amd/0")


def test_vram_usada_e_total_vem_da_biblioteca(monkeypatch):
    _como_admin(monkeypatch, _Computer(_gpu_com_memoria()))
    leitura = sensors._read_library_sensors()
    assert (leitura["gpu_vram_usada_mb"], leitura["gpu_vram_total_mb"]) == (8883, 12272)
    assert leitura["gpu_temp_c"] == 50.0


def test_igpu_que_so_tem_d3d_usa_a_memoria_dedicada(monkeypatch):
    """Uma Intel integrada não traz `GPU Memory *`; o par `D3D Dedicated
    Memory Used/Total` é o que a biblioteca dá para ela."""
    intel = _Hardware("GpuIntel", "Intel UHD 770", [
        _Sensor("SmallData", "D3D Dedicated Memory Used", 212.0, "/gpu-intel/0/smalldata/0"),
        _Sensor("SmallData", "D3D Dedicated Memory Total", 1024.0, "/gpu-intel/0/smalldata/1"),
        _Sensor("Temperature", "GPU Core", 41.0, "/gpu-intel/0/temperature/0"),
    ], ident="/gpu-intel/0")
    _como_admin(monkeypatch, _Computer(intel))
    leitura = sensors._read_library_sensors()
    assert (leitura["gpu_vram_usada_mb"], leitura["gpu_vram_total_mb"]) == (212, 1024)


def test_sem_privilegio_a_memoria_nao_transforma_zeros_em_medicao(monkeypatch):
    """Sem o driver, temperaturas, potências e ventoinhas voltam 0.0 e a
    leitura era descartada por estar toda zerada. A memória vem preenchida
    mesmo assim: ela fica, e os zeros continuam sendo "não medido"."""
    placa = _gpu_com_memoria(temp=0.0)
    placa.Sensors.append(_Sensor("Fan", "GPU Fan", 0.0, "/gpu-amd/0/fan/0"))
    placa.Sensors.append(_Sensor("Power", "GPU Package", 0.0, "/gpu-amd/0/power/0"))
    monkeypatch.setattr(sensors, "_state", lambda: (_Computer(placa), "sem_privilegio"))
    monkeypatch.setattr(sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensors, "_with_dell_thermal", lambda leitura: leitura)

    leitura = sensors._read_library_sensors()

    assert (leitura["gpu_vram_usada_mb"], leitura["gpu_vram_total_mb"]) == (8883, 12272)
    assert leitura["gpu_temp_c"] is None and leitura["gpu_potencia_w"] is None
    assert leitura["gpu_fan_rpm"] is None, "0 RPM sem privilégio não é zero-RPM medido"


def test_sem_placa_de_video_as_chaves_de_memoria_ficam_vazias(monkeypatch):
    cpu = _Hardware("Cpu", "Ryzen", [_Sensor("Temperature", "Core (Tctl/Tdie)", 42.0, "/amdcpu/0/temperature/2")],
                    ident="/amdcpu/0")
    _como_admin(monkeypatch, _Computer(cpu))
    leitura = sensors._read_library_sensors()
    assert leitura["gpu_vram_usada_mb"] is None and leitura["gpu_vram_total_mb"] is None
    assert leitura["cpu_temp_c"] == 42.0


def test_amostra_prefere_a_vram_da_biblioteca_e_cai_nos_contadores(monkeypatch):
    import gclaude_indexer.resources as resources_mod

    monkeypatch.setattr(resources_mod, "find_tool", lambda _n: None)
    monkeypatch.setattr(resources_mod, "gpu_usage_percent", lambda: 20.0)
    monkeypatch.setattr(resources_mod, "vram_used_mb", lambda: 1602)
    monkeypatch.setattr(resources_mod, "_vram_total_mb", lambda: 8176)
    com_memoria = dict.fromkeys(sensors.KEYS)
    com_memoria.update(gpu_vram_usada_mb=8883, gpu_vram_total_mb=12272)
    monkeypatch.setattr(resources_mod, "read_sensors", lambda: com_memoria)

    amostra = resources_mod.sample_resources()
    assert (amostra.gpu_vram_used_mb, amostra.gpu_vram_total_mb) == (8883, 12272)

    monkeypatch.setattr(resources_mod, "read_sensors", lambda: dict.fromkeys(sensors.KEYS))
    amostra = resources_mod.sample_resources()
    assert (amostra.gpu_vram_used_mb, amostra.gpu_vram_total_mb) == (1602, 8176)


def test_tela_mostra_a_vram_entre_os_sensores_da_gpu():
    from pathlib import Path

    html = Path("gclaude_indexer/web/templates/run.html").read_text(encoding="utf-8")
    assert 'id="vram-gpu"' in html and "t('resources.vram')" in html
    assert "gpu_vram_used_mb" in html.split('id="vram-gpu"', 1)[1], "o script preenche a linha nova"
    for idioma in ("pt", "en", "es"):
        assert translate(idioma, "resources.vram") != "resources.vram", idioma


# --- Revisão própria: OCR falho entra no plano de "Atualizar" ---------------------
#
# `requeue_ocr_failures` só refaz um arquivo 'extracted' enquanto o projeto
# não tem janelas (refazê-lo deixaria as janelas com as páginas em branco
# antigas) e manda olhar "a atualização do projeto" — que até aqui só via
# bytes. Os PDFs parciais ficariam com páginas em branco para sempre.


def test_arquivo_com_ocr_falho_entra_no_plano_como_a_refazer(tmp_path):
    from gclaude_indexer.update_plan import detect_changes
    from tests.test_phase17 import _config, _conn, _registrar

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    arquivo = origem / "a.pdf"
    arquivo.write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", arquivo.stat().st_mtime)  # bytes iguais, mtime igual
    conn.execute("UPDATE file SET ocr_failed = 1")
    conn.commit()

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert [(m.relative_path, m.kind) for m in mudancas] == [("a.pdf", "changed")]
    assert inalterados == 0

    conn.execute("UPDATE file SET ocr_failed = 0")
    conn.commit()
    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))
    assert mudancas == [] and inalterados == 1


# --- Revisão final: a única passada de correção -------------------------------------


def test_com_integrada_e_dedicada_a_memoria_e_a_da_placa_de_mais_vram(monkeypatch):
    """Important 2: a biblioteca lista a integrada AMD antes da dedicada; a
    primeira com `SmallData` vencia, e a tela passava a mostrar 300 / 512 MB
    enquanto o modelo ocupava 6 GB da dedicada."""
    integrada = _Hardware("GpuAmd", "AMD Radeon(TM) Graphics", [
        _Sensor("SmallData", "GPU Memory Used", 300.0, "/gpu-amd/0/smalldata/0"),
        _Sensor("SmallData", "GPU Memory Total", 512.0, "/gpu-amd/0/smalldata/1"),
        _Sensor("Temperature", "GPU Core", 45.0, "/gpu-amd/0/temperature/0"),
    ], ident="/gpu-amd/0")
    dedicada = _Hardware("GpuNvidia", "NVIDIA GeForce RTX 4060 Laptop", [
        _Sensor("SmallData", "GPU Memory Used", 6000.0, "/gpu-nvidia/0/smalldata/0"),
        _Sensor("SmallData", "GPU Memory Total", 8192.0, "/gpu-nvidia/0/smalldata/1"),
    ], ident="/gpu-nvidia/0")
    _como_admin(monkeypatch, _Computer(integrada, dedicada))
    leitura = sensors._read_library_sensors()
    assert (leitura["gpu_vram_usada_mb"], leitura["gpu_vram_total_mb"]) == (6000, 8192)


def test_vram_total_e_a_do_maior_adaptador_presente(monkeypatch):
    """Important 5: o modelo roda numa placa, não na soma. Integrada de 2 GB
    + dedicada de 6 GB somavam 8 GB, o suficiente para recomendar o modelo
    grande e pedir camadas que a dedicada não tem."""
    linhas = ["AMD Radeon(TM) Graphics;2147483648;2147483648", "NVIDIA GeForce RTX 3060 Laptop;6442450944;4293918720"]
    monkeypatch.setattr(windows_counters, "_query_lines", lambda _c: linhas)
    assert windows_counters.vram_total_mb() == 6144


def test_nome_de_adaptador_com_ponto_e_virgula_nao_e_descartado():
    assert windows_counters._parse_adapters(["Placa; modelo X;1073741824;0"]) == [("Placa; modelo X", 1024)]


def test_consulta_de_frequencia_da_cpu_nao_depende_do_idioma_do_windows(monkeypatch):
    """Important 4: o nome do conjunto de contadores é traduzido pelo Windows
    ("Información del procesador" em espanhol não casava com nada)."""
    script = windows_counters._PS_CPU_CLOCK
    assert "Informações" not in script and "Processor Information" not in script
    assert "Win32_PerfFormattedData_Counters_ProcessorInformation" in script
    monkeypatch.setattr(windows_counters, "_query", lambda _c: "3600")
    assert windows_counters._clock_cpu_mhz_uncached() == 3600


def test_continuar_retoma_a_cadeia_a_partir_da_etapa_pendente(tmp_path, monkeypatch):
    """Important 3: "Rodar tudo" sempre recomeça pelo scan (minutos numa
    pasta grande do Drive); Continuar tem de partir da etapa parada."""
    from gclaude_indexer.config import ProjectConfig

    iniciadas: list[str] = []

    def start_step_falso(project_id, _pasta, _config, step, stop_signal=None, language=None):
        iniciadas.append(step)
        return _tarefa(step=step, running=False, finished_ok=True, stop_signal=stop_signal or StopSignal())

    monkeypatch.setattr(task_manager, "start_step", start_step_falso)
    config = ProjectConfig(name="x", source_folder=str(tmp_path), output_folder=str(tmp_path))
    task_manager.start_all(9036, str(tmp_path), config, first_step="windows")
    for _ in range(100):
        if 9036 not in task_manager._chains:
            break
        threading.Event().wait(0.02)
    assert iniciadas == ["windows", "classification"]


def test_rota_de_continuar_parte_da_proxima_etapa_pendente(tmp_path, monkeypatch):
    from gclaude_indexer.web.step_state import next_pending_step, step_status

    cliente, pid, conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[dict] = []
    monkeypatch.setattr(task_manager, "start_all", lambda *a, **k: chamadas.append(k) or StopSignal())
    esperada = next_pending_step(step_status(conn, lambda _k: False))

    resposta = cliente.post(f"/projects/{pid}/resume", cookies={"language": "pt"})

    assert resposta.status_code == 200
    assert [c.get("first_step") for c in chamadas] == [esperada]


def test_quadro_pausado_continua_pela_rota_de_retomada(tmp_path, monkeypatch):
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setitem(task_manager._tasks, (pid, "classification"), _tarefa(running=False))
    resposta = cliente.get(f"/projects/{pid}/run/progress", cookies={"language": "pt"})
    assert f'hx-post="/projects/{pid}/resume"' in resposta.text
    assert f'hx-post="/projects/{pid}/run-all"' not in resposta.text


def test_etapa_concluida_com_outras_pendentes_tambem_oferece_continuar(tmp_path, monkeypatch):
    """Minor 4: a pausa que cai entre duas etapas para a cadeia sem deixar
    tarefa "parada" — a última está concluída. O botão aparece mesmo assim,
    enquanto houver etapa pendente."""
    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setitem(task_manager._tasks, (pid, "scan"), _tarefa(step="scan", running=False, finished_ok=True))
    resposta = cliente.get(f"/projects/{pid}/run/progress", cookies={"language": "pt"})
    assert translate("pt", "run.resume") in resposta.text


def test_pausa_alcanca_todas_as_cadeias_do_projeto():
    """Duplo clique em "Rodar tudo"/Continuar abre duas cadeias; a pausa
    entre etapas tem de parar as duas, não só a última registrada."""
    primeira, segunda = StopSignal(), StopSignal()
    task_manager._chains[9037] = [primeira, segunda]
    try:
        assert task_manager.pause(9037) is True
        assert primeira.should_stop() and segunda.should_stop()
    finally:
        task_manager._chains.pop(9037, None)


def test_snapshot_de_um_auxiliar_antigo_com_menos_chaves_e_aceito(tmp_path, monkeypatch):
    """Minor 5: um auxiliar elevado da versão anterior ainda no ar publica 8
    chaves; rejeitá-lo apagaria a temperatura da CPU até reiniciar."""
    import json

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    antigas = [k for k in sensors.KEYS if k not in ("gpu_vram_usada_mb", "gpu_vram_total_mb")]
    sensors.write_snapshot({k: 1 for k in antigas})
    caminho = sensors.snapshot_path()
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados["reading"] = {k: 1 for k in antigas}
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    leitura = sensors.read_snapshot()

    assert leitura is not None and leitura["cpu_temp_c"] == 1 and leitura["gpu_vram_usada_mb"] is None
    dados["reading"]["chave_estranha"] = 1
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    assert sensors.read_snapshot() is None, "chave desconhecida continua rejeitada"


def test_linha_de_vram_sem_total_nao_escreve_null():
    from pathlib import Path

    html = Path("gclaude_indexer/web/templates/run.html").read_text(encoding="utf-8")
    assert html.count("gpu_vram_total_mb == null") >= 1

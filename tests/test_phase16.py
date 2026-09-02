# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 16 — os oito defeitos relatados após a instalação numa segunda máquina.

1. Janelas de console piscando durante a conversão (OCR/Ghostscript).
2. Sensores de CPU não abrem mesmo com o atalho elevado.
3. A VRAM não é preenchida antes de transbordar para a RAM.
4. Não havia desinstalador.
5. Era preciso reiniciar o computador para o sistema funcionar.
6. A tela de log não deixava rolar, selecionar nem copiar.
7. A previsão de conclusão era calculada de forma equivocada.
8. Os projetos salvos não apareciam em outro computador.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def pasta_local(tmp_path, monkeypatch):
    """Aponta `machine_local_folder()` para uma pasta descartável."""
    from gclaude_indexer import paths

    destino = tmp_path / "local"
    destino.mkdir()
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(destino))
    return destino


# --- 1. janelas de console -------------------------------------------------


def test_o_patch_de_janela_e_idempotente_e_reversivel():
    from gclaude_indexer import no_window

    original = subprocess.Popen.__init__
    try:
        # Parte de um estado conhecido: o patch é global ao processo e
        # `convert()` já pode tê-lo instalado num teste anterior da suíte —
        # exatamente o que ele faz em produção.
        while no_window.uninstall():
            pass
        primeiro = no_window.install()
        segundo = no_window.install()
        if sys.platform == "win32":
            assert primeiro is True
            # Instalar duas vezes não empilha dois wrappers — o pool de
            # conversão e a subida do servidor chamam os dois.
            assert segundo is False
            assert no_window.is_installed()
        else:
            assert primeiro is False
    finally:
        no_window.uninstall()
        subprocess.Popen.__init__ = original


@pytest.mark.skipif(sys.platform != "win32", reason="CREATE_NO_WINDOW só existe no Windows")
def test_o_patch_adiciona_create_no_window_sem_desfazer_escolha_explicita():
    from gclaude_indexer import no_window

    assert no_window._merge_flags(0) == subprocess.CREATE_NO_WINDOW
    # Quem pediu um console de verdade continua com ele: as duas flags são
    # contraditórias e o Windows recusa a combinação.
    assert no_window._merge_flags(subprocess.CREATE_NEW_CONSOLE) == subprocess.CREATE_NEW_CONSOLE
    assert no_window._merge_flags(subprocess.DETACHED_PROCESS) == subprocess.DETACHED_PROCESS


def test_as_posicoes_dos_parametros_do_popen_conferem_com_o_cpython_atual():
    """O patch injeta `startupinfo`/`creationflags` como palavra-chave e
    precisa saber onde eles ficam posicionalmente: preencher por
    palavra-chave um parâmetro já passado por posição levanta `TypeError`.
    Um CPython futuro que reordene a assinatura é pego aqui, e não no meio
    de um OCR de alguém."""
    import inspect

    from gclaude_indexer import no_window

    # A assinatura tem que vir da função original: o patch é global ao
    # processo e, uma vez instalado por outro teste, `Popen.__init__` é o
    # wrapper `(self, *args, **kwargs)`.
    inicializador = getattr(
        subprocess.Popen.__init__, "_gclaude_original_init", subprocess.Popen.__init__
    )
    parametros = list(inspect.signature(inicializador).parameters)
    assert parametros.index("startupinfo") - 1 == no_window._STARTUPINFO_INDEX
    assert parametros.index("creationflags") - 1 == no_window._CREATIONFLAGS_INDEX


def test_o_patch_nao_quebra_uma_chamada_real_de_subprocesso():
    """O caminho que importa de verdade: com o patch instalado, um comando
    comum continua rodando e devolvendo a saída."""
    from gclaude_indexer import no_window

    instalou = no_window.install()
    try:
        resultado = subprocess.run(
            [sys.executable, "-B", "-c", "print('ok')"], capture_output=True, text=True
        )
        assert resultado.returncode == 0
        assert resultado.stdout.strip() == "ok"
    finally:
        if instalou:
            no_window.uninstall()


def test_o_ocr_roda_pelo_runner_que_esconde_as_janelas(tmp_path, monkeypatch):
    """O `ocrmypdf` é chamado por `_ocr_runner`, não direto.

    É o processo que dispara `tesseract.exe` e `gswin64c.exe`: só ali
    adianta ligar a supressão de janelas (ver `no_window.py`).
    """
    from gclaude_indexer import conversion

    capturado: dict = {}

    class _Resultado:
        returncode = 0
        stderr = ""

    def _falso_run(comando, **kwargs):
        capturado["comando"] = comando
        capturado["kwargs"] = kwargs
        return _Resultado()

    monkeypatch.setattr(conversion.subprocess, "run", _falso_run)
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=2)

    comando = capturado["comando"]
    # `-B`: a pasta do projeto e sincronizada pelo Drive e nunca pode
    # receber um `__pycache__` (secao 11.1).
    assert comando[1] == "-B"
    assert comando[2] == "-m"
    assert comando[3] == "gclaude_indexer._ocr_runner"
    assert "ocrmypdf" not in comando

    if sys.platform == "win32":
        assert capturado["kwargs"]["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_o_ambiente_do_ocr_leva_o_gancho_para_os_processos_netos():
    """O `sitecustomize.py` tem que estar no PYTHONPATH do OCR.

    Com `--jobs > 1` o próprio ocrmypdf cria um pool de interpretadores
    novos, e cada um deles é o pai direto de um `tesseract.exe`. O
    `install()` do runner não alcança esses netos; o `sitecustomize`, que o
    módulo `site` importa em todo interpretador, alcança.
    """
    from gclaude_indexer import conversion

    ambiente = conversion._ocr_environment()
    caminhos = ambiente["PYTHONPATH"].split(";" if sys.platform == "win32" else ":")
    assert any(caminho.endswith("_nowindow_site") for caminho in caminhos)

    gancho = Path(conversion.__file__).resolve().parent / "_nowindow_site" / "sitecustomize.py"
    assert gancho.is_file()
    assert "no_window" in gancho.read_text(encoding="utf-8")


# --- 2. sensores elevados --------------------------------------------------


def test_o_auxiliar_elevado_roda_de_uma_copia_local(pasta_local):
    """O processo elevado não enxerga o drive virtual do Google Drive.

    O token de administrador é a outra metade do token dividido da conta, e
    o Windows não leva os mapeamentos de unidade de uma metade para a
    outra: `H:\\...` simplesmente não existe para o filho elevado. Sem
    espelhar os módulos numa pasta local, o `-m gclaude_indexer.sensor_service`
    falhava antes de executar uma linha nossa — e como o auxiliar sobe com
    `pythonw.exe` e `SW_HIDE`, o erro não aparecia em lugar nenhum.
    """
    from gclaude_indexer import sensor_service

    raiz = sensor_service.stage_helper_modules()
    assert raiz == pasta_local / "helper"
    for nome in sensor_service.HELPER_MODULES:
        assert (raiz / "gclaude_indexer" / nome).is_file()


def test_a_pasta_local_do_servidor_vai_na_linha_de_comando(pasta_local):
    from gclaude_indexer import sensor_service

    _programa, argumentos = sensor_service.helper_command(99)
    assert "--local-folder" in argumentos
    assert argumentos[argumentos.index("--local-folder") + 1] == str(pasta_local)


def test_a_tela_avisa_quando_o_auxiliar_subiu_e_nao_respondeu(pasta_local, monkeypatch):
    """Estado que antes era indistinguível de "nunca tentou".

    Sem isso, a tela mandava o usuário abrir pelo atalho do sensor de CPU —
    exatamente o que ele já tinha feito.
    """
    from gclaude_indexer import sensor_service, sensors

    sensors._state.cache_clear()
    monkeypatch.setattr(sensors, "_state", lambda: (object(), "sem_privilegio"))
    monkeypatch.setattr(sensors, "read_snapshot", lambda: None)

    sensor_service.write_launch_status("started")
    assert sensors.unavailable_reason() == "helper_sem_resposta"

    sensor_service.write_launch_status("refused")
    assert sensors.unavailable_reason() == "sem_privilegio"


def test_todo_motivo_de_sensor_tem_texto_nos_tres_idiomas():
    from gclaude_indexer.i18n import AVAILABLE_LANGUAGES, has_key
    from gclaude_indexer.install_diagnostics import _SENSOR_REASON_KEYS

    for chave in _SENSOR_REASON_KEYS.values():
        assert has_key(chave), chave
    for idioma in AVAILABLE_LANGUAGES:
        for chave in _SENSOR_REASON_KEYS.values():
            from gclaude_indexer.i18n import translate

            assert translate(idioma, chave) != chave


# --- 3. uso da VRAM --------------------------------------------------------


def test_o_modelo_inteiro_vai_para_a_gpu_quando_cabe():
    from gclaude_indexer.gpu_budget import ModelShape, layers_that_fit

    # 4 GB de pesos, 32 camadas, numa placa com 12 GB livres: cabe inteiro.
    forma = ModelShape(
        total_bytes=4 * 1024**3, layer_count=32,
        embedding_length=4096, head_count=32, head_count_kv=8,
    )
    assert layers_that_fit(forma, free_vram_mb=12288, context_tokens=8192) == 33


def test_o_modelo_que_nao_cabe_inteiro_fica_com_o_escalonador_do_ollama():
    """Correção medida na revisão de qualidade, não deduzida.

    A versão anterior calculava um número parcial de camadas quando o
    modelo não cabia. Medido no acervo real: com 4712 MB disponíveis ela
    pediu 18 de 43 camadas, e o Ollama passou a colocar 1849 MB na placa
    onde antes colocava 3108 MB — a estimativa substituiu a divisão do
    escalonador por uma PIOR e deixou a execução mais lenta.

    O custo por camada aqui é o tamanho do arquivo dividido pelas camadas,
    um número grosseiro; o Ollama conhece o tamanho real de cada tensor.
    Então a regra é assimétrica de propósito: só sobrepõe o `-1` quando dá
    para afirmar com certeza que cabe TUDO.
    """
    from gclaude_indexer.gpu_budget import ModelShape, layers_that_fit

    forma = ModelShape(
        total_bytes=16 * 1024**3, layer_count=48,
        embedding_length=5120, head_count=40, head_count_kv=8,
    )
    assert layers_that_fit(forma, free_vram_mb=8192, context_tokens=8192) is None


def test_sem_medida_confiavel_a_decisao_volta_para_o_ollama():
    """Degradar para o comportamento anterior, nunca para um pior."""
    from gclaude_indexer.gpu_budget import ModelShape, layers_that_fit

    forma = ModelShape(total_bytes=4 * 1024**3, layer_count=32)
    assert layers_that_fit(forma, free_vram_mb=None, context_tokens=4096) is None
    assert layers_that_fit(forma, free_vram_mb=0, context_tokens=4096) is None
    # Menos VRAM livre que a margem de segurança: não há orçamento honesto
    # para dividir, e forçar camadas numa placa cheia mata a execução.
    assert layers_that_fit(forma, free_vram_mb=100, context_tokens=4096) is None


def test_as_camadas_vem_do_modelo_de_linguagem_e_nao_da_torre_de_audio():
    """Medido no `gemma4:e4b` contra o Ollama real desta máquina.

    Um modelo multimodal publica `gemma4.block_count = 42` para o modelo de
    texto e `gemma4.audio.block_count = 12` para a torre de áudio — e a de
    áudio vem antes no mapa. Casar só pelo sufixo lia 12 no lugar de 42 e
    errava o custo por camada em mais de três vezes.
    """
    from gclaude_indexer.gpu_budget import _suffix_value

    model_info = {
        "general.architecture": "gemma4",
        "gemma4.audio.block_count": 12,
        "gemma4.vision.block_count": 16,
        "gemma4.block_count": 42,
        "gemma4.audio.embedding_length": 1024,
        "gemma4.embedding_length": 2560,
    }
    assert _suffix_value(model_info, "block_count") == 42
    assert _suffix_value(model_info, "embedding_length") == 2560

    # Sem `general.architecture`, as chaves de submodelo continuam de fora.
    sem_arquitetura = {k: v for k, v in model_info.items() if k != "general.architecture"}
    assert _suffix_value(sem_arquitetura, "block_count") == 42


def test_sem_head_count_kv_o_modelo_usa_atencao_completa():
    """`qwen3.5:9b` publica `attention.head_count_kv` como null: não usa
    grouped-query attention, então cada cabeça tem seu próprio par
    chave/valor. Zerado, o cache KV inteiro sumiria da conta."""
    from gclaude_indexer.gpu_budget import ModelShape

    forma = ModelShape(
        total_bytes=1000, layer_count=32,
        embedding_length=4096, head_count=16, head_count_kv=16,
    )
    assert forma.kv_bytes_per_token(1) > 0


def test_o_servidor_do_ollama_recebe_as_variaveis_que_liberam_vram():
    from gclaude_indexer.gpu_budget import SERVER_ENVIRONMENT, server_environment

    ambiente = server_environment({})
    # A maior fonte de VRAM desperdiçada: o padrão dimensiona o cache KV
    # para quatro requisições simultâneas e este classificador manda uma.
    assert ambiente["OLLAMA_NUM_PARALLEL"] == "1"
    assert ambiente["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
    assert ambiente["OLLAMA_FLASH_ATTENTION"] == "1"

    # Quem já tinha definido a variável na mão continua mandando nela.
    escolhido = server_environment({"OLLAMA_NUM_PARALLEL": "4"})
    assert escolhido["OLLAMA_NUM_PARALLEL"] == "4"
    assert set(SERVER_ENVIRONMENT).issubset(ambiente)


def test_o_contexto_nunca_encolhe_e_respeita_o_limite_do_modelo():
    """O `num_ctx` padrão do Ollama (4096) trunca uma janela cheia em
    silêncio — o modelo classificaria um trecho cujo fim nunca recebeu."""
    from gclaude_indexer.engine_local import context_tokens_for

    assert context_tokens_for("curto") == 4096
    grande = context_tokens_for("x" * 120_000)
    assert grande > 4096
    assert context_tokens_for("x" * 120_000, model_limit=8192) == 8192


def test_o_modo_cpu_nao_e_sobreposto_pela_medicao():
    """Escolher "cpu" é uma decisão do usuário; nenhuma medição a desfaz."""
    from gclaude_indexer.engine_local import LocalEngine

    motor = LocalEngine(model="qualquer", num_gpu=0)
    assert motor.plan_gpu_use("prompt") is None
    assert motor.num_gpu == 0


# --- 5. sem precisar reiniciar ---------------------------------------------


def test_o_caminho_gravado_pelo_instalador_vem_antes_do_path(pasta_local, monkeypatch, tmp_path):
    """A correção do item 5.

    O `install.ps1` escreve o PATH no registro e transmite WM_SETTINGCHANGE,
    mas o Explorer costuma ignorar — e todo processo que ele já tinha
    iniciado segue com o ambiente de antes da instalação. Por isso o
    caminho absoluto gravado na hora da instalação é consultado primeiro.
    """
    from gclaude_indexer import tools

    falso = tmp_path / "tesseract.exe"
    falso.write_text("", encoding="utf-8")
    tools.record_tool("tesseract", str(falso))

    monkeypatch.setattr(tools.shutil, "which", lambda _nome: "C:/do/PATH/antigo.exe")
    assert tools.find("tesseract") == str(falso)


def test_um_registro_apontando_para_arquivo_sumido_cai_para_o_path(pasta_local, monkeypatch):
    from gclaude_indexer import tools

    tools.record_tool("tesseract", str(pasta_local / "nao_existe.exe"))
    monkeypatch.setattr(tools.shutil, "which", lambda _nome: "C:/valido/tesseract.exe")
    assert tools.find("tesseract") == "C:/valido/tesseract.exe"


def test_o_path_das_ferramentas_e_acrescentado_sem_duplicar(pasta_local, monkeypatch, tmp_path):
    from gclaude_indexer import tools

    pasta_bin = tmp_path / "bin"
    pasta_bin.mkdir()
    (pasta_bin / "tesseract.exe").write_text("", encoding="utf-8")
    tools.record_tool("tesseract", str(pasta_bin / "tesseract.exe"))
    monkeypatch.setattr(tools, "find", lambda nome: str(pasta_bin / "tesseract.exe") if nome == "tesseract" else None)

    resultado = tools.path_with_tools("C:/ja/existente")
    assert str(pasta_bin) in resultado
    # Idempotente: um PATH que já tem a pasta não a ganha duas vezes.
    assert tools.path_with_tools(resultado).count(str(pasta_bin)) == 1


def test_o_indexer_bat_recarrega_o_path_do_registro():
    """A segunda correção independente do item 5, do lado do .bat."""
    texto = (Path(__file__).resolve().parent.parent / "Indexer.bat").read_text(encoding="utf-8", errors="replace")
    assert "GetEnvironmentVariable('Path','Machine')" in texto
    assert "GetEnvironmentVariable('Path','User')" in texto


# --- 6. a tela de log ------------------------------------------------------


def test_o_log_e_cronologico_do_mais_antigo_para_o_mais_novo(tmp_path):
    """A rolagem ia para o fim enquanto o mais recente ficava no topo: as
    duas metades discordavam e seguir a execução arrastava o usuário para a
    linha mais antiga a cada dois segundos."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events, record_event

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for indice in range(3):
        record_event(conn, "scan", "info", f"linha {indice}")

    eventos = list_events(conn)
    assert [evento["message"] for evento in eventos] == ["linha 0", "linha 1", "linha 2"]
    assert eventos[0]["id"] < eventos[-1]["id"]
    conn.close()


def test_o_fragmento_incremental_traz_so_as_linhas_novas():
    """`?since=<id>` devolve `<li>` soltos para acrescentar.

    Reconstruir o painel inteiro a cada dois segundos era o que apagava a
    seleção do usuário (impossível "copiar alguma linha do log") e jogava a
    rolagem embaixo dele.
    """
    modelos = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "templates"
    itens = (modelos / "_log_items.html").read_text(encoding="utf-8")
    lista = (modelos / "_log.html").read_text(encoding="utf-8")

    assert 'data-event-id="{{ evento.id }}"' in itens
    assert "<ul" not in itens  # só os <li>, para o append
    assert '_log_items.html' in lista
    assert 'id="log-list"' in lista


def test_so_um_container_do_log_rola():
    """A causa direta de "não consigo rolar": `.log` e `.log-box` tinham
    ambos `overflow-y: auto`, e o script controlava o de fora enquanto o de
    dentro era o que realmente rolava."""
    css = (
        Path(__file__).resolve().parent.parent
        / "gclaude_indexer" / "web" / "static" / "style.css"
    ).read_text(encoding="utf-8")

    regra_lista = [linha for linha in css.splitlines() if linha.startswith(".log {")]
    assert len(regra_lista) == 1
    assert "overflow-y" not in regra_lista[0]
    assert "max-height" not in regra_lista[0]

    assert "resize: vertical;" in css
    assert "user-select: text;" in css


def test_a_tela_de_execucao_nao_troca_o_log_inteiro_pelo_htmx():
    html = (
        Path(__file__).resolve().parent.parent
        / "gclaude_indexer" / "web" / "templates" / "run.html"
    ).read_text(encoding="utf-8")

    bloco_log = html[html.index('<div id="log"'):html.index('<div id="log"') + 400]
    assert "hx-get" not in bloco_log
    assert "data-log-url" in bloco_log
    assert 'id="log-copy"' in html


# --- 7. a previsão de conclusão --------------------------------------------


def test_a_previsao_segue_o_ritmo_recente_e_nao_a_media_de_tudo():
    """O ponto do item 7.

    Uma média sobre toda a execução inclui o arranque (criar o pool, o
    Ollama carregando o modelo na VRAM) e demora tanto quanto a própria
    execução para perceber que o ritmo mudou. Aqui a coleção começa devagar
    e acelera: a previsão tem que cair.
    """
    from gclaude_indexer.web.eta import ProgressEstimator

    estimador = ProgressEstimator(started_at=0.0)
    estimador.observe(0, 1000, now=0.0)
    for instante, feito in ((10.0, 20), (20.0, 40), (30.0, 60)):
        lento = estimador.observe(feito, 1000, now=instante)
    assert lento is not None

    for instante, feito in ((32.0, 120), (34.0, 180), (36.0, 240), (38.0, 300)):
        rapido = estimador.observe(feito, 1000, now=instante)
    assert rapido is not None
    assert rapido < lento


def test_a_previsao_sobe_quando_o_trabalho_fica_mais_lento():
    """"aumentando ou diminuindo a previsão quando necessário" — os dois
    sentidos, não só o de encolher."""
    from gclaude_indexer.web.eta import ProgressEstimator

    estimador = ProgressEstimator(started_at=0.0)
    estimador.observe(0, 10_000, now=0.0)
    for instante in range(2, 22, 2):
        rapido = estimador.observe(instante * 100, 10_000, now=float(instante))

    # A partir daqui, um arquivo grande: quase nada anda por meio minuto.
    for instante in range(22, 60, 2):
        lento = estimador.observe(2000 + (instante - 20) * 2, 10_000, now=float(instante))
    assert lento > rapido


def test_sem_amostras_suficientes_nao_ha_previsao():
    """Uma previsão ausente é honesta; uma confiante e errada, não."""
    from gclaude_indexer.web.eta import ProgressEstimator

    estimador = ProgressEstimator(started_at=0.0)
    assert estimador.observe(0, 100, now=0.0) is None
    assert estimador.observe(1, 100, now=1.0) is None  # menos de MIN_ELAPSED_S


def test_uma_etapa_travada_perde_a_previsao_em_vez_de_mentir():
    from gclaude_indexer.web.eta import STALL_TIMEOUT_S, ProgressEstimator

    estimador = ProgressEstimator(started_at=0.0)
    estimador.observe(0, 1000, now=0.0)
    for instante in (10.0, 20.0, 30.0):
        assert estimador.observe(instante * 2, 1000, now=instante) is not None

    parado = 30.0 + STALL_TIMEOUT_S + 1
    assert estimador.observe(60, 1000, now=parado) is None


def test_a_conversao_e_medida_em_bytes_e_nao_em_arquivos(tmp_path):
    """Um PDF escaneado de 900 páginas e um bilhete de 3 KB contam como um
    arquivo cada; o custo real não é comparável."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.web.background_runs import _weight_done, _weight_pending

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome, tamanho, situacao in (
        ("grande.pdf", 900_000_000, "discovered"),
        ("bilhete.txt", 3_000, "converted"),
    ):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, status) "
            "VALUES (?, ?, ?, ?, '', ?)",
            (nome, nome, nome.split(".")[-1], tamanho, situacao),
        )
    conn.commit()

    assert _weight_pending(conn, "conversion") == 900_000_000
    assert _weight_done(conn, "conversion") == 3_000
    # Janelas têm tamanho fixo por construção: contá-las já é a unidade certa.
    assert _weight_pending(conn, "classification") is None
    conn.close()


# --- 8. projetos vistos em qualquer computador -----------------------------


def test_sem_pasta_configurada_o_catalogo_continua_local(pasta_local):
    from gclaude_indexer import catalog

    assert catalog.catalog_folder() is None
    assert catalog.catalog_path() == pasta_local / "projects.json"


def test_o_projeto_registrado_guarda_o_caminho_relativo_ao_catalogo(pasta_local, tmp_path):
    """A letra da unidade muda entre máquinas (seção 11.5): `H:` aqui, `G:`
    lá. Só o caminho relativo à própria pasta do catálogo é igual nas duas."""
    from gclaude_indexer import catalog, settings

    drive = tmp_path / "Drive"
    pasta_catalogo = drive / "GClaude" / "catalogo"
    pasta_projeto = drive / "Saidas" / "Processo X"
    pasta_catalogo.mkdir(parents=True)
    pasta_projeto.mkdir(parents=True)

    settings.set_shared_catalog_folder(str(pasta_catalogo))
    entrada = catalog.register_project("Processo X", str(pasta_projeto))

    assert entrada.relative_output_folder
    assert ".." in entrada.relative_output_folder  # irmão, não filho
    assert (pasta_catalogo / "projects.json").is_file()


def test_o_mesmo_catalogo_abre_com_outra_letra_de_unidade(pasta_local, tmp_path):
    """O item 8 inteiro, num teste: o catálogo é gravado com o Drive numa
    letra e lido com ele em outra."""
    from gclaude_indexer import catalog, settings

    primeiro = tmp_path / "H"
    (primeiro / "GClaude" / "catalogo").mkdir(parents=True)
    (primeiro / "Saidas" / "Processo X").mkdir(parents=True)

    settings.set_shared_catalog_folder(str(primeiro / "GClaude" / "catalogo"))
    catalog.register_project("Processo X", str(primeiro / "Saidas" / "Processo X"))

    # A mesma árvore, montada em outro lugar — o outro computador.
    segundo = tmp_path / "G"
    segundo.mkdir()
    import shutil as _shutil

    _shutil.copytree(primeiro, segundo, dirs_exist_ok=True)
    settings.set_shared_catalog_folder(str(segundo / "GClaude" / "catalogo"))

    encontrado = catalog.find_project(1)
    assert encontrado is not None
    assert Path(encontrado.output_folder) == (segundo / "Saidas" / "Processo X").resolve()


def test_um_projeto_de_outro_computador_e_listado_como_indisponivel(pasta_local, tmp_path):
    from gclaude_indexer import catalog, settings

    pasta_catalogo = tmp_path / "catalogo"
    pasta_catalogo.mkdir()
    settings.set_shared_catalog_folder(str(pasta_catalogo))

    (pasta_catalogo / "projects.json").write_text(
        json.dumps([{
            "id": 1, "name": "De outra máquina",
            "output_folder": "Z:\\so\\existe\\la",
            "created_at": "2026-01-01T00:00:00",
            "relative_output_folder": "",
        }]),
        encoding="utf-8",
    )

    entradas = catalog.list_projects()
    assert len(entradas) == 1
    # Listado, não escondido nem apresentado como quebrado.
    assert entradas[0].is_available(catalog.catalog_folder()) is False


def test_o_catalogo_compartilhado_adota_os_projetos_ja_existentes(pasta_local, tmp_path):
    """Configurar a pasta e o outro computador continuar vendo a tela vazia
    seria idêntico ao defeito que isto corrige."""
    from gclaude_indexer import catalog, settings

    projeto = tmp_path / "Saidas" / "Antigo"
    projeto.mkdir(parents=True)
    catalog.register_project("Antigo", str(projeto))  # ainda no catálogo local

    pasta_catalogo = tmp_path / "catalogo"
    pasta_catalogo.mkdir()
    settings.set_shared_catalog_folder(str(pasta_catalogo))
    assert catalog.adopt_local_projects() == 1

    compartilhado = json.loads((pasta_catalogo / "projects.json").read_text(encoding="utf-8"))
    assert [entrada["name"] for entrada in compartilhado] == ["Antigo"]


def test_um_catalogo_estragado_nao_derruba_a_tela(pasta_local, tmp_path):
    """Um arquivo em pasta sincronizada é escrito por outras máquinas e
    outras versões: nada ali pode virar exceção."""
    from gclaude_indexer import catalog, settings

    pasta_catalogo = tmp_path / "catalogo"
    pasta_catalogo.mkdir()
    settings.set_shared_catalog_folder(str(pasta_catalogo))

    (pasta_catalogo / "projects.json").write_text("{isso não é json", encoding="utf-8")
    assert catalog.list_projects() == []

    (pasta_catalogo / "projects.json").write_text(
        json.dumps([
            {"id": 1, "name": "ok", "output_folder": "C:\\x", "created_at": "2026-01-01", "campo_futuro": 7},
            {"nada": "a ver"},
        ]),
        encoding="utf-8",
    )
    entradas = catalog.list_projects()
    assert len(entradas) == 1
    assert entradas[0].name == "ok"


def test_ids_repetidos_de_duas_maquinas_nao_escondem_um_projeto(pasta_local, tmp_path):
    from gclaude_indexer import catalog, settings

    pasta_catalogo = tmp_path / "catalogo"
    pasta_catalogo.mkdir()
    settings.set_shared_catalog_folder(str(pasta_catalogo))

    (pasta_catalogo / "projects.json").write_text(
        json.dumps([
            {"id": 1, "name": "A", "output_folder": "C:\\a", "created_at": "2026-01-01"},
            {"id": 1, "name": "B", "output_folder": "C:\\b", "created_at": "2026-01-02"},
        ]),
        encoding="utf-8",
    )

    entradas = catalog.list_projects()
    assert len({entrada.id for entrada in entradas}) == 2
    assert catalog.find_project(entradas[1].id).name == "B"


# --- 4. o desinstalador ----------------------------------------------------


def test_existe_um_desinstalador_e_ele_nunca_apaga_projetos():
    caminho = Path(__file__).resolve().parent.parent / "uninstall.ps1"
    assert caminho.is_file()
    texto = caminho.read_text(encoding="utf-8-sig")

    # Interativo item a item, com as saídas não interativas que o instalador
    # e um administrador precisam.
    for parametro in ("$RemoveAll", "$KeepDependencies", "$WhatIfOnly"):
        assert parametro in texto

    # Toda dependência compartilhada é oferecida separadamente.
    for programa in ("Tesseract", "Ghostscript", "Ollama", "Python"):
        assert programa in texto

    # E as pastas dos projetos são listadas, jamais removidas.
    assert "Get-KnownProjectFolders" in texto
    assert "NEVER removed" in texto


def test_o_instalador_grava_onde_as_ferramentas_ficaram():
    """A metade da correção do item 5 que fica do lado do instalador."""
    texto = (Path(__file__).resolve().parent.parent / "install.ps1").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    assert "tools.json" in texto
    assert "OLLAMA_NUM_PARALLEL" in texto
    # O desinstalador NÃO ganha atalho na área de trabalho (decisão
    # explícita do usuário): a área de trabalho é para o que se abre todo
    # dia, e um desinstalador é o oposto disso — um botão que ninguém quer
    # apertar, ao lado do que se aperta sempre, com o mesmo ícone. Ele fica
    # no `Desinstalar.bat`, na pasta do projeto.
    assert "GClaude Indexer (uninstall).lnk" not in texto
    assert "Desinstalar.bat" in texto


# --- 9. abrir um projeto existente (pergunta do usuário, fase 16) ----------
#
# O catálogo compartilhado resolve "mesmo Drive, outro computador". Não
# resolve desinstalar tudo, formatar, trocar de conta, mover a pasta ou
# receber a pasta de outra pessoa. Nesses casos o projeto está inteiro — o
# `project.db` na pasta de saída tem a configuração, os arquivos lidos, as
# páginas e as peças — e o que faltava era um jeito de dizer "abra aquele".


def _projeto_de_exemplo(raiz: Path, **extras):
    """Cria um projeto com dados e devolve a pasta de saída."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.project import create_project

    origem = raiz / "origem"
    origem.mkdir(parents=True, exist_ok=True)
    (origem / "a.txt").write_text("x", encoding="utf-8")
    saida = raiz / "saida"

    parametros = dict(
        name="Processo Real", subject="assunto original",
        source_folder=str(origem), output_folder=str(saida), pages_per_window=8,
    )
    parametros.update(extras)
    conn, _ = create_project(ProjectConfig(**parametros))
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status) "
        "VALUES ('a.txt','a.txt','txt',1,'h','extracted')"
    )
    conn.commit()
    conn.close()
    return saida


def test_a_pasta_de_saida_ja_identifica_o_projeto(tmp_path):
    """A resposta à pergunta: não é preciso um identificador novo. O
    `project.db` da pasta de saída já é o projeto."""
    from gclaude_indexer.project import describe_project

    saida = _projeto_de_exemplo(tmp_path)
    resumo = describe_project(saida)

    assert resumo is not None
    assert resumo.name == "Processo Real"
    assert resumo.subject == "assunto original"
    assert resumo.files == 1
    assert resumo.config_rows == 1


def test_inspecionar_uma_pasta_nao_cria_nada_nela(tmp_path):
    """`describe_project` abre o banco em modo somente leitura.

    É chamada para responder "já existe projeto aqui?", inclusive pelo
    formulário de Novo projeto — uma checagem que respondesse criando um
    banco vazio na pasta perguntada seria pior do que não checar.
    """
    from gclaude_indexer.project import describe_project

    vazia = tmp_path / "vazia"
    vazia.mkdir()
    assert describe_project(vazia) is None
    assert list(vazia.iterdir()) == []

    # Pasta inexistente e arquivo que não é banco: nenhum levanta exceção,
    # e nenhum vira "projeto".
    assert describe_project(tmp_path / "nao_existe") is None
    quebrada = tmp_path / "quebrada"
    quebrada.mkdir()
    (quebrada / "project.db").write_text("isto nao e um banco", encoding="utf-8")
    assert describe_project(quebrada) is None


def test_abrir_reaproveita_o_projeto_sem_recriar(tmp_path, pasta_local):
    from fastapi.testclient import TestClient

    from gclaude_indexer.project import load_project
    from gclaude_indexer.web.app import app

    saida = _projeto_de_exemplo(tmp_path)
    cliente = TestClient(app)

    inspecao = cliente.post("/projects/open", data={"existing_output_folder": str(saida)})
    assert inspecao.status_code == 200
    assert "Processo Real" in inspecao.text

    aberto = cliente.post(
        "/projects/open",
        data={"existing_output_folder": str(saida), "confirm": "1"},
        follow_redirects=False,
    )
    assert aberto.status_code == 303
    assert "/run" in aberto.headers["location"]

    # Nada recriado, nada sobrescrito.
    config, conn = load_project(saida)
    try:
        assert config.subject == "assunto original"
        assert config.pages_per_window == 8
        assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM file").fetchone()[0] == 1
    finally:
        conn.close()


def test_abrir_uma_pasta_sem_projeto_explica_o_erro(tmp_path, pasta_local):
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app

    vazia = tmp_path / "sem_projeto"
    vazia.mkdir()
    resposta = TestClient(app).post("/projects/open", data={"existing_output_folder": str(vazia)})

    assert resposta.status_code == 400
    # O engano provável é apontar a pasta de origem; a mensagem diz isso.
    assert "project.db" in resposta.text


def test_novo_projeto_numa_pasta_ocupada_avisa_em_vez_de_sobrescrever(tmp_path, pasta_local):
    """O caminho que antes corrompia a configuração em silêncio.

    Criar ali dentro inseria uma segunda linha em `project`, e passava a
    valer a configuração do formulário — inclusive `pages_per_window`, que
    mudaria o sentido das janelas já montadas.
    """
    from fastapi.testclient import TestClient

    from gclaude_indexer.project import load_project
    from gclaude_indexer.web.app import app

    saida = _projeto_de_exemplo(tmp_path)
    resposta = TestClient(app).post("/projects/new", data={
        "name": "tentativa", "subject": "", "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida), "extensions": ["pdf"], "pages_per_block": "80",
        "pages_per_window": "16", "overlap": "2", "chars_per_page": "2000",
        "collection_type": "processo", "group_mode": "subfolder", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "automatic",
        "processing_mode": "automatic", "parallelism": "automatic",
    })

    assert resposta.status_code == 409
    assert "Processo Real" in resposta.text

    config, conn = load_project(saida)
    try:
        assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
        assert config.subject == "assunto original"
        assert config.pages_per_window == 8
    finally:
        conn.close()


def test_um_banco_ja_afetado_volta_a_usar_a_configuracao_original(tmp_path):
    """O reparo, para quem já passou pelo defeito.

    A leitura era `ORDER BY id DESC` — a última linha, ou seja, a do
    formulário sobreposto. Passa a ser a primeira, a original. As linhas
    extras não são apagadas: são o único registro do que aconteceu, e um
    reparo que destrói a evidência para arrumar a aparência não é reparo.
    """
    from gclaude_indexer.config import config_to_json, load_config
    from gclaude_indexer.db import connect
    from gclaude_indexer.project import describe_project, load_project

    saida = _projeto_de_exemplo(tmp_path)

    # Reproduz o estado que o defeito deixava: uma segunda configuração.
    conn = connect(saida / "project.db")
    sobreposta = load_config({
        "name": "tentativa", "subject": "", "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida), "pages_per_window": 16,
    })
    conn.execute(
        "INSERT INTO project (name, subject, source_folder, output_folder, config_json, created_at) "
        "VALUES (?, '', ?, ?, ?, '2026-09-01T00:00:00')",
        ("tentativa", str(tmp_path / "origem"), str(saida), config_to_json(sobreposta)),
    )
    conn.commit()
    conn.close()

    config, conn = load_project(saida)
    try:
        assert config.subject == "assunto original"
        assert config.pages_per_window == 8
        # Nada apagado.
        assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 2
        avisos = conn.execute(
            "SELECT COUNT(*) FROM event WHERE message_key = 'log.project.duplicate_config'"
        ).fetchone()[0]
        assert avisos == 1
    finally:
        conn.close()

    # E o aviso não se repete a cada abertura: `load_project` roda em toda
    # requisição — quatro vezes a cada dois segundos na tela de Execução.
    for _ in range(3):
        _config, conn = load_project(saida)
        conn.close()
    _config, conn = load_project(saida)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM event WHERE message_key = 'log.project.duplicate_config'"
        ).fetchone()[0] == 1
    finally:
        conn.close()

    assert describe_project(saida).config_rows == 2


def test_a_tela_de_projetos_oferece_abrir_um_projeto_existente(pasta_local):
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app

    resposta = TestClient(app).get("/projects")
    assert resposta.status_code == 200
    assert "/projects/open" in resposta.text


def test_existe_um_lancador_bat_para_o_desinstalador():
    """A política de execução, e por que um .bat resolve.

    O Google Drive marca todo arquivo que sincroniza com
    `Zone.Identifier`/`ZoneId=3` — "veio da internet". A política padrão do
    Windows (RemoteSigned) então recusa rodar um .ps1 dessa zona sem
    assinatura digital, com uma mensagem que parece dizer que o script está
    quebrado. Todo lançador deste projeto já passa `-ExecutionPolicy
    Bypass`; o desinstalador era o único sem lançador, e apareceu na
    primeira vez que alguém o rodou do jeito óbvio, direto do PowerShell.
    """
    raiz = Path(__file__).resolve().parent.parent
    bat = raiz / "Desinstalar.bat"
    assert bat.is_file()

    texto = bat.read_text(encoding="utf-8", errors="replace")
    assert "-ExecutionPolicy Bypass" in texto
    assert "uninstall.ps1" in texto
    # As opções documentadas no README continuam valendo pelo .bat.
    assert "%*" in texto


def test_o_instalador_desbloqueia_os_scripts_da_pasta():
    """Conserta a cópia que está na máquina agora, que é a que o usuário
    vai rodar. Não substitui os lançadores: o Drive pode remarcar o arquivo
    na próxima sincronização."""
    texto = (Path(__file__).resolve().parent.parent / "install.ps1").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    assert "Unblock-File" in texto
    assert "Zone.Identifier" in texto
    # E o atalho aponta para o .bat, que dispensa o desbloqueio.
    assert "Desinstalar.bat" in texto


def test_o_desinstalador_nunca_remove_a_pasta_do_codigo():
    """A garantia mais importante do desinstalador, verificada no texto.

    Auditado também em execução: rodando `uninstall.ps1 -RemoveAll` com toda
    operação destrutiva interceptada, os 12 alvos de remoção ficam em
    `%LOCALAPPDATA%\GClaudeIndexer`, na área de trabalho e em
    `%USERPROFILE%\.ollama\models` — nenhum na pasta do código. Este teste
    é o que impede uma edição futura de introduzir um.
    """
    linhas = (
        Path(__file__).resolve().parent.parent / "uninstall.ps1"
    ).read_text(encoding="utf-8-sig").splitlines()

    remocoes = [
        linha for linha in linhas
        if ("Remove-Item" in linha or "Remove-ItemSafely -Path" in linha)
        and not linha.strip().startswith("#")
        and "function Remove-ItemSafely" not in linha
    ]
    assert remocoes, "nenhuma linha de remoção encontrada — o teste perdeu o alvo"
    for linha in remocoes:
        assert "$ProjectRoot" not in linha, linha

    # E `$ProjectRoot` só aparece na definição e nas duas mensagens de tela.
    usos = [linha.strip() for linha in linhas if "$ProjectRoot" in linha]
    assert len(usos) == 3, usos
    assert usos[0].startswith("$ProjectRoot =")
    assert all("Write-Host" in uso for uso in usos[1:])


def test_o_catalogo_compartilhado_no_drive_sobrevive_a_desinstalacao():
    """Só o catálogo local é apagado. O do Drive é o que devolve os
    projetos depois de uma reinstalação — apagá-lo faria a desinstalação
    numa máquina esvaziar a lista de todas as outras."""
    linhas = (
        Path(__file__).resolve().parent.parent / "uninstall.ps1"
    ).read_text(encoding="utf-8-sig").splitlines()

    # Todo caminho da lista de estado local é montado sobre $LocalFolder.
    montagem = [linha for linha in linhas if "$path = Join-Path" in linha]
    assert montagem, "a montagem do caminho do estado local sumiu"
    for linha in montagem:
        assert "$LocalFolder" in linha, linha


def test_a_vram_do_modelo_ja_carregado_conta_como_disponivel():
    """Outro defeito achado medindo, não lendo.

    Com o modelo residente, a VRAM *livre* da placa exclui justamente o
    modelo que estamos dimensionando. Orçar por esse número pede menos
    camadas do que cabem, o Ollama recarrega menor, sobra menos livre, e a
    próxima execução pede menos ainda — uma catraca que empurraria para
    fora da GPU um modelo que cabia. Medido: 5,0 GB livres com nada
    carregado; 1,6 GB com o `gemma4:e4b` residente.
    """
    from gclaude_indexer import gpu_budget

    original = gpu_budget._get_json
    try:
        gpu_budget._get_json = lambda url, payload=None, timeout=5.0: (
            {"models": [{"name": "gemma4:e4b", "size_vram": 3108 * gpu_budget.MB}]}
            if url.endswith("/api/ps") else None
        )
        assert gpu_budget.loaded_model_vram_mb("gemma4:e4b", "http://x") == 3108
        # Casa pelo nome sem a tag também, e devolve 0 para outro modelo.
        assert gpu_budget.loaded_model_vram_mb("gemma4", "http://x") == 3108
        assert gpu_budget.loaded_model_vram_mb("outro:7b", "http://x") == 0
    finally:
        gpu_budget._get_json = original


# --- 10. qualidade da classificação (revisão do score 60/100) --------------
#
# Origem: um acervo real de material de pós-graduação pontuou 60/100 com
# 99,3% das peças em confiança alta. A investigação mostrou que a nota não
# media a classificação — media um campo em branco.


def test_o_prompt_recebe_o_que_o_usuario_escreveu_no_formulario():
    """O defeito de maior impacto encontrado na revisão.

    `subject`, `collection_type`, `role_instructions` e `extra_rules` eram
    coletados no formulário, gravados, e usados **apenas** para escrever o
    `instrucoes-do-projeto.md` — um artefato produzido depois da
    classificação. Nenhum motor mostrava esses campos ao modelo. Resultado
    medido: 1432 de 1445 peças sem tipo, porque os únicos exemplos do
    prompt eram "OFÍCIO, MEMORANDO, PARECER" e os documentos eram apostilas
    de curso.
    """
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.engine_local import build_context

    config = ProjectConfig(
        name="x", source_folder=".", output_folder=".",
        subject="Material de pós-graduação em Direito do Consumidor.",
        collection_type="biblioteca",
        role_instructions="Você é um bibliotecário jurídico.",
        extra_rules="Observar a legislação vigente e a jurisprudência.",
    )
    contexto = build_context(config)

    assert "Direito do Consumidor" in contexto
    assert "bibliotecário jurídico" in contexto
    assert "legislação vigente" in contexto
    assert "biblioteca" in contexto

    # E entra como CONTEXTO, nunca como tarefa: o `extra_rules` daquele
    # acervo mandava "observar a legislação", que é instrução para o uso
    # posterior do índice, não algo que o classificador deva executar.
    assert "NÃO é a sua tarefa" in contexto

    # Sem nada preenchido, o prompt fica exatamente como era antes.
    vazio = ProjectConfig(name="x", source_folder=".", output_folder=".", collection_type="")
    assert build_context(vazio) == ""
    assert build_context(None) == ""


def test_o_contexto_nao_engole_a_janela():
    """Os campos livres dividem a janela de contexto com as páginas: uma
    instrução muito longa empurraria para fora o documento que ela deveria
    ajudar a ler."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.engine_local import _CONTEXT_FIELD_LIMIT, build_context

    config = ProjectConfig(
        name="x", source_folder=".", output_folder=".", subject="palavra " * 5000,
    )
    contexto = build_context(config)
    assert len(contexto) < _CONTEXT_FIELD_LIMIT + 500
    # O assunto é cortado com reticências; o bloco segue com as outras
    # linhas, então o "…" fica no meio do texto, não no fim dele.
    linha_do_assunto = next(l for l in contexto.splitlines() if l.startswith("- Assunto"))
    assert linha_do_assunto.endswith("…")
    assert len(linha_do_assunto) < _CONTEXT_FIELD_LIMIT + 50


def test_o_prompt_pede_uma_peca_por_unidade_de_assunto():
    """Fragmentação medida no acervo didático: 1,28 página por peça.

    A primeira redação desta regra dizia "UMA PEÇA POR DOCUMENTO" e curou
    a fragmentação criando o extremo oposto — no benchmark do laudo, cinco
    modelos colapsaram 31 páginas em até 3 peças. A regra atual nomeia os
    dois erros; a cobertura é garantida à parte, pelo código.
    """
    from gclaude_indexer.engine_local import _PROMPT

    assert "UNIDADE DE ASSUNTO" in _PROMPT
    assert "fatiar um assunto contínuo" in _PROMPT


def test_o_tipo_e_normalizado_para_nao_duplicar_no_indice():
    from gclaude_indexer.classification import normalize_type

    # O acervo real trouxe as duas grafias, contadas como tipos diferentes.
    assert normalize_type("ÍNDICE") == normalize_type("Índice") == "ÍNDICE"
    assert normalize_type("  projeto  pedagógico ") == "PROJETO PEDAGÓGICO"
    # "null" como texto é ausência de tipo, não um tipo chamado NULL.
    for vazio in ("null", "N/A", "desconhecido", "", "   ", None, 123):
        assert normalize_type(vazio) is None


def test_arquivos_do_sistema_nao_viram_pecas():
    """Com as extensões em "todas", um `desktop.ini` virou a peça número 1
    de um índice de material didático, resumido como "arquivo de
    configuração do sistema operacional"."""
    from pathlib import Path as _Path

    from gclaude_indexer.scanning import is_system_file

    for lixo in ("desktop.ini", "Thumbs.db", ".DS_Store", "~$rascunho.docx", ".~lock.a.odt#"):
        assert is_system_file(_Path(lixo)), lixo

    # E nada além disso: uma lista explícita, não uma regra como "arquivo
    # oculto" — um acervo pode legitimamente ter um documento cujo nome
    # começa com ponto, e recusá-lo seria perder material do usuário.
    for documento in ("Contrato.pdf", ".gitignore-do-acervo.txt", "Icon", "relatorio.docx"):
        assert not is_system_file(_Path(documento)), documento


def test_a_data_so_conta_quando_o_acervo_tem_datas():
    """A métrica exigia data em toda peça. Apostila de curso não tem data
    por documento, então vazio era a resposta CERTA — e a fórmula cobrava
    15 dos 30 pontos de preenchimento por isso, punindo o motor por
    acertar e deixando 100 inalcançável."""
    from gclaude_indexer.quality import _fill_rate

    # Acervo sem datas, tipo todo preenchido: preenchimento cheio.
    assert _fill_rate(1445, 0, 1445) == (1.0, False)
    # Acervo com datas: a data volta a contar, como sempre contou.
    assert _fill_rate(1445, 0, 0) == (1.0, True)
    taxa, contou = _fill_rate(1445, 0, 722)
    assert contou and 0.7 < taxa < 0.8
    # E o tipo continua contando nos dois casos.
    taxa_sem_tipo, _ = _fill_rate(1000, 1000, 1000)
    assert taxa_sem_tipo == 0.0


def test_uma_data_solitaria_nao_muda_a_regra_do_acervo_inteiro():
    """5% e não 0: um punhado de datas entre milhares ainda é um acervo sem
    datas, e uma data que o modelo inventou não pode passar a cobrar o
    campo do acervo todo."""
    from gclaude_indexer.quality import _fill_rate

    _taxa, contou = _fill_rate(1000, 0, 999)  # 1 peça datada em 1000
    assert contou is False
    _taxa, contou = _fill_rate(1000, 0, 900)  # 10% datadas
    assert contou is True


def test_o_score_vem_decomposto_para_a_tela_poder_explicar(tmp_path):
    """Um número que o usuário não consegue abrir é um número sobre o qual
    ele não consegue agir: descobrir que um campo vazio respondia por 30
    dos 40 pontos que faltavam exigiu consultar o banco."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.quality import quality_summary

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for indice in range(10):
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
            "type, date, engine, confidence, files) "
            "VALUES ('g', 'f. 1', 'f. 2', 1, 2, 'OFÍCIO', NULL, 'local', 'high', 'a.pdf')"
        )
    conn.commit()

    resumo = quality_summary(conn, ProjectConfig(name="x", source_folder=".", output_folder="."))
    conn.close()

    assert resumo["confidence_points"] + resumo["fill_points"] + resumo["penalty_points"] == pytest.approx(
        resumo["score"], abs=1.0
    )
    assert resumo["date_counted"] is False  # nenhuma peça datada
    # 25, não 30: a cobertura passou a valer 40 dos 100 pontos, e o
    # preenchimento cedeu espaço para ela.
    assert resumo["fill_points"] == pytest.approx(25.0, abs=0.1)  # tipo 100% preenchido


def test_a_referencia_com_o_nome_do_arquivo_junto_e_aceita():
    """Sem isto, o prompt corrigido produzia ZERO peças.

    Cada página é apresentada ao modelo como `--- f. 2 (Arquivo.pdf) ---`,
    e um modelo que copia o rótulo inteiro de volta — `"ref_start": "f. 2
    (Arquivo.pdf)"` — identificou a página certa e escreveu numa forma que
    a comparação por igualdade exata recusa. Medido: com o prompt novo, o
    `qwen3:8b` devolveu uma peça de f. 2 a f. 16 (o documento inteiro,
    exatamente como pedido) e ela foi descartada por isso, deixando a
    janela com zero peças e nenhum motivo visível.
    """
    from gclaude_indexer.engine_local import _normalize_reference as normaliza

    assert normaliza("f. 2 (Projeto Pedagógico do Curso.pdf)") == normaliza("f. 2")
    assert normaliza("p. 5 (a.pdf)") == normaliza("p. 5")
    # As tolerâncias que já existiam continuam valendo.
    assert normaliza("F. 2") == normaliza("fl. 2") == normaliza("f.2") == "f.2"
    # E prefixos diferentes continuam sendo referências diferentes.
    assert normaliza("f. 1") != normaliza("p. 1")
    # Texto que não começa por uma referência não vira uma por acidente.
    assert normaliza("documento sem referência") == "documentosemreferência"


# --- 11. cobertura: nenhuma página fica fora do índice ---------------------
#
# O índice existe para levar alguém ao PDF certo, na página certa. Uma
# página que não aparece em peça nenhuma é informação que ninguém mais
# encontra — e foi o que o benchmark de um laudo de 31 páginas revelou:
# `gemma4:e4b`, `qwen3:8b`, `qwen3.5:9b`, `qwen3.5:4b` e `granite4.2:8b`
# devolveram de 0 a 3 peças cobrindo 9,7% das páginas, todas com confiança
# "high". Cinco modelos, o mesmo buraco: o problema era o prompt, e a
# garantia tinha de estar no código.


def _pagina(numero: int, texto: str = "conteudo", arquivo: str = "a.pdf"):
    from gclaude_indexer.classification import WindowPage

    return WindowPage(
        reference=f"f. {numero}", file_name=arquivo, text=texto, has_table=False, image_count=0
    )


def _peca(inicio: int, fim: int):
    from gclaude_indexer.classification import ClassifiedItem

    return ClassifiedItem(
        start_ref=f"f. {inicio}", end_ref=f"f. {fim}", start_order=inicio, end_order=fim,
        type="EXAME", date=None, author=None, summary="resumo", has_table=False,
        has_image=False, engine="local", confidence="high", files=["a.pdf"],
    )


def test_as_paginas_que_o_modelo_ignorou_sao_detectadas():
    from gclaude_indexer.engine_local import _uncovered_pages

    paginas = [_pagina(n) for n in range(1, 9)]
    # O modelo devolveu só as duas primeiras — o caso real medido.
    faltando = _uncovered_pages(paginas, [_peca(1, 2)])
    assert [p.reference for p in faltando] == [f"f. {n}" for n in range(3, 9)]

    # Cobertura completa não gera nada.
    assert _uncovered_pages(paginas, [_peca(1, 8)]) == []


def test_paginas_ignoradas_entram_no_indice_como_pecas_de_cobertura():
    from gclaude_indexer.classification import normalize_type
    from gclaude_indexer.engine_local import _coverage_items

    faltando = [_pagina(n, texto=f"Hemograma pagina {n} " * 40) for n in (3, 4, 5)]
    pecas = _coverage_items(faltando)

    # Páginas consecutivas viram UMA peça, não uma linha por página.
    assert len(pecas) == 1
    assert (pecas[0].start_ref, pecas[0].end_ref) == ("f. 3", "f. 5")
    # E são honestas sobre o que são: não fingem uma classificação.
    assert pecas[0].confidence == "low"
    assert normalize_type(pecas[0].type) is None
    # Mas carregam o suficiente para a busca chegar na página.
    assert "Hemograma" in pecas[0].summary
    assert pecas[0].files == ["a.pdf"]


def test_blocos_separados_viram_pecas_separadas():
    from gclaude_indexer.engine_local import _coverage_items

    # Buracos em 3-4 e 7: dois blocos, não um intervalo de 3 a 7 que
    # incluiria a página 5-6 que o modelo já classificou.
    pecas = _coverage_items([_pagina(3), _pagina(4), _pagina(7)])
    assert [(p.start_ref, p.end_ref) for p in pecas] == [("f. 3", "f. 4"), ("f. 7", "f. 7")]


def test_o_resumo_de_cobertura_nao_copia_a_pagina_inteira():
    """O índice tem de caber no contexto de um projeto do Claude: uma peça
    de cobertura leva o começo da página, não a página."""
    from gclaude_indexer.engine_local import _FALLBACK_SUMMARY_CHARS, _coverage_items

    pecas = _coverage_items([_pagina(1, texto="palavra " * 5000)])
    assert len(pecas[0].summary) <= _FALLBACK_SUMMARY_CHARS + 1
    assert pecas[0].summary.endswith("…")


def test_o_prompt_exige_cobertura_total_e_granularidade_por_assunto():
    """As duas falhas opostas medidas no benchmark, ambas endereçadas.

    A primeira versão da regra ("UMA PEÇA POR DOCUMENTO") corrigiu a
    fragmentação do material didático e criou o extremo oposto: um laudo
    com dezenas de exames virou uma peça só.
    """
    from gclaude_indexer.engine_local import _PROMPT

    assert "COBERTURA TOTAL" in _PROMPT
    assert "UNIDADE DE ASSUNTO" in _PROMPT
    # E diz explicitamente que os DOIS extremos são errados.
    assert "Os dois extremos são" in _PROMPT
    # O resumo é o que o Claude vai ler para decidir abrir a página.
    assert "decidir se vale abrir" in _PROMPT


def test_a_cobertura_pesa_na_nota_de_qualidade(tmp_path):
    """Antes, um índice com 9,7% de cobertura pontuava perto de 100: a
    fórmula media confiança e preenchimento, e as peças que sobraram tinham
    os dois perfeitos."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.quality import quality_summary

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status) "
        "VALUES ('a.pdf','a.pdf','pdf',1,'h','extracted')"
    )
    for numero in range(1, 32):  # 31 páginas, como o laudo do benchmark
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
            "VALUES (1, ?, ?, 100, 0, 0, 'x')",
            (numero, f"f. {numero}"),
        )
    # Uma única peça perfeita cobrindo 3 das 31 páginas — o resultado real.
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, type, date, "
        "engine, confidence, files) "
        "VALUES ('g','f. 1','f. 3',1,3,'LAUDO','2026-08-13','local','high','a.pdf')"
    )
    conn.commit()

    resumo = quality_summary(conn, ProjectConfig(name="x", source_folder=".", output_folder="."))
    conn.close()

    assert resumo["pages_total"] == 31
    assert resumo["pages_covered"] == 3
    assert resumo["coverage_pct"] == pytest.approx(9.7, abs=0.1)
    # Confiança e preenchimento perfeitos, cobertura péssima: a nota tem de
    # refletir o buraco, não a perfeição das poucas peças que existem.
    assert resumo["confidence_points"] == pytest.approx(35.0, abs=0.1)
    assert resumo["coverage_points"] < 4
    assert resumo["score"] < 70


# --- 12. o índice como ferramenta de busca --------------------------------
#
# O objetivo declarado pelo dono do sistema: o índice é lido para achar em
# QUAL PDF e em QUAL PÁGINA está uma informação, sem carregar os PDFs num
# projeto do Claude. Nada pode faltar, e o índice tem de ser compacto.
#
# O benchmark sobre um laudo de 31 páginas mostrou que pedir faixas ao
# modelo não entrega isso: cinco modelos de três famílias cobriram de 0% a
# 9,7% das páginas, todos com confiança "high".


def _pg(numero: int, texto: str = "conteudo da pagina", arquivo: str = "laudo.pdf"):
    from gclaude_indexer.classification import WindowPage

    return WindowPage(
        reference=f"p. {numero}", file_name=arquivo, text=texto, has_table=False, image_count=0
    )


def test_a_pagina_e_identificada_por_numero_e_nao_pela_referencia():
    """A correção de uma falha total, medida contra o modelo real.

    Pedir a referência de volta ("copiada exatamente como aparece") fez o
    `qwen3.5:4b` copiar o TEXTO INTEIRO da página para dentro do campo
    `ref`: o JSON estourou antes de fechar e o parser recebeu zero linhas —
    0% de tipo e uma peça por página. Um inteiro pequeno não tem como ser
    confundido com o conteúdo.
    """
    from gclaude_indexer.engine_local import _PAGE_PROMPT, _build_page_prompt

    prompt = _build_page_prompt([_pg(1), _pg(2)])
    assert "NUMERADAS de 1 a 2" in prompt
    assert "--- Página 1 (p. 1, laudo.pdf) ---" in prompt
    # O prompt diz explicitamente para não copiar o texto para dentro do
    # campo de identificação — foi o erro observado.
    assert "NUNCA copie o texto da" in _PAGE_PROMPT


def test_o_agrupamento_segue_o_assunto_e_nao_o_continues_do_modelo():
    """O caso exato medido: `qwen3.5:4b` nomeou impecavelmente os oito
    exames de uma janela e marcou `continues: true` em todos, porque
    entendeu "continua o mesmo laudo". Oito exames distintos têm de virar
    oito peças localizáveis, não uma."""
    from gclaude_indexer.engine_local import _group_pages_into_items

    assuntos = [
        "Hemograma completo", "VPM e Proteína C Reativa", "Ferritina",
        "Metabolismo do Ferro", "Vitamina B-12", "Tempo de Protrombina",
        "Ureia", "Creatinina e eGFR",
    ]
    paginas = [_pg(n) for n in range(1, 9)]
    linhas = [
        {"n": i + 1, "subject": a, "type": "EXAME", "detail": f"detalhe de {a}", "continues": i > 0}
        for i, a in enumerate(assuntos)
    ]

    pecas = _group_pages_into_items(paginas, linhas)
    assert len(pecas) == 8
    assert [p.start_ref for p in pecas] == [f"p. {n}" for n in range(1, 9)]


def test_a_continuacao_legitima_do_mesmo_documento_vira_uma_peca():
    """O outro lado: quando o assunto muda de redação sem mudar de
    documento, `continues` desempata e as páginas ficam juntas."""
    from gclaude_indexer.engine_local import _group_pages_into_items

    linhas = [
        {"n": 1, "subject": "Hemograma série vermelha", "type": "EXAME", "detail": "d", "continues": False},
        {"n": 2, "subject": "Hemograma série branca", "type": "EXAME", "detail": "d", "continues": True},
    ]
    pecas = _group_pages_into_items([_pg(1), _pg(2)], linhas)
    assert len(pecas) == 1
    assert (pecas[0].start_ref, pecas[0].end_ref) == ("p. 1", "p. 2")


def test_uma_pagina_que_o_modelo_ignorou_ainda_entra_no_indice():
    """A cobertura como propriedade, não como esperança: o agrupamento
    percorre as PÁGINAS da janela, não as linhas da resposta."""
    from gclaude_indexer.classification import normalize_type
    from gclaude_indexer.engine_local import _group_pages_into_items

    paginas = [_pg(n, texto=f"Exame numero {n} com resultados") for n in range(1, 5)]
    # O modelo respondeu sobre 1, 2 e 4 — pulou a 3.
    linhas = [
        {"n": 1, "subject": "Hemograma", "type": "EXAME", "detail": "serie vermelha", "continues": False},
        {"n": 2, "subject": "Ferritina", "type": "EXAME", "detail": "dosagem", "continues": False},
        {"n": 4, "subject": "Ureia", "type": "EXAME", "detail": "dosagem", "continues": False},
    ]
    pecas = _group_pages_into_items(paginas, linhas)

    cobertas = {n for p in pecas for n in range(p.start_order, p.end_order + 1)}
    assert cobertas == {1, 2, 3, 4}

    # A página 3 entra com o texto dela, sem fingir uma classificação.
    terceira = next(p for p in pecas if p.start_order == 3)
    assert normalize_type(terceira.type) is None
    assert "Exame numero 3" in terceira.summary


def test_o_resumo_de_cada_peca_tem_teto():
    """O índice inteiro precisa caber no contexto de um projeto do Claude."""
    from gclaude_indexer.engine_local import _SUMMARY_CHAR_LIMIT, _group_pages_into_items

    linhas = [{"n": 1, "subject": "Exame", "type": "EXAME",
               "detail": "palavra " * 2000, "continues": False}]
    pecas = _group_pages_into_items([_pg(1)], linhas)
    assert len(pecas[0].summary) <= _SUMMARY_CHAR_LIMIT


def test_o_numero_da_pagina_e_aceito_como_texto():
    """Modelos devolvem `"n": "5"` com frequência; recusar isso custaria a
    linha inteira."""
    from gclaude_indexer.engine_local import _group_pages_into_items

    linhas = [
        {"n": "1", "subject": "A", "type": "X", "detail": "d", "continues": False},
        {"n": "2", "subject": "B", "type": "X", "detail": "d", "continues": False},
    ]
    pecas = _group_pages_into_items([_pg(1), _pg(2)], linhas)
    assert len(pecas) == 2
    assert pecas[0].type == "X"


def test_assuntos_iguais_com_pontuacao_diferente_casam():
    from gclaude_indexer.engine_local import _same_topic_start, _subject_key

    assert _subject_key("Hemograma, completo!") == _subject_key("hemograma completo")
    # Palavras vazias não separam dois rótulos iguais.
    assert _subject_key("Metabolismo do Ferro") == _subject_key("metabolismo ferro")
    # E dois exames diferentes continuam diferentes.
    assert _subject_key("Ferritina") != _subject_key("Ureia")
    assert _same_topic_start(_subject_key("Hemograma serie vermelha"),
                             _subject_key("Hemograma serie branca"))
    assert not _same_topic_start(_subject_key("Hemograma"), _subject_key("Ferritina"))


def test_o_modo_por_pagina_e_o_padrao():
    from gclaude_indexer.engine_local import LocalEngine

    assert LocalEngine(model="x").per_page is True
    # O modo de faixas continua acessível — é o que os testes da fase 8
    # exercitam contra o servidor falso.
    assert LocalEngine(model="x", per_page=False).per_page is False


# --- 13. servidor rodando código velho ------------------------------------
#
# Aconteceu de verdade: um servidor iniciado às 02:09 continuava, às 08:03,
# executando o código de antes das correções de 05:40 — e passou horas
# produzindo um índice com um defeito já corrigido. O único sinal foi uma
# linha de log que o usuário leu por acaso e estranhou. Nenhuma tela dizia
# que os dois estavam fora de sincronia.


def test_o_sistema_percebe_que_o_codigo_mudou_depois_da_subida(tmp_path, monkeypatch):
    from gclaude_indexer import staleness

    pacote = tmp_path / "gclaude_indexer"
    pacote.mkdir()
    arquivo = pacote / "a.py"
    arquivo.write_text("x = 1", encoding="utf-8")
    monkeypatch.setattr(staleness, "_package_folder", lambda: pacote)

    staleness.record_loaded_source()
    assert staleness.is_stale() is False

    # Uma edição de verdade é detectada.
    arquivo.write_text("x = 2", encoding="utf-8")
    assert staleness.is_stale() is True

    # E voltar ao conteúdo original volta a casar: é o conteúdo que conta.
    arquivo.write_text("x = 1", encoding="utf-8")
    assert staleness.is_stale() is False


def test_o_drive_mexendo_na_data_nao_dispara_alarme_falso(tmp_path, monkeypatch):
    """A pasta é sincronizada pelo Google Drive, que reescreve o carimbo de
    tempo de arquivos cujos bytes não mudaram. Comparar datas daria alarme
    falso com frequência suficiente para o aviso ser ignorado — que é a pior
    coisa que um aviso pode ser."""
    import os

    from gclaude_indexer import staleness

    pacote = tmp_path / "gclaude_indexer"
    pacote.mkdir()
    arquivo = pacote / "a.py"
    arquivo.write_text("x = 1", encoding="utf-8")
    monkeypatch.setattr(staleness, "_package_folder", lambda: pacote)
    staleness.record_loaded_source()

    # Só a data muda; o conteúdo, não.
    futuro = arquivo.stat().st_mtime + 10_000
    os.utime(arquivo, (futuro, futuro))
    assert staleness.is_stale() is False


def test_um_arquivo_novo_no_pacote_tambem_conta(tmp_path, monkeypatch):
    """Uma correção pode chegar como arquivo novo, não como edição de um
    existente — foi o caso de `staleness.py`, `tools.py` e `gpu_budget.py`."""
    from gclaude_indexer import staleness

    pacote = tmp_path / "gclaude_indexer"
    pacote.mkdir()
    (pacote / "a.py").write_text("x = 1", encoding="utf-8")
    monkeypatch.setattr(staleness, "_package_folder", lambda: pacote)
    staleness.record_loaded_source()

    (pacote / "novo.py").write_text("y = 2", encoding="utf-8")
    assert staleness.is_stale() is True


def test_sem_registro_nao_ha_aviso(monkeypatch):
    """Um teste, ou qualquer código que importe o módulo sem subir o
    servidor, não pode ver um aviso: pergunta sem resposta não vira alerta
    na tela."""
    from gclaude_indexer import staleness

    monkeypatch.setattr(staleness, "_loaded_fingerprint", None)
    assert staleness.is_stale() is False


def test_o_aviso_aparece_em_qualquer_tela(pasta_local, monkeypatch):
    """Em toda tela, e não só na de Execução: código velho erra em qualquer
    etapa, e o usuário precisa ver isso onde quer que esteja."""
    from fastapi.testclient import TestClient

    from gclaude_indexer.web import app as app_mod

    monkeypatch.setattr(app_mod, "source_is_stale", lambda: True)
    cliente = TestClient(app_mod.app)
    for rota in ("/projects", "/projects/new", "/about"):
        resposta = cliente.get(rota)
        assert resposta.status_code == 200, rota
        assert "stale-banner" in resposta.text, rota

    monkeypatch.setattr(app_mod, "source_is_stale", lambda: False)
    assert "stale-banner" not in cliente.get("/projects").text


def test_o_pedido_de_elevacao_nao_segura_a_subida_do_servidor(monkeypatch):
    """O prompt do Windows bloqueia até alguém responder — e a resposta pode
    nunca vir.

    `ShellExecuteW` com o verbo "runas" só retorna depois que o usuário
    decide. Feita em linha, antes do `uvicorn.run`, essa chamada segurava a
    subida inteira: o prompt costuma aparecer atrás da janela do navegador,
    e enquanto não fosse respondido a porta 8000 nem começava a escutar.
    Encontrado com quatro `consent.exe` empilhados e o servidor parado
    atrás deles — o sistema simplesmente não abria.
    """
    import threading
    import time

    from gclaude_indexer.web import app as app_mod

    subiu = threading.Event()
    liberar = threading.Event()

    def _elevacao_que_trava():
        # Simula o prompt aberto que ninguém responde.
        liberar.wait(timeout=10)

    def _uvicorn_falso(app, host, port):
        subiu.set()

    monkeypatch.setattr(app_mod, "_request_cpu_sensor_helper", _elevacao_que_trava)
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", _uvicorn_falso)

    inicio = time.monotonic()
    app_mod.start_server()
    decorrido = time.monotonic() - inicio

    assert subiu.is_set(), "o servidor tem de subir mesmo com o prompt pendente"
    assert decorrido < 2.0, f"a subida esperou o prompt ({decorrido:.1f}s)"
    liberar.set()

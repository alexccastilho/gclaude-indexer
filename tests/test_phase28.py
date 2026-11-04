"""1.5.8 — desempenho e atualização sem servidor antigo.

- Intermediários (`converted/`, `blocks/`) na pasta local da máquina, não
  na pasta de saída do Google Drive; projetos antigos continuam lendo os
  que ficaram lá; em outro computador o arquivo volta para a conversão.
- Conversão em duas filas: arquivos leves num grupo grande de processos.
- Janelas: `.txt` só para o motor Claude Code; classificação sem reler o
  grupo inteiro a cada janela.
- Instalação de versão nova: o servidor antigo é encerrado.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import fitz

from gclaude_indexer import cleanup, parallelism, workdir
from gclaude_indexer.classification import WindowPageLoader, load_window_pages
from gclaude_indexer.conversion import convert
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.i18n import translate
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows, write_missing_window_files

from .test_phase4 import _criar_pdf, _preparar_projeto


TODAS = {"extensions": ["all"]}


def _html(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(f"<html><body><p>{texto}</p></body></html>", encoding="utf-8")


def _linha(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


# --- intermediários na pasta local ------------------------------------------


def test_conversao_grava_intermediarios_na_pasta_local_e_nao_na_saida(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path, extra=TODAS)
    _html(origem / "lei.htm", "Lei de teste com texto suficiente para a extração.")
    scan(conn, config)
    convert(conn, config)

    local = workdir.work_folder(saida) / "converted" / "lei.txt"
    assert local.is_file()
    assert "Lei de teste" in local.read_text(encoding="utf-8")
    assert not (saida / "converted").exists()
    assert str(saida) in (workdir.work_folder(saida) / "origin.txt").read_text(encoding="utf-8")

    extract_pages(conn, config)
    assert _linha(conn, "lei.htm")["status"] == "extracted"
    conn.close()


def test_projeto_convertido_antes_da_1_5_8_le_os_intermediarios_da_saida(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path, extra=TODAS)
    _html(origem / "lei.htm", "Texto que ficou na pasta de saída por uma versão anterior.")
    scan(conn, config)
    convert(conn, config)

    # Como uma versão anterior deixaria: a cópia na pasta de saída.
    local = workdir.work_folder(saida) / "converted" / "lei.txt"
    antigo = saida / "converted" / "lei.txt"
    antigo.parent.mkdir(parents=True)
    shutil.move(str(local), str(antigo))

    resultado = extract_pages(conn, config)
    assert resultado.failed == 0
    assert _linha(conn, "lei.htm")["status"] == "extracted"
    texto = conn.execute("SELECT text FROM page").fetchone()[0]
    assert "versão anterior" in texto
    conn.close()


def test_sem_o_intermediario_neste_computador_o_arquivo_volta_para_a_conversao(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path, extra=TODAS)
    _html(origem / "lei.htm", "Convertido em outro computador.")
    scan(conn, config)
    convert(conn, config)
    shutil.rmtree(workdir.work_folder(saida))

    resultado = extract_pages(conn, config, language="pt-BR")
    linha = _linha(conn, "lei.htm")
    assert resultado.failed == 0
    assert linha["status"] == "discovered"
    mensagens = [e["message"] for e in list_events(conn, step="extraction", language="pt-BR")]
    assert any("não está neste computador" in m for m in mensagens)

    convert(conn, config)
    extract_pages(conn, config)
    assert _linha(conn, "lei.htm")["status"] == "extracted"
    conn.close()


def test_limpeza_apaga_os_intermediarios_nos_dois_lugares(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path, extra=TODAS)
    _html(origem / "lei.htm", "Texto.")
    scan(conn, config)
    convert(conn, config)
    antigo = saida / "converted" / "velho.txt"
    antigo.parent.mkdir(parents=True)
    antigo.write_text("de uma versão anterior", encoding="utf-8")

    liberado = cleanup.clear_intermediates(str(saida))
    assert liberado > 0
    assert not (workdir.work_folder(saida) / "converted").exists()
    assert not (saida / "converted").exists()
    conn.close()


def test_caminho_do_intermediario_prefere_o_local_e_cai_no_antigo():
    saida = Path("C:/projetos/saida")
    local = workdir.local_path(saida, "converted", "a/b.htm", ".txt")
    assert local.parts[-3:] == ("converted", "a", "b.txt")
    assert workdir.intermediate_path(saida, "converted", "a/b.htm", ".txt") == local
    assert workdir.work_folder(saida) == workdir.work_folder("C:/projetos/saida/")


# --- conversão em duas filas ------------------------------------------------


def test_arquivos_leves_tem_mais_processos_que_o_ocr(monkeypatch):
    monkeypatch.setattr(parallelism, "_physical_cores", lambda: 8)
    assert parallelism.io_workers_for("economy") == 1
    assert parallelism.io_workers_for("automatic") == 16
    assert parallelism.io_workers_for("maximum") == 32
    assert parallelism.workers_for("maximum") == 8


def test_acervo_misto_converte_leves_e_pdfs_no_modo_maximo(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path, extra={**TODAS, "parallelism": "maximum"})
    for indice in range(6):
        _html(origem / f"leis/lei{indice}.htm", f"Lei número {indice}.")
    _criar_pdf(origem / "leis/coletanea.pdf", n_paginas=2)
    scan(conn, config)

    resultado = convert(conn, config)
    assert resultado.converted == 7
    assert resultado.failed == 0
    assert conn.execute("SELECT COUNT(*) FROM file WHERE status = 'converted'").fetchone()[0] == 7
    conn.close()


# --- janelas e classificação ------------------------------------------------


def _projeto_com_paginas(tmp_path, motor="automatic"):
    origem, saida, config, conn = _preparar_projeto(
        tmp_path, extra={"pages_per_window": 3, "overlap": 1, "classification_engine": motor}
    )
    _criar_pdf(origem / "processo.pdf", n_paginas=8)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    return origem, saida, config, conn


def test_janelas_sem_arquivos_txt_quando_o_motor_nao_e_o_claude_code(tmp_path):
    _, saida, config, conn = _projeto_com_paginas(tmp_path)
    resultado = prepare_windows(conn, config)
    assert resultado.created > 0
    assert not list((saida / "windows").glob("*.txt"))
    conn.close()


def test_janelas_com_arquivos_txt_para_o_claude_code_e_os_que_faltarem(tmp_path):
    _, saida, config, conn = _projeto_com_paginas(tmp_path, motor="claude_code")
    resultado = prepare_windows(conn, config)
    arquivos = sorted((saida / "windows").glob("*.txt"))
    assert len(arquivos) == resultado.created

    # Motor trocado depois da etapa: o que faltar é escrito na preparação.
    arquivos[0].unlink()
    assert write_missing_window_files(conn, config) == 1
    assert arquivos[0].is_file()
    assert write_missing_window_files(conn, config) == 0
    conn.close()


def test_carregador_de_janelas_devolve_as_mesmas_paginas(tmp_path):
    _, saida, config, conn = _projeto_com_paginas(tmp_path)
    prepare_windows(conn, config)
    loader = WindowPageLoader(conn)
    janelas = conn.execute("SELECT * FROM window ORDER BY id").fetchall()
    assert len(janelas) > 1
    for janela in janelas:
        assert load_window_pages(conn, janela, loader) == load_window_pages(conn, janela)
    conn.close()


# --- atualização: servidor de versão antiga ---------------------------------


def test_endereco_de_versao():
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import SYSTEM_VERSION, app

    resposta = TestClient(app).get("/api/version")
    assert resposta.status_code == 200
    assert resposta.json() == {"version": SYSTEM_VERSION}


def test_so_encerra_processo_do_proprio_programa(monkeypatch):
    import os
    import subprocess
    import sys

    from gclaude_indexer import paths
    from gclaude_indexer.web import app as app_module

    # Um venv do programa que não é o do Python que roda a suíte.
    monkeypatch.setattr(paths, "machine_local_folder", lambda: Path("C:/nao/existe"))
    # O próprio processo nunca; e um processo fora do venv do programa
    # (aqui, um Python qualquer) também não.
    assert app_module.stop_outdated_server("127.0.0.1", 8999, os.getpid()) is False
    alheio = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert app_module.stop_outdated_server("127.0.0.1", 8999, alheio.pid) is False
        assert alheio.poll() is None
    finally:
        alheio.kill()
        alheio.wait()


def test_versao_que_nao_responde_e_desconhecida():
    from gclaude_indexer.web.app import _running_version

    assert _running_version("127.0.0.1", 1) is None


def test_mensagem_nova_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        texto = translate(idioma, "log.extraction.intermediate_missing", name="a.htm")
        assert "a.htm" in texto and texto != "log.extraction.intermediate_missing"

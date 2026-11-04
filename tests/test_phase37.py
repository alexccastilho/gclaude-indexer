# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 37 — CI verificável, medida de qualidade e acervo de demonstração.

"""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent


# --- Task 1: a suíte fala com uma porta fechada, nunca com o Ollama real ----


def test_a_suite_nunca_alcanca_o_ollama_real():
    """Antes desta fase a suíte fazia centenas de pedidos 404 ao Ollama real
    da máquina do desenvolvedor (modelos falsos em 127.0.0.1:11434), e duas
    quedas do servidor em uso coincidiram com rodadas da suíte em 02/11."""
    from gclaude_indexer import engine_local

    assert engine_local.OLLAMA_BASE_URL == "http://127.0.0.1:9"
    assert engine_local.LocalEngine(model="x").url_base == "http://127.0.0.1:9"
    assert engine_local.LocalEngine(model="x", url_base="http://127.0.0.1:8").url_base == "http://127.0.0.1:8"


def test_os_outros_leitores_do_ollama_tambem_usam_a_porta_fechada(monkeypatch):
    """`hardware` e `web.ollama_models` consultavam `/api/tags` com o
    endereço copiado na importação — a rodada parcial da suíte deixou 7
    pedidos `GET /api/tags` no log do servidor real mesmo com a fixture."""
    import urllib.request

    from gclaude_indexer import hardware
    from gclaude_indexer.web import ollama_models

    urls = []

    def captura(url, timeout=None):
        urls.append(url)
        raise OSError("porta fechada")

    monkeypatch.setattr(urllib.request, "urlopen", captura)
    assert hardware._real_model_size_mb("x") is None
    assert ollama_models.list_installed_models() == []
    assert urls == ["http://127.0.0.1:9/api/tags", "http://127.0.0.1:9/api/tags"]



def test_o_cli_do_ollama_tambem_e_apontado_para_a_porta_fechada():
    """A tela "Sobre" roda `ollama --version` (install_diagnostics), e o
    próprio CLI consulta `/api/version` do servidor que `OLLAMA_HOST` indica:
    eram 6 pedidos por rodada de test_phase13 mesmo com a URL do motor
    trocada. Com a porta fechada o CLI avisa e ainda sai com código 0."""
    import os

    assert os.environ.get("OLLAMA_HOST") == "127.0.0.1:9"



def test_a_suite_nunca_sobe_um_ollama_serve_de_verdade(monkeypatch, tmp_path):
    """Com a porta fechada, `run_classification` acha o Ollama fora do ar e
    `_try_restart_ollama` subia um `ollama serve` REAL com o `OLLAMA_HOST`
    da suíte: às 16:13 de 02/11 um servidor órfão ficou escutando na porta
    9, atendendo os modelos falsos dos testes e gravando por cima do log do
    servidor da máquina. Nenhum teste pode chegar ao `Popen`."""
    import sqlite3
    import subprocess

    from gclaude_indexer import engine_local
    from gclaude_indexer.db import init_schema

    import threading

    chamadas = []
    popen_real = subprocess.Popen
    thread_do_teste = threading.current_thread()

    def popen_proibido(*args, **kwargs):
        # Só a thread deste teste conta: o amostrador de recursos
        # (`resources.ResourceSampler`, thread "resource-sampler", iniciado
        # por qualquer teste que leia a tela Execução) roda o PowerShell dos
        # contadores pelo `Popen` a cada intervalo, e já caiu nesta
        # armadilha no runner do GitHub. Esse Popen
        # é de outra thread e não tem nada a ver com `_try_restart_ollama`.
        if threading.current_thread() is not thread_do_teste:
            return popen_real(*args, **kwargs)
        chamadas.append(args[0] if args else kwargs.get("args"))
        raise AssertionError("Popen chamado pela suíte")

    monkeypatch.setattr(subprocess, "Popen", popen_proibido)
    monkeypatch.setattr(engine_local, "WAIT_BETWEEN_ATTEMPTS_S", 0.0)
    conn = sqlite3.connect(tmp_path / "p.db")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    assert engine_local._try_restart_ollama(conn, engine_local.LocalEngine(model="x")) is False
    assert chamadas == []



def test_a_suite_nao_para_o_ollama_da_maquina(tmp_path):
    """Um canário (presença do `ollama.exe` conferida após cada teste)
    apontou o culpado das quedas do servidor em uso
    durante a suíte: `test_fechar_o_ollama_funciona_com_ele_ausente` (fase
    19) chamava a `Stop-OllamaProcesses` real do desinstalador, que para todo
    processo chamado `ollama` da máquina. Um sósia (cmd.exe renomeado) tem de
    sobreviver àquele teste."""
    import importlib.util
    import os
    import shutil
    import subprocess
    import time

    sosia = tmp_path / "ollama.exe"
    shutil.copy(os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe", sosia)
    processo = subprocess.Popen([str(sosia), "/c", "ping -n 30 127.0.0.1 >nul"],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        spec = importlib.util.spec_from_file_location("test_phase19", _RAIZ / "tests" / "test_phase19.py")
        fase19 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fase19)
        fase19.test_fechar_o_ollama_funciona_com_ele_ausente()
        time.sleep(0.5)
        assert processo.poll() is None, "a suíte parou um processo chamado ollama.exe que não é dela"
    finally:
        processo.kill()
        processo.wait()


# --- Task 2: comparação do índice com um gabarito ---------------------------


def _banco_com_indice(tmp_path, arquivos, itens):
    """`arquivos`: (caminho_relativo, grupo, páginas); `itens`: (grupo,
    start_order, end_order, tipo, data, autor). As folhas são contínuas no
    grupo, como a extração grava ("f. 1", "f. 2", ...)."""
    import sqlite3

    from gclaude_indexer.db import init_schema

    conn = sqlite3.connect(tmp_path / "project.db")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    folha_por_grupo: dict[str, int] = {}
    for caminho, grupo, paginas in arquivos:
        nome = caminho.rsplit("/", 1)[-1]
        file_id = conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, page_count, status)"
            " VALUES (?, ?, 'pdf', 1, 'x', ?, ?, 'extracted')",
            (caminho, nome, grupo, paginas),
        ).lastrowid
        for numero in range(1, paginas + 1):
            folha = folha_por_grupo.get(grupo, 0) + 1
            folha_por_grupo[grupo] = folha
            conn.execute(
                "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text)"
                " VALUES (?, ?, ?, 10, 0, 0, 'texto')",
                (file_id, numero, f"f. {folha}"),
            )
    for grupo, inicio, fim, tipo, data, autor in itens:
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, type, date, author,"
            " engine, confidence, files) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'rules', 'high', '')",
            (grupo, f"f. {inicio}", f"f. {fim}", inicio, fim, tipo, data, autor),
        )
    conn.commit()
    return conn


def _gabarito_csv(tmp_path, linhas):
    caminho = tmp_path / "gabarito.csv"
    caminho.write_text(
        "arquivo,pagina_inicial,pagina_final,tipo,data,autor\n" + "".join(l + "\n" for l in linhas),
        encoding="utf-8",
    )
    return caminho


def test_gabarito_e_lido_do_csv(tmp_path):
    from gclaude_indexer.answer_key import KeyPiece, load_answer_key

    pecas = load_answer_key(_gabarito_csv(tmp_path, [
        "Processo 2026-0001/volume_1.pdf,1,3,OFÍCIO,2026-01-10,Maria Souza",
        "Processo 2026-0001/volume_1.pdf,4,4,,,",
        "Contratos/contrato.pdf,1,2,TERMO,2026-03-05,\"Prefeitura, Secretaria de Obras\"",
    ]))
    assert pecas == [
        KeyPiece("Processo 2026-0001/volume_1.pdf", 1, 3, "OFÍCIO", "2026-01-10", "Maria Souza"),
        KeyPiece("Processo 2026-0001/volume_1.pdf", 4, 4, "", "", ""),
        KeyPiece("Contratos/contrato.pdf", 1, 2, "TERMO", "2026-03-05", "Prefeitura, Secretaria de Obras"),
    ]


def test_cobertura_limites_e_campos(tmp_path):
    """Jaccard ≥ 0,5 por arquivo: a peça B (f. 4) devolvida como f. 4-5
    conta como encontrada com limite errado, não como ausente."""
    from gclaude_indexer.answer_key import KeyPiece, compare_with_answer_key

    conn = _banco_com_indice(tmp_path, [("P/v1.pdf", "P", 8)], [
        ("P", 1, 3, "OFICIO", "2026-01-10", "M. Souza"),
        ("P", 4, 5, None, None, None),
        ("P", 6, 8, "PARECER", "2026-02-02", "PGM"),
    ])
    relatorio = compare_with_answer_key(conn, [
        KeyPiece("P/v1.pdf", 1, 3, "OFÍCIO", "2026-01-10", "Maria Souza"),
        KeyPiece("P/v1.pdf", 4, 4, "", "", ""),
        KeyPiece("P/v1.pdf", 5, 8, "PARECER", "2026-02-01", "Procuradoria (PGM)"),
    ])
    assert (relatorio.pages_total, relatorio.pages_covered) == (8, 8)
    assert (relatorio.key_pieces, relatorio.index_pieces, relatorio.matched) == (3, 3, 3)
    assert (relatorio.precision, relatorio.recall, relatorio.f1) == (1.0, 1.0, 1.0)
    assert (relatorio.type_score.hits, relatorio.type_score.total) == (3, 3)
    assert (relatorio.date_score.hits, relatorio.date_score.total) == (1, 2)
    assert (relatorio.author_score.hits, relatorio.author_score.total) == (2, 2)
    assert list(relatorio.by_group) == ["P"]
    assert relatorio.by_group["P"].matched == 3
    assert [m["field"] for m in relatorio.mismatches] == ["pages", "pages", "date"]


def test_indice_vazio_nao_divide_por_zero(tmp_path):
    from gclaude_indexer.answer_key import KeyPiece, compare_with_answer_key

    conn = _banco_com_indice(tmp_path, [("P/v1.pdf", "P", 4)], [])
    relatorio = compare_with_answer_key(conn, [KeyPiece("P/v1.pdf", 1, 4, "ATA", "", "")])
    assert relatorio.coverage == 0.0
    assert relatorio.precision is None
    assert relatorio.recall == 0.0
    assert relatorio.f1 is None
    assert relatorio.type_score.rate is None


def test_arquivo_fora_do_gabarito_e_listado(tmp_path):
    """Divergência entre acervo e gabarito aparece no relatório e não
    derruba a medição; páginas de arquivo que o índice não tem contam como
    não cobertas."""
    from gclaude_indexer.answer_key import KeyPiece, compare_with_answer_key

    conn = _banco_com_indice(tmp_path, [("P/v1.pdf", "P", 2), ("Solto/extra.pdf", "Solto", 1)], [
        ("P", 1, 2, "ATA", None, None),
        ("Solto", 1, 1, "OFICIO", None, None),
    ])
    relatorio = compare_with_answer_key(conn, [
        KeyPiece("P/v1.pdf", 1, 2, "ATA", "", ""),
        KeyPiece("P/v2.pdf", 1, 3, "DESPACHO", "", ""),
    ])
    assert relatorio.unknown_files == ["Solto/extra.pdf"]
    assert relatorio.missing_files == ["P/v2.pdf"]
    assert (relatorio.pages_total, relatorio.pages_covered) == (5, 2)
    assert (relatorio.key_pieces, relatorio.index_pieces, relatorio.matched) == (2, 2, 1)


def test_relatorio_em_markdown_tem_as_linhas_da_tabela(tmp_path):
    from gclaude_indexer.answer_key import KeyPiece, compare_with_answer_key, render_report

    conn = _banco_com_indice(tmp_path, [("P/v1.pdf", "P", 4)], [("P", 1, 4, "ATA", "2026-01-01", "Mesa Diretora da Câmara")])
    relatorio = compare_with_answer_key(conn, [KeyPiece("P/v1.pdf", 1, 4, "ATA", "2026-01-01", "Mesa Diretora")])
    texto = render_report(relatorio, {
        "engine": "rules", "model": "", "version": "1.7.5", "machine": "RX 6700 XT",
        "date": "2026-11-02", "duration_s": 61.5,
    })
    assert "| rules |" in texto and "1.7.5" in texto and "RX 6700 XT" in texto
    assert "| **Total** | 4/4 (100,0%) | 1/1 | 100,0% | 100,0% | 100,0% | 100,0% | 100,0% | 100,0% |" in texto
    assert "| P | 4/4 (100,0%) |" in texto


def test_normalize_type_e_author_matches():
    from gclaude_indexer.answer_key import author_matches, normalize_type

    assert normalize_type(" Ofício   Circular ") == "OFICIO CIRCULAR"
    assert normalize_type(None) == ""
    assert author_matches("Maria Souza", "M. Souza")
    assert author_matches("Procuradoria (PGM)", "PGM")
    assert author_matches("João de Assunção", "joao de assuncao")
    assert not author_matches("Maria Souza", None)
    assert not author_matches("Maria Souza", "Prefeitura")


# --- Task 3: acervo de demonstração ------------------------------------------

_DEMO = _RAIZ / "demo"


def _gerar_acervo():
    import importlib.util

    import sys

    spec = importlib.util.spec_from_file_location("gerar_acervo", _DEMO / "gerar_acervo.py")
    module = importlib.util.module_from_spec(spec)
    # `dataclass` procura o módulo em sys.modules para resolver as anotações
    # (`from __future__ import annotations`); sem registrar, AttributeError.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _arquivos_do_acervo() -> set[str]:
    return {
        str(p.relative_to(_DEMO / "acervo")).replace("\\", "/")
        for p in (_DEMO / "acervo").rglob("*") if p.is_file()
    }


def test_gabarito_bate_com_os_arquivos_do_acervo():
    """Foco de revisão 1: toda faixa cabe no arquivo, sem buraco nem
    sobreposição; os tipos são os do motor de regras; há peças sem tipo."""
    import json
    import re

    import fitz

    from gclaude_indexer.answer_key import load_answer_key

    pecas = load_answer_key(_DEMO / "gabarito.csv")
    por_arquivo: dict[str, list] = {}
    for peca in pecas:
        por_arquivo.setdefault(peca.file, []).append(peca)
    assert set(por_arquivo) == _arquivos_do_acervo()

    for arquivo, lista in por_arquivo.items():
        caminho = _DEMO / "acervo" / arquivo
        if caminho.suffix == ".pdf":
            with fitz.open(caminho) as doc:
                total = doc.page_count
        else:
            # extraction._extract_file_pages: texto convertido de .docx, .xlsx,
            # .eml e imagem vira UMA página lógica, cortada em chars_per_page.
            total = 1
        proxima = 1
        for inicio, fim in sorted((p.first_page, p.last_page) for p in lista):
            assert (inicio, fim >= inicio) == (proxima, True), (arquivo, inicio, fim, proxima)
            proxima = fim + 1
        assert proxima == total + 1, (arquivo, proxima - 1, total)

    tipos = {p.type for p in pecas}
    vocabulario = json.loads((_RAIZ / "config" / "classification_rules.json").read_text(encoding="utf-8"))["types"]
    assert tipos - {""} <= set(vocabulario), tipos - {""} - set(vocabulario)
    assert len(tipos - {""}) >= 10
    assert sum(1 for p in pecas if p.type == "") >= 3
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.date) for p in pecas if p.date)
    assert len(pecas) >= 25


def test_gerador_reproduz_o_acervo_versionado(tmp_path):
    """Quem muda `PECAS` regenera; quem não muda tem o mesmo acervo que o
    repositório, página por página."""
    import fitz
    from PIL import Image, ImageChops

    from gclaude_indexer import conversion

    _gerar_acervo().main(tmp_path)
    assert (tmp_path / "gabarito.csv").read_text(encoding="utf-8") == (_DEMO / "gabarito.csv").read_text(encoding="utf-8")
    gerados = {
        str(p.relative_to(tmp_path / "acervo")).replace("\\", "/")
        for p in (tmp_path / "acervo").rglob("*") if p.is_file()
    }
    assert gerados == _arquivos_do_acervo()
    for rel in sorted(gerados):
        novo, versionado = tmp_path / "acervo" / rel, _DEMO / "acervo" / rel
        if rel.endswith(".pdf"):
            with fitz.open(novo) as a, fitz.open(versionado) as b:
                assert [p.get_text() for p in a] == [p.get_text() for p in b], rel
        elif rel.endswith(".docx"):
            assert conversion._extract_text_docx(novo) == conversion._extract_text_docx(versionado)
        elif rel.endswith(".xlsx"):
            assert conversion._extract_text_xlsx(novo) == conversion._extract_text_xlsx(versionado)
        elif rel.endswith(".eml"):
            assert novo.read_bytes() == versionado.read_bytes()
        elif rel.endswith(".png"):
            with Image.open(novo) as a, Image.open(versionado) as b:
                assert a.size == b.size and ImageChops.difference(a.convert("L"), b.convert("L")).getbbox() is None


def test_acervo_tem_os_formatos_prometidos():
    import email
    from email import policy

    from PIL import Image

    sufixos = {rel.rsplit(".", 1)[-1] for rel in _arquivos_do_acervo()}
    assert {"pdf", "docx", "xlsx", "png", "eml"} <= sufixos
    # 150 dpi sobre A4 dá 1240 px de largura: legível pelo Tesseract, e o
    # arquivo fica em dezenas de KB, não em MB.
    with Image.open(_DEMO / "acervo" / "Contratos" / "oficio_digitalizado.png") as imagem:
        assert imagem.size[0] >= 1200
    with (_DEMO / "acervo" / "Contratos" / "pedido_prorrogacao.eml").open("rb") as handle:
        mensagem = email.message_from_binary_file(handle, policy=policy.default)
    assert mensagem["Subject"] and mensagem["From"] and mensagem.get_body(("plain",)) is not None


def test_o_municipio_do_acervo_nao_existe():
    """A revisão da fase 37 achou que "Vila Nova do Sul" existe (RS, IBGE
    4323457); o nome atual foi conferido contra a lista do IBGE.
    Nada no acervo pode citar o município real."""
    import fitz

    real = "Vila Nova do Sul"
    assert _gerar_acervo().MUNICIPIO != real
    for rel in ("demo/gerar_acervo.py", "demo/README.md", "demo/acervo/Contratos/pedido_prorrogacao.eml"):
        assert real not in (_RAIZ / rel).read_text(encoding="utf-8"), rel
    for pdf in sorted((_RAIZ / "demo" / "acervo").rglob("*.pdf")):
        with fitz.open(pdf) as documento:
            assert all(real not in pagina.get_text() for pagina in documento), pdf.name


# --- Task 4: indexação sem interface e medição ------------------------------


def _ferramenta(nome: str):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(nome, _RAIZ / "tools" / f"{nome}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_indexacao_sem_interface_do_acervo_de_demonstracao_cobre_todas_as_paginas(tmp_path, monkeypatch):
    """Foco de revisão 4: o pipeline real, com o motor de regras e OCR na
    página digitalizada, coloca toda página do gabarito em alguma peça."""
    from gclaude_indexer import ocr_languages

    # A pasta local vai para tmp_path (a conversão escreve em
    # machine_local_folder()/work), mas o idioma do OCR mora na pasta privada
    # REAL desta máquina e a suíte não baixa nada: aponta-se para ela quando
    # existe. No CI ela não existe e a pasta do próprio Tesseract tem o `por`.
    tessdata_real = ocr_languages.private_folder()
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    if tessdata_real.is_dir():
        monkeypatch.setenv("TESSDATA_PREFIX", str(tessdata_real))
    indexar_pasta = _ferramenta("indexar_pasta")
    medir_acerto = _ferramenta("medir_acerto")

    info = indexar_pasta.run(_RAIZ / "demo" / "acervo", tmp_path / "saida", engine="rules")
    assert (tmp_path / "saida" / "index.md").exists()
    assert info["engine"] == "rules" and info["items"] > 0 and info["duration_s"] >= 0
    assert (tmp_path / "saida" / "run_info.json").exists()

    report = medir_acerto.run(tmp_path / "saida", _RAIZ / "demo" / "gabarito.csv", tmp_path / "acerto.md")
    assert report.coverage == 1.0, (report.pages_covered, report.pages_total, report.missing_files)
    assert report.unknown_files == [] and report.missing_files == []
    texto = (tmp_path / "acerto.md").read_text(encoding="utf-8")
    assert texto.startswith("# ") and "| rules |" in texto


# --- Task 5: CI prova o produto; selo no README ----------------------------


def test_ci_indexa_o_acervo_de_demonstracao_e_publica_o_relatorio():
    wf = (_RAIZ / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "tools/indexar_pasta.py demo/acervo" in wf and "tools/medir_acerto.py" in wf
    assert "--exigir-cobertura 1.0" in wf
    # Revisão da fase 37: `"\demo_indexado\acerto.md"` saiu com um BEL (0x07)
    # no lugar de `\a`; nenhuma substring acima tocava o trecho. Barras
    # normais (Python e upload-artifact aceitam) e nenhum byte de controle.
    assert '--saida-md "$env:RUNNER_TEMP/demo_indexado/acerto.md"' in wf
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", wf), "byte de controle no workflow"
    assert "actions/upload-artifact" in wf and "if: always()" in wf
    for leiame in ("README.md", "docs/README.pt-BR.md", "docs/README.es.md"):
        texto = (_RAIZ / leiame).read_text(encoding="utf-8")
        assert "actions/workflows/tests.yml/badge.svg" in texto, leiame


# --- Task 6: números reais e documentação ------------------------------------


def test_documentos_de_qualidade_nos_tres_idiomas():
    for nome in ("QUALITY.md", "QUALITY.pt-BR.md", "QUALITY.es.md"):
        texto = (_RAIZ / "docs" / nome).read_text(encoding="utf-8")
        assert "qwen3.5:9b" in texto, nome
        assert "rules" in texto.lower() or "regras" in texto.lower() or "reglas" in texto.lower(), nome
        assert "Jaccard" in texto, nome
    for leiame in ("README.md", "docs/README.pt-BR.md", "docs/README.es.md"):
        assert "demo/" in (_RAIZ / leiame).read_text(encoding="utf-8"), leiame


# --- Task 7: versão 1.7.5 e documentos ---------------------------------------


def test_versao_e_documentos_da_fase_37():
    import re

    # A versão exata e o nome do instalador são afirmados pelo teste da fase
    # corrente (`test_phase38_docs.test_versao_e_documentos_da_fase_38`);
    # aqui fica o que a 1.7.5 deixou e nenhuma fase seguinte desfaz.
    app = (_RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    assert re.search(r'^SYSTEM_VERSION = "\d+\.\d+\.\d+"$', app, re.M)
    for registro in ("CHANGELOG.md", "docs/CHANGELOG.pt-BR.md", "docs/CHANGELOG.es.md"):
        texto = (_RAIZ / registro).read_text(encoding="utf-8")
        assert "## [1.7.5]" in texto and texto.index("## [1.7.5]") < texto.index("## [1.7.4]"), registro
        assert "QUALITY" in texto, registro
    especificacao = (_RAIZ / "docs" / "SPECIFICATION.md").read_text(encoding="utf-8")
    assert "QUALITY.md" in especificacao and "demo/gabarito.csv" in especificacao

"""Busca de texto completo: toda informação dos arquivos pode ser localizada.

A classificação lê só os primeiros "caracteres por página"; a busca guarda
o texto inteiro, em trechos que dizem onde estão (folha/página, artigo,
linha), sem acento e sem diferença de maiúsculas, e marca o que estava
tachado no original.
"""

from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.fulltext import (
    MATCH_START,
    coverage,
    fts_query,
    index_pending,
    search,
    split_document,
)
from gclaude_indexer.scanning import scan
from gclaude_indexer.web.app import app

ARTIGOS_LONGOS = "\n".join(
    f"Art. {n}º " + f"Disposição número {n} sobre a matéria regulada. " * 20 for n in range(1, 6)
)


def _lei_html(corpo_extra: str = "", tachado: str = "") -> str:
    revogado = f"<p><strike>{tachado}</strike></p>" if tachado else ""
    artigos = "".join(
        f"<p>Art. {n}º " + f"Disposição número {n} sobre a matéria regulada. " * 20 + "</p>"
        for n in range(1, 40)
    )
    return (
        "<html><body><p>LEI Nº 9.999, DE 1º DE JANEIRO DE 2020.</p>"
        f"{artigos}{revogado}<p>Art. 40. {corpo_extra}</p></body></html>"
    )


def _projeto(tmp_path, chars_per_page=2000):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Busca",
        "source_folder": str(origem),
        "output_folder": str(saida),
        "extensions": ["pdf", "web_dados", "text", "docx"],
        "collection_type": "biblioteca",
        "classification_engine": "rules",
        "chars_per_page": chars_per_page,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, config, conn


def _extrair(conn, config):
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)


# --- divisão em trechos ----------------------------------------------------------


def test_trechos_levam_o_artigo_e_a_linha_onde_comecam():
    trechos = split_document("LEI Nº 1\nPreâmbulo curto.\n" + ARTIGOS_LONGOS)

    assert len(trechos) >= 5
    rotulos = [t.locator for t in trechos]
    assert "Art. 3º" in rotulos
    terceiro = next(t for t in trechos if t.locator == "Art. 3º")
    assert terceiro.text.startswith("Art. 3º")
    assert terceiro.line == 5


def test_texto_sem_estrutura_e_cortado_em_trechos_limitados():
    trechos = split_document("\n".join("linha de texto corrido sem títulos " * 3 for _ in range(400)))
    assert len(trechos) > 1
    assert all(len(t.text) < 2500 + 200 for t in trechos)


def test_consulta_do_usuario_nunca_vira_erro_de_sintaxe():
    assert fts_query('lei "ordem cronológica" revoga*') == '"lei" "ordem cronológica" "revoga"*'
    assert fts_query('(a OR b) - "') == '"a" "OR" "b"'
    assert fts_query("   ") == ""


# --- de ponta a ponta ----------------------------------------------------------------


def test_trecho_alem_do_corte_de_caracteres_e_encontrado(tmp_path):
    origem, config, conn = _projeto(tmp_path, chars_per_page=1500)
    (origem / "lei.htm").write_bytes(_lei_html("Fica instituída a semana da xilogravura.").encode("cp1252"))

    _extrair(conn, config)

    # A página guardada para a classificação foi cortada antes do fim...
    assert "xilogravura" not in conn.execute("SELECT text FROM page").fetchone()[0]
    # ...mas a busca acha, sem acento, e diz onde.
    hits, total = search(conn, "instituida XILOGRAVURA")
    assert total == 1
    assert hits[0].name == "lei.htm"
    assert hits[0].locator == "p. 1 · Art. 40"
    assert hits[0].line > 1
    assert MATCH_START in hits[0].snippet
    assert coverage(conn) == (1, 1)
    conn.close()


def test_texto_tachado_e_marcado_no_resultado(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    (origem / "lei.htm").write_text(
        _lei_html("Vigente.", tachado="Art. 39-A. Fica criado o conselho de zeladoria."), encoding="utf-8"
    )
    _extrair(conn, config)

    [revogado], _ = search(conn, "zeladoria")
    vigentes, _ = search(conn, "Disposição")
    assert revogado.struck is True
    assert vigentes and not any(hit.struck for hit in vigentes)
    conn.close()


def test_pdf_e_localizado_pela_pagina(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    documento = fitz.open()
    for n in range(3):
        documento.new_page().insert_text((72, 72), f"Página {n + 1} do parecer." + (" Ornitorrinco." if n == 2 else ""))
    documento.save(origem / "parecer.pdf")
    documento.close()

    _extrair(conn, config)

    [hit], total = search(conn, "ornitorrinco")
    assert (total, hit.locator, hit.name) == (1, "p. 3", "parecer.pdf")
    conn.close()


def test_arquivo_reprocessado_sai_da_busca(tmp_path):
    import os

    from gclaude_indexer.invalidation import apply_update_plan
    from gclaude_indexer.update_plan import build_update_plan

    origem, config, conn = _projeto(tmp_path)
    arquivo = origem / "nota.txt"
    arquivo.write_text("Texto sobre capivaras.", encoding="utf-8")
    _extrair(conn, config)
    assert search(conn, "capivaras")[1] == 1

    arquivo.write_text("Texto sobre tamanduás, bem mais longo que antes.", encoding="utf-8")
    os.utime(arquivo, (2_000_000_000, 2_000_000_000))
    apply_update_plan(conn, config, build_update_plan(conn, config), language="pt")
    assert search(conn, "capivaras")[1] == 0
    assert coverage(conn)[0] == 0

    _extrair(conn, config)
    assert search(conn, "capivaras")[1] == 0
    assert search(conn, "tamanduas")[1] == 1
    conn.close()


def test_indexar_pendentes_retoma_o_que_ficou_de_fora(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    for n in range(3):
        (origem / f"n{n}.txt").write_text(f"nota {n} sobre jabuticabas", encoding="utf-8")
    _extrair(conn, config)
    conn.execute("DELETE FROM fulltext")
    conn.execute("DELETE FROM fulltext_file")
    conn.commit()
    assert coverage(conn) == (0, 3)

    resultado = index_pending(conn, config, time_budget=-1)
    assert resultado.interrupted and resultado.pending == 3
    resultado = index_pending(conn, config)
    assert (resultado.files, coverage(conn)) == (3, (3, 3))
    assert search(conn, "jabuticaba*")[1] == 3
    conn.close()


# --- tela -----------------------------------------------------------------------------


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


def _projeto_web(cliente, tmp_path):
    origem = tmp_path / "web_origem"
    origem.mkdir()
    (origem / "lei.htm").write_text(
        _lei_html("Regula o uso de <b>drones</b>.", tachado="Art. 39-A. Proibia os drones noturnos."),
        encoding="utf-8",
    )
    saida = tmp_path / "web_saida"
    dados = {
        "name": "Busca web", "subject": "Leis", "source_folder": str(origem), "output_folder": str(saida),
        "collection_type": "biblioteca", "group_mode": "subfolder", "group_pattern": "",
        "extensions": ["pdf", "web_dados"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "0", "chars_per_page": "2000", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "gemma4:e4b", "role_instructions": "", "extra_rules": "",
    }
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    projeto_id = int(resposta.headers["location"].split("/")[2])
    config = load_config({**dados, "extensions": ["pdf", "web_dados"], "chars_per_page": 2000,
                          "pages_per_block": 80, "pages_per_window": 16, "overlap": 0})
    conn = connect(saida / "project.db")
    _extrair(conn, config)
    conn.close()
    return projeto_id


@pytest.mark.parametrize("idioma, titulo, tachado", [
    ("pt", "Buscar no acervo", "tachado no original"),
    ("en", "Search the collection", "struck through in the original"),
    ("es", "Buscar en el acervo", "tachado en el original"),
])
def test_tela_de_busca_mostra_trecho_local_e_tachado(cliente, tmp_path, idioma, titulo, tachado):
    projeto_id = _projeto_web(cliente, tmp_path)
    cliente.cookies.set("language", idioma)

    resposta = cliente.get(f"/projects/{projeto_id}/search", params={"q": "drones"})

    assert resposta.status_code == 200
    assert titulo in resposta.text
    assert "<mark>drones</mark>" in resposta.text or "<mark>Drones</mark>" in resposta.text
    assert tachado in resposta.text
    assert "<del>" in resposta.text
    assert "Art. 40" in resposta.text
    assert "&lt;b&gt;" not in resposta.text  # o HTML do arquivo nunca vaza como marcação


def test_resultado_ruim_escapado_e_links_de_navegacao(cliente, tmp_path):
    projeto_id = _projeto_web(cliente, tmp_path)
    assert f"/projects/{projeto_id}/search" in cliente.get(f"/projects/{projeto_id}/result").text
    resposta = cliente.get(f"/projects/{projeto_id}/search", params={"q": '"<script>'})
    assert resposta.status_code == 200
    assert "<script>" not in resposta.text.split("</header>")[-1].split("<script")[0]


def test_abrir_arquivo_usa_o_caminho_do_banco(cliente, tmp_path, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    abertos = []
    monkeypatch.setattr(app_mod.os, "startfile", lambda caminho: abertos.append(caminho), raising=False)
    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    projeto_id = _projeto_web(cliente, tmp_path)

    resposta = cliente.post(
        f"/projects/{projeto_id}/open-file",
        data={"file_id": "1", "back": "https://exemplo.invalido/"}, follow_redirects=False,
    )
    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/projects/{projeto_id}/search"
    assert len(abertos) == 1 and abertos[0].endswith("lei.htm")

    assert cliente.post(f"/projects/{projeto_id}/open-file", data={"file_id": "999"}).status_code == 404
    assert cliente.post(f"/projects/{projeto_id}/open-file", data={"file_id": "../x"}).status_code == 400
    assert len(abertos) == 1


def test_botao_incluir_os_que_faltam(cliente, tmp_path):
    projeto_id = _projeto_web(cliente, tmp_path)
    saida = tmp_path / "web_saida"
    conn = connect(saida / "project.db")
    conn.execute("DELETE FROM fulltext")
    conn.execute("DELETE FROM fulltext_file")
    conn.commit()
    conn.close()

    tela = cliente.get(f"/projects/{projeto_id}/search", params={"q": "drones"})
    assert "0 de 1" in tela.text or "0 of 1" in tela.text

    resposta = cliente.post(f"/projects/{projeto_id}/search/index", data={"q": "drones"}, follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"].endswith("/search?q=drones")
    assert "<mark>" in cliente.get(resposta.headers["location"]).text


def test_projeto_de_versao_anterior_ganha_a_busca_ao_reabrir(tmp_path):
    """Um project.db da 1.5.0 não tem as tabelas da busca. Reabrir o projeto
    as cria; a atualização do acervo (que apaga da busca) não quebra."""
    from gclaude_indexer.project import create_project, load_project

    origem, config, conn = _projeto(tmp_path)
    conn.close()
    conn, _ = create_project(config)
    (origem / "nota.txt").write_text("Texto sobre mandacarus.", encoding="utf-8")
    _extrair(conn, config)
    conn.execute("DROP TABLE fulltext")
    conn.execute("DROP TABLE fulltext_file")
    conn.commit()
    conn.close()

    _config, conn = load_project(tmp_path / "saida")
    assert coverage(conn) == (0, 1)
    index_pending(conn, config)
    assert search(conn, "mandacaru*")[1] == 1
    conn.close()

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 38 — vários acervos num Project, legislação pesquisável e
documentação para leigos.

"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from gclaude_indexer.artifacts import (
    generate_all_artifacts,
    generate_index_md,
    generate_project_instructions_md,
    group_index_filename,
)
from gclaude_indexer.claude_package import budget, generate_claude_project_package
from gclaude_indexer.config import ProjectConfig, load_config
from gclaude_indexer.db import connect, init_schema

_RAIZ = Path(__file__).resolve().parent.parent


def _config(tmp_path, **extra) -> ProjectConfig:
    return ProjectConfig(name="Acervo", source_folder=".", output_folder=str(tmp_path), **extra)


def _banco(tmp_path, db_name="p.db", arquivos=None):
    """Mesmo esquema da fase 31: um PDF de 4 páginas no grupo `Processo`, um
    `.htm` do Planalto de 1 página no mesmo grupo e um PDF de 2 páginas em
    `Avulsos`."""
    conn = connect(tmp_path / db_name)
    init_schema(conn)
    arquivos = arquivos or [
        ("vol1.pdf", "pdf", "Processo", 4),
        ("lei.htm", "htm", "Processo", 1),
        ("anexo.pdf", "pdf", "Avulsos", 2),
    ]
    for ordem, (nome, ext, grupo, paginas) in enumerate(arquivos, start=1):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key) "
            "VALUES (?, ?, ?, 1, ?, 'extracted', ?)",
            (nome, nome, ext, f"h{ordem}", grupo),
        )
        for numero in range(1, paginas + 1):
            conn.execute(
                "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
                "VALUES (?, ?, ?, 100, 0, 0, 'x')",
                (ordem, numero, f"f. {numero}"),
            )
    conn.commit()
    return conn


def _peca(conn, grupo, inicio, fim, tipo, arquivo, *, engine="local", data="2026-01-01",
          confianca="high", resumo="resumo"):
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
        "type, date, engine, confidence, files, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (grupo, f"f. {inicio}", f"f. {fim}", inicio, fim, tipo, data, engine, confianca, arquivo, resumo),
    )
    conn.commit()


def _acervo_com_lei(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    _peca(conn, "Processo", 5, 5, "LEI", "lei.htm", engine="structured", data="1990-07-11",
          resumo="Lei 8.078 — Código de Defesa do Consumidor")
    _peca(conn, "Avulsos", 1, 2, "OFÍCIO", "anexo.pdf")
    return conn


def _nomes_do_zip(config, idioma="pt") -> list[str]:
    conteudo = generate_claude_project_package(config, idioma)
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        return z.namelist()


def _app_com_projeto(tmp_path, monkeypatch):
    """Servidor de teste com um projeto pronto e um ato do Planalto."""
    from fastapi.testclient import TestClient

    from gclaude_indexer import paths
    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json
    from gclaude_indexer.web.app import app

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _banco(saida, "project.db")
    config = ProjectConfig(name="acervo", source_folder=str(origem), output_folder=str(saida))
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-11-01T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()
    _peca(conn, "Processo", 5, 5, "LEI", "lei.htm", engine="structured")
    entry = register_project(config.name, str(saida))
    return TestClient(app), entry.id, conn, config


# --- Task 1: sai `legislacao-<grupo>.md` e a opção do Planalto no pacote -----


def test_atos_do_planalto_nao_geram_mais_arquivo_de_legislacao(tmp_path):
    """Arquivos `legislacao-<grupo>-*.md` de um acervo grande foram
    recusados pelo claude.ai: "o conhecimento do projeto
    excede o máximo". Um arquivo que nunca pode subir não deve existir."""
    conn = _acervo_com_lei(tmp_path)
    config = _config(tmp_path)

    escritos = generate_all_artifacts(conn, config, "pt")

    assert list(tmp_path.glob("legislacao-*.md")) == []
    assert not any(chave.startswith("legislation:") for chave in escritos)
    indice = (tmp_path / group_index_filename("Processo")).read_text(encoding="utf-8")
    assert "LAUDO" in indice and "Código de Defesa" not in indice, "o ato não voltou para o índice"
    assert "1990-07-11" not in (tmp_path / "timeline.md").read_text(encoding="utf-8")
    assert [e.name for e in budget(config).outside] == [], "nada de legislação fora do pacote"


def test_sumario_conta_as_paginas_do_planalto_e_aponta_para_as_normas_citadas(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")

    sumario = (tmp_path / "index.md").read_text(encoding="utf-8")
    linha = next(l for l in sumario.splitlines() if "**Processo**" in l)
    assert "1 documento(s) do acervo" in linha
    assert "1 página(s) do Planalto" in linha
    assert "legislacao-" not in sumario
    assert "normas-citadas.md" in sumario


def test_legislacao_antiga_e_apagada_na_proxima_geracao(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    velho = tmp_path / "legislacao-Processo.md"
    velho.write_text("velho", encoding="utf-8")

    generate_all_artifacts(conn, _config(tmp_path), "pt")

    assert not velho.exists()


def test_config_antiga_com_planalto_in_package_carrega(tmp_path):
    """Projetos criados até a 1.7.5 gravaram a chave no `config_json`."""
    config = load_config({
        "name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path), "planalto_in_package": True,
    })
    assert not hasattr(config, "planalto_in_package")


def test_instrucoes_avisam_que_a_legislacao_nao_esta_no_projeto(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    texto = generate_project_instructions_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    assert "não estão no conhecimento" in texto
    assert "legislacao-" not in texto


def test_nenhum_texto_fala_mais_do_arquivo_de_legislacao_nem_da_opcao():
    """Nem a interface, nem os guias do pacote, nem os artefatos."""
    from gclaude_indexer import i18n
    from gclaude_indexer.claude_package import _GUIDE

    for idioma, textos in i18n._TRANSLATIONS.items():
        for chave, valor in textos.items():
            assert "planalto_in_package" not in chave, (idioma, chave)
            assert "legislacao-<" not in valor, (idioma, chave)
    rotulos = ('Planalto no pacote"', 'legislation in the package"', 'Planalto en el paquete"')
    for idioma, guia in _GUIDE.items():
        assert "legislacao-" not in guia, idioma
        assert not any(rotulo in guia for rotulo in rotulos), idioma
    for modelo in ("result.html", "new_project.html"):
        html = (_RAIZ / "gclaude_indexer" / "web" / "templates" / modelo).read_text(encoding="utf-8")
        assert "planalto_in_package" not in html, modelo


def test_tela_de_resultado_nao_tem_mais_a_opcao_do_planalto(tmp_path, monkeypatch):
    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    generate_all_artifacts(conn, config, "pt")

    corpo = cliente.get(f"/projects/{projeto_id}/result").text
    assert "planalto_in_package" not in corpo
    resposta = cliente.post(f"/projects/{projeto_id}/package-options", data={}, follow_redirects=False)
    assert resposta.status_code in (404, 405)


# --- Task 2: `normas-citadas.md`, uma linha por ato reconhecido, com link ----


def _acervo_com_duas_normas(tmp_path):
    """Duas normas reconhecidas pelo leitor do Planalto, no formato que o
    `planalto.parse` grava: `TIPO Nº número: ementa`."""
    conn = _banco(tmp_path, arquivos=[
        ("vol1.pdf", "pdf", "Processo", 4),
        ("lei.htm", "htm", "Processo", 1),
        ("decreto.htm", "htm", "Processo", 1),
    ])
    # Posições no grupo seguem a ordem natural dos caminhos: decreto.htm (1),
    # lei.htm (2), vol1.pdf (3 a 6).
    _peca(conn, "Processo", 1, 1, "DECRETO", "decreto.htm", engine="structured", data="1986-11-24",
          resumo="DECRETO Nº 93.618: Aprova o Regulamento de Movimentação para Oficiais da Marinha.")
    _peca(conn, "Processo", 2, 2, "LEI", "lei.htm", engine="structured", data="1993-06-21",
          resumo="LEI Nº 8.666: Regulamenta o art. 37, inciso XXI, da Constituição Federal.")
    _peca(conn, "Processo", 3, 6, "LAUDO", "vol1.pdf")
    return conn


def _linhas_da_tabela(texto: str) -> list[str]:
    linhas = [l for l in texto.splitlines() if l.startswith("| ")]
    return linhas[1:]  # cabeçalho fora (o separador começa com "|-")


def test_normas_citadas_tem_uma_linha_por_ato_com_link(tmp_path):
    from gclaude_indexer.artifacts import NORMS_FILENAME, generate_cited_norms_md

    conn = _acervo_com_duas_normas(tmp_path)
    caminho = generate_cited_norms_md(conn, _config(tmp_path), "pt")

    assert caminho == tmp_path / NORMS_FILENAME == tmp_path / "normas-citadas.md"
    texto = caminho.read_text(encoding="utf-8")
    linhas = _linhas_da_tabela(texto)
    assert len(linhas) == 2
    decreto, lei = linhas  # ordem: tipo, depois data
    assert "DECRETO Nº 93.618" in decreto and "1986-11-24" in decreto
    assert "https://www.lexml.gov.br/urn/urn:lex:br:federal:decreto:1986-11-24;93618" in decreto
    assert "LEI Nº 8.666" in lei and "Regulamenta o art. 37" in lei
    assert "https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:1993-06-21;8666" in lei
    assert "lei.htm (p. 1)" in lei and "Processo" in lei


def test_norma_repetida_em_duas_paginas_aparece_uma_vez_com_as_paginas_somadas(tmp_path):
    from gclaude_indexer.artifacts import generate_cited_norms_md

    conn = _banco(tmp_path, arquivos=[("a.htm", "htm", "G", 1), ("b.htm", "htm", "G", 1)])
    for folha, arquivo in ((1, "a.htm"), (2, "b.htm")):
        _peca(conn, "G", folha, folha, "LEI", arquivo, engine="structured", data="2006-09-15",
              resumo="LEI Nº 11.346: Cria o Sistema Nacional de Segurança Alimentar e Nutricional.")

    texto = generate_cited_norms_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    linhas = _linhas_da_tabela(texto)
    assert len(linhas) == 1
    assert "a.htm (p. 1)" in linhas[0] and "b.htm (p. 1)" in linhas[0]


def test_norma_de_tipo_sem_urn_conhecida_ganha_link_de_busca(tmp_path):
    from gclaude_indexer.artifacts import generate_cited_norms_md

    conn = _banco(tmp_path, arquivos=[("p.htm", "htm", "G", 1)])
    _peca(conn, "G", 1, 1, "PORTARIA", "p.htm", engine="structured", data="2020-03-20",
          resumo="PORTARIA Nº 454: Declara estado de transmissão comunitária.")

    texto = generate_cited_norms_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    assert "https://www.lexml.gov.br/busca/search?keyword=PORTARIA" in texto
    assert "urn:lex" not in texto


def test_sem_ato_nao_ha_arquivo_e_o_antigo_some(tmp_path):
    from gclaude_indexer.artifacts import generate_cited_norms_md

    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    velho = tmp_path / "normas-citadas.md"
    velho.write_text("velho", encoding="utf-8")

    assert generate_cited_norms_md(conn, _config(tmp_path), "pt") is None
    assert not velho.exists()
    assert "normas-citadas" not in generate_project_instructions_md(
        conn, _config(tmp_path), "pt").read_text(encoding="utf-8")


def test_instrucoes_mandam_ler_normas_citadas_e_usar_o_link(tmp_path):
    conn = _acervo_com_duas_normas(tmp_path)
    texto = generate_project_instructions_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    regra = next(l for l in texto.splitlines() if "normas-citadas.md" in l)
    assert "2 página(s)" in regra and "link" in regra
    assert texto.index("normas-citadas.md") < texto.index("## Colunas dos arquivos")


def test_pacote_e_orcamento_levam_normas_citadas(tmp_path):
    conn = _acervo_com_duas_normas(tmp_path)
    config = _config(tmp_path)
    escritos = generate_all_artifacts(conn, config, "pt")

    assert escritos["norms"] == tmp_path / "normas-citadas.md"
    assert "normas-citadas.md" in _nomes_do_zip(config)
    assert "normas-citadas.md" in [e.name for e in budget(config).entries]


def test_guia_e_exclusao_conhecem_normas_citadas():
    from fnmatch import fnmatch

    from gclaude_indexer.claude_package import _GUIDE
    from gclaude_indexer.deletion import GENERATED_FILES

    assert any(fnmatch("normas-citadas.md", padrao) for padrao in GENERATED_FILES)
    for idioma, guia in _GUIDE.items():
        assert "normas-citadas.md" in guia, idioma


# --- Task 3: busca por tema para o Claude Code e LexML ------------------------

_SRU_OK = b"""<?xml version="1.0" encoding="UTF-8"?>
<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:srw_dc="info:srw/schema/1/dc-schema">
<srw:version>1.1</srw:version><srw:numberOfRecords>1</srw:numberOfRecords>
<srw:records><srw:record><srw:recordSchema>info:srw/schema/1/dc-schema</srw:recordSchema><srw:recordData><srw_dc:dc>
<dc:title>Lei n\xc2\xba 11.346, de 15 de Setembro de 2006</dc:title>
<dc:date>2006-09-15</dc:date>
<dc:description>Cria o Sistema Nacional de Seguran\xc3\xa7a Alimentar e Nutricional - SISAN.</dc:description>
<dc:identifier>urn:lex:br:federal:lei:2006-09-15;11346</dc:identifier>
</srw_dc:dc></srw:recordData></srw:record></srw:records></srw:searchRetrieveResponse>"""

_SENADO_CHALLENGE = (
    b"<!DOCTYPE html><html><head><title>Verifica\xc3\xa7\xc3\xa3o de seguran\xc3\xa7a \xe2\x80\x94 Senado Federal"
    b"</title></head><body>Aguarde...</body></html>"
)


def test_lexml_le_registros_do_sru():
    from gclaude_indexer import lexml

    pedidos = []

    def fetch(url, timeout):
        pedidos.append(url)
        return _SRU_OK

    r = lexml.search("saneamento", limit=5, fetch=fetch)
    assert r.status == "ok"
    assert pedidos[0].startswith(lexml.SRU_URL) and "saneamento" in pedidos[0] and "maximumRecords=5" in pedidos[0]
    assert len(r.records) == 1
    registro = r.records[0]
    assert registro.title.startswith("Lei nº 11.346") and registro.date == "2006-09-15"
    assert registro.urn == "urn:lex:br:federal:lei:2006-09-15;11346"
    assert registro.url == "https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2006-09-15;11346"
    assert "SISAN" in registro.description
    assert r.search_url == lexml.search_page_url("saneamento")


def test_lexml_reconhece_a_pagina_de_verificacao():
    """Verificado: o SRU e a página de busca respondem a programas
    com a verificação de segurança do Senado. Não se contorna; avisa-se."""
    from gclaude_indexer import lexml

    r = lexml.search("saneamento", fetch=lambda url, timeout: _SENADO_CHALLENGE)
    assert r.status == "challenge" and r.records == []
    assert r.search_url == "https://www.lexml.gov.br/busca/search?keyword=saneamento"


def test_lexml_sem_rede_nao_quebra():
    from urllib.error import URLError

    from gclaude_indexer import lexml

    def cai(url, timeout):
        raise URLError("sem rede")

    r = lexml.search("x", fetch=cai)
    assert r.status == "offline" and r.records == [] and "keyword=x" in r.search_url


def test_lexml_resposta_inesperada_vira_erro_com_link():
    from gclaude_indexer import lexml

    r = lexml.search("x", fetch=lambda url, timeout: b"isto nao e xml <<<")
    assert r.status == "error" and r.records == [] and r.search_url.endswith("keyword=x")


def _projeto_com_busca(tmp_path, *, texto_lei: str, texto_memorando: str):
    """Projeto com busca indexada: uma lei (reconhecida pelo leitor do
    Planalto) e um memorando, nas pastas `Leis/` e `Memorandos/`."""
    from gclaude_indexer.config import config_to_json, load_config
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.scanning import scan

    origem = tmp_path / "origem"
    (origem / "Leis").mkdir(parents=True)
    (origem / "Memorandos").mkdir()
    (origem / "Leis" / "lei.htm").write_text(
        "<html><body><p>LEI Nº 11.346, DE 15 DE SETEMBRO DE 2006.</p>"
        f"<p>{texto_lei}</p><p>O PRESIDENTE DA REPÚBLICA Faço saber que o Congresso Nacional decreta:</p>"
        "<p>Art. 1º Esta Lei estabelece as definições, princípios e diretrizes do sistema.</p></body></html>",
        encoding="utf-8",
    )
    (origem / "Memorandos" / "memorando.txt").write_text(
        f"MEMORANDO Nº 12/2026\n\nAssunto: {texto_memorando}\n", encoding="utf-8",
    )
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Busca", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["web_dados", "text"], "collection_type": "biblioteca",
        "classification_engine": "rules", "chars_per_page": 2000,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-11-02T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    grupo_lei = conn.execute("SELECT group_key FROM file WHERE name = 'lei.htm'").fetchone()[0]
    grupo_memo = conn.execute("SELECT group_key FROM file WHERE name = 'memorando.txt'").fetchone()[0]
    _peca(conn, grupo_lei, 1, 1, "LEI", "lei.htm", engine="structured", data="2006-09-15",
          resumo="LEI Nº 11.346: Cria o Sistema Nacional de Segurança Alimentar e Nutricional.")
    _peca(conn, grupo_memo, 1, 1, "MEMORANDO", "memorando.txt", data="2026-01-10", resumo="memorando")
    conn.close()
    return saida, grupo_lei, grupo_memo


def _lexml_falso(status="ok"):
    from gclaude_indexer import lexml

    chamadas = []

    def falso(term, limit=10, timeout=10.0, fetch=None):
        chamadas.append(term)
        registros = [lexml.LexmlRecord(
            title="Lei nº 11.346, de 15 de Setembro de 2006", date="2006-09-15",
            description="Cria o SISAN.", urn="urn:lex:br:federal:lei:2006-09-15;11346",
            url="https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2006-09-15;11346",
        )] if status == "ok" else []
        return lexml.LexmlResult(status=status, records=registros, search_url=lexml.search_page_url(term), detail="")

    falso.chamadas = chamadas
    return falso


def test_buscar_lista_paginas_do_acervo_com_trecho_e_link(tmp_path):
    from gclaude_indexer import search_cli

    saida, grupo_lei, grupo_memo = _projeto_com_busca(
        tmp_path, texto_lei="Dispõe sobre a universalização do saneamento básico.",
        texto_memorando="campanha de saneamento nas escolas",
    )
    falso = _lexml_falso()

    texto = search_cli.run(saida, "saneamento", None, False, 20, False, "pt", lexml_search=falso)

    assert "lei.htm" in texto and "memorando.txt" in texto
    assert "**saneamento**" in texto, "o termo aparece destacado no trecho"
    assert "https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2006-09-15;11346" in texto
    assert falso.chamadas == [], "há norma no acervo: o LexML não é consultado sem --lexml"
    assert "LexML" not in texto


def test_buscar_agrupa_os_trechos_por_arquivo(tmp_path):
    """Num acervo grande, uma busca devolveu vários trechos do mesmo decreto antes
    de qualquer outra norma: a pergunta "quais leis tratam de X" quer uma
    linha por norma, com os trechos embaixo."""
    from gclaude_indexer import search_cli

    artigos = "</p><p>".join(
        f"Art. {n}º A universalização do saneamento básico observará a diretriz número {n}. " + "Texto do artigo. " * 40
        for n in (1, 2, 3, 4)
    )
    saida, _, _ = _projeto_com_busca(tmp_path, texto_lei=artigos, texto_memorando="nada a ver")

    texto = search_cli.run(saida, "saneamento", None, False, 20, False, "pt", lexml_search=_lexml_falso())

    assert texto.count("- **lei.htm**") == 1, "uma entrada por arquivo"
    assert texto.count("  > ") >= 2, "os trechos do arquivo ficam embaixo dele"
    assert texto.count("  > ") <= search_cli.EXCERPTS_PER_FILE
    assert "1 arquivo(s)" in texto


def test_buscar_so_legislacao_consulta_o_lexml_quando_nao_acha_norma(tmp_path):
    from gclaude_indexer import search_cli

    saida, grupo_lei, grupo_memo = _projeto_com_busca(
        tmp_path, texto_lei="Dispõe sobre a segurança alimentar.",
        texto_memorando="campanha de saneamento nas escolas",
    )
    falso = _lexml_falso()

    texto = search_cli.run(saida, "saneamento", None, True, 20, False, "pt", lexml_search=falso)

    assert "memorando.txt" not in texto, "--so-legislacao deixa o memorando de fora"
    assert falso.chamadas == ["saneamento"]
    assert "LexML" in texto and "Lei nº 11.346" in texto
    assert "https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2006-09-15;11346" in texto


def test_buscar_com_grupo_e_lexml_em_verificacao(tmp_path):
    from gclaude_indexer import search_cli

    saida, grupo_lei, grupo_memo = _projeto_com_busca(
        tmp_path, texto_lei="Dispõe sobre a universalização do saneamento básico.",
        texto_memorando="campanha de saneamento nas escolas",
    )
    falso = _lexml_falso("challenge")

    texto = search_cli.run(saida, "saneamento", grupo_memo, False, 20, True, "pt", lexml_search=falso)

    assert "memorando.txt" in texto and "lei.htm" not in texto
    assert falso.chamadas == ["saneamento"]
    assert "https://www.lexml.gov.br/busca/search?keyword=saneamento" in texto
    assert "verifica" in texto.lower()


def test_buscar_main_imprime_markdown_e_avisa_pasta_sem_projeto(tmp_path, capsys):
    from gclaude_indexer import search_cli

    saida, _, _ = _projeto_com_busca(
        tmp_path, texto_lei="Dispõe sobre a universalização do saneamento básico.", texto_memorando="nada",
    )
    assert search_cli.main([str(saida), "saneamento", "básico", "--limite", "5", "--idioma", "pt"]) == 0
    assert "lei.htm" in capsys.readouterr().out

    assert search_cli.main([str(tmp_path / "vazia"), "saneamento"]) == 2
    assert "project.db" in capsys.readouterr().err


def test_buscar_bat_aponta_para_o_python_e_o_modulo(tmp_path):
    from gclaude_indexer.artifacts import SEARCH_LAUNCHER_FILENAME, generate_search_launcher

    caminho = generate_search_launcher(_config(tmp_path))

    assert caminho == tmp_path / SEARCH_LAUNCHER_FILENAME == tmp_path / "buscar.bat"
    bat = caminho.read_text(encoding="utf-8")
    assert "-m gclaude_indexer.search_cli" in bat and '"%~dp0."' in bat and "%*" in bat
    assert "python.exe" in bat.lower() and "pythonw" not in bat.lower()
    assert str(_RAIZ) in bat, "a raiz do código, para o módulo ser encontrado"


def test_geracao_escreve_o_buscar_bat_e_a_exclusao_o_conhece(tmp_path):
    from fnmatch import fnmatch

    from gclaude_indexer.deletion import GENERATED_FILES

    conn = _acervo_com_lei(tmp_path)
    escritos = generate_all_artifacts(conn, _config(tmp_path), "pt")
    assert escritos["search_launcher"] == tmp_path / "buscar.bat"
    assert any(fnmatch("buscar.bat", padrao) for padrao in GENERATED_FILES)
    assert "buscar.bat" not in _nomes_do_zip(_config(tmp_path)), "é da pasta, não do Project"


def test_claude_md_ensina_a_buscar_nos_tres_idiomas(tmp_path):
    from gclaude_indexer.windows_prep import generate_claude_md

    for idioma in ("pt", "en", "es"):
        texto = generate_claude_md(_config(tmp_path), idioma).read_text(encoding="utf-8")
        assert "buscar.bat" in texto and "--lexml" in texto and "normas-citadas.md" in texto, idioma


def test_instrucoes_do_projeto_citam_o_buscar_bat(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    texto = generate_project_instructions_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    assert "buscar.bat" in texto


def test_tela_de_busca_consulta_o_lexml_so_quando_pedido(tmp_path, monkeypatch):
    from gclaude_indexer import lexml

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    falso = _lexml_falso("challenge")
    monkeypatch.setattr(lexml, "search", falso)

    sem = cliente.get(f"/projects/{projeto_id}/search", params={"q": "saneamento"}).text
    assert falso.chamadas == []
    assert 'name="lexml"' in sem

    com = cliente.get(f"/projects/{projeto_id}/search", params={"q": "saneamento", "lexml": "1"}).text
    assert falso.chamadas == ["saneamento"]
    assert 'id="lexml-results"' in com
    assert "https://www.lexml.gov.br/busca/search?keyword=saneamento" in com
    assert 'name="lexml" value="1" checked' in com


def test_tela_de_busca_lista_as_normas_do_lexml(tmp_path, monkeypatch):
    from gclaude_indexer import lexml

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(lexml, "search", _lexml_falso("ok"))

    com = cliente.get(f"/projects/{projeto_id}/search", params={"q": "saneamento", "lexml": "1"}).text
    assert "Lei nº 11.346" in com and "urn:lex:br:federal:lei:2006-09-15;11346" in com


# --- Task 4: o orçamento protege: arquivo acima do teto fica fora do pacote ---


def test_arquivo_acima_do_teto_nao_entra_no_zip(tmp_path, monkeypatch):
    """Até a 1.7.5 o pacote levava o arquivo acima de 30 MB e a tela só
    avisava; o envio ao Project o recusa. Agora o arquivo fica fora e a tela
    diz por quê."""
    from gclaude_indexer import claude_package

    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 100)
    (tmp_path / "index.md").write_bytes(b"x" * 50)
    (tmp_path / "timeline.md").write_bytes(b"x" * 150)
    config = _config(tmp_path)

    plano = claude_package.package_plan(config)
    assert [p.name for p in plano.included] == ["index.md"]
    assert [e.name for e in plano.excluded] == ["timeline.md"]
    assert plano.excluded[0].too_big and plano.excluded[0].size_bytes == 150
    assert [p.name for p in claude_package.package_files(config)] == ["index.md"]
    assert "timeline.md" not in _nomes_do_zip(config)


def test_orcamento_lista_os_excluidos_e_nao_os_soma(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 100)
    (tmp_path / "index.md").write_bytes(b"x" * 60)
    (tmp_path / "index-G.md").write_bytes(b"x" * 300)

    orcamento = claude_package.budget(_config(tmp_path))
    assert [e.name for e in orcamento.entries] == ["index.md"]
    assert [e.name for e in orcamento.excluded] == ["index-G.md"]
    assert orcamento.total_tokens == 20
    assert all(not e.too_big for e in orcamento.entries)


def test_tela_de_resultado_mostra_os_excluidos_em_vermelho(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    generate_all_artifacts(conn, config, "pt")
    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 10)

    corpo = cliente.get(f"/projects/{projeto_id}/result").text

    assert 'id="package-excluded"' in corpo
    bloco = corpo[corpo.index('id="package-excluded"'):]
    assert "budget-excluded" in bloco and "index.md" in bloco and "30 MB" in bloco
    assert 'data-budget-level="' in corpo
    assert "ficou fora" in bloco or "fora do pacote" in bloco


def test_guia_do_pacote_fala_do_que_ficou_de_fora():
    from gclaude_indexer.claude_package import _GUIDE

    for idioma, guia in _GUIDE.items():
        assert "30 MB" in guia, idioma
        assert any(p in guia for p in ("ficou fora", "ficaram fora", "left out", "stays out", "quedó fuera", "quedaron fuera")), idioma


# --- Task 5: conjuntos de acervos e pacote combinado --------------------------


def _projeto_pronto(tmp_path, nome: str, pasta: str, *, grupo="Processo", papel="", regras="", volumes=1):
    """Um projeto real na pasta `pasta`: banco, linha em `project`, uma peça
    e os relatórios gerados. Os dois projetos de cada teste têm o mesmo
    grupo para que `index-Processo.md` colida sem o prefixo. Com `volumes`
    acima de 1 há um PDF a mais por volume no mesmo grupo: é o que faz o
    índice sair em partes quando `INDEX_PART_BYTES` é rebaixado."""
    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json

    origem = tmp_path / f"origem-{pasta}"
    origem.mkdir()
    saida = tmp_path / pasta
    saida.mkdir()
    extras = [(f"vol{n}.pdf", "pdf", grupo, 3) for n in range(2, volumes + 1)]
    conn = _banco(saida, "project.db", arquivos=[("vol1.pdf", "pdf", grupo, 4), ("lei.htm", "htm", grupo, 1), *extras])
    config = ProjectConfig(
        name=nome, source_folder=str(origem), output_folder=str(saida), subject=f"Assunto de {nome}",
        role_instructions=papel, extra_rules=regras,
    )
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-11-01T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()
    _peca(conn, grupo, 1, 4, "LAUDO", "vol1.pdf")
    _peca(conn, grupo, 5, 5, "LEI", "lei.htm", engine="structured", data="1990-07-11",
          resumo="LEI Nº 8.078: Código de Defesa do Consumidor")
    for n, (arquivo, _ext, _grupo, _paginas) in enumerate(extras):
        folha = 6 + 3 * n
        _peca(conn, grupo, folha, folha + 2, "OFÍCIO", arquivo, resumo="ofício " + "x" * 120)
    generate_all_artifacts(conn, config, "pt")
    conn.close()
    return register_project(nome, str(saida))


def _dois_projetos(tmp_path, monkeypatch, *, volumes=1):
    """Dois projetos de mesmo nome e mesmo grupo: o caso em que todo nome
    colide. Catálogo, conjuntos e preferências ficam na pasta local de teste."""
    from gclaude_indexer import paths

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))
    a = _projeto_pronto(tmp_path, "Atas", "saida-a", papel="Você responde sobre atas.", regras="Cite a data da sessão.",
                        volumes=volumes)
    b = _projeto_pronto(tmp_path, "Atas", "saida-b")
    return a, b


def _conjunto_de_dois(tmp_path, monkeypatch, *, texto_pessoal="Fale sempre em português.", volumes=1):
    from gclaude_indexer.sets import SetEntry, SetMember, save_set

    a, b = _dois_projetos(tmp_path, monkeypatch, volumes=volumes)
    entry = save_set(SetEntry(
        id=0, name="Conselho", personal_instructions=texto_pessoal,
        members=[SetMember(project_id=a.id, alias="atas"), SetMember(project_id=b.id, alias="atas")],
    ))
    return entry, a, b


def _zip_combinado(entry, idioma="pt") -> dict[str, bytes]:
    from gclaude_indexer.combined_package import generate_zip

    with zipfile.ZipFile(io.BytesIO(generate_zip(entry, idioma))) as z:
        return {nome: z.read(nome) for nome in z.namelist()}


def _nomes_citados(texto: str) -> set[str]:
    """Todo `arquivo.md` citado entre crases ou em link Markdown."""
    import re

    return set(re.findall(r"`([^`\s]+\.md)`", texto)) | set(re.findall(r"\]\(([^)\s]+\.md)\)", texto))


def test_apelido_proposto_e_seguro_e_unico():
    from gclaude_indexer.sets import propose_alias

    assert propose_alias("Diretoria / Região Sul", set()) == "diretoria-regiao-sul"
    assert propose_alias("  Atas  2024 ", set()) == "atas-2024"
    assert propose_alias("***", set()) == "acervo"
    assert propose_alias("Atas", {"atas"}) == "atas-2"
    assert propose_alias("Atas", {"atas", "atas-2"}) == "atas-3"
    assert propose_alias("RH", set()) == "rh"


def test_conjunto_e_gravado_e_lido_no_catalogo_local(tmp_path, monkeypatch):
    from gclaude_indexer import paths
    from gclaude_indexer.sets import SetEntry, SetMember, find_set, list_sets, remove_set, save_set

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))
    assert list_sets() == []

    gravado = save_set(SetEntry(id=0, name="Conselho", personal_instructions="Texto meu",
                                members=[SetMember(1, "atas"), SetMember(2, "oficios")]))
    assert gravado.id == 1 and gravado.created_at
    assert (tmp_path / "local" / "sets.json").exists()

    lido = find_set(1)
    assert lido == gravado
    assert [m.alias for m in lido.members] == ["atas", "oficios"]

    gravado.name = "Conselho 2026"
    save_set(gravado)
    assert [s.name for s in list_sets()] == ["Conselho 2026"]

    segundo = save_set(SetEntry(id=0, name="Outro", members=[SetMember(1, "atas")]))
    assert segundo.id == 2
    remove_set(1)
    assert [s.id for s in list_sets()] == [2]
    assert find_set(1) is None


def test_pacote_combinado_nao_repete_nomes_e_todo_link_existe(tmp_path, monkeypatch):
    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)

    arquivos = _zip_combinado(entry)
    nomes = list(arquivos)

    assert len(nomes) == len(set(nomes))
    assert "HOW_TO_USE.md" in nomes and nomes.count("project_instructions.md") == 1
    # Dois projetos de mesmo nome: o segundo apelido foi desempatado.
    assert "atas__index.md" in nomes and "atas-2__index.md" in nomes
    assert "atas__index-Processo.md" in nomes and "atas-2__index-Processo.md" in nomes
    assert "atas__normas-citadas.md" in nomes
    assert not any(n.startswith("index") or n.startswith("timeline") for n in nomes)
    for nome in nomes:
        if nome.endswith("__index.md"):
            citados = _nomes_citados(arquivos[nome].decode("utf-8"))
            assert citados, nome
            assert citados <= set(nomes), (nome, citados - set(nomes))


def test_instrucoes_combinadas_comecam_com_o_texto_pessoal_e_tem_uma_secao_por_acervo(tmp_path, monkeypatch):
    from gclaude_indexer.artifacts import SOURCE_OF_TRUTH_RULE
    from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch, texto_pessoal="Fale sempre em português.")
    texto = _zip_combinado(entry)["project_instructions.md"].decode("utf-8")

    assert texto.startswith("Fale sempre em português.")
    assert texto.index("Fale sempre em português.") < texto.index(BEGIN_MARK)
    bloco = texto[texto.index(BEGIN_MARK):texto.index(END_MARK)]
    assert bloco.count(SOURCE_OF_TRUTH_RULE) == 1
    assert "Em qual acervo procurar" in bloco
    assert bloco.count("atas__index.md") >= 1 and bloco.count("atas-2__index.md") >= 1
    assert "Você responde sobre atas." in bloco and "Cite a data da sessão." in bloco
    # Só nomes prefixados: nenhum `index…`, `timeline…`, `review.md` ou
    # `normas-citadas.md` sem apelido, nem nos padrões `index-<grupo>.md`.
    for citado in _nomes_citados(bloco):
        if citado.startswith("-"):  # `-2.md`, fragmento do padrão das partes
            continue
        assert "__" in citado, citado
    assert "`index-<grupo>.md`" not in bloco and "`timeline.md`" not in bloco


def test_regenerar_preserva_o_texto_pessoal(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import write_folder
    from gclaude_indexer.managed_block import BEGIN_MARK

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch, texto_pessoal="Texto pessoal v1")
    pasta = tmp_path / "combinada"
    write_folder(entry, pasta, "pt")
    instrucoes = pasta / "project_instructions.md"
    primeiro = instrucoes.read_text(encoding="utf-8")
    assert primeiro.startswith("Texto pessoal v1")

    instrucoes.write_text(
        primeiro.replace("Texto pessoal v1", "Texto pessoal v1\n\nLinha minha, editada na pasta."), encoding="utf-8",
    )
    entry.personal_instructions = "Texto pessoal v2"
    write_folder(entry, pasta, "pt")

    segundo = instrucoes.read_text(encoding="utf-8")
    assert segundo.startswith("Texto pessoal v1")
    assert "Linha minha, editada na pasta." in segundo
    assert segundo.count(BEGIN_MARK) == 1
    # Num pacote novo (sem arquivo anterior) vale o texto atual do conjunto.
    assert _zip_combinado(entry)["project_instructions.md"].decode("utf-8").startswith("Texto pessoal v2")


def test_membro_indisponivel_fica_fora_e_e_explicado(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import load_members, plan

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    Path(b.output_folder).rename(tmp_path / "fora-do-ar")

    membros = load_members(entry, "pt")
    assert [m.available for m in membros] == [True, False]
    assert membros[1].reason and membros[1].config is None

    plano = plan(entry, "pt")
    assert [m.member.project_id for m in plano.unavailable] == [b.id]
    assert all(f.arcname.startswith("atas__") for f in plano.files)
    assert plano.total_tokens > 0 and plano.level == "ok"

    arquivos = _zip_combinado(entry)
    assert not any(n.startswith("atas-2__") for n in arquivos)
    guia = arquivos["HOW_TO_USE.md"].decode("utf-8")
    assert "atas-2" in guia and membros[1].reason in guia


def test_reescrita_de_links_nao_toca_texto_parecido():
    from gclaude_indexer.combined_package import prefixed_name, rewrite_links

    nomes = {"index-Atas.md": prefixed_name("x", "index-Atas.md"), "index.md": "x__index.md"}
    texto = (
        "Veja `index-Atas.md` e [o sumário](index.md); também `index-Atas.md.bak`, "
        "`meu-index-Atas.md`, index-Atas.md sem crase, `index-Atas.md`."
    )
    assert rewrite_links(texto, nomes) == (
        "Veja `x__index-Atas.md` e [o sumário](x__index.md); também `index-Atas.md.bak`, "
        "`meu-index-Atas.md`, index-Atas.md sem crase, `x__index-Atas.md`."
    )
    assert prefixed_name("atas-2", "timeline.md") == "atas-2__timeline.md"


def test_gravar_numa_pasta_escreve_claude_md_combinado(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import write_folder
    from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    pasta = tmp_path / "combinada"
    pasta.mkdir()
    (pasta / "CLAUDE.md").write_text("# Regras minhas\n\nNunca apague nada.\n", encoding="utf-8")

    escritos = write_folder(entry, pasta, "pt")

    nomes = {p.name for p in escritos}
    assert {"CLAUDE.md", "project_instructions.md", "atas__index.md", "atas-2__index.md"} <= nomes
    assert all(p.exists() for p in escritos)
    claude_md = (pasta / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.startswith("# Regras minhas")
    assert "Nunca apague nada." in claude_md
    bloco = claude_md[claude_md.index(BEGIN_MARK):claude_md.index(END_MARK)]
    assert "atas__index.md" in bloco and "atas-2__index.md" in bloco
    assert a.output_folder in bloco  # onde fica o buscar.bat daquele acervo


# --- Task 6: tela Conjuntos ------------------------------------------------------


def _cliente_web():
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app, lock_manager

    lock_manager.close_all()
    return TestClient(app)


def _formulario_do_conjunto(a, b, nome="Conselho", **extras):
    dados = {
        "name": nome, "personal_instructions": "Fale sempre em português.",
        f"project_{a.id}": "1", f"alias_{a.id}": "Atas do Plenário",
        f"project_{b.id}": "1", f"alias_{b.id}": "atas",
    }
    dados.update(extras)
    return dados


def test_tela_de_conjuntos_lista_e_cria(tmp_path, monkeypatch):
    a, b = _dois_projetos(tmp_path, monkeypatch)
    cliente = _cliente_web()

    vazia = cliente.get("/sets").text
    assert 'href="/sets/new"' in vazia
    assert 'href="/sets"' in cliente.get("/projects").text  # link no menu e atalho

    formulario = cliente.get("/sets/new").text
    assert f'name="project_{a.id}"' in formulario and f'name="alias_{b.id}"' in formulario

    resposta = cliente.post("/sets/new", data=_formulario_do_conjunto(a, b), follow_redirects=False)
    assert resposta.status_code == 303 and resposta.headers["location"] == "/sets/1"

    lista = cliente.get("/sets").text
    assert "Conselho" in lista and 'href="/sets/1"' in lista

    tela = cliente.get("/sets/1").text
    # Apelido proposto do nome, e o repetido desempatado.
    assert 'value="atas-do-plenario"' in tela and 'value="atas"' in tela
    assert "Fale sempre em português." in tela
    assert 'href="/sets/1/package"' in tela and 'action="/sets/1/write-folder"' in tela

    # Nome vazio ou um acervo só não grava.
    erro = cliente.post("/sets/new", data=_formulario_do_conjunto(a, b, nome="  "))
    assert erro.status_code == 400 and 'class="errors"' in erro.text
    so_um = _formulario_do_conjunto(a, b)
    del so_um[f"project_{b.id}"]
    assert cliente.post("/sets/new", data=so_um).status_code == 400
    assert len(cliente.get("/sets").text.split('href="/sets/1"')) == 2


def test_projeto_sem_artefatos_aparece_desabilitado_com_motivo(tmp_path, monkeypatch):
    from gclaude_indexer.catalog import register_project

    a, b = _dois_projetos(tmp_path, monkeypatch)
    sem_relatorios = tmp_path / "saida-c"
    sem_relatorios.mkdir()
    _banco(sem_relatorios, "project.db")
    c = register_project("Sem relatórios", str(sem_relatorios))
    fora_do_ar = register_project("Noutro computador", str(tmp_path / "nao-existe"))

    formulario = _cliente_web().get("/sets/new").text

    def campo(projeto):
        inicio = formulario.index(f'name="project_{projeto.id}"')
        return formulario[formulario.rindex("<input", 0, inicio):formulario.index(">", inicio)]

    assert "disabled" in campo(c) and "disabled" in campo(fora_do_ar)
    assert "disabled" not in campo(a) and "disabled" not in campo(b)
    assert "ainda não gerou os relatórios" in formulario
    assert "não está acessível neste computador" in formulario


def test_baixar_pacote_combinado_devolve_zip(tmp_path, monkeypatch):
    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    cliente = _cliente_web()

    resposta = cliente.get(f"/sets/{entry.id}/package")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/zip"
    assert "claude_project_Conselho.zip" in resposta.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resposta.content)) as z:
        nomes = z.namelist()
    assert "atas__index.md" in nomes and "atas-2__index.md" in nomes and "project_instructions.md" in nomes
    assert cliente.get("/sets/999/package").status_code == 404


def test_orcamento_somado_aparece_na_tela(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package
    from gclaude_indexer.combined_package import plan

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    cliente = _cliente_web()
    plano = plan(entry, "pt")

    tela = cliente.get(f"/sets/{entry.id}").text
    assert 'id="set-budget"' in tela and f'data-budget-level="{plano.level}"' in tela
    total = "{:,}".format(plano.total_tokens).replace(",", ".")
    assert total in tela
    assert "atas__index.md" in tela and "atas-2__index.md" in tela

    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 10)
    tela = cliente.get(f"/sets/{entry.id}").text
    bloco = tela[tela.index('id="set-excluded"'):]
    assert "atas__index.md" in bloco and "atas-2__index.md" in bloco and "30 MB" in bloco

    Path(b.output_folder).rename(tmp_path / "fora-do-ar")
    tela = cliente.get(f"/sets/{entry.id}").text
    bloco = tela[tela.index('id="set-unavailable"'):]
    assert "atas-2" in bloco and "não está acessível neste computador" in bloco


def test_gravar_numa_pasta_e_apagar_pela_tela(tmp_path, monkeypatch):
    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    cliente = _cliente_web()
    destino = tmp_path / "pasta-combinada"

    resposta = cliente.post(f"/sets/{entry.id}/write-folder", data={"target_folder": str(destino)}, follow_redirects=False)
    assert resposta.status_code == 303
    assert (destino / "CLAUDE.md").exists() and (destino / "atas__index.md").exists()
    assert str(destino) in cliente.get(resposta.headers["location"]).text

    sem_pasta = cliente.post(f"/sets/{entry.id}/write-folder", data={"target_folder": ""})
    assert sem_pasta.status_code == 400

    apagar = cliente.post(f"/sets/{entry.id}/delete", follow_redirects=False)
    assert apagar.status_code == 303 and apagar.headers["location"] == "/sets"
    assert cliente.get(f"/sets/{entry.id}").status_code == 404
    assert (destino / "CLAUDE.md").exists()  # apagar o conjunto não toca em arquivo


def test_textos_da_tela_nos_tres_idiomas(tmp_path, monkeypatch):
    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    cliente = _cliente_web()
    esperados = {
        "pt": ("Conjuntos", "Novo conjunto", "Apelido"),
        "en": ("Sets", "New set", "Alias"),
        "es": ("Conjuntos", "Nuevo conjunto", "Alias"),
    }
    for idioma, palavras in esperados.items():
        cliente.cookies.set("language", idioma)
        lista = cliente.get("/sets").text
        tela = cliente.get(f"/sets/{entry.id}").text
        assert palavras[0] in lista and palavras[1] in lista, idioma
        assert palavras[2] in tela, idioma


# --- Revisão independente (parte A): correções ----------------------------------


def _nomes_entre_crases(texto: str) -> set[str]:
    """Todo `arquivo.md` dentro de crases, mesmo quando a crase traz dois
    nomes (`index-G-1.md … index-G-3.md`, o rótulo do índice em partes)."""
    import re

    nomes = set()
    for span in re.findall(r"`([^`]+)`", texto):
        nomes |= {token for token in span.split() if token.endswith(".md")}
    return nomes | set(re.findall(r"\]\(([^)\s]+\.md)\)", texto))


def test_reescrita_de_links_alcanca_o_rotulo_do_indice_em_partes():
    from gclaude_indexer.combined_package import rewrite_links

    nomes = {"index-G-1.md": "a__index-G-1.md", "index-G-3.md": "a__index-G-3.md", "index.md": "a__index.md"}
    texto = "- **G** — 9 folhas — `index-G-1.md … index-G-3.md`; veja `index-G-1.md.bak` e `meu-index.md`."
    assert rewrite_links(texto, nomes) == (
        "- **G** — 9 folhas — `a__index-G-1.md … a__index-G-3.md`; veja `index-G-1.md.bak` e `meu-index.md`."
    )


def test_sumario_combinado_de_indice_em_partes_aponta_para_arquivos_do_zip(tmp_path, monkeypatch):
    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 300)
    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch, volumes=3)
    assert (Path(a.output_folder) / "index-Processo-1.md").exists(), "o cenário precisa de um índice em partes"

    arquivos = _zip_combinado(entry)
    citados = _nomes_entre_crases(arquivos["atas__index.md"].decode("utf-8"))
    assert "atas__index-Processo-1.md" in citados
    faltando = {n for n in citados if n not in arquivos and not n.startswith("-")}
    assert not faltando, faltando


def test_salvar_o_conjunto_mantem_o_membro_que_esta_fora_do_ar(tmp_path, monkeypatch):
    from gclaude_indexer.sets import find_set

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    Path(b.output_folder).rename(tmp_path / "fora-do-ar")
    cliente = _cliente_web()

    # O navegador não envia controle desabilitado: o formulário chega só com o membro disponível.
    dados = {"name": "Conselho", "personal_instructions": "Novo texto.", f"project_{a.id}": "1", f"alias_{a.id}": "atas"}
    resposta = cliente.post(f"/sets/{entry.id}", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text

    salvo = find_set(entry.id)
    assert salvo.personal_instructions == "Novo texto."
    assert {(m.project_id, m.alias) for m in salvo.members} == {(a.id, "atas"), (b.id, "atas-2")}


def test_gravar_na_pasta_de_um_acervo_e_recusado(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import write_folder

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    saida = Path(a.output_folder)
    antes = (saida / "project_instructions.md").read_bytes()

    with pytest.raises(ValueError):
        write_folder(entry, saida, "pt")
    with pytest.raises(ValueError):
        write_folder(entry, Path(a.output_folder).parent / "origem-saida-a", "pt")

    cliente = _cliente_web()
    resposta = cliente.post(f"/sets/{entry.id}/write-folder", data={"target_folder": str(saida)})
    assert resposta.status_code == 400
    assert "pasta de um acervo" in resposta.text
    assert (saida / "project_instructions.md").read_bytes() == antes
    assert not (saida / "atas-2__index.md").exists()


def test_regravar_apaga_os_arquivos_prefixados_que_sairam(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import write_folder
    from gclaude_indexer.sets import SetMember, save_set

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    pasta = tmp_path / "combinada"
    write_folder(entry, pasta, "pt")
    (pasta / "notas.md").write_text("minhas notas\n", encoding="utf-8")
    assert (pasta / "atas-2__index.md").exists()

    entry.members = [SetMember(project_id=a.id, alias="atas"), SetMember(project_id=b.id, alias="oficios")]
    save_set(entry)
    write_folder(entry, pasta, "pt")

    restantes = {p.name for p in pasta.iterdir()}
    assert "oficios__index.md" in restantes and "atas__index.md" in restantes
    assert not any(n.startswith("atas-2__") for n in restantes), restantes
    assert {"notas.md", "CLAUDE.md", "project_instructions.md"} <= restantes


def test_lexml_nao_confunde_uma_ementa_com_a_pagina_de_verificacao():
    from gclaude_indexer import lexml

    corpo = _SRU_OK.replace(
        b"Cria o Sistema Nacional", b"Exige verifica\xc3\xa7\xc3\xa3o de seguran\xc3\xa7a peri\xc3\xb3dica e cria o Sistema Nacional"
    )
    r = lexml.search("segurança", fetch=lambda url, timeout: corpo)
    assert r.status == "ok" and len(r.records) == 1
    assert lexml.search("x", fetch=lambda url, timeout: _SENADO_CHALLENGE).status == "challenge"


def test_resumo_de_ato_revogado_sem_ementa_volta_as_partes():
    from gclaude_indexer.artifacts import _split_norm_summary

    assert _split_norm_summary("LEI Nº 8.666 (Revogada pela Lei nº 14.133, de 2021)", "LEI") == ("LEI", "8.666", "")
    kind, number, ementa = _split_norm_summary("LEI Nº 8.078: Código de Defesa do Consumidor (Revogada pela X)", "LEI")
    assert (kind, number) == ("LEI", "8.078") and ementa.startswith("Código de Defesa")
    assert _split_norm_summary("DECRETO: Dispõe sobre algo", "DECRETO") == ("DECRETO", None, "Dispõe sobre algo")
    assert _split_norm_summary("MEDIDA PROVISÓRIA Nº 1.000", None) == ("MEDIDA PROVISÓRIA", "1.000", "")

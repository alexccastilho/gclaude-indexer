# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.10.3: a document changed between two runs of the Execution screen.

The scan used to send it back to 'discovered' without deleting its pages,
and the next extraction stopped on `UNIQUE constraint failed: page.file_id,
page.number`. Only the "Update" button discarded pages, search passages and
windows. The scan step now applies the same invalidation to what changed
(never to what was removed: that still needs the person's confirmation),
and a database already left in the broken state is repaired.
"""

from __future__ import annotations

import os

from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.fulltext import search
from gclaude_indexer.scanning import scan
from gclaude_indexer.web.background_runs import _STEP_FUNCTIONS


def _projeto(tmp_path):
    origem = tmp_path / "origem"
    (origem / "pasta").mkdir(parents=True)
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Alterados",
        "source_folder": str(origem),
        "output_folder": str(saida),
        "extensions": ["text"],
        "collection_type": "biblioteca",
        "classification_engine": "rules",
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, config, conn


def _gravar(caminho, texto, deslocamento=0):
    caminho.write_text(texto, encoding="utf-8")
    if deslocamento:
        instante = caminho.stat().st_mtime + deslocamento
        os.utime(caminho, (instante, instante))


def _etapa(nome, conn, config):
    _STEP_FUNCTIONS[nome](conn, config, None, None)


def _executar(conn, config, ate="extraction"):
    for nome in ("scan", "conversion", "extraction", "windows"):
        _etapa(nome, conn, config)
        if nome == ate:
            break


def _texto(conn, nome):
    return [tuple(row) for row in conn.execute(
        "SELECT page.text FROM page JOIN file ON file.id = page.file_id WHERE file.name = ?",
        (nome,),
    )]


def test_documento_alterado_entre_execucoes_nao_quebra_a_extracao(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _gravar(origem / "pasta" / "a.txt", "Ofício sobre a cobrança de anuidades.")
    _gravar(origem / "pasta" / "b.txt", "Memorando sobre o calendário de reuniões.")
    _executar(conn, config, ate="windows")
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] > 0

    _gravar(origem / "pasta" / "a.txt", "Ofício sobre a renovação do convênio.", deslocamento=10)
    _executar(conn, config, ate="extraction")

    assert _texto(conn, "a.txt") == [("Ofício sobre a renovação do convênio.",)]
    assert search(conn, "convênio")[1] == 1
    assert search(conn, "anuidades")[1] == 0
    estados = dict(conn.execute("SELECT name, status FROM file").fetchall())
    assert estados == {"a.txt": "extracted", "b.txt": "extracted"}


def test_janelas_do_grupo_alterado_sao_descartadas(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _gravar(origem / "pasta" / "a.txt", "Primeira versão do parecer.")
    _executar(conn, config, ate="windows")
    antes = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
    assert antes > 0

    _gravar(origem / "pasta" / "a.txt", "Segunda versão do parecer.", deslocamento=10)
    _etapa("scan", conn, config)

    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0


def test_banco_ja_quebrado_pela_versao_anterior_e_reparado(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _gravar(origem / "pasta" / "a.txt", "Ata da reunião ordinária.")
    _executar(conn, config)

    # What 1.10.2 did: the bare scan resets the row and keeps the pages.
    _gravar(origem / "pasta" / "a.txt", "Ata da reunião extraordinária.", deslocamento=10)
    scan(conn, config)
    convert(conn, config)
    assert conn.execute(
        "SELECT status FROM file WHERE name = 'a.txt'"
    ).fetchone()[0] == "converted"
    assert _texto(conn, "a.txt") == [("Ata da reunião ordinária.",)]

    # "Continue" starts at the extraction: it must not stop on the old pages.
    _etapa("extraction", conn, config)
    # And the next full run reads the new content.
    _executar(conn, config)

    assert _texto(conn, "a.txt") == [("Ata da reunião extraordinária.",)]
    assert search(conn, "extraordinária")[1] == 1


def test_documento_removido_continua_pedindo_confirmacao(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _gravar(origem / "pasta" / "a.txt", "Portaria de nomeação.")
    _gravar(origem / "pasta" / "b.txt", "Portaria de exoneração.")
    _executar(conn, config)

    (origem / "pasta" / "b.txt").unlink()
    _executar(conn, config)

    assert _texto(conn, "b.txt") == [("Portaria de exoneração.",)]
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0


def _projeto_janelas_pequenas(tmp_path, nomes):
    origem, config, conn = _projeto(tmp_path)
    from dataclasses import replace

    config = replace(config, pages_per_window=2, overlap=0)
    for nome in nomes:
        _gravar(origem / "pasta" / nome, f"Conteúdo original de {nome}.")
    _executar(conn, config, ate="windows")
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    return origem, config, conn


def test_documento_de_uma_pagina_alterado_nao_renumera_o_resto_do_grupo(tmp_path):
    """1.10.4: an HTML or text document is always one page. Changing it
    in place shifts nothing after it, so only the windows holding its
    page go back to the model. 1.10.3 renumbered every later file of the
    group and discarded every later window — on a large legislation
    folder, a hundred thousand files read again for a few changed acts."""
    nomes = [f"{n:02d}.txt" for n in range(1, 9)]  # 8 pages, 4 windows of 2
    origem, config, conn = _projeto_janelas_pequenas(tmp_path, nomes)
    janelas_antes = {row[0] for row in conn.execute("SELECT key FROM window")}
    assert len(janelas_antes) == 4

    _gravar(origem / "pasta" / "03.txt", "Conteúdo novo do terceiro.", deslocamento=10)
    _etapa("scan", conn, config)

    # Only the window of pages 3–4 left; the others are still classified.
    restantes = {row[0] for row in conn.execute("SELECT key FROM window WHERE status = 'done'")}
    assert len(restantes) == 3
    assert len(janelas_antes - restantes) == 1
    # Nobody after it lost its pages.
    estados = dict(conn.execute("SELECT name, status FROM file").fetchall())
    assert estados.pop("03.txt") == "discovered"
    assert set(estados.values()) == {"extracted"}

    _executar(conn, config, ate="windows")
    assert _texto(conn, "03.txt") == [("Conteúdo novo do terceiro.",)]
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0] == 1


def test_documento_novo_no_meio_do_grupo_continua_renumerando(tmp_path):
    nomes = ["01.txt", "02.txt", "04.txt", "05.txt"]
    origem, config, conn = _projeto_janelas_pequenas(tmp_path, nomes)

    _gravar(origem / "pasta" / "03.txt", "Documento que entrou no meio.")
    _gravar(origem / "pasta" / "01.txt", "Primeiro alterado.", deslocamento=10)
    _etapa("scan", conn, config)

    # A new file shifts everything after it: the old rule still applies.
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'done'").fetchone()[0] == 0
    estados = dict(conn.execute("SELECT name, status FROM file").fetchall())
    assert estados["04.txt"] != "extracted" and estados["05.txt"] != "extracted"


def test_primeira_execucao_nao_registra_atualizacao(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _gravar(origem / "pasta" / "a.txt", "Resolução inicial.")
    _executar(conn, config)

    assert conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.update.applied'"
    ).fetchone()[0] == 0

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Tests for Phase 17: incremental re-indexing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from gclaude_indexer import db
from gclaude_indexer.paths import natural_sort_key
from gclaude_indexer.windows_prep import pages_for_group


def _conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "project.db")
    db.init_schema(connection)
    return connection


def test_a_tabela_de_removidos_e_a_coluna_mtime_nascem_na_abertura(tmp_path):
    conn = _conn(tmp_path)

    tabelas = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "removed_file" in tabelas

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas


def test_abrir_o_projeto_duas_vezes_nao_duplica_a_coluna(tmp_path):
    conn = _conn(tmp_path)
    db.init_schema(conn)  # não pode levantar "duplicate column name"

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(file)")]
    assert colunas.count("mtime") == 1


def test_um_projeto_da_1_0_1_ganha_a_coluna_na_primeira_abertura(tmp_path):
    """Simula o banco antigo: tabela `file` sem `mtime`."""
    conn = db.connect(tmp_path / "project.db")
    conn.execute(
        "CREATE TABLE file (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL,"
        " sha256 TEXT NOT NULL, group_key TEXT, page_count INTEGER,"
        " needs_ocr INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT)"
    )
    conn.commit()

    db.init_schema(conn)

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas


def test_o_caminhamento_ignora_lixo_de_sistema_e_a_pasta_de_saida(tmp_path):
    from gclaude_indexer.scanning import source_files

    origem = tmp_path / "origem"
    saida = origem / "saida"
    (origem / "sub").mkdir(parents=True)
    saida.mkdir()

    (origem / "b.pdf").write_text("b", encoding="utf-8")
    (origem / "A.pdf").write_text("a", encoding="utf-8")
    (origem / "sub" / "c.pdf").write_text("c", encoding="utf-8")
    (origem / "desktop.ini").write_text("lixo", encoding="utf-8")
    (saida / "index.md").write_text("gerado", encoding="utf-8")

    encontrados = [p.relative_to(origem).as_posix() for p in source_files(origem, saida)]

    assert encontrados == ["A.pdf", "b.pdf", "sub/c.pdf"]


def test_quinhentas_paginas_dao_trinta_e_seis_janelas():
    from gclaude_indexer.windows_prep import window_key, window_spans

    spans = window_spans(500, 16, 2)

    assert len(spans) == 36
    assert spans[0] == (0, 16)
    assert spans[-1] == (490, 500)


def test_dez_paginas_no_fim_mudam_so_a_cauda():
    from gclaude_indexer.windows_prep import window_spans

    antes = window_spans(500, 16, 2)
    depois = window_spans(510, 16, 2)

    assert antes[:35] == depois[:35]      # 35 janelas idênticas
    assert antes[35] == (490, 500)        # a última de antes
    assert depois[35] == (490, 506)       # mudou: cobre 6 páginas novas
    assert depois[36] == (504, 510)       # e nasceu uma
    assert len(depois) == 37


def test_a_chave_da_janela_e_posicional_e_com_zeros_a_esquerda():
    from gclaude_indexer.windows_prep import window_key

    assert window_key("processo", 490, 500) == "processo::000491-000500"


def test_acervo_vazio_nao_gera_janela():
    from gclaude_indexer.windows_prep import window_spans

    assert window_spans(0, 16, 2) == []


def test_sobreposicao_maior_que_a_janela_nao_trava():
    """Passo zero ou negativo faria laço infinito. O piso de 1 impede."""
    from gclaude_indexer.windows_prep import window_spans

    spans = window_spans(10, 4, 9)

    assert len(spans) <= 10
    assert spans[-1][1] == 10


def test_a_ordem_natural_poe_o_dez_depois_do_dois():
    nomes = ["doc10.pdf", "doc2.pdf", "doc1.pdf"]

    assert sorted(nomes, key=natural_sort_key) == ["doc1.pdf", "doc2.pdf", "doc10.pdf"]


def test_pagina_inserida_depois_nao_salta_para_o_fim_do_grupo(tmp_path):
    """O caso da atualização: o arquivo b.pdf é reextraído e suas páginas
    recebem ids maiores que as de c.pdf. A ordem tem de continuar a-b-c."""
    conn = _conn(tmp_path)
    for relative_path in ("a.pdf", "b.pdf", "c.pdf"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256,"
            " group_key, status) VALUES (?, ?, 'pdf', 1, ?, 'g', 'extracted')",
            (relative_path, relative_path, relative_path),
        )
    ids = {
        row["relative_path"]: row["id"]
        for row in conn.execute("SELECT id, relative_path FROM file")
    }
    # c.pdf entra antes de b.pdf, como aconteceria numa reextração de b.
    for relative_path in ("a.pdf", "c.pdf", "b.pdf"):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, 1, 'f. 1', 1, 0, 0, ?)",
            (ids[relative_path], relative_path),
        )
    conn.commit()

    ordem = [row["text"] for row in pages_for_group(conn, "g")]

    assert ordem == ["a.pdf", "b.pdf", "c.pdf"]

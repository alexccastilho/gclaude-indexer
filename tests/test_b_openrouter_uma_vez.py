# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: um projeto salvo com o motor `openrouter` (aposentado) abre
como `rules`. O aviso saía a cada abertura, e `load_project` roda a cada
pedido; a conversão passa a ser gravada uma vez, com um aviso só."""

from __future__ import annotations

import json
import sqlite3

from gclaude_indexer.config import load_config
from gclaude_indexer.project import create_project, load_project


def _projeto_openrouter(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({"name": "x", "subject": "y", "source_folder": str(origem), "output_folder": str(saida)})
    conn, _ = create_project(config)
    texto = conn.execute("SELECT config_json FROM project").fetchone()[0]
    dados = json.loads(texto) | {"classification_engine": "openrouter"}
    conn.execute("UPDATE project SET config_json = ?", (json.dumps(dados),))
    conn.commit()
    conn.close()
    return saida


def test_conversao_do_openrouter_e_gravada_uma_vez(tmp_path):
    saida = _projeto_openrouter(tmp_path)
    for _ in range(3):
        config, conn = load_project(saida)
        assert config.classification_engine == "rules"
        conn.close()

    conn = sqlite3.connect(saida / "project.db")
    avisos = conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.project.classification_engine_converted'"
    ).fetchone()[0]
    gravado = json.loads(conn.execute("SELECT config_json FROM project").fetchone()[0])
    conn.close()
    assert avisos == 1
    assert gravado["classification_engine"] == "rules"

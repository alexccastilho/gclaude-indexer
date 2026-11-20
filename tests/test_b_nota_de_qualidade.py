# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: a nota de qualidade tinha duas fórmulas. O cabeçalho do
Resultado (`quality_summary`: cobertura 40, confiança 35, preenchimento 25,
penalidade) e a tabela "Comparar motores" (`_engine_quality`: confiança 70,
preenchimento 30) davam números diferentes para a mesma corrida. Vale a
primeira; a tabela usa a mesma conta."""

from __future__ import annotations

from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.quality import compare_runs, quality_summary


def _banco(tmp_path):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO run (step,engine,model,parallelism,started_at,finished_at,items,ok) "
        "VALUES ('classification','local','qwen3.5:4b','automatic','2026-01-01T10:00:00','2026-01-01T10:00:20',4,1)"
    )
    # Tudo "high" e completo, mas nenhuma página extraída: a cobertura é 0,
    # e é aí que as duas fórmulas se separavam (100 contra 60).
    for i in range(4):
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
            "engine, confidence, type, date, summary, files) "
            "VALUES (?, 'f. 1', 'f. 1', ?, ?, 'local', 'high', 'OFICIO', '2024-01-10', 'x', '')",
            (f"grupo{i}", i, i),
        )
    conn.commit()
    return conn


def _config(tmp_path):
    return load_config({
        "name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path),
        "classification_engine": "local",
    })


def test_tabela_de_comparacao_usa_a_nota_do_resultado(tmp_path):
    conn = _banco(tmp_path)
    resumo = quality_summary(conn, _config(tmp_path), pending={})
    (linha,) = compare_runs(conn)
    conn.close()
    assert linha["score"] == resumo["score"]
    assert linha["confidence"] == resumo["confidence"]


def test_tabela_aceita_o_resumo_ja_calculado(tmp_path):
    conn = _banco(tmp_path)
    resumo = quality_summary(conn, _config(tmp_path), pending={})
    (linha,) = compare_runs(conn, resumo)
    conn.close()
    assert linha["score"] == resumo["score"]

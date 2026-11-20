# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: o Resultado guarda qualidade, pendências e a comparação de
motores até a assinatura mudar, e a assinatura não olhava a tabela `run`,
que `compare_runs` lê. O `UPDATE run` do fim da etapa vem depois do último
commit de janela: uma visita nesse intervalo guardava a comparação sem a
execução, e ela não se renovava."""

from __future__ import annotations

from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.quality import compare_runs
from gclaude_indexer.web import caches


def test_comparacao_se_renova_quando_a_execucao_fecha(tmp_path):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    config = load_config({"name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path)})
    conn.execute(
        "INSERT INTO run (step,engine,model,parallelism,started_at,items,ok) "
        "VALUES ('classification','rules',NULL,'automatic','2026-01-01T10:00:00',0,0)"
    )
    conn.commit()

    def comparacao():
        return caches._cached_by_signature(9101, "comparison", conn, config, lambda: compare_runs(conn))

    assert comparacao() == [], "execução ainda aberta: nada a comparar"
    conn.execute("UPDATE run SET finished_at = '2026-01-01T10:00:30', items = 4, ok = 1")
    conn.commit()
    linhas = comparacao()
    conn.close()
    assert len(linhas) == 1 and linhas[0]["engine"] == "rules"

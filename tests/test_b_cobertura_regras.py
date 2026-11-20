"""Etapa B: o motor de regras tem a mesma garantia de cobertura do motor
local: nenhuma página da janela fica sem peça.

Antes, uma peça recusada pela validação levava as páginas dela para fora
do índice (só o motor local preenchia a falta). Agora as páginas que
nenhuma peça gravada cobre ganham peças de cobertura (confiança baixa,
resumo tirado do próprio texto), com o aviso `log.rules.coverage_filled`."""

from __future__ import annotations

import json
from dataclasses import replace

from gclaude_indexer import engine_rules
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows

from tests.test_phase5 import _pdf


def test_pagina_de_peca_recusada_ganha_peca_de_cobertura(tmp_path, monkeypatch):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"
    _pdf(
        origem / "volume_1" / "peca.pdf",
        [
            "OFÍCIO No 1\nAssunto: abertura do processo administrativo.\n10/01/2024",
            "PARECER\nAssunto: análise técnica do pedido apresentado nos autos.\n12/01/2024",
        ],
    )
    config = load_config({
        "name": "Cobertura", "source_folder": str(origem), "output_folder": str(saida),
        "pages_per_window": 5, "overlap": 1,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)

    classificar = engine_rules.RulesEngine.classify

    def com_a_segunda_peca_recusada(self, pages):
        pecas = classificar(self, pages)
        return [pecas[0]] + [replace(peca, engine="desconhecido") for peca in pecas[1:]]

    monkeypatch.setattr(engine_rules.RulesEngine, "classify", com_a_segunda_peca_recusada)
    resultado = engine_rules.classify_pending(conn, config, language="pt")

    assert resultado.invalid_items == 1
    linhas = [json.loads(linha) for linha in (saida / "raw_items.jsonl").read_text(encoding="utf-8").splitlines()]
    cobertas = set()
    for linha in linhas:
        cobertas.update(range(linha["order_start"], linha["order_end"] + 1))
    assert cobertas == {1, 2}
    cobertura = [linha for linha in linhas if linha["order_start"] == 2]
    assert len(cobertura) == 1
    assert (cobertura[0]["engine"], cobertura[0]["confidence"]) == ("rules", "low")
    assert "PARECER" in cobertura[0]["summary"]
    chaves = [evento["message_key"] for evento in list_events(conn, language="pt")]
    assert "log.rules.coverage_filled" in chaves
    conn.close()

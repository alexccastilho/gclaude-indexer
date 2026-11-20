"""Etapa B: os dois motores (regras e local) gravam o resumo com o mesmo
teto (`classification.SUMMARY_CHAR_LIMIT`, o do motor local) e o campo
`files` na mesma ordem (a das páginas).

Antes, o motor de regras não cortava o resumo (uma frase longa sem ponto
entrava inteira), e o motor local listava os arquivos de uma peça em ordem
alfabética, enquanto o de regras os listava na ordem em que as páginas
aparecem."""

from __future__ import annotations

from gclaude_indexer import engine_local
from gclaude_indexer.classification import SUMMARY_CHAR_LIMIT, WindowPage
from gclaude_indexer.engine_rules import RulesEngine, load_rules


def _pagina(texto, ordem, arquivo):
    return WindowPage(
        reference=f"f. {ordem}", file_name=arquivo, text=texto, has_table=False, image_count=0, order=ordem,
    )


def test_motor_de_regras_corta_o_resumo_no_teto_do_motor_local():
    regras = load_rules()
    marcador = regras.summary_markers[0]
    longo = "palavra " * 200
    pecas = RulesEngine(regras).classify([_pagina(f"{marcador}: {longo}", 1, "a.pdf")])

    assert len(pecas) == 1
    assert pecas[0].summary is not None
    assert len(pecas[0].summary) <= SUMMARY_CHAR_LIMIT
    assert pecas[0].summary == longo.strip()[:SUMMARY_CHAR_LIMIT]


def test_motor_local_lista_os_arquivos_na_ordem_das_paginas():
    paginas = [_pagina("texto do volume dois", 1, "volume-2.pdf"), _pagina("texto do volume um", 2, "volume-1.pdf")]
    linhas = [
        {"n": 1, "type": "Contrato", "subject": "Contrato de locação", "detail": "Contrato de locação"},
        {"n": 2, "type": "Contrato", "subject": "Contrato de locação", "detail": "Contrato de locação"},
    ]

    pecas = engine_local._group_pages_into_items(paginas, linhas)

    assert [peca.files for peca in pecas] == [["volume-2.pdf", "volume-1.pdf"]]


def test_pecas_de_cobertura_do_motor_local_listam_os_arquivos_na_ordem_das_paginas():
    paginas = [_pagina("texto b", 1, "b.pdf"), _pagina("texto a", 2, "a.pdf")]

    pecas = engine_local._coverage_items(paginas)

    assert [peca.files for peca in pecas] == [["b.pdf", "a.pdf"]]

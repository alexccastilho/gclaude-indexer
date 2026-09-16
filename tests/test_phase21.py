# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 21: o contexto calibrado e a nota honesta.

A fase 20 corrigiu o contexto congelado e manteve a constante que o
alimenta. Medido contra o tokenizador do modelo, conteúdo tabular entrega
1,45 caracteres por token e não os 3,0 que o código supõe: o recálculo por
janela roda e chega curto toda vez. Numa corrida de 2904 páginas
(15/09/2026, `qwen3.5:4b`), 153 de 1449 janelas entraram no índice sem
classificação nenhuma, e a nota declarou 89/100.
"""

from __future__ import annotations

import sqlite3

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import _group_pages_into_items
from gclaude_indexer.quality import _coverage


def _page(referencia: str, texto: str = "texto da pagina") -> WindowPage:
    return WindowPage(
        reference=referencia,
        file_name="acervo.pdf",
        text=texto,
        has_table=False,
        image_count=0,
    )


def test_pagina_sem_linha_do_modelo_recebe_confianca_baixa():
    """O modelo não respondeu nada sobre a janela. As páginas entram no
    índice pelo agrupamento — essa garantia fica — mas não podem se passar
    por classificadas: era isso que fazia o log fechar em `baixa=0` com 612
    peças cegas."""
    pages = [_page("f. 1"), _page("f. 2")]

    itens = _group_pages_into_items(pages, [])

    assert itens, "a garantia de cobertura precisa continuar valendo"
    assert all(item.confidence == "low" for item in itens)


def test_linha_incompleta_do_modelo_continua_media():
    """O modelo falou, mas sem tipo. Isso é diferente de não falar, e
    continua valendo `medium`."""
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "detail": "contrato de honorarios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["medium"]


def test_linha_completa_do_modelo_continua_alta():
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "type": "CONTRATO",
             "detail": "contrato de honorarios advocaticios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["high"]


# --- Cobertura: a consulta comparava numerações diferentes -----------------

def _banco_com_duas_familias() -> sqlite3.Connection:
    """Dois grupos cujas folhas se sobrepõem em numeração, que é o caso
    real: cada PDF numera as páginas de 1 a N, e a folha é do processo."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE file (id INTEGER PRIMARY KEY, group_key TEXT, name TEXT);
        CREATE TABLE page (id INTEGER PRIMARY KEY, file_id INTEGER,
                           number INTEGER, reference TEXT);
        CREATE TABLE item (id INTEGER PRIMARY KEY, group_key TEXT,
                           start_order INTEGER, end_order INTEGER,
                           confidence TEXT);
        """
    )
    conn.execute("INSERT INTO file VALUES (1, 'Processo', 'vol1.pdf')")
    conn.execute("INSERT INTO file VALUES (2, 'Avulsos', 'anexo.pdf')")
    # Processo: folhas 1 a 4, numeradas 1..4 dentro do proprio PDF.
    for n in range(1, 5):
        conn.execute("INSERT INTO page VALUES (?, 1, ?, ?)", (n, n, f"f. {n}"))
    # Avulsos: folhas 1 a 2, tambem numeradas 1..2 dentro do PDF.
    for n in range(1, 3):
        conn.execute("INSERT INTO page VALUES (?, 2, ?, ?)", (100 + n, n, f"f. {n}"))
    return conn


def test_cobertura_nao_conta_peca_de_outro_grupo():
    """O defeito: `page.number` é a página dentro do arquivo e
    `item.start_order` é a folha do grupo. Sem join, a peça de um grupo
    'cobria' a página de outro que por acaso tinha o mesmo número."""
    conn = _banco_com_duas_familias()
    # Uma unica peca, no grupo Processo, cobrindo as folhas 1 a 4.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 4, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert total == 6
    # As duas folhas de 'Avulsos' NAO estao cobertas: nenhuma peca daquele
    # grupo existe. A consulta antiga contava 6 de 6.
    assert cobertas == 4


def test_cobertura_enxerga_o_buraco():
    """Reprodução do que foi medido no acervo: removendo as peças de uma
    faixa, a cobertura tem de cair."""
    conn = _banco_com_duas_familias()
    # Cobre so as folhas 1 e 2 do Processo; 3 e 4 ficam de fora.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Avulsos', 1, 2, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 4)


def test_cobertura_classificada_ignora_peca_cega():
    """Uma peça de confiança `low` é a rede de segurança funcionando, não
    classificação. Era isto que pagava 40 de 40 pontos numa corrida com 11%
    do índice cego."""
    conn = _banco_com_duas_familias()
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Processo', 3, 4, 'low')")
    conn.execute("INSERT INTO item VALUES (3, 'Avulsos', 1, 2, 'high')")

    total, cobertas, classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 6), "toda pagina segue no indice"
    assert classificadas == 4, "as duas folhas cegas nao contam como classificadas"

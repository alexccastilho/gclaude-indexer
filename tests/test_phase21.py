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

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import _group_pages_into_items


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

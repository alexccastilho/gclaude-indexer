"""2.1.4: "E-MAIL" e "EMAIL" são o mesmo tipo.

Num acervo de e-mails o modelo escreveu ora "E-MAIL", ora "EMAIL", e o índice
listava os dois como tipos diferentes. O hífen, como o acento, é grafia.
"""

from gclaude_indexer.item_normalize import normalize_types


def _pecas(*tipos):
    return [{"type": tipo, "summary": "x"} for tipo in tipos]


def test_grafias_que_so_diferem_no_hifen_viram_uma():
    pecas = _pecas(*["E-MAIL"] * 3, *["EMAIL"] * 2, "e-mail")
    normalize_types(pecas)
    assert {p["type"] for p in pecas} == {"E-MAIL"}


def test_hifen_e_acento_juntos_seguem_preferindo_a_grafia_acentuada():
    pecas = _pecas(*["PRE-PROJETO"] * 3, *["PRÉ-PROJETO"] * 2, "PREPROJETO")
    normalize_types(pecas)
    assert {p["type"] for p in pecas} == {"PRÉ-PROJETO"}


def test_palavras_separadas_por_espaco_continuam_diferentes():
    pecas = _pecas("AUTO DE INFRAÇÃO", "AUTODEINFRAÇÃO", "LEI", "LEI FEDERAL")
    normalize_types(pecas)
    assert len({p["type"] for p in pecas}) == 4


def test_autor_do_planalto_com_hifen_nao_derruba_a_importacao():
    from gclaude_indexer import planalto
    from gclaude_indexer.item_normalize import fill_structured_authors

    pecas = [{"engine": planalto.ENGINE, "author": nome} for nome in ("Jean-Paul Prates", "Jean Paul Prates")]
    fill_structured_authors(None, pecas)
    # Nomes de pessoa não se juntam pelo hífen: só o tipo é rótulo.
    assert [p["author"] for p in pecas] == ["Jean-Paul Prates", "Jean Paul Prates"]

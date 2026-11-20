"""Data por competência (AAAA-MM, AAAA) vinda do motor local: guardada como
os outros caminhos guardam (`classification.normalize_date`), em vez de
sumir da peça."""

from __future__ import annotations

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import _dict_to_item


def _paginas():
    return [
        WindowPage("f. 1", "doc.pdf", "texto 1", has_table=False, image_count=0),
        WindowPage("f. 2", "doc.pdf", "texto 2", has_table=False, image_count=0),
    ]


def _data(valor):
    bruto = {"ref_start": "f. 1", "ref_end": "f. 2", "confidence": "high", "date": valor}
    peca = _dict_to_item(bruto, _paginas())
    assert peca is not None
    return peca.date


def test_mes_e_ano_do_modelo_ficam_na_peca():
    assert _data("2020-01") == "2020-01"
    assert _data("2019") == "2019"


def test_dia_inexistente_cai_para_o_mes():
    assert _data("2021-09-31") == "2021-09"


def test_dia_completo_e_lixo_continuam_como_antes():
    assert _data("2020-01-05") == "2020-01-05"
    assert _data("05/01/2020") is None
    assert _data(None) is None

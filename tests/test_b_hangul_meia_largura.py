"""Decisão do usuário (etapa B, 8): o hangul de meia largura (U+FFA0–U+FFDC)
é escrita sem espaço, como o resto do hangul. Ficava fora da classe das
escritas sem espaço: o trecho não ia para a `fulltext_trigram` e a busca por
um pedaço dele não achava nada."""

from __future__ import annotations

from gclaude_indexer import fulltext, language_detect

from tests.test_idiomas import _banco_com_trechos

# Letras de hangul de meia largura (categoria Lo).
TEXTO = "ﾡﾤﾧﾩﾱﾲﾷﾸﾺﾻﾼﾽﾾ"
TERMO = "ﾩﾱﾲ"


def test_hangul_de_meia_largura_e_escrita_sem_espaco():
    assert language_detect.has_unspaced(TEXTO)
    assert language_detect.collapse_unspaced_spaces("ﾡ ﾤ") == "ﾡﾤ"
    # A faixa vizinha (katakana de meia largura) e o hangul comum seguem iguais.
    assert language_detect.has_unspaced("ｱｲ")
    assert language_detect.collapse_unspaced_spaces("가 나") == "가나"


def test_busca_acha_pedaco_de_trecho_em_hangul_de_meia_largura(tmp_path):
    conn = _banco_com_trechos(tmp_path, {1: [TEXTO]})
    if not fulltext.trigram_available(conn):  # SQLite sem trigram
        conn.close()
        return
    hits, total = fulltext.search(conn, TERMO)
    assert total == 1 and hits[0].file_id == 1
    conn.close()

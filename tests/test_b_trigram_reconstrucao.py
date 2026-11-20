"""Decisão do usuário (etapa B): projeto migrado reconstrói a `fulltext_trigram`
uma vez.

O filtro `GLOB` do `backfill_trigram` tinha divergido das faixas da indexação
(corrigido em 8072f88): num projeto da 1.x migrado antes disso, trechos de
tibetano, hangul jamo, katakana de meia largura e outros ficaram fora da
trigram, e o marcador `backfilled = 1` impede que o backfill rode de novo.
A migração zera o marcador uma vez; o backfill da extração (ou da tela de
busca) refaz a tabela com o filtro certo, e nada disso volta a acontecer."""

from __future__ import annotations

from gclaude_indexer import fulltext
from gclaude_indexer.db import connect, init_schema

# Um trecho de escrita sem espaço (hangul), que vai para a trigram.
TRECHO = "각 각 각 각 각 각 각 각 각 각"


def _projeto_migrado_com_trigram_incompleta(tmp_path):
    """Um projeto que já passou pelo backfill antigo: trecho na `fulltext`,
    trigram vazia, marcador em 1, sem a coluna nova."""
    banco = tmp_path / "project.db"
    conn = connect(banco)
    init_schema(conn)
    if not fulltext.trigram_available(conn):  # SQLite sem trigram: nada a testar
        conn.close()
        return None
    conn.execute("INSERT INTO fulltext (rowid, text, file_id, locator, line) VALUES (1, ?, 1, 'p. 1', 1)", (TRECHO,))
    conn.execute("DROP TABLE fulltext_trigram_state")
    conn.execute("CREATE TABLE fulltext_trigram_state (id INTEGER PRIMARY KEY CHECK (id = 1), backfilled INTEGER NOT NULL)")
    conn.execute("INSERT INTO fulltext_trigram_state (id, backfilled) VALUES (1, 1)")
    conn.execute("DELETE FROM fulltext_trigram")
    conn.commit()
    conn.close()
    return banco


def _marcador(conn) -> int:
    return conn.execute("SELECT backfilled FROM fulltext_trigram_state WHERE id = 1").fetchone()[0]


def test_projeto_migrado_reconstroi_a_trigram_uma_vez(tmp_path):
    banco = _projeto_migrado_com_trigram_incompleta(tmp_path)
    if banco is None:
        return
    conn = connect(banco)
    init_schema(conn)  # a abertura do projeto

    assert _marcador(conn) == 0
    assert fulltext.backfill_trigram(conn) == 1
    assert _marcador(conn) == 1

    # Uma vez só: abrir de novo não zera.
    init_schema(conn)
    assert _marcador(conn) == 1
    conn.close()
    conn = connect(banco)
    init_schema(conn)
    assert _marcador(conn) == 1
    conn.close()


def test_projeto_novo_nao_reconstroi(tmp_path):
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    if not fulltext.trigram_available(conn):
        conn.close()
        return
    assert _marcador(conn) == 1
    conn.execute("INSERT INTO fulltext (rowid, text, file_id, locator, line) VALUES (1, ?, 1, 'p. 1', 1)", (TRECHO,))
    conn.commit()

    init_schema(conn)

    assert _marcador(conn) == 1
    conn.close()

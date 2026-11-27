# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""2.1.6 — caixa de mensagens ilegível no meio da gravação (auditoria, lote 1)."""

from __future__ import annotations

import pytest

# --- Item 4: uma caixa de mensagens ilegível não derruba a etapa ----------------------
#
# `MessagePassages`/`MessagePages` só abrem o intermediário quando iterados,
# e isso acontece dentro da operação do `BatchWriter`. Um `OSError` ali saía
# por fora do tratamento de cada arquivo: no índice de busca abortava a
# indexação inteira, em toda execução; na extração deixava páginas pela
# metade gravadas sem `MARK_EXTRACTED`, e a execução seguinte batia no
# `UNIQUE(file_id, number)`.

from gclaude_indexer import extraction, fulltext
from gclaude_indexer.db import BatchWriter
from gclaude_indexer.scanning import scan
from tests.test_outlook import _projeto


class _QuebraNoMeio:
    """Rende uma parte e então falha, como um `.pst` que some do disco."""

    def __init__(self, primeiro):
        self.primeiro = primeiro

    def __iter__(self):
        yield self.primeiro
        raise OSError("intermediário sumiu")


def _dois_arquivos(tmp_path):
    origem, _saida, config, conn = _projeto(tmp_path, extensoes=("text",))
    (origem / "a.txt").write_text("primeiro", encoding="utf-8")
    (origem / "b.txt").write_text("segundo", encoding="utf-8")
    scan(conn, config)
    linhas = conn.execute("SELECT * FROM file ORDER BY relative_path").fetchall()
    return config, conn, linhas


def test_indice_de_busca_segue_quando_um_arquivo_falha_no_meio(tmp_path, monkeypatch):
    config, conn, (a, b) = _dois_arquivos(tmp_path)
    conn.execute("UPDATE file SET status = 'extracted'")
    conn.commit()

    def leitura(_config, row, _refs):
        texto = fulltext.split_document("texto do arquivo " + row["name"])
        return _QuebraNoMeio(texto[0]) if row["id"] == a["id"] else texto

    monkeypatch.setattr(fulltext, "_read_passages", leitura)

    resultado = fulltext.index_pending(conn, config, language="pt")  # não pode levantar

    indexados = {r[0] for r in conn.execute("SELECT file_id FROM fulltext_file")}
    assert indexados == {a["id"], b["id"]}, "o ilegível fica como indexado sem trechos"
    assert conn.execute("SELECT COUNT(*) FROM fulltext WHERE file_id = ?", (a["id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fulltext WHERE file_id = ?", (b["id"],)).fetchone()[0] >= 1
    avisos = conn.execute("SELECT COUNT(*) FROM event WHERE message_key = 'log.fulltext.file_failed'").fetchone()[0]
    assert avisos == 1
    assert resultado.files == 1
    conn.close()


def test_extracao_nao_deixa_paginas_orfas_quando_a_leitura_falha_no_meio(tmp_path):
    config, conn, (a, _b) = _dois_arquivos(tmp_path)
    writer = BatchWriter(conn)
    resultado = extraction.ExtractionResult()

    folha = extraction._queue_pages(
        writer, config, a, _QuebraNoMeio(("pagina 1", 0, False)), 0, resultado, language="pt",
    )
    writer.flush()

    assert folha == 0, "nenhuma folha conta para o grupo"
    assert conn.execute("SELECT COUNT(*) FROM page WHERE file_id = ?", (a["id"],)).fetchone()[0] == 0
    status = conn.execute("SELECT status, error FROM file WHERE id = ?", (a["id"],)).fetchone()
    assert status[0] == "failed" and "sumiu" in status[1]
    assert (resultado.failed, resultado.files_processed) == (1, 0)
    conn.close()


@pytest.mark.parametrize("nome", ["", "1abc", "x; DROP TABLE page", "a b", "ponto.e"])
def test_savepoint_so_aceita_identificador_simples(tmp_path, nome):
    from gclaude_indexer.db import connect, isolated_write

    conn = connect(tmp_path / "x.db")
    with pytest.raises(ValueError):
        isolated_write(conn, nome, lambda c: None)
    with pytest.raises(ValueError):
        isolated_write(conn, "valido", lambda c: None, begin="COMMIT")
    conn.close()

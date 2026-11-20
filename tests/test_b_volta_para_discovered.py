"""Etapa B: voltar um arquivo para `discovered` é uma transição só
(`file_status.reset_to_discovered`).

Antes eram cinco cópias que zeravam colunas diferentes: a repetição do OCR,
a extração sem intermediário e o renumerar sem intermediário zeravam só
`page_count`/`error`; o arquivo alterado (atualização) zerava também o
idioma; a varredura zerava o idioma e `needs_ocr`, e `ocr_failed` só ao
ignorar. Um `discovered` que ficava com `ocr_failed = 1` era tomado pelo
plano de atualização como "alterado" a cada abertura, até a conversão
chegar a ele. Agora todas zeram o mesmo conjunto; quem preserva algo diz o
quê: o mesmo conteúdo guarda o plano de OCR e o idioma (`KEEP_SAME_BYTES`),
e `needs_ocr` nunca é zerado (aponta o intermediário que ainda está no
disco, para a remoção apagá-lo)."""

from __future__ import annotations

import hashlib

import pytest

from gclaude_indexer import file_status
from gclaude_indexer.conversion import requeue_ocr_failures
from gclaude_indexer.db import BatchWriter
from gclaude_indexer.extraction import ExtractionResult, _queue_reconversion
from gclaude_indexer.invalidation import discard_changed_file
from gclaude_indexer.scanning import scan

from tests.test_phase17 import _config, _conn, _group_key, _registrar_com_paginas


def _marcar(conn, nome, **valores):
    colunas = ", ".join(f"{coluna} = ?" for coluna in valores)
    conn.execute(f"UPDATE file SET {colunas} WHERE relative_path = ?", (*valores.values(), nome))
    conn.commit()


def _linha(conn, nome):
    return conn.execute(
        "SELECT status, page_count, error, needs_ocr, ocr_failed, ocr_lang, language FROM file"
        " WHERE relative_path = ?", (nome,),
    ).fetchone()


def _projeto(tmp_path, nome="a.pdf"):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(saida)
    config = _config(origem, saida)
    (origem / nome).write_text("conteúdo", encoding="utf-8")
    _registrar_com_paginas(conn, origem, nome, 3, _group_key(origem, saida))
    _marcar(conn, nome, needs_ocr=1, ocr_failed=1, ocr_lang="por", language="pt", error="x")
    return origem, config, conn


def test_repetir_o_ocr_zera_ocr_failed_e_guarda_plano_e_idioma(tmp_path):
    _origem, _config_, conn = _projeto(tmp_path)
    _marcar(conn, "a.pdf", status=file_status.FAILED)

    assert requeue_ocr_failures(conn) == 1

    linha = _linha(conn, "a.pdf")
    assert linha["status"] == file_status.DISCOVERED
    assert (linha["page_count"], linha["error"], linha["ocr_failed"]) == (None, None, 0)
    assert (linha["ocr_lang"], linha["language"], linha["needs_ocr"]) == ("por", "pt", 1)
    conn.close()


def test_extracao_sem_intermediario_zera_ocr_failed_e_guarda_plano_e_idioma(tmp_path):
    _origem, _config_, conn = _projeto(tmp_path)
    conn.execute("DELETE FROM page")
    _marcar(conn, "a.pdf", status=file_status.CONVERTED)
    row = conn.execute("SELECT id, name FROM file WHERE relative_path = 'a.pdf'").fetchone()

    writer = BatchWriter(conn)
    _queue_reconversion(writer, row, ExtractionResult(), "pt")
    writer.flush()

    linha = _linha(conn, "a.pdf")
    assert linha["status"] == file_status.DISCOVERED
    assert (linha["page_count"], linha["error"], linha["ocr_failed"]) == (None, None, 0)
    assert (linha["ocr_lang"], linha["language"], linha["needs_ocr"]) == ("por", "pt", 1)
    conn.close()


def test_arquivo_alterado_na_atualizacao_zera_ocr_failed_e_o_idioma(tmp_path):
    _origem, config, conn = _projeto(tmp_path)

    discard_changed_file(conn, config, "a.pdf", "a.pdf", 8, language="pt")

    linha = _linha(conn, "a.pdf")
    assert linha["status"] == file_status.DISCOVERED
    assert (linha["page_count"], linha["error"], linha["ocr_failed"]) == (None, None, 0)
    assert (linha["ocr_lang"], linha["language"]) == (None, None)
    # O intermediário velho continua no disco até a conversão: a remoção
    # precisa saber onde ele está.
    assert linha["needs_ocr"] == 1
    conn.close()


def test_varredura_de_arquivo_alterado_faz_o_mesmo_reset(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    (origem / "a.pdf").write_text("conteúdo novo, outro tamanho", encoding="utf-8")

    scan(conn, config)

    linha = _linha(conn, "a.pdf")
    assert linha["status"] == file_status.DISCOVERED
    assert (linha["page_count"], linha["error"], linha["ocr_failed"]) == (None, None, 0)
    assert (linha["ocr_lang"], linha["language"]) == (None, None)
    assert linha["needs_ocr"] == 1
    novo = hashlib.sha256("conteúdo novo, outro tamanho".encode("utf-8")).hexdigest()
    assert conn.execute("SELECT sha256 FROM file WHERE relative_path = 'a.pdf'").fetchone()[0] == novo
    conn.close()


def test_preservar_coluna_que_o_reset_nao_conhece_e_erro(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        file_status.reset_to_discovered(conn, 1, keep=("needs_ocr",))
    conn.close()

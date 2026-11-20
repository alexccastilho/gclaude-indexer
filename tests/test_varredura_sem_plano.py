# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""A varredura como rede da atualização (revisão de 7c0c04c..HEAD, achados 1
e 10).

Quando a atualização automática antes da varredura não descartou o que um
documento alterado tinha no índice (o plano não conseguiu lê-lo, a pasta
sumiu num instante, Parar), a própria varredura descarta: as páginas, o
texto da busca e as janelas do grupo a partir dele, pela mesma rotina da
invalidação. Sem isso a extração parava em `UNIQUE(page.file_id,
page.number)`, ou as páginas novas caíam por baixo de janelas já
classificadas.
"""

from __future__ import annotations

from dataclasses import replace

import fitz

from gclaude_indexer import update_plan
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.invalidation import apply_pending_changes
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows


def _pdf(caminho, textos):
    documento = fitz.open()
    for texto in textos:
        documento.new_page().insert_text((72, 72), texto)
    documento.save(str(caminho))
    documento.close()


def _projeto(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = replace(load_config({
        "name": "Rede", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["pdf"], "pages_per_window": 2, "overlap": 0,
    }), parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    _pdf(origem / "a.pdf", ["Primeira do a com texto nativo.", "Segunda do a."])
    _pdf(origem / "b.pdf", ["Primeira do b com texto nativo.", "Segunda do b."])
    _pdf(origem / "c.pdf", ["Primeira do c com texto nativo.", "Segunda do c.", "Terceira do c."])
    return origem, config, conn


def _etapas(conn, config):
    """Varredura, conversão, extração (direta: sem o reparo de
    `stale_page_paths` que `_extraction_step` faz) e janelas."""
    scan(conn, config, language="pt-BR")
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config, language="pt-BR")
    prepare_windows(conn, config, language="pt-BR")


def _janelas(conn):
    return {r["key"]: r["status"] for r in conn.execute("SELECT key, status FROM window")}


def _paginas(conn, nome):
    return conn.execute(
        "SELECT COUNT(*) FROM page JOIN file ON file.id = page.file_id WHERE file.name = ?", (nome,)
    ).fetchone()[0]


def _classificadas(conn):
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    return _janelas(conn)


def _avisos(conn, chave):
    return [r[0] for r in conn.execute("SELECT message FROM event WHERE message_key = ?", (chave,))]


def test_plano_sem_ler_o_arquivo_e_a_varredura_descarta_o_que_ele_tinha(tmp_path, monkeypatch):
    origem, config, conn = _projeto(tmp_path)
    _etapas(conn, config)
    antes = _classificadas(conn)
    assert len(antes) == 4  # 7 páginas, janelas de 2

    _pdf(origem / "b.pdf", ["Nova primeira do b.", "Nova segunda do b.", "Nova terceira do b."])

    # O plano não consegue ler o b (placeholder do Drive sem rede).
    def _sem_rede(_caminho):
        raise OSError(22, "Invalid argument")

    with monkeypatch.context() as m:
        m.setattr(update_plan, "compute_hash", _sem_rede)
        plano = update_plan.build_update_plan(conn, config, record_warnings=False)
        assert plano.unverified == ("b.pdf",) and not plano.changed
        assert apply_pending_changes(conn, config, language="pt-BR") is None

    # A varredura, logo depois, lê.
    _etapas(conn, config)

    assert _paginas(conn, "b.pdf") == 3
    texto = " ".join(r[0] for r in conn.execute(
        "SELECT page.text FROM page JOIN file ON file.id = page.file_id WHERE file.name = 'b.pdf'"
    ))
    assert "Nova primeira" in texto and "Primeira do b" not in texto
    depois = _janelas(conn)
    # A primeira janela (só páginas do a) fica; as do b em diante voltam.
    assert [k for k, s in depois.items() if s == "done"] == [k for k in sorted(antes)][:1]
    assert len(depois) == 4  # 8 páginas
    assert any("b.pdf" in m for m in _avisos(conn, "log.scan.discarded_without_update"))
    conn.close()


def test_documento_que_falhou_editado_tambem_descarta_as_janelas_seguintes(tmp_path):
    """Sem páginas, mas no meio de um grupo com janelas: quando a leitura der
    certo, as páginas dele deslocam tudo o que vem depois."""
    origem, config, conn = _projeto(tmp_path)
    (origem / "b.pdf").write_bytes(b"%PDF-1.4 corrompido")
    _etapas(conn, config)
    assert conn.execute("SELECT status FROM file WHERE name = 'b.pdf'").fetchone()[0] == "failed"
    antes = _classificadas(conn)
    assert len(antes) == 3  # a (2) + c (3) = 5 páginas

    _pdf(origem / "b.pdf", ["Agora o b abre.", "Segunda do b."])
    _etapas(conn, config)  # sem a atualização antes

    assert _paginas(conn, "b.pdf") == 2
    depois = _janelas(conn)
    assert [k for k, s in depois.items() if s == "done"] == sorted(antes)[:1]
    assert any("b.pdf" in m for m in _avisos(conn, "log.scan.discarded_without_update"))
    conn.close()


def test_com_a_atualizacao_antes_a_varredura_nao_descarta_de_novo(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    _etapas(conn, config)
    _classificadas(conn)
    _pdf(origem / "b.pdf", ["Nova primeira do b.", "Nova segunda do b."])

    assert apply_pending_changes(conn, config, language="pt-BR") is not None
    _etapas(conn, config)
    assert _avisos(conn, "log.scan.discarded_without_update") == []
    assert _paginas(conn, "b.pdf") == 2
    conn.close()


def test_documento_novo_que_o_plano_nao_leu_ainda_entra_no_grupo(tmp_path, monkeypatch):
    """O arquivo novo do mesmo tamanho de um indexado é lido pelo plano para
    saber se é cópia. Se a leitura não sai (sem rede, prazo, leitura ainda
    pendente), ele não pode ficar fora do grupo: a varredura logo depois o lê,
    ele entra, e as páginas dele caem por baixo das janelas seguintes."""
    origem, config, conn = _projeto(tmp_path)
    _etapas(conn, config)
    antes = _classificadas(conn)

    novo = origem / "b_novo.pdf"
    _pdf(novo, ["x"])
    tamanho = (origem / "a.pdf").stat().st_size
    assert novo.stat().st_size < tamanho
    with open(novo, "ab") as arquivo:  # mesmo tamanho do a.pdf, outro conteúdo
        arquivo.write(b"\n%" + b" " * (tamanho - novo.stat().st_size - 2))
    assert novo.stat().st_size == tamanho

    def _sem_rede(_caminho):
        raise OSError(22, "Invalid argument")

    with monkeypatch.context() as m:
        m.setattr(update_plan, "compute_hash", _sem_rede)
        apply_pending_changes(conn, config, language="pt-BR")

    _etapas(conn, config)
    assert _paginas(conn, "b_novo.pdf") == 1
    depois = _janelas(conn)
    # a (0-1), b (2-3) ficam; b_novo entra na página 4 e desloca o c.
    assert sorted(k for k, s in depois.items() if s == "done") == sorted(antes)[:2]
    conn.close()


def test_banco_ocupado_por_um_instante_nao_derruba_a_rede_da_varredura(tmp_path, monkeypatch):
    """Achado 1 da revisão seguinte: o descarte da rede roda numa transação
    própria; um `database is locked` momentâneo (o Drive, outra conexão) é
    esperado e tentado de novo, como no lote da varredura, em vez de abortar
    a varredura inteira."""
    import sqlite3

    from gclaude_indexer import invalidation

    origem, config, conn = _projeto(tmp_path)
    _etapas(conn, config)
    _classificadas(conn)
    _pdf(origem / "b.pdf", ["Nova primeira do b.", "Nova segunda do b.", "Nova terceira do b."])

    aplicar_real = invalidation._apply
    tentativas = {"n": 0}

    def _ocupado_na_primeira(*args, **kwargs):
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return aplicar_real(*args, **kwargs)

    monkeypatch.setattr(invalidation, "_apply", _ocupado_na_primeira)
    _etapas(conn, config)  # sem a atualização antes: a rede descarta

    assert tentativas["n"] == 2
    assert _paginas(conn, "b.pdf") == 3
    assert any("b.pdf" in m for m in _avisos(conn, "log.scan.discarded_without_update"))
    conn.close()

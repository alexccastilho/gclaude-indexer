"""Cópia (`duplicate`) de um documento cujo original mudou de conteúdo.

A cópia entra como `duplicate` e fica fora do processamento, apoiada no
original. Quando o original era removido, a cópia já era liberada
(`invalidation._apply`); quando ele MUDAVA de conteúdo, a cópia seguia
`duplicate` de um conteúdo que saiu do índice, e nem a varredura nem o plano
reexaminam uma cópia inalterada: os bytes continuavam na pasta, o conteúdo
sumia do índice. Agora, quando a varredura grava o conteúdo novo do
original, as cópias do conteúdo antigo são liberadas e a próxima
atualização as enxerga como documento novo."""

from __future__ import annotations

import hashlib

import pytest

from gclaude_indexer.events import list_events
from gclaude_indexer.invalidation import apply_update_plan
from gclaude_indexer.scanning import scan
from gclaude_indexer.update_plan import build_update_plan, detect_changes

from tests.test_phase17 import _config, _conn, _group_key, _registrar_com_paginas


@pytest.mark.parametrize("nome_da_copia", ["0-copia-de-b.pdf", "z-copia-de-b.pdf"])
def test_original_mudado_libera_a_copia_do_conteudo_antigo(tmp_path, nome_da_copia):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(saida)
    config = _config(origem, saida)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    copia = origem / nome_da_copia
    copia.write_text("b.pdf", encoding="utf-8")
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status)"
        " VALUES (?, ?, 'pdf', 5, ?, ?, 'duplicate')",
        (nome_da_copia, nome_da_copia, hashlib.sha256(b"b.pdf").hexdigest(), copia.stat().st_mtime),
    )
    conn.commit()

    # O original muda de conteúdo; a cópia continua com o conteúdo antigo.
    (origem / "b.pdf").write_text("b.pdf, segunda versão", encoding="utf-8")
    apply_update_plan(conn, config, build_update_plan(conn, config), language="pt")
    scan(conn, config)

    # A cópia não fica "duplicata de algo que não existe mais": a próxima
    # atualização a enxerga como documento novo e a indexa.
    novos = [c.relative_path for c in detect_changes(conn, config)[0] if c.kind == "new"]
    assert novos == [nome_da_copia]
    mensagens = " ".join(e["message"] for e in list_events(conn, language="pt"))
    assert nome_da_copia in mensagens

    # E a próxima atualização mais a varredura a põem no índice.
    apply_update_plan(conn, config, build_update_plan(conn, config), language="pt")
    scan(conn, config)
    linha = conn.execute("SELECT status, group_key FROM file WHERE relative_path = ?", (nome_da_copia,)).fetchone()
    assert linha["status"] == "discovered" and linha["group_key"] == grupo
    conn.close()


def test_original_lido_de_novo_sem_mudar_nao_libera_a_copia(tmp_path):
    """Contraprova: só a mudança de conteúdo libera. Varrer de novo o mesmo
    original não mexe na cópia."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(saida)
    config = _config(origem, saida)
    grupo = _group_key(origem, saida)
    (origem / "b.pdf").write_text("b.pdf", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "b.pdf", 10, grupo)
    copia = origem / "copia-de-b.pdf"
    copia.write_text("b.pdf", encoding="utf-8")
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status)"
        " VALUES (?, ?, 'pdf', 5, ?, ?, 'duplicate')",
        ("copia-de-b.pdf", "copia-de-b.pdf", hashlib.sha256(b"b.pdf").hexdigest(), copia.stat().st_mtime),
    )
    conn.commit()

    scan(conn, config)

    linha = conn.execute("SELECT status FROM file WHERE relative_path = 'copia-de-b.pdf'").fetchone()
    assert linha["status"] == "duplicate"
    conn.close()

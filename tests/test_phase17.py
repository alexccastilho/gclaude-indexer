# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Tests for Phase 17: incremental re-indexing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from gclaude_indexer import db
from gclaude_indexer.paths import natural_sort_key
from gclaude_indexer.windows_prep import pages_for_group


def _conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "project.db")
    db.init_schema(connection)
    return connection


def test_a_tabela_de_removidos_e_a_coluna_mtime_nascem_na_abertura(tmp_path):
    conn = _conn(tmp_path)

    tabelas = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "removed_file" in tabelas

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas


def test_abrir_o_projeto_duas_vezes_nao_duplica_a_coluna(tmp_path):
    conn = _conn(tmp_path)
    db.init_schema(conn)  # não pode levantar "duplicate column name"

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(file)")]
    assert colunas.count("mtime") == 1


def test_um_projeto_da_1_0_1_ganha_a_coluna_na_primeira_abertura(tmp_path):
    """Simula o banco antigo: tabela `file` sem `mtime`."""
    conn = db.connect(tmp_path / "project.db")
    conn.execute(
        "CREATE TABLE file (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL,"
        " sha256 TEXT NOT NULL, group_key TEXT, page_count INTEGER,"
        " needs_ocr INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT)"
    )
    conn.commit()

    db.init_schema(conn)

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas


def test_o_caminhamento_ignora_lixo_de_sistema_e_a_pasta_de_saida(tmp_path):
    from gclaude_indexer.scanning import source_files

    origem = tmp_path / "origem"
    saida = origem / "saida"
    (origem / "sub").mkdir(parents=True)
    saida.mkdir()

    (origem / "b.pdf").write_text("b", encoding="utf-8")
    (origem / "A.pdf").write_text("a", encoding="utf-8")
    (origem / "sub" / "c.pdf").write_text("c", encoding="utf-8")
    (origem / "desktop.ini").write_text("lixo", encoding="utf-8")
    (saida / "index.md").write_text("gerado", encoding="utf-8")

    encontrados = [p.relative_to(origem).as_posix() for p in source_files(origem, saida)]

    assert encontrados == ["A.pdf", "b.pdf", "sub/c.pdf"]


def test_quinhentas_paginas_dao_trinta_e_seis_janelas():
    from gclaude_indexer.windows_prep import window_key, window_spans

    spans = window_spans(500, 16, 2)

    assert len(spans) == 36
    assert spans[0] == (0, 16)
    assert spans[-1] == (490, 500)


def test_dez_paginas_no_fim_mudam_so_a_cauda():
    from gclaude_indexer.windows_prep import window_spans

    antes = window_spans(500, 16, 2)
    depois = window_spans(510, 16, 2)

    assert antes[:35] == depois[:35]      # 35 janelas idênticas
    assert antes[35] == (490, 500)        # a última de antes
    assert depois[35] == (490, 506)       # mudou: cobre 6 páginas novas
    assert depois[36] == (504, 510)       # e nasceu uma
    assert len(depois) == 37


def test_a_chave_da_janela_e_posicional_e_com_zeros_a_esquerda():
    from gclaude_indexer.windows_prep import window_key

    assert window_key("processo", 490, 500) == "processo::000491-000500"


def test_acervo_vazio_nao_gera_janela():
    from gclaude_indexer.windows_prep import window_spans

    assert window_spans(0, 16, 2) == []


def test_sobreposicao_maior_que_a_janela_nao_trava():
    """Passo zero ou negativo faria laço infinito. O piso de 1 impede."""
    from gclaude_indexer.windows_prep import window_spans

    spans = window_spans(10, 4, 9)

    assert len(spans) <= 10
    assert spans[-1][1] == 10


def test_a_ordem_natural_poe_o_dez_depois_do_dois():
    nomes = ["doc10.pdf", "doc2.pdf", "doc1.pdf"]

    assert sorted(nomes, key=natural_sort_key) == ["doc1.pdf", "doc2.pdf", "doc10.pdf"]


def test_pagina_inserida_depois_nao_salta_para_o_fim_do_grupo(tmp_path):
    """O caso da atualização: o arquivo b.pdf é reextraído e suas páginas
    recebem ids maiores que as de c.pdf. A ordem tem de continuar a-b-c."""
    conn = _conn(tmp_path)
    for relative_path in ("a.pdf", "b.pdf", "c.pdf"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256,"
            " group_key, status) VALUES (?, ?, 'pdf', 1, ?, 'g', 'extracted')",
            (relative_path, relative_path, relative_path),
        )
    ids = {
        row["relative_path"]: row["id"]
        for row in conn.execute("SELECT id, relative_path FROM file")
    }
    # c.pdf entra antes de b.pdf, como aconteceria numa reextração de b.
    for relative_path in ("a.pdf", "c.pdf", "b.pdf"):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, 1, 'f. 1', 1, 0, 0, ?)",
            (ids[relative_path], relative_path),
        )
    conn.commit()

    ordem = [row["text"] for row in pages_for_group(conn, "g")]

    assert ordem == ["a.pdf", "b.pdf", "c.pdf"]


from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.update_plan import SourceFolderUnavailable, detect_changes


def _config(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="all_together", extensions=["pdf"],
    )


def _registrar(conn, relative_path: str, conteudo: str, mtime: float | None):
    import hashlib

    digest = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, status) VALUES (?, ?, 'pdf', ?, ?, ?, 'g', 'extracted')",
        (relative_path, Path(relative_path).name, len(conteudo), digest, mtime),
    )
    conn.commit()


def test_pasta_de_origem_sumida_nao_propoe_remover_o_acervo(tmp_path):
    """A guarda mais importante da funcionalidade. Drive desconectado,
    pasta movida, letra de unidade trocada: nada disso pode virar uma
    proposta de apagar tudo."""
    origem = tmp_path / "origem"
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)

    with pytest.raises(SourceFolderUnavailable):
        detect_changes(conn, _config(origem, saida))


def test_pasta_vazia_com_banco_cheio_tambem_e_recusada(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)

    with pytest.raises(SourceFolderUnavailable):
        detect_changes(conn, _config(origem, saida))


def test_pasta_inalterada_nao_acusa_mudanca(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    arquivo = origem / "a.pdf"
    arquivo.write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", arquivo.stat().st_mtime)

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert mudancas == []
    assert inalterados == 1


def test_mtime_reescrito_pelo_drive_sem_mudar_conteudo_nao_e_alteracao(tmp_path):
    """O Google Drive reescreve a data de arquivos cujo conteúdo não mudou.
    Sem o desempate pelo hash, o plano gritaria 'mudou' o tempo todo."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)  # mtime antigo, conteúdo igual

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert mudancas == []
    assert inalterados == 1


def test_novo_alterado_e_removido_sao_detectados(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "igual.pdf").write_text("igual", encoding="utf-8")
    (origem / "mudou.pdf").write_text("depois", encoding="utf-8")
    (origem / "novo.pdf").write_text("novo", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "igual.pdf", "igual", (origem / "igual.pdf").stat().st_mtime)
    _registrar(conn, "mudou.pdf", "antes", 1.0)
    _registrar(conn, "sumiu.pdf", "sumiu", 1.0)

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    por_tipo = {m.kind: m.relative_path for m in mudancas}
    assert por_tipo == {"new": "novo.pdf", "changed": "mudou.pdf", "removed": "sumiu.pdf"}
    assert inalterados == 1


def test_a_impressao_digital_muda_quando_a_pasta_muda(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)

    _, _, antes = detect_changes(conn, _config(origem, saida))
    (origem / "b.pdf").write_text("b", encoding="utf-8")
    _, _, depois = detect_changes(conn, _config(origem, saida))

    assert antes != depois


def test_o_scan_grava_o_mtime_para_a_deteccao_rapida(tmp_path):
    from gclaude_indexer.scanning import scan

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)

    scan(conn, _config(origem, saida))

    gravado = conn.execute("SELECT mtime FROM file WHERE relative_path = 'a.pdf'").fetchone()[0]
    assert gravado == pytest.approx((origem / "a.pdf").stat().st_mtime)


# --- Task 6: divergência por grupo e contagem de janelas -------------------

from gclaude_indexer.update_plan import build_update_plan, first_affected_window
from gclaude_indexer.windows_prep import window_spans


def _group_key(origem: Path, saida: Path) -> str:
    """Chave do grupo derivada pela mesma função que a produção usa.

    Hardcoding "g" here would be a silent lie: `_config` uses
    `group_mode="all_together"`, under which `derive_group_key` returns the
    source folder's *name*. With a literal, the stored group and the
    intended group would never match, and every divergence test would
    measure the wrong thing while still passing.
    """
    from gclaude_indexer.scanning import derive_group_key

    origem_resolvida = origem.resolve()
    chave = derive_group_key(
        "qualquer.pdf", origem_resolvida, _config(origem_resolvida, saida)
    )
    assert chave is not None
    return chave


def _registrar_com_paginas(
    conn, origem: Path, nome: str, paginas: int, group_key: str
) -> None:
    import hashlib

    caminho = origem / nome
    conteudo = caminho.read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, page_count, status)"
        " VALUES (?, ?, 'pdf', ?, ?, ?, ?, ?, 'extracted')",
        (nome, nome, len(conteudo), hashlib.sha256(conteudo.encode()).hexdigest(),
         caminho.stat().st_mtime, group_key, paginas),
    )
    file_id = conn.execute(
        "SELECT id FROM file WHERE relative_path = ?", (nome,)
    ).fetchone()[0]
    for numero in range(1, paginas + 1):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
            (file_id, numero, f"f. {numero}"),
        )
    conn.commit()


def _criar_janelas(
    conn, group_key: str, page_count: int, window_size: int, overlap: int
) -> None:
    from gclaude_indexer.windows_prep import window_key

    for start, end in window_spans(page_count, window_size, overlap):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, ?, ?, ?, 'done')",
            (window_key(group_key, start, end), group_key,
             f"f. {start + 1}", f"f. {end}"),
        )
    conn.commit()


def _contar_janelas_criadas(page_count: int, window_size: int, overlap: int) -> int:
    """Roda `prepare_windows` de verdade sobre um grupo sintético.

    A conexão é fechada antes de sair do `TemporaryDirectory`: no Windows
    um `project.db` ainda aberto trava a remoção da pasta (WinError 32) e
    o teste falharia por causa da limpeza, não da contagem.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as pasta:
        base = Path(pasta)
        conn = db.connect(base / "project.db")
        db.init_schema(conn)
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256,"
            " group_key, page_count, status) VALUES ('a.pdf', 'a.pdf', 'pdf', 1, 'h',"
            " 'g', ?, 'extracted')",
            (page_count,),
        )
        file_id = conn.execute("SELECT id FROM file").fetchone()[0]
        for numero in range(1, page_count + 1):
            conn.execute(
                "INSERT INTO page (file_id, number, reference, char_count, image_count,"
                " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
                (file_id, numero, f"f. {numero}"),
            )
        conn.commit()

        from gclaude_indexer.windows_prep import prepare_windows

        config = ProjectConfig(
            name="a", source_folder=str(base), output_folder=str(base),
            pages_per_window=window_size, overlap=overlap,
        )
        prepare_windows(conn, config)
        criadas = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
        conn.close()
        return criadas


def test_a_ultima_janela_sempre_entra_porque_o_total_a_limita():
    """Divergência na página 501 (0-based 500). Nenhuma janela antiga
    cobre essa página, mas a última ia de 491 a 500 e passa a ir de 491 a
    506: é ela que muda."""
    antigas = window_spans(500, 16, 2)
    novas = window_spans(510, 16, 2)

    indice = first_affected_window(antigas, 500)

    assert indice == 35
    assert len(antigas) - indice == 1   # exatamente 1 descartada
    assert indice == 35                 # exatamente 35 preservadas
    assert len(novas) == 37
    assert antigas[:35] == novas[:35]   # as preservadas continuam idênticas
    assert antigas[35] != novas[35]     # (490, 500) vira (490, 506)


def test_divergencia_no_comeco_invalida_tudo():
    antigas = window_spans(500, 16, 2)

    assert first_affected_window(antigas, 0) == 0


def test_divergencia_no_meio_preserva_o_que_vem_antes():
    antigas = window_spans(500, 16, 2)

    indice = first_affected_window(antigas, 250)

    assert antigas[indice][1] > 250       # a janela cobre a página divergente
    assert antigas[indice - 1][1] <= 250  # a anterior não


def test_grupo_sem_janela_nao_quebra():
    assert first_affected_window([], 0) == 0


def test_o_plano_conta_janelas_descartadas_e_preservadas(tmp_path):
    """Acervo de 30 páginas em 3 arquivos de 10, janela 16 / sobreposição 2.
    Um quarto arquivo entra no fim."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo_esperado = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo_esperado)
    _criar_janelas(conn, grupo_esperado, page_count=30, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    assert [m.relative_path for m in plano.new] == ["d.pdf"]
    assert plano.changed == ()
    assert plano.removed == ()
    grupo = plano.groups[0]
    assert grupo.group_key == grupo_esperado
    assert grupo.windows_kept + grupo.windows_discarded == len(window_spans(30, 16, 2))
    assert grupo.windows_discarded >= 1
    assert plano.is_empty is False
    assert plano.files_needing_ocr == 1
    assert plano.windows_to_reclassify == grupo.windows_discarded


def test_acervo_intacto_nao_produz_plano(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)

    plano = build_update_plan(conn, _config(origem, saida))

    assert plano.is_empty is True
    assert plano.groups == ()
    assert plano.unchanged_count == 2
    assert plano.windows_to_reclassify == 0


def test_arquivos_antes_da_divergencia_nao_sao_renumerados(tmp_path):
    """Ruling C2: só o último arquivo muda, então nada antes dele pode
    entrar em `files_to_renumber` — quem entra nessa lista perde as
    páginas e volta para a extração."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    (origem / "d.pdf").write_text("d bem diferente", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    assert [m.relative_path for m in plano.changed] == ["d.pdf"]
    invalidacao = plano.groups[0]
    assert invalidacao.first_divergent_page == 30
    assert "a.pdf" not in invalidacao.files_to_renumber
    assert "b.pdf" not in invalidacao.files_to_renumber
    assert "c.pdf" not in invalidacao.files_to_renumber
    assert invalidacao.files_to_renumber == ()


def test_so_quem_vem_depois_da_divergencia_e_renumerado(tmp_path):
    """O arquivo do meio muda: quem vem antes fica intacto, quem vem
    depois precisa de novas folhas."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    (origem / "b.pdf").write_text("b bem diferente", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    invalidacao = plano.groups[0]
    assert invalidacao.first_divergent_page == 10
    assert invalidacao.files_to_renumber == ("c.pdf", "d.pdf")


def test_arquivo_removido_do_meio_desloca_quem_vem_depois(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    (origem / "b.pdf").unlink()

    plano = build_update_plan(conn, _config(origem, saida))

    assert [m.relative_path for m in plano.removed] == ["b.pdf"]
    invalidacao = plano.groups[0]
    assert invalidacao.first_divergent_page == 10
    assert invalidacao.files_to_renumber == ("c.pdf",)


def test_a_contagem_prevista_bate_com_a_que_windows_prep_cria():
    """Teste de acoplamento: se a aritmética voltar a ser duplicada, este
    falha antes de o usuário ver um número errado na tela."""
    for page_count in (1, 15, 16, 17, 30, 100, 500, 510):
        previstas = len(window_spans(page_count, 16, 2))
        criadas = _contar_janelas_criadas(page_count, window_size=16, overlap=2)
        assert previstas == criadas, f"{page_count} páginas"

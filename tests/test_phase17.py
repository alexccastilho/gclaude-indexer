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
    """Grava as janelas de um grupo como `prepare_windows` as gravaria.

    A chave passa por `sanitize_group_name`, como na produção. Sem isso a
    fixture só coincidiria com o código real por acidente do nome do
    grupo usado nos testes ("origem", que a higienização não altera), e um
    grupo com espaço ou acento revelaria a diferença apenas no usuário.
    """
    from gclaude_indexer.windows_prep import sanitize_group_name, window_key

    base = sanitize_group_name(group_key)
    for start, end in window_spans(page_count, window_size, overlap):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, ?, ?, ?, 'done')",
            (window_key(base, start, end), group_key,
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


def test_ultima_janela_truncada_e_descartada_quando_o_acervo_cresce():
    """Metade 1 da regra. 500 páginas em janela 16 / sobreposição 2: a
    última vai de (490, 500) — só 10 páginas, truncada pelo total. Com
    mais páginas ela vira (490, 506): muda de chave e precisa voltar ao
    modelo."""
    antigas = window_spans(500, 16, 2)
    ultima_inicio, ultima_fim = antigas[-1]
    assert ultima_fim - ultima_inicio < 16  # truncada

    indice = first_affected_window(antigas, 500, 16)

    assert indice == 35
    assert len(antigas) - indice == 1   # 1 descartada
    assert indice == 35                 # 35 preservadas
    assert antigas[indice:] == [(490, 500)]


def test_ultima_janela_cheia_sobrevive_ao_acrescimo():
    """Metade 2 da regra. 30 páginas na mesma configuração dão
    [(0, 16), (14, 30)]: a última tem 16 páginas, não foi truncada, e o
    total maior recalcula o mesmo (14, 30). Nada a descartar — descartá-la
    seria pagar o modelo por um texto que não mudou."""
    antigas = window_spans(30, 16, 2)
    novas = window_spans(40, 16, 2)
    ultima_inicio, ultima_fim = antigas[-1]
    assert ultima_fim - ultima_inicio == 16  # cheia

    indice = first_affected_window(antigas, 30, 16)

    assert indice == len(antigas)       # nada descartado
    assert antigas[indice:] == []       # fatiar no limite não estoura
    assert max(0, len(antigas) - indice) == 0   # windows_discarded
    assert indice == 2                          # windows_kept
    assert novas[: len(antigas)] == antigas     # as antigas continuam lá


def test_acervo_de_uma_janela_so_e_tratado_como_truncado():
    """Um grupo menor que uma janela dá [(0, n)], e o layout sozinho não
    diz se n é o total ou o tamanho da janela. Sem `window_size` a função
    escolhe o lado seguro: descartar."""
    assert first_affected_window([(0, 10)], 10) == 0        # truncada, inferida
    assert first_affected_window([(0, 10)], 10, 16) == 0    # truncada, explícita
    assert first_affected_window([(0, 16)], 16, 16) == 1    # cheia: preservada


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
    # Zero descartadas é a resposta certa para *este* acervo, não uma
    # omissão: 30 páginas em janela 16 / sobreposição 2 dão
    # [(0, 16), (14, 30)], e a última tem 16 páginas — cheia, não
    # truncada. Acrescentar um quarto documento no fim recalcula esse
    # mesmo (14, 30) idêntico, então reclassificá-lo seria pagar o modelo
    # por um texto que não mudou. Compare com o acervo de 500 páginas,
    # cuja última janela tem 10 e por isso é descartada.
    assert grupo.windows_discarded == 0
    assert grupo.windows_kept == 2
    assert grupo.discard_whole_group is False
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


def _marcar_como_falho(conn, nome: str, page_count_fantasma: int) -> None:
    """Reproduz o estado que `conversion` + `extraction` deixam para trás.

    `conversion.py` grava `page_count = N` no sucesso; se a extração
    depois falha, `extraction.py` grava só `status = 'failed'` e deixa o
    `N` lá, sem nenhuma linha em `page`. É assim que `file.page_count`
    passa a mentir sobre a geometria real do grupo.
    """
    file_id = conn.execute(
        "SELECT id FROM file WHERE relative_path = ?", (nome,)
    ).fetchone()[0]
    conn.execute("DELETE FROM page WHERE file_id = ?", (file_id,))
    conn.execute(
        "UPDATE file SET status = 'failed', page_count = ? WHERE id = ?",
        (page_count_fantasma, file_id),
    )
    conn.commit()


def test_geometria_vem_das_paginas_reais_e_nao_de_file_page_count(tmp_path):
    """Um PDF ilegível no meio do acervo não pode deslocar a geometria.

    `b.pdf` falhou na extração e ficou com `page_count = 100` e zero
    linhas em `page`. As janelas que existem de verdade foram montadas
    sobre 20 páginas — as de `a.pdf` e `c.pdf` —, não sobre 120. Ler a
    coluna daria divergência 110 e índice 7 numa lista de 2 janelas: a
    Task 7 fatiaria vazio, não apagaria nada, e a janela (14, 20)
    manteria a classificação antiga sobre páginas que mudaram.
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    _marcar_como_falho(conn, "b.pdf", page_count_fantasma=100)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    (origem / "c.pdf").write_text("c bem diferente", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    # A geometria derivada é a das linhas de `page`, não a da coluna.
    paginas_reais = len(pages_for_group(conn, grupo))
    assert paginas_reais == 20
    invalidacao = plano.groups[0]
    assert invalidacao.first_divergent_page == 10  # início de c.pdf, não 110
    janelas_reais = window_spans(paginas_reais, 16, 2)
    assert len(janelas_reais) == 2
    assert invalidacao.windows_kept + invalidacao.windows_discarded == 2
    assert invalidacao.first_affected_window == 0
    assert invalidacao.windows_discarded == 2
    # Índice 0 porque a divergência cai dentro da primeira janela, não
    # porque o layout gravado discorda: os dois mecanismos são
    # distintos e aqui o gravado bate com o derivado.
    assert invalidacao.discard_whole_group is False
    # E o arquivo falho não é arrastado para a renumeração.
    assert invalidacao.files_to_renumber == ()


def test_arquivo_sem_paginas_nao_desalinha_a_comparacao_posicional(tmp_path):
    """O arquivo de zero páginas continua na lista com contagem zero.

    Omiti-lo deslocaria todas as posições seguintes e poria a divergência
    cedo demais: aqui `c.pdf` muda, e a divergência tem de ser 10 (início
    de c), não 0.
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    _marcar_como_falho(conn, "b.pdf", page_count_fantasma=0)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    (origem / "c.pdf").write_text("c bem diferente", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    assert plano.groups[0].first_divergent_page == 10


def test_layout_divergente_descarta_o_grupo_inteiro_e_avisa(tmp_path):
    """Rede de segurança: se o que está gravado não bate com o que as
    páginas dariam, nenhuma previsão vale e o grupo inteiro volta."""
    from gclaude_indexer.events import list_events

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    # O índice guarda um layout de 500 páginas (36 janelas); as páginas
    # dão 30 (2 janelas). A diferença é de 34 de propósito: um erro de
    # um a mais ou a menos não passa por este teste.
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")
    gravadas = conn.execute(
        "SELECT COUNT(*) FROM window WHERE group_key = ?", (grupo,)
    ).fetchone()[0]
    derivadas = len(window_spans(30, 16, 2))
    assert (gravadas, derivadas) == (36, 2)

    plano = build_update_plan(conn, _config(origem, saida))

    invalidacao = plano.groups[0]
    # A bandeira é o que carrega a intenção. Um índice não consegue
    # dizer "tudo o que a tabela tem deste grupo": apagar por
    # `spans[first_affected_window:]` alcançaria no máximo as 2 janelas
    # derivadas — talvez nenhuma delas existente — e deixaria 34 para
    # trás, dentro da própria rede de segurança.
    assert invalidacao.discard_whole_group is True
    assert invalidacao.first_affected_window == 0
    assert invalidacao.windows_kept == 0
    # A conta mostrada é a das janelas que existem, não a das derivadas.
    assert invalidacao.windows_discarded == gravadas == 36
    assert invalidacao.windows_discarded != derivadas
    assert plano.windows_to_reclassify == 36
    chaves = [evento["message_key"] for evento in list_events(conn)]
    assert "log.update.layout_mismatch" in chaves


def test_grupo_sem_janela_gravada_nao_e_tratado_como_divergencia(tmp_path):
    """Antes da primeira classificação não há layout gravado para
    contradizer. Acusar divergência aqui não descartaria nada e ainda
    assim diria ao usuário que o acervo inteiro volta ao modelo."""
    from gclaude_indexer.events import list_events

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    (origem / "d.pdf").write_text("d", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    # Última janela de 30 páginas é cheia: nada a descartar.
    assert plano.groups[0].windows_discarded == 0
    assert plano.groups[0].discard_whole_group is False
    chaves = [evento["message_key"] for evento in list_events(conn)]
    assert "log.update.layout_mismatch" not in chaves


def test_a_contagem_prevista_bate_com_a_que_windows_prep_cria():
    """Teste de acoplamento: se a aritmética voltar a ser duplicada, este
    falha antes de o usuário ver um número errado na tela."""
    for page_count in (1, 15, 16, 17, 30, 100, 500, 510):
        previstas = len(window_spans(page_count, 16, 2))
        criadas = _contar_janelas_criadas(page_count, window_size=16, overlap=2)
        assert previstas == criadas, f"{page_count} páginas"


# --- Task 7: aplicação do plano (a única coisa do projeto que apaga) ------

from gclaude_indexer.invalidation import PlanExpired, apply_update_plan
from gclaude_indexer.windows_prep import sanitize_group_name


def test_plano_vencido_e_recusado_sem_escrever_nada(tmp_path):
    """O plano é uma fotografia da pasta, e o Drive continua sincronizando
    enquanto o usuário lê a tela de confirmação. Aplicar um plano vencido
    seria gravar uma coisa tendo mostrado outra.

    O acervo aqui é montado de propósito com coisas a perder — um
    documento removido, 36 janelas gravadas, 20 páginas — e com um layout
    divergente, que faz `build_update_plan` gravar um evento de aviso.
    Com um acervo vazio as asserções de "não escreveu nada" seriam
    verdadeiras em qualquer implementação, inclusive numa sem verificação
    de impressão digital.
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "fica.pdf").write_text("fica", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "fica.pdf", paginas=10, group_key=grupo)
    (origem / "sai.pdf").write_text("sai", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "sai.pdf", paginas=10, group_key=grupo)
    (origem / "sai.pdf").unlink()
    # 20 páginas dariam 2 janelas; o índice guarda 36. O layout diverge,
    # e é isso que faria `build_update_plan` gravar um evento.
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    eventos_antes = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]

    (origem / "c.pdf").write_text("c", encoding="utf-8")  # a pasta mudou

    with pytest.raises(PlanExpired):
        apply_update_plan(conn, config, plano)

    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM file").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 20
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 36
    # Nem sequer um evento: a verificação usa `detect_changes`, que não
    # grava nada, e não `build_update_plan`, que grava o aviso de layout
    # divergente (e dá commit) antes de qualquer recusa.
    assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == eventos_antes


def test_arquivo_que_some_entre_as_duas_caminhadas_nao_e_apagado(tmp_path, monkeypatch):
    """Aplicar faz duas caminhadas pela pasta: a da verificação e a de
    dentro de `build_update_plan`. O plano aplicado vem da segunda, então
    ele *não* é o objeto cuja impressão digital foi validada.

    Um arquivo sincronizado que pisca fora de existência entre as duas —
    coisa que cliente de Drive faz — entraria em `current.removed` sem
    nunca ter sido visto nem confirmado pelo usuário, e teria as páginas,
    a linha de `file` e o registro de remoção gravados. Aqui o plano
    confirmado estava vazio: não havia nada a apagar, e mesmo assim um
    documento sumiria.
    """
    from gclaude_indexer import update_plan as modulo_plano

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("fica.pdf", "pisca.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 2, group_key=grupo)
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    assert plano.is_empty  # o usuário confirmou "nada a fazer"

    # Só a segunda caminhada enxerga a pasta sem o arquivo: `invalidation`
    # guarda a própria referência a `detect_changes`, importada no topo,
    # enquanto `build_update_plan` resolve a sua no módulo `update_plan`.
    deteccao_real = modulo_plano.detect_changes

    def some_antes_da_segunda_caminhada(conn_interna, config_interna):
        caminho = origem / "pisca.pdf"
        if caminho.exists():
            caminho.unlink()
        return deteccao_real(conn_interna, config_interna)

    monkeypatch.setattr(
        modulo_plano, "detect_changes", some_antes_da_segunda_caminhada
    )

    with pytest.raises(PlanExpired):
        apply_update_plan(conn, config, plano)

    assert conn.execute(
        "SELECT COUNT(*) FROM file WHERE relative_path = 'pisca.pdf'"
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0


def test_o_plano_recebido_e_so_testemunha_da_impressao_digital(tmp_path):
    """Os índices do plano apontam para o layout que existia quando a
    fotografia foi tirada; os vãos fatiados aqui vêm do banco de agora. A
    impressão digital cobre a pasta de origem, não o índice — outra
    conexão pode tê-lo movido por baixo de um plano ainda válido. Por
    isso a aplicação é feita sobre um plano derivado na hora, e o plano
    recebido serve só para provar que a pasta não mudou."""
    from dataclasses import replace

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    assert plano.groups and plano.changed  # o plano de verdade tem o que fazer

    # Mesma impressão digital, conteúdo esvaziado: uma implementação que
    # iterasse o plano recebido não apagaria janela nenhuma.
    mentiroso = replace(plano, groups=(), changed=(), removed=())

    apply_update_plan(conn, config, mentiroso)

    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert conn.execute(
        "SELECT status FROM file WHERE relative_path = 'a.pdf'"
    ).fetchone()[0] == "discovered"


def test_o_removido_sai_das_tabelas_e_entra_em_removed_file(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "fica.pdf").write_text("fica", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "fica.pdf", paginas=2, group_key=grupo)
    (origem / "sai.pdf").write_text("sai", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "sai.pdf", paginas=2, group_key=grupo)
    (origem / "sai.pdf").unlink()
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert conn.execute(
        "SELECT COUNT(*) FROM file WHERE relative_path = 'sai.pdf'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 2
    assert conn.execute(
        "SELECT name FROM removed_file"
    ).fetchone()["name"] == "sai.pdf"
    assert resultado.files_removed == 1
    assert resultado.pages_deleted == 2


def test_quem_mudou_volta_para_discovered_e_quem_so_renumera_para_converted(tmp_path):
    """A economia inteira da funcionalidade está nestas duas transições:
    'discovered' paga OCR de novo, 'converted' relê o que já está em
    <saida>/converted/. Trocá-las tornaria toda atualização tão cara
    quanto uma reindexação completa."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    (origem / "b.pdf").write_text("b", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=2, group_key=grupo)
    _registrar_com_paginas(conn, origem, "b.pdf", paginas=2, group_key=grupo)
    (origem / "a.pdf").write_text("a corrigido e maior", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    estados = dict(conn.execute("SELECT relative_path, status FROM file"))
    assert estados["a.pdf"] == "discovered"   # mudou: paga OCR
    assert estados["b.pdf"] == "converted"    # só renumera: relê o convertido
    assert resultado.files_reset == 1
    assert resultado.files_renumbered == 1
    # Os dois perderam as páginas: um para reextrair, o outro para
    # renumerar. Nenhum dos dois fica com numeração velha.
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 0


def test_o_txt_da_janela_descartada_some_do_disco(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    base = sanitize_group_name(grupo)
    txt = saida / "windows" / f"{base}_j0001-0016.txt"
    txt.write_text("texto velho", encoding="utf-8")
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    apply_update_plan(conn, config, build_update_plan(conn, config))

    assert not txt.exists()
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0


def test_layout_divergente_apaga_todas_as_janelas_gravadas_do_grupo(tmp_path):
    """Correção da bandeira `discard_whole_group`: apagar vão a vão
    alcançaria no máximo as 2 janelas derivadas e deixaria 34 gravadas
    de pé, dentro da própria rede de segurança."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    # 30 páginas dão 2 janelas; o índice guarda o layout de 500 (36).
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")
    base = sanitize_group_name(grupo)
    dentro_do_derivado = saida / "windows" / f"{base}_j0001-0016.txt"
    so_no_gravado = saida / "windows" / f"{base}_j0491-0500.txt"
    dentro_do_derivado.write_text("velho", encoding="utf-8")
    so_no_gravado.write_text("velho", encoding="utf-8")
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    assert plano.groups[0].discard_whole_group is True

    resultado = apply_update_plan(conn, config, plano)

    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert resultado.windows_deleted == 36
    assert not dentro_do_derivado.exists()
    assert not so_no_gravado.exists()  # inalcançável vão a vão


def test_chave_que_escapa_da_pasta_de_janelas_nao_apaga_nada_fora(tmp_path):
    """A chave do grupo pode vir de uma regex sobre um nome de arquivo que
    o acervo trouxe: é dado, não constante. Um `.txt` órfão custa nada;
    um delete fora da pasta de janelas custa o acervo do usuário."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    # Três linhas gravadas contra duas derivadas: dispara o descarte do
    # grupo inteiro, que é o caminho em que o nome do arquivo vem da
    # chave armazenada.
    for chave in (
        f"{grupo}::000001-000016",
        f"{grupo}::000015-000030",
        "../../escapou::000001-000016",
    ):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, ?, 'f. 1', 'f. 16', 'done')",
            (chave, grupo),
        )
    conn.commit()
    (origem / "d.pdf").write_text("d", encoding="utf-8")
    forasteiro = tmp_path / "escapou_j0001-0016.txt"
    forasteiro.write_text("nao me apague", encoding="utf-8")
    base = sanitize_group_name(grupo)
    legitimos = [
        saida / "windows" / f"{base}_j0001-0016.txt",
        saida / "windows" / f"{base}_j0015-0030.txt",
    ]
    for caminho in legitimos:
        caminho.write_text("velho", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert forasteiro.exists()
    # Pula exatamente o arquivo recusado e nenhum outro: os dois
    # legítimos foram apagados.
    assert [caminho.exists() for caminho in legitimos] == [False, False]
    assert resultado.windows_orphaned == 0
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0


def test_falha_no_meio_deixa_o_banco_como_estava_e_o_txt_no_disco(tmp_path, monkeypatch):
    """Atomicidade e ordem: nada é gravado pela metade, e nenhum arquivo
    some antes de o commit passar."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "fica.pdf").write_text("fica", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "fica.pdf", paginas=2, group_key=grupo)
    (origem / "sai.pdf").write_text("sai", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "sai.pdf", paginas=2, group_key=grupo)
    (origem / "sai.pdf").unlink()
    _criar_janelas(conn, grupo, page_count=4, window_size=16, overlap=2)
    base = sanitize_group_name(grupo)
    txt = saida / "windows" / f"{base}_j0001-0004.txt"
    txt.write_text("texto velho", encoding="utf-8")
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    paginas_antes = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]
    janelas_antes = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]

    import gclaude_indexer.invalidation as mod

    def explode(*args, **kwargs):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(mod, "_record_removals", explode)

    with pytest.raises(RuntimeError):
        apply_update_plan(conn, config, plano)

    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == paginas_antes
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == janelas_antes
    assert conn.execute(
        "SELECT COUNT(*) FROM file WHERE relative_path = 'sai.pdf'"
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0
    # O apagamento em disco só acontece depois do commit: se acontecesse
    # antes, este arquivo teria sumido e a linha da janela continuaria
    # no banco, deixando uma janela sem texto.
    assert txt.exists()


def test_txt_preso_no_disco_vira_aviso_em_vez_de_silencio(tmp_path, monkeypatch):
    """O Drive pode estar segurando o arquivo. Levantar depois de um
    commit bem-sucedido seria pior — mas engolir sem deixar rastro também
    é ruim: `prepare_windows` pula o `.txt` que já existe, então um
    sobrevivente pode virar o texto de uma janela nova com o mesmo vão."""
    from gclaude_indexer.events import list_events

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    base = sanitize_group_name(grupo)
    preso = saida / "windows" / f"{base}_j0001-0016.txt"
    solto = saida / "windows" / f"{base}_j0015-0020.txt"
    preso.write_text("texto velho", encoding="utf-8")
    solto.write_text("texto velho", encoding="utf-8")
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    unlink_real = Path.unlink

    def travado(self, *args, **kwargs):
        if self.name == preso.name:
            raise PermissionError("arquivo em uso pelo Drive")
        return unlink_real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", travado)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    # A atualização não falhou: o banco já estava commitado.
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert resultado.windows_deleted == 2
    assert resultado.windows_orphaned == 1
    assert preso.exists() and not solto.exists()
    avisos = [
        evento for evento in list_events(conn)
        if evento["message_key"] == "log.update.orphan_window_file"
    ]
    assert len(avisos) == 1
    assert avisos[0]["level"] == "warning"
    assert preso.name in avisos[0]["message"]


def test_grupo_com_espaco_apaga_o_txt_com_o_nome_higienizado(tmp_path):
    """A produção nomeia o `.txt` com `sanitize_group_name(group_key)`,
    não com a chave crua. Todos os outros testes usam um grupo que a
    higienização não altera, então trocar uma pela outra passaria
    despercebido — aqui não."""
    origem = tmp_path / "Meu Acervo"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    base = sanitize_group_name(grupo)
    assert (grupo, base) == ("Meu Acervo", "Meu_Acervo")

    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)
    higienizado = saida / "windows" / f"{base}_j0001-0016.txt"
    cru = saida / "windows" / f"{grupo}_j0001-0016.txt"
    higienizado.write_text("este é o que a produção escreveu", encoding="utf-8")
    cru.write_text("este nome nunca foi escrito pela produção", encoding="utf-8")
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert not higienizado.exists()
    assert cru.exists()
    # A linha também saiu: a chave gravada usa a mesma higienização.
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert resultado.windows_deleted == 2


def test_as_chaves_do_log_da_atualizacao_existem_nos_tres_idiomas():
    """A suíte não tem teste de paridade de chaves de i18n; sem isto uma
    tradução faltando só apareceria para o usuário."""
    from gclaude_indexer.i18n import _TRANSLATIONS

    for idioma in ("pt", "en", "es"):
        assert "log.update.applied" in _TRANSLATIONS[idioma]
        assert "log.update.orphan_window_file" in _TRANSLATIONS[idioma]

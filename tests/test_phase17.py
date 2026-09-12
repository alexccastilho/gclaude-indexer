# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Tests for Phase 17: incremental re-indexing."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from gclaude_indexer import db
from gclaude_indexer.paths import natural_sort_key
from gclaude_indexer.windows_prep import pages_for_group

# --- geometry of the oracle's collection (see `_config_do_oraculo`) --------
ORACULO_PAGINAS_POR_JANELA = 4
ORACULO_SOBREPOSICAO = 1

# The three numbers the oracle's fixture is worth. 30 pages with a stride
# of 3 give ten spans; `02-recibo.pdf` starts at page 10 (0-based), so the
# first span ending past it is index 3 — three windows survive the update
# and seven go back to the engine. Asserted, not merely computed here, for
# the reason spelled out at the assertion itself.
ORACULO_JANELAS_PRESERVADAS = 3
ORACULO_JANELAS_DESCARTADAS = 7


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


def test_renumerar_sem_o_convertido_no_disco_volta_para_discovered(tmp_path):
    """"Renumerar sem OCR" só existe enquanto o intermediário existe.

    `cleanup.py` apaga `<saida>/converted/` de propósito, e a tela de
    Resultado oferece o botão ("liberar espaço depois que os artefatos
    estão prontos"). Rebaixar para 'converted' com o artefato apagado não
    é uma atualização lenta: a extração levanta no arquivo que falta,
    marca o documento 'failed', ele some do `index.md` e do
    `timeline.md`, e nada o traz de volta — `convert()` só pega
    'discovered' e um novo `scan` pula o arquivo porque o hash continua
    batendo.
    """
    from gclaude_indexer.events import list_events

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "converted").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 2, group_key=grupo)
    # Os dois posteriores foram digitalizados: a extração os relê do
    # PDF gravado em converted/, não do original.
    conn.execute("UPDATE file SET needs_ocr = 1 WHERE relative_path IN ('b.pdf', 'c.pdf')")
    conn.commit()
    # Só o de "c.pdf" sobreviveu à limpeza dos intermediários.
    (saida / "converted" / "c.pdf").write_bytes(b"%PDF-1.4 ocr")
    (origem / "a.pdf").write_text("a corrigido e bem maior", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    estados = dict(conn.execute("SELECT relative_path, status FROM file"))
    assert estados["b.pdf"] == "discovered"  # sem artefato: paga OCR de novo
    assert estados["c.pdf"] == "converted"   # com artefato: só renumera
    assert resultado.files_reconverted == 1
    assert resultado.files_renumbered == 1
    chaves = [evento["message_key"] for evento in list_events(conn)]
    assert "log.update.reconversion_needed" in chaves


def test_pdf_com_texto_nativo_renumera_sem_reconverter(tmp_path):
    """Um PDF que nunca precisou de OCR não tem intermediário nenhum: a
    extração abre o original na pasta de origem. Exigir um artefato dele
    mandaria para o OCR justamente o caso em que o OCR é inútil."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()  # sem converted/ nenhum, e é o certo
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 2, group_key=grupo)
    (origem / "a.pdf").write_text("a corrigido e bem maior", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert dict(conn.execute("SELECT relative_path, status FROM file"))["b.pdf"] == "converted"
    assert resultado.files_reconverted == 0


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


def test_aplicar_duas_vezes_nao_descarta_o_que_a_primeira_preservou(tmp_path):
    """O estado que uma aplicação bem-sucedida deixa não é layout corrompido.

    Depois de aplicar, o grupo guarda menos janelas do que as páginas
    dariam: a cauda foi apagada e `prepare_windows` ainda não rodou para
    recriá-la. Comparando *contagens*, o plano seguinte lia isso como
    contradição e mandava descartar o grupo inteiro — e esse plano
    seguinte está a um clique de distância, porque `update_apply`
    redireciona para a tela de execução, cujo aviso roda ao carregar e
    ainda enxerga o documento alterado (quem atualiza o hash é o `scan`).
    O segundo "Atualizar" jogava fora toda janela preservada e toda linha
    de `raw_items.jsonl` do grupo: exatamente a opção A que o §5 do
    design recusa.

    Comparando *chaves*, um conjunto gravado contido no derivado é o
    estado normal de meio-caminho, e não uma contradição.
    """
    from gclaude_indexer.events import list_events
    from gclaude_indexer.windows_prep import window_key as _chave

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("01.pdf", "02.pdf", "03.pdf", "04.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=40, window_size=16, overlap=2)
    base = sanitize_group_name(grupo)
    preservada = _chave(base, 0, 16)
    bruto = _escrever_raw_items(saida, [(preservada, grupo)])
    # `03.pdf` começa na página 20: a primeira janela sobrevive.
    (origem / "03.pdf").write_text("03 corrigido e bem maior", encoding="utf-8")
    config = _config(origem, saida)

    apply_update_plan(conn, config, build_update_plan(conn, config))

    # Pré-condição: a primeira aplicação preservou mesmo alguma coisa —
    # sem isso as asserções seguintes seriam verdadeiras à toa.
    assert [linha[0] for linha in conn.execute("SELECT key FROM window")] == [preservada]

    segundo = build_update_plan(conn, config)

    assert segundo.groups[0].discard_whole_group is False
    chaves = [evento["message_key"] for evento in list_events(conn)]
    assert "log.update.layout_mismatch" not in chaves

    apply_update_plan(conn, config, segundo)

    assert [linha[0] for linha in conn.execute("SELECT key FROM window")] == [preservada]
    assert _janelas_do_raw_items(bruto) == [preservada]


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


def _escrever_raw_items(saida: Path, pecas: list[tuple[str, str]]) -> Path:
    """Uma peça por par `(chave da janela, agrupador)`.

    Os dois campos são gravados porque `item_to_dict` grava os dois em
    produção — `window` é a chave da janela e `group` é o `group_key`
    dela — e a poda usa um ou outro conforme o ramo do descarte.
    """
    caminho = saida / "raw_items.jsonl"
    caminho.write_text(
        "".join(
            json.dumps({"window": chave, "group": grupo, "type": "OFÍCIO"},
                       ensure_ascii=False) + "\n"
            for chave, grupo in pecas
        ),
        encoding="utf-8",
    )
    return caminho


def _janelas_do_raw_items(caminho: Path) -> list[str]:
    return [
        json.loads(linha)["window"]
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if linha.startswith("{")
    ]


def test_a_poda_tira_do_raw_items_so_as_pecas_da_janela_descartada(tmp_path):
    """`raw_items.jsonl` é append-only e relido inteiro a cada importação,
    então uma peça de janela descartada continua entrando no índice com
    referências de folha que agora apontam para outras páginas."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=30, window_size=16, overlap=2)
    base = sanitize_group_name(grupo)
    from gclaude_indexer.windows_prep import window_key as _chave

    preservada = _chave(base, 0, 16)
    descartada = _chave(base, 14, 30)
    de_outro_grupo = "outro::000001-000016"
    bruto = _escrever_raw_items(
        saida,
        [(preservada, grupo), (descartada, grupo), (de_outro_grupo, "outro")],
    )
    # Linha ilegível: a importação já a reporta como erro; a poda não é
    # quem decide apagar o que não consegue ler.
    with open(bruto, "a", encoding="utf-8") as arquivo:
        arquivo.write("isto nao e json\n")
    # `c.pdf` começa na página 20, então a primeira janela (0-16)
    # sobrevive e só a segunda é descartada.
    (origem / "c.pdf").write_text("c corrigido e maior", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert resultado.items_pruned == 1
    assert resultado.prune_failures == 0
    assert _janelas_do_raw_items(bruto) == [preservada, de_outro_grupo]
    assert "isto nao e json" in bruto.read_text(encoding="utf-8")
    assert not (saida / "raw_items.jsonl.tmp").exists()


def test_a_poda_do_grupo_inteiro_alcanca_as_janelas_que_o_layout_derivado_nao_ve(tmp_path):
    """No descarte do grupo inteiro as chaves vêm das linhas gravadas, não
    dos vãos derivados — as mesmas que já servem para achar os `.txt`."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")
    base = sanitize_group_name(grupo)
    from gclaude_indexer.windows_prep import window_key as _chave

    # 490-500 só existe no layout gravado; vão a vão seria inalcançável.
    so_no_gravado = _chave(base, 490, 500)
    de_outro_grupo = "outro::000001-000016"
    bruto = _escrever_raw_items(
        saida,
        [
            (_chave(base, 0, 16), grupo),
            (so_no_gravado, grupo),
            (de_outro_grupo, "outro"),
        ],
    )
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    assert plano.groups[0].discard_whole_group is True

    resultado = apply_update_plan(conn, config, plano)

    assert resultado.items_pruned == 2
    assert _janelas_do_raw_items(bruto) == [de_outro_grupo]


def test_poda_do_grupo_inteiro_recupera_linhas_de_uma_poda_anterior_que_falhou(tmp_path):
    """Se uma poda falhou, as linhas ficaram e as janelas delas já não
    existem — nada consegue reconstruir aquelas chaves. O campo `group`,
    que `item_to_dict` grava em toda linha, ainda as identifica."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")
    base = sanitize_group_name(grupo)

    # Sobras de uma poda que falhou numa atualização anterior: chaves de
    # um layout que não existe mais em `window`.
    orfa_1 = f"{base}::000901-000916"
    orfa_2 = f"{base}::000915-000930"
    de_outro_grupo = "outro::000001-000016"
    bruto = _escrever_raw_items(
        saida, [(orfa_1, grupo), (orfa_2, grupo), (de_outro_grupo, "outro")]
    )
    chaves_gravadas = {
        linha[0] for linha in conn.execute("SELECT key FROM window")
    }
    assert orfa_1 not in chaves_gravadas and orfa_2 not in chaves_gravadas
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    assert plano.groups[0].discard_whole_group is True

    resultado = apply_update_plan(conn, config, plano)

    assert resultado.items_pruned == 2
    assert _janelas_do_raw_items(bruto) == [de_outro_grupo]


def test_raw_items_corrompido_nao_estoura_depois_do_commit(tmp_path):
    """Bytes inválidos em UTF-8 levantam `UnicodeDecodeError`, que é
    `ValueError` e não `OSError`. Depois do commit nada pode escapar: o
    chamador ouviria que a atualização falhou com as linhas já apagadas."""
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
    bruto = saida / "raw_items.jsonl"
    bruto.write_bytes(b'{"window": "x"}\n\xff\xfe nao e utf-8\n')
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    # A atualização em si deu certo — e foi isso que o chamador ouviu.
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert resultado.windows_deleted == 2
    assert resultado.prune_failures == 1
    assert resultado.items_pruned == 0
    assert not (saida / "raw_items.jsonl.tmp").exists()
    avisos = [
        evento for evento in list_events(conn)
        if evento["message_key"] == "log.update.raw_items_prune_failed"
    ]
    assert len(avisos) == 1
    assert avisos[0]["level"] == "warning"


def test_projeto_nunca_classificado_nao_tem_raw_items_e_isso_e_normal(tmp_path):
    """Antes da primeira classificação o arquivo não existe. Não é erro."""
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
    assert not (saida / "raw_items.jsonl").exists()

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    assert resultado.items_pruned == 0
    assert resultado.prune_failures == 0
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0


def test_poda_que_falha_e_contada_e_avisada_em_vez_de_silenciosa(tmp_path, monkeypatch):
    """Pior que um `.txt` sobrevivente: este produz um índice errado, não
    um arquivo órfão. O aviso tem de dizer isso ao usuário."""
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
    from gclaude_indexer.windows_prep import window_key as _chave

    bruto = _escrever_raw_items(saida, [(_chave(base, 0, 16), grupo)])
    antes = bruto.read_text(encoding="utf-8")
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    def recusa(self, *args, **kwargs):
        raise PermissionError("arquivo em uso pelo Drive")

    monkeypatch.setattr(Path, "replace", recusa)

    resultado = apply_update_plan(conn, config, build_update_plan(conn, config))

    # A atualização em si deu certo: o banco já estava commitado.
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert resultado.prune_failures == 1
    assert resultado.items_pruned == 0
    assert bruto.read_text(encoding="utf-8") == antes  # nada pela metade
    assert not (saida / "raw_items.jsonl.tmp").exists()
    avisos = [
        evento for evento in list_events(conn)
        if evento["message_key"] == "log.update.raw_items_prune_failed"
    ]
    assert len(avisos) == 1
    assert avisos[0]["level"] == "warning"


def test_as_chaves_do_log_da_atualizacao_existem_nos_tres_idiomas():
    """A suíte não tem teste de paridade de chaves de i18n; sem isto uma
    tradução faltando só apareceria para o usuário."""
    from gclaude_indexer.i18n import _TRANSLATIONS

    for idioma in ("pt", "en", "es"):
        assert "log.update.applied" in _TRANSLATIONS[idioma]
        assert "log.update.orphan_window_file" in _TRANSLATIONS[idioma]
        assert "log.update.raw_items_prune_failed" in _TRANSLATIONS[idioma]
        assert "log.update.reconversion_needed" in _TRANSLATIONS[idioma]


# --- Task 8: reescrita incondicional quando a linha é criada aqui -----------

def test_txt_orfao_e_reescrito_quando_a_linha_nao_existia(tmp_path):
    """Corrige a corrupção de janela: se prepare_windows cria a linha,
    reescreve o .txt incondicionalmente, mesmo que o arquivo exista no disco.
    Um arquivo descartado que não saiu (travado, desconexão) deixaria a
    janela com texto velho ao lado da nova classificação — um silêncio
    perigoso. Agora: se a linha aqui nasce, o texto sempre entra novo.
    """
    from gclaude_indexer.windows_prep import prepare_windows, sanitize_group_name

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)

    # Cria um arquivo com páginas, mas sem inserir a linha de window no banco
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)

    # Pré-cria o arquivo da janela com texto velho (simula arquivo preso no disco)
    config = _config(origem, saida)
    windows_dir = Path(config.output_folder) / "windows"
    base = sanitize_group_name(grupo)
    txt_path = windows_dir / f"{base}_j0001-0016.txt"
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("TEXTO VELHO", encoding="utf-8")

    # Valida que a linha não existe ainda
    assert conn.execute(
        "SELECT COUNT(*) FROM window WHERE key LIKE ?",
        (f"{base}::%",)
    ).fetchone()[0] == 0

    # Executa prepare_windows
    resultado = prepare_windows(conn, config)

    # Valida que ambas as linhas foram criadas (20 paginas = 2 janelas)
    assert resultado.created == 2
    assert resultado.existing == 0

    # Valida que o arquivo foi reescrito (contém texto novo, não velho)
    conteudo = txt_path.read_text(encoding="utf-8")
    assert "TEXTO VELHO" not in conteudo
    # O arquivo deve conter o header e o texto das páginas
    assert "# window:" in conteudo
    assert "# pages: 16" in conteudo


def test_janela_existente_pula_reescrita_se_arquivo_existe(tmp_path):
    """Regressao: a otimizacao que salta a reescrita quando a linha existe
    e o arquivo existe no disco deve continuar funcionando. De outro jeito,
    toda execucao de prepare_windows reescreveria todas as janelas."""
    from gclaude_indexer.windows_prep import prepare_windows, sanitize_group_name

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    grupo = _group_key(origem, saida)

    # Cria um arquivo com paginas e as janelas do banco
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20, group_key=grupo)
    _criar_janelas(conn, grupo, page_count=20, window_size=16, overlap=2)

    # Pre-escreve os arquivos das janelas com um marcador identificavel
    config = _config(origem, saida)
    windows_dir = Path(config.output_folder) / "windows"
    base = sanitize_group_name(grupo)
    txt_path = windows_dir / f"{base}_j0001-0016.txt"
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    marcador = "CONTEUDO INTOCAVEL"
    txt_path.write_text(marcador, encoding="utf-8")

    # Valida estado inicial: linha existe, arquivo existe, tem o marcador
    assert conn.execute(
        "SELECT COUNT(*) FROM window WHERE key LIKE ?",
        (f"{base}::%",)
    ).fetchone()[0] == 2
    assert txt_path.read_text(encoding="utf-8") == marcador

    # Roda prepare_windows
    resultado = prepare_windows(conn, config)

    # Valida que nenhuma nova linha foi criada (ambas ja existiam)
    assert resultado.created == 0
    assert resultado.existing == 2

    # Valida que o arquivo foi poupado da reescrita (marcador ainda la)
    assert txt_path.read_text(encoding="utf-8") == marcador


# --- Task 9: removed documents in review.md --------------------------------


def test_o_review_lista_os_documentos_removidos(tmp_path):
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    conn.execute(
        "INSERT INTO removed_file (relative_path, name, removed_at)"
        " VALUES ('velho.pdf', 'velho.pdf', '2026-09-12T10:00:00+00:00')"
    )
    conn.commit()
    config = ProjectConfig(name="a", source_folder=str(tmp_path), output_folder=str(saida))

    caminho = generate_review_md(conn, config, "pt")
    texto = caminho.read_text(encoding="utf-8")

    assert "velho.pdf" in texto
    assert "2026-09-12T10:00:00+00:00" in texto


def test_sem_remocoes_o_review_diz_que_nao_houve(tmp_path):
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    config = ProjectConfig(name="a", source_folder=str(tmp_path), output_folder=str(saida))

    texto = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")

    assert "Nenhum documento removido" in texto


def test_a_secao_de_removidos_existe_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave in (
            "artifact.review.removed_section",
            "artifact.review.removed_none",
        ):
            texto = translate(idioma, chave)
            assert texto and not texto.startswith("artifact."), f"{idioma}/{chave}"


# --- Task 10: rotas, tela de confirmação e aviso na execução ---------------


def _app_com_projeto(tmp_path, monkeypatch):
    """Servidor de teste com um projeto registrado e uma pasta de origem.

    Isola `machine_local_folder()` numa pasta descartável através da
    variável de ambiente que a própria função já lê
    (`paths.LOCAL_FOLDER_ENV`), e não através de um patch por módulo.

    `machine_local_folder` é importado separadamente por `catalog.py`,
    `sync.py` e `settings.py` (`from .paths import machine_local_folder`
    em cada um) — corrigir só o nome ligado dentro de `catalog` deixaria
    `sync.check_sync`/`mark_synced` (chamados em todo `_open_project`) e
    `settings.shared_catalog_folder` (chamado por `catalog.catalog_folder`)
    ainda lendo o `%LOCALAPPDATA%\\GClaudeIndexer` de verdade desta
    máquina. A variável de ambiente é lida dentro da própria função, a
    cada chamada (`paths.machine_local_folder`), então alcança todo mundo
    de uma vez, não importa como cada módulo importou o nome — ver
    `test_o_isolamento_alcanca_catalogo_sincronizacao_e_configuracoes`
    logo abaixo, que prova isso.
    """
    from fastapi.testclient import TestClient

    from gclaude_indexer import paths
    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json
    from gclaude_indexer.web.app import app

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")

    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    config = _config(origem, saida)
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-09-12T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()
    from gclaude_indexer.scanning import scan

    scan(conn, config)

    entry = register_project("acervo", str(saida))
    return TestClient(app), entry.id, conn


def test_o_isolamento_alcanca_catalogo_sincronizacao_e_configuracoes(tmp_path, monkeypatch):
    """Prova de que a variável de ambiente redireciona todo mundo que lê
    `machine_local_folder()`, não só o módulo `catalog`.

    Sem isso, cada teste desta seção — que abre um projeto de verdade via
    `_open_project`, e portanto passa por `sync.check_sync`/`mark_synced`
    e por `catalog.register_project`/`find_project` — gravaria em
    `%LOCALAPPDATA%\\GClaudeIndexer\\projects.json` e
    `...\\sincronizacao.json` desta máquina, e não numa pasta descartável.
    """
    import os

    pasta_real = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "GClaudeIndexer"
    marcadores = ("projects.json", "sincronizacao.json")
    mtimes_antes = {
        nome: (pasta_real / nome).stat().st_mtime
        for nome in marcadores
        if (pasta_real / nome).is_file()
    }

    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)
    assert cliente.get(f"/projects/{projeto_id}/update").status_code == 200

    mtimes_depois = {
        nome: (pasta_real / nome).stat().st_mtime
        for nome in marcadores
        if (pasta_real / nome).is_file()
    }
    assert mtimes_depois == mtimes_antes, "a pasta local de verdade desta máquina foi tocada pelo teste"

    pasta_redirecionada = tmp_path / "local"
    assert (pasta_redirecionada / "projects.json").is_file()
    assert (pasta_redirecionada / "sincronizacao.json").is_file()


def test_o_diagnostico_nao_escreve_no_banco(tmp_path, monkeypatch):
    """A rota GET roda a cada abertura da tela. Se escrevesse, abrir um
    projeto o modificaria.

    Precisa de uma pasta que realmente divergiu do índice, e de um "a.pdf"
    que já tenha passado por extração e preparação de janelas — com
    "a.pdf" parado e sem página nem janela nenhuma (o estado que
    `_app_com_projeto` deixa pronto sozinho), uma invalidação indevida não
    teria absolutamente nada para descartar: `status` já é 'discovered' e
    voltaria a ser 'discovered', `page_count` já é `NULL` e voltaria a ser
    `NULL`, não há página nem janela para apagar. O teste não
    distinguiria "não escreve" de "escreve, mas não tinha nada para
    escrever" (é exatamente esse buraco que o code review do Finding 2
    apontou, e a inspeção manual confirmou: injetar um `apply_update_plan`
    de propósito na rota GET não fazia este teste, na sua versão
    anterior, falhar).

    Por isso o "a.pdf" ganha 3 páginas e a janela correspondente antes do
    diff (imitando o que `prepare_windows` deixaria gravado depois de uma
    execução completa), e só então a pasta ganha um arquivo novo e o
    existente é alterado. Uma invalidação chamada por engano aqui
    descartaria a janela do grupo e resetaria "a.pdf" para 'discovered'
    com `page_count = NULL` — mudanças reais, que o teste consegue ver.
    """
    cliente, projeto_id, conn = _app_com_projeto(tmp_path, monkeypatch)
    origem = tmp_path / "origem"

    grupo, file_id = conn.execute(
        "SELECT group_key, id FROM file WHERE relative_path = 'a.pdf'"
    ).fetchone()
    conn.execute(
        "UPDATE file SET status = 'extracted', page_count = 3 WHERE id = ?", (file_id,)
    )
    for numero in range(1, 4):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
            (file_id, numero, f"f. {numero}"),
        )
    _criar_janelas(conn, grupo, page_count=3, window_size=16, overlap=2)
    conn.commit()

    (origem / "novo.pdf").write_text("novo", encoding="utf-8")
    (origem / "a.pdf").write_text("mudou bastante", encoding="utf-8")

    arquivos_antes = {
        row["relative_path"]: (row["sha256"], row["status"], row["page_count"])
        for row in conn.execute("SELECT relative_path, sha256, status, page_count FROM file")
    }
    paginas_antes = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]
    janelas_antes = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
    removidos_antes = conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0]
    assert paginas_antes == 3 and janelas_antes == 1  # pré-condição: há o que descartar

    resposta = cliente.get(f"/projects/{projeto_id}/update")

    assert resposta.status_code == 200
    arquivos_depois = {
        row["relative_path"]: (row["sha256"], row["status"], row["page_count"])
        for row in conn.execute("SELECT relative_path, sha256, status, page_count FROM file")
    }
    assert arquivos_depois == arquivos_antes
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == paginas_antes
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == janelas_antes
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == removidos_antes


def test_o_diagnostico_nao_grava_nem_o_aviso_de_layout_divergente(tmp_path, monkeypatch):
    """A única escrita que o plano se permitia era o aviso de layout
    divergente, e ela alcançava as rotas GET.

    O design promete que o diagnóstico não escreve. Tornar o aviso raro
    não é a mesma coisa que a promessa: aqui a rota é posta justamente
    no estado que o dispara, e mesmo assim nenhuma linha de `event` pode
    nascer. Quem avisa é `apply_update_plan`, que está escrevendo de
    qualquer maneira.
    """
    cliente, projeto_id, conn = _app_com_projeto(tmp_path, monkeypatch)
    origem = tmp_path / "origem"

    grupo, file_id = conn.execute(
        "SELECT group_key, id FROM file WHERE relative_path = 'a.pdf'"
    ).fetchone()
    conn.execute(
        "UPDATE file SET status = 'extracted', page_count = 3 WHERE id = ?", (file_id,)
    )
    for numero in range(1, 4):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
            (file_id, numero, f"f. {numero}"),
        )
    # 3 páginas dariam uma janela; o índice guarda o layout de 500 (36).
    _criar_janelas(conn, grupo, page_count=500, window_size=16, overlap=2)
    conn.commit()
    (origem / "novo.pdf").write_text("novo", encoding="utf-8")
    eventos_antes = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]

    resposta = cliente.get(f"/projects/{projeto_id}/update")

    assert resposta.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == eventos_antes


def test_o_aviso_cala_enquanto_o_pipeline_tem_trabalho_pendente(tmp_path, monkeypatch):
    """Depois de aplicar, a ação honesta é "rodar as etapas", não
    "atualizar de novo".

    A invalidação deixa o acervo cheio de trabalho que o pipeline já sabe
    fazer, e os documentos novos só entram na tabela `file` quando o
    `scan` roda — então o plano continua não-vazio e o aviso convidaria a
    uma segunda atualização sobre um estado meio aplicado.
    """
    cliente, projeto_id, conn = _app_com_projeto(tmp_path, monkeypatch)
    origem = tmp_path / "origem"
    (origem / "novo.pdf").write_text("novo", encoding="utf-8")

    # `_app_com_projeto` roda só o `scan`: "a.pdf" está 'discovered', ou
    # seja, a conversão ainda tem o que fazer.
    assert cliente.get(f"/projects/{projeto_id}/update/banner").text.strip() == ""

    conn.execute("UPDATE file SET status = 'extracted' WHERE relative_path = 'a.pdf'")
    conn.commit()

    # Sem nada pendente, o aviso volta: a supressão é de estado, não de
    # sempre — senão o teste passaria com o aviso removido de vez.
    assert cliente.get(f"/projects/{projeto_id}/update/banner").text.strip() != ""


def test_o_post_com_plano_vencido_e_recusado(tmp_path, monkeypatch):
    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)

    resposta = cliente.post(
        f"/projects/{projeto_id}/update", data={"fingerprint": "impressao-que-nao-existe"}
    )

    assert resposta.status_code == 409


def test_o_aviso_nao_aparece_quando_nada_mudou(tmp_path, monkeypatch):
    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)

    corpo = cliente.get(f"/projects/{projeto_id}/update/banner").text

    assert corpo.strip() == ""


def _esvaziar_pasta_de_origem(tmp_path: Path) -> None:
    """Simula a pasta de origem ficando inacessível, sem apagar a própria
    pasta.

    Apagar ou renomear a pasta inteira (`shutil.rmtree`) faz
    `_open_project` levantar antes de qualquer rota rodar: `load_config`
    valida `source_folder` (`config._validate`, `folder.exists()`) em
    toda abertura de projeto, não só nas de atualização, e devolve um 500
    — um comportamento pré-existente, alheio a esta tarefa. O caminho que
    realmente alcança `SourceFolderUnavailable` dentro das rotas novas é
    o mesmo já coberto em `update_plan.py`
    (`test_pasta_vazia_com_banco_cheio_tambem_e_recusada`): a pasta
    continua existindo, mas está vazia enquanto o índice não está —
    `detect_changes` levanta `SourceFolderUnavailable` nesse caso porque
    lê-la como "tudo foi removido" seria a própria falha de segurança que
    a exceção existe para evitar.
    """
    for item in tmp_path.joinpath("origem").iterdir():
        item.unlink()


def test_o_aviso_nao_aparece_quando_a_pasta_de_origem_sumiu(tmp_path, monkeypatch):
    """A guarda mais importante: uma pasta de origem inacessível nunca vira
    um aviso alarmante na tela de Execução — só a tela dedicada explica o
    motivo (ver o teste seguinte)."""
    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)
    _esvaziar_pasta_de_origem(tmp_path)

    corpo = cliente.get(f"/projects/{projeto_id}/update/banner").text

    assert corpo.strip() == ""


def test_a_tela_de_atualizacao_explica_a_pasta_de_origem_sumida(tmp_path, monkeypatch):
    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)
    _esvaziar_pasta_de_origem(tmp_path)

    resposta = cliente.get(f"/projects/{projeto_id}/update")

    assert resposta.status_code == 409
    assert "não pode ser lida" in resposta.text  # update.source_unavailable (pt)


def test_todas_as_chaves_da_atualizacao_existem_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    chaves = (
        "update.title", "update.banner", "update.new", "update.changed",
        "update.removed", "update.files_ocr", "update.windows_discarded",
        "update.windows_kept", "update.new_windows_unknown", "update.confirm",
        "update.cancel", "update.nothing_changed", "update.source_unavailable",
        "update.plan_expired", "update.cost_title",
    )
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            texto = translate(idioma, chave)
            assert texto and not texto.startswith("update."), f"{idioma}/{chave}"


# --- Task 11: the oracle ----------------------------------------------------
#
# The correctness criterion of the whole feature: an incremental update is
# right if, and only if, its result cannot be told apart from a full
# reindex of the same final folder.

# Matches the ISO instant that `artifacts._now_iso()` stamps on every
# generated file ("2026-09-12T14:33:01"). Deliberately a full pattern and
# not the brief's "starts with 20" heuristic: that one would also drop a
# legitimate line beginning with "20" — an item dated "2024-..." in
# `timeline.md`, say — and a silently dropped line is a divergence the
# oracle would never see.
_CARIMBO_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _texto_de_pagina(rotulo: str, numero: int) -> str:
    """Enough native text that `_pdf_needs_ocr` never fires.

    The threshold is an average of 100 characters per page; below it the
    conversion calls `ocrmypdf`, which need not exist on the machine
    running the suite — and an OCR pass would make the two sides of the
    oracle depend on a binary instead of on the code under test.
    """
    return (
        f"{rotulo} - pagina {numero}. Documento de teste com texto nativo "
        "suficiente para que a conversao nao trate a pagina como digitalizada. "
        f"Referencia interna {rotulo}-{numero:03d} do acervo de verificacao."
    )


def _pdf_de_paginas(caminho: Path, rotulo: str, paginas: int) -> None:
    """A PDF with `paginas` text pages, deterministic for a given label."""
    import fitz

    documento = fitz.open()
    try:
        for numero in range(1, paginas + 1):
            pagina = documento.new_page()
            pagina.insert_textbox(
                (50, 50, 550, 750), _texto_de_pagina(rotulo, numero), fontsize=11
            )
        documento.save(caminho)
    finally:
        documento.close()


def _etapas_depois_do_scan(conn, config: ProjectConfig) -> None:
    """Da conversão aos artefatos. Mesma ordem de `background_runs.STEP_ORDER`.

    Serves both sides of the oracle: after the `scan`, in a brand-new
    project, and after the invalidation, in an updated one — where the
    invalidation has already put every known file into the state these
    steps look for.
    """
    from gclaude_indexer.artifacts import generate_all_artifacts
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.import_items import import_and_consolidate
    from gclaude_indexer.orchestrator import run_classification
    from gclaude_indexer.windows_prep import prepare_windows

    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    run_classification(conn, config)
    import_and_consolidate(conn, config)
    generate_all_artifacts(conn, config, "pt")


def _config_do_oraculo(origem: Path, saida: Path) -> ProjectConfig:
    """`rules` engine: deterministic, no model, no cost.

    Small windows on purpose, so a ten-page document spans several of
    them. With a single window per group the update could only ever
    discard everything, and the window preservation the feature exists
    for would never be exercised at all.
    """
    return ProjectConfig(
        name="acervo",
        source_folder=str(origem),
        output_folder=str(saida),
        group_mode="all_together",
        extensions=["pdf"],
        classification_engine="rules",
        pages_per_window=ORACULO_PAGINAS_POR_JANELA,
        overlap=ORACULO_SOBREPOSICAO,
    )


def _rodar_pipeline_completo(
    origem: Path, saida: Path
) -> tuple[sqlite3.Connection, ProjectConfig]:
    """Pipeline inteiro, do zero, sobre a pasta como ela estiver agora."""
    from gclaude_indexer.scanning import scan

    config = _config_do_oraculo(origem, saida)
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)

    scan(conn, config)
    _etapas_depois_do_scan(conn, config)
    return conn, config


def _sem_carimbo(texto: str) -> str:
    """Remove a linha de data, a única coisa que difere legitimamente."""
    return "\n".join(
        linha for linha in texto.splitlines() if not _CARIMBO_ISO.search(linha)
    )


def _secao_de_removidos(review_md: str) -> str:
    """O trecho de `review.md` entre o título da seção de removidos e o da
    seção seguinte.

    Recebe o texto **bruto**, nunca o filtrado. `generate_review_md` (
    `artifacts.py:295`) renderiza cada remoção numa linha só — ``- `nome`
    (instante ISO)`` — e `_sem_carimbo` descarta a linha inteira, isto é,
    justamente a única que nomeia o arquivo. O filtro existe para tornar
    justa a comparação de igualdade dos outros três artefatos; uma
    verificação de conteúdo não precisa dele e só é prejudicada por ele.

    E o recorte por seção, em vez de procurar o nome no arquivo todo:
    `review.md` termina com até cinquenta eventos de erro, e um deles
    citando o documento faria uma busca solta passar sem que a seção de
    removidos dissesse coisa alguma.
    """
    from gclaude_indexer.i18n import translate

    inicio = f"## {translate('pt', 'artifact.review.removed_section')}"
    fim = f"## {translate('pt', 'artifact.review.errors_section')}"

    _antes, marcador, resto = review_md.partition(inicio)
    assert marcador, "review.md sem a seção de documentos removidos"
    secao, _marcador_final, _depois = resto.partition(fim)
    return secao


def _montar_acervo_inicial(origem: Path) -> None:
    origem.mkdir()
    _pdf_de_paginas(origem / "01-contrato.pdf", "CONTRATO", 10)
    _pdf_de_paginas(origem / "02-recibo.pdf", "RECIBO", 10)
    _pdf_de_paginas(origem / "03-carta.pdf", "CARTA", 10)


def _mudar_o_acervo(origem: Path) -> None:
    """Um acrescentado, um alterado, um removido — as três mudanças que a
    invalidação trata por caminhos diferentes."""
    _pdf_de_paginas(origem / "04-aditivo.pdf", "ADITIVO", 6)
    _pdf_de_paginas(origem / "02-recibo.pdf", "RECIBO REVISTO", 12)
    (origem / "03-carta.pdf").unlink()


def test_atualizar_produz_o_mesmo_que_reindexar_do_zero(tmp_path):
    """O critério de correção da funcionalidade inteira.

    Um acervo é montado e indexado. Depois um documento é acrescentado,
    outro alterado e um terceiro removido, e o acervo é atualizado. Em
    paralelo, um projeto novo é construído do zero sobre a pasta final. Os
    artefatos gerados têm de ser iguais.
    """
    from gclaude_indexer.invalidation import apply_update_plan
    from gclaude_indexer.scanning import scan
    from gclaude_indexer.update_plan import build_update_plan

    origem = tmp_path / "origem"
    _montar_acervo_inicial(origem)

    incremental = tmp_path / "incremental"
    incremental.mkdir()
    conn, config = _rodar_pipeline_completo(origem, incremental)

    _mudar_o_acervo(origem)

    # Nothing may touch the source folder between building the plan and
    # applying it: `apply_update_plan` re-derives its own plan and compares
    # fingerprints, and a folder that moved on raises `PlanExpired`.
    plano = build_update_plan(conn, config)

    # --- the oracle's own fixture, pinned -------------------------------
    #
    # These are not a second copy of the unit tests: they are what stops
    # this test from degenerating into a tautology. The comparison below
    # only means something while the left-hand side is an *incremental*
    # update. If some later change made every update discard its whole
    # group — a different default `pages_per_window`, a stricter
    # `_layout_disagrees`, anything — both sides would quietly become full
    # reindexes, the equality would still hold, and the oracle would be
    # comparing two full reindexes agreeing with each other while the
    # feature's entire value had evaporated. That is the same failure the
    # brief's original three-text-file fixture had; the data was fixed,
    # and this is the contract. Do not delete them to simplify the test:
    # deleting them deletes the test's meaning.
    (grupo,) = plano.groups
    assert grupo.discard_whole_group is False
    assert grupo.windows_kept == ORACULO_JANELAS_PRESERVADAS
    assert grupo.windows_discarded == ORACULO_JANELAS_DESCARTADAS

    resultado = apply_update_plan(conn, config, plano)

    # And that the apply really walked the incremental path, rather than
    # reporting a plan it did not carry out. A run that pruned nothing
    # never exercised what the oracle exists to prove.
    assert resultado.windows_deleted == ORACULO_JANELAS_DESCARTADAS
    assert resultado.items_pruned > 0
    assert resultado.prune_failures == 0

    # The `scan` still runs: the invalidation puts the *known* files into
    # the states the later steps look for, but only the scan brings a
    # brand-new file into the `file` table. It is the first step of the
    # rerun, exactly as on the execution screen.
    scan(conn, config)
    _etapas_depois_do_scan(conn, config)
    conn.close()

    # And the same collection, indexed from scratch.
    completo = tmp_path / "completo"
    completo.mkdir()
    conn_completo, _ = _rodar_pipeline_completo(origem, completo)
    conn_completo.close()

    for nome in ("index.md", "timeline.md", "review.md", "project_instructions.md"):
        if nome == "review.md":
            # The one artifact that legitimately differs: the updated
            # project knows about the removal and reports it, while the
            # from-scratch one never saw the document exist. The assertion
            # is that whole asymmetry — present in one side's removals
            # section, absent from the other's — and it runs on the raw
            # text, for the reason `_secao_de_removidos` explains.
            removidos_atualizado = _secao_de_removidos(
                (incremental / nome).read_text(encoding="utf-8")
            )
            removidos_do_zero = _secao_de_removidos(
                (completo / nome).read_text(encoding="utf-8")
            )
            assert "03-carta.pdf" in removidos_atualizado
            assert "03-carta.pdf" not in removidos_do_zero
            continue

        atualizado = _sem_carimbo((incremental / nome).read_text(encoding="utf-8"))
        do_zero = _sem_carimbo((completo / nome).read_text(encoding="utf-8"))

        if nome == "index.md":
            # Non-vacuity guard, and part of the same defence as the plan
            # assertions above: two empty files compare equal. Without
            # this, an `index.md` that lost its table — or a collection
            # that silently indexed nothing — would still satisfy the
            # equality and the oracle would report success over a pair of
            # blanks. Naming a document that must be in the table makes
            # the comparison prove that there was something to compare.
            assert "01-contrato.pdf" in atualizado

        assert atualizado == do_zero, f"{nome} diverge"


def test_reexecutar_sem_mudanca_nao_reprocessa_nada(tmp_path):
    """A incrementalidade que já existia por acidente passa a ter contrato."""
    from gclaude_indexer.update_plan import build_update_plan

    origem = tmp_path / "origem"
    origem.mkdir()
    _pdf_de_paginas(origem / "a.pdf", "DOCUMENTO", 10)
    saida = tmp_path / "saida"
    saida.mkdir()
    conn, config = _rodar_pipeline_completo(origem, saida)
    janelas_antes = dict(conn.execute("SELECT key, status FROM window"))

    plano = build_update_plan(conn, config)

    assert plano.is_empty
    assert plano.groups == ()
    assert dict(conn.execute("SELECT key, status FROM window")) == janelas_antes
    conn.close()

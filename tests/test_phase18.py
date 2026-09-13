# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 18: relatórios que avisam quando estão velhos.

O caso real que originou a fase: um acervo recebeu três documentos, o
pipeline os processou até a classificação, e os quatro `.md` continuaram
descrevendo o estado anterior — 13 arquivos quando o banco já tinha 16, e
2264 peças quando 537 classificações novas esperavam importação. Nada na
interface dizia isso. O usuário só descobriu lendo os números à mão.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from gclaude_indexer import db
from gclaude_indexer.config import ProjectConfig


def _conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "project.db")
    db.init_schema(connection)
    return connection


def _config(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo",
        source_folder=str(origem),
        output_folder=str(saida),
        group_mode="all_together",
        extensions=["pdf"],
    )


def _arquivo(conn, relative_path: str, status: str, paginas: int = 0, grupo: str = "g") -> int:
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status)"
        " VALUES (?, ?, 'pdf', 1, ?, ?, ?)",
        (relative_path, Path(relative_path).name, relative_path, grupo, status),
    )
    file_id = conn.execute(
        "SELECT id FROM file WHERE relative_path = ?", (relative_path,)
    ).fetchone()[0]
    for numero in range(1, paginas + 1):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
            (file_id, numero, f"f. {numero}"),
        )
    conn.commit()
    return file_id


def _janela(conn, key: str, status: str, grupo: str = "g") -> None:
    conn.execute(
        "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
        " VALUES (?, ?, 'f. 1', 'f. 2', ?)",
        (key, grupo, status),
    )
    conn.commit()


def _peca(conn, grupo: str = "g") -> None:
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order,"
        " engine, confidence, files) VALUES (?, 'f. 1', 'f. 1', 1, 1, 'rules', 'high', 'a.pdf')",
        (grupo,),
    )
    conn.commit()


# --- a lacuna do review.md -------------------------------------------------


def test_o_review_conta_os_arquivos_marcados_como_duplicata(tmp_path):
    """A lista de cobertura ignorava `duplicate`, então um arquivo que
    entrasse como cópia de outro sumia do relatório sem deixar rastro."""
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _arquivo(conn, "original.pdf", "extracted")
    _arquivo(conn, "copia.pdf", "duplicate")

    texto = generate_review_md(conn, _config(tmp_path, saida), "pt").read_text(encoding="utf-8")

    assert "- duplicate: 1" in texto
    assert "- extracted: 1" in texto


def test_a_cobertura_do_review_cobre_todos_os_status_que_o_pipeline_grava(tmp_path):
    """Guarda contra a mesma falha voltar por um status novo: todo valor
    que o código grava em `file.status` tem de aparecer no relatório."""
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    gravados = ("discovered", "converted", "extracted", "failed", "duplicate", "skipped")
    for status in gravados:
        _arquivo(conn, f"{status}.pdf", status)

    texto = generate_review_md(conn, _config(tmp_path, saida), "pt").read_text(encoding="utf-8")

    for status in gravados:
        assert f"- {status}: 1" in texto, status


# --- o estado que os artefatos descrevem -----------------------------------


def test_a_tabela_de_estado_nasce_na_abertura_e_aceita_abrir_duas_vezes(tmp_path):
    conn = _conn(tmp_path)
    db.init_schema(conn)

    tabelas = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "artifact_state" in tabelas


def test_um_projeto_anterior_ganha_a_tabela_sem_passo_manual(tmp_path):
    """Projeto criado na 1.1.0 não tem a tabela; abrir na 1.2.0 a cria."""
    conn = db.connect(tmp_path / "project.db")
    conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    conn.commit()

    db.init_schema(conn)

    tabelas = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "artifact_state" in tabelas


def test_gerar_os_artefatos_registra_o_estado_que_eles_descrevem(tmp_path):
    from gclaude_indexer.artifacts import generate_all_artifacts

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    _janela(conn, "g::000001-000002", "done")
    _peca(conn)

    generate_all_artifacts(conn, _config(tmp_path, saida), "pt")

    gravado = conn.execute(
        "SELECT files, windows_done, items FROM artifact_state WHERE id = 1"
    ).fetchone()
    assert tuple(gravado) == (1, 1, 1)


def test_gerar_de_novo_substitui_o_estado_em_vez_de_acumular(tmp_path):
    from gclaude_indexer.artifacts import generate_all_artifacts

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    config = _config(tmp_path, saida)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")

    _arquivo(conn, "b.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")

    linhas = conn.execute("SELECT COUNT(*) FROM artifact_state").fetchone()[0]
    assert linhas == 1
    assert conn.execute("SELECT files FROM artifact_state").fetchone()[0] == 2


# --- o diagnóstico ---------------------------------------------------------


def test_sem_registro_nenhum_nada_e_acusado(tmp_path):
    """Projeto vindo de uma versão anterior não tem registro. Acusar
    desatualização aí seria alarme falso: não há com o que comparar."""
    from gclaude_indexer.artifacts import stale_artifacts

    conn = _conn(tmp_path)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)

    assert stale_artifacts(conn) is None


def test_estado_igual_nao_e_acusado(tmp_path):
    from gclaude_indexer.artifacts import generate_all_artifacts, stale_artifacts

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    _janela(conn, "g::000001-000002", "done")
    generate_all_artifacts(conn, _config(tmp_path, saida), "pt")

    assert stale_artifacts(conn) is None


def test_o_caso_real_arquivos_novos_classificados_sem_importar(tmp_path):
    """Reproduz o acervo que originou a fase: os relatórios descreviam 13
    arquivos e 307 janelas enquanto o banco já tinha 16 e 378, e as peças
    novas ainda não tinham sido importadas."""
    from gclaude_indexer.artifacts import generate_all_artifacts, stale_artifacts

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    config = _config(tmp_path, saida)
    for numero in range(13):
        _arquivo(conn, f"antigo{numero}.pdf", "extracted", paginas=2)
    for numero in range(307):
        _janela(conn, f"g::{numero:06d}", "done")
    _peca(conn)
    generate_all_artifacts(conn, config, "pt")

    # Os três documentos novos entram e são classificados, mas ninguém
    # clicou em "importar e gerar relatórios".
    for numero in range(3):
        _arquivo(conn, f"novo{numero}.pdf", "extracted", paginas=2, grupo="cdc")
    for numero in range(71):
        _janela(conn, f"cdc::{numero:06d}", "done", grupo="cdc")

    desatualizado = stale_artifacts(conn)

    assert desatualizado is not None
    assert desatualizado.recorded.files == 13
    assert desatualizado.current.files == 16
    assert desatualizado.recorded.windows_done == 307
    assert desatualizado.current.windows_done == 378


def test_peca_importada_depois_tambem_acusa(tmp_path):
    from gclaude_indexer.artifacts import generate_all_artifacts, stale_artifacts

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, _config(tmp_path, saida), "pt")

    _peca(conn)

    desatualizado = stale_artifacts(conn)
    assert desatualizado is not None
    assert desatualizado.current.items == 1
    assert desatualizado.recorded.items == 0


# --- as duas telas ---------------------------------------------------------


def _app_com_projeto(tmp_path, monkeypatch):
    """Servidor de teste com um projeto pronto, sem tocar no estado real
    da máquina — mesmo isolamento por variável de ambiente da fase 17."""
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
        " VALUES (?, ?, ?, ?, '2026-09-13T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()

    entry = register_project(config.name, str(saida))
    return TestClient(app), entry.id, conn, config


def test_a_tela_de_resultado_avisa_que_os_relatorios_sao_anteriores(tmp_path, monkeypatch):
    from gclaude_indexer.artifacts import generate_all_artifacts

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")
    _arquivo(conn, "b.pdf", "extracted", paginas=2)

    corpo = cliente.get(f"/projects/{projeto_id}/result").text

    assert 'id="stale-artifacts"' in corpo
    assert f"/projects/{projeto_id}/import-and-generate" in corpo


def test_a_tela_de_resultado_nao_avisa_quando_esta_em_dia(tmp_path, monkeypatch):
    from gclaude_indexer.artifacts import generate_all_artifacts

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")

    corpo = cliente.get(f"/projects/{projeto_id}/result").text

    assert 'id="stale-artifacts"' not in corpo


def test_a_execucao_avisa_quando_nao_ha_mais_o_que_processar(tmp_path, monkeypatch):
    from gclaude_indexer.artifacts import generate_all_artifacts

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")
    _arquivo(conn, "b.pdf", "extracted", paginas=2)
    _janela(conn, "g::000001-000002", "done")

    corpo = cliente.get(f"/projects/{projeto_id}/run").text

    assert 'id="stale-artifacts"' in corpo


def test_a_execucao_nao_manda_gerar_relatorio_com_trabalho_pendente(tmp_path, monkeypatch):
    """Com janela pendente o conselho certo é rodar as etapas, não gerar
    relatório — o aviso de desatualizado atrapalharia em vez de ajudar."""
    from gclaude_indexer.artifacts import generate_all_artifacts

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _arquivo(conn, "a.pdf", "extracted", paginas=2)
    generate_all_artifacts(conn, config, "pt")
    _arquivo(conn, "b.pdf", "extracted", paginas=2)
    _janela(conn, "g::000001-000002", "pending")

    corpo = cliente.get(f"/projects/{projeto_id}/run").text

    assert 'id="stale-artifacts"' not in corpo


def test_as_chaves_novas_existem_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    chaves = (
        "result.stale_title",
        "result.stale_explanation",
        "result.stale_regenerate",
        "run.stale_artifacts",
    )
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            texto = translate(idioma, chave)
            assert texto and not texto.startswith(("result.", "run.")), f"{idioma}/{chave}"

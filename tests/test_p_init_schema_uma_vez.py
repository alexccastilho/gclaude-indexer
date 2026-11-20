"""Etapa P: `load_project` roda `init_schema` uma vez por banco no processo.

A tela de Execução reabre o projeto a cada 2 s enquanto uma etapa grava, e
`init_schema` são umas trinta instruções e um commit num banco que costuma
estar no Drive. O atalho não pode esconder um banco que precisa da
migração: esquema mudado por outra conexão, ou arquivo trocado no disco."""

from __future__ import annotations

import shutil
import sqlite3

from gclaude_indexer import project as project_mod
from gclaude_indexer.config import load_config
from gclaude_indexer.project import create_project, load_project


def _projeto(tmp_path, nome="saida"):
    origem = tmp_path / "origem"
    origem.mkdir(exist_ok=True)
    config = load_config({"name": "P", "source_folder": str(origem), "output_folder": str(tmp_path / nome)})
    conn, _ = create_project(config)
    conn.close()
    return tmp_path / nome


def _indices(pasta):
    conn = sqlite3.connect(pasta / "project.db")
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()


def _contar_init(monkeypatch):
    chamadas = []
    original = project_mod.init_schema

    def contando(conn):
        chamadas.append(1)
        original(conn)

    monkeypatch.setattr(project_mod, "init_schema", contando)
    return chamadas


def test_segunda_abertura_nao_refaz_o_esquema(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path)
    chamadas = _contar_init(monkeypatch)
    for _ in range(3):
        _config, conn = load_project(pasta)
        conn.close()
    assert chamadas == [1]


def test_esquema_mudado_por_fora_volta_a_ser_migrado(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path)
    _config, conn = load_project(pasta)
    conn.close()
    outra = sqlite3.connect(pasta / "project.db")
    outra.execute("DROP INDEX idx_window_status")
    outra.commit()
    outra.close()
    assert "idx_window_status" not in _indices(pasta)

    _config, conn = load_project(pasta)
    conn.close()

    assert "idx_window_status" in _indices(pasta)


def test_banco_trocado_no_disco_volta_a_ser_migrado(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path)
    copia = _projeto(tmp_path, "copia")
    _config, conn = load_project(pasta)
    versao = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.close()
    outra = sqlite3.connect(copia / "project.db")
    outra.execute("DROP INDEX idx_window_status")
    outra.commit()
    outra.execute(f"PRAGMA schema_version = {versao}")
    outra.commit()
    assert outra.execute("PRAGMA schema_version").fetchone()[0] == versao
    outra.close()

    # Um banco do mesmo esquema (mesmo schema_version) chega por cima do
    # primeiro, como numa restauração ou numa sincronização do Drive.
    (pasta / "project.db").unlink()
    shutil.copy2(copia / "project.db", pasta / "project.db")
    chamadas = _contar_init(monkeypatch)
    _config, conn = load_project(pasta)
    conn.close()

    assert chamadas == [1]
    assert "idx_window_status" in _indices(pasta)


def test_banco_regravado_no_lugar_volta_a_ser_migrado(tmp_path, monkeypatch):
    """Gravado por cima do mesmo arquivo (mesmo id e mesma data de criação),
    com o mesmo schema_version e um esquema diferente."""
    pasta = _projeto(tmp_path)
    copia = _projeto(tmp_path, "copia")
    _config, conn = load_project(pasta)
    versao = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.close()
    outra = sqlite3.connect(copia / "project.db")
    outra.execute("DROP INDEX idx_window_status")
    outra.commit()
    outra.execute(f"PRAGMA schema_version = {versao}")
    outra.commit()
    outra.close()

    (pasta / "project.db").write_bytes((copia / "project.db").read_bytes())
    _config, conn = load_project(pasta)
    conn.close()

    assert "idx_window_status" in _indices(pasta)

# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.9.1: faster navigation and the author fixes.

- The screens that only read keep one read-only connection per open project
  (`web/readers.py`), so SQLite's page cache survives between requests.
- `/projects` no longer opens every project's database when nothing changed.
- The update plan reads the `file` table once and hashes new files only
  when it has to.
- Authors: "null", the same name in different case, citations of norms.
"""

from __future__ import annotations

import os
import sqlite3
import time

import pytest

from gclaude_indexer.web.readers import ReaderPool, reader_pool
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def _pasta_de(pid):
    from gclaude_indexer.catalog import find_project

    return find_project(pid).output_folder


# --- the persistent reader ---------------------------------------------------

def test_a_tela_reaproveita_a_mesma_conexao(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path)
    assert cliente.get(f"/projects/{pid}/run").status_code == 200
    assert cliente.get(f"/projects/{pid}/run/steps").status_code == 200
    leitor = reader_pool.acquire(_pasta_de(pid))
    assert leitor is not None
    conexao = leitor.conn
    reader_pool.release(leitor)
    assert cliente.get(f"/projects/{pid}/run/steps").status_code == 200
    leitor = reader_pool.acquire(_pasta_de(pid))
    assert leitor.conn is conexao
    reader_pool.release(leitor)


def test_a_conexao_de_leitura_nao_grava(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    leitor = reader_pool.acquire(_pasta_de(pid))
    try:
        with pytest.raises(sqlite3.OperationalError):
            leitor.conn.execute("CREATE TABLE x (a)")
    finally:
        reader_pool.release(leitor)


def test_banco_trocado_por_fora_reabre_a_conexao(cliente, tmp_path):
    """Google Drive replacing project.db with the other computer's copy."""
    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    pasta = _pasta_de(pid)
    leitor = reader_pool.acquire(pasta)
    antiga = leitor.conn
    reader_pool.release(leitor)
    banco = os.path.join(str(pasta), "project.db")
    info = os.stat(banco)
    os.utime(banco, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
    leitor = reader_pool.acquire(pasta)
    assert leitor.conn is not antiga
    reader_pool.release(leitor)


def test_o_que_outra_conexao_grava_aparece_na_hora(cliente, tmp_path):
    from gclaude_indexer import db

    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    pasta = _pasta_de(pid)
    leitor = reader_pool.acquire(pasta)
    antes = leitor.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    reader_pool.release(leitor)
    conn = db.connect(os.path.join(str(pasta), "project.db"))
    conn.execute("INSERT INTO event (step, level, message, created_at) VALUES ('teste', 'info', 'x', '2026-11-03')")
    conn.commit()
    conn.close()
    leitor = reader_pool.acquire(pasta)
    assert leitor.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == antes + 1
    reader_pool.release(leitor)


def test_apagar_o_projeto_fecha_o_leitor(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    cliente.get(f"/projects/{pid}/run/steps")
    pasta = _pasta_de(pid)
    from gclaude_indexer.lock import LockManager

    assert LockManager._key(pasta) in reader_pool._readers
    reader_pool.close(pasta)
    assert LockManager._key(pasta) not in reader_pool._readers


def test_leitor_parado_fecha_sozinho(tmp_path, cliente):
    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    cliente.get(f"/projects/{pid}/run/steps")
    assert reader_pool._readers
    reader_pool.close_idle(now=time.monotonic() + 10_000)
    assert not reader_pool._readers


def test_sem_banco_nao_ha_leitor(tmp_path):
    assert ReaderPool().acquire(tmp_path) is None


def test_desligado_cai_na_conexao_normal(cliente, tmp_path, monkeypatch):
    pid = _criar_projeto(cliente, tmp_path)
    monkeypatch.setattr(reader_pool, "enabled", False)
    assert cliente.get(f"/projects/{pid}/run").status_code == 200
    assert cliente.get(f"/projects/{pid}/run/steps").status_code == 200
    assert not reader_pool._readers


class _ConexaoOcupada:
    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")


@pytest.mark.parametrize("rota", ["run/steps", "run/progress"])
def test_leitor_com_banco_ocupado_devolve_204(cliente, tmp_path, rota):
    pid = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{pid}/run")
    cliente.get(f"/projects/{pid}/run/steps")
    leitor = reader_pool.acquire(_pasta_de(pid))
    verdadeira = leitor.conn
    leitor.conn = _ConexaoOcupada()
    reader_pool.release(leitor)
    try:
        resposta = cliente.get(f"/projects/{pid}/{rota}", headers={"HX-Request": "true"})
        assert resposta.status_code == 204
    finally:
        leitor.conn = verdadeira


# --- /projects ---------------------------------------------------------------

def test_lista_de_projetos_nao_reabre_banco_que_nao_mudou(tmp_path, monkeypatch):
    from gclaude_indexer import db
    from gclaude_indexer.web import step_state

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    conn.close()
    chamadas = []
    original = step_state._project_status

    def contando(pasta):
        chamadas.append(pasta)
        return ("not_started", {})

    monkeypatch.setattr(step_state, "_project_status", contando)
    step_state._status_cache.clear()
    assert step_state.project_status(str(saida)) == ("not_started", {})
    assert step_state.project_status(str(saida)) == ("not_started", {})
    assert len(chamadas) == 1
    banco = saida / "project.db"
    info = os.stat(banco)
    os.utime(banco, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
    step_state.project_status(str(saida))
    assert len(chamadas) == 2
    assert original is not contando


# --- update plan: hashing only when the size is taken ------------------------

def test_arquivo_novo_de_tamanho_unico_nao_e_lido(tmp_path, monkeypatch):
    from gclaude_indexer import update_plan
    from tests.test_phase39 import _acervo, _config

    origem, saida, conn = _acervo(tmp_path)
    lidos = []
    real = update_plan.compute_hash

    def contando(caminho):
        lidos.append(caminho.name)
        return real(caminho)

    monkeypatch.setattr(update_plan, "compute_hash", contando)
    # "igual" (5 bytes) and "sumiu" (5 bytes) are indexed; "novo" has 4.
    (origem / "sub" / "copia.pdf").write_text("igual", encoding="utf-8")
    (origem / "sub" / "outra.pdf").write_text("nova", encoding="utf-8")  # 4 bytes, like "novo"
    (origem / "sub" / "unico.pdf").write_text("tamanho unico", encoding="utf-8")
    config = _config(origem, saida)
    changes = [c for c in update_plan.detect_changes(conn, config)[0] if c.kind == "new"]
    membros = dict(update_plan._intended_membership(conn, config, origem, changes, {"sumiu.pdf"}))

    assert "sub/copia.pdf" not in membros          # duplicate of igual.pdf
    assert "sub/novo.pdf" in membros and "sub/outra.pdf" in membros
    assert "sub/unico.pdf" in membros              # never read
    assert sorted(lidos) == ["copia.pdf", "novo.pdf", "outra.pdf"]
    conn.close()


def test_duplicata_entre_arquivos_novos_continua_achada(tmp_path):
    from gclaude_indexer import update_plan
    from tests.test_phase39 import _acervo, _config

    origem, saida, conn = _acervo(tmp_path)
    (origem / "sub" / "zz_copia.pdf").write_text("novo", encoding="utf-8")
    config = _config(origem, saida)
    changes = [c for c in update_plan.detect_changes(conn, config)[0] if c.kind == "new"]
    membros = dict(update_plan._intended_membership(conn, config, origem, changes, set()))
    assert "sub/novo.pdf" in membros
    assert "sub/zz_copia.pdf" not in membros
    conn.close()


# --- authors -------------------------------------------------------------------

def _peca(autor, engine="local", **extra):
    base = {"group": "g", "order_start": 1, "order_end": 1, "type": "OFÍCIO",
            "author": autor, "engine": engine, "summary": "s", "date": None}
    base.update(extra)
    return base


def test_null_vira_vazio():
    from gclaude_indexer.item_normalize import clean_placeholders

    pecas = [_peca("null"), _peca("N/A", date="null"), _peca("Maria Souza"), _peca("  ")]
    assert clean_placeholders(pecas) == 3
    assert [p["author"] for p in pecas] == [None, None, "Maria Souza", None]
    assert pecas[1]["date"] is None


def test_mesmo_autor_em_caixa_diferente_vira_uma_grafia():
    from gclaude_indexer.item_normalize import clean_authors

    pecas = [_peca("LUIZ INÁCIO LULA DA SILVA") for _ in range(5)] + [_peca("Luiz Inácio Lula da Silva")]
    pecas.append(_peca("XPTO"))
    clean_authors(pecas)
    assert {p["author"] for p in pecas[:6]} == {"Luiz Inácio Lula da Silva"}
    assert pecas[6]["author"] == "XPTO"   # only ever in capitals: left alone


def test_mesmo_autor_com_e_sem_acento_vira_uma_grafia():
    from gclaude_indexer.item_normalize import clean_authors

    pecas = [_peca("ANTONIO PEREIRA") for _ in range(3)] + [_peca("ANTÔNIO PEREIRA") for _ in range(2)]
    pecas += [_peca("Jose Antonio Prado") for _ in range(4)] + [_peca("JOSÉ ANTÔNIO PRADO")]
    pecas += [_peca("Ana Lúcia") for _ in range(2)] + [_peca("ANA LUCIA")]
    clean_authors(pecas)
    # Only capitals: the accented spelling wins with half the count.
    assert {p["author"] for p in pecas[:5]} == {"ANTÔNIO PEREIRA"}
    # Mixed case beats capitals even when the capitals carry the accents.
    assert {p["author"] for p in pecas[5:10]} == {"Jose Antonio Prado"}
    assert {p["author"] for p in pecas[10:]} == {"Ana Lúcia"}


def test_citacao_de_norma_nao_e_autor():
    from gclaude_indexer.item_normalize import clean_authors

    pecas = [_peca("Lei nº 9.394/1996"), _peca("Decreto 7.892 de 2013"),
             _peca("Lei Maria da Penha"), _peca("Atos Ferreira")]
    clean_authors(pecas)
    assert [p["author"] for p in pecas] == [None, None, "Lei Maria da Penha", "Atos Ferreira"]


def test_autor_do_planalto_nao_passa_pela_limpeza_geral():
    from gclaude_indexer import planalto
    from gclaude_indexer.item_normalize import clean_authors

    pecas = [_peca("Lei nº 1", engine=planalto.ENGINE)]
    clean_authors(pecas)
    assert pecas[0]["author"] == "Lei nº 1"


def test_pagina_em_branco_nao_avanca_sobre_a_peca_seguinte(tmp_path, monkeypatch):
    from gclaude_indexer import import_items

    paginas = [{"reference": f"f. {n}"} for n in range(1, 21)]
    monkeypatch.setattr(import_items, "pages_for_group", lambda conn, g, with_text=False: paginas)
    pecas = [
        _peca(None, type="PÁGINA EM BRANCO", order_start=14, order_end=15, ref_start="f. 14", ref_end="f. 15"),
        _peca("Ana", order_start=15, order_end=18, ref_start="f. 15", ref_end="f. 18"),
        _peca("Rui", type="PROCESSO", order_start=19, order_end=20, ref_start="f. 19", ref_end="f. 20"),
    ]
    consolidadas = import_items._consolidate(pecas)
    assert import_items._trim_overlaps(None, consolidadas) == 1
    assert (consolidadas[0]["order_end"], consolidadas[0]["ref_end"]) == (14, "f. 14")
    assert consolidadas[1]["order_start"] == 15


def test_peca_dentro_de_outra_fica_como_esta():
    from gclaude_indexer import import_items

    pecas = [
        _peca("A", type="PROCESSO", order_start=1, order_end=20, ref_start="f. 1", ref_end="f. 20"),
        _peca("B", type="ANEXO", order_start=5, order_end=8, ref_start="f. 5", ref_end="f. 8"),
    ]
    consolidadas = import_items._consolidate(pecas)
    assert import_items._trim_overlaps(None, consolidadas) == 0
    assert consolidadas[0]["order_end"] == 20


def test_estimativa_do_9b_usa_o_tamanho_do_9b(tmp_path, monkeypatch):
    from gclaude_indexer import hardware as hardware_mod
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.hardware import GB_MB, GpuInfo, HardwareDiagnostic

    monkeypatch.setattr(hardware_mod, "_real_model_size_mb", lambda modelo, timeout_s=2.0: None)
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    diagnostico = HardwareDiagnostic(
        gpu=GpuInfo("RX 6700 XT", "AMD", 12 * GB_MB), ram_mb=32 * GB_MB,
        free_space_mb=999_999, checked_folder=str(tmp_path),
        tesseract_present=False, tesseract_path=None,
        ghostscript_present=False, ghostscript_path=None,
        ollama_present=False, ollama_path=None,
    )
    hardware_mod.choose_model(conn, diagnostico, "qwen3.5:9b")
    texto = " ".join(e["message"] for e in list_events(conn, step="diagnostics"))
    assert "6300" in texto and "3232" not in texto
    conn.close()

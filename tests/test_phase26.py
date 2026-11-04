"""1.5.6: o modo econômico e a varredura também não travam mais.

A 1.5.5 protegeu os caminhos com processos auxiliares. Ficaram de fora o
modo econômico (paralelismo 1, um arquivo por vez no próprio processo) e a
varredura (listagem das pastas, `stat` e hash de cada arquivo): ali, um
arquivo que o Google Drive nunca responde ainda congelava a etapa.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from gclaude_indexer import conversion as conversao_mod
from gclaude_indexer import extraction as extracao_mod
from gclaude_indexer import scanning as varredura_mod
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.update_plan import SourceFolderUnavailable, detect_changes
from gclaude_indexer.worker_pool import (
    CallTimedOut, DaemonThreadExecutor, StepStalledError, call_with_deadline,
)


@pytest.fixture
def liberar_presos():
    evento = threading.Event()
    yield evento
    evento.set()


def _banco(tmp_path, nomes, status):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome in nomes:
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', NULL, ?)",
            (nome, nome, status),
        )
    conn.commit()
    return conn


def _config(tmp_path, **campos):
    return ProjectConfig(
        name="p", source_folder=str(tmp_path / "origem"), output_folder=str(tmp_path / "saida"), **campos,
    )


# --- peças --------------------------------------------------------------------------


def test_chamada_com_prazo_desiste_e_nao_espera(liberar_presos):
    inicio = time.monotonic()
    with pytest.raises(CallTimedOut):
        call_with_deadline(liberar_presos.wait, deadline=0.2)
    assert time.monotonic() - inicio < 2


def test_chamada_com_prazo_repassa_resultado_e_excecao():
    assert call_with_deadline(lambda x: x * 2, 21, deadline=5) == 42
    with pytest.raises(FileNotFoundError):
        call_with_deadline(os.stat, "nao/existe/mesmo", deadline=5)


def test_executor_de_threads_usa_threads_daemon(liberar_presos):
    nomes = []

    def trabalho():
        nomes.append(threading.current_thread().daemon)
        return "ok"

    assert DaemonThreadExecutor().submit(trabalho).result(timeout=5) == "ok"
    assert nomes == [True], "uma thread abandonada nunca pode segurar o fechamento do servidor"


# --- modo econômico ---------------------------------------------------------------------


def test_conversao_no_modo_economico_com_arquivo_preso_termina(tmp_path, monkeypatch, liberar_presos):
    def _falso_processar(config, linha, jobs):
        if linha["name"] == "a_preso.txt":
            liberar_presos.wait()
        return {
            "id": linha["id"], "name": linha["name"],
            "sql": "UPDATE file SET status = 'converted', error = NULL WHERE id = ?", "params": (linha["id"],),
            "events": [], "ocr_applied": False, "sliced": False, "blocks_generated": 0,
        }

    monkeypatch.setattr(conversao_mod, "_process_file", _falso_processar)
    monkeypatch.setattr(conversao_mod, "workers_for", lambda modo: 1)
    # 1.5.8: `.txt` vai para a fila dos arquivos leves.
    monkeypatch.setattr(conversao_mod, "io_workers_for", lambda modo: 1)
    monkeypatch.setattr(conversao_mod, "deadline_for_size", lambda tamanho: 0.4)

    conn = _banco(tmp_path, ["a_preso.txt"] + [f"b{i}.txt" for i in range(20)], "discovered")
    inicio = time.monotonic()
    resultado = conversao_mod.convert(conn, _config(tmp_path), language="pt")
    assert time.monotonic() - inicio < 30

    status = {l["name"]: l["status"] for l in conn.execute("SELECT name, status FROM file")}
    conn.close()
    assert status.pop("a_preso.txt") == "failed"
    assert set(status.values()) == {"converted"}
    assert resultado.converted == 20 and resultado.failed == 1


def test_extracao_no_modo_economico_com_arquivo_preso_termina(tmp_path, monkeypatch, liberar_presos):
    def _falso_extrair(config, linha):
        if linha["relative_path"] == "a.txt":
            liberar_presos.wait()
        return [("texto", 0, False)]

    monkeypatch.setattr(extracao_mod, "_extract_file_pages", _falso_extrair)
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 1)
    monkeypatch.setattr(extracao_mod, "deadline_for_size", lambda tamanho: 0.4)
    monkeypatch.setattr(extracao_mod, "index_pending", lambda *a, **k: None)

    conn = _banco(tmp_path, ["a.txt"] + [f"b{i}.txt" for i in range(20)], "converted")
    inicio = time.monotonic()
    resultado = extracao_mod.extract_pages(conn, _config(tmp_path), language="pt")
    assert time.monotonic() - inicio < 30

    status = {l["relative_path"]: l["status"] for l in conn.execute("SELECT relative_path, status FROM file")}
    conn.close()
    assert status.pop("a.txt") == "failed"
    assert set(status.values()) == {"extracted"}
    assert resultado.files_processed == 20


def test_modo_economico_preserva_numeracao_de_folhas(tmp_path, monkeypatch):
    """Um arquivo por vez continua numerando as folhas na ordem do agrupador."""
    monkeypatch.setattr(extracao_mod, "_extract_file_pages", lambda config, linha: [("p", 0, False)] * 2)
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 1)
    monkeypatch.setattr(extracao_mod, "index_pending", lambda *a, **k: None)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome in ("g/1.txt", "g/2.txt", "g/10.txt"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', 'g', 'converted')",
            (nome, nome),
        )
    conn.commit()
    extracao_mod.extract_pages(conn, _config(tmp_path))
    referencias = [
        (l["relative_path"], l["reference"]) for l in conn.execute(
            "SELECT f.relative_path, p.reference FROM page p JOIN file f ON f.id = p.file_id ORDER BY p.id"
        )
    ]
    conn.close()
    assert referencias == [
        ("g/1.txt", "f. 1"), ("g/1.txt", "f. 2"),
        ("g/2.txt", "f. 3"), ("g/2.txt", "f. 4"),
        ("g/10.txt", "f. 5"), ("g/10.txt", "f. 6"),
    ]


# --- varredura ----------------------------------------------------------------------------


def _origem_com_arquivos(tmp_path, quantidade):
    origem = tmp_path / "origem"
    (origem / "pasta").mkdir(parents=True)
    for i in range(quantidade):
        (origem / "pasta" / f"doc{i:02}.txt").write_text(f"conteudo {i}", encoding="utf-8")
    return origem


def test_varredura_com_arquivo_preso_segue_e_deixa_ele_para_a_proxima(tmp_path, monkeypatch, liberar_presos):
    _origem_com_arquivos(tmp_path, 10)
    hash_real = varredura_mod.compute_hash

    def _hash(caminho):
        if caminho.name == "doc03.txt":
            liberar_presos.wait()
        return hash_real(caminho)

    monkeypatch.setattr(varredura_mod, "compute_hash", _hash)
    monkeypatch.setattr(varredura_mod, "deadline_for_size", lambda tamanho: 0.3)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    inicio = time.monotonic()
    resultado = varredura_mod.scan(conn, _config(tmp_path, extensions=["text"]), language="pt")
    assert time.monotonic() - inicio < 15

    nomes = {l["name"] for l in conn.execute("SELECT name FROM file")}
    avisos = conn.execute("SELECT message FROM event WHERE message_key = 'log.scan.file_timed_out'").fetchall()
    assert not conn.in_transaction
    conn.close()
    assert "doc03.txt" not in nomes and len(nomes) == 9
    assert resultado.total_found == 10
    assert avisos and "doc03.txt" in avisos[0]["message"]


def test_varredura_com_disco_travado_para_com_mensagem(tmp_path, monkeypatch, liberar_presos):
    _origem_com_arquivos(tmp_path, 10)
    monkeypatch.setattr(varredura_mod, "compute_hash", lambda caminho: liberar_presos.wait())
    monkeypatch.setattr(varredura_mod, "deadline_for_size", lambda tamanho: 0.2)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    with pytest.raises(StepStalledError, match="Google Drive"):
        varredura_mod.scan(conn, _config(tmp_path, extensions=["text"]), language="pt")
    assert conn.execute("SELECT COUNT(*) FROM file").fetchone()[0] == 0
    assert not conn.in_transaction
    conn.close()


def test_pasta_que_nao_responde_interrompe_a_caminhada(tmp_path, monkeypatch, liberar_presos):
    origem = _origem_com_arquivos(tmp_path, 3)
    scandir_real = os.scandir

    def _scandir(caminho):
        if os.path.basename(str(caminho)) == "pasta":
            liberar_presos.wait()
        return scandir_real(caminho)

    monkeypatch.setattr(varredura_mod.os, "scandir", _scandir)
    monkeypatch.setattr(varredura_mod, "FOLDER_LISTING_DEADLINE_SECONDS", 0.2)

    inicio = time.monotonic()
    with pytest.raises(varredura_mod.SourceFolderStalled) as erro:
        varredura_mod.walk_source_files(origem, tmp_path / "saida")
    assert time.monotonic() - inicio < 5
    assert erro.value.folder.name == "pasta"


def test_plano_de_atualizacao_nunca_le_pasta_travada_como_remocao(tmp_path, monkeypatch, liberar_presos):
    """Uma pasta que não respondeu não pode virar "todos os arquivos dela
    foram removidos" — o plano oferece apagar o que acha removido."""
    origem = _origem_com_arquivos(tmp_path, 3)
    config = _config(tmp_path, extensions=["text"])
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    varredura_mod.scan(conn, config)

    scandir_real = os.scandir

    def _scandir(caminho):
        if os.path.basename(str(caminho)) == "pasta":
            liberar_presos.wait()
        return scandir_real(caminho)

    monkeypatch.setattr(varredura_mod.os, "scandir", _scandir)
    monkeypatch.setattr(varredura_mod, "FOLDER_LISTING_DEADLINE_SECONDS", 0.2)

    with pytest.raises(SourceFolderUnavailable):
        detect_changes(conn, config)
    conn.close()
    assert origem.exists()


def test_chaves_novas_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave, params in (
            ("log.scan.file_timed_out", {"name": "x", "minutes": 10}),
            ("error.folder_stalled", {"folder": "x"}),
        ):
            texto = translate(idioma, chave, **params)
            assert texto and texto != chave

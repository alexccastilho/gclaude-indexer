"""1.5.5: a conversão nunca mais trava, o banco ocupado não vira erro 500.

O que aconteceu em 31/10/2026 (projeto com 145 mil arquivos numa pasta do
Google Drive): o Drive parou de responder a oito aberturas de arquivo, os
oito processos auxiliares ficaram presos para sempre, a etapa encontrou o
banco ocupado, saiu do laço com a transação aberta e ficou esperando os
auxiliares no `shutdown(wait=True)`. O banco ficou travado e as três
consultas da tela de Execução devolviam "Internal Server Error".
"""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
import gclaude_indexer.sensors as sensors_mod
from gclaude_indexer import conversion as conversao_mod
from gclaude_indexer import extraction as extracao_mod
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.db import BatchWriter, connect, init_schema
from gclaude_indexer.events import record_event
from gclaude_indexer.worker_pool import (
    CRASHED, OK, TIMED_OUT, PoolStalledError, ResilientPool, StepStalledError, deadline_for_size,
)


@pytest.fixture
def liberar_presos():
    """Os "travamentos" dos testes são threads esperando um evento. O pool
    não espera por elas (é o ponto); o evento as solta no fim do teste."""
    evento = threading.Event()
    yield evento
    evento.set()


def _pool_de_threads(trabalhadores, **opcoes):
    return ResilientPool(
        lambda: ThreadPoolExecutor(max_workers=trabalhadores),
        trabalhadores,
        poll_seconds=0.02,
        **opcoes,
    )


# --- pool resiliente -----------------------------------------------------------


def test_arquivo_preso_e_reiniciado_e_marcado_como_tempo_esgotado(liberar_presos):
    def trabalho(item):
        if item == "preso":
            liberar_presos.wait()
            return "nunca"
        time.sleep(0.02)
        return item.upper()

    reinicios = []
    itens = ["preso"] + [f"r{i}" for i in range(40)]
    inicio = time.monotonic()
    with _pool_de_threads(
        2, deadline_for=lambda item: 0.3, on_restart=lambda motivo, item: reinicios.append((motivo, item)),
    ) as pool:
        resultados = {o.item: o for o in pool.run(itens, lambda ex, item: ex.submit(trabalho, item))}
    duracao = time.monotonic() - inicio

    assert duracao < 10, "o pool esperou pelo arquivo preso"
    assert resultados["preso"].kind == TIMED_OUT
    assert all(resultados[f"r{i}"].kind == OK and resultados[f"r{i}"].value == f"R{i}" for i in range(40))
    assert reinicios[0] == ("stalled", "preso")
    assert len(reinicios) == 2, "uma segunda tentativa antes de condenar o arquivo"


def test_travamento_geral_interrompe_sem_condenar_ninguem(liberar_presos):
    """Nada termina entre os reinícios: o problema é o disco, não o arquivo.
    O pool desiste com `PoolStalledError` e não devolve tempo esgotado para
    ninguém — o acervo inteiro fica para a próxima execução."""
    def trabalho(item):
        liberar_presos.wait()

    vistos = []
    inicio = time.monotonic()
    with pytest.raises(PoolStalledError):
        with _pool_de_threads(2, deadline_for=lambda item: 0.1) as pool:
            for outcome in pool.run(["a", "b", "c"], lambda ex, item: ex.submit(trabalho, item)):
                vistos.append(outcome)
    assert time.monotonic() - inicio < 10
    assert vistos == []


def test_pausa_com_arquivo_preso_nao_trava(liberar_presos):
    def trabalho(item):
        liberar_presos.wait()

    pausado = threading.Event()
    threading.Timer(0.05, pausado.set).start()
    inicio = time.monotonic()
    with _pool_de_threads(2, deadline_for=lambda item: 0.3, should_stop=pausado.is_set) as pool:
        resultados = list(pool.run(["a", "b", "c", "d"], lambda ex, item: ex.submit(trabalho, item)))
    assert time.monotonic() - inicio < 5
    assert resultados == []


def test_pool_quebrado_e_reconstruido_e_continua():
    """Antes, um processo morto (falta de memória) encerrava a etapa inteira.
    Agora o pool é reconstruído e os arquivos seguintes continuam."""
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    quebrou = {"vez": 0}

    class _QuebraUmaVez:
        def __init__(self):
            self.real = ThreadPoolExecutor(max_workers=2)

        def submit(self, fn, *args):
            if quebrou["vez"] == 0:
                quebrou["vez"] = 1
                futuro = Future()
                futuro.set_exception(BrokenProcessPool("morreu"))
                return futuro
            return self.real.submit(fn, *args)

        def shutdown(self, wait=True, cancel_futures=False):
            self.real.shutdown(wait=wait, cancel_futures=cancel_futures)

    with ResilientPool(_QuebraUmaVez, 2, deadline_for=lambda item: 5, poll_seconds=0.02) as pool:
        resultados = {o.item: o.kind for o in pool.run(list(range(6)), lambda ex, i: ex.submit(lambda x: x, i))}

    assert resultados == {i: OK for i in range(6)}


def test_processo_real_preso_e_morto_e_a_saida_nao_espera():
    """Com processos de verdade: o auxiliar preso (aqui, `time.sleep(120)`)
    é morto ao sair, e sair não espera por ele."""
    from concurrent.futures import ProcessPoolExecutor

    processos = []

    def submeter(executor, segundos):
        futuro = executor.submit(time.sleep, segundos)
        # Anotados aqui: `shutdown` zera `_processes` depois.
        processos.extend(executor._processes.values())
        return futuro

    inicio = time.monotonic()
    with pytest.raises(PoolStalledError):
        with ResilientPool(
            lambda: ProcessPoolExecutor(max_workers=1), 1,
            deadline_for=lambda item: 5, poll_seconds=0.1, max_unhealthy_restarts=1,
        ) as pool:
            list(pool.run([120], submeter))
    assert time.monotonic() - inicio < 60

    assert processos, "o teste precisa ver o processo auxiliar"
    limite = time.monotonic() + 10
    while any(p.is_alive() for p in processos) and time.monotonic() < limite:
        time.sleep(0.1)
    assert not any(p.is_alive() for p in processos)


def test_prazo_cresce_com_o_tamanho():
    assert deadline_for_size(20_000) == pytest.approx(600, abs=5)
    assert deadline_for_size(100 * 1024 * 1024) == pytest.approx(600 + 120 * 100)
    assert deadline_for_size(10**12) == 6 * 3600
    assert deadline_for_size(None) == 600


# --- gravação em lote -------------------------------------------------------------


class _ConexaoQueFalhaNoCommit:
    """`sqlite3.Connection` não aceita atributos novos; o dublê delega tudo
    e faz o commit falhar com "database is locked" nas primeiras vezes."""

    def __init__(self, conn, falhas):
        self._conn = conn
        self.falhas = falhas

    def execute(self, *args):
        return self._conn.execute(*args)

    def rollback(self):
        self._conn.rollback()

    def commit(self):
        if self.falhas > 0:
            self.falhas -= 1
            raise sqlite3.OperationalError("database is locked")
        self._conn.commit()


def test_lote_e_reaplicado_inteiro_depois_de_banco_ocupado(tmp_path):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    dubla = _ConexaoQueFalhaNoCommit(conn, falhas=2)
    escritor = BatchWriter(dubla, max_items=1000, max_seconds=1000, sleep=lambda s: None)

    for i in range(3):
        escritor.add(lambda c, i=i: record_event(c, "conversion", "info", f"evento {i}", commit=False))
    escritor.flush()

    mensagens = [l["message"] for l in conn.execute("SELECT message FROM event ORDER BY id")]
    conn.close()
    assert mensagens == ["evento 0", "evento 1", "evento 2"], "nem perdido, nem duplicado"
    assert escritor.pending == 0


def test_lote_desiste_depois_do_prazo_e_nao_deixa_transacao_aberta(tmp_path):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    dubla = _ConexaoQueFalhaNoCommit(conn, falhas=10**9)
    relogio = iter(range(0, 10**6, 100))
    escritor = BatchWriter(
        dubla, max_items=1000, max_seconds=1000, retry_seconds=250,
        sleep=lambda s: None, clock=lambda: float(next(relogio)),
    )
    escritor.add(lambda c: record_event(c, "conversion", "info", "x", commit=False))
    with pytest.raises(sqlite3.OperationalError):
        escritor.flush()

    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 0
    conn.close()


def test_lote_comita_pelo_tempo(tmp_path):
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    agora = [0.0]
    escritor = BatchWriter(conn, max_items=1000, max_seconds=1.0, clock=lambda: agora[0])
    escritor.add(lambda c: record_event(c, "conversion", "info", "x", commit=False))
    assert escritor.pending == 1
    agora[0] = 1.5
    escritor.flush_if_due()
    assert escritor.pending == 0 and not conn.in_transaction
    conn.close()


def test_banco_usa_journal_truncate(tmp_path):
    conn = connect(tmp_path / "p.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "truncate"
    conn.close()


# --- conversão e extração de ponta a ponta -------------------------------------------


def _banco_com_arquivos(tmp_path, nomes, status):
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


def _config(tmp_path):
    return ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))


def test_conversao_com_arquivo_preso_termina_e_marca_so_ele(tmp_path, monkeypatch, liberar_presos):
    def _falso_processar(config, linha, jobs):
        if linha["name"] == "preso.txt":
            liberar_presos.wait()
        time.sleep(0.02)
        return {
            "id": linha["id"], "name": linha["name"],
            "sql": "UPDATE file SET status = 'converted', error = NULL WHERE id = ?", "params": (linha["id"],),
            "events": [], "ocr_applied": False, "sliced": False, "blocks_generated": 0,
        }

    monkeypatch.setattr(conversao_mod, "ProcessPoolExecutor", lambda max_workers, initializer: ThreadPoolExecutor(max_workers))
    monkeypatch.setattr(conversao_mod, "_process_file", _falso_processar)
    monkeypatch.setattr(conversao_mod, "workers_for", lambda modo: 2)
    monkeypatch.setattr(conversao_mod, "deadline_for_size", lambda tamanho: 0.4)

    nomes = ["a_preso.txt"] + [f"b{i:03}.txt" for i in range(300)]
    conn = _banco_com_arquivos(tmp_path, nomes, "discovered")
    conn.execute("UPDATE file SET name = 'preso.txt' WHERE relative_path = 'a_preso.txt'")
    conn.commit()

    inicio = time.monotonic()
    resultado = conversao_mod.convert(conn, _config(tmp_path), language="pt")
    assert time.monotonic() - inicio < 30

    status = {l["name"]: (l["status"], l["error"]) for l in conn.execute("SELECT name, status, error FROM file")}
    avisos = conn.execute("SELECT message FROM event WHERE message_key = 'log.worker_restarted'").fetchall()
    assert not conn.in_transaction
    conn.close()

    assert status["preso.txt"][0] == "failed"
    assert "tempo esgotado" in status["preso.txt"][1]
    assert all(status[f"b{i:03}.txt"] == ("converted", None) for i in range(300))
    assert resultado.converted == 300 and resultado.failed == 1
    assert avisos, "o reinício dos auxiliares fica registrado no log"


def test_conversao_com_disco_travado_interrompe_com_mensagem_clara(tmp_path, monkeypatch, liberar_presos):
    def _falso_processar(config, linha, jobs):
        liberar_presos.wait()

    monkeypatch.setattr(conversao_mod, "ProcessPoolExecutor", lambda max_workers, initializer: ThreadPoolExecutor(max_workers))
    monkeypatch.setattr(conversao_mod, "_process_file", _falso_processar)
    monkeypatch.setattr(conversao_mod, "workers_for", lambda modo: 2)
    monkeypatch.setattr(conversao_mod, "deadline_for_size", lambda tamanho: 0.2)

    conn = _banco_com_arquivos(tmp_path, ["a.txt", "b.txt", "c.txt"], "discovered")
    with pytest.raises(StepStalledError, match="Google Drive"):
        conversao_mod.convert(conn, _config(tmp_path), language="pt")

    status = {l["name"]: l["status"] for l in conn.execute("SELECT name, status FROM file")}
    assert not conn.in_transaction
    conn.close()
    assert set(status.values()) == {"discovered"}, "nada condenado: fica tudo para a próxima execução"


def test_extracao_com_arquivo_preso_termina(tmp_path, monkeypatch, liberar_presos):
    def _falso_extrair(config, linha):
        if linha["relative_path"] == "a.txt":
            liberar_presos.wait()
        time.sleep(0.02)
        return [("texto", 0, False)]

    monkeypatch.setattr(extracao_mod, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(extracao_mod, "_extract_file_pages", _falso_extrair)
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 2)
    monkeypatch.setattr(extracao_mod, "deadline_for_size", lambda tamanho: 0.4)
    monkeypatch.setattr(extracao_mod, "index_pending", lambda *a, **k: None)

    nomes = ["a.txt"] + [f"b{i:03}.txt" for i in range(300)]
    conn = _banco_com_arquivos(tmp_path, nomes, "converted")
    inicio = time.monotonic()
    resultado = extracao_mod.extract_pages(conn, _config(tmp_path), language="en")
    assert time.monotonic() - inicio < 30

    status = {l["relative_path"]: l["status"] for l in conn.execute("SELECT relative_path, status FROM file")}
    conn.close()
    assert status["a.txt"] == "failed"
    assert resultado.files_processed == 300


# --- tela de Execução ---------------------------------------------------------------


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(sensors_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app_mod.app)


import gclaude_indexer.web.app as app_mod  # noqa: E402  (usado pela fixture acima)


def _criar_projeto(cliente, tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.txt").write_text("texto", encoding="utf-8")
    dados = {
        "name": "Projeto 1.5.5", "subject": "Teste", "source_folder": str(origem),
        "output_folder": str(tmp_path / "saida"), "collection_type": "processo", "group_mode": "subfolder",
        "group_pattern": "", "extensions": ["pdf", "docx", "imagens"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "2", "chars_per_page": "2000", "ocr_language": "por", "classification_engine": "rules",
        "local_model": "gemma4:e4b", "role_instructions": "", "extra_rules": "",
    }
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


@pytest.mark.parametrize("rota", ["run/steps", "run/progress", "run/log"])
def test_consulta_da_tela_com_banco_ocupado_devolve_204(cliente, tmp_path, monkeypatch, rota):
    projeto = _criar_projeto(cliente, tmp_path)
    assert cliente.get(f"/projects/{projeto}/run/steps").status_code == 200

    def _ocupado(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(app_mod, "load_project", _ocupado)
    resposta = cliente.get(f"/projects/{projeto}/{rota}", headers={"HX-Request": "true"})
    assert resposta.status_code == 204


def test_pagina_inteira_com_banco_ocupado_explica_em_vez_de_erro_500(cliente, tmp_path, monkeypatch):
    projeto = _criar_projeto(cliente, tmp_path)

    def _ocupado(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(app_mod, "load_project", _ocupado)
    cliente.cookies.set("language", "pt")
    resposta = cliente.get(f"/projects/{projeto}/run/steps")
    assert resposta.status_code == 503
    assert "Banco de dados ocupado" in resposta.text


def test_chaves_novas_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave, params in (
            ("log.worker_restarted", {"name": "x", "minutes": 10}),
            ("log.pool_stalled", {"name": "x"}),
            ("error.file_timed_out", {"minutes": 10}),
            ("busy.title", {}),
            ("busy.message", {}),
        ):
            texto = translate(idioma, chave, **params)
            assert texto and texto != chave

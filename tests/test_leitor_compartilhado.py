"""2.1.6: o leitor compartilhado (`ReaderPool`) não entrega conexão fechada.

`acquire` soltava a trava do mapa antes de pegar a trava do leitor; nesse
intervalo `close()`/`close_idle()` podiam tirar o leitor do mapa e fechar a
conexão, e a tela recebia uma conexão já fechada.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from gclaude_indexer.web.readers import ReaderPool
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def _pasta_de(pid):
    from gclaude_indexer.catalog import find_project

    return find_project(pid).output_folder


class _TravaQueFechaAntes:
    """Trava que, na primeira vez, deixa outro fechar o leitor antes de ser
    obtida — o intervalo que o `acquire` deixava aberto."""

    def __init__(self, ao_adquirir):
        self._trava = threading.Lock()
        self._ao_adquirir = ao_adquirir

    def acquire(self, *args, **kwargs):
        if self._ao_adquirir is not None:
            acao, self._ao_adquirir = self._ao_adquirir, None
            acao()
        return self._trava.acquire(*args, **kwargs)

    def release(self):
        self._trava.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def test_leitor_fechado_entre_o_mapa_e_a_trava_nao_e_entregue(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path)
    pasta = _pasta_de(pid)
    pool = ReaderPool()
    leitor = pool.acquire(pasta)
    pool.release(leitor)

    def fechar_por_fora():
        with pool._lock:
            pool._readers.pop(leitor.folder_key, None)
        leitor.conn.close()

    leitor.lock = _TravaQueFechaAntes(fechar_por_fora)

    obtido = pool.acquire(pasta)
    try:
        if obtido is not None:
            assert obtido is not leitor
            obtido.conn.execute("SELECT 1").fetchone()
    finally:
        if obtido is not None:
            pool.release(obtido)
        pool.close_all()


def test_leitor_substituido_tem_a_conexao_fechada(cliente, tmp_path, monkeypatch):
    pid = _criar_projeto(cliente, tmp_path)
    pasta = _pasta_de(pid)
    pool = ReaderPool()
    intruso = {}
    original_open = pool._open

    # Enquanto esta requisição abre o leitor, outra põe no mapa um leitor
    # com assinatura antiga; o desta o substitui, e o antigo não pode ficar
    # com a conexão aberta.
    def abrir_enquanto_outro_entra(key, output_folder, db_path, signature):
        outro = original_open(key, output_folder, db_path, signature)
        outro.signature = (-1, -1)
        with pool._lock:
            pool._readers[key] = outro
        intruso["leitor"] = outro
        return original_open(key, output_folder, db_path, signature)

    monkeypatch.setattr(pool, "_open", abrir_enquanto_outro_entra)
    obtido = pool.acquire(pasta)
    pool.release(obtido)
    try:
        assert obtido is not intruso["leitor"]
        with pytest.raises(sqlite3.ProgrammingError):
            intruso["leitor"].conn.execute("SELECT 1")
    finally:
        pool.close_all()

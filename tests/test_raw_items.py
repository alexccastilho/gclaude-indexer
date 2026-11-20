"""`raw_items.jsonl` e o banco não podem divergir se o processo cair no meio
de uma devolução de janelas (`requeue_fallback_windows`).

A devolução mexe nos dois lados: as janelas que o motor de regras
classificou só porque o modelo estava fora voltam para `pending` no banco, e
as linhas delas saem do arquivo. Se a troca do arquivo valer e a gravação do
banco não, as janelas ficam `done` sem nenhuma linha: as peças somem do
índice e nada as reclassifica. A ordem segura grava o banco primeiro; uma
queda entre os dois passos deixa as janelas `pending` com as linhas velhas
ainda no arquivo, e a próxima devolução termina o serviço.

A queda é simulada com uma exceção injetada em cada passo e a conexão é
fechada e reaberta antes de conferir, como num processo novo: na mesma
conexão o `UPDATE` não gravado continuaria visível e o teste passaria com a
ordem errada.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.engine_local import requeue_fallback_windows

QUEDA = "regras"  # janela classificada pelo motor de regras na queda do modelo
MISTA = "mista"  # tem linha sem marca: fica como está
MODELO = "modelo"  # classificada pelo modelo


class _Queda(Exception):
    pass


class _ConexaoQueCaiNoCommit:
    """Repassa tudo à conexão real, mas o `commit` derruba o processo."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self):
        raise _Queda("caiu antes de gravar o banco")


def _linha(janela: str, fallback: bool) -> str:
    dados = {"window": janela, "group": "g", "ref_start": "f. 1", "ref_end": "f. 1"}
    if fallback:
        dados["fallback"] = True
    return json.dumps(dados, ensure_ascii=False) + "\n"


def _projeto(tmp_path: Path) -> tuple[Path, Path]:
    banco = tmp_path / "project.db"
    conn = connect(banco)
    init_schema(conn)
    for chave in (QUEDA, MISTA, MODELO):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, 'g', 'f. 1', 'f. 1', 'done')",
            (chave,),
        )
    conn.commit()
    conn.close()
    jsonl = tmp_path / "raw_items.jsonl"
    with open(jsonl, "w", encoding="utf-8", newline="") as arquivo:
        arquivo.write(_linha(QUEDA, True))
        arquivo.write(_linha(MODELO, False))
        arquivo.write(_linha(QUEDA, True))
        arquivo.write(_linha(MISTA, True))
        arquivo.write(_linha(MISTA, False))
    return banco, jsonl


def _estado(banco: Path, jsonl: Path) -> tuple[dict, list[str]]:
    conn = connect(banco)
    try:
        status = dict(conn.execute("SELECT key, status FROM window").fetchall())
    finally:
        conn.close()
    linhas = [json.loads(linha)["window"] for linha in jsonl.read_text(encoding="utf-8").split("\n") if linha.strip()]
    return status, linhas


def _sem_perda(status: dict, linhas: list[str]) -> None:
    """Nenhuma janela `done` sem as linhas dela."""
    for chave, situacao in status.items():
        if situacao == "done":
            assert chave in linhas, f"{chave} ficou done sem nenhuma linha"


def _resultado_sem_queda(tmp_path: Path) -> tuple[dict, list[str]]:
    banco, jsonl = _projeto(tmp_path / "sem_queda")
    conn = connect(banco)
    try:
        assert requeue_fallback_windows(conn, jsonl) == 1
    finally:
        conn.close()
    return _estado(banco, jsonl)


@pytest.fixture
def esperado(tmp_path):
    (tmp_path / "sem_queda").mkdir()
    status, linhas = _resultado_sem_queda(tmp_path)
    assert status == {QUEDA: "pending", MISTA: "done", MODELO: "done"}
    assert linhas == [MODELO, MISTA, MISTA]
    return status, linhas


def _depois_da_queda_e_de_nova_devolucao(banco: Path, jsonl: Path):
    status, linhas = _estado(banco, jsonl)
    _sem_perda(status, linhas)
    conn = connect(banco)
    try:
        requeue_fallback_windows(conn, jsonl)
    finally:
        conn.close()
    return _estado(banco, jsonl)


def test_queda_antes_de_gravar_o_banco_nao_perde_pecas(tmp_path, esperado):
    banco, jsonl = _projeto(tmp_path)
    conn = connect(banco)
    try:
        with pytest.raises(_Queda):
            requeue_fallback_windows(_ConexaoQueCaiNoCommit(conn), jsonl)
    finally:
        conn.close()  # sem commit: o UPDATE não gravado se perde, como na queda

    assert _depois_da_queda_e_de_nova_devolucao(banco, jsonl) == esperado


def test_queda_ao_trocar_o_arquivo_nao_perde_nem_duplica(tmp_path, monkeypatch, esperado):
    banco, jsonl = _projeto(tmp_path)

    def cai(self, *args, **kwargs):
        raise _Queda("caiu ao trocar o arquivo")

    conn = connect(banco)
    try:
        with monkeypatch.context() as m:
            m.setattr(Path, "replace", cai)
            with pytest.raises(_Queda):
                requeue_fallback_windows(conn, jsonl)
    finally:
        conn.close()

    assert _depois_da_queda_e_de_nova_devolucao(banco, jsonl) == esperado
    assert not list(jsonl.parent.glob("*.tmp"))


def test_devolucao_sem_janela_de_queda_nao_reescreve_o_arquivo(tmp_path):
    jsonl = tmp_path / "raw_items.jsonl"
    conteudo = _linha(MODELO, False) + "\n" + "não é json\n"
    jsonl.write_bytes(conteudo.encode("utf-8"))
    banco = tmp_path / "project.db"
    conn = connect(banco)
    init_schema(conn)
    try:
        assert requeue_fallback_windows(conn, jsonl) == 0
    finally:
        conn.close()
    assert jsonl.read_bytes() == conteudo.encode("utf-8")

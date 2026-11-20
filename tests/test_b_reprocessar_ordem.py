"""`tools/reprocessar_janelas_com_falha.py --aplicar`: o banco é gravado antes
de trocar o `raw_items.jsonl`, como na devolução de janelas (ec9ebd1).

Na ordem velha (poda, depois commit), uma queda entre os dois tirava do
arquivo as peças das janelas e as deixava `done`: as peças sumiam do índice
e nada as reclassificava. Na ordem segura a queda deixa as janelas como
estavam e as linhas no arquivo; rodar de novo termina o serviço."""

from __future__ import annotations

import json
import sqlite3

import pytest

from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import record_event

import tools.reprocessar_janelas_com_falha as ferramenta

JANELA = "volume_1:0001-0010"
OUTRA = "volume_1:0011-0020"


class _Queda(Exception):
    pass


class _ConexaoQueCaiNoCommit:
    """Repassa tudo à conexão real, mas o `commit` derruba o processo."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._conn.executemany(*args, **kwargs)

    def commit(self):
        raise _Queda("caiu antes de gravar o banco")

    def close(self):
        self._conn.close()


def _projeto(tmp_path):
    saida = tmp_path / "acervo_indexado"
    saida.mkdir()
    conn = connect(saida / "project.db")
    init_schema(conn)
    for indice, chave in enumerate((JANELA, OUTRA), start=1):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, 'volume_1', ?, ?, 'done')",
            (chave, f"p{indice}", f"p{indice}"),
        )
    conn.commit()
    record_event(
        conn, "classification", "warning", "log.local_engine.window_rejection",
        {"window": JANELA, "reason": "pages_missing_from_answer"},
    )
    conn.close()
    (saida / "raw_items.jsonl").write_text(
        json.dumps({"window": JANELA}) + "\n" + json.dumps({"window": OUTRA}) + "\n", encoding="utf-8"
    )
    return saida


def _janelas_no_arquivo(saida) -> list[str]:
    texto = (saida / "raw_items.jsonl").read_text(encoding="utf-8")
    return [json.loads(linha)["window"] for linha in texto.splitlines() if linha.strip()]


def _status(saida) -> dict:
    conn = sqlite3.connect(saida / "project.db")
    try:
        return dict(conn.execute("SELECT key, status FROM window").fetchall())
    finally:
        conn.close()


def test_queda_antes_de_gravar_o_banco_nao_tira_as_pecas_do_arquivo(tmp_path, monkeypatch):
    saida = _projeto(tmp_path)
    conectar = sqlite3.connect
    monkeypatch.setattr(ferramenta.sqlite3, "connect", lambda *a, **k: _ConexaoQueCaiNoCommit(conectar(*a, **k)))

    with pytest.raises(_Queda):
        ferramenta.main([str(saida), "--aplicar"])
    monkeypatch.undo()

    # Nada se perdeu: janela `done` continua com a peça dela no arquivo.
    assert _status(saida) == {JANELA: "done", OUTRA: "done"}
    assert _janelas_no_arquivo(saida) == [JANELA, OUTRA]

    # Rodar de novo termina o serviço.
    assert ferramenta.main([str(saida), "--aplicar"]) == 0
    assert _status(saida) == {JANELA: "pending", OUTRA: "done"}
    assert _janelas_no_arquivo(saida) == [OUTRA]


def test_poda_mantem_o_fim_de_linha_das_linhas_que_ficam(tmp_path):
    """A troca usa `raw_items.prune`: as linhas mantidas saem byte a byte."""
    caminho = tmp_path / "raw_items.jsonl"
    caminho.write_bytes(
        (json.dumps({"window": "a"}) + "\n" + json.dumps({"window": "b"}) + "\n").encode("utf-8")
    )

    assert ferramenta.podar_jsonl(caminho, {"a"}) == (1, 1)
    assert caminho.read_bytes() == (json.dumps({"window": "b"}) + "\n").encode("utf-8")

"""Documento do índice cujo conteúdo muda para algo que não se indexa (uma
chave privada num `.txt`), visto direto pela varredura (`scanning._drop_derived_data`).

Dois defeitos:
1. páginas, busca e intermediário saíam, mas as janelas do grupo (e as
   linhas delas no `raw_items.jsonl`) ficavam apontando para páginas que
   sumiram;
2. o intermediário era apagado do disco dentro de uma operação do lote,
   antes do commit: um commit que falhasse deixava o banco como estava e o
   intermediário perdido. A regra do projeto (`invalidation.py`) é banco
   primeiro, disco depois."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.paths import RAW_ITEMS_FILE_NAME
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows
from gclaude_indexer.workdir import converted_artifact_path

CHAVE = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAuma\n-----END RSA PRIVATE KEY-----\n"


def _texto(n: int) -> str:
    return "\n".join(f"Linha {i} do documento {n}, texto comum de teste para indexar." for i in range(40))


def _projeto(tmp_path):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "saida"
    for nome in ("a.txt", "b.txt"):
        (origem / "volume_1" / nome).write_text(_texto(ord(nome[0])), encoding="utf-8")
    config = load_config({
        "name": "Vira ignorado", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["text"], "pages_per_window": 1, "overlap": 0,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    chaves = [row[0] for row in conn.execute("SELECT key FROM window")]
    assert chaves
    with open(saida / RAW_ITEMS_FILE_NAME, "w", encoding="utf-8") as arquivo:
        for chave in chaves:
            arquivo.write(json.dumps({"window": chave, "group": "volume_1"}) + "\n")
    linha = conn.execute("SELECT extension, needs_ocr FROM file WHERE name = 'a.txt'").fetchone()
    intermediario = converted_artifact_path(saida, "volume_1/a.txt", linha["extension"], bool(linha["needs_ocr"]))
    assert intermediario is not None and intermediario.exists()
    return origem, saida, config, conn, intermediario


def test_documento_que_vira_chave_leva_junto_as_janelas_e_as_linhas_delas(tmp_path):
    origem, saida, config, conn, intermediario = _projeto(tmp_path)
    janelas_antes = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]

    (origem / "volume_1" / "a.txt").write_text(CHAVE, encoding="utf-8")
    scan(conn, config)

    arquivo = conn.execute("SELECT id, status FROM file WHERE name = 'a.txt'").fetchone()
    assert arquivo["status"] == "skipped"
    assert conn.execute("SELECT COUNT(*) FROM page WHERE file_id = ?", (arquivo["id"],)).fetchone()[0] == 0
    # As janelas que liam as páginas de a.txt saíram, e as linhas delas também.
    janelas = {row[0] for row in conn.execute("SELECT key FROM window")}
    assert len(janelas) < janelas_antes
    linhas = [json.loads(l)["window"] for l in (saida / RAW_ITEMS_FILE_NAME).read_text(encoding="utf-8").splitlines()]
    assert set(linhas) <= janelas
    assert not intermediario.exists()
    conn.close()


class _ConexaoQueNaoGrava:
    """Repassa tudo à conexão real, mas o `commit` falha (banco travado por
    outro programa até o fim da paciência)."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, nome):
        return getattr(self._conn, nome)

    def commit(self):
        raise RuntimeError("o commit falhou")


def test_commit_que_falha_nao_leva_o_intermediario(tmp_path):
    origem, saida, config, conn, intermediario = _projeto(tmp_path)
    (origem / "volume_1" / "a.txt").write_text(CHAVE, encoding="utf-8")

    with pytest.raises(RuntimeError):
        scan(_ConexaoQueNaoGrava(conn), config)
    conn.rollback()

    # O banco continua dizendo que a.txt tem páginas lidas do intermediário:
    # ele não pode ter sumido.
    assert conn.execute("SELECT status FROM file WHERE name = 'a.txt'").fetchone()[0] != "skipped"
    assert intermediario.exists()
    conn.close()

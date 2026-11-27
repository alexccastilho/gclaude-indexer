# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""2.1.6 — geometria do grupo quando um arquivo entra ou sai dele (auditoria, lote 1)."""

from __future__ import annotations

import pytest

from gclaude_indexer.scanning import scan

# --- Item 3: arquivo que muda de situação no meio de um grupo -------------------------
#
# Três transições punham páginas no meio do grupo (ou as tiravam) sem
# descartar as janelas seguintes: um ignorado (`skipped`, sem hash) editado
# até virar indexável, uma cópia (`duplicate`) editada até virar conteúdo
# único, e um documento de uma página que vira ignorado. As janelas já
# classificadas depois dele continuavam `done`, cobrindo folhas que agora
# são de outro arquivo.

from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.invalidation import apply_update_plan
from gclaude_indexer.update_plan import build_update_plan
from gclaude_indexer.windows_prep import prepare_windows

CHAVE = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAuma\n-----END RSA PRIVATE KEY-----\n"


def _texto(letra: str) -> str:
    return "\n".join(f"Linha {i} do documento {letra}, texto comum de teste." for i in range(30))


def _pipeline(conn, config) -> None:
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)


def _cobertura(conn) -> dict[str, tuple[str, str]]:
    """Janela → (arquivo da folha, status), com uma folha por janela."""
    return {
        row["key"]: (row["relative_path"], row["status"])
        for row in conn.execute(
            """
            SELECT window.key, window.status, file.relative_path
            FROM window
            JOIN page ON page.reference = window.start_ref
            JOIN file ON file.id = page.file_id AND file.group_key = window.group_key
            """
        )
    }


def _grupo(tmp_path, conteudos: dict[str, str]):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "saida"
    for nome, texto in conteudos.items():
        (origem / "volume_1" / nome).write_text(texto, encoding="utf-8")
    config = load_config({
        "name": "Geometria", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["text"], "pages_per_window": 1, "overlap": 0,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    _pipeline(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    return origem, config, conn


def _janelas_feitas_continuam_validas(antes, depois) -> None:
    for chave, (arquivo, status) in depois.items():
        if status == "done":
            assert antes.get(chave, (None,))[0] == arquivo, (
                f"{chave} segue classificada, mas agora cobre {arquivo}"
            )


@pytest.mark.parametrize("pelo_plano", [False, True], ids=["varredura", "atualizacao"])
@pytest.mark.parametrize("caso", ["ignorado_vira_indexavel", "copia_vira_unica", "documento_vira_ignorado"])
def test_janelas_seguintes_saem_quando_arquivo_entra_ou_sai_do_grupo(tmp_path, caso, pelo_plano):
    if caso == "ignorado_vira_indexavel":
        inicial = {"a.txt": _texto("A"), "b.txt": CHAVE, "c.txt": _texto("C")}
        novo_b = _texto("B")
    elif caso == "copia_vira_unica":
        inicial = {"a.txt": _texto("A"), "b.txt": _texto("A"), "c.txt": _texto("C")}
        novo_b = _texto("B")
    else:
        inicial = {"a.txt": _texto("A"), "b.txt": _texto("B"), "c.txt": _texto("C")}
        novo_b = CHAVE
    origem, config, conn = _grupo(tmp_path, inicial)
    antes = _cobertura(conn)

    (origem / "volume_1" / "b.txt").write_text(novo_b + "\n", encoding="utf-8")
    if pelo_plano:
        apply_update_plan(conn, config, build_update_plan(conn, config))
    _pipeline(conn, config)

    depois = _cobertura(conn)
    _janelas_feitas_continuam_validas(antes, depois)
    # A janela da folha 1 (a.txt) não tinha por que sair.
    assert any(status == "done" and arquivo.endswith("a.txt") for arquivo, status in depois.values())
    conn.close()


def test_projeto_sem_mudancas_nao_perde_janelas(tmp_path):
    origem, config, conn = _grupo(
        tmp_path, {"a.txt": _texto("A"), "b.txt": CHAVE, "b2.txt": _texto("A"), "c.txt": _texto("C")},
    )
    antes = _cobertura(conn)
    plano = build_update_plan(conn, config)
    assert plano.is_empty, "nada mudou: plano vazio"
    apply_update_plan(conn, config, plano)
    _pipeline(conn, config)
    assert _cobertura(conn) == antes
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status != 'done'").fetchone()[0] == 0
    conn.close()

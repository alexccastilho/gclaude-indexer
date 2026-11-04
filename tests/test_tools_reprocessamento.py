"""Tests for `tools/reprocessar_janelas_com_falha.py`.

The tool exists because the pipeline has no `done -> pending` transition:
the only state change the product performs is `pending -> done`, and the
incremental update (Phase 17) reacts to changes in the *source files*, so
with the PDFs untouched it invalidates nothing. Without the tool the
options are reindexing the whole acquis or living with the result.

That makes it destructive in a way the product's own code never is — it
rewrites `raw_items.jsonl` and moves rows of `window` backwards. These
tests cover the three ways that can go wrong: reopening a window that no
longer exists, reopening a failure that retrying cannot fix, and writing
anything at all during a dry run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import record_event

from tools.reprocessar_janelas_com_falha import (
    janelas_com_falha,
    main,
    podar_jsonl,
)

REJEICAO = "log.local_engine.window_rejection"
PECA_INVALIDA = "log.local_engine.invalid_item"


def _projeto(tmp_path, janelas=("volume_1:0001-0010", "volume_1:0011-0020")):
    """Uma pasta de saída com `project.db` e as janelas dadas já concluídas."""
    saida = tmp_path / "acervo_indexado"
    saida.mkdir()
    conn = connect(saida / "project.db")
    init_schema(conn)
    for indice, chave in enumerate(janelas, start=1):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, 'volume_1', ?, ?, 'done')",
            (chave, f"p{indice}", f"p{indice}"),
        )
    conn.commit()
    return saida, conn


def _falha(conn, janela, *, chave_msg=REJEICAO, motivo="pages_missing_from_answer"):
    record_event(
        conn, "classification", "warning", chave_msg,
        {"window": janela, "reason": motivo},
    )


def _status(conn, janela) -> str:
    return conn.execute(
        "SELECT status FROM window WHERE key = ?", (janela,)
    ).fetchone()[0]


# ---------------------------------------------------------------- leitura


def test_reune_as_duas_assinaturas_de_falha(tmp_path):
    """As duas formas de perder uma peça na etapa 6 contam como falha: a
    janela que o modelo não respondeu e a peça recusada na validação."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    _falha(conn, "volume_1:0011-0020", chave_msg=PECA_INVALIDA, motivo="sem data")

    encontradas = janelas_com_falha(conn, "0000")

    assert set(encontradas) == {"volume_1:0001-0010", "volume_1:0011-0020"}
    assert encontradas["volume_1:0001-0010"] == {"modelo não respondeu"}
    assert encontradas["volume_1:0011-0020"] == {"peça recusada na validação"}


def test_ignora_rejeicao_que_repetir_nao_resolve(tmp_path):
    """`window_rejection` embrulha vários avisos. Só o que diz que o modelo
    deixou páginas sem resposta é reclassificável — uma referência que o
    acervo não reconhece continuará não sendo reconhecida na segunda vez."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010", motivo="unknown_reference")

    assert janelas_com_falha(conn, "0000") == {}


def test_ignora_janela_que_nao_existe_mais(tmp_path):
    """Uma janela citada num evento antigo pode ter sido descartada por uma
    atualização posterior. Reabri-la ressuscitaria uma posição que o acervo
    atual não tem."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    conn.execute("DELETE FROM window WHERE key = 'volume_1:0001-0010'")
    conn.commit()

    assert janelas_com_falha(conn, "0000") == {}


def test_desde_descarta_falhas_de_corridas_anteriores(tmp_path):
    """Sem recorte por data, a falha de uma corrida antiga — já resolvida por
    uma reclassificação posterior — reabriria a janela de novo."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    conn.execute("UPDATE event SET created_at = '2020-01-01T00:00:00'")
    conn.commit()

    assert janelas_com_falha(conn, "2026-01-01") == {}
    assert set(janelas_com_falha(conn, "2019-01-01")) == {"volume_1:0001-0010"}


def test_evento_com_params_ilegiveis_nao_derruba_a_leitura(tmp_path):
    """Um `message_params` que não decodifica é pulado, não uma exceção no
    meio da varredura."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0011-0020")
    conn.execute(
        "INSERT INTO event (step, level, message, message_key, message_params, created_at)"
        " VALUES ('classification', 'warning', 'x', ?, '{nao e json', '2026-09-17')",
        (PECA_INVALIDA,),
    )
    conn.commit()

    assert set(janelas_com_falha(conn, "0000")) == {"volume_1:0011-0020"}


# ------------------------------------------------------------------ poda


def test_poda_remove_so_as_pecas_das_janelas_indicadas(tmp_path):
    caminho = tmp_path / "raw_items.jsonl"
    caminho.write_text(
        "\n".join(
            json.dumps({"window": janela, "n": indice})
            for indice, janela in enumerate(["a", "b", "a", "c"])
        ) + "\n",
        encoding="utf-8",
    )

    removidas, mantidas = podar_jsonl(caminho, {"a"})

    assert (removidas, mantidas) == (2, 2)
    janelas = [json.loads(linha)["window"] for linha in caminho.read_text(encoding="utf-8").splitlines()]
    assert janelas == ["b", "c"]


def test_poda_mantem_a_linha_que_nao_decodifica(tmp_path):
    """Apagar em silêncio o que não se consegue ler não é decisão deste
    script — a importação já reporta a linha inválida como erro."""
    caminho = tmp_path / "raw_items.jsonl"
    caminho.write_text('{"window": "a"}\nlixo que nao e json\n', encoding="utf-8")

    removidas, mantidas = podar_jsonl(caminho, {"a"})

    assert (removidas, mantidas) == (1, 1)
    assert caminho.read_text(encoding="utf-8") == "lixo que nao e json\n"


def test_poda_de_arquivo_inexistente_nao_e_erro(tmp_path):
    """Um acervo cuja etapa 6 nunca terminou não tem `raw_items.jsonl`."""
    assert podar_jsonl(tmp_path / "nao_existe.jsonl", {"a"}) == (0, 0)


# ------------------------------------------------------------- linha de comando


def test_ensaio_nao_escreve_nada(tmp_path, capsys):
    """Sem `--aplicar` o script lista o que faria e para: nem o status da
    janela, nem o JSONL, nem cópia de segurança."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    (saida / "raw_items.jsonl").write_text(
        json.dumps({"window": "volume_1:0001-0010"}) + "\n", encoding="utf-8"
    )
    conn.close()

    assert main([str(saida)]) == 0

    saida_texto = capsys.readouterr().out
    assert "volume_1:0001-0010" in saida_texto
    assert "Ensaio" in saida_texto
    conferencia = sqlite3.connect(saida / "project.db")
    assert _status(conferencia, "volume_1:0001-0010") == "done"
    conferencia.close()
    assert (saida / "raw_items.jsonl").read_text(encoding="utf-8").strip() != ""
    assert list(saida.glob("*.bak-*")) == []


def test_aplicar_devolve_a_janela_e_poda_o_jsonl(tmp_path, capsys):
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    (saida / "raw_items.jsonl").write_text(
        json.dumps({"window": "volume_1:0001-0010"}) + "\n"
        + json.dumps({"window": "volume_1:0011-0020"}) + "\n",
        encoding="utf-8",
    )
    conn.close()

    assert main([str(saida), "--aplicar"]) == 0

    conferencia = sqlite3.connect(saida / "project.db")
    assert _status(conferencia, "volume_1:0001-0010") == "pending"
    assert _status(conferencia, "volume_1:0011-0020") == "done", (
        "a janela que não falhou não pode ser reaberta junto"
    )
    conferencia.close()

    restantes = (saida / "raw_items.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(linha)["window"] for linha in restantes] == ["volume_1:0011-0020"]


def test_aplicar_grava_copia_de_seguranca_dos_dois_arquivos(tmp_path):
    """O banco e o JSONL são reescritos; ambos têm cópia antes disso."""
    saida, conn = _projeto(tmp_path)
    _falha(conn, "volume_1:0001-0010")
    (saida / "raw_items.jsonl").write_text(
        json.dumps({"window": "volume_1:0001-0010"}) + "\n", encoding="utf-8"
    )
    conn.close()

    main([str(saida), "--aplicar"])

    assert len(list(saida.glob("project.db.bak-*"))) == 1
    copia = next(saida.glob("raw_items.jsonl.bak-*"))
    assert json.loads(copia.read_text(encoding="utf-8"))["window"] == "volume_1:0001-0010", (
        "a cópia guarda a peça que a poda apagou"
    )


def test_sem_falhas_nao_faz_nada(tmp_path, capsys):
    saida, conn = _projeto(tmp_path)
    conn.close()

    assert main([str(saida), "--aplicar"]) == 0
    assert "Nada a fazer" in capsys.readouterr().out
    assert list(saida.glob("*.bak-*")) == []


def test_pasta_sem_banco_falha_com_instrucao(tmp_path, capsys):
    """O erro mais provável de quem usa o script é apontar para a pasta de
    origem em vez da pasta de saída."""
    assert main([str(tmp_path)]) == 1
    assert "_indexado" in capsys.readouterr().err

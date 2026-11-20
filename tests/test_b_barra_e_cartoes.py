"""Etapa B: a barra de progresso e o tempo restante da tela de Execução
contam o que falta pela mesma regra dos cartões das etapas.

Antes, o cartão da conversão dava como pendentes os `discovered` mais os
arquivos cujo OCR falhou (que a conversão seguinte devolve à fila), e a
barra só os `discovered`; o cartão da classificação dava "total menos
feitas", e a barra só as `pending`. Agora as duas leem
`step_state.conversion_pending`/`classification_pending`."""

from __future__ import annotations

from gclaude_indexer import file_status
from gclaude_indexer.web.background_runs import _total_and_baseline, _weight_total_and_baseline
from gclaude_indexer.web.step_state import step_status

from tests.test_phase17 import _conn


def _arquivo(conn, nome, status, size, ocr_failed=0):
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, group_key, status, ocr_failed)"
        " VALUES (?, ?, 'pdf', ?, ?, 0, 'g', ?, ?)",
        (nome, nome, size, nome, status, ocr_failed),
    )


def _cartao(conn, chave):
    return next(etapa for etapa in step_status(conn, lambda _key: False) if etapa["chave"] == chave)


def test_pendentes_da_conversao_iguais_no_cartao_e_na_barra(tmp_path):
    conn = _conn(tmp_path)
    _arquivo(conn, "novo.pdf", file_status.DISCOVERED, 100)
    _arquivo(conn, "ocr_falhou.pdf", file_status.FAILED, 40, ocr_failed=1)
    _arquivo(conn, "pronto.pdf", file_status.CONVERTED, 7)
    conn.commit()

    pendentes_no_cartao = _cartao(conn, "conversion")["vars"]["pending"]
    total_da_barra, _baseline = _total_and_baseline(conn, "conversion")
    _base_bytes, bytes_pendentes = _weight_total_and_baseline(conn, "conversion")

    assert pendentes_no_cartao == 2
    assert total_da_barra == pendentes_no_cartao
    assert bytes_pendentes == 140
    conn.close()


def test_pendentes_da_classificacao_iguais_no_cartao_e_na_barra(tmp_path):
    conn = _conn(tmp_path)
    for chave, status in (("g_1", file_status.WINDOW_PENDING), ("g_2", file_status.WINDOW_DONE), ("g_3", "outro")):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status) VALUES (?, 'g', 'f. 1', 'f. 2', ?)",
            (chave, status),
        )
    conn.commit()

    pendentes_no_cartao = _cartao(conn, "classification")["vars"]["pending"]
    total_da_barra, baseline = _total_and_baseline(conn, "classification")

    assert pendentes_no_cartao == 2
    assert (total_da_barra, baseline) == (pendentes_no_cartao, 1)
    conn.close()

"""1.5.7 — OCR sem PDF/A e nova tentativa automática das falhas de OCR.

Um PDF com espaço de cor incomum fazia o ocrmypdf recusar a conversão para
PDF/A (`ColorConversionNeededError`) e descartar o OCR do arquivo inteiro.
Agora a saída é um PDF comum, e todo arquivo cujo OCR falhou fica marcado
(`file.ocr_failed`) e volta à fila na conversão seguinte. As demais falhas
(arquivo corrompido, protegido) continuam como estão.
"""

from __future__ import annotations

import json
from dataclasses import replace

import fitz

from gclaude_indexer import conversion
from gclaude_indexer import workdir
from gclaude_indexer.conversion import convert, ocr_retry_count, requeue_ocr_failures
from gclaude_indexer.db import SCHEMA_SQL, connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.i18n import translate
from gclaude_indexer.scanning import scan
from gclaude_indexer.web.step_state import step_status

from .test_phase3 import _criar_pdf_escaneado, _criar_pdf_misto, _preparar_projeto


class _Resultado:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr


def _falso_ocrmypdf(monkeypatch, returncode: int, comandos: list | None = None):
    def _run(comando, **kwargs):
        if comandos is not None:
            comandos.append(comando)
        return _Resultado(returncode, "ColorConversionNeededError: unusual color space")

    monkeypatch.setattr(conversion.subprocess, "run", _run)


def _linha(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


def _mensagens(conn):
    return [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]


def test_ocrmypdf_gera_pdf_comum_e_nao_pdfa(tmp_path, monkeypatch):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_misto(origem / "ata_mista.pdf")
    comandos = []
    _falso_ocrmypdf(monkeypatch, 0, comandos)

    scan(conn, config)
    convert(conn, config)

    comando = comandos[0]
    assert comando[comando.index("--output-type") + 1] == "pdf"
    conn.close()


def test_falha_parcial_de_ocr_fica_marcada_e_e_refeita_na_proxima_conversao(tmp_path, monkeypatch):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_misto(origem / "ata_mista.pdf")
    scan(conn, config)

    _falso_ocrmypdf(monkeypatch, 1)
    convert(conn, config)
    linha = _linha(conn, "ata_mista.pdf")
    assert linha["status"] == "converted"
    assert linha["ocr_failed"] == 1
    assert ocr_retry_count(conn) == 1

    # A tela de execução mostra a conversão como pendente enquanto há
    # arquivo para refazer.
    etapas = {e["chave"]: e for e in step_status(conn, lambda _key: False)}
    assert etapas["conversion"]["status"] != "done"
    assert etapas["conversion"]["vars"]["pending"] == 1

    monkeypatch.undo()
    resultado = convert(conn, config, language="pt-BR")

    linha = _linha(conn, "ata_mista.pdf")
    assert resultado.ocr_applied == 1
    assert linha["status"] == "converted"
    assert linha["ocr_failed"] == 0
    assert linha["needs_ocr"] == 1
    assert ocr_retry_count(conn) == 0
    assert any("voltaram à fila" in m for m in _mensagens(conn))

    documento = fitz.open(workdir.work_folder(saida) / "converted" / "ata_mista.pdf")
    assert "RECONHECIMENTO" in documento[1].get_text().upper()
    documento.close()
    conn.close()


def test_falha_total_de_ocr_fica_marcada_mas_outras_falhas_nao(tmp_path, monkeypatch):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_escaneado(origem / "escaneado.pdf")
    (origem / "corrompido.pdf").write_bytes(b"isto nao e um pdf")
    # Um arquivo por vez, no próprio processo: o ocrmypdf falso não chega
    # aos processos do modo paralelo.
    config = replace(config, parallelism="economy")
    scan(conn, config)

    _falso_ocrmypdf(monkeypatch, 1)
    convert(conn, config)

    escaneado = _linha(conn, "escaneado.pdf")
    corrompido = _linha(conn, "corrompido.pdf")
    assert escaneado["status"] == "failed"
    assert escaneado["ocr_failed"] == 1
    assert corrompido["status"] == "failed"
    assert corrompido["ocr_failed"] == 0

    assert requeue_ocr_failures(conn) == 1
    assert _linha(conn, "escaneado.pdf")["status"] == "discovered"
    assert _linha(conn, "escaneado.pdf")["error"] is None
    assert _linha(conn, "corrompido.pdf")["status"] == "failed"
    conn.close()


def test_arquivo_ja_extraido_volta_a_fila_e_perde_as_paginas_antigas(tmp_path, monkeypatch):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_misto(origem / "ata_mista.pdf")
    scan(conn, config)
    _falso_ocrmypdf(monkeypatch, 1)
    convert(conn, config)

    linha = _linha(conn, "ata_mista.pdf")
    conn.execute("UPDATE file SET status = 'extracted' WHERE id = ?", (linha["id"],))
    conn.execute(
        "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text)"
        " VALUES (?, 1, 'f. 1', 0, 0, 0, '')",
        (linha["id"],),
    )
    conn.commit()

    assert requeue_ocr_failures(conn) == 1
    assert _linha(conn, "ata_mista.pdf")["status"] == "discovered"
    assert conn.execute("SELECT COUNT(*) FROM page WHERE file_id = ?", (linha["id"],)).fetchone()[0] == 0
    conn.close()


def test_arquivo_extraido_com_janelas_prontas_nao_volta_e_gera_aviso(tmp_path, monkeypatch):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_misto(origem / "ata_mista.pdf")
    scan(conn, config)
    _falso_ocrmypdf(monkeypatch, 1)
    convert(conn, config)

    linha = _linha(conn, "ata_mista.pdf")
    conn.execute("UPDATE file SET status = 'extracted' WHERE id = ?", (linha["id"],))
    conn.execute(
        "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
        " VALUES ('g_j0001-0002', 'g', 'f. 1', 'f. 2', 'pending')"
    )
    conn.commit()

    assert ocr_retry_count(conn) == 0
    assert requeue_ocr_failures(conn, language="pt-BR") == 0
    assert _linha(conn, "ata_mista.pdf")["status"] == "extracted"
    assert any("não voltaram à fila" in m and "ata_mista.pdf" in m for m in _mensagens(conn))
    conn.close()


def _banco_anterior_a_1_5_7(caminho):
    """Um banco como o da 1.5.6: sem a coluna `ocr_failed`."""
    conn = connect(caminho)
    conn.executescript(SCHEMA_SQL)
    for coluna in ("message_key TEXT", "message_params TEXT"):
        if coluna.split()[0] not in {r[1] for r in conn.execute("PRAGMA table_info(event)")}:
            conn.execute(f"ALTER TABLE event ADD COLUMN {coluna}")
    if "mtime" not in {r[1] for r in conn.execute("PRAGMA table_info(file)")}:
        conn.execute("ALTER TABLE file ADD COLUMN mtime REAL")
    if "ocr_failed" in {r[1] for r in conn.execute("PRAGMA table_info(file)")}:
        conn.execute("ALTER TABLE file DROP COLUMN ocr_failed")

    def arquivo(nome, status, erro=None, extensao="pdf"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, status, error)"
            " VALUES (?, ?, ?, 1, 'x', ?, ?)",
            (f"pasta/{nome}", nome, extensao, status, erro),
        )

    arquivo("glossario.pdf", "converted")
    arquivo("escaneado.pdf", "failed", "ocrmypdf falhou (código 1): ColorConversionNeededError")
    arquivo("corrompido.pdf", "failed", "PDF corrompido")
    arquivo("outro.pdf", "converted")
    arquivo("glossario.pdf.txt", "converted", extensao="txt")
    conn.execute(
        "INSERT INTO event (step, level, message, message_key, message_params, created_at)"
        " VALUES ('conversion', 'warning', 'x', 'log.conversion.ocr_pages_failed', ?, '2026-10-31')",
        (json.dumps({"name": "glossario.pdf", "pages": 3, "total": 230, "error": "e"}),),
    )
    conn.commit()
    return conn


def test_atualizacao_marca_uma_vez_os_arquivos_que_falharam_antes(tmp_path):
    conn = _banco_anterior_a_1_5_7(tmp_path / "project.db")

    init_schema(conn)
    marcados = {
        r["name"] for r in conn.execute("SELECT name FROM file WHERE ocr_failed = 1")
    }
    assert marcados == {"glossario.pdf", "escaneado.pdf"}

    # Uma vez só: depois de refeitos, os eventos antigos não os marcam de novo.
    conn.execute("UPDATE file SET ocr_failed = 0")
    conn.commit()
    init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM file WHERE ocr_failed = 1").fetchone()[0] == 0
    conn.close()


def test_mensagens_novas_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        for chave in ("log.conversion.ocr_retry", "log.conversion.ocr_retry_held"):
            texto = translate(idioma, chave, count=2, names="a.pdf")
            assert texto != chave
            assert "2" in texto

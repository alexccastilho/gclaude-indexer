"""Phase 3 tests: conversion, OCR and block slicing."""

from __future__ import annotations

import hashlib

import fitz
import pytest
from PIL import Image, ImageDraw

from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert, slice_pdf
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.scanning import scan


def _hash_arquivo(caminho) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


TEXTO_NATIVO_PADRAO = (
    "Texto nativo de teste, com camada de texto real e conteúdo suficiente "
    "para superar o limiar médio de cem caracteres por página definido na "
    "seção 5 da especificação, evitando acionar o OCR indevidamente."
)


def _criar_pdf_nativo(caminho, n_paginas=1, texto=TEXTO_NATIVO_PADRAO):
    documento = fitz.open()
    for _ in range(n_paginas):
        pagina = documento.new_page()
        pagina.insert_textbox(fitz.Rect(50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_pdf_escaneado(caminho, texto="TESTE DE RECONHECIMENTO OCR"):
    """PDF cuja única página é uma imagem (sem camada de texto)."""
    imagem = Image.new("RGB", (900, 300), "white")
    desenho = ImageDraw.Draw(imagem)
    desenho.text((30, 120), texto, fill="black")
    caminho_png = caminho.with_suffix(".png")
    imagem.save(caminho_png)

    documento = fitz.open()
    pagina = documento.new_page(width=900, height=300)
    pagina.insert_image(fitz.Rect(0, 0, 900, 300), filename=str(caminho_png))
    documento.save(caminho)
    documento.close()
    caminho_png.unlink()


def _preparar_projeto(tmp_path, extensoes=None):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "origem_indexado"

    dados = {
        "name": "Projeto Fase 3",
        "source_folder": str(origem),
        "output_folder": str(saida),
    }
    if extensoes:
        dados["extensions"] = extensoes
    config = load_config(dados)

    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


# --- PDF nativo x escaneado ------------------------------------------------


def test_pdf_nativo_nao_passa_por_ocr(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_nativo(origem / "peca_nativa.pdf", n_paginas=2)

    hash_antes = _hash_arquivo(origem / "peca_nativa.pdf")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.converted == 1
    assert resultado.ocr_applied == 0
    assert resultado.failed == 0

    linha = conn.execute("SELECT * FROM file WHERE name = 'peca_nativa.pdf'").fetchone()
    assert linha["status"] == "converted"
    assert linha["needs_ocr"] == 0
    assert linha["page_count"] == 2

    # original intocado, nenhuma cópia OCR criada para ele
    assert _hash_arquivo(origem / "peca_nativa.pdf") == hash_antes
    assert not (saida / "converted" / "peca_nativa.pdf").exists()

    conn.close()


def test_pdf_escaneado_recebe_ocr(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_escaneado(origem / "peca_escaneada.pdf")

    hash_antes = _hash_arquivo(origem / "peca_escaneada.pdf")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.converted == 1
    assert resultado.ocr_applied == 1
    assert resultado.failed == 0

    linha = conn.execute("SELECT * FROM file WHERE name = 'peca_escaneada.pdf'").fetchone()
    assert linha["status"] == "converted"
    assert linha["needs_ocr"] == 1
    assert linha["page_count"] == 1

    caminho_ocr = saida / "converted" / "peca_escaneada.pdf"
    assert caminho_ocr.exists()

    # a cópia com OCR agora tem camada de texto
    documento_ocr = fitz.open(caminho_ocr)
    texto_extraido = documento_ocr[0].get_text()
    documento_ocr.close()
    assert len(texto_extraido.strip()) > 0

    # original intocado
    assert _hash_arquivo(origem / "peca_escaneada.pdf") == hash_antes

    eventos = [e["message"] for e in list_events(conn, step="conversion")]
    assert any("OCR aplicado" in m for m in eventos)

    conn.close()


# --- fatiamento --------------------------------------------------------


def test_fatiar_pdf_gera_blocos_com_numeracao_real(tmp_path):
    origem = tmp_path / "origem.pdf"
    _criar_pdf_nativo(origem, n_paginas=5)

    pasta_destino = tmp_path / "blocks"
    blocos = slice_pdf(origem, pasta_destino, "documento", pages_per_block=2)

    nomes = sorted(b.name for b in blocos)
    assert nomes == ["documento_p1-2.pdf", "documento_p3-4.pdf", "documento_p5-5.pdf"]

    doc_bloco_final = fitz.open(pasta_destino / "documento_p5-5.pdf")
    assert doc_bloco_final.page_count == 1
    doc_bloco_final.close()


def test_pdf_grande_e_fatiado_durante_a_conversao(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    config.pages_per_block = 2
    _criar_pdf_nativo(origem / "processo_longo.pdf", n_paginas=5)

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.sliced == 1
    assert resultado.blocks_generated == 3

    pasta_blocos = saida / "blocks"
    nomes = sorted(p.name for p in pasta_blocos.glob("*.pdf"))
    assert nomes == ["processo_longo_p1-2.pdf", "processo_longo_p3-4.pdf", "processo_longo_p5-5.pdf"]

    conn.close()


# --- imagem --------------------------------------------------------------


def test_imagem_e_convertida_via_ocr(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    imagem = Image.new("RGB", (900, 300), "white")
    desenho = ImageDraw.Draw(imagem)
    desenho.text((30, 120), "FOTO DE DOCUMENTO PARA TESTE", fill="black")
    imagem.save(origem / "foto.jpg")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.converted == 1
    assert resultado.ocr_applied == 1

    linha = conn.execute("SELECT * FROM file WHERE name = 'foto.jpg'").fetchone()
    assert linha["status"] == "converted"
    assert linha["needs_ocr"] == 1
    assert linha["page_count"] == 1

    destino_txt = saida / "converted" / "foto.txt"
    assert destino_txt.exists()

    conn.close()


# --- docx ------------------------------------------------------------------


def test_docx_e_extraido_sem_ocr(tmp_path):
    from docx import Document

    origem, saida, config, conn = _preparar_projeto(tmp_path)
    documento = Document()
    documento.add_paragraph("Texto de teste do documento DOCX.")
    documento.save(origem / "memorando.docx")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.converted == 1
    assert resultado.ocr_applied == 0

    linha = conn.execute("SELECT * FROM file WHERE name = 'memorando.docx'").fetchone()
    assert linha["status"] == "converted"
    assert linha["needs_ocr"] == 0

    destino_txt = saida / "converted" / "memorando.txt"
    assert destino_txt.exists()
    assert "Texto de teste do documento DOCX." in destino_txt.read_text(encoding="utf-8")

    conn.close()


# --- corrupção e continuidade -----------------------------------------------


def test_arquivo_corrompido_registra_erro_e_processo_continua(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    (origem / "corrompido.pdf").write_bytes(b"isto nao e um pdf valido")
    _criar_pdf_nativo(origem / "valido.pdf")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.failed == 1
    assert resultado.converted == 1

    linha_ruim = conn.execute("SELECT * FROM file WHERE name = 'corrompido.pdf'").fetchone()
    assert linha_ruim["status"] == "failed"
    assert linha_ruim["error"] is not None and linha_ruim["error"] != ""

    linha_boa = conn.execute("SELECT * FROM file WHERE name = 'valido.pdf'").fetchone()
    assert linha_boa["status"] == "converted"

    eventos_erro = [e for e in list_events(conn, step="conversion") if e["level"] == "error"]
    assert any("corrompido.pdf" in e["message"] for e in eventos_erro)

    conn.close()


def test_nenhuma_escrita_fora_da_pasta_de_saida(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    _criar_pdf_escaneado(origem / "escaneado.pdf")

    arquivos_antes = sorted(p.name for p in origem.iterdir())

    scan(conn, config)
    convert(conn, config)

    arquivos_depois = sorted(p.name for p in origem.iterdir())
    assert arquivos_antes == arquivos_depois

    conn.close()

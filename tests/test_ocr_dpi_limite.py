"""2.1.3: página com um ícone minúsculo em alta resolução.

Os processos do órgão trazem em toda página um ícone de 700×600 px desenhado
num espaço de 11×10 pontos: 4.500 DPI. O ocrmypdf rasteriza a página inteira
na maior resolução das imagens dela, e a folha A4 virava uma imagem de
1,96 gigapixel. O Pillow recusava (`DecompressionBombError`) e o OCR do
arquivo inteiro falhava: 599 de 608 páginas ficavam em branco no índice.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import fitz
import pytest
from ocrmypdf import _pipeline
from ocrmypdf.helpers import Resolution

from gclaude_indexer import _ocr_runner, conversion, tools


def _page_context(dpi: float):
    pageinfo = SimpleNamespace(dpi=Resolution(dpi, dpi), page_dpi_profile=lambda: None)
    return SimpleNamespace(pageinfo=pageinfo)


def test_resolucao_da_pagina_e_limitada(monkeypatch):
    monkeypatch.setattr(_pipeline, "calculate_image_dpi", _pipeline.calculate_image_dpi)
    _ocr_runner.limit_raster_dpi()
    dpi = _pipeline.calculate_image_dpi(_page_context(4500.0))
    assert dpi.x == dpi.y == _ocr_runner.MAX_RASTER_DPI


def test_resolucao_normal_nao_muda(monkeypatch):
    monkeypatch.setattr(_pipeline, "calculate_image_dpi", _pipeline.calculate_image_dpi)
    _ocr_runner.limit_raster_dpi()
    dpi = _pipeline.calculate_image_dpi(_page_context(300.0))
    assert (dpi.x, dpi.y) == (300.0, 300.0)


def _pdf_com_icone_minusculo(path):
    from PIL import Image

    rng = random.Random(7)
    icon = Image.frombytes("RGB", (700, 600), bytes(rng.randrange(256) for _ in range(700 * 600 * 3)))
    icon_path = path.with_suffix(".png")
    icon.save(icon_path)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(240.5, 582.6, 251.7, 592.2), filename=str(icon_path))
    document.save(path)
    document.close()


@pytest.mark.skipif(
    not (tools.find("tesseract") and tools.find_ghostscript()), reason="sem Tesseract ou Ghostscript"
)
def test_ocr_de_pagina_com_icone_em_4500_dpi_nao_falha(tmp_path):
    source = tmp_path / "orgao.pdf"
    _pdf_com_icone_minusculo(source)
    destination = tmp_path / "saida.pdf"
    conversion._run_ocrmypdf(source, destination, "eng", pages=[1])
    assert destination.exists()

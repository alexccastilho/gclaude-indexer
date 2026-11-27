"""2.1.3: página em branco com um ícone não vai para o OCR.

Processos digitalizados podem ter milhares de páginas vazias, só com o rodapé "Para
verificar as assinaturas..." (texto nativo de 99 caracteres) e um ícone de
11×10 pontos. Pouco texto e uma imagem bastavam para a página ir ao OCR:
poucos arquivos somavam milhares de páginas assim, horas de OCR para texto nenhum.
"""

from __future__ import annotations

import fitz
from PIL import Image

from gclaude_indexer import ocr_detection

RODAPE = "Para verificar as assinaturas, acesse www.exemplo.gov.br/autenticidade e informe o código 12345678."


def _pagina(tmp_path, image_rect: fitz.Rect):
    icon = tmp_path / "icone.png"
    Image.new("L", (700, 600), 128).save(icon)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((140, 836), RODAPE, fontsize=6)
    page.insert_image(image_rect, filename=str(icon))
    return document, page


def test_pagina_so_com_icone_nao_precisa_de_ocr(tmp_path):
    document, page = _pagina(tmp_path, fitz.Rect(117, 829, 128, 839))
    assert not ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()


def test_pagina_escaneada_continua_precisando_de_ocr(tmp_path):
    document, page = _pagina(tmp_path, fitz.Rect(0, 0, 595, 820))
    assert ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()


def test_assinatura_escaneada_conta_como_conteudo(tmp_path):
    # Uma assinatura de 2 × 1 polegada é conteúdo que o OCR pode ler.
    document, page = _pagina(tmp_path, fitz.Rect(200, 600, 344, 672))
    assert ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()


def test_retangulo_branco_de_fundo_nao_conta(tmp_path):
    # As páginas vazias desses processos também têm retângulos brancos preenchidos, sem
    # contorno: invisíveis no papel branco, nada para o OCR.
    document, page = _pagina(tmp_path, fitz.Rect(117, 829, 128, 839))
    page.draw_rect(fitz.Rect(37, 57, 316, 783), color=None, fill=(1, 1, 1))
    assert not ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()


def test_formulario_vazio_com_barras_e_linhas_nao_conta(tmp_path):
    # Folha de formulário em branco: barras cinza e linhas de tabela.
    # Retângulo e linha reta não são texto; o OCR não teria o que ler.
    document, page = _pagina(tmp_path, fitz.Rect(117, 829, 128, 839))
    page.draw_rect(fitz.Rect(37, 57, 537, 80), color=None, fill=(0.88, 0.88, 0.88))
    page.draw_line(fitz.Point(37, 132), fitz.Point(37, 755), color=(0, 0, 0))
    page.draw_rect(fitz.Rect(37, 57, 316, 780), color=(0, 0, 0))
    assert not ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()


def test_texto_convertido_em_curvas_continua_contando(tmp_path):
    # Texto convertido em curvas é desenho com curvas: o OCR é que o lê.
    document, page = _pagina(tmp_path, fitz.Rect(117, 829, 128, 839))
    shape = page.new_shape()
    for x in range(60, 500, 20):
        shape.draw_bezier((x, 100), (x + 5, 80), (x + 10, 120), (x + 15, 100))
    shape.finish(color=(0, 0, 0), fill=(0, 0, 0))
    shape.commit()
    assert ocr_detection.page_needs_ocr(page, page.get_text().strip())
    document.close()

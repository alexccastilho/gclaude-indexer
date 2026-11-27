"""2.1.3: foto girada ao contrário pelo OSD.

Nas fotos de ofícios (celular, papel em pé), o OSD do Tesseract
mandava girar 180° três de dez fotos, com confiança baixa (0,4 a 3,3). O
OCR lia a página de cabeça para baixo e o índice guardava texto ilegível
("ODIO O GLUIONUI © APBPIONUAINGIQ"). Ler as duas orientações e ficar com a
de maior confiança média por palavra acertou as dez.
"""

from __future__ import annotations

import fitz
import pytest
from PIL import Image

from gclaude_indexer import ocr_detection, tools

PARAGRAFO = (
    "O Tribunal de Contas da União comunica que o processo indicado nesta\n"
    "notificação está disponível para consulta. Em caso de dúvida, favor\n"
    "entrar em contato com a Central de Atendimento pelo telefone indicado."
)


def _foto_em_pe():
    document = fitz.open()
    page = document.new_page(width=420, height=200)
    page.insert_text((20, 40), PARAGRAFO, fontsize=11)
    pixmap = page.get_pixmap(dpi=200, colorspace="gray")
    document.close()
    return Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)


pytestmark = pytest.mark.skipif(not tools.find("tesseract"), reason="sem Tesseract")


@pytest.fixture(autouse=True)
def _tesseract_no_path():
    tools.ensure_on_path()


def test_rotacao_errada_do_osd_e_desfeita():
    assert ocr_detection.confirm_rotation(_foto_em_pe(), 180, "eng") == 0


def test_rotacao_certa_do_osd_e_mantida():
    de_cabeca_para_baixo = _foto_em_pe().rotate(180, expand=True)
    assert ocr_detection.confirm_rotation(de_cabeca_para_baixo, 180, "eng") == 180


def test_sem_rotacao_nada_a_conferir():
    assert ocr_detection.confirm_rotation(_foto_em_pe(), 0, "eng") == 0


# Os outros caminhos que giram uma imagem também passam pela conferência.


def test_imagem_refeita_tambem_confere_a_rotacao(tmp_path, monkeypatch):
    from gclaude_indexer import ocr_detection as od

    _foto_em_pe().save(tmp_path / "foto.png")
    monkeypatch.setattr(od, "osd_image", lambda _imagem: ("latin", 180))
    monkeypatch.setattr(od, "confirm_rotation", lambda _imagem, _graus, _modelo: 0)
    row = {"id": 1, "relative_path": "foto.png", "extension": "png", "ocr_lang": "por"}
    result = od.detect_file(row, str(tmp_path), frozenset({"osd", "eng", "por"}), True)
    assert result["rotate"] == {1: 0}
    assert result["samples"] == {} and result["needs"] == []


def test_releitura_de_imagem_confere_a_rotacao(tmp_path, monkeypatch):
    from gclaude_indexer import conversion, language_detect, ocr_detection as od

    _foto_em_pe().save(tmp_path / "foto.png")
    monkeypatch.setattr(od, "osd_image", lambda _imagem: ("cyrillic", 180))
    monkeypatch.setattr(od, "confirm_rotation", lambda _imagem, _graus, _modelo: 0)
    pedidos = []
    monkeypatch.setattr(
        conversion, "_extract_text_image", lambda _p, lang, rotate=0: pedidos.append((lang, rotate)) or "текст длинный"
    )
    modelo = language_detect.script_model("cyrillic")
    conversion._reread_image(tmp_path / "foto.png", "", "por", 0, None, [], "foto.png")
    assert pedidos == [(modelo, 0)]

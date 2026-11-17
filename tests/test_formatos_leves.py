# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Formatos leves da 2.0.0: variantes do OOXML, OpenDocument, paginados do
PyMuPDF, imagens extras, assinaturas ICP-Brasil, RTF, XLS, MBOX, DXF e
legendas.

Cada formato é gerado aqui, no teste (nada de binário no repositório), e
percorre a conversão e a extração de verdade.
"""

from __future__ import annotations

import datetime
import io
import shutil
import struct
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from gclaude_indexer import artifacts, conversion, fulltext, light_formats, ocr_languages, workdir
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert, converted_artifact_path
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.file_types import (
    CATEGORY_ALL, CATEGORY_FAMILIES, EXTENSION_CATEGORIES, categories_by_family, category_of_extension,
    index_decision, is_extension_allowed, is_whole_document_file,
)
from gclaude_indexer.i18n import translate
from gclaude_indexer.scanning import scan


# --- apoio -----------------------------------------------------------------------


def _projeto(tmp_path, extensoes):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Formatos leves",
        "source_folder": str(origem),
        "output_folder": str(saida),
        "extensions": extensoes,
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


def _processar(conn, config):
    scan(conn, config)
    resultado = convert(conn, config)
    assert resultado.failed == 0, [dict(r) for r in conn.execute("SELECT name, error FROM file WHERE error IS NOT NULL")]
    extract_pages(conn, config)
    return resultado


def _paginas(conn, nome):
    return [
        row["text"] for row in conn.execute(
            "SELECT p.text AS text FROM page p JOIN file f ON f.id = p.file_id WHERE f.name = ?"
            " ORDER BY p.number", (nome,),
        )
    ]


def _arquivo(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


@pytest.fixture(autouse=True)
def _sem_idioma_faltando(monkeypatch):
    """O idioma do OCR existe, onde a conversão pergunta."""
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])


# --- categorias, famílias e rótulos -------------------------------------------------

NOVAS = {
    "opendocument": {".odt", ".ods", ".odp", ".odg", ".fodt", ".fods", ".fodp"},
    "rtf": {".rtf"},
    "paginados": {".xps", ".oxps", ".epub", ".mobi", ".fb2", ".svg", ".cbz"},
    "legendas": {".srt", ".vtt"},
    "mbox": {".mbox"},
    "outlook": {".pst", ".ost"},
    "cad": {".dxf"},
    "assinados": {".p7s", ".p7m"},
}


@pytest.mark.parametrize("categoria, extensoes", sorted(NOVAS.items()))
def test_categoria_nova_cobre_as_extensoes(categoria, extensoes):
    assert EXTENSION_CATEGORIES[categoria] == extensoes
    for extensao in extensoes:
        assert category_of_extension(extensao) == categoria
        assert is_extension_allowed(extensao, [CATEGORY_ALL])
        assert is_extension_allowed(extensao, [categoria])
        assert index_decision(f"arquivo{extensao}", b"", [CATEGORY_ALL]) is None


def test_variantes_e_imagens_entram_nas_categorias_antigas():
    assert {".docm", ".dotx", ".dotm"} <= EXTENSION_CATEGORIES["docx"]
    assert {".xlsm", ".xltx", ".xltm", ".xls"} <= EXTENSION_CATEGORIES["xlsx"]
    assert {".pptm", ".ppsx", ".potx", ".potm"} <= EXTENSION_CATEGORIES["pptx"]
    assert {".jp2", ".j2k", ".jpx", ".jfif", ".jpe", ".heic", ".heif"} <= EXTENSION_CATEGORIES["imagens"]


def test_toda_categoria_aparece_numa_familia_do_formulario_com_rotulo_nos_tres_idiomas():
    em_familias = {c for categorias in CATEGORY_FAMILIES.values() for c in categorias}
    assert em_familias == set(EXTENSION_CATEGORIES) - {"midia"}
    assert {c for _familia, itens in categories_by_family() for i in itens for c in [i["categoria"]]} == em_familias
    for idioma in ("pt-BR", "en", "es"):
        for categoria in em_familias:
            chave = f"new_project.category.{categoria}"
            assert translate(idioma, chave) != chave, (idioma, chave)
        for familia in CATEGORY_FAMILIES:
            chave = f"new_project.family.{familia}"
            assert translate(idioma, chave) != chave, (idioma, chave)


def test_audio_e_video_seguem_de_fora_do_todos():
    assert not is_extension_allowed(".mp3", [CATEGORY_ALL])


def test_paginados_nao_sao_documento_inteiro():
    assert not is_whole_document_file("livro.epub")
    assert not is_whole_document_file("foto.heic")
    assert is_whole_document_file("caixa.mbox")
    assert is_whole_document_file("lei.odt")
    # Um assinado é um documento só (o contrato assinado): o limite entre
    # arquivos vale, e as páginas de dentro seguem com a extração.
    assert is_whole_document_file("contrato.pdf.p7m")


# --- variantes do OOXML -----------------------------------------------------------------


def _com_outro_tipo(dados: bytes, antigo: str, novo: str) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(dados)) as origem, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in origem.infolist():
            conteudo = origem.read(info.filename)
            if info.filename == "[Content_Types].xml":
                texto = conteudo.decode("utf-8")
                assert antigo in texto
                conteudo = texto.replace(antigo, novo).encode("utf-8")
            destino.writestr(info.filename, conteudo)
    return saida.getvalue()


_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_PPT = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"


def _docx_bytes() -> bytes:
    from docx import Document

    documento = Document()
    documento.add_paragraph("Cláusula primeira do contrato")
    tabela = documento.add_table(rows=1, cols=2)
    tabela.rows[0].cells[0].text = "valor"
    tabela.rows[0].cells[1].text = "R$ 10"
    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("extensao, tipo", [
    (".docm", "application/vnd.ms-word.document.macroEnabled.main+xml"),
    (".dotx", "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"),
    (".dotm", "application/vnd.ms-word.template.macroEnabledTemplate.main+xml"),
])
def test_variantes_do_word(tmp_path, extensao, tipo):
    origem, saida, config, conn = _projeto(tmp_path, ["docx"])
    (origem / f"modelo{extensao}").write_bytes(_com_outro_tipo(_docx_bytes(), _WORD, tipo))

    _processar(conn, config)

    texto = _paginas(conn, f"modelo{extensao}")[0]
    assert "Cláusula primeira do contrato" in texto
    assert "valor\tR$ 10" in texto
    linha = conn.execute("SELECT has_table FROM page JOIN file ON file.id = page.file_id WHERE file.name = ?",
                         (f"modelo{extensao}",)).fetchone()
    assert linha["has_table"] == 1
    conn.close()


@pytest.mark.parametrize("extensao, tipo", [
    (".pptm", "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"),
    (".ppsx", "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml"),
    (".potx", "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"),
    (".potm", "application/vnd.ms-powerpoint.template.macroEnabled.main+xml"),
])
def test_variantes_do_powerpoint(tmp_path, extensao, tipo):
    from pptx import Presentation
    from pptx.util import Inches

    origem, saida, config, conn = _projeto(tmp_path, ["pptx"])
    apresentacao = Presentation()
    slide = apresentacao.slides.add_slide(apresentacao.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = "Pauta da reunião"
    buffer = io.BytesIO()
    apresentacao.save(buffer)
    (origem / f"aula{extensao}").write_bytes(_com_outro_tipo(buffer.getvalue(), _PPT, tipo))

    _processar(conn, config)

    assert "Pauta da reunião" in _paginas(conn, f"aula{extensao}")[0]
    conn.close()


@pytest.mark.parametrize("extensao", [".xlsm", ".xltx", ".xltm"])
def test_variantes_do_excel(tmp_path, extensao):
    from openpyxl import Workbook

    origem, saida, config, conn = _projeto(tmp_path, ["xlsx"])
    planilha = Workbook()
    planilha.active["A1"] = "Total"
    planilha.active["B1"] = 42
    planilha.save(origem / f"contas{extensao}")

    _processar(conn, config)

    assert "Total\t42" in _paginas(conn, f"contas{extensao}")[0]
    conn.close()


# --- OpenDocument --------------------------------------------------------------------------

_ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)
_ODF_ESTILOS = (
    '<office:automatic-styles><style:style style:name="T1" style:family="text">'
    '<style:text-properties style:text-line-through-style="solid"/></style:style></office:automatic-styles>'
)
_ODF_CORPO_TEXTO = (
    '<office:body><office:text>'
    '<text:tracked-changes><text:changed-region><text:deletion><text:p>apagado pela revisão</text:p>'
    '</text:deletion></text:changed-region></text:tracked-changes>'
    '<text:h text:outline-level="1">Lei de teste</text:h>'
    '<text:p>Art. 1º <text:span text:style-name="T1">Revogado.</text:span> Vigente.</text:p>'
    '<text:p>Com<text:s text:c="2"/>espaço<text:tab/>e aba</text:p>'
    '<table:table><table:table-row>'
    '<table:table-cell><text:p>A1</text:p></table:table-cell>'
    '<table:table-cell><text:p>B1</text:p></table:table-cell>'
    '</table:table-row></table:table>'
    '</office:text></office:body>'
)


def _odf_zip(corpo: str, mimetype: str) -> bytes:
    conteudo = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_ODF_NS}>'
        f'{_ODF_ESTILOS}{corpo}</office:document-content>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        arquivo.writestr("content.xml", conteudo)
    return buffer.getvalue()


def test_odt_traz_texto_tabela_e_tachado(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument"])
    (origem / "lei.odt").write_bytes(_odf_zip(_ODF_CORPO_TEXTO, "application/vnd.oasis.opendocument.text"))

    _processar(conn, config)

    texto = _paginas(conn, "lei.odt")[0]
    assert "Lei de teste" in texto
    assert "Art. 1º ~~Revogado.~~ Vigente." in texto
    assert "Com  espaço\te aba" in texto
    assert "A1\tB1" in texto
    assert "apagado pela revisão" not in texto
    conn.close()


def test_ods_vira_tabela_e_pula_linhas_vazias(tmp_path):
    corpo = (
        '<office:body><office:spreadsheet><table:table table:name="Folha1">'
        '<table:table-row><table:table-cell><text:p>Item</text:p></table:table-cell>'
        '<table:table-cell><text:p>Preço</text:p></table:table-cell></table:table-row>'
        '<table:table-row table:number-rows-repeated="900"><table:table-cell/></table:table-row>'
        '<table:table-row><table:table-cell><text:p>Caneta</text:p></table:table-cell>'
        '<table:table-cell><text:p>3</text:p></table:table-cell></table:table-row>'
        '</table:table></office:spreadsheet></office:body>'
    )
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument"])
    (origem / "preco.ods").write_bytes(_odf_zip(corpo, "application/vnd.oasis.opendocument.spreadsheet"))

    _processar(conn, config)

    assert _paginas(conn, "preco.ods") == ["Item\tPreço\nCaneta\t3"]
    tabela = conn.execute("SELECT has_table FROM page").fetchone()["has_table"]
    assert tabela == 1
    conn.close()


def test_odp_e_odg_trazem_o_texto_dos_quadros(tmp_path):
    corpo = (
        '<office:body><office:presentation><draw:page><draw:frame><draw:text-box>'
        '<text:p>Slide um</text:p></draw:text-box></draw:frame></draw:page>'
        '<draw:page><draw:frame><draw:text-box><text:p>Slide dois</text:p></draw:text-box></draw:frame>'
        '</draw:page></office:presentation></office:body>'
    )
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument"])
    (origem / "aula.odp").write_bytes(_odf_zip(corpo, "application/vnd.oasis.opendocument.presentation"))
    (origem / "figura.odg").write_bytes(_odf_zip(corpo, "application/vnd.oasis.opendocument.graphics"))

    _processar(conn, config)

    assert _paginas(conn, "aula.odp") == ["Slide um\nSlide dois"]
    assert "Slide um" in _paginas(conn, "figura.odg")[0]
    conn.close()


@pytest.mark.parametrize("extensao", [".fodt", ".fods", ".fodp"])
def test_opendocument_plano_e_um_xml_so(tmp_path, extensao):
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document {_ODF_NS}>{_ODF_ESTILOS}'
        f'{_ODF_CORPO_TEXTO}</office:document>'
    )
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument"])
    (origem / f"plano{extensao}").write_text(xml, encoding="utf-8")

    _processar(conn, config)

    assert "Art. 1º ~~Revogado.~~ Vigente." in _paginas(conn, f"plano{extensao}")[0]
    conn.close()


def test_opendocument_corrompido_falha_sem_derrubar_o_resto(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument", "text"])
    (origem / "quebrado.odt").write_bytes(b"isto nao e um zip")
    (origem / "nota.txt").write_text("segue valendo", encoding="utf-8")
    scan(conn, config)

    resultado = convert(conn, config)

    assert resultado.failed == 1 and resultado.converted == 1
    assert _arquivo(conn, "quebrado.odt")["status"] == "failed"
    assert _arquivo(conn, "nota.txt")["status"] == "converted"
    conn.close()


# --- paginados (PyMuPDF) ---------------------------------------------------------------------


def _svg(destino: Path) -> str:
    destino.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
        '<text x="10" y="50">Olá SVG teste</text></svg>', encoding="utf-8",
    )
    return "Olá SVG teste"


def _epub(destino: Path) -> str:
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="c.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "c.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title>'
            '<dc:identifier id="id">x</dc:identifier><dc:language>pt</dc:language></metadata>'
            '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine></package>',
        )
        z.writestr(
            "c1.xhtml",
            '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>'
            '</head><body><p>Capítulo um do livro EPUB</p></body></html>',
        )
    return "Capítulo um do livro EPUB"


def _fb2(destino: Path) -> str:
    destino.write_text(
        '<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        '<description><title-info><book-title>T</book-title></title-info></description>'
        '<body><section><p>Texto do FB2 aqui</p></section></body></FictionBook>', encoding="utf-8",
    )
    return "Texto do FB2 aqui"


def _xps(destino: Path) -> str:
    import fitz

    tipos = (
        '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/>'
        '<Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>'
        '<Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>'
        '<Default Extension="ttf" ContentType="application/vnd.ms-opentype"/></Types>'
    )
    relacoes = (
        '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="R0" Type="http://schemas.microsoft.com/xps/2005/06/fixedrepresentation" '
        'Target="/FixedDocumentSequence.fdseq"/></Relationships>'
    )
    ns = 'xmlns="http://schemas.microsoft.com/xps/2005/06"'
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", relacoes)
        z.writestr("FixedDocumentSequence.fdseq", f'<FixedDocumentSequence {ns}><DocumentReference Source="/Documents/1/FixedDocument.fdoc"/></FixedDocumentSequence>')
        z.writestr("Documents/1/FixedDocument.fdoc", f'<FixedDocument {ns}><PageContent Source="/Documents/1/Pages/1.fpage"/></FixedDocument>')
        z.writestr(
            "Documents/1/Pages/1.fpage",
            f'<FixedPage {ns} Width="816" Height="1056" xml:lang="en-US"><Glyphs OriginX="96" OriginY="96" '
            'FontRenderingEmSize="24" FontUri="/Resources/f.ttf" UnicodeString="Texto do XPS aqui" Fill="#FF000000"/></FixedPage>',
        )
        # A fonte que o próprio PyMuPDF traz: nada de binário no repositório.
        z.writestr("Resources/f.ttf", fitz.Font("helv").buffer)
    return "Texto do XPS aqui"


def _mobi(destino: Path) -> str:
    html = "<html><body><p>Livro MOBI texto simples</p></body></html>".encode()
    mobi = bytearray(232)
    mobi[0:4] = b"MOBI"
    struct.pack_into(">I", mobi, 4, 232)
    struct.pack_into(">I", mobi, 8, 2)
    struct.pack_into(">I", mobi, 12, 65001)
    struct.pack_into(">I", mobi, 16, 1234)
    struct.pack_into(">I", mobi, 20, 6)
    for deslocamento in range(24, 64, 4):
        struct.pack_into(">I", mobi, deslocamento, 0xFFFFFFFF)
    registro0 = struct.pack(">HHIHHHH", 1, 0, len(html), 1, 4096, 0, 0) + bytes(mobi) + b"\x00" * 8
    cabecalho = bytearray(78)
    cabecalho[0:6] = b"teste\x00"
    cabecalho[60:64] = b"BOOK"
    cabecalho[64:68] = b"MOBI"
    struct.pack_into(">H", cabecalho, 76, 2)
    base = 78 + 8 * 2 + 2
    entradas = struct.pack(">IBBBB", base, 0, 0, 0, 0) + struct.pack(">IBBBB", base + len(registro0), 0, 0, 0, 1)
    destino.write_bytes(bytes(cabecalho) + entradas + b"\x00\x00" + registro0 + html)
    return "Livro MOBI texto simples"


FABRICAS = {
    ".svg": _svg, ".epub": _epub, ".fb2": _fb2, ".xps": _xps, ".oxps": _xps, ".mobi": _mobi,
}


@pytest.mark.parametrize("extensao", sorted(FABRICAS))
def test_paginados_viram_pdf_intermediario_com_texto_nativo(tmp_path, extensao, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path, ["paginados"])
    esperado = FABRICAS[extensao](origem / f"obra{extensao}")

    def _sem_ocr(*_a, **_k):
        raise AssertionError("texto nativo não pede OCR")

    monkeypatch.setattr(conversion, "_run_ocrmypdf", _sem_ocr)
    _processar(conn, config)

    linha = _arquivo(conn, f"obra{extensao}")
    assert linha["status"] == "extracted" and linha["page_count"] == 1 and linha["needs_ocr"] == 0
    assert esperado in _paginas(conn, f"obra{extensao}")[0]
    intermediario = converted_artifact_path(saida, f"obra{extensao}", extensao, False)
    assert intermediario.name == f"obra{extensao}.pdf" and intermediario.exists()
    assert not list(intermediario.parent.glob("*.raw.pdf"))
    # Os paginados têm páginas de verdade: a busca cita a página.
    achados = fulltext.passages_for_file(conn, config, linha)
    assert any(esperado in passagem.text for passagem in achados)
    conn.close()


def test_cbz_sem_texto_passa_pelo_ocr_das_paginas(tmp_path, monkeypatch):
    from PIL import Image

    origem, saida, config, conn = _projeto(tmp_path, ["paginados"])
    imagem = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(imagem, "PNG")
    with zipfile.ZipFile(origem / "gibi.cbz", "w") as z:
        z.writestr("1.png", imagem.getvalue())
        z.writestr("2.png", imagem.getvalue())
    pedidos = []

    def _ocr_falso(origem_pdf, destino, idioma, jobs=1, pages=None):
        pedidos.append((Path(origem_pdf).name, idioma, pages))
        shutil.copyfile(origem_pdf, destino)

    monkeypatch.setattr(conversion, "_run_ocrmypdf", _ocr_falso)

    resultado = _processar(conn, config)

    assert pedidos == [("gibi.cbz.raw.pdf", config.ocr_language, [1, 2])]
    linha = _arquivo(conn, "gibi.cbz")
    assert linha["status"] == "extracted" and linha["page_count"] == 2 and linha["needs_ocr"] == 1
    assert resultado.ocr_applied == 1
    assert not list(workdir.work_folder(saida).rglob("*.raw.pdf"))
    conn.close()


def test_paginado_corrompido_falha_com_mensagem_e_sem_conteudo(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["paginados"])
    (origem / "quebrado.epub").write_bytes(b"nao e epub")
    scan(conn, config)

    resultado = convert(conn, config)

    assert resultado.failed == 1
    assert _arquivo(conn, "quebrado.epub")["status"] == "failed"
    conn.close()


# --- imagens extras ----------------------------------------------------------------------------


@pytest.mark.parametrize("extensao", [".jp2", ".j2k", ".jpx", ".jfif", ".jpe", ".heic", ".heif"])
def test_imagens_extras_abrem_para_o_ocr(tmp_path, monkeypatch, extensao):
    import pytesseract
    from PIL import Image

    destino = tmp_path / f"foto{extensao}"
    imagem = Image.new("RGB", (64, 48), "white")
    if extensao in (".heic", ".heif"):
        import pillow_heif

        pillow_heif.from_pillow(imagem).save(str(destino))
    elif extensao in (".jfif", ".jpe"):
        imagem.save(destino, format="JPEG")
    else:
        imagem.save(destino, format="JPEG2000")
    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, lang: f"{img.width}x{img.height}:{lang}")

    assert conversion._extract_text_image(destino, "por") == "64x48:por"


def test_heic_percorre_a_conversao_inteira(tmp_path, monkeypatch):
    import pillow_heif
    import pytesseract
    from PIL import Image

    origem, saida, config, conn = _projeto(tmp_path, ["imagens"])
    pillow_heif.from_pillow(Image.new("RGB", (32, 32), "white")).save(str(origem / "iphone.heic"))
    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, lang: "texto lido da foto")

    _processar(conn, config)

    assert _paginas(conn, "iphone.heic") == ["texto lido da foto"]
    conn.close()


# --- RTF ------------------------------------------------------------------------------------------


def test_rtf_vira_texto_com_acentos(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["rtf"])
    (origem / "oficio.rtf").write_bytes(
        b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0 Arial;}}\\f0\\fs24 Of\\'edcio n\\'ba 12\\par "
        b"Assunto: concess\\'e3o de prazo\\par}"
    )

    _processar(conn, config)

    texto = _paginas(conn, "oficio.rtf")[0]
    assert "Ofício nº 12" in texto and "Assunto: concessão de prazo" in texto
    assert "\\" not in texto
    conn.close()


# --- XLS ---------------------------------------------------------------------------------------------


def _xls_biff2(linhas: list[list]) -> bytes:
    """Planilha BIFF2, a mais simples que o `xlrd` lê: cabeçalho, células e fim."""
    saida = b"\x09\x00\x04\x00\x00\x00\x10\x00"
    for numero, linha in enumerate(linhas):
        for coluna, valor in enumerate(linha):
            if isinstance(valor, str):
                bruto = valor.encode("cp1252")
                dados = struct.pack("<HH", numero, coluna) + b"\x00\x00\x00" + bytes([len(bruto)]) + bruto
                saida += struct.pack("<HH", 0x0004, len(dados)) + dados
            else:
                dados = struct.pack("<HH", numero, coluna) + b"\x00\x00\x00" + struct.pack("<d", valor)
                saida += struct.pack("<HH", 0x0003, len(dados)) + dados
    return saida + b"\x0a\x00\x00\x00"


def test_xls_antigo_e_lido_pelo_xlrd(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["xlsx"])
    (origem / "antiga.xls").write_bytes(_xls_biff2([["Descrição", "Valor"], ["Café", 12.0], ["Pão", 3.5]]))
    (origem / "antiga.xlsx").write_bytes(b"")  # mesmo nome-base: o intermediário não pode colidir

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)

    texto = _paginas(conn, "antiga.xls")[0]
    assert texto == "Descrição\tValor\nCafé\t12\nPão\t3.5"
    assert converted_artifact_path(saida, "antiga.xls", "xls", False).name == "antiga.xls.txt"
    assert converted_artifact_path(saida, "antiga.xlsx", "xlsx", False).name == "antiga.txt"
    conn.close()


def test_xls_que_na_verdade_e_html_ou_texto_nao_falha(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["xlsx"])
    (origem / "exportado.xls").write_bytes(
        "<html><body><table><tr><td>Código</td><td>Nome</td></tr></table></body></html>".encode("utf-8")
    )
    (origem / "tabulado.xls").write_bytes("a\tb\n1\t2\n".encode("utf-8"))

    _processar(conn, config)

    assert "Código" in _paginas(conn, "exportado.xls")[0] and "<td>" not in _paginas(conn, "exportado.xls")[0]
    assert _paginas(conn, "tabulado.xls") == ["a\tb\n1\t2\n"]
    conn.close()


def test_xls_tachado_pela_fonte_da_celula():
    class Fonte:
        struck_out = 1

    class Formato:
        font_index = 0

    class Livro:
        font_list = [Fonte()]
        xf_list = [Formato()]

    class Celula:
        xf_index = 0

    assert light_formats._xls_struck(Livro(), Celula()) is True
    Livro.font_list = [type("F", (), {"struck_out": 0})()]
    assert light_formats._xls_struck(Livro(), Celula()) is False


# --- MBOX ----------------------------------------------------------------------------------------------

_CAIXA = (
    "From ana@x.com Mon Jan  1 10:00:00 2026\n"
    "From: Ana <ana@x.com>\nTo: bia@x.com\nDate: Mon, 1 Jan 2026 10:00:00 +0000\nSubject: Primeira mensagem\n\n"
    "Corpo da primeira.\n\n"
    "From bia@x.com Tue Jan  2 11:00:00 2026\n"
    "From: Bia <bia@x.com>\nTo: ana@x.com\nDate: Tue, 2 Jan 2026 11:00:00 +0000\nSubject: Segunda mensagem\n\n"
    "Corpo da segunda.\n"
)


def test_mbox_cada_mensagem_e_uma_pagina(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["mbox"])
    (origem / "caixa.mbox").write_text(_CAIXA, encoding="utf-8")

    _processar(conn, config)

    paginas = _paginas(conn, "caixa.mbox")
    assert len(paginas) == 2
    assert "From: Ana <ana@x.com>" in paginas[0] and "Subject: Primeira mensagem" in paginas[0]
    assert "Date: Thu, 01 Jan 2026" in paginas[0] and "Corpo da primeira." in paginas[0]
    assert "Subject: Segunda mensagem" in paginas[1] and "Corpo da segunda." in paginas[1]
    linha = _arquivo(conn, "caixa.mbox")
    assert linha["page_count"] == 2
    assert conn.execute("SELECT COUNT(*) FROM page WHERE file_id = ?", (linha["id"],)).fetchone()[0] == 2
    # A busca cita a mensagem (a página) de cada trecho.
    achados = fulltext.passages_for_file(conn, config, linha)
    segunda = next(p for p in achados if "Corpo da segunda." in p.text)
    assert segunda.locator.startswith("f. 2")
    conn.close()


# --- DXF --------------------------------------------------------------------------------------------------


def test_dxf_traz_textos_cotas_e_atributos(tmp_path):
    import ezdxf

    origem, saida, config, conn = _projeto(tmp_path, ["cad"])
    documento = ezdxf.new("R2010")
    desenho = documento.modelspace()
    desenho.add_text("Planta baixa do pavimento 1")
    desenho.add_mtext("Nota: {\\fArial|b1;concreto} fck 30 MPa")
    carimbo = documento.blocks.new("CARIMBO")
    carimbo.add_attdef("PROJETO", (0, 0), text="modelo", dxfattribs={"height": 1})
    desenho.add_blockref("CARIMBO", (0, 0)).add_auto_attribs({"PROJETO": "Edifício Aurora"})
    cota = desenho.add_linear_dim(base=(0, 2), p1=(0, 0), p2=(4, 0), text="vão livre")
    cota.render()
    documento.saveas(origem / "planta.dxf")

    _processar(conn, config)

    texto = _paginas(conn, "planta.dxf")[0]
    assert "Planta baixa do pavimento 1" in texto
    assert "concreto" in texto and "fck 30 MPa" in texto and "\\f" not in texto
    assert "PROJETO: Edifício Aurora" in texto
    assert "vão livre" in texto
    conn.close()


def test_dxf_corrompido_falha_com_mensagem(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["cad"])
    (origem / "lixo.dxf").write_bytes(b"\x00\x01\x02 nao e desenho")
    scan(conn, config)

    assert convert(conn, config).failed == 1
    conn.close()


# --- legendas -------------------------------------------------------------------------------------------------


def test_srt_sem_numeracao_marcas_de_tempo_e_falas_repetidas(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["legendas"])
    (origem / "filme.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nOlá, mundo.\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n<i>Segunda fala</i>\n\n"
        "3\n00:00:04,000 --> 00:00:05,000\nSegunda fala\n\n"
        "4\n00:00:06,000 --> 00:00:07,000\n{\\an8}Fim\n", encoding="utf-8",
    )

    _processar(conn, config)

    assert _paginas(conn, "filme.srt") == ["Olá, mundo.\nSegunda fala\nFim"]
    conn.close()


def test_vtt_sem_cabecalho_notas_e_identificadores(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["legendas"])
    (origem / "aula.vtt").write_text(
        "WEBVTT - Aula\n\nNOTE isto é comentário\nde duas linhas\n\n"
        "intro\n00:01.000 --> 00:02.000 align:start\nPrimeira\n\n"
        "00:03.000 --> 00:04.000\nPrimeira\nSegunda\n\n"
        "01:00:05.000 --> 01:00:06.000\n<v Ana>Terceira</v>\n", encoding="utf-8",
    )

    _processar(conn, config)

    assert _paginas(conn, "aula.vtt") == ["Primeira\nSegunda\nTerceira"]
    conn.close()


# --- assinaturas ICP-Brasil (.p7m / .p7s) ---------------------------------------------------------------------


def _certificado(com_san: bool = True):
    from asn1crypto import core
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "FULANO DE TAL:12345678901"),
    ])
    # Campo ICP-Brasil 2.16.76.1.3.1: nascimento (8) + CPF (11) + NIS + RG + órgão.
    valor = core.OctetString(("01011980" + "12345678901" + "0" * 11 + "0" * 15 + "0" * 6).encode()).dump()
    agora = datetime.datetime.now(datetime.timezone.utc)
    construtor = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - datetime.timedelta(days=1)).not_valid_after(agora + datetime.timedelta(days=30))
    )
    if com_san:
        construtor = construtor.add_extension(
            x509.SubjectAlternativeName([x509.OtherName(ObjectIdentifier("2.16.76.1.3.1"), valor)]), critical=False,
        )
    return construtor.sign(chave, hashes.SHA256()), chave


def _assinar(conteudo: bytes, destacada: bool = False) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    certificado, chave = _certificado()
    opcoes = [pkcs7.PKCS7Options.Binary] + ([pkcs7.PKCS7Options.DetachedSignature] if destacada else [])
    return (
        pkcs7.PKCS7SignatureBuilder().set_data(conteudo).add_signer(certificado, chave, hashes.SHA256())
        .sign(serialization.Encoding.DER, opcoes)
    )


def _pdf(texto: str) -> bytes:
    import fitz

    documento = fitz.open()
    documento.new_page().insert_text((72, 72), texto)
    return documento.tobytes()


def _assinaturas(conn, nome):
    return [
        dict(row) for row in conn.execute(
            "SELECT s.* FROM file_signature s JOIN file f ON f.id = s.file_id WHERE f.name = ? ORDER BY s.rowid",
            (nome,),
        )
    ]


def test_p7m_com_pdf_indexa_o_pdf_interno_e_grava_o_signatario(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    (origem / "contrato.pdf.p7m").write_bytes(_assinar(_pdf("Contrato assinado digitalmente")))

    def _sem_ocr(*_a, **_k):
        raise AssertionError("o PDF tem texto nativo")

    monkeypatch.setattr(conversion, "_run_ocrmypdf", _sem_ocr)
    _processar(conn, config)

    linha = _arquivo(conn, "contrato.pdf.p7m")
    assert linha["status"] == "extracted" and linha["page_count"] == 1
    assert "Contrato assinado digitalmente" in _paginas(conn, "contrato.pdf.p7m")[0]
    assinaturas = _assinaturas(conn, "contrato.pdf.p7m")
    assert len(assinaturas) == 1
    assert assinaturas[0]["signer"] == "FULANO DE TAL"
    assert assinaturas[0]["holder_document"] == "CPF 123.456.789-01"
    assert assinaturas[0]["signed_at"].startswith(datetime.datetime.now().strftime("%Y-%m-%d"))
    assert assinaturas[0]["source"] == "embedded"
    assert converted_artifact_path(saida, "contrato.pdf.p7m", "p7m", False).suffix == ".pdf"
    achados = fulltext.passages_for_file(conn, config, linha)
    assert any("Contrato assinado" in passagem.text for passagem in achados)
    conn.close()


def test_p7m_com_docx_dentro_e_detectado_pelos_bytes(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    # A extensão do arquivo interno nem aparece: só os bytes dizem que é Word.
    (origem / "parecer.p7m").write_bytes(_assinar(_docx_bytes()))

    _processar(conn, config)

    assert "Cláusula primeira do contrato" in _paginas(conn, "parecer.p7m")[0]
    assert _assinaturas(conn, "parecer.p7m")[0]["signer"] == "FULANO DE TAL"
    assert converted_artifact_path(saida, "parecer.p7m", "p7m", False).suffix == ".txt"
    conn.close()


def test_p7m_com_texto_e_aceito_e_com_binario_desconhecido_e_ignorado(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    (origem / "recibo.txt.p7m").write_bytes(_assinar("Recebi a quantia de R$ 100.".encode("utf-8")))
    (origem / "estranho.p7m").write_bytes(_assinar(bytes(range(0, 32)) * 40))

    scan(conn, config)
    resultado = convert(conn, config)
    extract_pages(conn, config)

    assert resultado.failed == 0
    assert _paginas(conn, "recibo.txt.p7m") == ["Recebi a quantia de R$ 100."]
    estranho = _arquivo(conn, "estranho.p7m")
    assert estranho["status"] == "skipped" and estranho["error"] == "binary"
    assert _paginas(conn, "estranho.p7m") == []
    # A assinatura é do arquivo mesmo assim: o índice sabe quem assinou.
    assert _assinaturas(conn, "estranho.p7m")[0]["signer"] == "FULANO DE TAL"
    conn.close()


def test_p7s_destacado_vai_para_o_arquivo_irmao_e_sai_do_indice(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, [CATEGORY_ALL])
    pdf = _pdf("Termo de posse")
    (origem / "termo.pdf").write_bytes(pdf)
    (origem / "termo.pdf.p7s").write_bytes(_assinar(pdf, destacada=True))
    (origem / "ata.pdf").write_bytes(_pdf("Ata da reunião"))
    (origem / "ata.p7s").write_bytes(_assinar(b"qualquer coisa", destacada=True))
    (origem / "sozinha.p7s").write_bytes(_assinar("sem irmão".encode(), destacada=True))

    _processar(conn, config)

    for nome in ("termo.pdf.p7s", "ata.p7s", "sozinha.p7s"):
        linha = _arquivo(conn, nome)
        assert linha["status"] == "skipped" and linha["error"] == "signature_detached", nome
        assert _paginas(conn, nome) == []
    assert [a["source"] for a in _assinaturas(conn, "termo.pdf")] == ["detached:termo.pdf.p7s"]
    assert _assinaturas(conn, "termo.pdf")[0]["signer"] == "FULANO DE TAL"
    assert [a["source"] for a in _assinaturas(conn, "ata.pdf")] == ["detached:ata.p7s"]
    assert conn.execute("SELECT COUNT(*) FROM file_signature").fetchone()[0] == 2
    # O PDF assinado segue indexado normalmente.
    assert "Termo de posse" in _paginas(conn, "termo.pdf")[0]
    conn.close()


def test_p7m_corrompido_falha_sem_derrubar_o_resto(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados", "text"])
    (origem / "falso.p7m").write_bytes(b"isto nao e uma assinatura")
    (origem / "nota.txt").write_text("ok", encoding="utf-8")
    scan(conn, config)

    resultado = convert(conn, config)

    assert resultado.failed == 1 and resultado.converted == 1
    assert _arquivo(conn, "falso.p7m")["status"] == "failed"
    conn.close()


def test_assinatura_em_pem_e_em_base64_tambem_e_lida():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7
    import base64

    certificado, chave = _certificado()
    montar = lambda codificacao: (  # noqa: E731
        pkcs7.PKCS7SignatureBuilder().set_data(b"texto simples").add_signer(certificado, chave, hashes.SHA256())
        .sign(codificacao, [pkcs7.PKCS7Options.Binary])
    )
    em_pem = montar(serialization.Encoding.PEM)
    em_der = montar(serialization.Encoding.DER)

    for dados in (em_pem, base64.b64encode(em_der)):
        lido = light_formats.signed_content_of(dados)
        assert lido.content == b"texto simples"
        assert lido.signatures[0].signer == "FULANO DE TAL"


def test_assinatura_com_o_documento_so_no_nome_do_titular():
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives.serialization import Encoding

    # Sem os campos ICP-Brasil, o documento vem do fim do CN (`NOME:CPF`).
    certificado, _chave = _certificado(com_san=False)
    sem_san = asn1_x509.Certificate.load(certificado.public_bytes(Encoding.DER))
    assert sem_san.subject_alt_name_value is None
    nome, documento = light_formats._holder_document(sem_san)
    assert nome == "FULANO DE TAL" and documento == "CPF 123.456.789-01"


def test_indice_mostra_signatario_e_data_na_coluna_origem(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    (origem / "contrato.pdf.p7m").write_bytes(_assinar(_pdf("Contrato assinado digitalmente")))
    (origem / "outro.pdf.p7m").write_bytes(_assinar(_pdf("Outro contrato")))
    _processar(conn, config)
    grupo = _arquivo(conn, "contrato.pdf.p7m")["group_key"]
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, type, date, author, summary,"
        " has_table, has_image, engine, confidence, files) VALUES (?, 'f. 1', 'f. 1', 1, 1, 'Contrato',"
        " '2026-01-02', 'Fulano', 'Resumo', 0, 0, 'rules', 'high', 'contrato.pdf.p7m')", (grupo,),
    )
    conn.commit()

    caminhos = artifacts.generate_index_md(conn, config, "pt-BR")

    texto = "\n".join(caminho.read_text(encoding="utf-8") for caminho in caminhos)
    data = datetime.datetime.now().strftime("%Y-%m-%d")
    assert f"contrato.pdf.p7m — assinado por FULANO DE TAL (CPF 123.456.789-01), {data}" in texto
    # Sem assinatura gravada, a coluna fica como sempre foi.
    conn.execute("DELETE FROM file_signature")
    conn.commit()
    caminhos = artifacts.generate_index_md(conn, config, "pt-BR")
    assert "assinado por" not in "\n".join(c.read_text(encoding="utf-8") for c in caminhos)
    conn.close()


def test_apagar_o_arquivo_leva_a_assinatura_junto(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    (origem / "contrato.pdf.p7m").write_bytes(_assinar(_pdf("Contrato")))
    _processar(conn, config)
    assert conn.execute("SELECT COUNT(*) FROM file_signature").fetchone()[0] == 1

    conn.execute("DELETE FROM page")
    conn.execute("DELETE FROM file")

    assert conn.execute("SELECT COUNT(*) FROM file_signature").fetchone()[0] == 0
    conn.close()


def test_tabela_de_assinaturas_nasce_em_projeto_antigo(tmp_path):
    conn = connect(tmp_path / "antigo.db")
    init_schema(conn)
    conn.execute("DROP TABLE file_signature")
    init_schema(conn)
    colunas = [row[1] for row in conn.execute("PRAGMA table_info(file_signature)")]
    assert colunas == ["file_id", "signer", "holder_document", "signed_at", "source"]
    conn.close()


# --- conteúdo envelopado: tipo pelos bytes ----------------------------------------------------------------------


def test_tipo_real_do_conteudo_pelos_bytes():
    sniff = light_formats.sniff_content_type
    assert sniff(_pdf("x")) == "pdf"
    assert sniff(_docx_bytes()) == "docx"
    assert sniff(_odf_zip(_ODF_CORPO_TEXTO, "application/vnd.oasis.opendocument.text")) == "odf"
    assert sniff(b"{\\rtf1 oi}") == "rtf"
    assert sniff(b"\xff\xd8\xff\xe0 resto") == "image"
    assert sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "image"
    assert sniff("texto comum".encode()) == "text"
    assert sniff(bytes(range(32)) * 10) == "binary"
    # Um ZIP qualquer é compactado: nunca é aberto.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("a.txt", "dentro")
    assert sniff(buffer.getvalue()) == "binary"


def test_extracao_pdf_de_assinado_usa_o_limite_de_pagina_do_projeto(tmp_path):
    from gclaude_indexer.extraction import chars_limit_for

    config = load_config({
        "name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "s"),
        "chars_per_page": 9000,
    })
    assert chars_limit_for("paginados", config) == 9000
    assert chars_limit_for("assinados", config) == 9000
    assert chars_limit_for("mbox", config) == 4000
    assert chars_limit_for("opendocument", config) == 4000


def test_p7m_com_pdf_de_varias_paginas_mantem_as_paginas(tmp_path):
    import fitz

    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    documento = fitz.open()
    for numero in (1, 2, 3):
        documento.new_page().insert_text((72, 72), f"Cláusula numero {numero} do contrato assinado em varias paginas")
    (origem / "longo.pdf.p7m").write_bytes(_assinar(documento.tobytes()))

    _processar(conn, config)

    paginas = _paginas(conn, "longo.pdf.p7m")
    assert len(paginas) == 3 and "numero 3" in paginas[2]
    assert _arquivo(conn, "longo.pdf.p7m")["page_count"] == 3
    conn.close()


def test_ignorados_pela_conversao_nao_voltam_a_fila_nem_duplicam_assinatura(tmp_path):
    from gclaude_indexer import update_plan

    origem, saida, config, conn = _projeto(tmp_path, [CATEGORY_ALL])
    pasta = origem / "contratos" / "2026"
    pasta.mkdir(parents=True)
    pdf = _pdf("Termo de posse")
    (pasta / "termo.pdf").write_bytes(pdf)
    (pasta / "termo.pdf.p7s").write_bytes(_assinar(pdf, destacada=True))
    (pasta / "estranho.p7m").write_bytes(_assinar(bytes(range(0, 32)) * 40))
    _processar(conn, config)
    antes = {r["name"]: (r["status"], r["error"]) for r in conn.execute("SELECT * FROM file")}
    assert antes["termo.pdf.p7s"] == ("skipped", "signature_detached")
    assert antes["estranho.p7m"] == ("skipped", "binary")
    assert [a["source"] for a in _assinaturas(conn, "termo.pdf")] == ["detached:termo.pdf.p7s"]

    scan(conn, config)
    mudancas, _n, _i = update_plan.detect_changes(conn, config)
    resultado = convert(conn, config)
    extract_pages(conn, config)

    assert mudancas == []
    assert resultado.converted == 0
    assert {r["name"]: (r["status"], r["error"]) for r in conn.execute("SELECT * FROM file")} == antes
    assert conn.execute("SELECT COUNT(*) FROM file_signature").fetchone()[0] == 2
    conn.close()


def test_extensoes_novas_nao_disputam_o_mesmo_intermediario(tmp_path, monkeypatch):
    import pytesseract
    from PIL import Image

    origem, saida, config, conn = _projeto(tmp_path, ["imagens", "docx"])
    Image.new("RGB", (20, 20), "white").save(origem / "IMG_1.jpg")
    Image.new("RGB", (20, 20), "white").save(origem / "IMG_1.jfif", format="JPEG")
    (origem / "X.docx").write_bytes(_docx_bytes())
    (origem / "X.docm").write_bytes(_com_outro_tipo(
        _docx_bytes(), _WORD, "application/vnd.ms-word.document.macroEnabled.main+xml"
    ))
    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, lang: "ocr")

    _processar(conn, config)

    nomes = {converted_artifact_path(saida, n, n.rsplit(".", 1)[1], False).name for n in
             ("IMG_1.jpg", "IMG_1.jfif", "X.docx", "X.docm")}
    assert nomes == {"IMG_1.txt", "IMG_1.jfif.txt", "X.txt", "X.docm.txt"}
    assert _paginas(conn, "IMG_1.jfif") == ["ocr"]
    assert "Cláusula primeira" in _paginas(conn, "X.docm")[0]
    conn.close()


def test_doc_antigo_dentro_do_p7m_e_ignorado_como_binario(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    ole = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) + bytes(range(256)) * 4  # um .doc: OLE que nao e planilha
    (origem / "velho.doc.p7m").write_bytes(_assinar(ole))

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.failed == 0
    linha = _arquivo(conn, "velho.doc.p7m")
    assert linha["status"] == "skipped" and linha["error"] == "binary"
    conn.close()


# --- tetos contra pacote malicioso (bomba de descompressão, amplificação) -------------------------


def _com_tamanho_declarado(dados: bytes, nome: bytes, tamanho: int) -> bytes:
    """O ZIP com o tamanho descompactado de um membro adulterado no diretório
    central, como faz uma bomba: o arquivo é pequeno, o declarado é enorme."""
    posicao = 0
    while True:
        posicao = dados.index(b"PK\x01\x02", posicao)
        comprimento_nome = struct.unpack_from("<H", dados, posicao + 28)[0]
        if dados[posicao + 46: posicao + 46 + comprimento_nome] == nome:
            break
        posicao += 4
    return dados[: posicao + 24] + struct.pack("<I", tamanho) + dados[posicao + 28:]


def test_text_s_com_repeticao_absurda_e_limitado(tmp_path):
    corpo = (
        '<office:body><office:text><text:p>a<text:s text:c="100000000"/>b'
        '<text:s text:c="abc"/>c</text:p></office:text></office:body>'
    )
    arquivo = tmp_path / "bomba.odt"
    arquivo.write_bytes(_odf_zip(corpo, "application/vnd.oasis.opendocument.text"))

    texto = light_formats.extract_text_opendocument(arquivo)

    assert texto == "a" + " " * light_formats._MAX_REPEATED_SPACES + "b c"


def test_texto_do_opendocument_tem_teto(tmp_path, monkeypatch):
    corpo = "<office:body><office:text>" + "<text:p>linha de texto qualquer</text:p>" * 50 + "</office:text></office:body>"
    arquivo = tmp_path / "grande.odt"
    arquivo.write_bytes(_odf_zip(corpo, "application/vnd.oasis.opendocument.text"))
    monkeypatch.setattr(light_formats, "_MAX_TEXT_CHARS", 200)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)


def test_mimetype_que_declara_tamanho_enorme_e_recusado():
    zip_ok = io.BytesIO()
    with zipfile.ZipFile(zip_ok, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", "<x/>")
    adulterado = _com_tamanho_declarado(zip_ok.getvalue(), b"mimetype", 0x7FFFFFFF)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.sniff_content_type(adulterado)


def test_mimetype_grande_de_verdade_tambem_e_recusado():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text" + " " * 5000)
    with pytest.raises(light_formats.LightFormatError):
        light_formats.sniff_content_type(buffer.getvalue())


def test_content_xml_que_declara_tamanho_enorme_e_recusado(tmp_path):
    arquivo = tmp_path / "bomba.odt"
    arquivo.write_bytes(_com_tamanho_declarado(
        _odf_zip(_ODF_CORPO_TEXTO, "application/vnd.oasis.opendocument.text"), b"content.xml", 0x7FFFFFFF,
    ))

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)


def test_pacote_com_membros_demais_e_recusado(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", "<x/>")
        for numero in range(10):
            z.writestr(f"extra{numero}.txt", "x")
    arquivo = tmp_path / "muitos.odt"
    arquivo.write_bytes(buffer.getvalue())
    monkeypatch.setattr(light_formats, "_MAX_ZIP_MEMBERS", 5)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)
    with pytest.raises(light_formats.LightFormatError):
        light_formats.sniff_content_type(buffer.getvalue())


def test_pacote_ooxml_acima_do_orcamento_total_e_recusado(tmp_path, monkeypatch):
    arquivo = tmp_path / "modelo.dotx"
    arquivo.write_bytes(_com_outro_tipo(
        _docx_bytes(), _WORD, "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    ))
    monkeypatch.setattr(light_formats, "_MAX_ZIP_TOTAL_BYTES", 500)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.open_docx(arquivo)


def test_membro_ooxml_acima_do_teto_e_recusado(tmp_path, monkeypatch):
    arquivo = tmp_path / "modelo.docm"
    arquivo.write_bytes(_com_outro_tipo(
        _docx_bytes(), _WORD, "application/vnd.ms-word.document.macroEnabled.main+xml",
    ))
    monkeypatch.setattr(light_formats, "_MAX_ZIP_MEMBER_BYTES", 200)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.open_docx(arquivo)


def test_compressao_suspeita_e_recusada(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.xml", b"\0" * (3 * 1024 * 1024))  # 3 MB que cabem em ~3 KB
    monkeypatch.setattr(light_formats, "_MAX_COMPRESSION_RATIO", 100)

    with zipfile.ZipFile(buffer) as archive:
        with pytest.raises(light_formats.LightFormatError):
            light_formats._read_member(archive, "content.xml")


def test_bomba_vira_erro_do_arquivo_e_o_resto_segue(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path, ["opendocument", "text"])
    (origem / "bomba.odt").write_bytes(_com_tamanho_declarado(
        _odf_zip(_ODF_CORPO_TEXTO, "application/vnd.oasis.opendocument.text"), b"content.xml", 0x7FFFFFFF,
    ))
    (origem / "nota.txt").write_text("segue valendo", encoding="utf-8")
    scan(conn, config)

    resultado = convert(conn, config)

    assert resultado.failed == 1 and resultado.converted == 1
    linha = _arquivo(conn, "bomba.odt")
    assert linha["status"] == "failed" and "grande demais" in linha["error"]
    conn.close()


def test_p7m_com_zip_bomba_dentro_falha_sem_alocar(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, ["assinados"])
    zip_ok = io.BytesIO()
    with zipfile.ZipFile(zip_ok, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", "<x/>")
    bomba = _com_tamanho_declarado(zip_ok.getvalue(), b"mimetype", 0x7FFFFFFF)
    (origem / "bomba.odt.p7m").write_bytes(_assinar(bomba))
    scan(conn, config)

    assert convert(conn, config).failed == 1
    assert _arquivo(conn, "bomba.odt.p7m")["status"] == "failed"
    conn.close()


# --- trabalho, não só texto: tabelas aninhadas, profundidade e nós visitados ----------------------


def _fodt(corpo: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document {_ODF_NS}>'
        f'<office:body><office:text>{corpo}</office:text></office:body></office:document>'
    )


def _tabela(conteudo: str) -> str:
    return (
        '<table:table><table:table-row><table:table-cell>'
        f'{conteudo}</table:table-cell></table:table-row></table:table>'
    )


def test_tabela_aninhada_aparece_uma_vez_so(tmp_path):
    arquivo = tmp_path / "aninhada.fodt"
    arquivo.write_text(_fodt(_tabela("<text:p>fora</text:p>" + _tabela("<text:p>dentro</text:p>"))), encoding="utf-8")

    assert light_formats.extract_text_opendocument(arquivo) == "fora\ndentro"


def test_linhas_de_cabecalho_e_de_grupo_entram_uma_vez(tmp_path):
    corpo = (
        '<table:table><table:table-header-rows><table:table-row><table:table-cell><text:p>Cab</text:p>'
        '</table:table-cell></table:table-row></table:table-header-rows>'
        '<table:table-rows><table:table-row><table:table-cell><text:p>L1</text:p></table:table-cell>'
        '</table:table-row></table:table-rows>'
        '<table:table-row-group><table:table-row><table:table-cell><text:p>L2</text:p></table:table-cell>'
        '</table:table-row></table:table-row-group></table:table>'
    )
    arquivo = tmp_path / "grupos.fodt"
    arquivo.write_text(_fodt(corpo), encoding="utf-8")

    assert light_formats.extract_text_opendocument(arquivo) == "Cab\nL1\nL2"


def test_tabelas_aninhadas_alem_do_limite_sao_recusadas(tmp_path):
    conteudo = "<text:p>fundo</text:p>"
    for _ in range(light_formats._MAX_ODF_DEPTH + 5):
        conteudo = _tabela(conteudo)
    arquivo = tmp_path / "funda.fodt"
    arquivo.write_text(_fodt(conteudo), encoding="utf-8")

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)


def test_span_aninhado_alem_do_limite_e_recusado(tmp_path):
    corpo = "<text:p>" + "<text:span>" * 60 + "x" + "</text:span>" * 60 + "</text:p>"
    arquivo = tmp_path / "spans.fodt"
    arquivo.write_text(_fodt(corpo), encoding="utf-8")

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)


def test_elementos_vazios_demais_estouram_o_orcamento_de_nos(tmp_path, monkeypatch):
    arquivo = tmp_path / "vazio.fodt"
    arquivo.write_text(_fodt("<text:span/>" * 500), encoding="utf-8")
    monkeypatch.setattr(light_formats, "_MAX_ODF_NODES", 100)

    with pytest.raises(light_formats.LightFormatError):
        light_formats.extract_text_opendocument(arquivo)


def test_tabela_larga_e_rasa_legitima_continua_convertendo(tmp_path):
    celulas = "".join(f"<table:table-cell><text:p>c{n}</text:p></table:table-cell>" for n in range(500))
    linhas = "".join(f"<table:table-row>{celulas}</table:table-row>" for _ in range(40))
    arquivo = tmp_path / "larga.fodt"
    arquivo.write_text(_fodt(f"<table:table>{linhas}</table:table>"), encoding="utf-8")

    texto = light_formats.extract_text_opendocument(arquivo)

    assert texto.count("\n") == 39 and texto.splitlines()[0].split("\t")[499] == "c499"

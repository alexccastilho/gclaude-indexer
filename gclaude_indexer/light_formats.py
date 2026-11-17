# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Leitura dos formatos leves da 2.0.0: OpenDocument, RTF, XLS, MBOX, DXF,
legendas, as variantes do OOXML e as assinaturas ICP-Brasil (`.p7s/.p7m`).

Cada função recebe um caminho (ou bytes) e devolve texto; quem decide o que
fazer com ele é `conversion.py`. Nenhuma abre a rede, nenhuma executa macro
ou script do documento, e o conteúdo lido é sempre dado, nunca instrução.
Falha de leitura vira `LightFormatError` (a conversão a registra no arquivo,
sem conteúdo do documento na mensagem).
"""

from __future__ import annotations

import base64
import email
import io
import mailbox
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from email import policy
from pathlib import Path

from struct import error as struct_error

from .file_types import looks_binary
from .html_text import STRUCK_MARK, html_to_text, looks_like_html, mark_struck
from .text_decoding import decode_bytes, decode_markup

# Tetos do que se lê de dentro de um ZIP (OpenDocument, OOXML, o conteúdo de um
# `.p7m`): um pacote malicioso (bomba de descompressão, milhões de membros, um
# `content.xml` que vira gigabytes de árvore) não pode estourar a memória.
# Valem para todo leitor de ZIP deste módulo.
_MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024  # um membro qualquer
_MAX_XML_BYTES = 32 * 1024 * 1024  # um XML que vira árvore (content.xml): a árvore é ~10x isso
_MAX_ZIP_TOTAL_BYTES = 256 * 1024 * 1024  # tudo que o pacote descomprime
_MAX_ZIP_MEMBERS = 10_000
_MAX_COMPRESSION_RATIO = 1_000  # só olhado em membro grande: texto repetido chega a 100x
_RATIO_MIN_BYTES = 1024 * 1024
# Teto do texto extraído de um OpenDocument (caracteres) e da repetição de
# espaços (`text:s`) que um único elemento pede.
_MAX_TEXT_CHARS = 50_000_000
_MAX_REPEATED_SPACES = 1_000
# Trabalho, não só texto: nós visitados e profundidade de aninhamento. Um
# `content.xml` de 32 MB cheio de elementos vazios ou de tabelas dentro de
# tabelas não emite texto, mas custa tempo e pilha.
_MAX_ODF_NODES = 5_000_000
_MAX_ODF_DEPTH = 32


def _check_package(archive: zipfile.ZipFile) -> None:
    """Recusa, pelo que o diretório do ZIP declara e sem ler nada, o pacote
    com membros demais ou grande demais. O diretório pode mentir; por isso
    toda leitura de membro também é limitada (`_read_member`)."""
    infos = archive.infolist()
    if len(infos) > _MAX_ZIP_MEMBERS:
        raise LightFormatError("pacote com membros demais")
    if sum(info.file_size for info in infos) > _MAX_ZIP_TOTAL_BYTES:
        raise LightFormatError("pacote grande demais depois de descompactado")


def _read_member(archive: zipfile.ZipFile, name: str, limit: int | None = None) -> bytes:
    """Lê um membro sem nunca passar de `limit` bytes: confere o tamanho e a
    razão de compressão declarados e, como o declarado pode mentir, lê no
    máximo `limit + 1`."""
    limit = _MAX_ZIP_MEMBER_BYTES if limit is None else limit
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise LightFormatError("membro do pacote grande demais")
    if (
        info.file_size >= _RATIO_MIN_BYTES
        and info.file_size > max(info.compress_size, 1) * _MAX_COMPRESSION_RATIO
    ):
        raise LightFormatError("membro do pacote com compressão suspeita")
    with archive.open(info) as member:
        data = member.read(limit + 1)
    if len(data) > limit:
        raise LightFormatError("membro do pacote grande demais")
    return data
# Separador das páginas no texto intermediário de uma caixa `.mbox`. O
# form feed não aparece em e-mail de verdade; é tirado do corpo, por garantia.
MBOX_PAGE_SEPARATOR = "\n\x0c\n"


class LightFormatError(Exception):
    """Falha ao ler um formato leve. A mensagem não traz conteúdo do documento."""


# --- variantes do OOXML ----------------------------------------------------

_WORD_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_PRESENTATION_MAIN = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
# Tipos do documento principal que `python-docx` e `python-pptx` recusam,
# trocados pelo tipo comum: o conteúdo é o mesmo (macro e modelo só mudam o
# tipo declarado), e a macro nunca é lida.
_OOXML_MAIN_TYPES = {
    "docx": {
        "application/vnd.ms-word.document.macroEnabled.main+xml": _WORD_MAIN,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml": _WORD_MAIN,
        "application/vnd.ms-word.template.macroEnabledTemplate.main+xml": _WORD_MAIN,
    },
    "pptx": {
        "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml": _PRESENTATION_MAIN,
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml": _PRESENTATION_MAIN,
        "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml": _PRESENTATION_MAIN,
        "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml": _PRESENTATION_MAIN,
        "application/vnd.ms-powerpoint.template.macroEnabled.main+xml": _PRESENTATION_MAIN,
    },
}


def _with_plain_main_type(path: Path, kind: str) -> io.BytesIO:
    """O pacote OOXML em memória, com o tipo do documento principal trocado
    pelo comum. Os demais membros passam intactos."""
    replacements = _OOXML_MAIN_TYPES[kind]
    output = io.BytesIO()
    try:
        source_zip = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise LightFormatError("pacote OOXML ilegível ou corrompido") from exc
    total = 0
    with source_zip as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        _check_package(source)
        for info in source.infolist():
            data = _read_member(source, info.filename)
            total += len(data)
            if total > _MAX_ZIP_TOTAL_BYTES:
                raise LightFormatError("pacote grande demais depois de descompactado")
            if info.filename == "[Content_Types].xml":
                text = data.decode("utf-8", errors="replace")
                for old, new in replacements.items():
                    text = text.replace(old, new)
                data = text.encode("utf-8")
            target.writestr(info.filename, data)
    output.seek(0)
    return output


def open_docx(path: Path):
    """`docx.Document` de um `.docx` ou de uma variante (`.docm .dotx .dotm`)."""
    from docx import Document

    if path.suffix.lower() == ".docx":
        return Document(path)
    return Document(_with_plain_main_type(path, "docx"))


def open_pptx(path: Path):
    """`pptx.Presentation` de um `.pptx` ou de uma variante
    (`.pptm .ppsx .potx .potm`)."""
    from pptx import Presentation

    if path.suffix.lower() == ".pptx":
        return Presentation(path)
    return Presentation(_with_plain_main_type(path, "pptx"))


# --- OpenDocument ------------------------------------------------------------

_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


_ODF_SKIPPED = {
    _q("office", "forms"), _q("office", "scripts"), _q("office", "font-face-decls"),
    _q("office", "automatic-styles"), _q("office", "styles"), _q("office", "master-styles"),
    _q("office", "settings"), _q("office", "meta"),
    # Texto apagado com a revisão ligada: ainda está no arquivo, mas não é
    # mais o texto do documento.
    _q("text", "tracked-changes"),
}


class _OdfStyles(set):
    """Os estilos que riscam o texto, e a conta de caracteres já extraídos
    (o teto do texto de um OpenDocument)."""

    chars = 0
    visits = 0
    depth = 0


def _odf_enter(context) -> None:
    """Conta uma visita e um nível de aninhamento (quem chama desce com
    `context.depth -= 1` ao sair)."""
    context.visits += 1
    if context.visits > _MAX_ODF_NODES:
        raise LightFormatError("OpenDocument com elementos demais")
    context.depth += 1
    if context.depth > _MAX_ODF_DEPTH:
        raise LightFormatError("OpenDocument aninhado demais")


def _odf_struck_styles(root) -> set[str]:
    """Nomes dos estilos que riscam o texto (`text-line-through-style`)."""
    names: set[str] = _OdfStyles()
    for style in root.iter(_q("style", "style")):
        properties = style.find(_q("style", "text-properties"))
        if properties is None:
            continue
        line_through = properties.get(_q("style", "text-line-through-style"))
        if line_through not in (None, "none"):
            name = style.get(_q("style", "name"))
            if name:
                names.add(name)
    return names


def _odf_inline(element, struck_styles: set[str], struck: bool, segments: list, notes: list) -> None:
    """Texto corrido de um parágrafo, com o tachado marcado. Notas de rodapé
    saem do fluxo e entram depois do parágrafo, em `notes`."""

    def emit(text: str) -> None:
        struck_styles.chars += len(text)
        if struck_styles.chars > _MAX_TEXT_CHARS:
            raise LightFormatError("texto do OpenDocument grande demais")
        segments.append((text, struck))

    _odf_enter(struck_styles)
    try:
        _odf_inline_children(element, struck_styles, struck, segments, notes, emit)
    finally:
        struck_styles.depth -= 1


def _odf_inline_children(element, struck_styles, struck, segments, notes, emit) -> None:
    if element.text:
        emit(element.text)
    for child in element:
        struck_styles.visits += 1
        if struck_styles.visits > _MAX_ODF_NODES:
            raise LightFormatError("OpenDocument com elementos demais")
        tag = child.tag
        if tag == _q("text", "s"):
            try:
                count = int(child.get(_q("text", "c"), "1") or 1)
            except ValueError:
                count = 1
            # `text:c` é a repetição de espaços; sem teto, um elemento de 30
            # bytes pede gigabytes.
            emit(" " * min(max(count, 1), _MAX_REPEATED_SPACES))
        elif tag == _q("text", "tab"):
            emit("\t")
        elif tag == _q("text", "line-break"):
            emit("\n")
        elif tag == _q("text", "note"):
            body = child.find(_q("text", "note-body"))
            if body is not None:
                notes.extend(_odf_blocks(body, struck_styles))
        elif tag in (_q("text", "span"), _q("text", "a")):
            style = child.get(_q("text", "style-name"))
            _odf_inline(child, struck_styles, struck or style in struck_styles, segments, notes)
        elif tag in (_q("office", "annotation"), _q("text", "tracked-changes")):
            pass
        else:
            _odf_inline(child, struck_styles, struck, segments, notes)
        if child.tail:
            emit(child.tail)


def _odf_paragraph(element, struck_styles: set[str]) -> list[str]:
    segments: list = []
    notes: list[str] = []
    paragraph_style = element.get(_q("text", "style-name"))
    _odf_inline(element, struck_styles, paragraph_style in struck_styles, segments, notes)
    text = mark_struck(segments)
    lines = [text] if text.strip() else []
    return lines + notes


_ODF_ROW_GROUPS = (
    _q("table", "table-header-rows"), _q("table", "table-rows"), _q("table", "table-row-group"),
)


def _odf_rows(container, context):
    """As linhas da própria tabela: filhas diretas e as dos grupos
    (`table-header-rows`, `table-rows`, `table-row-group`). Nunca as de uma
    tabela aninhada: essa é lida uma vez só, dentro da célula que a contém."""
    for child in container:
        context.visits += 1
        if context.visits > _MAX_ODF_NODES:
            raise LightFormatError("OpenDocument com elementos demais")
        if child.tag == _q("table", "table-row"):
            yield child
        elif child.tag in _ODF_ROW_GROUPS:
            _odf_enter(context)
            try:
                yield from _odf_rows(child, context)
            finally:
                context.depth -= 1


def _odf_table(table, struck_styles: set[str]) -> list[str]:
    rows: list[str] = []
    for row in _odf_rows(table, struck_styles):
        cells = []
        for cell in row:
            if cell.tag == _q("table", "table-cell"):
                cells.append("\n".join(_odf_blocks(cell, struck_styles)))
            elif cell.tag == _q("table", "covered-table-cell"):
                continue
        # Planilha com milhares de linhas vazias repetidas no fim.
        if any(text.strip() for text in cells):
            rows.append("\t".join(cells))
    return rows


def _odf_blocks(element, struck_styles: set[str]) -> list[str]:
    _odf_enter(struck_styles)
    try:
        return _odf_blocks_of(element, struck_styles)
    finally:
        struck_styles.depth -= 1


def _odf_blocks_of(element, struck_styles: set[str]) -> list[str]:
    lines: list[str] = []
    for child in element:
        struck_styles.visits += 1
        if struck_styles.visits > _MAX_ODF_NODES:
            raise LightFormatError("OpenDocument com elementos demais")
        tag = child.tag
        if tag in _ODF_SKIPPED:
            continue
        if tag in (_q("text", "p"), _q("text", "h")):
            lines.extend(_odf_paragraph(child, struck_styles))
        elif tag == _q("table", "table"):
            lines.extend(_odf_table(child, struck_styles))
        elif tag == _q("draw", "page"):
            lines.extend(_odf_blocks(child, struck_styles))
        else:
            lines.extend(_odf_blocks(child, struck_styles))
    return lines


def _odf_parse(data: bytes):
    from lxml import etree

    # Sem entidades externas, sem rede: o conteúdo é de terceiros.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise LightFormatError("XML do OpenDocument ilegível") from exc


def extract_text_opendocument(path: Path) -> str:
    """`.odt .ods .odp .odg` (ZIP com `content.xml`) e os planos `.fodt
    .fods .fodp` (um XML só)."""
    if path.suffix.lower().startswith(".f"):
        if path.stat().st_size > _MAX_XML_BYTES:
            raise LightFormatError("XML do OpenDocument grande demais")
        root = _odf_parse(path.read_bytes())
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                _check_package(archive)
                data = _read_member(archive, "content.xml", _MAX_XML_BYTES)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise LightFormatError("OpenDocument ilegível ou corrompido") from exc
        root = _odf_parse(data)
    struck_styles = _odf_struck_styles(root)
    return "\n".join(_odf_blocks(root, struck_styles))


def odf_has_table(path: Path) -> bool:
    """Planilha (`.ods`, `.fods`): conta como tabela, como o `.xlsx`."""
    return path.suffix.lower() in (".ods", ".fods")


# --- RTF -----------------------------------------------------------------------


def extract_text_rtf(path: Path) -> str:
    from striprtf.striprtf import rtf_to_text

    raw = path.read_bytes().decode("latin-1")
    return rtf_to_text(raw, encoding="cp1252", errors="ignore")


# --- XLS (binário antigo do Excel) ---------------------------------------------


def _xls_cell_text(book, cell) -> str:
    import xlrd

    kind = cell.ctype
    value = cell.value
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if kind == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(value, book.datemode).isoformat(sep=" ")
        except (xlrd.xldate.XLDateError, OverflowError, ValueError):
            return str(value)
    if kind == xlrd.XL_CELL_NUMBER and float(value).is_integer():
        return str(int(value))
    if kind == xlrd.XL_CELL_BOOLEAN:
        return "VERDADEIRO" if value else "FALSO"
    if kind == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(value, "#ERRO")
    return str(value)


def _xls_struck(book, cell) -> bool:
    try:
        font = book.font_list[book.xf_list[cell.xf_index].font_index]
    except (AttributeError, IndexError):
        return False
    return bool(getattr(font, "struck_out", 0))


def _text_of_disguised_xls(data: bytes) -> str | None:
    """Muita planilha `.xls` é HTML ou texto separado por tabulação com o
    nome de Excel (exportação de sistema). Devolve o texto, ou `None` se os
    bytes são mesmo binários."""
    text, _ = decode_markup(data)
    if looks_like_html(text):
        return html_to_text(text)
    if looks_binary(data[:8192]):
        return None
    return decode_bytes(data)[0]


def extract_text_xls(path: Path, data: bytes | None = None) -> str:
    import xlrd

    raw = path.read_bytes() if data is None else data
    try:
        try:
            # `formatting_info` traz as fontes, de onde vem o tachado.
            book = xlrd.open_workbook(file_contents=raw, formatting_info=True)
        except NotImplementedError:
            book = xlrd.open_workbook(file_contents=raw)
    except (xlrd.XLRDError, xlrd.compdoc.CompDocError, zipfile.BadZipFile, OSError, IndexError, struct_error) as exc:
        text = _text_of_disguised_xls(raw)
        if text is None:
            raise LightFormatError("planilha .xls ilegível ou corrompida") from exc
        return text
    try:
        rows: list[str] = []
        for sheet in book.sheets():
            for index in range(sheet.nrows):
                cells = []
                for cell in sheet.row(index):
                    text = _xls_cell_text(book, cell)
                    if text.strip() and _xls_struck(book, cell):
                        text = f"{STRUCK_MARK}{text.strip()}{STRUCK_MARK}"
                    cells.append(text)
                rows.append("\t".join(cells))
        return "\n".join(rows)
    finally:
        book.release_resources()


# --- MBOX ----------------------------------------------------------------------


def message_part_text(part) -> str:
    """Text of one MIME part. Decodes the bytes itself instead of calling
    `get_content()`, which raises `LookupError` on a charset label Python
    does not know — a common sight in old mail — and would fail the file."""
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset()
    if part.get_content_type() == "text/html":
        text, _ = decode_markup(payload, charset)
        return html_to_text(text)
    return decode_bytes(payload, charset)[0]


def _mbox_message_text(message) -> str:
    parts = [
        f"From: {message.get('From', '')}",
        f"Date: {message.get('Date', '')}",
        f"Subject: {message.get('Subject', '')}",
    ]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        parts.append(message_part_text(body))
    return "\n\n".join(parts).replace("\x0c", " ")


def extract_text_mbox(path: Path) -> str:
    """Uma página por mensagem, separadas por `MBOX_PAGE_SEPARATOR`."""
    box = mailbox.mbox(
        str(path), create=False,
        factory=lambda handle: email.message_from_binary_file(handle, policy=policy.default),
    )
    try:
        pages = [_mbox_message_text(message) for message in box]
    except (mailbox.Error, OSError) as exc:
        raise LightFormatError("caixa .mbox ilegível") from exc
    finally:
        box.close()
    return MBOX_PAGE_SEPARATOR.join(pages)


# --- DXF -----------------------------------------------------------------------


def _dxf_entity_lines(entity) -> list[str]:
    kind = entity.dxftype()
    lines: list[str] = []
    try:
        if kind == "TEXT":
            lines.append(entity.dxf.text)
        elif kind == "MTEXT":
            lines.append(entity.plain_text())
        elif kind in ("ATTRIB", "ATTDEF"):
            tag, text = entity.dxf.get("tag", ""), entity.dxf.get("text", "")
            if text:
                lines.append(f"{tag}: {text}" if tag else text)
        elif kind == "INSERT":
            for attribute in entity.attribs:
                lines.extend(_dxf_entity_lines(attribute))
        elif kind == "DIMENSION":
            override = entity.dxf.get("text", "")
            if override and override != "<>":
                lines.append(override)
            else:
                measurement = entity.dxf.get("actual_measurement", None)
                if measurement:
                    lines.append(f"{measurement:g}")
        elif kind == "MULTILEADER":
            lines.append(entity.get_mtext_content())
    except Exception:
        # Uma entidade estranha não pode custar o desenho inteiro.
        return []
    return [line.strip() for line in lines if line and line.strip()]


def extract_text_dxf(path: Path) -> str:
    import ezdxf
    from ezdxf import recover

    try:
        document = ezdxf.readfile(str(path))
    except ezdxf.DXFError:
        try:
            document, _auditor = recover.readfile(str(path))
        except Exception as exc:
            raise LightFormatError("desenho DXF ilegível ou corrompido") from exc
    except OSError as exc:
        raise LightFormatError("desenho DXF ilegível") from exc

    containers = [document.modelspace()]
    containers += [layout for layout in document.layouts if not layout.is_modelspace]
    # Carimbo e legenda ficam em blocos; os anônimos (`*D1`…) repetem as
    # cotas e os hachuras, e ficam de fora.
    containers += [block for block in document.blocks if not block.name.startswith("*")]

    seen: set[str] = set()
    ordered: list[str] = []
    for container in containers:
        for entity in container:
            for line in _dxf_entity_lines(entity):
                if line not in seen:
                    seen.add(line)
                    ordered.append(line)
    return "\n".join(ordered)


# --- legendas ------------------------------------------------------------------

_SUBTITLE_TIME = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*")
_SUBTITLE_TAGS = re.compile(r"<[^>]*>|\{\\[^}]*\}")


def extract_text_subtitles(path: Path) -> str:
    """`.srt` e `.vtt`: só as falas. Número da fala, marca de tempo,
    cabeçalho e blocos de nota somem; fala repetida em sequência (legenda
    automática que rola) vale uma vez."""
    text = decode_bytes(path.read_bytes())[0]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    skip_block = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            skip_block = False
            continue
        if skip_block:
            continue
        if index == 0 and stripped.lstrip("﻿").startswith("WEBVTT"):
            skip_block = True
            continue
        if stripped.split(" ", 1)[0] in ("NOTE", "STYLE", "REGION") and not _SUBTITLE_TIME.match(stripped):
            skip_block = True
            continue
        if _SUBTITLE_TIME.match(stripped):
            continue
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if _SUBTITLE_TIME.match(following):
            continue  # número (SRT) ou identificador (VTT) da fala
        cleaned = _SUBTITLE_TAGS.sub("", stripped).strip()
        if cleaned and (not output or output[-1] != cleaned):
            output.append(cleaned)
    return "\n".join(output)


# --- assinaturas ICP-Brasil ------------------------------------------------------

# OIDs do ICP-Brasil (DOC-ICP-04) em `otherName` da SAN do certificado:
# 3.1 pessoa física (nascimento 8 + CPF 11 + NIS + RG + órgão), 3.3 CNPJ da
# pessoa jurídica, 3.4 responsável (nascimento 8 + CPF 11 + ...).
_OID_PERSON = "2.16.76.1.3.1"
_OID_COMPANY = "2.16.76.1.3.3"
_OID_RESPONSIBLE = "2.16.76.1.3.4"
_CN_DOCUMENT = re.compile(r":\s*(\d{11}|\d{14})\s*$")


@dataclass
class SignatureInfo:
    signer: str
    holder_document: str
    signed_at: str


@dataclass
class SignedFile:
    """O que um `.p7m`/`.p7s` guarda: o conteúdo envelopado (ausente numa
    assinatura destacada) e quem assinou."""
    content: bytes | None
    signatures: list[SignatureInfo]


def _format_cpf(digits: str) -> str:
    return f"CPF {digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _format_cnpj(digits: str) -> str:
    return f"CNPJ {digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _der_value(der: bytes) -> bytes:
    """O texto de dentro de um valor DER, sem a marca explícita `[0]` e sem o
    byte do tipo e o do tamanho. Os campos ICP-Brasil são texto em OCTET
    STRING, PrintableString ou UTF8String; o byte do tamanho (`0x33`) também
    é um dígito ASCII, e por isso precisa sair antes de procurar os números."""
    for _ in range(3):
        if len(der) < 2 or der[0] not in (0xA0, 0x04, 0x13, 0x0C, 0x16):
            break
        first = der[1]
        der = der[2 if first < 0x80 else 2 + (first & 0x7F):]
    return der


def _holder_document(certificate) -> tuple[str, str]:
    """`(nome do titular, documento do titular)` do certificado. O documento
    vem dos campos ICP-Brasil do certificado e, na falta deles, do final do
    CN (`NOME:12345678901`). Vazio quando o certificado não traz nenhum."""
    common_name = certificate.subject.native.get("common_name") or ""
    if isinstance(common_name, list):
        common_name = common_name[0]
    common_name = str(common_name).strip()

    found: dict[str, bytes] = {}
    try:
        names = certificate.subject_alt_name_value
    except Exception:
        names = None
    for name in names or ():
        if name.name != "other_name":
            continue
        other = name.chosen
        oid = other["type_id"].dotted
        if oid in (_OID_PERSON, _OID_COMPANY, _OID_RESPONSIBLE):
            found[oid] = _der_value(other["value"].dump())

    document = ""
    company = re.search(rb"\d{14}", found.get(_OID_COMPANY, b""))
    person = re.search(rb"\d{19,}", found.get(_OID_PERSON, b""))
    responsible = re.search(rb"\d{19,}", found.get(_OID_RESPONSIBLE, b""))
    if company:
        document = _format_cnpj(company.group().decode())
    elif person:
        document = _format_cpf(person.group().decode()[8:19])
    elif responsible:
        document = _format_cpf(responsible.group().decode()[8:19])

    from_name = _CN_DOCUMENT.search(common_name)
    if from_name:
        common_name = common_name[: from_name.start()].strip()
        if not document:
            digits = from_name.group(1)
            document = _format_cpf(digits) if len(digits) == 11 else _format_cnpj(digits)
    return common_name, document


def _signing_time(signer_info) -> str:
    attributes = signer_info["signed_attrs"]
    if attributes.native is None:
        return ""
    for attribute in attributes:
        if attribute["type"].native == "signing_time":
            value = attribute["values"][0].native
            if isinstance(value, datetime):
                local = value.astimezone() if value.tzinfo else value
                return local.strftime("%Y-%m-%d %H:%M")
    return ""


def _certificate_matches(certificate, sid) -> bool:
    if sid.name == "issuer_and_serial_number":
        chosen = sid.chosen
        return (
            certificate.serial_number == chosen["serial_number"].native
            and certificate.issuer == chosen["issuer"]
        )
    if sid.name == "subject_key_identifier":
        return certificate.key_identifier == sid.chosen.native
    return False


def _decode_container(data: bytes) -> bytes:
    """DER direto, PEM (`-----BEGIN PKCS7-----`) ou DER em base64 puro."""
    from asn1crypto import pem

    stripped = data.lstrip()
    if pem.detect(stripped):
        return pem.unarmor(stripped)[2]
    if stripped[:1] != b"\x30":  # DER de PKCS#7 começa por SEQUENCE
        try:
            return base64.b64decode(b"".join(stripped.split()), validate=True)
        except ValueError:
            pass
    return data


def parse_signature_container(data: bytes) -> SignedFile:
    """Lê um PKCS#7/CMS SignedData: o conteúdo envelopado (quando há) e os
    signatários. Não valida nada: nem a assinatura, nem a cadeia, nem a
    revogação. Isso exigiria a rede (LCR, OCSP, repositório de raízes), e o
    programa nunca a usa para ler um documento."""
    from asn1crypto import cms

    try:
        info = cms.ContentInfo.load(_decode_container(data))
        if info["content_type"].native != "signed_data":
            raise LightFormatError("o arquivo não é uma assinatura (SignedData)")
        signed = info["content"]
        encapsulated = signed["encap_content_info"]
        content = encapsulated["content"].native if encapsulated["content"].contents else None
        certificates = []
        if signed["certificates"].native:
            certificates = [choice.chosen for choice in signed["certificates"] if choice.name == "certificate"]
        signatures: list[SignatureInfo] = []
        for signer_info in signed["signer_infos"]:
            certificate = next(
                (cert for cert in certificates if _certificate_matches(cert, signer_info["sid"])), None
            )
            name, document = _holder_document(certificate) if certificate is not None else ("", "")
            signatures.append(SignatureInfo(name, document, _signing_time(signer_info)))
    except LightFormatError:
        raise
    except Exception as exc:
        raise LightFormatError("assinatura ilegível ou corrompida") from exc
    return SignedFile(content if content else None, signatures)


def signed_content_of(data: bytes, depth: int = 4) -> SignedFile:
    """Como `parse_signature_container`, mas desce enquanto o conteúdo for
    outra assinatura (`.p7m` assinado duas vezes), somando os signatários."""
    outer = parse_signature_container(data)
    signatures = list(outer.signatures)
    content = outer.content
    while content is not None and depth > 0:
        try:
            inner = parse_signature_container(content)
        except LightFormatError:
            break
        if inner.content is None:
            break
        signatures += inner.signatures
        content = inner.content
        depth -= 1
    return SignedFile(content, signatures)


# --- tipo real do conteúdo envelopado -----------------------------------------------

_IMAGE_MAGIC = (
    b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"II*\x00", b"MM\x00*", b"GIF87a", b"GIF89a",
    b"\xff\x4f\xff\x51", b"\x00\x00\x00\x0cjP  ", b"RIFF",
)


def sniff_content_type(data: bytes) -> str:
    """Tipo real de um conteúdo, pela assinatura de bytes: `pdf`, `docx`,
    `xlsx`, `pptx`, `odf`, `epub`, `image`, `rtf`, `xls`, `text` ou
    `binary`. Um ZIP que não é um desses é `binary`: compactado nunca é
    aberto."""
    head = data[:8192]
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                _check_package(archive)
                names = set(archive.namelist())
                if "mimetype" in names:
                    # No máximo 100 bytes de um membro que pode declarar gigabytes.
                    info = archive.getinfo("mimetype")
                    if info.file_size > 1024:
                        raise LightFormatError("membro mimetype grande demais")
                    with archive.open(info) as member:
                        mimetype = member.read(100).decode("ascii", errors="ignore")
                    if mimetype.startswith("application/vnd.oasis.opendocument"):
                        return "odf"
                    if mimetype.startswith("application/epub+zip"):
                        return "epub"
                if "[Content_Types].xml" in names:
                    if any(name.startswith("word/") for name in names):
                        return "docx"
                    if any(name.startswith("xl/") for name in names):
                        return "xlsx"
                    if any(name.startswith("ppt/") for name in names):
                        return "pptx"
        except zipfile.BadZipFile:
            pass
        return "binary"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    if (
        head.startswith(_IMAGE_MAGIC)
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
        or (head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"))
    ):
        return "image"
    return "binary" if looks_binary(head) else "text"


def convert_to_pdf_bytes(path: Path) -> bytes:
    """Um formato paginado (`.xps .oxps .epub .mobi .fb2 .svg .cbz`) como PDF,
    pelo PyMuPDF. As páginas são as do documento (um `.svg` é uma só)."""
    import fitz

    try:
        document = fitz.open(path)
    except Exception as exc:
        raise LightFormatError(f"documento ilegível ou corrompido: {exc}") from exc
    try:
        if document.page_count == 0:
            raise LightFormatError("documento sem páginas")
        return document.convert_to_pdf()
    except LightFormatError:
        raise
    except Exception as exc:
        raise LightFormatError(f"falha ao converter para PDF: {exc}") from exc
    finally:
        document.close()

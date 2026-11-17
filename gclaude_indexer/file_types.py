# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Supported file categories and their mapping to extensions.

Used by the configuration ("Included extensions" field, section 6) and by
the scan (section 5, step 1) to decide what enters the inventory.
"""

from __future__ import annotations

from pathlib import Path

from .text_decoding import _BOMS

EXTENSION_CATEGORIES: dict[str, set[str]] = {
    "pdf": {".pdf"},
    # 2.0.0: as variantes com macro e modelo abrem pelas mesmas bibliotecas;
    # a macro nunca é executada (só o texto é lido). `.xls` é o formato
    # binário antigo do Excel, lido por `xlrd`.
    "docx": {".docx", ".docm", ".dotx", ".dotm"},
    "xlsx": {".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"},
    "pptx": {".pptx", ".pptm", ".ppsx", ".potx", ".potm"},
    "opendocument": {".odt", ".ods", ".odp", ".odg", ".fodt", ".fods", ".fodp"},
    "rtf": {".rtf"},
    # Têm páginas de verdade: o PyMuPDF os converte para um PDF intermediário
    # e o resto do caminho (texto nativo, OCR de página sem texto) é o do PDF.
    "paginados": {".xps", ".oxps", ".epub", ".mobi", ".fb2", ".svg", ".cbz"},
    "imagens": {
        ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp",
        ".jp2", ".j2k", ".jpx", ".jfif", ".jpe", ".heic", ".heif",
    },
    # Every text-like format goes through `text_decoding`, which works out
    # the encoding. "web_dados" also goes through `html_text`: HTML and its
    # derivatives (XHTML, server-side includes, MHTML saved by a browser, an
    # `.xml` whose root is `<html>`) become readable text with strikethrough
    # kept as `~~`; other XML and JSON stay literal — their tags are field
    # names that carry meaning.
    "text": {".txt", ".md", ".log", ".csv"},
    "legendas": {".srt", ".vtt"},
    "web_dados": {".html", ".htm", ".xhtml", ".xht", ".shtml", ".mht", ".mhtml", ".xml", ".json"},
    "email": {".eml", ".msg"},
    # Cada mensagem da caixa é uma página, como o `.eml` é um documento.
    "mbox": {".mbox"},
    "cad": {".dxf"},
    # ICP-Brasil: o conteúdo envelopado é indexado pelo tipo real e o
    # signatário vai para `file_signature`.
    "assinados": {".p7s", ".p7m"},
    # Opt-in: "all" não inclui. A chave é dado (como "imagens"), o rótulo é
    # traduzido no formulário. Ainda sem transcritor, o arquivo entra no
    # inventário mas não produz texto.
    "midia": {
        ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma",
        ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".3gp",
    },
}

# Note: category keys above ("imagens", "web_dados") are data values shared
# with the i18n keys ("new_project.category.*") and with form/template
# markup outside this module's scope — they are intentionally left
# untranslated here so the UI keeps resolving them. ("text" and CATEGORY_ALL
# below were translated in Task 9d, Phase 14 — narrower exceptions the
# coordinator asked for explicitly, not a reversal of this module's general
# policy toward the rest of the set.)

# Special category (explicit user request): "all" scans any extension that
# is NOT in the blocklist below — i.e. it is not restricted to
# `EXTENSION_CATEGORIES`. It never appears among `EXTENSION_CATEGORIES`
# values because it isn't a fixed set of extensions: it's a rule ("everything
# except binaries/executables"), applied in `scanning.py`.
CATEGORY_ALL = "all"

# Always excluded, even with "all" selected — executable or binary formats
# that never make sense to index as a document (never text/image in a
# collection), and `.ini` configuration files (Windows and Google Drive
# write one into every folder; none is ever a document).
ALWAYS_BLOCKED_EXTENSIONS: set[str] = {
    ".exe", ".dll", ".msi", ".bat", ".cmd", ".com", ".scr", ".sys", ".bin",
    ".so", ".dylib", ".iso", ".vhd", ".vhdx", ".drv", ".ocx", ".cpl", ".vbs",
    ".js", ".jar", ".apk", ".deb", ".rpm", ".ps1", ".sh", ".app", ".lnk",
    ".ini",
    # Imagens de disco, bancos de dados, fontes, CAD binário: nunca são
    # documento de um acervo e o conteúdo não é texto.
    ".img", ".dmg", ".vmdk", ".qcow2",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".dbf",
    ".ttf", ".otf", ".woff", ".woff2",
    ".dwg",
    ".pyc", ".pyd", ".class", ".o", ".obj", ".lib", ".a", ".wasm", ".msix", ".appx",
}

# Compactados nunca são abertos (decisão do usuário): ficam no inventário
# como ignorados, com o motivo `archive`.
ARCHIVE_EXTENSIONS: frozenset[str] = frozenset({
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst",
    ".cab", ".lz", ".lzma", ".arj", ".z",
})

# Atalhos do Google Drive para a nuvem: o arquivo local é só um link.
GOOGLE_DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".gdoc", ".gsheet", ".gslides", ".gdraw", ".gform", ".gmap", ".gsite", ".gjam",
})

# Chaves, certificados e cofres de senha: nunca entram no índice.
SECRET_EXTENSIONS: frozenset[str] = frozenset({
    ".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".jks", ".keystore", ".env",
})
_SECRET_NAME_PREFIXES = ("id_rsa", "id_ed25519")

# Só os primeiros bytes são lidos para decidir; o resto do arquivo (e todo o
# conteúdo de um segredo) fica de fora.
HEAD_BYTES = 8192
_SECRET_MARKER_BEGIN = b"-----BEGIN"
_SECRET_MARKER_END = b"PRIVATE KEY-----"
_BINARY_CONTROL_RATIO = 0.30

REASON_SYSTEM = "system"
REASON_GOOGLE_DOC = "google_doc"
REASON_ARCHIVE = "archive"
REASON_BLOCKED = "blocked_extension"
REASON_MEDIA = "media_not_selected"
REASON_SECRET = "secret"
REASON_BINARY = "binary"
REASON_NOT_SELECTED = "extension_not_selected"
# Gravado pela conversão (não pela varredura): um `.p7s` destacado não tem
# conteúdo próprio, a assinatura vai para o arquivo irmão.
REASON_SIGNATURE_DETACHED = "signature_detached"


# Categorias com páginas reais (o limite de caracteres por página do projeto
# vale para elas, e o documento pode continuar no arquivo seguinte).
PAGED_CATEGORIES: tuple[str, ...] = ("pdf", "imagens", "paginados")


def valid_categories() -> set[str]:
    return set(EXTENSION_CATEGORIES) | {CATEGORY_ALL}


def extensions_for_categories(categories: list[str]) -> set[str]:
    """Converts a list of configured categories (e.g. `["pdf", "imagens"]`)
    into the set of dotted extensions they cover (e.g. `{".pdf", ".jpg", ...}`).
    An unknown category is ignored here — it is validated earlier, in
    `config.py`. Does not cover `CATEGORY_ALL`, which is not a fixed set —
    see `is_extension_allowed()`.
    """
    extensions: set[str] = set()
    for category in categories:
        extensions |= EXTENSION_CATEGORIES.get(category, set())
    return extensions


def is_extension_allowed(extension_with_dot: str, categories: list[str]) -> bool:
    """Decides whether an extension enters the scan, given what the project
    configured in "Included extensions". With `CATEGORY_ALL` selected,
    accepts any extension not in `ALWAYS_BLOCKED_EXTENSIONS` (executable/
    binary) and not audio/video; otherwise, only the extensions of the
    selected categories. Audio and video enter only through `midia`: "all"
    never covers them (it would index a film as an empty page)."""
    extension_with_dot = extension_with_dot.lower()
    if extension_with_dot in extensions_for_categories(categories):
        return True
    if CATEGORY_ALL in categories:
        return (
            extension_with_dot not in ALWAYS_BLOCKED_EXTENSIONS
            and extension_with_dot not in EXTENSION_CATEGORIES["midia"]
        )
    return False


def normalize_categories(categories: list[str]) -> list[str]:
    """`all` already covers every specific category except `midia`, so the
    list kept is `["all"]` (plus `midia` if it was chosen). The form keeps
    the two exclusive in JS only; this is the guarantee on the server."""
    if CATEGORY_ALL not in categories:
        return list(categories)
    result = [CATEGORY_ALL]
    if "midia" in categories:
        result.append("midia")
    return result


def looks_binary(head: bytes) -> bool:
    """Unknown extension, first bytes only. A BOM of UTF-16/32 means text
    (those encodings are full of NUL bytes); a NUL without BOM, or more
    than 30% of control characters, means binary."""
    if not head:
        return False
    if any(head.startswith(bom) for bom, _ in _BOMS):
        return False
    if b"\x00" in head:
        return True
    controls = sum(1 for byte in head if byte < 32 and byte not in (9, 10, 12, 13, 27))
    return controls / len(head) > _BINARY_CONTROL_RATIO


def _has_private_key_marker(head: bytes) -> bool:
    start = head.find(_SECRET_MARKER_BEGIN)
    return start != -1 and _SECRET_MARKER_END in head[start:]


def _extension(name: str) -> str:
    """Same extension the scan stores (`Path.suffix`, lower case), except
    that a bare dotfile such as `.env` counts as being its own extension."""
    lower = name.lower()
    suffix = Path(lower).suffix
    if not suffix and lower.startswith(".") and lower.count(".") == 1:
        return lower
    return suffix


def name_decision(name: str, categories: list[str] | None = None) -> str | None:
    """The part of `index_decision` that needs only the file name, in the
    same order. `None` means "not decided by the name"."""
    lower = name.lower()
    extension = _extension(lower)
    # Local import: scanning imports this module.
    from .scanning import is_system_file
    if is_system_file(Path(name)):
        return REASON_SYSTEM
    if extension in GOOGLE_DOC_EXTENSIONS:
        return REASON_GOOGLE_DOC
    if extension in ARCHIVE_EXTENSIONS:
        return REASON_ARCHIVE
    if extension in ALWAYS_BLOCKED_EXTENSIONS:
        return REASON_BLOCKED
    if extension in EXTENSION_CATEGORIES["midia"] and "midia" not in (categories or ()):
        return REASON_MEDIA
    if extension in SECRET_EXTENSIONS or lower.startswith(_SECRET_NAME_PREFIXES):
        return REASON_SECRET
    return None


def index_decision(
    name: str, head_bytes: bytes | None = None, categories: list[str] | None = None,
) -> str | None:
    """Why a file must not be indexed, or `None` if it may be.

    One rule for the scan, the update plan and the conversion. The order is
    the contract: system file, Google shortcut, archive, blocked extension,
    audio/video not selected, secret. Only then does the content count, and
    only the first `HEAD_BYTES`: a secret marker, or — for an extension with
    no category — binary content. `head_bytes=None` decides by name alone
    (nothing was read), so a video is never downloaded to be refused.
    """
    reason = name_decision(name, categories)
    if reason is not None:
        return reason
    extension = _extension(name)
    known = category_of_extension(extension) is not None
    if head_bytes is None:
        return None
    head = head_bytes[:HEAD_BYTES]
    if _has_private_key_marker(head):
        return REASON_SECRET
    if not known and looks_binary(head):
        return REASON_BINARY
    return None


def needs_head(name: str, categories: list[str] | None = None) -> bool:
    """Whether `index_decision` would need to read the start of the file:
    only when the name alone did not decide, and the file is a text-like
    candidate (unknown extension, or a plain text one that might hold a key)."""
    if name_decision(name, categories) is not None:
        return False
    category = category_of_extension(_extension(name))
    return category is None or category in ("text", "web_dados")


def is_whole_document_file(file_name: str) -> bool:
    """Whether a file always becomes exactly one page holding the whole
    document — everything except PDF, images and the paged formats, which
    have real pages and whose documents may continue into the next file. An extension with no
    category (the "all" rule) is read as one block of text, so it counts."""
    dot = file_name.rfind(".")
    category = category_of_extension(file_name[dot:]) if dot > 0 else None
    return category not in PAGED_CATEGORIES


def category_of_extension(extension_with_dot: str) -> str | None:
    """Name of the category (e.g. `"imagens"`) an extension belongs to, or
    `None` if it doesn't match any known category."""
    extension_with_dot = extension_with_dot.lower()
    for category, extensions in EXTENSION_CATEGORIES.items():
        if extension_with_dot in extensions:
            return category
    return None


# Grouping is only for display in the form (section 6): the flat alphabetical
# list of eight checkboxes said nothing about what each label covers or what
# is similar to what. Does not change any scan rule — `EXTENSION_CATEGORIES`
# remains the source of truth.
CATEGORY_FAMILIES: dict[str, tuple[str, ...]] = {
    "documentos": ("pdf", "docx", "xlsx", "pptx", "opendocument", "rtf", "paginados"),
    "imagens": ("imagens",),
    "text_data": ("text", "legendas", "web_dados"),
    "mensagens": ("email", "mbox"),
    "tecnicos": ("cad", "assinados"),
}


def categories_by_family() -> list[tuple[str, list[dict]]]:
    """Categories grouped for the form, each with the extensions it covers.
    `CATEGORY_ALL` is deliberately left out: it's a rule ("everything except
    binaries"), not a fixed set, and the template shows it separately."""
    grouped: list[tuple[str, list[dict]]] = []
    for family, categories in CATEGORY_FAMILIES.items():
        items = [
            {"categoria": category, "extensoes": sorted(EXTENSION_CATEGORIES[category])}
            for category in categories
            if category in EXTENSION_CATEGORIES
        ]
        if items:
            grouped.append((family, items))
    return grouped

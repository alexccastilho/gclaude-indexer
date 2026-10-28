# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Turning the bytes of any text file into text, whatever its encoding.

Every text-like format used to be read as UTF-8 with `errors="replace"`.
Brazilian collections are full of Windows-1252 — the whole of the Planalto
legislation site, for one, either declares `iso-8859-1` or declares nothing
— and every accent came out as "�", in the index and in the converted copy.

The order, from the most to the least trustworthy evidence:

1. a byte-order mark, which no other encoding can produce by accident;
2. what the file (or its container — an e-mail part, an MHTML part) says
   it is, provided the bytes really decode that way;
3. UTF-8, which almost never decodes text that is not UTF-8;
4. statistical detection (`charset_normalizer`), only when all of the
   above failed — it is the slow step, and it guesses;
5. Windows-1252, then Latin-1, which decodes any byte at all.

`decode_bytes` never raises. A file whose encoding cannot be told is still
read — at worst with a few wrong characters, never lost.
"""

from __future__ import annotations

import codecs
import re

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

# WHATWG Encoding Standard: browsers read these labels as windows-1252, and
# the documents that carry them are written accordingly — the curly quotes
# and dashes Word inserts (0x91–0x97) only exist in windows-1252.
_WINDOWS_1252_ALIASES = {"iso8859-1", "latin-1", "ascii"}

# Detections `charset_normalizer` makes between near-identical Latin
# single-byte tables. For Portuguese and Spanish text they differ only in
# rarely used positions, and windows-1252 is what such files really are.
_LATIN_FAMILY = {
    "cp1252", "iso8859-1", "latin-1", "iso8859-15", "cp1250", "iso8859-2",
    "mac-roman", "cp850", "cp437", "iso8859-9", "cp1254", "cp858",
}

# How much more "chaos" (charset_normalizer's measure of implausible
# characters) windows-1252 may show and still count as a tie with the best
# match.
_CHAOS_TIE = 0.01

# Enough to cover any real `<head>`; declarations further down are ignored,
# as browsers ignore them.
_SNIFF_BYTES = 8192

_XML_DECLARATION = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._:-]+)""", re.IGNORECASE)
_META_CHARSET = re.compile(rb"""<meta[^>]+?charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.IGNORECASE)


def canonical_encoding(label: str | None) -> str | None:
    """The Python codec name for an encoding label, or `None` when the label
    is unknown. Labels that browsers read as windows-1252 come back as
    `cp1252`."""
    if not label:
        return None
    try:
        name = codecs.lookup(label.strip().strip("\"'")).name
    except (LookupError, ValueError):
        return None
    return "cp1252" if name in _WINDOWS_1252_ALIASES else name


def _decode_strict(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def _detect(data: bytes) -> str | None:
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return None
    try:
        matches = list(from_bytes(data))
    except Exception:
        return None
    if not matches:
        return None
    best = matches[0]
    # Short Portuguese text decodes equally cleanly as several 8-bit
    # tables, and the tie is broken by a language-coherence score that
    # often picks the wrong one — a 1962 decree from the Planalto came out
    # as cp1257, "Eleva ą categoria … honorįrio". When windows-1252 is as
    # clean as the winner, it is what such a file really is.
    for match in matches:
        if canonical_encoding(match.encoding) == "cp1252" and match.chaos <= best.chaos + _CHAOS_TIE:
            return "cp1252"
    encoding = canonical_encoding(best.encoding)
    if encoding in _LATIN_FAMILY and _decode_strict(data, "cp1252") is not None:
        return "cp1252"
    return encoding


def decode_bytes(data: bytes, declared: str | None = None) -> tuple[str, str]:
    """`(text, codec_used)` for `data`. `declared` is what the file or its
    container claims the encoding is; it is used only if the bytes agree."""
    if not data:
        return "", "utf-8"

    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding, errors="replace"), encoding

    declared_encoding = canonical_encoding(declared)
    # A UTF-16/32 label on a document with no BOM is a lie told by an
    # ASCII-compatible file (it was read far enough to find the label).
    if declared_encoding and not declared_encoding.startswith(("utf-16", "utf-32")):
        text = _decode_strict(data, declared_encoding)
        if text is not None:
            return text, declared_encoding

    text = _decode_strict(data, "utf-8")
    if text is not None:
        return text, "utf-8"

    detected = _detect(data)
    if detected:
        text = _decode_strict(data, detected)
        if text is not None:
            return text, detected

    text = _decode_strict(data, "cp1252")
    if text is not None:
        return text, "cp1252"
    return data.decode("latin-1"), "latin-1"


def declared_markup_encoding(data: bytes) -> str | None:
    """The encoding an HTML or XML document declares at its top — XML
    declaration, `<meta charset>` or `<meta http-equiv="Content-Type">` —
    as written, or `None`."""
    head = data[:_SNIFF_BYTES]
    for pattern in (_XML_DECLARATION, _META_CHARSET):
        match = pattern.search(head)
        if match:
            return match.group(1).decode("ascii", errors="ignore")
    return None


def decode_markup(data: bytes, declared: str | None = None) -> tuple[str, str]:
    """`decode_bytes` for HTML/XML: a label from the container (`declared`)
    wins over the one inside the document, as in a browser."""
    return decode_bytes(data, declared or declared_markup_encoding(data))

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""O perfil do acervo, para o contexto do motor local (2.0.0).

Um projeto sem Tema deixava o modelo sem saber o que estava lendo, e é aí
que o tipo da peça mais falta. Este módulo resume o acervo pelo que os
próprios arquivos dizem, sem nenhum pedido ao modelo: os tipos de arquivo
(PDF, Word, e-mail…), os idiomas detectados (`file.language`) e os termos que
mais abrem os títulos das páginas (a primeira linha de cada uma). É uma linha
só, de no máximo `_PROFILE_CHARS` caracteres, acrescentada ao contexto
quando o Tema está vazio (`engine_local.build_context`).
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter

from . import language_detect
from .file_types import category_of_extension

_PROFILE_CHARS = 400
# Quantas páginas entram na contagem dos títulos: um acervo de milhões de
# páginas não precisa ser lido inteiro para dizer quais termos se repetem.
_TITLE_SAMPLE_PAGES = 4000
_TITLE_TERMS = 8
# Um termo só é "frequente" se abre o título de pelo menos duas páginas.
_MIN_TITLE_COUNT = 2
_MIN_WORD_LETTERS = 4

# Palavras de ligação nas línguas mais comuns do acervo: sozinhas não dizem
# nada sobre o assunto.
_STOP_WORDS = frozenset(
    "para como pelo pela pelos pelas sobre entre desta deste esta este isso essa esse "
    "nesta neste mais menos onde quando qual quais seus suas dele dela eles elas "
    "with from that this have been which their there about into than then they "
    "para como pero este esta esto desde hasta sobre entre cuando donde "
    "page pagina página folha".split()
)


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def _title_terms(conn: sqlite3.Connection) -> list[str]:
    seen: Counter[str] = Counter()
    for (text,) in conn.execute(
        "SELECT substr(text, 1, 200) FROM page WHERE char_count > 0 ORDER BY id LIMIT ?",
        (_TITLE_SAMPLE_PAGES,),
    ):
        words = {
            word for word in re.findall(r"[^\W\d_]+", _first_line(text).lower())
            if len(word) >= _MIN_WORD_LETTERS and word not in _STOP_WORDS
        }
        seen.update(words)  # uma vez por página: é quantas páginas têm o termo
    return [word for word, count in seen.most_common(_TITLE_TERMS * 3) if count >= _MIN_TITLE_COUNT][:_TITLE_TERMS]


def _file_kinds(conn: sqlite3.Connection) -> list[str]:
    counts: Counter[str] = Counter()
    for (extension,) in conn.execute(
        "SELECT extension FROM file WHERE status NOT IN ('skipped', 'failed')"
    ):
        counts[category_of_extension("." + (extension or "")) or (extension or "?")] += 1
    return [f"{name} ({count})" for name, count in counts.most_common(4)]


def _languages(conn: sqlite3.Connection) -> list[str]:
    counts: Counter[str] = Counter()
    for (language,) in conn.execute("SELECT language FROM file WHERE language IS NOT NULL AND language != ''"):
        for code in language.split(","):
            if code.strip():
                counts[code.strip()] += 1
    return [language_detect.language_name(code) for code, _ in counts.most_common(3)]


def build_profile(conn: sqlite3.Connection) -> str:
    """O perfil em uma linha, ou `""` quando não há o que dizer (acervo sem
    arquivos extraídos) ou a leitura falha: o perfil nunca derruba a etapa."""
    try:
        parts = []
        kinds = _file_kinds(conn)
        if kinds:
            parts.append("arquivos: " + ", ".join(kinds))
        languages = _languages(conn)
        if languages:
            parts.append("idiomas: " + ", ".join(languages))
        terms = _title_terms(conn)
        if terms:
            parts.append("termos frequentes nos títulos: " + ", ".join(terms))
    except Exception:
        return ""
    text = "; ".join(parts)
    return text if len(text) <= _PROFILE_CHARS else text[: _PROFILE_CHARS - 1].rstrip() + "…"

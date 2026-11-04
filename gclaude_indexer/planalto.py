# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Federal legislation pages from the Planalto website, read by their own
structure instead of by the model.

Every act published at planalto.gov.br carries the same parts, in the same
order: a title with kind, number and date ("DECRETO Nº 93.618, DE 24 DE
NOVEMBRO DE 1986."), the ementa (the act's official one-sentence summary),
the enacting clause ("O PRESIDENTE DA REPÚBLICA, …"), the body, the place
and date line ("Brasília, 24 de novembro de 1986; 165º da Independência…")
and the signatures, the President's first. Those parts *are* the index
entry: type, date, author and summary come out of them word for word, and
the summary is the official one rather than a paraphrase.

In a collection of downloaded legislation almost every page is a Planalto
act, and the local model takes ~40 s for each window of 16 of them — days
for what this reads in minutes.

A page is taken only when the title is found near the top and either the
enacting clause or the closing date line confirms it is an act. Anything
else goes to the model as before. Nothing here decides what can be
searched: the full text of every page is indexed by `fulltext.py` whatever
classifies it.
"""

from __future__ import annotations

import re

from .classification import ClassifiedItem, WindowPage
from .html_text import STRUCK_MARK

ENGINE = "structured"

_MONTHS = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
    "JULHO": 7, "AGOSTO": 8, "AGÔSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}

# Longest names first: "DECRETO-LEI" must not be read as "DECRETO".
_KINDS = (
    "EMENDA CONSTITUCIONAL DE REVISÃO", "EMENDA CONSTITUCIONAL", "LEI COMPLEMENTAR", "LEI DELEGADA",
    "LEI CONSTITUCIONAL", "DECRETO-LEI", "DECRETO LEGISLATIVO", "DECRETO DO CONSELHO DE MINISTROS",
    "DECRETO", "LEI", "MEDIDA PROVISÓRIA", "MEDIDA PROVISORIA",
    "ATO DO PRESIDENTE DA MESA DO CONGRESSO NACIONAL", "ATO COMPLEMENTAR", "ATO INSTITUCIONAL",
    # Ministerial acts the same site republishes (the Covid-19
    # collection is mostly these). Same layout, same landmarks.
    "PORTARIA INTERMINISTERIAL", "PORTARIA CONJUNTA", "PORTARIA", "RESOLUÇÃO CONJUNTA", "RESOLUÇÃO",
    "INSTRUÇÃO NORMATIVA CONJUNTA", "INSTRUÇÃO NORMATIVA",
    "ATO DECLARATÓRIO DO PRESIDENTE DA MESA DO CONGRESSO NACIONAL", "ALVARÁ", "CARTA RÉGIA", "CARTA DE LEI",
    "DECISÃO",
)
_KIND_PATTERN = "|".join(re.escape(kind).replace(r"\ ", r"\s+") for kind in _KINDS)

_TITLE = re.compile(
    # "(*) DECRETO Nº 54.213 …": a footnote mark before the title.
    rf"^[#\s]*(?:\(\*+\)\s*)?(?P<kind>{_KIND_PATTERN})"
    # "Nº 93.618", "N. 9.418", "nº 29 542", "Nº 1.478-18" (an MP's reissue)
    r"(?:\s+N[º°o.\-]*\s*(?P<number>\d[\d. ]*\d|\d)(?P<suffix>-[\dA-Z]+)?)?"
    r"\s*[,.]?\s*(?:[-–—]\s*)?DE\s+"
    # "DE 21 DE AGOSTO DE 1984", the older "De 23 janeiro DE 1948", and
    # the typo "DE JUNHO DE1949".
    r"(?:(?P<day>\d{1,2})[º°o]?\s+(?:DE\s+)?(?P<month>[A-ZÇÔÁÉÍÓÚÂÊ]+)\s+(?:DE\s*)?)?(?P<year>\d{4})",
    re.IGNORECASE,
)

# The sentence that opens the body: what comes before it, after the title,
# is the ementa (plus the site's own notes, filtered out below).
_ENACTING = re.compile(
    r"^\s*(?:O|A|OS|AS)\s+(?:PRESIDENT[EA]|VICE-PRESIDENT[EA]|CONGRESSO|MESAS?|MINISTROS?|"
    r"CHEFE|JUNTA|SENADO|CÂMARA)\b|^\s*FA[ÇC]O\s+SABER|^\s*(?:DECRETA|RESOLVE)\s*:|"
    # "…no uso das atribuições que lhe confere …, resolve:": in ministerial
    # acts the enacting verb ends the line instead of opening it.
    r"^.{20,}\b(?:DECRETA|RESOLVE|RESOLVEM|DETERMINA)\s*:\s*$",
    re.IGNORECASE,
)

# "Brasília, 24 de novembro de 1986; 165º da Independência e 98º da República."
_CLOSING = re.compile(r"\bda\s+Independ[êe]ncia\b.*\bda\s+Rep[úu]blica\b", re.IGNORECASE)

# Lines the site adds around the ementa: status, links, notes.
_NOTE = re.compile(
    r"^\s*(?:\(?\s*(?:Revogad[oa]|Vide|Vigência|Vig[êe]ncia|Texto\s+(?:para\s+impress[ãa]o|compilado|original)|"
    r"Mensagem\s+de\s+veto|Convers[ãa]o|Convertid[oa]|Regulamento|Regulamenta[çc][ãa]o|Promulga[çc][ãa]o|"
    r"Produ[çc][ãa]o\s+de\s+efeito|Publica[çc][ãa]o\s+original|Retifica[çc][ãa]o|Republica[çc][ãa]o|"
    r"Partes?\s+mantid|Reeditad|Publicad|Exposi[çc][ãa]o\s+de\s+motivos|Revigorad|Suspens|Declarad|Ver\s|Veto|Eficácia|"
    r"N[ãa]o\s+remover|-\s+(?:Down|Up)\b|Anexo|\(Vide|Presidência\s+da\s+República|Casa\s+Civil|Subchefia|Secretaria|###)|\s*\|)",
    re.IGNORECASE,
)

_REVOKED = re.compile(r"^\s*\(?\s*Revogad[oa]\b.*", re.IGNORECASE)

# What the Planalto site prints above every act: "Presidência da
# República / Casa Civil / Subchefia…", or the old "###DEC-024388-…@@@"
# marker.
_HEADER = re.compile(r"Presid[êe]ncia\s+da\s+Rep[úu]blica|Subchefia\s+para\s+Assuntos\s+Jur[íi]dicos|^#*[A-Z]{2,4}-\d{6}-", re.IGNORECASE)


def _site_header(lines: list[str]) -> bool:
    return any(_HEADER.search(line) for line in lines)


_SCAN_LINES = 15
_SUMMARY_LIMIT = 600

# The place and date line of acts that are not the President's:
# "Congresso Nacional, em 21 de junho de 2005", "Capital Federal, 8 de
# agosto de 1891, 3º da Republica." The signature comes right under it.
_DATE_LINE = re.compile(
    r"^(?:Congresso\s+Nacional|Senado\s+Federal|C[âa]mara\s+dos\s+Deputados|Bras[íi]lia|"
    r"Rio\s+de\s+Janeiro|Capital\s+Federal|Pal[áa]cio\b[^,]{0,60})\s*,\s*(?:em\s+)?\d{1,2}",
    re.IGNORECASE,
)

# Acts signed by a body rather than by one person, or whose signature the
# page does not carry: the author is the body. An amendment to
# the Constitution is signed by the two Mesas, a dozen names.
_INSTITUTIONAL_AUTHOR = {
    "EMENDA CONSTITUCIONAL": "Mesas da Câmara dos Deputados e do Senado Federal",
    "EMENDA CONSTITUCIONAL DE REVISÃO": "Mesa do Congresso Nacional",
    "ATO DO PRESIDENTE DA MESA DO CONGRESSO NACIONAL": "Presidente da Mesa do Congresso Nacional",
    "ATO DECLARATÓRIO DO PRESIDENTE DA MESA DO CONGRESSO NACIONAL": "Presidente da Mesa do Congresso Nacional",
    "DECRETO LEGISLATIVO": "Congresso Nacional",
}
_SIGNED_BY_A_BODY = ("EMENDA CONSTITUCIONAL", "EMENDA CONSTITUCIONAL DE REVISÃO")

_PARTICLES = {"da", "das", "de", "do", "dos", "e"}
_ROMAN = re.compile(r"^[IVX]+$")


def person_name(name: str) -> str:
    """One spelling for a signature the site writes three ways ("ERNESTO
    GEISEL", "Ernesto Geisel", "ernesto geisel"): capitalized words, the
    particles in lower case, roman numerals kept ("D. Pedro II")."""
    first = [True]

    def word(match: re.Match) -> str:
        text = match.group(0)
        if _ROMAN.match(text) and not first[0]:
            return text.upper()
        lower = text.lower()
        result = lower if (lower in _PARTICLES and not first[0]) else lower[:1].upper() + lower[1:]
        first[0] = False
        return result

    return re.sub(r"[^\W\d_]+", word, " ".join(name.split()))


def _signature(lines: list[str]) -> str | None:
    for line in lines[:2]:
        if line.lower().startswith("este texto") or line.startswith("*") or len(line) > 80:
            continue
        name = line.strip(" .|,")
        return person_name(name) if name else None
    return None


def find_author(text: str, kind: str | None) -> str | None:
    """The act's author from its whole text: the first signature under the
    last place and date line, or the body that issues that kind of act.

    The page the classifier sees is cut at the project's page size (4,000
    characters by default), and in a long law the signature is past the
    cut; the import reads the whole text again to find it."""
    if kind in _SIGNED_BY_A_BODY:
        return _INSTITUTIONAL_AUTHOR[kind]
    lines = [_clean(line) for line in (text or "").split("\n")]
    lines = [line for line in lines if line]
    for index in range(len(lines) - 1, -1, -1):
        if _CLOSING.search(lines[index]) or _DATE_LINE.match(lines[index]):
            author = _signature(lines[index + 1:index + 3])
            if author:
                return author
            break
    return _INSTITUTIONAL_AUTHOR.get(kind or "")


def _clean(line: str) -> str:
    line = line.strip().strip("|")
    return " ".join(line.replace(STRUCK_MARK, " ").split())


def parse(text: str) -> dict | None:
    """`{type, number, date, author, summary, revoked}` for an act page, or
    `None` when the page does not read as one."""
    lines = [_clean(line) for line in (text or "").split("\n")]
    lines = [line for line in lines if line]
    title_index = None
    match = None
    for index, line in enumerate(lines[:_SCAN_LINES]):
        match = _TITLE.match(line)
        if match:
            title_index = index
            break
        # "ATO DO PRESIDENTE DA MESA / DO CONGRESSO NACIONAL No- 42, DE 2013":
        # a title the site broke over two lines.
        if index + 1 < len(lines):
            match = _TITLE.match(f"{line} {lines[index + 1]}")
            if match:
                title_index = index + 1
                break
    if match is None:
        return None
    year = int(match.group("year"))
    if not 1800 <= year <= 2100:
        return None
    if match.group("day"):
        month = _MONTHS.get(match.group("month").upper())
        day = int(match.group("day"))
        if month is None or not 1 <= day <= 31:
            return None
        date = f"{year:04d}-{month:02d}-{day:02d}"
    else:
        date = f"{year:04d}"  # "ATO … Nº 90, DE 2020": the year is all there is

    enacting_index = None
    for index in range(title_index + 1, min(len(lines), title_index + 40)):
        if _ENACTING.match(lines[index]):
            enacting_index = index
            break
    closing_index = None
    for index in range(len(lines) - 1, title_index, -1):
        if _CLOSING.search(lines[index]):
            closing_index = index
            break
    # The title alone could be a citation inside another document: one of
    # the two other landmarks has to agree that this page is the act. The
    # site's own header above the title counts too: acts of the
    # Empire ("Attendendo ao que…", "Eu o Principe Regente…") have neither
    # an enacting clause nor the republican closing line.
    if enacting_index is None and closing_index is None and not _site_header(lines[:title_index]):
        return None

    revoked = None
    ementa_lines = []
    stop = enacting_index if enacting_index is not None else min(len(lines), title_index + 6)
    for line in lines[title_index + 1:stop]:
        if revoked is None and _REVOKED.match(line):
            revoked = line.strip("() ")
            continue
        if _NOTE.match(line):
            continue
        ementa_lines.append(line)
    if enacting_index is None:
        # Without an enacting clause nothing marks where the ementa ends:
        # an act of the Empire runs straight into its text ("Convindo ao
        # meu real serviço…"). Its ementa is the one line under the title.
        ementa_lines = ementa_lines[:1]
    ementa = " ".join(ementa_lines).strip()
    if not ementa:
        # No ementa (the Congress's acts never have one): the first article,
        # or the act's single sentence, says what it does.
        start = enacting_index if enacting_index is not None else title_index + 1
        for line in lines[start:start + 12]:
            if line.lower().startswith("art") or (len(line) > 120 and start == enacting_index and "ATO" in match.group("kind").upper()):
                ementa = line
                break
    if len(ementa) > _SUMMARY_LIMIT:
        ementa = ementa[: _SUMMARY_LIMIT - 1].rstrip() + "…"

    kind = " ".join(match.group("kind").upper().split())
    kind = kind.replace("PROVISORIA", "PROVISÓRIA")
    author = find_author("\n".join(lines[title_index + 1:]), kind)
    number = match.group("number")
    if number:
        number = number.replace(" ", ".") + (match.group("suffix") or "")
    title = f"{kind} Nº {number}" if number else kind
    summary = f"{title}: {ementa}" if ementa else title
    if revoked:
        summary = f"{summary} ({revoked})"
    return {
        "type": kind,
        "number": number,
        "date": date,
        "author": author,
        "summary": summary,
        "revoked": revoked,
        "has_ementa": bool(ementa),
    }


def _is_web_page(page: WindowPage) -> bool:
    return page.file_name.lower().endswith((".htm", ".html"))


def split(pages: list[WindowPage]) -> tuple[list[ClassifiedItem], list[WindowPage]]:
    """Items for the pages read as Planalto acts, and the pages left for the
    model. One item per act; an act spread over several consecutive pages
    of the same file is one item (its first page carries the title)."""
    items: list[ClassifiedItem] = []
    rest: list[WindowPage] = []
    current: ClassifiedItem | None = None
    current_file: str | None = None
    for page in pages:
        if current is not None and page.file_name == current_file:
            current.end_ref, current.end_order = page.reference, page.order
            current.has_table = current.has_table or page.has_table
            current.has_image = current.has_image or page.image_count > 0
            continue
        current, current_file = None, None
        act = parse(page.text) if _is_web_page(page) else None
        if act is None:
            rest.append(page)
            continue
        current = ClassifiedItem(
            start_ref=page.reference, end_ref=page.reference,
            start_order=page.order, end_order=page.order,
            type=act["type"], date=act["date"], author=act["author"], summary=act["summary"],
            has_table=page.has_table, has_image=page.image_count > 0,
            engine=ENGINE, confidence="high" if act["has_ementa"] else "medium",
            files=[page.file_name],
        )
        current_file = page.file_name
        items.append(current)
    return items, rest

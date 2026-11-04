# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Cliente do LexML, a rede de informação legislativa do Senado (fase 38).

Responde à pergunta "quais normas federais tratam de X" quando a norma não
está na pasta do acervo: a busca por tema (`search_cli`) e a tela "Buscar
no acervo" chamam `search()` e listam o que vier, marcado como "fora do
acervo".

Limitação medida no fim de 2026: tanto o SRU (`/busca/SRU`) quanto a página
de busca respondem a programas com a página "Verificação de segurança" do
Senado, uma página HTML que pede um navegador. Contorná-la não é opção.
Este cliente a reconhece e devolve `status="challenge"` com o link da busca
para a pessoa abrir no navegador; se o LexML voltar a responder a
programas, o mesmo código passa a listar as normas sem mudança. Nenhuma
consulta acontece durante a indexação: só quando alguém pesquisa.
"""

from __future__ import annotations

import http.client
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

SRU_URL = "https://www.lexml.gov.br/busca/SRU"
SEARCH_PAGE_URL = "https://www.lexml.gov.br/busca/search?keyword={term}"
URN_PAGE_URL = "https://www.lexml.gov.br/urn/{urn}"
# O título da página que o Senado devolve a programas.
CHALLENGE_MARK = "verificação de segurança"
# 10 s: o SRU, quando responde, responde em menos de 2 s; acima de 10 s é
# a rede, e a busca local já está pronta para ser mostrada.
DEFAULT_TIMEOUT = 10.0
MAX_BODY_BYTES = 4 * 1024 * 1024
_USER_AGENT = "GClaude Indexer (https://github.com/alexccastilho/gclaude-indexer)"

Fetch = Callable[[str, float], bytes]


@dataclass(frozen=True)
class LexmlRecord:
    title: str
    date: str
    description: str
    urn: str
    url: str


@dataclass
class LexmlResult:
    """`status`: `ok` (lista, possivelmente vazia), `challenge` (o Senado
    pediu verificação no navegador), `offline` (sem resposta) ou `error`
    (resposta que não é o XML do SRU). `search_url` sempre vem preenchido:
    é o que a pessoa abre quando o programa não consegue."""

    status: str
    records: list[LexmlRecord] = field(default_factory=list)
    search_url: str = ""
    detail: str = ""


def search_page_url(term: str) -> str:
    return SEARCH_PAGE_URL.format(term=quote(term))


def sru_url(term: str, limit: int) -> str:
    return SRU_URL + "?" + urlencode({
        "operation": "searchRetrieve", "version": "1.1", "query": term, "maximumRecords": max(1, limit),
    })


def _fetch(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/xml, text/xml;q=0.9, */*;q=0.1",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _records(root: ET.Element) -> list[LexmlRecord]:
    """Os registros Dublin Core da resposta, sem depender dos prefixos de
    namespace que o servidor escolher."""
    registros = []
    for record in root.iter():
        if _local_name(record.tag) != "record":
            continue
        campos: dict[str, str] = {}
        for element in record.iter():
            nome = _local_name(element.tag)
            if nome in ("title", "date", "description", "identifier") and nome not in campos:
                campos[nome] = " ".join((element.text or "").split())
        titulo = campos.get("title", "")
        if not titulo:
            continue
        urn = campos.get("identifier", "")
        if urn.startswith("urn:lex:"):
            url = URN_PAGE_URL.format(urn=urn)
        elif urn.startswith(("http://", "https://")):
            url = urn
        else:
            url = search_page_url(titulo)
        registros.append(LexmlRecord(
            title=titulo, date=campos.get("date", ""), description=campos.get("description", ""),
            urn=urn, url=url,
        ))
    return registros


def search(term: str, limit: int = 10, timeout: float = DEFAULT_TIMEOUT, fetch: Fetch | None = None) -> LexmlResult:
    """Consulta o SRU do LexML por `term`. Nunca levanta exceção: toda falha
    vira um `status` com o link da busca para abrir no navegador.
    `fetch` existe para os testes, que nunca falam com a rede."""
    term = " ".join((term or "").split())
    pagina = search_page_url(term)
    if not term:
        return LexmlResult(status="error", search_url=pagina, detail="termo vazio")
    buscar = fetch or _fetch
    try:
        corpo = buscar(sru_url(term, limit), timeout)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as exc:
        return LexmlResult(status="offline", search_url=pagina, detail=str(exc))
    texto = corpo.decode("utf-8", errors="replace") if isinstance(corpo, bytes) else str(corpo)
    minusculas = texto.lower()
    inicio = minusculas.lstrip()[:200]
    # A marca só vale numa página HTML (no começo ou no <title>): uma ementa
    # do SRU pode falar em "verificação de segurança" (Lei 12.334, barragens)
    # e não é a página do Senado (revisão da fase 38).
    titulo = re.search(r"<title[^>]*>(.*?)</title>", minusculas, re.S)
    if inicio.startswith(("<!doctype html", "<html")) or (titulo and CHALLENGE_MARK in titulo.group(1)):
        return LexmlResult(status="challenge", search_url=pagina)
    # O SRU nunca manda DTD nem entidades; um XML que as traga é outra
    # coisa (e é por elas que um XML hostil estoura um parser). Também não
    # passa de alguns KB por registro: acima de 4 MB não é a resposta.
    if "<!doctype" in minusculas or "<!entity" in minusculas or len(corpo) > MAX_BODY_BYTES:
        return LexmlResult(status="error", search_url=pagina, detail="resposta fora do formato do SRU")
    try:
        raiz = ET.fromstring(corpo)
    except ET.ParseError as exc:
        return LexmlResult(status="error", search_url=pagina, detail=f"XML inválido: {exc}")
    return LexmlResult(status="ok", records=_records(raiz)[:limit], search_url=pagina)

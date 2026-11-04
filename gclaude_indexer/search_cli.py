# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Busca por tema na pasta de saída, pela linha de comando (fase 38).

É o que o Claude Code roda quando alguém pergunta "quais leis tratam de
saneamento": o mesmo motor da tela "Buscar no acervo" (`fulltext`, FTS5),
com a saída em Markdown para ser lida por um modelo. O `buscar.bat` que
`artifacts.generate_search_launcher` grava na pasta de saída chama este
módulo com a própria pasta como primeiro argumento:

    buscar.bat saneamento
    buscar.bat "segurança alimentar" --so-legislacao --limite 30
    buscar.bat saneamento --lexml

Quando nenhuma norma do acervo cita o termo, ou com `--lexml`, consulta
também o LexML (`lexml.py`) e lista o que vier como "fora do acervo".
Sem rede, ou com a verificação do Senado no caminho, diz o que houve e dá
o link para abrir no navegador; a parte local sai do mesmo jeito.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from . import lexml
from .artifacts import NORMS_FILENAME, legislation_file_test, norm_links_by_file
from .fulltext import MATCH_END, MATCH_START
from .fulltext import search as fulltext_search
from .i18n import DEFAULT_LANGUAGE, translate
from .project import DB_NAME, load_project

# Os filtros por grupo e por legislação se aplicam depois da consulta FTS,
# que ordena por relevância: pede-se mais do que se mostra para o filtro
# não devolver uma página vazia quando o grupo pedido está mais abaixo.
FETCH_FACTOR = 5
# Trechos por arquivo: três bastam para dizer "é esta norma" e abrir o
# arquivo certo; a saída inteira é para ser lida por um modelo, e 21
# trechos do mesmo decreto (caso medido) só gastavam contexto.
EXCERPTS_PER_FILE = 3
LEXML_LIMIT = 10


def _snippet(text: str) -> str:
    """O trecho do FTS5 numa linha só, com o termo em negrito."""
    linha = " ".join(text.replace(MATCH_START, "**").replace(MATCH_END, "**").split())
    return linha.replace("** **", " ")


def run(
    output_folder: Path | str, term: str, group: str | None, only_legislation: bool, limit: int,
    lexml_flag: bool, language: str, lexml_search: Callable[..., lexml.LexmlResult | None] = lexml.search,
) -> str:
    """O resultado em Markdown: a seção "No acervo" e, quando consultado, a
    seção do LexML. `lexml_search` é injetável para a suíte nunca sair
    para a rede."""
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    limit = max(1, limit)
    config, conn = load_project(Path(output_folder))
    try:
        e_norma = legislation_file_test(conn)
        links = norm_links_by_file(conn)
        hits, total = fulltext_search(conn, term, limit=max(limit * FETCH_FACTOR, 100))
    finally:
        conn.close()

    # Uma entrada por arquivo, na ordem do melhor trecho de cada um. Antes,
    # um termo podia devolver vários trechos do mesmo decreto antes de
    # qualquer outra norma; "quais leis tratam de X" quer
    # a lista das normas, com os trechos embaixo de cada uma.
    arquivos: dict[tuple[str | None, str], dict] = {}
    for hit in hits:
        norma = e_norma(hit.group_key, hit.name)
        if group and hit.group_key != group:
            continue
        if only_legislation and not norma:
            continue
        entrada = arquivos.setdefault((hit.group_key, hit.relative_path), {"hit": hit, "norma": norma, "trechos": []})
        if len(entrada["trechos"]) < EXCERPTS_PER_FILE:
            entrada["trechos"].append(hit)
    normas_no_acervo = sum(1 for entrada in arquivos.values() if entrada["norma"])
    mostrados = list(arquivos.values())[:limit]

    filtros = []
    if group:
        filtros.append(t("buscar.filter_group", group=group))
    if only_legislation:
        filtros.append(t("buscar.filter_legislation"))

    linhas = [f"# {t('buscar.title', term=term)}", ""]
    if filtros:
        linhas += [t("buscar.filters", filters="; ".join(filtros)), ""]
    linhas += [f"## {t('buscar.local_title', files=len(mostrados), total=total)}", ""]
    if not mostrados:
        linhas.append(t("buscar.local_empty"))
    for entrada in mostrados:
        hit = entrada["hit"]
        linhas.append(f"- **{hit.name}**; {t('buscar.group')}: {hit.group_key or '?'}; `{hit.relative_path}`")
        if entrada["norma"]:
            url = links.get((hit.group_key, hit.name))
            linhas.append(f"  {t('buscar.norm_link')}: {url or t('buscar.norm_unknown', norms=NORMS_FILENAME)}")
        for trecho in entrada["trechos"]:
            onde = []
            if trecho.locator:
                onde.append(trecho.locator)
            if trecho.line:
                onde.append(t("search.line", line=trecho.line))
            if trecho.struck:
                onde.append(t("search.struck"))
            prefixo = f"[{', '.join(onde)}] " if onde else ""
            linhas.append(f"  > {prefixo}{_snippet(trecho.snippet)}")

    if lexml_flag or normas_no_acervo == 0:
        resultado = lexml_search(term, limit=LEXML_LIMIT)
        linhas += ["", f"## {t('search.lexml_title')}", ""]
        if resultado is None:
            linhas.append(t("buscar.lexml_skipped"))
        elif resultado.status == "ok" and resultado.records:
            for registro in resultado.records:
                linha = f"- **{registro.title}**"
                if registro.date:
                    linha += f" ({registro.date})"
                linha += f"; {t('search.lexml_outside')}; {registro.url}"
                linhas.append(linha)
                if registro.description:
                    linhas.append(f"  > {registro.description}")
        elif resultado.status == "ok":
            linhas.append(t("search.lexml_empty"))
        else:
            linhas.append(f"{t('search.lexml_' + resultado.status)} {resultado.search_url}")
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="buscar", description="Busca por tema na pasta de saída de um projeto do GClaude Indexer.",
    )
    parser.add_argument("pasta", help="pasta de saída do projeto (a que tem project.db)")
    parser.add_argument("termo", nargs="+", help='palavras, "frase entre aspas" ou prefixo*')
    parser.add_argument("--grupo", default=None, help="só este grupo")
    parser.add_argument("--so-legislacao", action="store_true", help="só páginas de normas do Planalto")
    parser.add_argument("--limite", type=int, default=20, help="quantos trechos mostrar (padrão 20)")
    parser.add_argument("--lexml", action="store_true", help="consultar também o LexML")
    parser.add_argument("--idioma", default=DEFAULT_LANGUAGE, choices=("pt", "en", "es"))
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    pasta = Path(args.pasta)
    if not (pasta / DB_NAME).exists():
        print(translate(args.idioma, "buscar.no_project", folder=str(pasta), db=DB_NAME), file=sys.stderr)
        return 2
    print(run(
        pasta, " ".join(args.termo), args.grupo, args.so_legislacao, args.limite, args.lexml, args.idioma,
    ), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

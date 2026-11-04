# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Generation of the four output artifacts (spec section 5, step 8):
`index.md`, `timeline.md`, `review.md` and `project_instructions.md`.

Each file is rewritten from scratch on every run — deterministic from the
database's current state, so regenerating is always safe.

File names are fixed in English regardless of the interface language (Task
11, Phase 14): a name that changed with the language would break scripts,
links and the system's own re-reads of these files. What follows the
language is the *content* — headings, table headers and labels, translated
through `translate()` (moved to core in this same task, see `i18n.py`).
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import sqlite3
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .config import ProjectConfig
from .events import record_event
from .html_text import STRUCK_MARK
from .i18n import translate
from .managed_block import user_part, write_managed
from .run_control import OperationCancelled, checkpoint

# Kept in Portuguese on purpose: this is default *content* written into
# `project_instructions.md` for the collection's own Claude Project, not UI
# text — it is not covered by the i18n layer and changing its wording would
# be a content change, not a rename. (Task 11, Phase 14: the file's own
# headings and labels now follow the interface language — see
# `generate_project_instructions_md()` below — but this default role prose
# and `SOURCE_OF_TRUTH_RULE` stay out of scope, same as this comment
# predates.)
DEFAULT_ROLE = (
    "Você é um assistente de pesquisa que ajuda a localizar e resumir peças "
    "deste acervo. Responda com base no índice e na cronologia para "
    "encontrar a peça certa, mas siga sempre a regra inegociável abaixo "
    "antes de citar qualquer valor, data ou conteúdo de tabela."
)

SOURCE_OF_TRUTH_RULE = (
    "**Valor, data e conteúdo de tabela citados numa resposta sempre vêm da "
    "leitura do arquivo original — nunca do índice.** O índice e a "
    "cronologia foram gerados por OCR e por um motor de classificação "
    "automática; ambos podem errar. Servem só para localizar a peça certa "
    "pela referência (`f. N` ou `p. N`) e pelo nome do arquivo de origem. "
    "Antes de citar um número, uma data ou o conteúdo de uma tabela, abra o "
    "arquivo original na pasta de origem, na referência indicada, e "
    "confirme o valor ali."
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# An output file is rewritten only when what it says changed. Every
# generation used to rewrite all of them — on a large project, dozens of
# index files and a `normas-citadas.md` of tens of MB re-synced by Google Drive and, worse, no
# way for the user to tell which ones a new indexing run had actually
# touched, so the whole package went back to the Claude Project each time.
# The generation stamp ("Gerado em 2026-11-03T09:05:15") is not a change.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_changed_files: ContextVar[list[Path] | None] = ContextVar("changed_files", default=None)
_removed_files: ContextVar[list[str] | None] = ContextVar("removed_files", default=None)


def _remove_output(path: Path) -> None:
    """Deletes an output file that no longer has a reason to exist, noting
    it for the report: the user has to take it out of the Claude Project."""
    try:
        path.unlink()
    except OSError:
        return
    removed = _removed_files.get()
    if removed is not None:
        removed.append(path.name)


def _without_stamps(text: str) -> str:
    return _TIMESTAMP.sub("", text)


def write_if_changed(path: Path, text: str, *, newline: str | None = None) -> bool:
    """Writes `text` to `path` unless the file already says the same,
    generation stamps aside. Returns whether it wrote; a write is noted for
    `generate_all_artifacts`' report of what changed."""
    try:
        with path.open(encoding="utf-8", newline=newline) as handle:
            if _without_stamps(handle.read()) == _without_stamps(text):
                return False
    except (OSError, UnicodeDecodeError):
        pass
    path.write_text(text, encoding="utf-8", newline=newline)
    changed = _changed_files.get()
    if changed is not None:
        changed.append(path)
    return True


def _items(conn):
    return conn.execute("SELECT * FROM item ORDER BY group_key, start_order").fetchall()


def _cell(value) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


# Fixed, English, independent of the interface language — see module
# docstring. Shared with `web/app.py` (Result screen listing/preview) and
# `claude_package.py` (Claude Project zip) so the four names live in one
# place.
# Quebra de linha dos artefatos, nomeada para nao se perder em escapes.
NL = chr(10)

INDEX_FILENAME = "index.md"
TIMELINE_FILENAME = "timeline.md"
REVIEW_FILENAME = "review.md"
PROJECT_INSTRUCTIONS_FILENAME = "project_instructions.md"
# Fase 38: uma linha por norma federal reconhecida no acervo, com link.
# Substitui o `legislacao-<grupo>.md` (dezenas de MB num acervo grande,
# recusados pelo claude.ai) por poucos KB que cabem em
# qualquer Project.
NORMS_FILENAME = "normas-citadas.md"
# Fase 38: o lançador da busca por tema (`search_cli`) na pasta de saída.
# Fica na pasta, não no pacote: é para o Claude Code, que lê a pasta.
SEARCH_LAUNCHER_FILENAME = "buscar.bat"


# O motor que o leitor do Planalto (`planalto.py`) grava nas peças que
# reconhece de forma determinística: leis, decretos, MPs, portarias. Fase
# 31: essas peças saem do índice e da cronologia (num acervo grande de
# legislação, eram quase todas as linhas do índice). Fase 38: elas não vão
# mais para arquivo nenhum. O `legislacao-<grupo>.md` chegava a dezenas de
# MB em duas partes e o claude.ai recusou as duas ("o conhecimento do
# projeto excede o máximo"); um arquivo que nunca sobe só confundia.
STRUCTURED_ENGINE = "structured"


def _safe_group_name(group_key: str) -> str:
    seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in group_key)
    seguro = "-".join(parte for parte in seguro.split("-") if parte)
    return seguro or "grupo"


def group_index_filename(group_key: str) -> str:
    """`index-<grupo>.md`, com o nome do grupo reduzido a caracteres
    seguros para nome de arquivo em qualquer sistema."""
    return f"index-{_safe_group_name(group_key)}.md"


def group_timeline_filename(group_key: str) -> str:
    """`timeline-<grupo>.md`: a cronologia de um grupo com mais peças datadas
    do que `config.timeline_split_items`, para não inflar o `timeline.md`."""
    return f"timeline-{_safe_group_name(group_key)}.md"


def _range_cell(item, origem: tuple[str, int] | None, *, with_file: bool) -> str:
    """`f. 3 – f. 4 (vol1.pdf, p. 3)`, ou só `(p. 3)` quando o arquivo já
    está na coluna Origem da mesma linha (`with_file=False`) — a repetição
    custava 20 a 30% do tamanho do índice (fase 31)."""
    span = f"{item['start_ref']} – {item['end_ref']}"
    if not origem:
        return span
    arquivo, pagina = origem
    if with_file:
        return f"{span} ({arquivo}, p. {pagina})"
    return f"{span} (p. {pagina})"


# Corte de um índice de grupo (fase 31): o Projeto do Claude recusa arquivo
# acima de 30 MB (`claude_package.MAX_FILE_BYTES`); 25 MB deixa margem para
# a quebra na fronteira de arquivo de origem, que nunca parte um bloco.
INDEX_PART_BYTES = 25 * 1024 * 1024


def _unique_name(nome: str, group: str, usados: set[str], reservados: set[str] = frozenset()) -> str:
    """"A/B" e "A-B" viram o mesmo nome seguro; sem o sufixo, um grupo
    sobrescreveria o arquivo do outro sem aviso. `reservados`: nomes-base
    de outros grupos que uma parte numerada também não pode tomar."""
    if nome in usados or nome in reservados:
        sufixo = hashlib.sha1(group.encode("utf-8")).hexdigest()[:6]
        nome = f"{nome[:-3]}-{sufixo}.md"
    usados.add(nome)
    return nome


def _first_file(files: str | None) -> str:
    return (files or "").split(";")[0].strip()


def _legislation_map(conn) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[str, str]]:
    """`(arquivos, raizes)`: cada arquivo por `(grupo, nome)` com caminho e
    extensão, e a pasta comum dos atos reconhecidos de cada grupo. Base dos
    dois predicados abaixo."""
    arquivos = {
        (row["group_key"], row["name"]): (
            (row["relative_path"] or "").replace("\\", "/"),
            (row["extension"] or "").lower().lstrip("."),
        )
        for row in conn.execute("SELECT group_key, name, relative_path, extension FROM file")
    }
    pastas: dict[str, list[str]] = {}
    for row in conn.execute("SELECT group_key, files FROM item WHERE engine = ?", (STRUCTURED_ENGINE,)):
        info = arquivos.get((row["group_key"], _first_file(row["files"])))
        if info:
            pastas.setdefault(row["group_key"], []).append(posixpath.dirname(info[0]))
    raizes = {
        group: "" if "" in dirs else posixpath.commonpath(dirs)
        for group, dirs in pastas.items()
    }
    return arquivos, raizes


def _under_legislation_root(arquivos, raizes, group_key, name) -> bool:
    raiz = raizes.get(group_key)
    if raiz is None:
        return False
    info = arquivos.get((group_key, name))
    if not info or info[1] not in ("htm", "html"):
        return False
    caminho = info[0]
    return raiz == "" or caminho == raiz or caminho.startswith(raiz + "/")


def legislation_file_test(conn) -> Callable[[str | None, str], bool]:
    """O mesmo predicado de `_legislation_test`, por arquivo em vez de por
    peça: a busca por tema (fase 38) acha trechos, e um trecho sabe o
    arquivo e o grupo, não a peça. É legislação o arquivo de um ato
    reconhecido ou um `.htm` da pasta comum desses atos."""
    arquivos, raizes = _legislation_map(conn)
    reconhecidos = {
        (row["group_key"], _first_file(row["files"]))
        for row in conn.execute("SELECT group_key, files FROM item WHERE engine = ?", (STRUCTURED_ENGINE,))
    }

    def e_legislacao(group_key, name) -> bool:
        return (group_key, name) in reconhecidos or _under_legislation_root(arquivos, raizes, group_key, name)

    return e_legislacao


def _legislation_test(conn) -> Callable[[sqlite3.Row], bool]:
    """O predicado "esta peça é legislação do Planalto", igual para o
    índice, a cronologia, a coluna Confiança e as instruções.

    É legislação a peça que o leitor do Planalto reconheceu (`structured`)
    e também a peça vinda de uma página `.htm`/`.html` da mesma pasta dos
    atos reconhecidos — a pasta comum, por grupo, dos arquivos dessas
    peças. Num acervo grande, milhares de peças eram páginas de
    `Direito/Legislacao/...` que o leitor não leu — retificações, mensagens
    presidenciais, decretos fora do padrão — e que o modelo classificou:
    só elas quase dobravam o índice do pacote. Uma página
    `.htm` fora dessa pasta (um manual) continua documento do acervo; um
    grupo sem ato reconhecido não tem pasta de legislação.
    """
    arquivos, raizes = _legislation_map(conn)

    def e_legislacao(item) -> bool:
        if item["engine"] == STRUCTURED_ENGINE:
            return True
        return _under_legislation_root(arquivos, raizes, item["group_key"], _first_file(item["files"]))

    return e_legislacao


# Tipos de ato cuja URN o LexML resolve de forma previsível. Conferido:
# `urn:lex:br:federal:lei:1993-06-21;8666` abre a Lei 8.666.
# Fora da tabela, o link é a busca do LexML pelo título: melhor um link que
# funciona do que uma URN que dá 404.
_LEXML_KINDS = {
    "LEI": "lei",
    "LEI COMPLEMENTAR": "lei.complementar",
    "LEI DELEGADA": "lei.delegada",
    "DECRETO": "decreto",
    "DECRETO-LEI": "decreto.lei",
    "DECRETO LEGISLATIVO": "decreto.legislativo",
    "MEDIDA PROVISÓRIA": "medida.provisoria",
    "EMENDA CONSTITUCIONAL": "emenda.constitucional",
}
_LEXML_URN = "https://www.lexml.gov.br/urn/urn:lex:br:federal:{kind}:{date};{number}"
_LEXML_SEARCH = "https://www.lexml.gov.br/busca/search?keyword={term}"


def norm_url(kind: str, number: str | None, date: str | None) -> str:
    """O link de uma norma: a URN do LexML quando tipo, número e data
    completa permitem montá-la; senão a busca do LexML pelo título."""
    tipo = _LEXML_KINDS.get((kind or "").upper())
    if tipo and number and date and len(date) == 10:
        limpo = re.sub(r"[.\s]", "", number).lower()
        return _LEXML_URN.format(kind=tipo, date=date, number=limpo)
    titulo = f"{kind} {number}".strip() if number else (kind or "")
    return _LEXML_SEARCH.format(term=quote(titulo))


# `TIPO`, depois opcionalmente ` Nº número`, depois opcionalmente `: ementa`;
# um ato revogado sem ementa termina em ` (Revogada pela …)`, que fica fora
# do número. A versão anterior deixava o `Nº` opcional engolir a frase
# inteira nesse caso (revisão da fase 38).
_NORM_SUMMARY = re.compile(
    r"^(?P<kind>[^:(]+?)(?:\s+Nº\s+(?P<number>[^\s:(]+))?\s*(?:\([^)]*\))?\s*(?::\s*(?P<ementa>.*))?$", re.S
)


def _split_norm_summary(summary: str | None, kind: str | None) -> tuple[str, str | None, str]:
    """`planalto.parse` grava `TIPO Nº número: ementa` no resumo da peça
    (e ` (Revogada pela …)` no fim quando é o caso). De volta às partes,
    sem reler a página; o tipo gravado na peça (`kind`) vale mais que o do
    resumo, porque é o mesmo texto já normalizado."""
    match = _NORM_SUMMARY.match((summary or "").strip())
    if not match:
        return (kind or ""), None, (summary or "")
    tipo = (kind or match.group("kind") or "").strip()
    return tipo, match.group("number"), (match.group("ementa") or "").strip()


def norm_links_by_file(conn) -> dict[tuple[str | None, str], str]:
    """De `(grupo, arquivo)` para o link da norma reconhecida nele: o que a
    busca por tema imprime ao lado de um trecho de legislação."""
    links: dict[tuple[str | None, str], str] = {}
    for ato in conn.execute(
        "SELECT group_key, files, type, date, summary FROM item WHERE engine = ?", (STRUCTURED_ENGINE,)
    ):
        chave = (ato["group_key"], _first_file(ato["files"]))
        if chave in links:
            continue
        kind, number, _ementa = _split_norm_summary(ato["summary"], ato["type"])
        links[chave] = norm_url(kind, number, ato["date"])
    return links


def generate_search_launcher(config: ProjectConfig) -> Path:
    """`buscar.bat` na pasta de saída: `buscar.bat saneamento --lexml` roda
    `search_cli` sobre esta pasta com o Python do próprio programa. Existe
    porque o Claude Code trabalha na pasta de saída e não sabe onde o
    GClaude Indexer está instalado; o `.bat` sabe (gravado na geração).
    Sob `pythonw.exe` (o atalho do instalador) troca-se pelo `python.exe`
    ao lado, senão o comando não teria console para imprimir."""
    raiz = Path(__file__).resolve().parents[1]
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").exists():
        python = python.with_name("python.exe")
    caminho = Path(config.output_folder) / SEARCH_LAUNCHER_FILENAME
    linhas = [
        "@echo off",
        "rem GClaude Indexer: busca por tema nesta pasta de saida.",
        "rem Uso: buscar.bat <termo> [--grupo G] [--so-legislacao] [--limite N] [--lexml]",
        "chcp 65001 >nul",
        f'cd /d "{raiz}"',
        f'"{python}" -m gclaude_indexer.search_cli "%~dp0." %*',
        "",
    ]
    write_if_changed(caminho, "\r\n".join(linhas), newline="")
    return caminho


def generate_cited_norms_md(conn, config: ProjectConfig, language: str) -> Path | None:
    """`normas-citadas.md`: uma linha por norma que o leitor do Planalto
    reconheceu (`structured`), com data, ementa, link, grupo e páginas.
    Nada quando o acervo não tem ato nenhum: um arquivo vazio no pacote
    faria o Claude procurar legislação onde não há. Mesma norma em duas
    páginas (o texto e uma republicação) é uma linha com as duas páginas."""
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    caminho = Path(config.output_folder) / NORMS_FILENAME
    atos = conn.execute(
        "SELECT * FROM item WHERE engine = ? ORDER BY group_key, start_order", (STRUCTURED_ENGINE,)
    ).fetchall()
    if not atos:
        try:
            caminho.unlink()
        except FileNotFoundError:
            pass
        return None

    physical = _physical_pages(conn)
    normas: dict[tuple[str, str | None, str], dict] = {}
    for ato in atos:
        kind, number, ementa = _split_norm_summary(ato["summary"], ato["type"])
        chave = (kind, number, ato["date"] or "")
        origem = physical.get((ato["group_key"], ato["start_order"]))
        pagina = f"{origem[0]} (p. {origem[1]})" if origem else _first_file(ato["files"])
        norma = normas.setdefault(chave, {
            "kind": kind, "number": number, "date": ato["date"] or "", "ementa": ementa,
            "groups": [], "pages": [],
        })
        if ato["group_key"] not in norma["groups"]:
            norma["groups"].append(ato["group_key"])
        if pagina not in norma["pages"]:
            norma["pages"].append(pagina)

    def titulo(norma) -> str:
        return f"{norma['kind']} Nº {norma['number']}" if norma["number"] else norma["kind"]

    ordenadas = sorted(normas.values(), key=lambda n: (n["kind"], n["date"], n["number"] or ""))
    linhas = [
        f"# {t('artifact.norms.title')} — {config.name}",
        "",
        t("artifact.norms.intro", timestamp=_now_iso(), count=len(ordenadas)),
        "",
        "| " + " | ".join(t(f"artifact.norms.col_{c}") for c in ("norm", "date", "summary", "link", "group", "pages")) + " |",
        "|---|---|---|---|---|---|",
    ]
    for norma in ordenadas:
        linhas.append("| " + " | ".join((
            _cell(titulo(norma)), _cell(norma["date"]), _cell(norma["ementa"]),
            norm_url(norma["kind"], norma["number"], norma["date"]),
            _cell("; ".join(norma["groups"])), _cell("; ".join(norma["pages"])),
        )) + " |")
    write_if_changed(caminho, NL.join(linhas) + NL)
    return caminho


def _legislation_count(conn) -> int:
    e_legislacao = _legislation_test(conn)
    return sum(1 for item in conn.execute("SELECT group_key, engine, files FROM item") if e_legislacao(item))


def _show_confidence(conn, config: ProjectConfig) -> bool:
    """A coluna Confiança entra quando o projeto revisa confiança baixa ou
    quando existe ao menos uma peça abaixo de `high` (fase 31)."""
    if config.review_low_confidence:
        return True
    duvidosas = conn.execute(
        "SELECT group_key, engine, files FROM item WHERE confidence != 'high'"
    ).fetchall()
    # Legislação não conta: uma lei de confiança média que não sobe não
    # justifica uma coluna `high` em toda linha do índice que sobe.
    e_legislacao = _legislation_test(conn)
    return any(not e_legislacao(item) for item in duvidosas)


def _physical_pages(conn) -> dict[tuple[str, int], tuple[str, int]]:
    """De `(grupo, folha)` para `(arquivo, página dentro do arquivo)`.

    A folha é a numeração do processo, contínua entre os PDFs do grupo; a
    página é a do arquivo, que recomeça em 1 a cada volume. O índice trazia
    só o nome do arquivo, e num grupo de 21 volumes isso não diz onde
    abrir — `f. 417` é a página 145 do Vol 2.
    """
    from .windows_prep import group_page_positions

    mapa: dict[tuple[str, int], tuple[str, int]] = {}
    for group_key, pages in group_page_positions(conn, with_text=False).items():
        for position, page in enumerate(pages, start=1):
            mapa[(group_key, position)] = (page["file_name"], page["number"])
    return mapa


# --- index.md ---------------------------------------------------------


def generate_index_md(conn, config: ProjectConfig, language: str) -> list[Path]:
    """O sumário dos grupos, mais um índice por grupo.

    Saía tudo num arquivo só: 5443 linhas e 1,58 MB na coleção que motivou
    isto, demais para um Projeto do Claude recuperar de forma confiável. O
    sumário cabe em poucos KB e diz qual arquivo abrir; a linha de cada
    peça traz a página física do PDF, porque a folha do processo não diz
    em que página de qual volume ela está.
    """
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    items = _items(conn)
    physical = _physical_pages(conn)
    e_legislacao = _legislation_test(conn)
    by_group: dict[str, list] = {}
    for item in items:
        by_group.setdefault(item["group_key"], []).append(item)

    saida = Path(config.output_folder)
    # Fase 31: a coluna Confiança só quando informa algo — num acervo grande
    # de legislação, era `high` em quase todas as linhas. Decidido pelo projeto inteiro, porque
    # `project_instructions.md` descreve as colunas uma vez só.
    show_confidence = _show_confidence(conn, config)
    colunas = ["table_range", "table_type", "table_date", "table_author"]
    if show_confidence:
        colunas.append("table_confidence")
    colunas += ["table_source", "table_summary"]
    header = "| " + " | ".join(t(f"artifact.index.{c}") for c in colunas) + " |"

    resumo = [
        f"# {t('artifact.index.title')} — {config.name}",
        "",
        t("artifact.index.generated", timestamp=_now_iso(), count=len(items)),
    ]
    if not items:
        resumo += ["", t("artifact.index.empty")]
    else:
        resumo += ["", f"## {t('artifact.index.summary_title')}", ""]

    cabecalho = [header, "|" + "---|" * len(colunas)]

    def linha(item) -> str:
        origem = physical.get((item["group_key"], item["start_order"]))
        # O arquivo só entra no intervalo quando difere da coluna Origem:
        # repeti-lo custava 20 a 30% de cada linha.
        repete = bool(origem) and origem[0] == (item["files"] or "").strip()
        span = _range_cell(item, origem, with_file=not repete)
        valores = [span, item["type"], item["date"], item["author"]]
        if show_confidence:
            valores.append(item["confidence"])
        valores += [item["files"], item["summary"]]
        return "| " + " | ".join(_cell(v) for v in valores) + " |"

    def faixa(pecas: list) -> str:
        folhas = [p["start_order"] for p in pecas] + [p["end_order"] for p in pecas]
        return f"f. {min(folhas)}–{max(folhas)}" if folhas else "—"

    def em_partes(pecas: list) -> list[list]:
        """Blocos por arquivo de origem, acumulados até `INDEX_PART_BYTES`.
        Um bloco nunca é dividido: as peças de um mesmo PDF ficam juntas,
        mesmo que o bloco sozinho passe do corte."""
        blocos: list[list] = []
        anterior = object()
        for item in pecas:
            origem = physical.get((item["group_key"], item["start_order"]))
            fonte = origem[0] if origem else item["files"]
            if fonte != anterior:
                blocos.append([])
                anterior = fonte
            blocos[-1].append(item)
        base = len((NL.join(cabecalho) + NL).encode("utf-8"))
        partes: list[list] = [[]]
        tamanho = base
        for bloco in blocos:
            bytes_bloco = sum(len((linha(p) + NL).encode("utf-8")) for p in bloco)
            if partes[-1] and tamanho + bytes_bloco > INDEX_PART_BYTES:
                partes.append([])
                tamanho = base
            partes[-1].extend(bloco)
            tamanho += bytes_bloco
        return partes

    # Todos os nomes-base antes de escrever qualquer parte: a parte
    # `index-Vol-1.md` do grupo `Vol` não pode tomar o nome do grupo `Vol-1`.
    bases = {group_index_filename(g) for g in by_group}

    def escrever(nome_base: str, group: str, pecas: list) -> list[tuple[Path, list]]:
        partes = em_partes(pecas)
        escritos = []
        raiz = nome_base[:-3]
        if len(partes) > 1:
            # Se qualquer parte colidir com outro grupo (`index-Vol-1.md` é
            # do grupo `Vol-1`), todas levam o mesmo sufixo: `index-Vol-<hash>-1.md`,
            # `-2.md` — não uma com hash e a outra sem.
            candidatos = [f"{raiz}-{n}.md" for n in range(1, len(partes) + 1)]
            if any(c in usados or c in bases for c in candidatos):
                raiz = f"{raiz}-{hashlib.sha1(group.encode('utf-8')).hexdigest()[:6]}"
        for n, parte in enumerate(partes, start=1):
            if len(partes) == 1:
                nome = _unique_name(nome_base, group, usados)
            else:
                nome = _unique_name(f"{raiz}-{n}.md", group, usados, bases)
            caminho = saida / nome
            corpo = [f"# {t('artifact.index.title')} — {group}", "", *cabecalho, *(linha(p) for p in parte)]
            write_if_changed(caminho, NL.join(corpo) + NL)
            escritos.append((caminho, parte))
        return escritos

    def rotulo(escritos: list[tuple[Path, list]]) -> str:
        if len(escritos) == 1:
            return escritos[0][0].name
        return f"{escritos[0][0].name} … {escritos[-1][0].name}"

    caminhos: list[Path] = []
    usados: set[str] = set()
    ha_atos = False
    for group in sorted(by_group):
        do_grupo = by_group[group]
        # Fase 31: as páginas do Planalto fora do índice (eram 44 dos 46 MB
        # do índice do grupo). Fase 38: só contam no sumário; a lista das
        # normas reconhecidas, com link, é o `normas-citadas.md`.
        acervo = [item for item in do_grupo if not e_legislacao(item)]
        atos = [item for item in do_grupo if e_legislacao(item)]
        do_acervo = escrever(group_index_filename(group), group, acervo) if acervo else []

        arquivos = {
            physical[(group, item["start_order"])][0]
            for item in do_grupo
            if (group, item["start_order"]) in physical
        }
        if atos:
            resumo.append(t(
                "artifact.index.summary_row_split",
                group=group, sheets=faixa(do_grupo), files=len(arquivos),
                documents=len(acervo), acts=len(atos),
                file=rotulo(do_acervo) if do_acervo else "—",
            ))
        else:
            resumo.append(t(
                "artifact.index.summary_row",
                group=group, sheets=faixa(do_grupo), files=len(arquivos), file=rotulo(do_acervo),
            ))
        if len(do_acervo) > 1:
            for caminho, parte in do_acervo:
                resumo.append(t("artifact.index.summary_part_row", file=caminho.name, sheets=faixa(parte)))

        caminhos += [caminho for caminho, _ in do_acervo]
        if atos:
            ha_atos = True

    if ha_atos:
        resumo += ["", t("artifact.index.summary_legislation_note")]

    principal = saida / INDEX_FILENAME
    write_if_changed(principal, NL.join(resumo) + NL)

    # O índice de um grupo que sumiu do acervo não pode ficar para trás: o
    # pacote do Claude leva todo `index-*.md` da pasta, e o Claude acharia
    # peças de documentos que não existem mais. `legislacao-*.md` é o
    # arquivo que a fase 38 aposentou: some na primeira geração seguinte.
    for padrao in ("index-*.md", "legislacao-*.md"):
        for velho in saida.glob(padrao):
            if velho.name not in usados:
                _remove_output(velho)
    return [principal] + caminhos


# --- timeline.md -------------------------------------------------------


def generate_timeline_md(conn, config: ProjectConfig, language: str) -> list[Path]:
    """`timeline.md`, mais um `timeline-<grupo>.md` por grupo grande.

    Fase 31. Num acervo grande, a cronologia tinha mais de cem mil linhas,
    quase todas de um único grupo e quase todas atos do Planalto — o índice
    inteiro reordenado por data, dezenas de MB. Os atos saem e um grupo com mais de
    `config.timeline_split_items` peças datadas ganha
    arquivo próprio, com o `timeline.md` apontando para ele. A coluna
    Origem saiu: o arquivo e a página passam para a Referência.
    """
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    physical = _physical_pages(conn)
    e_legislacao = _legislation_test(conn)
    items = [p for p in _items(conn) if p["date"] and not e_legislacao(p)]
    items.sort(key=lambda p: (p["date"], p["group_key"], p["start_order"]))

    por_grupo: dict[str, int] = {}
    for item in items:
        por_grupo[item["group_key"]] = por_grupo.get(item["group_key"], 0) + 1
    grandes = {g for g, n in por_grupo.items() if n > config.timeline_split_items}

    header = (
        f"| {t('artifact.timeline.table_date')} | {t('artifact.timeline.table_type')} | "
        f"{t('artifact.timeline.table_reference')} | {t('artifact.timeline.table_group')} | "
        f"{t('artifact.timeline.table_summary')} |"
    )

    def linha(item) -> str:
        origem = physical.get((item["group_key"], item["start_order"]))
        referencia = _range_cell(item, origem, with_file=True)
        if not origem and item["files"]:
            # Sem a coluna Origem, a peça fora do mapa de páginas perderia o
            # arquivo — e a regra da fonte original depende dele.
            referencia = f"{referencia} ({item['files']})"
        return "| " + " | ".join(
            _cell(v) for v in (item["date"], item["type"], referencia, item["group_key"], item["summary"])
        ) + " |"

    def documento(titulo: str, pecas: list) -> list[str]:
        lines = [
            f"# {t('artifact.timeline.title')} — {titulo}",
            "",
            t("artifact.timeline.generated", timestamp=_now_iso(), count=len(pecas)),
        ]
        if pecas:
            lines += ["", header, "|---|---|---|---|---|"]
            lines += [linha(item) for item in pecas]
        return lines

    saida = Path(config.output_folder)
    usados: set[str] = set()
    extras: list[Path] = []
    principal_linhas = documento(config.name, [i for i in items if i["group_key"] not in grandes])
    if not items:
        principal_linhas += ["", t("artifact.timeline.empty")]
    for group in sorted(grandes):
        nome = _unique_name(group_timeline_filename(group), group, usados)
        pecas = [i for i in items if i["group_key"] == group]
        caminho = saida / nome
        write_if_changed(caminho, NL.join(documento(group, pecas)) + NL)
        extras.append(caminho)
        principal_linhas.append(t("artifact.timeline.group_split_row", group=group, count=len(pecas), file=nome))

    principal = saida / TIMELINE_FILENAME
    write_if_changed(principal, NL.join(principal_linhas) + NL)

    # Mesma razão da limpeza de `index-*.md`: a cronologia de um grupo que
    # sumiu, ou que voltou a caber no arquivo principal, não pode ficar.
    for velho in saida.glob("timeline-*.md"):
        if velho.name not in usados:
            _remove_output(velho)
    return [principal] + extras


# --- review.md --------------------------------------------------------


def _group_ranges(numbers: list[int]) -> list[tuple[int, int]]:
    numbers = sorted(numbers)
    ranges = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))
    return ranges


def _gaps_by_group(conn) -> dict[str, list[tuple[int, int]]]:
    from .windows_prep import group_page_counts

    # Counted, not loaded — this ran on every refresh of the
    # Execution screen (through `quality_summary`) and read every page's
    # text to learn how many there were.
    counts = group_page_counts(conn, only_extracted_groups=True)

    gaps = {}
    for group, page_count in counts.items():
        page_orders = list(range(1, page_count + 1))
        if not page_orders:
            continue

        items = conn.execute(
            "SELECT start_order, end_order FROM item WHERE group_key = ?", (group,)
        ).fetchall()
        covered: set[int] = set()
        for item in items:
            covered.update(range(item["start_order"], item["end_order"] + 1))

        missing = sorted(set(page_orders) - covered)
        if missing:
            gaps[group] = _group_ranges(missing)

    return gaps


def generate_review_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    file_counts = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM file GROUP BY status").fetchall()
    }
    window_counts = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM window GROUP BY status").fetchall()
    }
    total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    total_low_confidence_items = conn.execute(
        "SELECT COUNT(*) FROM item WHERE confidence = 'low'"
    ).fetchone()[0]

    failures = conn.execute(
        "SELECT name, relative_path, error FROM file WHERE status = 'failed' ORDER BY relative_path"
    ).fetchall()

    removals = conn.execute(
        "SELECT name, relative_path, removed_at FROM removed_file ORDER BY removed_at DESC, name"
    ).fetchall()

    error_events = conn.execute(
        "SELECT step, message, created_at FROM event WHERE level = 'error' ORDER BY id DESC LIMIT 50"
    ).fetchall()

    gaps = _gaps_by_group(conn)

    lines = [
        f"# {t('artifact.review.title')} — {config.name}", "", t("artifact.review.generated", timestamp=_now_iso()),
        "", f"## {t('artifact.review.file_coverage')}",
    ]
    # Statuses are the fixed database/domain codes (`file.status`), not
    # translatable prose — left as-is, same reasoning as the JSON contract
    # keys in `CLAUDE.md` (see `windows_prep.py`).
    # `duplicate` was missing from this list until phase 18, so a file that
    # entered as a copy of one already indexed left no trace in the report:
    # the coverage counts simply did not add up to the collection, and
    # nothing said why. `scanning.py` writes exactly these six values.
    for status in ("discovered", "converted", "extracted", "failed", "duplicate", "skipped"):
        lines.append(f"- {status}: {file_counts.get(status, 0)}")

    lines += ["", f"## {t('artifact.review.windows_section')}"]
    lines.append(f"- {t('artifact.review.windows_pending')}: {window_counts.get('pending', 0)}")
    lines.append(f"- {t('artifact.review.windows_done')}: {window_counts.get('done', 0)}")

    lines += ["", f"## {t('artifact.review.items_section')}"]
    lines.append(f"- {t('artifact.review.items_total')}: {total_items}")
    lines.append(f"- {t('artifact.review.items_low_confidence')}: {total_low_confidence_items}")

    lines += ["", f"## {t('artifact.review.gaps_section')}"]
    if not gaps:
        lines.append(t("artifact.review.gaps_none"))
    else:
        for group in sorted(gaps):
            ranges = ", ".join(
                f"{a}-{b}" if a != b else str(a) for a, b in gaps[group]
            )
            lines.append(f"- **{group}**: {t('artifact.review.gaps_missing')} {ranges}")

    lines += ["", f"## {t('artifact.review.failures_section')}"]
    if not failures:
        lines.append(t("artifact.review.failures_none"))
    else:
        for failure in failures:
            lines.append(f"- `{failure['relative_path']}`: {failure['error']}")

    lines += ["", f"## {t('artifact.review.removed_section')}"]
    if not removals:
        lines.append(t("artifact.review.removed_none"))
    else:
        for removal in removals:
            lines.append(f"- `{removal['relative_path']}` ({removal['removed_at']})")

    lines += ["", f"## {t('artifact.review.errors_section')}"]
    if not error_events:
        lines.append(t("artifact.review.errors_none"))
    else:
        for event in error_events:
            lines.append(f"- [{event['created_at']}] ({event['step']}) {event['message']}")

    path = Path(config.output_folder) / REVIEW_FILENAME
    write_if_changed(path, "\n".join(lines) + "\n")
    return path


# --- project_instructions.md ------------------------------------------------


@dataclass(frozen=True)
class ArtifactNames:
    """Como os arquivos se chamam no texto das instruções: os nomes de
    sempre no projeto simples; prefixados pelo apelido no pacote combinado
    (fase 38), onde `prefix` entra também nos padrões `index-<grupo>.md` e
    `timeline-<grupo>.md` das colunas."""

    index: str = INDEX_FILENAME
    timeline: str = TIMELINE_FILENAME
    review: str = REVIEW_FILENAME
    norms: str = NORMS_FILENAME
    prefix: str = ""


def project_instructions_sections(
    conn, config: ProjectConfig, language: str, names: ArtifactNames = ArtifactNames(), *, common: bool = True,
    default_role: bool = True,
) -> list[str]:
    """As seções das instruções, sem o título, como linhas de Markdown.

    O projeto simples e o pacote combinado dividem este texto. `common=False`
    (uma seção por acervo no combinado) deixa de fora o que vale para o
    Project inteiro e já foi dito uma vez: o papel padrão e a regra
    inegociável. O papel que a pessoa escreveu para aquele projeto continua,
    porque é dele.
    """
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    total_files = conn.execute(
        "SELECT COUNT(*) FROM file WHERE status IN ('converted', 'extracted')"
    ).fetchone()[0]

    role = config.role_instructions.strip()
    extra_rules = config.extra_rules.strip() or t("artifact.project_instructions.extra_rules_missing")

    lines: list[str] = []
    # `default_role=False`: the user's own instructions already say
    # who Claude is; only a role written in the form is repeated here.
    if role or (common and default_role):
        lines += [f"## {t('artifact.project_instructions.role_section')}", "", role or DEFAULT_ROLE, ""]
    lines += [
        f"## {t('artifact.project_instructions.about_section')}",
        "",
        config.subject.strip() or t("artifact.project_instructions.subject_missing"),
        "",
        t(
            "artifact.project_instructions.access_line",
            index_file=names.index, timeline_file=names.timeline, review_file=names.review,
            total_items=total_items, total_files=total_files,
        ),
        "",
    ]
    if common:
        lines += [f"## {t('artifact.project_instructions.rule_section')}", "", SOURCE_OF_TRUTH_RULE, ""]
    lines += [
        f"## {t('artifact.project_instructions.locate_section')}",
        "",
        "1. " + t("artifact.project_instructions.locate_step1", index_file=names.index, timeline_file=names.timeline),
        "2. " + t("artifact.project_instructions.locate_step2"),
        "3. " + t("artifact.project_instructions.locate_step3"),
        "4. " + t("artifact.project_instructions.locate_step4"),
        "",
    ]

    # Only for collections that have struck text (HTML/DOCX with `~~`): a
    # collection of PDFs keeps the instructions it always had.
    # Only the pages of files that can carry the mark. In a PDF
    # collection the old query read the text of every page to find none.
    from .file_types import EXTENSION_CATEGORIES

    no_struck = sorted(
        ext.lstrip(".") for ext in EXTENSION_CATEGORIES["pdf"] | EXTENSION_CATEGORIES["imagens"]
    )
    placeholders = ", ".join("?" for _ in no_struck)
    has_struck_text = conn.execute(
        f"""
        SELECT 1 FROM page JOIN file ON file.id = page.file_id
        WHERE lower(file.extension) NOT IN ({placeholders}) AND instr(page.text, ?) > 0
        LIMIT 1
        """,
        (*no_struck, STRUCK_MARK),
    ).fetchone()
    if has_struck_text:
        lines += [t("artifact.project_instructions.struck_text_rule"), ""]

    # Fase 31: a legislação do Planalto fica fora do pacote. Sem esta regra
    # o Claude procuraria no conhecimento do Projeto uma lei que não subiu e
    # responderia que o acervo não a tem. Fase 38: a regra aponta para
    # `normas-citadas.md` e para a busca por tema.
    atos = _legislation_count(conn)
    if atos:
        lines += [t("artifact.project_instructions.legislation_rule", count=atos, norms=names.norms), ""]

    # Fase 31: as colunas como ficaram — `(p. N)` sem arquivo é a página do
    # arquivo da coluna Origem; Confiança só quando aparece. Depois das
    # regras acima, para nenhuma delas cair sob este título.
    lines += [
        f"## {t('artifact.project_instructions.columns_section')}",
        "",
        t(
            "artifact.project_instructions.columns_index_confidence"
            if _show_confidence(conn, config) else "artifact.project_instructions.columns_index",
            prefix=names.prefix,
        ),
        "",
        t("artifact.project_instructions.columns_timeline", prefix=names.prefix),
        "",
    ]

    lines += [
        f"## {t('artifact.project_instructions.extra_rules_section')}",
        "",
        extra_rules,
    ]
    return lines


def _is_legacy_text(text: str) -> bool:
    """A file from before the marks, written whole by the program.

    It used to be enough for the file to carry the non-negotiable
    rule. A person who copied that rule into their own instructions by
    hand, in a file with no marks yet, would have had all of their text
    taken for ours and replaced (a `.bak` kept it, but still). Now every
    section of the file has to be one the program writes."""
    from .instructions_dedup import is_only_generated

    return SOURCE_OF_TRUTH_RULE in text and is_only_generated(text)


def _is_legacy_file(path: Path) -> bool:
    from .managed_block import has_managed_block

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return not has_managed_block(text) and _is_legacy_text(text)


def _duplicate_notice(conn, config: ProjectConfig, own: str, language: str) -> list[str]:
    from .instructions_dedup import detect

    report = detect(own, config.subject)
    if not report.has_findings:
        return []
    titles = report.copy_titles()
    if titles:
        notice = translate(
            language, "artifact.project_instructions.duplicate_notice", sections="; ".join(titles),
        )
    else:
        notice = translate(
            language, "artifact.project_instructions.duplicate_numbers_notice", count=len(report.volatile_lines),
        )
    record_event(
        conn, "instructions", "warning", "log.instructions.duplicates",
        {"count": len(titles), "sections": "; ".join(titles) or "-", "numbers": len(report.volatile_lines)},
        language=language,
    )
    return [f"> {notice}", ""]


def generate_project_instructions_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
    own = user_part(path) or config.existing_instructions.strip()
    if own and not (path.exists() and _is_legacy_file(path)):
        # The user has instructions of their own. The generated text
        # used to be a second complete set below them — its own title and a
        # generic "Role" contradicting the user's (a project could end up
        # with both: a long text of theirs, then "you are a research
        # assistant"). Now it
        # is one section of their document: the collection's facts, one
        # heading level down, and no role unless they wrote one in the form.
        sections = project_instructions_sections(conn, config, language, default_role=False)
        lines = [
            f"## {t('artifact.project_instructions.collection_title')}: {config.name}",
            "",
        ]
        # The user's part repeating this block. Their text is never
        # changed here (this runs in the background, with nobody to ask):
        # a notice at the top of the block and in the log, and the
        # Instructions screen offers the clean-up.
        lines += _duplicate_notice(conn, config, own, language)
        lines += [
            t("artifact.project_instructions.collection_intro"),
            "",
        ]
        lines += ["#" + line if line.startswith("## ") else line for line in sections]
    else:
        lines = [f"# {t('artifact.project_instructions.title')}: {config.name}", ""]
        lines += project_instructions_sections(conn, config, language)

    # Complementa, não substitui: o que o usuário escreveu fora do bloco — e
    # as instruções que ele já usava, coladas no formulário — atravessam
    # cada regeneração. Um arquivo de versão anterior às marcas traz a regra
    # da fonte original (sempre em português) e é inteiramente nosso.
    before = path.read_bytes() if path.exists() else None
    write_managed(
        path,
        "\n".join(lines),
        is_legacy=_is_legacy_text,
        user_text=config.existing_instructions,
    )
    changed = _changed_files.get()
    if changed is not None and path.read_bytes() != before:
        changed.append(path)
    return path


def pending_items(conn) -> dict:
    """Summary of what is still missing, for the Result screen (spec section 6)."""
    failures = conn.execute(
        "SELECT name, relative_path, error FROM file WHERE status = 'failed' ORDER BY relative_path"
    ).fetchall()
    windows_pending = conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0]
    return {
        "gaps": _gaps_by_group(conn),
        "failures": [dict(failure) for failure in failures],
        "windows_pending": windows_pending,
    }


# --- are the four files still current? --------------------------------------


@dataclass(frozen=True)
class ArtifactState:
    """What the four generated files describe, in three numbers."""

    files: int
    windows_done: int
    items: int


@dataclass(frozen=True)
class ArtifactStaleness:
    """The gap between what the files say and what the project holds."""

    recorded: ArtifactState
    current: ArtifactState
    generated_at: str


def current_artifact_state(conn: sqlite3.Connection) -> ArtifactState:
    """The state a generation run right now would describe."""
    return ArtifactState(
        files=conn.execute("SELECT COUNT(*) FROM file").fetchone()[0],
        windows_done=conn.execute(
            "SELECT COUNT(*) FROM window WHERE status = 'done'"
        ).fetchone()[0],
        items=conn.execute("SELECT COUNT(*) FROM item").fetchone()[0],
    )


def record_artifact_state(conn: sqlite3.Connection) -> ArtifactState:
    """Stores what the files just written describe. One row, replaced."""
    state = current_artifact_state(conn)
    conn.execute(
        "INSERT INTO artifact_state (id, generated_at, files, windows_done, items)"
        " VALUES (1, ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET generated_at = excluded.generated_at,"
        " files = excluded.files, windows_done = excluded.windows_done,"
        " items = excluded.items",
        (_now_iso(), state.files, state.windows_done, state.items),
    )
    conn.commit()
    return state


def stale_artifacts(conn: sqlite3.Connection) -> ArtifactStaleness | None:
    """The four files against the project as it stands, or `None` when they
    agree — and also `None` when there is nothing to compare against.

    A project from before phase 18 carries no recorded state. Reporting it
    as out of date would be a guess dressed as a fact, and a warning that
    cries wolf is worse than no warning: the first generation on this
    version records the state, and every one after it is checked.
    """
    recorded = conn.execute(
        "SELECT generated_at, files, windows_done, items FROM artifact_state WHERE id = 1"
    ).fetchone()
    if recorded is None:
        return None

    was = ArtifactState(
        files=recorded["files"],
        windows_done=recorded["windows_done"],
        items=recorded["items"],
    )
    now = current_artifact_state(conn)
    if was == now:
        return None

    return ArtifactStaleness(recorded=was, current=now, generated_at=recorded["generated_at"])


def generate_all_artifacts(
    conn, config: ProjectConfig, language: str, should_stop=None
) -> dict[str, Path]:
    """`should_stop` is checked between one output file and the
    next: a stop leaves every file either as it was or fully rewritten, and
    the log still lists the ones already rewritten, so the person knows
    what to send to the Claude Project."""
    changed: list[Path] = []
    removed: list[str] = []
    token = _changed_files.set(changed)
    removed_token = _removed_files.set(removed)
    cancelled = False
    written: dict[str, Path] = {}
    try:
        written = _generate_all(conn, config, language, should_stop)
    except OperationCancelled:
        cancelled = True
    finally:
        _changed_files.reset(token)
        _removed_files.reset(removed_token)
    # Which files this generation actually changed — the ones to send
    # to the Claude Project again. The others are byte for byte what was
    # already there.
    if changed:
        record_event(
            conn, "import", "info", "log.artifacts.changed",
            {"count": len(changed), "files": ", ".join(sorted(p.name for p in changed))},
            language=language,
        )
    if removed:
        record_event(
            conn, "import", "info", "log.artifacts.removed",
            {"count": len(removed), "files": ", ".join(sorted(removed))},
            language=language,
        )
    if cancelled:
        raise OperationCancelled()
    if not changed and not removed:
        record_event(conn, "import", "info", "log.artifacts.unchanged", {}, language=language)
    return written


def _generate_all(conn, config: ProjectConfig, language: str, should_stop=None) -> dict[str, Path]:
    checkpoint(should_stop)
    indices = generate_index_md(conn, config, language)
    checkpoint(should_stop)
    timelines = generate_timeline_md(conn, config, language)
    checkpoint(should_stop)
    written = {
        "index": indices[0],
        "timeline": timelines[0],
        "review": generate_review_md(conn, config, language),
        "project_instructions": generate_project_instructions_md(conn, config, language),
    }
    checkpoint(should_stop)
    normas = generate_cited_norms_md(conn, config, language)
    if normas:
        written["norms"] = normas
    written["search_launcher"] = generate_search_launcher(config)
    for extra in indices[1:]:
        written[f"index:{extra.stem}"] = extra
    for extra in timelines[1:]:
        written[f"timeline:{extra.stem}"] = extra
    # Last, and only on success: a state recorded for files that failed to
    # be written would claim they describe something they do not.
    record_artifact_state(conn)
    return written

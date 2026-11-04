# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""O pacote combinado de um conjunto: vários acervos num Project (fase 38).

Cada projeto continua gerando `index.md`, `index-<grupo>.md`, `timeline.md`,
`review.md`, `normas-citadas.md` e `project_instructions.md` na própria
pasta de saída, com os nomes de sempre. Dois deles no mesmo Project
colidiriam em todos esses nomes, e cada `project_instructions.md` foi
escrito para ser **as** instruções do Project.

O prefixo entra só aqui, no empacotamento: `atas__index.md`,
`atas__index-Atas.md`... (`prefixed_name`), com os links do sumário e da
cronologia reescritos para os nomes prefixados (`rewrite_links`). Em vez
dos `project_instructions.md` de cada projeto vai um só: o texto pessoal da
pessoa fora das marcas, e dentro delas papel e regra de fonte de verdade uma
vez, uma seção por acervo e a seção "Em qual acervo procurar". As pastas de
saída não mudam, porque Projects, `CLAUDE.md` e links já existentes
continuam valendo, e porque o apelido é do conjunto, não do projeto.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from .artifacts import (
    INDEX_FILENAME,
    NORMS_FILENAME,
    PROJECT_INSTRUCTIONS_FILENAME,
    REVIEW_FILENAME,
    SOURCE_OF_TRUTH_RULE,
    TIMELINE_FILENAME,
    ArtifactNames,
    project_instructions_sections,
)
from .catalog import CatalogEntry, find_project
from .claude_package import GUIDE_FILENAME, RAG_THRESHOLD_TOKENS, BudgetEntry, budget, candidate_files, package_plan
from .config import ConfigError, ProjectConfig
from .i18n import DEFAULT_LANGUAGE, translate
from .managed_block import merge_managed
from .project import load_project
from .sets import SetEntry, SetMember
from .windows_prep import CLAUDE_MD_FILENAME

# Os únicos arquivos gerados que citam outros arquivos gerados: o sumário
# aponta para `index-<grupo>.md` (e partes) e para `normas-citadas.md`; a
# cronologia aponta para `timeline-<grupo>.md`. Os índices de grupo e a
# conferência não citam ninguém, e um índice de grupo pode ter 25 MB:
# reescrever só quem precisa evita ler tudo a cada download.
_LINKED_FILES = frozenset({INDEX_FILENAME, TIMELINE_FILENAME})


@dataclass
class Member:
    """Um membro do conjunto como está nesta máquina, agora."""

    member: SetMember
    catalog: CatalogEntry | None
    config: ProjectConfig | None
    available: bool
    reason: str = ""

    @property
    def alias(self) -> str:
        return self.member.alias

    @property
    def name(self) -> str:
        if self.catalog is not None:
            return self.catalog.name
        return f"#{self.member.project_id}"


@dataclass
class CombinedFile:
    member: Member
    source: Path
    arcname: str
    # Bytes já reescritos (links prefixados); `None` copia o arquivo como está.
    content: bytes | None = None

    def read(self) -> bytes:
        return self.content if self.content is not None else self.source.read_bytes()


@dataclass
class CombinedPlan:
    files: list[CombinedFile]
    excluded: list[BudgetEntry]
    total_tokens: int
    level: str
    unavailable: list[Member]
    limit_tokens: int
    members: list[Member] = field(default_factory=list)
    # Um `BudgetEntry` por arquivo incluído, já com o nome prefixado: a
    # tela do conjunto mostra a mesma tabela da tela Resultado.
    entries: list[BudgetEntry] = field(default_factory=list)

    @property
    def included_members(self) -> list[Member]:
        return [m for m in self.members if m.available]


def prefixed_name(alias: str, name: str) -> str:
    return f"{alias}__{name}"


def rewrite_links(text: str, names: dict[str, str]) -> str:
    """Troca `nome.md` entre crases e `](nome.md)` pelos nomes de `names`.

    Só o nome exato, delimitado: `index-Atas.md.bak`, `meu-index-Atas.md` e
    o nome solto no texto ficam como estão. O sumário cita os índices de
    grupo entre crases e o manual pode citá-los como link; os dois casos
    bastam, e um `replace` cru tocaria em texto que só se parece com um
    nome de arquivo (Review Focus 4 da fase 38).

    Dentro de uma crase cada palavra conta: o índice em partes é citado como
    `index-G-1.md … index-G-3.md` num único par de crases, e a revisão da
    fase 38 achou o sumário combinado apontando para nomes sem
    prefixo exatamente nos acervos grandes que motivaram a fase.
    """
    if not names:
        return text

    def dentro_da_crase(m: re.Match) -> str:
        partes = re.split(r"(\s+)", m.group(1))
        return "`" + "".join(names.get(p, p) for p in partes) + "`"

    alternativas = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    text = re.sub(r"`([^`\n]+)`", dentro_da_crase, text)
    return re.sub(rf"\]\(({alternativas})\)", lambda m: f"]({names[m.group(1)]})", text)


def load_members(entry: SetEntry, language: str = DEFAULT_LANGUAGE) -> list[Member]:
    """Cada membro com a sua configuração, ou com o motivo de não entrar:
    fora do catálogo, pasta fora do ar (Drive de outro computador), banco
    que não abre, relatórios nunca gerados. Um membro com problema nunca
    derruba o conjunto: a tela mostra o motivo e o pacote sai sem ele."""
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    members: list[Member] = []
    for member in entry.members:
        catalog = find_project(member.project_id)
        if catalog is None:
            members.append(Member(member, None, None, False, t("combined.reason_removed")))
            continue
        folder = Path(catalog.output_folder)
        if not folder.is_dir():
            members.append(Member(member, catalog, None, False, t("combined.reason_unavailable", folder=str(folder))))
            continue
        try:
            config, conn = load_project(folder)
        except ConfigError as exc:
            detail = "; ".join(t(e.key, **e.params) for e in exc.errors)
            members.append(Member(member, catalog, None, False, t("combined.reason_unreadable", detail=detail)))
            continue
        except (sqlite3.Error, ValueError, OSError) as exc:
            members.append(Member(member, catalog, None, False, t("combined.reason_unreadable", detail=str(exc))))
            continue
        conn.close()
        # A pasta vale pelo catálogo, que já resolveu a letra do drive desta
        # máquina; o `config_json` guarda o caminho de quando o projeto foi
        # criado, talvez noutro computador.
        config = replace(config, output_folder=str(folder))
        if not (folder / INDEX_FILENAME).exists():
            members.append(Member(member, catalog, config, False, t("combined.reason_no_artifacts")))
            continue
        members.append(Member(member, catalog, config, True))
    return members


def _rename_map(member: Member) -> dict[str, str]:
    """Todo nome que o pacote simples levaria, prefixado. Inclui os que
    ficaram fora por tamanho: o link do sumário continua apontando para o
    nome que o arquivo teria, e a tela diz que ele ficou de fora."""
    assert member.config is not None
    return {
        path.name: prefixed_name(member.alias, path.name)
        for path in candidate_files(member.config) if path.name != PROJECT_INSTRUCTIONS_FILENAME
    }


def _default_limit() -> int:
    return ProjectConfig.__dataclass_fields__["package_token_limit"].default


def plan(entry: SetEntry, language: str = DEFAULT_LANGUAGE) -> CombinedPlan:
    """O que o ZIP combinado leva, com o orçamento somado. O limite é o
    menor entre os projetos: todos vão para o mesmo Project, e o mais
    conservador é o que a pessoa ajustou para caber."""
    members = load_members(entry, language)
    files: list[CombinedFile] = []
    excluded: list[BudgetEntry] = []
    entries: list[BudgetEntry] = []
    total = 0
    limits: list[int] = []
    for member in members:
        if not member.available or member.config is None:
            continue
        names = _rename_map(member)
        member_plan = package_plan(member.config)
        for path in member_plan.included:
            if path.name == PROJECT_INSTRUCTIONS_FILENAME:
                continue
            content = None
            if path.name in _LINKED_FILES:
                content = rewrite_links(path.read_text(encoding="utf-8"), names).encode("utf-8")
            files.append(CombinedFile(member, path, names[path.name], content))
        entries += [
            replace(e, name=prefixed_name(member.alias, e.name))
            for e in budget(member.config).entries if e.name != PROJECT_INSTRUCTIONS_FILENAME
        ]
        excluded += [replace(e, name=prefixed_name(member.alias, e.name)) for e in member_plan.excluded]
        limits.append(member.config.package_token_limit)
    total = sum(e.tokens for e in entries)
    limit = min(limits) if limits else _default_limit()
    if total > limit:
        level = "over"
    elif total > RAG_THRESHOLD_TOKENS:
        level = "rag"
    else:
        level = "ok"
    return CombinedPlan(
        files=files, excluded=excluded, total_tokens=total, level=level,
        unavailable=[m for m in members if not m.available], limit_tokens=limit, members=members,
        entries=entries,
    )


def _names_for(member: Member) -> ArtifactNames:
    alias = member.alias
    return ArtifactNames(
        index=prefixed_name(alias, INDEX_FILENAME),
        timeline=prefixed_name(alias, TIMELINE_FILENAME),
        review=prefixed_name(alias, REVIEW_FILENAME),
        norms=prefixed_name(alias, NORMS_FILENAME),
        prefix=f"{alias}__",
    )


def _where_section(members: list[Member], language: str) -> list[str]:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    lines = [f"## {t('combined.where_section')}", "", t("combined.where_text"), ""]
    for member in members:
        subject = (member.config.subject.strip() if member.config else "") or t("artifact.project_instructions.subject_missing")
        lines.append(t("combined.where_item", alias=member.alias, name=member.name, subject=subject))
    lines.append("")
    return lines


def generate_instructions(
    entry: SetEntry, members: list[Member], language: str, existing: str | None = None,
) -> str:
    """O `project_instructions.md` único do conjunto. O texto pessoal fica
    fora das marcas e só é semeado quando ainda não há nada fora delas
    (`merge_managed`): num arquivo já gravado na pasta, o que a pessoa
    escreveu ali é a verdade e atravessa a regeneração."""
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    available = [m for m in members if m.available and m.config is not None]
    lines = [
        f"# {t('combined.title', name=entry.name)}",
        "",
        f"## {t('artifact.project_instructions.role_section')}",
        "",
        t("combined.role", count=len(available)),
        "",
        f"## {t('artifact.project_instructions.rule_section')}",
        "",
        SOURCE_OF_TRUTH_RULE,
        "",
    ]
    lines += _where_section(available, language)
    for member in available:
        lines += [f"## {t('combined.collection_section', alias=member.alias, name=member.name)}", ""]
        config, conn = load_project(Path(member.config.output_folder))
        try:
            config = replace(config, output_folder=member.config.output_folder)
            sections = project_instructions_sections(conn, config, language, _names_for(member), common=False)
        finally:
            conn.close()
        # Um nível abaixo: o título do acervo é o `##`.
        lines += [("#" + line) if line.startswith("## ") else line for line in sections]
        lines.append("")
    return merge_managed(existing, "\n".join(lines), user_text=entry.personal_instructions)


def _guide(entry: SetEntry, combined: CombinedPlan, language: str) -> str:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    collections = "\n".join(
        t("combined.guide_collection", alias=m.alias, name=m.name) for m in combined.included_members
    )
    if combined.unavailable:
        left_out = "\n".join(
            t("combined.guide_left_out_item", alias=m.alias, name=m.name, reason=m.reason) for m in combined.unavailable
        )
    else:
        left_out = t("combined.guide_all_present")
    template = _GUIDE.get(language, _GUIDE[DEFAULT_LANGUAGE])
    return template.format(name=entry.name, collections=collections, left_out=left_out)


def generate_zip(entry: SetEntry, language: str = DEFAULT_LANGUAGE) -> bytes:
    """O `.zip` combinado, em memória: guia, arquivos prefixados e o
    `project_instructions.md` único."""
    combined = plan(entry, language)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(GUIDE_FILENAME, _guide(entry, combined, language))
        for item in combined.files:
            zip_file.writestr(item.arcname, item.read())
        zip_file.writestr(
            PROJECT_INSTRUCTIONS_FILENAME, generate_instructions(entry, combined.members, language),
        )
    return buffer.getvalue()


def _claude_md(entry: SetEntry, combined: CombinedPlan, language: str) -> str:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    collections = []
    for m in combined.included_members:
        assert m.config is not None
        subject = m.config.subject.strip() or t("artifact.project_instructions.subject_missing")
        collections.append(_CLAUDE_MD_COLLECTION.get(language, _CLAUDE_MD_COLLECTION[DEFAULT_LANGUAGE]).format(
            alias=m.alias, name=m.name, subject=subject, output_folder=m.config.output_folder,
        ))
    template = _CLAUDE_MD.get(language, _CLAUDE_MD[DEFAULT_LANGUAGE])
    return template.format(
        name=entry.name, collections="\n".join(collections), where=t("combined.where_text"), rule=SOURCE_OF_TRUTH_RULE,
    )


class ProtectedFolderError(ValueError):
    """O destino é a pasta de um acervo (saída ou origem)."""


# Só o que a gravação combinada produz leva `__` no nome; a geração simples
# nunca usa esse separador, então apagar por estes padrões não alcança
# arquivo de ninguém.
_STALE_PATTERNS = ("*__index*.md", "*__timeline*.md", "*__review.md", "*__normas-citadas.md")


def _is_protected_folder(folder: Path, members: list[Member]) -> bool:
    """Pasta de saída de qualquer projeto (tem `project.db`) ou pasta de
    origem/saída de um membro do conjunto. Gravar ali trocaria o
    `CLAUDE.md` e as instruções do projeto pelos combinados e deixaria
    índices prefixados onde a limpeza do projeto não os alcança (revisão da
    fase 38); numa pasta de origem, os `.md` seriam indexados
    na próxima varredura."""
    try:
        destino = folder.resolve()
    except OSError:
        destino = folder
    if (destino / "project.db").exists():
        return True
    protegidas = set()
    for member in members:
        protegidas.add(Path(member.catalog.output_folder) if member.catalog else None)
        if member.config is not None:
            protegidas.add(Path(member.config.output_folder))
            protegidas.add(Path(member.config.source_folder))
    for pasta in protegidas:
        if pasta is None or not str(pasta):
            continue
        try:
            if pasta.resolve() == destino:
                return True
        except OSError:
            continue
    return False


def _remove_stale(folder: Path, keep: set[str]) -> None:
    """Apelido trocado, membro retirado, grupo renomeado ou índice que
    deixou de ter partes: o nome antigo some, como a geração simples apaga
    os `index-*.md` órfãos. Sem isso o Claude Code lia índices fantasmas."""
    for pattern in _STALE_PATTERNS:
        for path in folder.glob(pattern):
            if path.name not in keep and path.is_file():
                path.unlink()


def write_folder(entry: SetEntry, folder: Path, language: str = DEFAULT_LANGUAGE) -> list[Path]:
    """Os mesmos arquivos do ZIP numa pasta, mais um `CLAUDE.md` combinado
    para o Claude Code trabalhar sobre vários acervos. Instruções e
    `CLAUDE.md` passam pelas marcas: o que a pessoa escreveu fora delas
    fica. Levanta `ProtectedFolderError` para a pasta de um acervo."""
    folder = Path(folder)
    combined = plan(entry, language)
    if _is_protected_folder(folder, combined.members):
        raise ProtectedFolderError(str(folder))
    folder.mkdir(parents=True, exist_ok=True)
    _remove_stale(folder, {item.arcname for item in combined.files})
    written: list[Path] = []

    guide = folder / GUIDE_FILENAME
    guide.write_text(_guide(entry, combined, language), encoding="utf-8")
    written.append(guide)
    for item in combined.files:
        destination = folder / item.arcname
        destination.write_bytes(item.read())
        written.append(destination)

    instructions = folder / PROJECT_INSTRUCTIONS_FILENAME
    existing = instructions.read_text(encoding="utf-8") if instructions.exists() else None
    instructions.write_text(generate_instructions(entry, combined.members, language, existing), encoding="utf-8")
    written.append(instructions)

    claude_md = folder / CLAUDE_MD_FILENAME
    existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else None
    claude_md.write_text(merge_managed(existing, _claude_md(entry, combined, language)), encoding="utf-8")
    written.append(claude_md)
    return written


# Um guia inteiro por idioma, como o `_GUIDE` de `claude_package.py`: prosa
# longa com estrutura própria, não chaves soltas de i18n.
_GUIDE: dict[str, str] = {
    "pt": """\
# Como configurar vários acervos num Claude Project

Este pacote reúne os arquivos gerados pelo GClaude Indexer para o conjunto
"{name}". Cada acervo entra com um apelido, e todo arquivo dele começa por
esse apelido seguido de dois sublinhados: `atas__index.md` é o sumário do
acervo "atas", `atas__index-<grupo>.md` o índice de um grupo dele, e assim
por diante. Os acervos nunca se misturam, e o Claude sabe de qual veio cada
informação.

## Acervos neste pacote

{collections}

## Acervos que ficaram fora

{left_out}

## Passo a passo

1. Em claude.ai, crie um Project novo (ou abra o que você já usa para esses
   acervos).
2. Abra `project_instructions.md` deste pacote e cole o arquivo inteiro no
   campo "Project instructions". O texto que você escreveu em "Instruções
   que você já usa no Project" já está no topo; o trecho entre as marcas
   `GCLAUDE-INDEXER` é o único que o programa refaz quando você gera o
   pacote de novo.
3. Em "Project knowledge", envie todos os arquivos `.md` deste pacote. Se o
   Project já tinha os arquivos de uma versão anterior, substitua os de
   mesmo nome.
4. Mantenha as pastas de origem de cada acervo acessíveis: o índice e a
   cronologia servem para achar a peça, e qualquer valor, data ou conteúdo
   de tabela citado numa resposta precisa ser confirmado no arquivo
   original.

## Arquivos que ficaram fora por tamanho

Um Project aceita até 30 MB por arquivo. Um índice acima disso fica fora
deste pacote; a tela do conjunto o lista em vermelho. Gere os relatórios
daquele acervo de novo para o índice sair em partes menores.

## Se um acervo crescer ou mudar

Gere os relatórios daquele acervo na tela "Resultado" dele, volte à tela do
conjunto e baixe este pacote de novo. Só os arquivos daquele acervo mudam;
o seu texto pessoal nas instruções continua no lugar.
""",
    "en": """\
# How to set up several collections in one Claude Project

This package gathers the files GClaude Indexer generated for the set
"{name}". Each collection comes in under an alias, and every file of that
collection starts with the alias followed by two underscores:
`minutes__index.md` is the summary of the "minutes" collection,
`minutes__index-<group>.md` the index of one of its groups, and so on.
Collections never mix, and Claude knows which one each piece of
information came from.

## Collections in this package

{collections}

## Collections left out

{left_out}

## Step by step

1. In claude.ai, create a new Project (or open the one you already use for
   these collections).
2. Open `project_instructions.md` in this package and paste the whole file
   into the "Project instructions" field. The text you wrote under
   "Instructions you already use in the Project" is already at the top;
   the part between the `GCLAUDE-INDEXER` marks is the only one the program
   rewrites when you generate the package again.
3. Under "Project knowledge", upload every `.md` file in this package. If
   the Project already had the files from an earlier version, replace the
   ones with the same name.
4. Keep each collection's source folder reachable: the index and the
   timeline find the item, and any value, date or table content quoted in
   an answer must be confirmed in the original file.

## Files left out for size

A Project accepts up to 30 MB per file. An index above that stays out of
this package; the set's screen lists it in red. Generate that collection's
reports again so the index comes out in smaller parts.

## If a collection grows or changes

Generate that collection's reports on its "Result" screen, go back to the
set's screen and download this package again. Only that collection's files
change; your personal text in the instructions stays where it is.
""",
    "es": """\
# Cómo configurar varias colecciones en un Claude Project

Este paquete reúne los archivos que GClaude Indexer generó para el conjunto
"{name}". Cada colección entra con un alias, y todo archivo suyo empieza
por ese alias seguido de dos guiones bajos: `actas__index.md` es el sumario
de la colección "actas", `actas__index-<grupo>.md` el índice de uno de sus
grupos, y así sucesivamente. Las colecciones nunca se mezclan, y Claude
sabe de cuál vino cada información.

## Colecciones en este paquete

{collections}

## Colecciones que quedaron fuera

{left_out}

## Paso a paso

1. En claude.ai, cree un Project nuevo (o abra el que ya usa para estas
   colecciones).
2. Abra `project_instructions.md` de este paquete y pegue el archivo entero
   en el campo "Project instructions". El texto que escribió en
   "Instrucciones que ya usa en el Project" ya está arriba; el tramo entre
   las marcas `GCLAUDE-INDEXER` es el único que el programa rehace cuando
   genera el paquete de nuevo.
3. En "Project knowledge", suba todos los archivos `.md` de este paquete.
   Si el Project ya tenía los archivos de una versión anterior, reemplace
   los del mismo nombre.
4. Mantenga accesibles las carpetas de origen de cada colección: el índice
   y la cronología sirven para encontrar la pieza, y cualquier valor, fecha
   o contenido de tabla citado en una respuesta debe confirmarse en el
   archivo original.

## Archivos que quedaron fuera por tamaño

Un Project acepta hasta 30 MB por archivo. Un índice mayor queda fuera de
este paquete; la pantalla del conjunto lo lista en rojo. Genere de nuevo
los informes de esa colección para que el índice salga en partes menores.

## Si una colección crece o cambia

Genere los informes de esa colección en su pantalla "Resultado", vuelva a
la pantalla del conjunto y descargue este paquete de nuevo. Solo cambian
los archivos de esa colección; su texto personal en las instrucciones sigue
en su lugar.
""",
}

# O `CLAUDE.md` da pasta combinada não é o de `windows_prep`: aquele é o
# contrato de classificação do motor `claude_code` sobre `windows/`; este
# diz ao Claude Code onde está cada acervo, com que prefixo, e onde fica o
# `buscar.bat` de cada um (a busca por tema continua na pasta de saída de
# cada projeto, que tem o banco).
_CLAUDE_MD: dict[str, str] = {
    "pt": """\
# Vários acervos do GClaude Indexer: {name}

Esta pasta reúne os relatórios de mais de um acervo. Os arquivos de cada
acervo começam pelo apelido dele e dois sublinhados (`<apelido>__index.md`,
`<apelido>__index-<grupo>.md`, `<apelido>__timeline.md`,
`<apelido>__review.md`, `<apelido>__normas-citadas.md` quando há normas).

## Em qual acervo procurar

{where}

{collections}
## Regra inegociável

{rule}
""",
    "en": """\
# Several GClaude Indexer collections: {name}

This folder gathers the reports of more than one collection. Each
collection's files start with its alias and two underscores
(`<alias>__index.md`, `<alias>__index-<group>.md`, `<alias>__timeline.md`,
`<alias>__review.md`, `<alias>__normas-citadas.md` when there are norms).

## Which collection to search

{where}

{collections}
## Non-negotiable rule

{rule}
""",
    "es": """\
# Varias colecciones de GClaude Indexer: {name}

Esta carpeta reúne los informes de más de una colección. Los archivos de
cada colección empiezan por su alias y dos guiones bajos
(`<alias>__index.md`, `<alias>__index-<grupo>.md`, `<alias>__timeline.md`,
`<alias>__review.md`, `<alias>__normas-citadas.md` cuando hay normas).

## En qué colección buscar

{where}

{collections}
## Regla innegociable

{rule}
""",
}

_CLAUDE_MD_COLLECTION: dict[str, str] = {
    "pt": """\
## Acervo {alias}: {name}

{subject}

Sumário: `{alias}__index.md`. Cronologia: `{alias}__timeline.md`. Conferência:
`{alias}__review.md`. Para achar onde um assunto aparece neste acervo, rode
o `buscar.bat` da pasta de saída dele: `{output_folder}`.
""",
    "en": """\
## Collection {alias}: {name}

{subject}

Summary: `{alias}__index.md`. Timeline: `{alias}__timeline.md`. Coverage:
`{alias}__review.md`. To find where a subject appears in this collection,
run the `buscar.bat` in its output folder: `{output_folder}`.
""",
    "es": """\
## Colección {alias}: {name}

{subject}

Sumario: `{alias}__index.md`. Cronología: `{alias}__timeline.md`. Revisión:
`{alias}__review.md`. Para encontrar dónde aparece un tema en esta
colección, ejecute el `buscar.bat` de su carpeta de salida: `{output_folder}`.
""",
}

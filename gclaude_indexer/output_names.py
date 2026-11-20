"""Os nomes dos arquivos que o sistema grava na pasta de saída.

Módulo de base (só depende de `paths`, que não importa nada do pacote): quem gera (`artifacts`), quem
empacota (`claude_package`, `combined_package`), quem apaga e quem leva a
pasta (`deletion`, `relocation`), o detector de cópia das instruções
(`instructions_dedup`) e a tela leem daqui. Os nomes são fixos, em inglês,
independentes do idioma da interface: um nome que mudasse com o idioma
quebraria qualquer link ou script que aponte para ele.

Nomes de arquivo gravados são contrato (projetos antigos, o Claude Project
de quem já enviou os arquivos): mudar um daqui muda o que existe em disco.
"""

from __future__ import annotations

# `PROJECT_DB_NAME` fica em `paths`, não aqui: `paths.py` é copiado sozinho
# para o leitor elevado de sensores (`sensor_service.HELPER_MODULES`) e não
# pode passar a importar outro módulo do pacote.
from .paths import PROJECT_DB_NAME

# Os arquivos auxiliares que o SQLite cria ao lado do banco.
_JOURNAL_SUFFIX = "-journal"
SQLITE_SIDECAR_SUFFIXES = (_JOURNAL_SUFFIX, "-wal", "-shm")
PROJECT_DB_SIDECARS = tuple(f"{PROJECT_DB_NAME}{suffix}" for suffix in SQLITE_SIDECAR_SUFFIXES)
# O journal do modo TRUNCATE (`db.connect`): fica com zero bytes depois de
# cada commit, e a mudança de pasta lê o tamanho dele como "banco ocupado".
PROJECT_DB_JOURNAL = f"{PROJECT_DB_NAME}{_JOURNAL_SUFFIX}"

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
# 2.0.0: o `CLAUDE.md` da pasta de saída só orienta a consulta (ler o
# índice, usar o `buscar.bat`). Já foi o contrato do motor manual do Claude
# Code, que não existe mais.
CLAUDE_MD_FILENAME = "CLAUDE.md"

_MD = ".md"


def dashed_name(name: str, tag: str) -> str:
    """`index.md` + `Vol` → `index-Vol.md`. É o formato dos índices e
    cronologias por grupo, das partes numeradas (`index-Vol-1.md`) e do
    sufixo de desempate (`index-Vol-<hash>.md`). `tag` entra como está:
    `*` dá o glob, `<grupo>` dá o padrão citado na prosa."""
    return f"{name.removesuffix(_MD)}-{tag}{_MD}"


def part_filename(name: str, number: int) -> str:
    """A parte `number` de um índice dividido: `index-Vol.md` → `index-Vol-1.md`."""
    return dashed_name(name, str(number))


def _safe_group_name(group_key: str) -> str:
    seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in group_key)
    seguro = "-".join(parte for parte in seguro.split("-") if parte)
    return seguro or "grupo"


def group_index_filename(group_key: str) -> str:
    """`index-<grupo>.md`, com o nome do grupo reduzido a caracteres
    seguros para nome de arquivo em qualquer sistema."""
    return dashed_name(INDEX_FILENAME, _safe_group_name(group_key))


def group_timeline_filename(group_key: str) -> str:
    """`timeline-<grupo>.md`: a cronologia de um grupo com mais peças datadas
    do que `config.timeline_split_items`, para não inflar o `timeline.md`."""
    return dashed_name(TIMELINE_FILENAME, _safe_group_name(group_key))


GROUP_INDEX_GLOB = dashed_name(INDEX_FILENAME, "*")
GROUP_TIMELINE_GLOB = dashed_name(TIMELINE_FILENAME, "*")
# Fase 38 aposentou o `legislacao-<grupo>.md`; o padrão fica só para apagar
# o que versões antigas deixaram.
LEGACY_LEGISLATION_GLOB = "legislacao-*.md"


# Pacote combinado (fase 38): cada arquivo de um acervo leva o apelido dele
# e este separador na frente. A geração simples nunca usa o separador.
COMBINED_SEPARATOR = "__"


def prefixed_name(alias: str, name: str) -> str:
    return f"{alias}{COMBINED_SEPARATOR}{name}"


# O que a gravação combinada pode ter deixado numa pasta: os nomes
# prefixados de índice e cronologia (com os de grupo e as partes) e de
# conferência e normas.
COMBINED_STALE_PATTERNS = (
    prefixed_name("*", f"{INDEX_FILENAME.removesuffix(_MD)}*{_MD}"),
    prefixed_name("*", f"{TIMELINE_FILENAME.removesuffix(_MD)}*{_MD}"),
    prefixed_name("*", REVIEW_FILENAME),
    prefixed_name("*", NORMS_FILENAME),
)

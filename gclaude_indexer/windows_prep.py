# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Preparation of classification windows (section 5, step 5) and generation
of the `CLAUDE.md` that guides the `claude_code` engine (section 5, step 6).

Each group has its pages (already extracted in phase 4) sliced into
overlapping windows, one window per `.txt` in `<output_folder>/windows/`. A
window that already exists (same `key`, computed from the group and the
position) is not rewritten — resumable without duplicating work.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .i18n import _REFERENCE_LANGUAGE

CLAUDE_MD_FILENAME = "CLAUDE.md"


@dataclass
class WindowsResult:
    created: int = 0
    existing: int = 0


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "grupo"


def pages_for_group(conn, group_key: str):
    """Pages of the group, in the order they were extracted (phase 4) — the
    same order used to build the windows and cited by `RulesEngine`."""
    return conn.execute(
        """
        SELECT page.*, file.name AS file_name
        FROM page
        JOIN file ON file.id = page.file_id
        WHERE file.group_key = ?
        ORDER BY page.id
        """,
        (group_key,),
    ).fetchall()


def _write_window_file(path: Path, key: str, group_key: str, start_ref: str, end_ref: str, pages) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    files_involved = sorted({page["file_name"] for page in pages})

    lines = [
        f"# window: {key}",
        f"# group: {group_key}",
        f"# range: {start_ref} a {end_ref}",
        f"# files: {', '.join(files_involved)}",
        f"# pages: {len(pages)}",
        "",
    ]
    for page in pages:
        lines.append(f"--- {page['reference']} ({page['file_name']}) ---")
        lines.append(page["text"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def prepare_windows(
    conn, config: ProjectConfig, should_stop: Callable[[], bool] | None = None, language: str | None = None
) -> WindowsResult:
    group_keys = [
        row["group_key"]
        for row in conn.execute(
            "SELECT DISTINCT group_key FROM file WHERE group_key IS NOT NULL AND status = 'extracted'"
        ).fetchall()
    ]

    windows_dir = Path(config.output_folder) / "windows"
    window_size = config.pages_per_window
    step = window_size - config.overlap

    result = WindowsResult()

    for group_key in group_keys:
        if should_stop is not None and should_stop():
            break

        pages = pages_for_group(conn, group_key)
        page_count = len(pages)
        if page_count == 0:
            continue

        base_name = _sanitize_name(group_key)
        start = 0

        while start < page_count:
            end = min(start + window_size, page_count)
            page_block = pages[start:end]
            start_ref = page_block[0]["reference"]
            end_ref = page_block[-1]["reference"]
            key = f"{base_name}::{start + 1:06d}-{end:06d}"

            if conn.execute("SELECT 1 FROM window WHERE key = ?", (key,)).fetchone():
                result.existing += 1
            else:
                conn.execute(
                    """
                    INSERT INTO window (key, group_key, start_ref, end_ref, status)
                    VALUES (?, ?, ?, ?, 'pending')
                    """,
                    (key, group_key, start_ref, end_ref),
                )
                conn.commit()
                result.created += 1

            file_path = windows_dir / f"{base_name}_j{start + 1:04d}-{end:04d}.txt"
            if not file_path.exists():
                _write_window_file(file_path, key, group_key, start_ref, end_ref, page_block)

            if end == page_count:
                break
            start += step

    record_event(
        conn,
        "windows",
        "info",
        "log.windows.summary",
        {"created": result.created, "existing": result.existing},
        language=language,
    )

    return result


def generate_claude_md(config: ProjectConfig, language: str) -> Path:
    """Writes the `CLAUDE.md` that guides the `claude_code` engine to
    classify the windows in `<output_folder>/windows/` and write
    `raw_items.jsonl`. Prose follows `language`, falling back to
    `_REFERENCE_LANGUAGE` ("pt") for an unrecognized value — same reasoning
    as `i18n.py::translate()`. The JSON contract keys (`window`, `group`,
    `type`, ...) and the document-type vocabulary (OFÍCIO, MEMORANDO, ...)
    stay fixed in every language: the former is a contract validated with a
    real model (Task 9e), the latter is literal terminology from the
    collection's own Portuguese-language source documents, not UI text (see
    `_CLAUDE_MD_CONTENT` below). Only the prose changes."""
    subject = config.subject.strip() or config.name
    template = _CLAUDE_MD_CONTENT.get(language, _CLAUDE_MD_CONTENT[_REFERENCE_LANGUAGE])
    path = Path(config.output_folder) / CLAUDE_MD_FILENAME
    path.write_text(template.format(subject=subject, project_name=config.name), encoding="utf-8")
    return path


# One full template per language (Task 11, Phase 14), not itemized i18n
# keys — same pattern already used for `claude_package.py`'s `_GUIDE`: this
# is one flowing guide document, not a set of independent UI labels, and
# translating it fragment by fragment would risk breaking sentence flow.
#
# What stays fixed across all three languages, on purpose:
# - The JSON field *keys* (`window`, `group`, `type`, `date`, ...): a
#   contract fixed and validated with a real model (Task 9e) — translating
#   them would break parsing, not just wording.
# - The document-type vocabulary (OFÍCIO, MEMORANDO, PARECER, ...): these
#   are literal words that appear in the collection's own Portuguese-
#   language source documents, regardless of which language the interface
#   (and this guide's prose) is in — translating them would make the
#   external Claude Code engine search for words that never appear in the
#   actual files.
# - The trigger phrase section lists all three interface phrasings
#   ("processe as janelas" / "process the windows" / "procese las
#   ventanas") as equally valid, in every language version of this file —
#   see `engine_claude_code.py`'s module docstring for why: there is no
#   persisted per-project language, only a `language` cookie read fresh on
#   each request, so a user who generated this file in one language and
#   later switched (or just remembers an older phrase) must still be
#   recognized.
_CLAUDE_MD_CONTENT: dict[str, str] = {
    "pt": """\
# GClaude Indexer — classificação das janelas ({project_name})

Este arquivo orienta você (Claude Code) a classificar o acervo
"{subject}" a partir das janelas de texto geradas pelo GClaude Indexer nesta
mesma pasta. Você é o motor de classificação `claude_code` — a opção de
melhor qualidade entre os motores do sistema.

## Quando o usuário disser "processe as janelas", "process the windows" ou "procese las ventanas"

As três frases acima são equivalentes — o usuário pode ter gerado este
arquivo numa língua e estar usando a interface noutra. Trate qualquer uma
delas como o mesmo comando.

1. Liste os arquivos `.txt` de `windows/`. Cada um começa com um cabeçalho
   `# window: <chave>` — essa `chave` identifica a janela de forma única.
2. Abra `raw_items.jsonl` (crie vazio se não existir) e colete o conjunto
   de `chave` já processadas (primeiro campo `"window"` de cada linha JSON).
   Pule as janelas cuja chave já apareça ali — já foram classificadas.
3. Para cada janela ainda pendente, leia o texto completo do arquivo e
   identifique as peças nele contidas (ver "Como reconhecer uma peça"
   abaixo). Cada página do arquivo já vem rotulada com sua referência
   citável (`f. N` para processo, `p. N` para biblioteca) e o nome do
   arquivo de origem — cite sempre essa referência, nunca invente uma.
4. Para cada peça encontrada, **acrescente uma linha** (não reescreva o
   arquivo) a `raw_items.jsonl`, na pasta de saída, no formato descrito em
   "Formato de cada linha" abaixo.
5. As janelas se sobrepõem em algumas páginas de propósito, para não cortar
   uma peça ao meio. Não se preocupe em deduplicar peças repetidas entre
   janelas vizinhas — a importação do GClaude Indexer faz isso depois.
6. Ao terminar todas as janelas pendentes, informe ao usuário quantas peças
   novas foram gravadas.

## Como reconhecer uma peça

- Início de peça: marcador de tipo no começo da página (ver vocabulário
  abaixo), página em branco anterior, carimbo de protocolo, ou mudança no
  cabeçalho repetido.
- Fim de peça: a página imediatamente anterior ao próximo início.
- Página sem nenhum marcador reconhecível pertence à peça anterior — grave-a
  como parte dela e marque `"confidence": "low"`.
- Vocabulário de tipos usual (não é uma lista fechada — use o tipo real que
  aparecer no documento): OFÍCIO, MEMORANDO, PARECER, DESPACHO, ATA,
  CERTIDÃO, TERMO, EDITAL, NOTA FISCAL, RECURSO, DECISÃO, PORTARIA,
  RESOLUÇÃO.
- Data: procure primeiro por um formato de data explícito no corpo do
  documento (numérico ou por extenso). Grave em ISO (`AAAA-MM-DD`). Sem data
  identificável, grave `null` — nunca invente uma data.
- Autor: normalmente no bloco de assinatura ou rodapé.
- Resumo: se houver linha "Assunto:" ou "Ementa:", use o texto dela. Na
  falta, escreva uma frase curta (não copie o documento inteiro).

## Formato de cada linha (uma peça = um objeto JSON)

```json
{{"window": "<chave da janela, copiada do cabeçalho>",
  "group": "<agrupador, copiado do cabeçalho da janela>",
  "ref_start": "<referência da primeira página da peça, ex. 'f. 12'>",
  "ref_end": "<referência da última página da peça>",
  "order_start": <número inteiro extraído de ref_start, ex. 12>,
  "order_end": <número inteiro extraído de ref_end>,
  "type": "<tipo da peça ou null>",
  "date": "<AAAA-MM-DD ou null>",
  "author": "<autor ou null>",
  "summary": "<frase curta ou null>",
  "has_table": <true ou false>,
  "has_image": <true ou false>,
  "engine": "claude_code",
  "confidence": "<high|medium|low>",
  "files": "<nomes dos arquivos de origem, separados por vírgula>"}}
```

Regras de formato — cada linha é validada campo a campo antes de ser
importada, então siga isto à risca:

- Uma linha por peça, sem vírgula entre linhas (é JSON Lines, não um array).
- `ref_start`/`ref_end` devem estar dentro do intervalo da própria
  janela (não referencie página de outra janela).
- `order_start` e `order_end` são inteiros (a parte numérica da
  referência), usados para ordenar e detectar lacunas — nunca strings.
- `date` é uma data ISO plausível (`AAAA-MM-DD`) ou `null`; nunca um texto
  livre como "maio de 2024".
- `confidence` é sempre uma destas três strings: `"high"`, `"medium"` ou
  `"low"`.
- `engine` é sempre a string fixa `"claude_code"`.
- Não inclua comentários nem texto fora do objeto JSON em cada linha.
""",
    "en": """\
# GClaude Indexer — classifying the windows ({project_name})

This file guides you (Claude Code) in classifying the collection
"{subject}" from the text windows GClaude Indexer generated in this same
folder. You are the `claude_code` classification engine — the highest-
quality option among the system's engines.

## When the user says "processe as janelas", "process the windows" or "procese las ventanas"

The three phrases above are equivalent — the user may have generated this
file in one language while using the interface in another. Treat any one
of them as the same command.

1. List the `.txt` files in `windows/`. Each one starts with a
   `# window: <key>` header — that `key` uniquely identifies the window.
2. Open `raw_items.jsonl` (create it empty if it does not exist) and
   collect the set of `key`s already processed (the first `"window"` field
   of each JSON line). Skip any window whose key already appears there —
   it has already been classified.
3. For each window still pending, read the file's full text and identify
   the items it contains (see "How to recognize an item" below). Each page
   in the file already comes labeled with its citable reference (`f. N`
   for a legal process, `p. N` for a library collection) and the name of
   the source file — always cite that reference, never invent one.
4. For each item found, **append a line** (do not rewrite the file) to
   `raw_items.jsonl`, in the output folder, in the format described in
   "Format of each line" below.
5. The windows overlap on a few pages on purpose, so as not to cut an item
   in half. Do not worry about deduplicating items repeated between
   neighboring windows — GClaude Indexer's import step does that
   afterward.
6. When you finish every pending window, tell the user how many new items
   were written.

## How to recognize an item

- Start of an item: a type marker at the top of the page (see vocabulary
  below), a preceding blank page, a protocol stamp, or a change in the
  repeated header.
- End of an item: the page immediately before the next start.
- A page with no recognizable marker belongs to the previous item — record
  it as part of that item and mark `"confidence": "low"`.
- Usual type vocabulary (not a closed list — use the actual type that
  appears in the document; these are Portuguese terms because the source
  documents are in Portuguese): OFÍCIO, MEMORANDO, PARECER, DESPACHO, ATA,
  CERTIDÃO, TERMO, EDITAL, NOTA FISCAL, RECURSO, DECISÃO, PORTARIA,
  RESOLUÇÃO.
- Date: first look for an explicit date format in the document's body
  (numeric or spelled out). Record it in ISO (`YYYY-MM-DD`). With no
  identifiable date, record `null` — never invent one.
- Author: usually in the signature block or footer.
- Summary: if there is an "Assunto:" or "Ementa:" line, use its text.
  Otherwise, write a short sentence (do not copy the whole document).

## Format of each line (one item = one JSON object)

```json
{{"window": "<window key, copied from the header>",
  "group": "<group, copied from the window's header>",
  "ref_start": "<reference of the item's first page, e.g. 'f. 12'>",
  "ref_end": "<reference of the item's last page>",
  "order_start": <integer extracted from ref_start, e.g. 12>,
  "order_end": <integer extracted from ref_end>,
  "type": "<item type or null>",
  "date": "<YYYY-MM-DD or null>",
  "author": "<author or null>",
  "summary": "<short sentence or null>",
  "has_table": <true or false>,
  "has_image": <true or false>,
  "engine": "claude_code",
  "confidence": "<high|medium|low>",
  "files": "<source file names, comma-separated>"}}
```

Format rules — every line is validated field by field before being
imported, so follow this precisely:

- One line per item, no comma between lines (this is JSON Lines, not an
  array).
- `ref_start`/`ref_end` must fall within the window's own range (never
  reference a page from another window).
- `order_start` and `order_end` are integers (the numeric part of the
  reference), used for ordering and gap detection — never strings.
- `date` is a plausible ISO date (`YYYY-MM-DD`) or `null`; never free text
  like "May 2024".
- `confidence` is always one of these three strings: `"high"`, `"medium"`
  or `"low"`.
- `engine` is always the fixed string `"claude_code"`.
- Do not include comments or text outside the JSON object on any line.
""",
    "es": """\
# GClaude Indexer — clasificación de las ventanas ({project_name})

Este archivo lo guía a usted (Claude Code) para clasificar la colección
"{subject}" a partir de las ventanas de texto que GClaude Indexer generó en
esta misma carpeta. Usted es el motor de clasificación `claude_code` — la
opción de mejor calidad entre los motores del sistema.

## Cuando el usuario diga "processe as janelas", "process the windows" o "procese las ventanas"

Las tres frases anteriores son equivalentes — el usuario puede haber
generado este archivo en un idioma y estar usando la interfaz en otro.
Trate cualquiera de ellas como el mismo comando.

1. Liste los archivos `.txt` de `windows/`. Cada uno comienza con un
   encabezado `# window: <clave>` — esa `clave` identifica la ventana de
   forma única.
2. Abra `raw_items.jsonl` (créelo vacío si no existe) y recolecte el
   conjunto de `clave` ya procesadas (primer campo `"window"` de cada
   línea JSON). Omita las ventanas cuya clave ya aparezca allí — ya fueron
   clasificadas.
3. Para cada ventana aún pendiente, lea el texto completo del archivo e
   identifique las piezas que contiene (vea "Cómo reconocer una pieza" más
   abajo). Cada página del archivo ya viene etiquetada con su referencia
   citable (`f. N` para expediente, `p. N` para biblioteca) y el nombre del
   archivo de origen — cite siempre esa referencia, nunca invente una.
4. Para cada pieza encontrada, **agregue una línea** (no reescriba el
   archivo) a `raw_items.jsonl`, en la carpeta de salida, en el formato
   descrito en "Formato de cada línea" más abajo.
5. Las ventanas se superponen en algunas páginas a propósito, para no
   cortar una pieza por la mitad. No se preocupe por deduplicar piezas
   repetidas entre ventanas vecinas — la importación de GClaude Indexer
   hace eso después.
6. Al terminar todas las ventanas pendientes, informe al usuario cuántas
   piezas nuevas se grabaron.

## Cómo reconocer una pieza

- Inicio de pieza: marcador de tipo al comienzo de la página (vea el
  vocabulario más abajo), página en blanco anterior, sello de protocolo, o
  cambio en el encabezado repetido.
- Fin de pieza: la página inmediatamente anterior al siguiente inicio.
- Una página sin ningún marcador reconocible pertenece a la pieza anterior
  — grábela como parte de ella y marque `"confidence": "low"`.
- Vocabulario de tipos habitual (no es una lista cerrada — use el tipo real
  que aparezca en el documento; son términos en portugués porque los
  documentos de origen están en portugués): OFÍCIO, MEMORANDO, PARECER,
  DESPACHO, ATA, CERTIDÃO, TERMO, EDITAL, NOTA FISCAL, RECURSO, DECISÃO,
  PORTARIA, RESOLUÇÃO.
- Fecha: busque primero un formato de fecha explícito en el cuerpo del
  documento (numérico o en palabras). Grábela en ISO (`AAAA-MM-DD`). Sin
  fecha identificable, grabe `null` — nunca invente una fecha.
- Autor: normalmente en el bloque de firma o pie de página.
- Resumen: si hay una línea "Assunto:" o "Ementa:", use ese texto. En su
  ausencia, escriba una frase corta (no copie el documento entero).

## Formato de cada línea (una pieza = un objeto JSON)

```json
{{"window": "<clave de la ventana, copiada del encabezado>",
  "group": "<agrupador, copiado del encabezado de la ventana>",
  "ref_start": "<referencia de la primera página de la pieza, ej. 'f. 12'>",
  "ref_end": "<referencia de la última página de la pieza>",
  "order_start": <número entero extraído de ref_start, ej. 12>,
  "order_end": <número entero extraído de ref_end>,
  "type": "<tipo de la pieza o null>",
  "date": "<AAAA-MM-DD o null>",
  "author": "<autor o null>",
  "summary": "<frase corta o null>",
  "has_table": <true o false>,
  "has_image": <true o false>,
  "engine": "claude_code",
  "confidence": "<high|medium|low>",
  "files": "<nombres de los archivos de origen, separados por comas>"}}
```

Reglas de formato — cada línea se valida campo por campo antes de ser
importada, así que sígalas al pie de la letra:

- Una línea por pieza, sin coma entre líneas (es JSON Lines, no un array).
- `ref_start`/`ref_end` deben estar dentro del propio rango de la ventana
  (no haga referencia a una página de otra ventana).
- `order_start` y `order_end` son enteros (la parte numérica de la
  referencia), usados para ordenar y detectar vacíos — nunca strings.
- `date` es una fecha ISO plausible (`AAAA-MM-DD`) o `null`; nunca un texto
  libre como "mayo de 2024".
- `confidence` es siempre una de estas tres strings: `"high"`, `"medium"` o
  `"low"`.
- `engine` es siempre la string fija `"claude_code"`.
- No incluya comentarios ni texto fuera del objeto JSON en ninguna línea.
""",
}

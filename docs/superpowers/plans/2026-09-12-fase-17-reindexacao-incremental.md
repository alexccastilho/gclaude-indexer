# Fase 17 — Reindexação incremental: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** permitir que um acervo já indexado absorva documentos novos,
alterados e removidos reprocessando apenas o que a mudança afeta.

**Architecture:** uma operação de invalidação em três fases (plano somente
leitura, invalidação transacional, reexecução do pipeline existente). As
cinco etapas atuais não mudam de contrato: a invalidação apenas devolve o
banco a um estado que elas já sabem tratar. Janelas são descartadas a
partir do ponto de divergência do grupo, nunca o grupo inteiro.

**Tech Stack:** Python 3.12, SQLite (stdlib `sqlite3`), FastAPI, Jinja2,
HTMX, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-fase-17-reindexacao-incremental-design.md`

## Global Constraints

- Python 3.12. Não usar recurso de 3.13+; as dependências fixadas quebram
  nas versões mais novas.
- Todo arquivo `.py` novo abre com o cabeçalho GPL-3.0 usado em todo
  `gclaude_indexer/` (copiar de `gclaude_indexer/paths.py`).
- Todo texto de interface passa por `i18n.py`, nos três idiomas (pt, en,
  es). Nenhuma string visível ao usuário escrita direto no template ou no
  Python.
- SQL sempre parametrizado (`conn.execute(sql, params)`). Nunca f-string
  em SQL, nem para valor interno.
- Type hints em toda função pública. `pathlib` em vez de `os.path`.
- Nenhum acesso de rede. O aplicativo é offline por projeto.
- Antes de apagar qualquer arquivo do disco, confinar o caminho com
  `paths.resolve_within(base, relative)`, que já existe e recusa escape.
- Testes em `tests/test_phase17.py`, nomes em português descrevendo o
  comportamento. Rodar com `python -m pytest tests/test_phase17.py -v`.
- Não renomear nem remover nada de que outro módulo dependa sem atualizar
  todos os pontos de uso na mesma tarefa.

## Correções do plano sobre a spec

Duas coisas que a leitura do código revelou depois da spec aprovada. Valem
sobre o texto da spec onde houver conflito.

1. **§9 — o total de janelas a classificar não é previsível.** As
   descartadas e as preservadas são exatas. As que os documentos novos vão
   gerar dependem do número de páginas deles, desconhecido antes da
   extração. A tela mostra os números exatos e declara que os novos entram
   por cima, em vez de estimar.
2. **§8.2 — a regra de invalidação tem duas condições, não uma.** Além da
   janela que contém a primeira página divergente, a **última** janela do
   grupo sempre pode mudar, porque a extensão dela é limitada pelo total de
   páginas (`min(start + window_size, page_count)`). O índice da primeira
   janela descartada é o menor dos dois. É com essa regra que o exemplo das
   500 páginas dá 1 descartada e 35 preservadas.

## Estrutura de arquivos

**Criar**

| Arquivo | Responsabilidade |
|---|---|
| `gclaude_indexer/update_plan.py` | Comparar pasta e banco. Somente leitura. Produz `UpdatePlan`. |
| `gclaude_indexer/invalidation.py` | Aplicar um `UpdatePlan`. Transacional. Única coisa que apaga. |
| `gclaude_indexer/web/templates/update_project.html` | Tela de confirmação. |
| `tests/test_phase17.py` | Testes da fase. |

**Modificar**

| Arquivo | Mudança |
|---|---|
| `gclaude_indexer/db.py` | Tabela `removed_file`; coluna `file.mtime`. |
| `gclaude_indexer/paths.py` | Recebe `natural_sort_key`, hoje privada em `extraction.py`. |
| `gclaude_indexer/scanning.py` | Extrai `source_files()` do corpo de `scan()`; grava `mtime`. |
| `gclaude_indexer/extraction.py` | Passa a importar `natural_sort_key` de `paths`. |
| `gclaude_indexer/windows_prep.py` | Extrai `window_spans()`/`window_key()`; ordena `pages_for_group` de forma determinística; grava o `.txt` ao criar a linha. |
| `gclaude_indexer/artifacts.py` | Seção de removidos no `review.md`. |
| `gclaude_indexer/i18n.py` | Chaves novas nos três idiomas. |
| `gclaude_indexer/web/app.py` | Três rotas: banner, diagnóstico, aplicação. |
| `gclaude_indexer/web/templates/run.html` | Ponto de ancoragem do banner. |

---

### Task 1: Esquema — tabela de removidos e coluna `mtime`

**Files:**
- Modify: `gclaude_indexer/db.py:22-114` (SCHEMA_SQL), `:152-157` (init_schema)
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: nada.
- Produces: tabela `removed_file(id, relative_path, name, removed_at)`;
  coluna `file.mtime REAL`; função `db._ensure_file_mtime_column(conn)`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_phase17.py
from __future__ import annotations

from pathlib import Path

import pytest

from gclaude_indexer import db


def _conn(tmp_path: Path):
    connection = db.connect(tmp_path / "project.db")
    db.init_schema(connection)
    return connection


def test_a_tabela_de_removidos_e_a_coluna_mtime_nascem_na_abertura(tmp_path):
    conn = _conn(tmp_path)

    tabelas = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "removed_file" in tabelas

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas


def test_abrir_o_projeto_duas_vezes_nao_duplica_a_coluna(tmp_path):
    conn = _conn(tmp_path)
    db.init_schema(conn)  # não pode levantar "duplicate column name"

    colunas = [row[1] for row in conn.execute("PRAGMA table_info(file)")]
    assert colunas.count("mtime") == 1


def test_um_projeto_da_1_0_1_ganha_a_coluna_na_primeira_abertura(tmp_path):
    """Simula o banco antigo: tabela `file` sem `mtime`."""
    conn = db.connect(tmp_path / "project.db")
    conn.execute(
        "CREATE TABLE file (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL,"
        " sha256 TEXT NOT NULL, group_key TEXT, page_count INTEGER,"
        " needs_ocr INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT)"
    )
    conn.commit()

    db.init_schema(conn)

    colunas = {row[1] for row in conn.execute("PRAGMA table_info(file)")}
    assert "mtime" in colunas
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: FAIL — `assert 'removed_file' in tabelas` e `'mtime' in colunas`.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/db.py`, dentro de `SCHEMA_SQL`, logo depois do bloco
`CREATE TABLE IF NOT EXISTS run (...)`:

```sql
-- Fase 17: documento que saiu da pasta de origem. É estado, não log: o
-- `review.md` relata as remoções, e um evento desapareceria se o log
-- fosse limpo.
CREATE TABLE IF NOT EXISTS removed_file (
    id            INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL,
    name          TEXT NOT NULL,
    removed_at    TEXT NOT NULL
);
```

Depois de `_ensure_event_message_columns`:

```python
def _ensure_file_mtime_column(conn: sqlite3.Connection) -> None:
    """Adds `file.mtime` (Phase 17): the update plan compares size and
    modification time before hashing, so opening a project does not read
    every byte of a Drive-synced collection. Same guard as
    `_ensure_event_message_columns` — `CREATE TABLE IF NOT EXISTS` never
    adds a column to a table that already exists, and `init_schema` runs
    on every project load."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(file)").fetchall()}
    if "mtime" not in existing_columns:
        conn.execute("ALTER TABLE file ADD COLUMN mtime REAL")
```

E em `init_schema`, uma linha depois da chamada existente:

```python
def init_schema(conn: sqlite3.Connection) -> None:
    """Creates section 4's tables and indexes, idempotent."""
    conn.executescript(SCHEMA_SQL)
    _ensure_event_message_columns(conn)
    _ensure_file_mtime_column(conn)
    conn.commit()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS, 3 testes.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: nenhuma regressão.

- [ ] **Step 6: Commit**

```bash
git add gclaude_indexer/db.py tests/test_phase17.py
git commit -m "feat(db): tabela removed_file e coluna file.mtime para a fase 17"
```

---

### Task 2: Caminhamento da pasta reutilizável

O plano e o scan têm de andar pela pasta pelos mesmos critérios. Se
divergirem, o plano mente para o usuário.

**Files:**
- Modify: `gclaude_indexer/scanning.py:170-180` (corpo de `scan`)
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: `scanning.is_system_file(path)` (já existe).
- Produces: `scanning.source_files(source_dir: Path, output_dir: Path) -> list[Path]`.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.scanning import source_files


def test_o_caminhamento_ignora_lixo_de_sistema_e_a_pasta_de_saida(tmp_path):
    origem = tmp_path / "origem"
    saida = origem / "saida"
    (origem / "sub").mkdir(parents=True)
    saida.mkdir()

    (origem / "b.pdf").write_text("b", encoding="utf-8")
    (origem / "A.pdf").write_text("a", encoding="utf-8")
    (origem / "sub" / "c.pdf").write_text("c", encoding="utf-8")
    (origem / "desktop.ini").write_text("lixo", encoding="utf-8")
    (saida / "index.md").write_text("gerado", encoding="utf-8")

    encontrados = [p.relative_to(origem).as_posix() for p in source_files(origem, saida)]

    assert encontrados == ["A.pdf", "b.pdf", "sub/c.pdf"]
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py::test_o_caminhamento_ignora_lixo_de_sistema_e_a_pasta_de_saida -v`
Expected: FAIL — `ImportError: cannot import name 'source_files'`.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/scanning.py`, logo depois de `is_system_file`:

```python
def source_files(source_dir: Path, output_dir: Path) -> list[Path]:
    """Files of the collection, in the order the scan walks them.

    Extracted from `scan()` (Phase 17) so the update plan
    (`update_plan.py`) walks by exactly the same criteria. Two walks that
    disagree would make the plan describe a folder the scan does not see.
    """
    return sorted(
        (
            path
            for path in source_dir.rglob("*")
            if path.is_file()
            and not path.is_relative_to(output_dir)
            and not is_system_file(path)
        ),
        key=lambda path: str(path.relative_to(source_dir)).lower(),
    )
```

Em `scan()`, substituir o bloco que monta `paths` e as duas guardas dentro
do laço. Antes:

```python
    paths = sorted(
        (path for path in source_dir.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(source_dir)).lower(),
    )

    for path in paths:
        if should_stop is not None and should_stop():
            break

        if path.is_relative_to(output_dir):
            continue

        if is_system_file(path):
            # (comentário existente sobre desktop.ini)
            continue
```

Depois:

```python
    for path in source_files(source_dir, output_dir):
        if should_stop is not None and should_stop():
            break
```

O comentário sobre o `desktop.ini` que vira item número um do índice muda
de lugar junto: passa para o corpo de `is_system_file`, que já o explica,
e não precisa ser duplicado.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte de scan**

Run: `python -m pytest tests/ -q -k "scan or fase1 or phase1"`
Expected: nenhuma regressão. O comportamento é idêntico: as duas guardas
já rodavam antes de `total_found` ser incrementado.

- [ ] **Step 6: Commit**

```bash
git add gclaude_indexer/scanning.py tests/test_phase17.py
git commit -m "refactor(scanning): extrai source_files para o plano de atualizacao reusar"
```

---

### Task 3: Aritmética de janela como função pura

**Files:**
- Modify: `gclaude_indexer/windows_prep.py:104-130`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `windows_prep.window_spans(page_count: int, window_size: int, overlap: int) -> list[tuple[int, int]]`
    — pares `(start, end)` com `start` 0-based e `end` exclusivo, para
    fatiar `pages[start:end]`.
  - `windows_prep.window_key(base_name: str, start: int, end: int) -> str`.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.windows_prep import window_key, window_spans


def test_quinhentas_paginas_dao_trinta_e_seis_janelas():
    spans = window_spans(500, 16, 2)

    assert len(spans) == 36
    assert spans[0] == (0, 16)
    assert spans[-1] == (490, 500)


def test_dez_paginas_no_fim_mudam_so_a_cauda():
    antes = window_spans(500, 16, 2)
    depois = window_spans(510, 16, 2)

    assert antes[:35] == depois[:35]      # 35 janelas idênticas
    assert antes[35] == (490, 500)        # a última de antes
    assert depois[35] == (490, 506)       # mudou: cobre 6 páginas novas
    assert depois[36] == (504, 510)       # e nasceu uma
    assert len(depois) == 37


def test_a_chave_da_janela_e_posicional_e_com_zeros_a_esquerda():
    assert window_key("processo", 490, 500) == "processo::000491-000500"


def test_acervo_vazio_nao_gera_janela():
    assert window_spans(0, 16, 2) == []


def test_sobreposicao_maior_que_a_janela_nao_trava():
    """Passo zero ou negativo faria laço infinito. O piso de 1 impede."""
    spans = window_spans(10, 4, 9)

    assert len(spans) <= 10
    assert spans[-1][1] == 10
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "janela or paginas or chave or acervo or sobreposicao"`
Expected: FAIL — `ImportError: cannot import name 'window_spans'`.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/windows_prep.py`, antes de `prepare_windows`:

```python
def window_spans(page_count: int, window_size: int, overlap: int) -> list[tuple[int, int]]:
    """`(start, end)` of each window over a group of `page_count` pages.

    `start` is 0-based and `end` exclusive, so the block is `pages[start:end]`.
    Extracted from `prepare_windows` (Phase 17) so `update_plan.py` can
    predict the layout without duplicating the arithmetic: a plan that
    counts windows differently from the step that creates them is a plan
    that lies.

    The step has a floor of 1. An overlap greater than or equal to the
    window size would otherwise give a step of zero and loop forever;
    configuration validation should prevent it, but a pure function is
    where the guard costs nothing.
    """
    if page_count <= 0:
        return []

    step = max(1, window_size - overlap)
    spans: list[tuple[int, int]] = []
    start = 0
    while start < page_count:
        end = min(start + window_size, page_count)
        spans.append((start, end))
        if end == page_count:
            break
        start += step
    return spans


def window_key(base_name: str, start: int, end: int) -> str:
    """The window's identity in the `window` table: group plus position."""
    return f"{base_name}::{start + 1:06d}-{end:06d}"
```

Em `prepare_windows`, trocar o laço manual pelo uso das duas. Antes:

```python
        base_name = _sanitize_name(group_key)
        start = 0

        while start < page_count:
            end = min(start + window_size, page_count)
            page_block = pages[start:end]
            start_ref = page_block[0]["reference"]
            end_ref = page_block[-1]["reference"]
            key = f"{base_name}::{start + 1:06d}-{end:06d}"
```

Depois:

```python
        base_name = _sanitize_name(group_key)

        for start, end in window_spans(page_count, window_size, config.overlap):
            page_block = pages[start:end]
            start_ref = page_block[0]["reference"]
            end_ref = page_block[-1]["reference"]
            key = window_key(base_name, start, end)
```

E remover, no fim do corpo do laço, as duas linhas que faziam o avanço
manual, porque agora quem itera é o `for`:

```python
            if end == page_count:
                break
            start += step
```

A variável `step`, calculada antes do laço dos grupos, deixa de ser usada
e sai junto.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte de janelas**

Run: `python -m pytest -q`
Expected: nenhuma regressão. As chaves geradas são idênticas às de antes.

- [ ] **Step 6: Commit**

```bash
git add gclaude_indexer/windows_prep.py tests/test_phase17.py
git commit -m "refactor(windows): extrai window_spans e window_key como funcoes puras"
```

---

### Task 4: Ordem determinística das páginas do grupo

Hoje `pages_for_group` ordena por `page.id`, a ordem de inserção. Coincide
com a ordem natural dos caminhos num projeto construído de uma vez, mas
não depois de uma atualização: um documento corrigido saltaria para o fim.
`classification.py:80` fatia as páginas por posição, então ele e
`windows_prep` têm de ver exatamente a mesma ordem.

**Files:**
- Modify: `gclaude_indexer/paths.py` (recebe `natural_sort_key`),
  `gclaude_indexer/extraction.py:54-55,147`, `gclaude_indexer/windows_prep.py:42-53`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: nada.
- Produces: `paths.natural_sort_key(text: str) -> list[int | str]`.
  `windows_prep.pages_for_group` passa a devolver as linhas ordenadas por
  `(natural_sort_key(file.relative_path), page.number)` e cada linha ganha
  a coluna `file_relative_path`.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.paths import natural_sort_key
from gclaude_indexer.windows_prep import pages_for_group


def test_a_ordem_natural_poe_o_dez_depois_do_dois():
    nomes = ["doc10.pdf", "doc2.pdf", "doc1.pdf"]

    assert sorted(nomes, key=natural_sort_key) == ["doc1.pdf", "doc2.pdf", "doc10.pdf"]


def test_pagina_inserida_depois_nao_salta_para_o_fim_do_grupo(tmp_path):
    """O caso da atualização: o arquivo b.pdf é reextraído e suas páginas
    recebem ids maiores que as de c.pdf. A ordem tem de continuar a-b-c."""
    conn = _conn(tmp_path)
    for relative_path in ("a.pdf", "b.pdf", "c.pdf"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256,"
            " group_key, status) VALUES (?, ?, 'pdf', 1, ?, 'g', 'extracted')",
            (relative_path, relative_path, relative_path),
        )
    ids = {
        row["relative_path"]: row["id"]
        for row in conn.execute("SELECT id, relative_path FROM file")
    }
    # c.pdf entra antes de b.pdf, como aconteceria numa reextração de b.
    for relative_path in ("a.pdf", "c.pdf", "b.pdf"):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, 1, 'f. 1', 1, 0, 0, ?)",
            (ids[relative_path], relative_path),
        )
    conn.commit()

    ordem = [row["text"] for row in pages_for_group(conn, "g")]

    assert ordem == ["a.pdf", "b.pdf", "c.pdf"]
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "ordem or salta"`
Expected: FAIL — `ImportError: cannot import name 'natural_sort_key'`, e
depois a ordem `['a.pdf', 'c.pdf', 'b.pdf']`.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/paths.py`, no fim do arquivo:

```python
def natural_sort_key(text: str) -> list[int | str]:
    """Sort key where "doc10" comes after "doc2", not before it.

    Lived in `extraction.py` as `_natural_sort_key` until Phase 17, when
    `windows_prep.pages_for_group` needed the same ordering: the windows
    and the classification slice the group's pages by position, so the two
    must agree on what that position is.
    """
    import re

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]
```

Em `gclaude_indexer/extraction.py`, apagar `_natural_sort_key` (linhas
54-55), importar a nova no topo e trocar o uso na linha 147:

```python
from .paths import natural_sort_key
```

```python
        group_files.sort(key=lambda r: natural_sort_key(r["relative_path"]))
```

Em `gclaude_indexer/windows_prep.py`, substituir `pages_for_group`:

```python
def pages_for_group(conn, group_key: str):
    """Pages of the group, in the order the windows and `RulesEngine` cite.

    Ordered by natural path and page number, not by `page.id` (Phase 17).
    The two coincide in a project built in one pass, because extraction
    writes group by group in that same order — but not after an update,
    where a re-extracted file's pages get the highest ids and would jump
    to the end of the group. Natural ordering is not expressible in SQL,
    so the final sort happens here, with the key `extraction` already uses.
    """
    rows = conn.execute(
        """
        SELECT page.*, file.name AS file_name, file.relative_path AS file_relative_path
        FROM page
        JOIN file ON file.id = page.file_id
        WHERE file.group_key = ?
        """,
        (group_key,),
    ).fetchall()

    return sorted(
        rows,
        key=lambda row: (natural_sort_key(row["file_relative_path"]), row["number"]),
    )
```

E no topo do módulo:

```python
from .paths import natural_sort_key
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Conferir os dois pontos de uso**

`pages_for_group` é chamado em `windows_prep.py:97` e em
`classification.py:80`. A coluna nova `file_relative_path` é aditiva e
nenhum dos dois a consome, então ambos continuam funcionando.

Run: `python -m pytest -q`
Expected: nenhuma regressão.

- [ ] **Step 6: Commit**

```bash
git add gclaude_indexer/paths.py gclaude_indexer/extraction.py gclaude_indexer/windows_prep.py tests/test_phase17.py
git commit -m "fix(windows): ordem das paginas do grupo deixa de depender da ordem de insercao"
```

---

### Task 5: `update_plan.py` — detecção e guarda da pasta inacessível

O primeiro teste desta tarefa é o que protege o acervo do usuário. Escreva
esse antes de qualquer outro.

**Files:**
- Create: `gclaude_indexer/update_plan.py`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: `scanning.source_files`, `scanning.compute_hash`,
  `scanning.derive_group_key`, `file_types.is_extension_allowed`.
- Produces:
  - `update_plan.SourceFolderUnavailable` (exceção).
  - `update_plan.FileChange(relative_path: str, kind: str, name: str, size: int)`
    com `kind` em `"new" | "changed" | "removed"`.
  - `update_plan.detect_changes(conn, config) -> tuple[list[FileChange], int, str]`
    devolvendo mudanças, contagem de inalterados e a impressão digital.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.update_plan import SourceFolderUnavailable, detect_changes


def _config(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="all_together", extensions=["pdf"],
    )


def _registrar(conn, relative_path: str, conteudo: str, mtime: float | None):
    import hashlib

    digest = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, status) VALUES (?, ?, 'pdf', ?, ?, ?, 'g', 'extracted')",
        (relative_path, Path(relative_path).name, len(conteudo), digest, mtime),
    )
    conn.commit()


def test_pasta_de_origem_sumida_nao_propoe_remover_o_acervo(tmp_path):
    """A guarda mais importante da funcionalidade. Drive desconectado,
    pasta movida, letra de unidade trocada: nada disso pode virar uma
    proposta de apagar tudo."""
    origem = tmp_path / "origem"
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)

    with pytest.raises(SourceFolderUnavailable):
        detect_changes(conn, _config(origem, saida))


def test_pasta_vazia_com_banco_cheio_tambem_e_recusada(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)

    with pytest.raises(SourceFolderUnavailable):
        detect_changes(conn, _config(origem, saida))


def test_pasta_inalterada_nao_acusa_mudanca(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    arquivo = origem / "a.pdf"
    arquivo.write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", arquivo.stat().st_mtime)

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert mudancas == []
    assert inalterados == 1


def test_mtime_reescrito_pelo_drive_sem_mudar_conteudo_nao_e_alteracao(tmp_path):
    """O Google Drive reescreve a data de arquivos cujo conteúdo não mudou.
    Sem o desempate pelo hash, o plano gritaria 'mudou' o tempo todo."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "a.pdf", "a", 1.0)  # mtime antigo, conteúdo igual

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert mudancas == []
    assert inalterados == 1


def test_novo_alterado_e_removido_sao_detectados(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "igual.pdf").write_text("igual", encoding="utf-8")
    (origem / "mudou.pdf").write_text("depois", encoding="utf-8")
    (origem / "novo.pdf").write_text("novo", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar(conn, "igual.pdf", "igual", (origem / "igual.pdf").stat().st_mtime)
    _registrar(conn, "mudou.pdf", "antes", 1.0)
    _registrar(conn, "sumiu.pdf", "sumiu", 1.0)

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    por_tipo = {m.kind: m.relative_path for m in mudancas}
    assert por_tipo == {"new": "novo.pdf", "changed": "mudou.pdf", "removed": "sumiu.pdf"}
    assert inalterados == 1


def test_a_impressao_digital_muda_quando_a_pasta_muda(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)

    _, _, antes = detect_changes(conn, _config(origem, saida))
    (origem / "b.pdf").write_text("b", encoding="utf-8")
    _, _, depois = detect_changes(conn, _config(origem, saida))

    assert antes != depois
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "pasta or mtime or detectad or impressao"`
Expected: FAIL — `ModuleNotFoundError: No module named 'gclaude_indexer.update_plan'`.

- [ ] **Step 3: Implementar**

Criar `gclaude_indexer/update_plan.py` com o cabeçalho GPL copiado de
`paths.py` e o conteúdo:

```python
"""Comparing the source folder with the index, without writing anything.

Phase 17. The plan is the read-only half of the update: it answers "what
changed in the folder, and what would that cost", and nothing it does can
alter the project. That is what lets it run every time the Execution
screen opens.

**Detection is cheap on purpose.** Hashing every file of a Drive-synced
collection on each open would force the client to download files the user
never asked for. Size and modification time decide first; the hash is
computed only for the few candidates that differ. The hash still has the
last word, because Drive rewrites the modification time of files whose
bytes never changed — the same lesson already recorded in `staleness.py`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .scanning import compute_hash, source_files


class SourceFolderUnavailable(RuntimeError):
    """The source folder cannot be read, so no plan can be trusted.

    Without this the plan would read an unreachable folder as "every
    document was removed" and offer to delete the whole index. A
    disconnected Drive, a moved folder or a changed drive letter must
    never reach the confirmation screen as a removal.
    """


@dataclass(frozen=True)
class FileChange:
    relative_path: str
    kind: str  # "new" | "changed" | "removed"
    name: str
    size: int


def _fingerprint(entries: list[tuple[str, int, float]]) -> str:
    """Cheap identity of the folder as the plan saw it.

    Re-checked before the invalidation writes: applying a plan built from
    a folder that has since changed would write one thing having shown
    another.
    """
    digest = hashlib.sha256()
    for relative_path, size, mtime in sorted(entries):
        digest.update(f"{relative_path}|{size}|{mtime:.6f}\n".encode("utf-8"))
    return digest.hexdigest()


def detect_changes(
    conn, config: ProjectConfig
) -> tuple[list[FileChange], int, str]:
    """New, changed and removed files; how many are unchanged; and the
    folder's fingerprint.

    Raises `SourceFolderUnavailable` when the source folder is missing, or
    empty while the index is not.
    """
    source_dir = Path(config.source_folder)
    if not source_dir.is_dir():
        raise SourceFolderUnavailable(str(source_dir))

    output_dir = Path(config.output_folder).resolve()
    paths = source_files(source_dir.resolve(), output_dir)

    known = {
        row["relative_path"]: row
        for row in conn.execute("SELECT relative_path, size, sha256, mtime FROM file")
    }

    if not paths and known:
        raise SourceFolderUnavailable(str(source_dir))

    changes: list[FileChange] = []
    unchanged = 0
    entries: list[tuple[str, int, float]] = []
    seen: set[str] = set()

    for path in paths:
        relative_path = path.relative_to(source_dir.resolve()).as_posix()
        stat = path.stat()
        entries.append((relative_path, stat.st_size, stat.st_mtime))
        seen.add(relative_path)

        row = known.get(relative_path)
        if row is None:
            changes.append(FileChange(relative_path, "new", path.name, stat.st_size))
            continue

        if row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
            unchanged += 1
            continue

        # Size or time moved. Only now is reading the bytes worth it.
        if compute_hash(path) == row["sha256"]:
            unchanged += 1
            continue

        changes.append(FileChange(relative_path, "changed", path.name, stat.st_size))

    for relative_path in sorted(set(known) - seen):
        changes.append(
            FileChange(relative_path, "removed", Path(relative_path).name, 0)
        )

    return changes, unchanged, _fingerprint(entries)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Fazer o scan gravar o `mtime`**

Sem isso a detecção rápida nunca liga: `mtime` fica nulo para sempre e
todo arquivo vira candidato a hash. Em `gclaude_indexer/scanning.py`,
acrescentar a coluna ao `INSERT` de `_insert_file` e ao `UPDATE` de
`_update_file`, e passar `path.stat().st_mtime` nas duas chamadas dentro
de `scan()`. As duas funções ganham um parâmetro `mtime: float` depois de
`file_hash`.

Teste que fecha o ciclo:

```python
def test_o_scan_grava_o_mtime_para_a_deteccao_rapida(tmp_path):
    from gclaude_indexer.scanning import scan

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)

    scan(conn, _config(origem, saida))

    gravado = conn.execute("SELECT mtime FROM file WHERE relative_path = 'a.pdf'").fetchone()[0]
    assert gravado == pytest.approx((origem / "a.pdf").stat().st_mtime)
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: nenhuma regressão.

- [ ] **Step 7: Commit**

```bash
git add gclaude_indexer/update_plan.py gclaude_indexer/scanning.py tests/test_phase17.py
git commit -m "feat(update): deteccao de novos, alterados e removidos com guarda de origem inacessivel"
```

---

### Task 6: `update_plan.py` — divergência e contagem de janelas

**Files:**
- Modify: `gclaude_indexer/update_plan.py`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: `FileChange` e `detect_changes` (Task 5);
  `windows_prep.window_spans` (Task 3); `paths.natural_sort_key` (Task 4).
- Produces:
  - `update_plan.GroupInvalidation(group_key, first_divergent_page, first_affected_window, windows_discarded, windows_kept, files_to_renumber)`.
  - `update_plan.UpdatePlan(new, changed, removed, groups, unchanged_count, fingerprint)`
    com as propriedades `is_empty`, `files_needing_ocr` e
    `windows_to_reclassify`.
  - `update_plan.build_update_plan(conn, config) -> UpdatePlan`.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.update_plan import build_update_plan, first_affected_window
from gclaude_indexer.windows_prep import window_spans


def test_a_ultima_janela_sempre_entra_porque_o_total_a_limita():
    """Divergência na página 501 (0-based 500). Nenhuma janela antiga
    cobre essa página, mas a última ia de 491 a 500 e passa a ir de 491 a
    506: é ela que muda."""
    antigas = window_spans(500, 16, 2)

    assert first_affected_window(antigas, 500) == 35
    assert len(antigas) - 35 == 1      # 1 descartada
    assert 35 == 35                    # 35 preservadas


def test_divergencia_no_comeco_invalida_tudo():
    antigas = window_spans(500, 16, 2)

    assert first_affected_window(antigas, 0) == 0


def test_divergencia_no_meio_preserva_o_que_vem_antes():
    antigas = window_spans(500, 16, 2)

    indice = first_affected_window(antigas, 250)

    assert antigas[indice][1] > 250       # a janela cobre a página divergente
    assert antigas[indice - 1][1] <= 250  # a anterior não


def test_grupo_sem_janela_nao_quebra():
    assert first_affected_window([], 0) == 0


def test_o_plano_conta_janelas_descartadas_e_preservadas(tmp_path):
    """Acervo de 30 páginas em 3 arquivos de 10, janela 16 / sobreposição 2.
    Um quarto arquivo entra no fim."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, paginas=10)
    _criar_janelas(conn, "g", page_count=30, window_size=16, overlap=2)
    (origem / "d.pdf").write_text("d", encoding="utf-8")

    plano = build_update_plan(conn, _config(origem, saida))

    assert [m.relative_path for m in plano.new] == ["d.pdf"]
    assert plano.changed == ()
    assert plano.removed == ()
    grupo = plano.groups[0]
    assert grupo.windows_kept + grupo.windows_discarded == len(window_spans(30, 16, 2))
    assert grupo.windows_discarded >= 1
    assert plano.is_empty is False
    assert plano.files_needing_ocr == 1


def test_a_contagem_prevista_bate_com_a_que_windows_prep_cria(tmp_path):
    """Teste de acoplamento: se a aritmética voltar a ser duplicada, este
    falha antes de o usuário ver um número errado na tela."""
    for page_count in (1, 15, 16, 17, 30, 100, 500, 510):
        previstas = len(window_spans(page_count, 16, 2))
        criadas = _contar_janelas_criadas(page_count, window_size=16, overlap=2)
        assert previstas == criadas, f"{page_count} páginas"
```

Auxiliares do teste, no mesmo arquivo:

```python
def _registrar_com_paginas(conn, origem: Path, nome: str, paginas: int) -> None:
    import hashlib

    caminho = origem / nome
    conteudo = caminho.read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, page_count, status) VALUES (?, ?, 'pdf', ?, ?, ?, 'g', ?, 'extracted')",
        (nome, nome, len(conteudo), hashlib.sha256(conteudo.encode()).hexdigest(),
         caminho.stat().st_mtime, paginas),
    )
    file_id = conn.execute("SELECT id FROM file WHERE relative_path = ?", (nome,)).fetchone()[0]
    for numero in range(1, paginas + 1):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
            (file_id, numero, f"f. {numero}"),
        )
    conn.commit()


def _criar_janelas(conn, group_key: str, page_count: int, window_size: int, overlap: int) -> None:
    from gclaude_indexer.windows_prep import window_key

    for start, end in window_spans(page_count, window_size, overlap):
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
            " VALUES (?, ?, ?, ?, 'done')",
            (window_key(group_key, start, end), group_key, f"f. {start + 1}", f"f. {end}"),
        )
    conn.commit()


def _contar_janelas_criadas(page_count: int, window_size: int, overlap: int) -> int:
    """Roda `prepare_windows` de verdade sobre um grupo sintético."""
    import tempfile

    with tempfile.TemporaryDirectory() as pasta:
        base = Path(pasta)
        conn = db.connect(base / "project.db")
        db.init_schema(conn)
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256,"
            " group_key, page_count, status) VALUES ('a.pdf', 'a.pdf', 'pdf', 1, 'h',"
            " 'g', ?, 'extracted')",
            (page_count,),
        )
        file_id = conn.execute("SELECT id FROM file").fetchone()[0]
        for numero in range(1, page_count + 1):
            conn.execute(
                "INSERT INTO page (file_id, number, reference, char_count, image_count,"
                " has_table, text) VALUES (?, ?, ?, 1, 0, 0, 'x')",
                (file_id, numero, f"f. {numero}"),
            )
        conn.commit()

        from gclaude_indexer.windows_prep import prepare_windows

        config = ProjectConfig(
            name="a", source_folder=str(base), output_folder=str(base),
            pages_per_window=window_size, overlap=overlap,
        )
        prepare_windows(conn, config)
        return conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "janela or divergencia or plano or contagem"`
Expected: FAIL — `ImportError: cannot import name 'first_affected_window'`.

- [ ] **Step 3: Implementar**

Acrescentar a `gclaude_indexer/update_plan.py`:

```python
from .paths import natural_sort_key
from .scanning import derive_group_key
from .windows_prep import window_spans


@dataclass(frozen=True)
class GroupInvalidation:
    group_key: str
    first_divergent_page: int
    first_affected_window: int
    windows_discarded: int
    windows_kept: int
    files_to_renumber: tuple[str, ...]


@dataclass(frozen=True)
class UpdatePlan:
    new: tuple[FileChange, ...]
    changed: tuple[FileChange, ...]
    removed: tuple[FileChange, ...]
    groups: tuple[GroupInvalidation, ...]
    unchanged_count: int
    fingerprint: str

    @property
    def is_empty(self) -> bool:
        return not (self.new or self.changed or self.removed)

    @property
    def files_needing_ocr(self) -> int:
        """Only these pay OCR again. The files that merely get renumbered
        are re-read from `<output>/converted/`."""
        return len(self.new) + len(self.changed)

    @property
    def windows_to_reclassify(self) -> int:
        """Windows certain to go back to the model.

        Exact, and deliberately not the whole answer: the windows a *new*
        document will add depend on its page count, which nothing knows
        before extraction. The screen says so rather than estimating.
        """
        return sum(group.windows_discarded for group in self.groups)


def first_affected_window(
    old_spans: list[tuple[int, int]], first_divergent_page: int
) -> int:
    """Index of the first window that must be discarded.

    Two conditions, not one. The obvious one is the window that covers the
    first divergent page. The one that is easy to miss: the **last**
    window of a group is clamped by the total page count
    (`min(start + window_size, page_count)`), so it can change extent even
    when no page before it moved — which is exactly what happens when a
    document is appended to the end of the group.
    """
    if not old_spans:
        return 0

    for index, (_start, end) in enumerate(old_spans):
        if end > first_divergent_page:
            return index
    return len(old_spans) - 1


def _divergence_page(stored: list[tuple[str, int]], intended: list[str], changed: set[str]) -> int:
    """First page position at which the group stops matching the index.

    `stored` is `(relative_path, page_count)` in the group's current page
    order; `intended` the paths the group will have, naturally sorted.
    """
    page_offset = 0
    for index, (relative_path, page_count) in enumerate(stored):
        if index >= len(intended):
            return page_offset
        if intended[index] != relative_path or relative_path in changed:
            return page_offset
        page_offset += page_count or 0

    return page_offset


def build_update_plan(conn, config: ProjectConfig) -> UpdatePlan:
    """The whole plan: what changed, and what invalidating it would cost."""
    changes, unchanged, fingerprint = detect_changes(conn, config)

    by_kind: dict[str, list[FileChange]] = {"new": [], "changed": [], "removed": []}
    for change in changes:
        by_kind[change.kind].append(change)

    changed_paths = {change.relative_path for change in by_kind["changed"]}
    removed_paths = {change.relative_path for change in by_kind["removed"]}

    source_dir = Path(config.source_folder).resolve()
    stored_rows = conn.execute(
        "SELECT relative_path, group_key, page_count FROM file"
        " WHERE group_key IS NOT NULL AND status != 'duplicate'"
    ).fetchall()

    stored_by_group: dict[str, list[tuple[str, int]]] = {}
    for row in stored_rows:
        stored_by_group.setdefault(row["group_key"], []).append(
            (row["relative_path"], row["page_count"] or 0)
        )
    for group_key in stored_by_group:
        stored_by_group[group_key].sort(key=lambda pair: natural_sort_key(pair[0]))

    intended_by_group: dict[str, list[str]] = {}
    for relative_path, group_key in _intended_membership(
        conn, config, source_dir, by_kind["new"], removed_paths
    ):
        intended_by_group.setdefault(group_key, []).append(relative_path)
    for group_key in intended_by_group:
        intended_by_group[group_key].sort(key=natural_sort_key)

    groups: list[GroupInvalidation] = []
    for group_key, stored in stored_by_group.items():
        intended = intended_by_group.get(group_key, [])
        touched = any(
            path in changed_paths or path in removed_paths for path, _ in stored
        ) or intended != [path for path, _ in stored]
        if not touched:
            continue

        divergent_page = _divergence_page(stored, intended, changed_paths)
        page_count = sum(count for _, count in stored)
        old_spans = window_spans(page_count, config.pages_per_window, config.overlap)
        affected = first_affected_window(old_spans, divergent_page)

        renumber = tuple(
            path
            for path, _ in stored
            if path not in changed_paths and path not in removed_paths
        )

        groups.append(
            GroupInvalidation(
                group_key=group_key,
                first_divergent_page=divergent_page,
                first_affected_window=affected,
                windows_discarded=max(0, len(old_spans) - affected),
                windows_kept=affected,
                files_to_renumber=renumber,
            )
        )

    return UpdatePlan(
        new=tuple(by_kind["new"]),
        changed=tuple(by_kind["changed"]),
        removed=tuple(by_kind["removed"]),
        groups=tuple(groups),
        unchanged_count=unchanged,
        fingerprint=fingerprint,
    )


def _intended_membership(
    conn, config: ProjectConfig, source_dir: Path,
    new_files: list[FileChange], removed_paths: set[str],
) -> list[tuple[str, str]]:
    """`(relative_path, group_key)` the collection will have after the update."""
    members: list[tuple[str, str]] = []

    for row in conn.execute(
        "SELECT relative_path, group_key FROM file"
        " WHERE group_key IS NOT NULL AND status != 'duplicate'"
    ):
        if row["relative_path"] not in removed_paths:
            members.append((row["relative_path"], row["group_key"]))

    for change in new_files:
        group_key = derive_group_key(change.relative_path, source_dir, config)
        if group_key is not None:
            members.append((change.relative_path, group_key))

    return members
```

Nota sobre `files_to_renumber`: a lista é conservadora de propósito. Quem
está antes da divergência não perde as páginas (a Task 7 usa
`first_divergent_page` para decidir), e a lista serve para a tela nomear o
que pode ser relido.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gclaude_indexer/update_plan.py tests/test_phase17.py
git commit -m "feat(update): divergencia por grupo e contagem exata de janelas descartadas"
```

---

### Task 7: `invalidation.py` — aplicar o plano

**Files:**
- Create: `gclaude_indexer/invalidation.py`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: `UpdatePlan`, `GroupInvalidation` (Task 6);
  `windows_prep.window_spans`, `window_key`, `_sanitize_name` (Task 3);
  `paths.resolve_within`.
- Produces:
  - `invalidation.PlanExpired` (exceção).
  - `invalidation.InvalidationResult(windows_deleted, pages_deleted, files_removed, files_reset, files_renumbered)`.
  - `invalidation.apply_update_plan(conn, config, plan, language=None) -> InvalidationResult`.

- [ ] **Step 1: Escrever o teste que falha**

```python
from gclaude_indexer.invalidation import PlanExpired, apply_update_plan


def test_plano_vencido_e_recusado_sem_escrever_nada(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)

    (origem / "b.pdf").write_text("b", encoding="utf-8")  # a pasta mudou

    with pytest.raises(PlanExpired):
        apply_update_plan(conn, config, plano)


def test_o_removido_sai_das_tabelas_e_entra_em_removed_file(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "fica.pdf").write_text("fica", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar_com_paginas(conn, origem, "fica.pdf", paginas=2)
    (origem / "sai.pdf").write_text("sai", encoding="utf-8")
    _registrar_com_paginas(conn, origem, "sai.pdf", paginas=2)
    (origem / "sai.pdf").unlink()
    config = _config(origem, saida)

    apply_update_plan(conn, config, build_update_plan(conn, config))

    assert conn.execute(
        "SELECT COUNT(*) FROM file WHERE relative_path = 'sai.pdf'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 2
    assert conn.execute(
        "SELECT name FROM removed_file"
    ).fetchone()["name"] == "sai.pdf"


def test_quem_mudou_volta_para_discovered_e_quem_so_renumera_para_converted(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    (origem / "b.pdf").write_text("b", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=2)
    _registrar_com_paginas(conn, origem, "b.pdf", paginas=2)
    (origem / "a.pdf").write_text("a corrigido e maior", encoding="utf-8")
    config = _config(origem, saida)

    apply_update_plan(conn, config, build_update_plan(conn, config))

    estados = dict(conn.execute("SELECT relative_path, status FROM file"))
    assert estados["a.pdf"] == "discovered"   # mudou: paga OCR
    assert estados["b.pdf"] == "converted"    # só renumera: relê o convertido


def test_o_txt_da_janela_descartada_some_do_disco(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    (saida / "windows").mkdir(parents=True)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=20)
    _criar_janelas(conn, "g", page_count=20, window_size=16, overlap=2)
    txt = saida / "windows" / "g_j0001-0016.txt"
    txt.write_text("texto velho", encoding="utf-8")
    (origem / "a.pdf").write_text("a corrigido", encoding="utf-8")
    config = _config(origem, saida)

    apply_update_plan(conn, config, build_update_plan(conn, config))

    assert not txt.exists()


def test_falha_no_meio_deixa_o_banco_como_estava(tmp_path, monkeypatch):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    conn = _conn(tmp_path)
    _registrar_com_paginas(conn, origem, "a.pdf", paginas=2)
    (origem / "b.pdf").write_text("b", encoding="utf-8")
    config = _config(origem, saida)
    plano = build_update_plan(conn, config)
    antes = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]

    import gclaude_indexer.invalidation as mod

    def explode(*args, **kwargs):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(mod, "_record_removals", explode)

    with pytest.raises(RuntimeError):
        apply_update_plan(conn, config, plano)

    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == antes
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "vencido or removido or discovered or txt or falha"`
Expected: FAIL — `ModuleNotFoundError: No module named 'gclaude_indexer.invalidation'`.

- [ ] **Step 3: Implementar**

Criar `gclaude_indexer/invalidation.py` com o cabeçalho GPL e:

```python
"""Applying an `UpdatePlan`. The only thing in the project that deletes.

Phase 17. Everything here runs inside one transaction: either the database
ends consistent in the new state, or it stays consistent in the old one.

What it does NOT touch: `item`. `import_items` already wipes and rebuilds
that table on every run, so invalidating it here would be work done twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .paths import resolve_within
from .update_plan import UpdatePlan, build_update_plan
from .windows_prep import _sanitize_name, window_key, window_spans


class PlanExpired(RuntimeError):
    """The folder changed between the diagnosis and the confirmation.

    The plan is a photograph, and Drive keeps syncing while the user reads
    the screen. Applying a stale plan would write one thing having shown
    another.
    """


@dataclass
class InvalidationResult:
    windows_deleted: int = 0
    pages_deleted: int = 0
    files_removed: int = 0
    files_reset: int = 0
    files_renumbered: int = 0


def _record_removals(conn, plan: UpdatePlan) -> int:
    moment = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for change in plan.removed:
        conn.execute(
            "INSERT INTO removed_file (relative_path, name, removed_at) VALUES (?, ?, ?)",
            (change.relative_path, change.name, moment),
        )
    return len(plan.removed)


def apply_update_plan(
    conn, config: ProjectConfig, plan: UpdatePlan, language: str | None = None
) -> InvalidationResult:
    """Invalidates exactly what the plan describes, in one transaction."""
    current = build_update_plan(conn, config)
    if current.fingerprint != plan.fingerprint:
        raise PlanExpired(plan.fingerprint)

    result = InvalidationResult()
    windows_dir = Path(config.output_folder) / "windows"
    doomed_files: list[Path] = []

    try:
        conn.execute("BEGIN")

        for group in plan.groups:
            page_count = conn.execute(
                "SELECT COUNT(*) FROM page JOIN file ON file.id = page.file_id"
                " WHERE file.group_key = ?",
                (group.group_key,),
            ).fetchone()[0]
            base_name = _sanitize_name(group.group_key)
            spans = window_spans(page_count, config.pages_per_window, config.overlap)

            for start, end in spans[group.first_affected_window:]:
                conn.execute(
                    "DELETE FROM window WHERE key = ?", (window_key(base_name, start, end),)
                )
                result.windows_deleted += 1
                # Containment before unlink: the group key can come from a
                # regex over a filename the collection brought in, so the
                # name is data. `resolve_within` refuses anything that
                # would land outside the windows folder.
                try:
                    doomed_files.append(
                        resolve_within(windows_dir, f"{base_name}_j{start + 1:04d}-{end:04d}.txt")
                    )
                except ValueError:
                    # Refused path: the row is gone, the file stays. Better
                    # an orphan text file than a delete outside the folder.
                    continue

        for change in plan.removed:
            row = conn.execute(
                "SELECT id FROM file WHERE relative_path = ?", (change.relative_path,)
            ).fetchone()
            if row is None:
                continue
            result.pages_deleted += conn.execute(
                "DELETE FROM page WHERE file_id = ?", (row["id"],)
            ).rowcount
            conn.execute("DELETE FROM file WHERE id = ?", (row["id"],))
        result.files_removed = _record_removals(conn, plan)

        for change in plan.changed:
            row = conn.execute(
                "SELECT id FROM file WHERE relative_path = ?", (change.relative_path,)
            ).fetchone()
            if row is None:
                continue
            result.pages_deleted += conn.execute(
                "DELETE FROM page WHERE file_id = ?", (row["id"],)
            ).rowcount
            conn.execute(
                "UPDATE file SET status = 'discovered', page_count = NULL, error = NULL"
                " WHERE id = ?",
                (row["id"],),
            )
            result.files_reset += 1

        untouched = {change.relative_path for change in plan.changed}
        for group in plan.groups:
            for relative_path in group.files_to_renumber:
                if relative_path in untouched:
                    continue
                row = conn.execute(
                    "SELECT id FROM file WHERE relative_path = ?", (relative_path,)
                ).fetchone()
                if row is None:
                    continue
                deleted = conn.execute(
                    "DELETE FROM page WHERE file_id = ? AND number > 0", (row["id"],)
                ).rowcount
                if deleted:
                    result.pages_deleted += deleted
                    # Back to 'converted', not 'discovered': the OCR output
                    # is still in <output>/converted/, so extraction re-reads
                    # it and renumbers without running OCR again.
                    conn.execute(
                        "UPDATE file SET status = 'converted' WHERE id = ?", (row["id"],)
                    )
                    result.files_renumbered += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Only after the database committed: a file removed before the commit
    # could be lost to a rollback that keeps the row.
    for path in doomed_files:
        path.unlink(missing_ok=True)

    record_event(
        conn, "scan", "info", "log.update.applied",
        {
            "windows": result.windows_deleted, "removed": result.files_removed,
            "reset": result.files_reset, "renumbered": result.files_renumbered,
        },
        language=language,
    )
    return result
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Acrescentar a chave de log nos três idiomas**

Em `gclaude_indexer/i18n.py`, no bloco pt (perto de `"log.scan.summary"`),
no bloco en e no bloco es:

```python
        "log.update.applied": (
            "atualização aplicada: {windows} janelas descartadas, {removed} documentos"
            " removidos, {reset} para reprocessar, {renumbered} para renumerar"
        ),
```

```python
        "log.update.applied": (
            "update applied: {windows} windows discarded, {removed} documents removed,"
            " {reset} to reprocess, {renumbered} to renumber"
        ),
```

```python
        "log.update.applied": (
            "actualización aplicada: {windows} ventanas descartadas, {removed} documentos"
            " eliminados, {reset} para reprocesar, {renumbered} para renumerar"
        ),
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: nenhuma regressão.

- [ ] **Step 7: Commit**

```bash
git add gclaude_indexer/invalidation.py gclaude_indexer/i18n.py tests/test_phase17.py
git commit -m "feat(update): invalidacao transacional com contencao de caminho antes de apagar"
```

---

### Task 8: A janela recriada grava o texto novo

Defeito latente que só a atualização revela: `prepare_windows` grava o
`.txt` apenas `if not file_path.exists()`, e o nome do arquivo vem das
posições. Um documento corrigido **sem mudar de número de páginas** produz
a mesma posição e o mesmo nome, e o texto velho sobreviveria ao lado da
classificação nova.

**Files:**
- Modify: `gclaude_indexer/windows_prep.py:125-127`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: Task 3.
- Produces: nenhuma assinatura nova.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_a_janela_recriada_grava_o_texto_novo_mesmo_com_o_mesmo_nome(tmp_path):
    from gclaude_indexer.windows_prep import prepare_windows

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, group_key,"
        " page_count, status) VALUES ('a.pdf', 'a.pdf', 'pdf', 1, 'h', 'g', 2, 'extracted')"
    )
    file_id = conn.execute("SELECT id FROM file").fetchone()[0]
    for numero in (1, 2):
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count,"
            " has_table, text) VALUES (?, ?, ?, 5, 0, 0, 'TEXTO NOVO')",
            (file_id, numero, f"f. {numero}"),
        )
    conn.commit()
    config = ProjectConfig(
        name="a", source_folder=str(tmp_path), output_folder=str(saida),
        pages_per_window=16, overlap=2,
    )
    velho = saida / "windows" / "g_j0001-0002.txt"
    velho.parent.mkdir(parents=True, exist_ok=True)
    velho.write_text("TEXTO VELHO", encoding="utf-8")

    prepare_windows(conn, config)

    assert "TEXTO NOVO" in velho.read_text(encoding="utf-8")
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py::test_a_janela_recriada_grava_o_texto_novo_mesmo_com_o_mesmo_nome -v`
Expected: FAIL — o arquivo ainda contém `TEXTO VELHO`.

- [ ] **Step 3: Implementar**

Em `prepare_windows`, o bloco que decide se a linha é nova já existe.
Guardar essa decisão e usá-la na escrita. Antes:

```python
            if conn.execute("SELECT 1 FROM window WHERE key = ?", (key,)).fetchone():
                result.existing += 1
            else:
                conn.execute(...)
                conn.commit()
                result.created += 1

            file_path = windows_dir / f"{base_name}_j{start + 1:04d}-{end:04d}.txt"
            if not file_path.exists():
                _write_window_file(file_path, key, group_key, start_ref, end_ref, page_block)
```

Depois:

```python
            already_there = conn.execute(
                "SELECT 1 FROM window WHERE key = ?", (key,)
            ).fetchone()
            if already_there:
                result.existing += 1
            else:
                conn.execute(...)
                conn.commit()
                result.created += 1

            file_path = windows_dir / f"{base_name}_j{start + 1:04d}-{end:04d}.txt"
            # Written unconditionally when this call creates the row
            # (Phase 17): a corrected document with the same page count
            # produces the same position and therefore the same filename,
            # and `if not exists` would have left the old text in place
            # next to the new classification.
            if not already_there or not file_path.exists():
                _write_window_file(file_path, key, group_key, start_ref, end_ref, page_block)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gclaude_indexer/windows_prep.py tests/test_phase17.py
git commit -m "fix(windows): janela recriada grava o texto novo em vez de manter o antigo"
```

---

### Task 9: Documentos removidos no `review.md`

**Files:**
- Modify: `gclaude_indexer/artifacts.py:227-296`, `gclaude_indexer/i18n.py`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: tabela `removed_file` (Task 1), escrita pela Task 7.
- Produces: seção nova no `review.md`. Nenhuma assinatura muda.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_o_review_lista_os_documentos_removidos(tmp_path):
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    conn.execute(
        "INSERT INTO removed_file (relative_path, name, removed_at)"
        " VALUES ('velho.pdf', 'velho.pdf', '2026-09-12T10:00:00+00:00')"
    )
    conn.commit()
    config = ProjectConfig(name="a", source_folder=str(tmp_path), output_folder=str(saida))

    caminho = generate_review_md(conn, config, "pt")
    texto = caminho.read_text(encoding="utf-8")

    assert "velho.pdf" in texto
    assert "2026-09-12T10:00:00+00:00" in texto


def test_sem_remocoes_o_review_diz_que_nao_houve(tmp_path):
    from gclaude_indexer.artifacts import generate_review_md

    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(tmp_path)
    config = ProjectConfig(name="a", source_folder=str(tmp_path), output_folder=str(saida))

    texto = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")

    assert "Nenhum documento removido" in texto


def test_a_secao_de_removidos_existe_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave in (
            "artifact.review.removed_section",
            "artifact.review.removed_none",
        ):
            texto = translate(idioma, chave)
            assert texto and not texto.startswith("artifact."), f"{idioma}/{chave}"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "review or removidos"`
Expected: FAIL — a string não aparece no arquivo.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/artifacts.py`, dentro de `generate_review_md`, depois
da consulta `failures` acrescentar:

```python
    removals = conn.execute(
        "SELECT name, relative_path, removed_at FROM removed_file ORDER BY removed_at DESC, name"
    ).fetchall()
```

E depois do bloco `failures_section`, antes de `errors_section`:

```python
    lines += ["", f"## {t('artifact.review.removed_section')}"]
    if not removals:
        lines.append(t("artifact.review.removed_none"))
    else:
        for removal in removals:
            lines.append(f"- `{removal['relative_path']}` ({removal['removed_at']})")
```

Em `gclaude_indexer/i18n.py`, junto das outras chaves
`artifact.review.*`, nos três blocos:

```python
        "artifact.review.removed_section": "Documentos removidos da pasta de origem",
        "artifact.review.removed_none": "Nenhum documento removido.",
```

```python
        "artifact.review.removed_section": "Documents removed from the source folder",
        "artifact.review.removed_none": "No documents removed.",
```

```python
        "artifact.review.removed_section": "Documentos eliminados de la carpeta de origen",
        "artifact.review.removed_none": "Ningún documento eliminado.",
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gclaude_indexer/artifacts.py gclaude_indexer/i18n.py tests/test_phase17.py
git commit -m "feat(review): relata no review.md os documentos que sairam da pasta"
```

---

### Task 10: Rotas, tela de confirmação e aviso na execução

**Files:**
- Create: `gclaude_indexer/web/templates/update_project.html`
- Modify: `gclaude_indexer/web/app.py` (três rotas novas),
  `gclaude_indexer/web/templates/run.html:12` (âncora do aviso),
  `gclaude_indexer/i18n.py`
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: `build_update_plan`, `apply_update_plan`,
  `SourceFolderUnavailable`, `PlanExpired`.
- Produces: `GET /projects/{id}/update/banner`, `GET /projects/{id}/update`,
  `POST /projects/{id}/update`.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_o_diagnostico_nao_escreve_no_banco(tmp_path, monkeypatch):
    """A rota GET roda a cada abertura da tela. Se escrevesse, abrir um
    projeto o modificaria."""
    cliente, projeto_id, conn = _app_com_projeto(tmp_path)
    antes = conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]

    resposta = cliente.get(f"/projects/{projeto_id}/update")

    assert resposta.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM file").fetchone()[0] == antes


def test_o_post_com_plano_vencido_e_recusado(tmp_path):
    cliente, projeto_id, _ = _app_com_projeto(tmp_path)

    resposta = cliente.post(
        f"/projects/{projeto_id}/update", data={"fingerprint": "impressao-que-nao-existe"}
    )

    assert resposta.status_code == 409


def test_o_aviso_nao_aparece_quando_nada_mudou(tmp_path):
    cliente, projeto_id, _ = _app_com_projeto(tmp_path)

    corpo = cliente.get(f"/projects/{projeto_id}/update/banner").text

    assert corpo.strip() == ""


def test_todas_as_chaves_da_atualizacao_existem_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    chaves = (
        "update.title", "update.banner", "update.new", "update.changed",
        "update.removed", "update.files_ocr", "update.windows_discarded",
        "update.windows_kept", "update.new_windows_unknown", "update.confirm",
        "update.cancel", "update.nothing_changed", "update.source_unavailable",
        "update.plan_expired",
    )
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            texto = translate(idioma, chave)
            assert texto and not texto.startswith("update."), f"{idioma}/{chave}"
```

Auxiliar, no mesmo arquivo:

```python
def _app_com_projeto(tmp_path):
    """Servidor de teste com um projeto registrado e uma pasta de origem."""
    from fastapi.testclient import TestClient

    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.web.app import app

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")

    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES ('acervo', ?, ?, '{}', '2026-09-12T00:00:00')",
        (str(origem), str(saida)),
    )
    conn.commit()
    from gclaude_indexer.scanning import scan

    scan(conn, _config(origem, saida))

    entry = register_project("acervo", str(saida))
    return TestClient(app), entry.id, conn
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/test_phase17.py -v -k "diagnostico or vencido or aviso or chaves"`
Expected: FAIL — 404 nas rotas.

- [ ] **Step 3: Implementar as rotas**

Em `gclaude_indexer/web/app.py`, depois de `run_screen`:

```python
@app.get("/projects/{project_id}/update/banner", response_class=HTMLResponse)
def update_banner(request: Request, project_id: int):
    """The "the folder changed" notice on the Execution screen.

    Fetched by HTMX after the page renders, never before it: on a large
    Drive-synced collection the walk takes seconds, and paying them before
    the first pixel would trade one problem for another. An unreachable
    source folder renders nothing — the screen is not the place to shout
    about a disconnected drive, and `SourceFolderUnavailable` never
    becomes a removal proposal.
    """
    with _open_project(project_id) as (entry, config, conn):
        try:
            plan = build_update_plan(conn, config)
        except SourceFolderUnavailable:
            return HTMLResponse("")
        if plan.is_empty:
            return HTMLResponse("")
        return render(
            request, "_update_banner.html",
            {"project": entry, "plan": plan, "config": config},
        )


@app.get("/projects/{project_id}/update", response_class=HTMLResponse)
def update_screen(request: Request, project_id: int):
    """The confirmation. Read-only: it never writes to the project."""
    with _open_project(project_id) as (entry, config, conn):
        try:
            plan = build_update_plan(conn, config)
        except SourceFolderUnavailable:
            return render(
                request, "update_project.html",
                {"project": entry, "config": config, "plan": None,
                 "error": "update.source_unavailable"},
                status_code=409,
            )
        return render(
            request, "update_project.html",
            {"project": entry, "config": config, "plan": plan, "error": None},
        )


@app.post("/projects/{project_id}/update", response_class=HTMLResponse)
async def update_apply(request: Request, project_id: int):
    """Applies the plan, then sends the user to the Execution screen.

    The stale-plan check lives in `apply_update_plan`, not here: it is the
    invariant of the invalidation itself, and putting it there keeps it
    testable without a web server and keeps this route from walking the
    folder a third time. The route rebuilds the plan the form refers to,
    hands it over, and turns a refusal into a screen.
    """
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    form = await request.form()

    with _open_project(project_id) as (entry, config, conn):
        try:
            plan = build_update_plan(conn, config)
        except SourceFolderUnavailable:
            return render(
                request, "update_project.html",
                {"project": entry, "config": config, "plan": None,
                 "error": "update.source_unavailable"},
                status_code=409,
            )

        # What the user actually saw. If the folder moved since the screen
        # rendered, this no longer matches the plan just rebuilt.
        seen = str(form.get("fingerprint", ""))
        try:
            apply_update_plan(
                conn, config, replace(plan, fingerprint=seen), language
            )
        except PlanExpired:
            return render(
                request, "update_project.html",
                {"project": entry, "config": config, "plan": plan,
                 "error": "update.plan_expired"},
                status_code=409,
            )

    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)
```

`replace` vem de `dataclasses` — `UpdatePlan` é `frozen=True`, então trocar
só a impressão digital exige uma cópia. Acrescentar ao topo de `app.py`:

```python
from dataclasses import replace
```

**Concorrência, sem trabalho extra.** As três rotas usam `_open_project`,
que já verifica o sinal de sincronização incompleta e o bloqueio da outra
máquina antes de liberar o projeto (`app.py:209-234`). A exigência da spec
(§10, "Concorrência") está atendida por usar o mesmo caminho de abertura
que a execução usa. Não acrescente bloqueio nenhum.

Importes no topo de `app.py`:

```python
from ..invalidation import PlanExpired, apply_update_plan
from ..update_plan import SourceFolderUnavailable, build_update_plan
```

- [ ] **Step 4: Implementar os templates**

`gclaude_indexer/web/templates/_update_banner.html`:

```html
<div class="notice">
  {{ t('update.banner',
        new=plan.new | length,
        changed=plan.changed | length,
        removed=plan.removed | length) }}
  <a href="/projects/{{ project.id }}/update" class="button-primary">
    {{ t('update.title') }}
  </a>
</div>
```

`gclaude_indexer/web/templates/update_project.html`:

```html
{% extends "base.html" %}
{% import "_macros.html" as m %}
{% block title %}{{ t('update.title') }} — {{ config.name }}{% endblock %}
{% block content %}
<h1>{{ t('update.title') }} — {{ config.name }}</h1>
<p class="breadcrumb">
  <a href="/projects/{{ project.id }}/run">{{ m.icon('back') }} {{ t('update.cancel') }}</a>
</p>

{% if error %}
  <p class="error">{{ t(error) }}</p>
{% elif plan.is_empty %}
  <p>{{ t('update.nothing_changed') }}</p>
{% else %}
  <h2>{{ t('update.new') }} ({{ plan.new | length }})</h2>
  <ul>{% for change in plan.new %}<li><code>{{ change.relative_path }}</code></li>{% endfor %}</ul>

  <h2>{{ t('update.changed') }} ({{ plan.changed | length }})</h2>
  <ul>{% for change in plan.changed %}<li><code>{{ change.relative_path }}</code></li>{% endfor %}</ul>

  <h2>{{ t('update.removed') }} ({{ plan.removed | length }})</h2>
  <ul>{% for change in plan.removed %}<li><code>{{ change.relative_path }}</code></li>{% endfor %}</ul>

  <h2>{{ t('update.cost_title') }}</h2>
  <ul>
    <li>{{ t('update.files_ocr', n=plan.files_needing_ocr) }}</li>
    <li>{{ t('update.windows_discarded', n=plan.windows_to_reclassify) }}</li>
    <li>{{ t('update.windows_kept', n=plan.groups | sum(attribute='windows_kept')) }}</li>
    <li>{{ t('update.new_windows_unknown') }}</li>
  </ul>

  <form method="post" action="/projects/{{ project.id }}/update">
    <input type="hidden" name="fingerprint" value="{{ plan.fingerprint }}">
    <button type="submit" class="button-primary">{{ t('update.confirm') }}</button>
  </form>
{% endif %}
{% endblock %}
```

Em `run.html`, logo depois do bloco `<p class="breadcrumb">…</p>`:

```html
<div id="update-banner"
     hx-get="/projects/{{ project.id }}/update/banner"
     hx-trigger="load"
     hx-swap="innerHTML"></div>
```

- [ ] **Step 5: Implementar as chaves de i18n**

Nos três blocos de `gclaude_indexer/i18n.py`. Bloco pt:

```python
        "update.title": "Atualizar acervo",
        "update.banner": (
            "A pasta de origem mudou: {new} novos, {changed} alterados, {removed} removidos."
        ),
        "update.new": "Documentos novos",
        "update.changed": "Documentos alterados",
        "update.removed": "Documentos removidos",
        "update.cost_title": "O que a atualização vai custar",
        "update.files_ocr": "{n} arquivos passarão por OCR novamente.",
        "update.windows_discarded": "{n} janelas serão reclassificadas.",
        "update.windows_kept": "{n} janelas serão preservadas com a classificação atual.",
        "update.new_windows_unknown": (
            "Os documentos novos acrescentam janelas além dessas. Quantas, só se sabe"
            " depois da leitura das páginas."
        ),
        "update.confirm": "Atualizar",
        "update.cancel": "Voltar sem atualizar",
        "update.nothing_changed": "A pasta de origem está igual ao índice. Nada a fazer.",
        "update.source_unavailable": (
            "A pasta de origem não pode ser lida. Verifique se a unidade está conectada"
            " e se a pasta não foi movida. Nada foi alterado."
        ),
        "update.plan_expired": (
            "A pasta mudou enquanto esta tela estava aberta. Nada foi alterado."
            " Refaça o diagnóstico."
        ),
```

Bloco en:

```python
        "update.title": "Update collection",
        "update.banner": (
            "The source folder changed: {new} new, {changed} changed, {removed} removed."
        ),
        "update.new": "New documents",
        "update.changed": "Changed documents",
        "update.removed": "Removed documents",
        "update.cost_title": "What the update will cost",
        "update.files_ocr": "{n} files will go through OCR again.",
        "update.windows_discarded": "{n} windows will be reclassified.",
        "update.windows_kept": "{n} windows keep their current classification.",
        "update.new_windows_unknown": (
            "New documents add windows on top of those. How many is not known until"
            " their pages have been read."
        ),
        "update.confirm": "Update",
        "update.cancel": "Back without updating",
        "update.nothing_changed": "The source folder matches the index. Nothing to do.",
        "update.source_unavailable": (
            "The source folder cannot be read. Check that the drive is connected and"
            " the folder has not been moved. Nothing was changed."
        ),
        "update.plan_expired": (
            "The folder changed while this screen was open. Nothing was changed."
            " Run the diagnosis again."
        ),
```

Bloco es:

```python
        "update.title": "Actualizar acervo",
        "update.banner": (
            "La carpeta de origen cambió: {new} nuevos, {changed} modificados,"
            " {removed} eliminados."
        ),
        "update.new": "Documentos nuevos",
        "update.changed": "Documentos modificados",
        "update.removed": "Documentos eliminados",
        "update.cost_title": "Lo que costará la actualización",
        "update.files_ocr": "{n} archivos pasarán por OCR de nuevo.",
        "update.windows_discarded": "{n} ventanas se reclasificarán.",
        "update.windows_kept": "{n} ventanas conservan su clasificación actual.",
        "update.new_windows_unknown": (
            "Los documentos nuevos añaden ventanas además de esas. Cuántas solo se sabe"
            " después de leer sus páginas."
        ),
        "update.confirm": "Actualizar",
        "update.cancel": "Volver sin actualizar",
        "update.nothing_changed": "La carpeta de origen coincide con el índice. Nada que hacer.",
        "update.source_unavailable": (
            "No se puede leer la carpeta de origen. Verifique que la unidad esté conectada"
            " y que la carpeta no se haya movido. No se cambió nada."
        ),
        "update.plan_expired": (
            "La carpeta cambió mientras esta pantalla estaba abierta. No se cambió nada."
            " Vuelva a hacer el diagnóstico."
        ),
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_phase17.py -v`
Expected: PASS.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: nenhuma regressão.

- [ ] **Step 8: Commit**

```bash
git add gclaude_indexer/web/app.py gclaude_indexer/web/templates/ gclaude_indexer/i18n.py tests/test_phase17.py
git commit -m "feat(web): tela de confirmacao da atualizacao e aviso na tela de execucao"
```

---

### Task 11: O oráculo — atualizar tem de igualar reindexar

O teste que prova a funcionalidade inteira. Se ele passa, a atualização
incremental está correta por definição. Se falha, um dos testes das tarefas
1 a 10 explica por quê.

**Files:**
- Test: `tests/test_phase17.py`

**Interfaces:**
- Consumes: tudo das tarefas 1 a 10.
- Produces: nada.

- [ ] **Step 1: Escrever o teste**

```python
def _etapas_depois_do_scan(conn, config: ProjectConfig) -> None:
    """Da conversão aos artefatos. Mesma ordem de `background_runs.STEP_ORDER`.

    Serve aos dois lados do oráculo: depois do `scan`, num projeto novo, e
    depois da invalidação, num projeto atualizado — onde o `scan` não
    precisa rodar, porque a invalidação já pôs os arquivos nos estados que
    estas etapas procuram.
    """
    from gclaude_indexer.artifacts import generate_all_artifacts
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.import_items import import_and_consolidate
    from gclaude_indexer.orchestrator import run_classification
    from gclaude_indexer.windows_prep import prepare_windows

    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    run_classification(conn, config)
    import_and_consolidate(conn, config)
    generate_all_artifacts(conn, config, "pt")


def _rodar_pipeline_completo(origem: Path, saida: Path):
    """Pipeline inteiro com o engine `rules`: determinístico, sem LLM, sem custo."""
    from gclaude_indexer.scanning import scan

    config = ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="all_together", extensions=["all"], classification_engine="rules",
    )
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)

    scan(conn, config)
    _etapas_depois_do_scan(conn, config)
    return conn, config


def _sem_carimbo(texto: str) -> str:
    """Remove a linha de data, a única coisa que difere legitimamente."""
    return "\n".join(
        linha for linha in texto.splitlines()
        if "2026-" not in linha and "20" not in linha[:4]
    )


def test_atualizar_produz_o_mesmo_que_reindexar_do_zero(tmp_path):
    """O critério de correção da funcionalidade inteira.

    Um acervo é montado e indexado. Depois um documento é acrescentado,
    outro alterado e um terceiro removido, e o acervo é atualizado. Em
    paralelo, um projeto novo é construído do zero sobre a pasta final. Os
    quatro artefatos têm de ser iguais.
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "01-contrato.txt").write_text("Contrato de locação.\n" * 40, encoding="utf-8")
    (origem / "02-recibo.txt").write_text("Recibo de pagamento.\n" * 40, encoding="utf-8")
    (origem / "03-carta.txt").write_text("Carta de cobrança.\n" * 40, encoding="utf-8")

    incremental = tmp_path / "incremental"
    incremental.mkdir()
    conn, config = _rodar_pipeline_completo(origem, incremental)

    # A pasta muda: um novo, um alterado, um removido.
    (origem / "04-aditivo.txt").write_text("Aditivo contratual.\n" * 40, encoding="utf-8")
    (origem / "02-recibo.txt").write_text("Recibo corrigido.\n" * 55, encoding="utf-8")
    (origem / "03-carta.txt").unlink()

    plano = build_update_plan(conn, config)
    apply_update_plan(conn, config, plano)
    # Sem `scan`: a invalidação já pôs cada arquivo no estado que as
    # etapas seguintes procuram. Mas o scan precisa rodar para que os
    # arquivos *novos* entrem na tabela — ele é a primeira etapa da
    # reexecução, exatamente como na tela de execução.
    from gclaude_indexer.scanning import scan

    scan(conn, config)
    _etapas_depois_do_scan(conn, config)

    # E o mesmo acervo, indexado do zero.
    completo = tmp_path / "completo"
    completo.mkdir()
    _rodar_pipeline_completo(origem, completo)

    for nome in ("index.md", "timeline.md", "review.md", "project_instructions.md"):
        atualizado = _sem_carimbo((incremental / nome).read_text(encoding="utf-8"))
        do_zero = _sem_carimbo((completo / nome).read_text(encoding="utf-8"))
        if nome == "review.md":
            # O incremental sabe da remoção; o do zero nunca viu o arquivo.
            assert "03-carta.txt" in atualizado
            continue
        assert atualizado == do_zero, f"{nome} diverge"


def test_reexecutar_sem_mudanca_nao_reprocessa_nada(tmp_path):
    """A incrementalidade que já existia por acidente passa a ter contrato."""
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.txt").write_text("Documento.\n" * 40, encoding="utf-8")
    saida = tmp_path / "saida"
    saida.mkdir()
    conn, config = _rodar_pipeline_completo(origem, saida)
    janelas_antes = dict(conn.execute("SELECT key, status FROM window"))

    plano = build_update_plan(conn, config)

    assert plano.is_empty
    assert plano.groups == ()
    assert dict(conn.execute("SELECT key, status FROM window")) == janelas_antes
```

Não há auxiliar de classificação a escrever: `run_classification`
(`orchestrator.py:54`) já resolve o engine a partir de
`config.classification_engine`, que os dois lados do oráculo fixam em
`"rules"`, e só processa janelas `pending`.

- [ ] **Step 2: Rodar**

Run: `python -m pytest tests/test_phase17.py -v -k "oraculo or zero or reexecutar"`
Expected: PASS. Se falhar, o teste que falhar entre as tarefas 1 e 10
aponta a causa; não conserte aqui.

- [ ] **Step 3: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: nenhuma regressão, e a contagem total sobe em relação aos 456
testes da 1.0.1.

- [ ] **Step 4: Revisão de segurança antes de fechar**

```
- [ ] Nenhum segredo, senha ou token escrito no código
- [ ] Toda consulta parametrizada (nenhuma f-string em SQL)
- [ ] Todo caminho apagado passou por `resolve_within` antes do unlink
- [ ] Erro fecha: `SourceFolderUnavailable` nega, nunca propõe remoção
- [ ] Exceção na invalidação faz rollback e não deixa transação aberta
- [ ] Nada renomeado de que outro módulo dependa sem atualizar o uso
- [ ] Todo texto visível existe nos três idiomas
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase17.py
git commit -m "test: atualizar incrementalmente produz o mesmo que reindexar do zero"
```

---

## Como testar à mão, no fim

1. Abra o aplicativo pelo atalho e crie um projeto pequeno, com cinco ou
   seis documentos numa pasta de teste. Rode todas as etapas até o fim.
2. Na pasta de origem, acrescente um documento, edite outro e apague um
   terceiro.
3. Volte ao projeto. A tela de execução deve mostrar o aviso de que a
   pasta mudou, alguns segundos depois de a página aparecer.
4. Clique em **Atualizar acervo**. Confira que os três documentos estão
   listados pelo nome e que os números de custo aparecem.
5. Confirme. Rode as etapas. O `index.md` tem de conter o documento novo,
   a versão corrigida do alterado, e não pode conter o apagado. O
   `review.md` tem de listar o apagado na seção de removidos.
6. **O caso que mais importa:** desconecte a unidade da pasta de origem (ou
   renomeie a pasta) e abra o projeto. Nenhum aviso de remoção pode
   aparecer. A tela de atualização, se aberta à mão, tem de dizer que a
   pasta não pode ser lida.

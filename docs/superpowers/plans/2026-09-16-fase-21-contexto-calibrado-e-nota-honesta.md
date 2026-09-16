# Fase 21 — Contexto calibrado e nota honesta (plano de implementação)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o GClaude Indexer classificar as janelas densas que hoje entram cegas no índice, e fazer a nota de qualidade dizer a verdade sobre o que foi classificado.

**Architecture:** Três frentes independentes no código, mas dependentes na avaliação. A medição é corrigida primeiro, para haver linha de base honesta (89 é falso; 83 é o valor real da corrida atual). Depois a classificação — calibração da razão caracteres/token com `prompt_eval_count`, detecção de truncamento pelos dois lados da telemetria, e escada de retentativa com subdivisão no teto da placa. Por último os artefatos de consulta.

**Tech Stack:** Python 3.12, SQLite, Ollama HTTP API, pytest, Jinja2, Inno Setup 6.

**Spec:** `docs/superpowers/specs/2026-09-16-fase-21-contexto-calibrado-e-nota-honesta-design.md`

## Global Constraints

- Branch: `fix/razao-chars-token`, a partir de `origin/main` (v1.3.1, commit `05c80ac`).
- Python dos testes: `%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe -B -m pytest` — o Python global não tem pytest.
- Suíte na linha de base: **618 testes passando**. Nenhuma tarefa pode reduzir esse número.
- Toda mensagem nova de log ou de interface entra nos **três** idiomas de `gclaude_indexer/i18n.py` (pt-BR, en, es). O arquivo tem três blocos; a chave precisa existir nos três.
- Comentários e docstrings novos em inglês nos módulos que já são em inglês; os que já estão em português (trechos de `engine_local.py`) seguem em português. Seguir o arquivo, não uma regra global.
- Nada de mexer em `_PAGE_PROMPT`, em `_group_pages_into_items` como garantia de cobertura, em `chars_per_page`/`pages_per_window`, nem no modo CPU (`num_gpu == 0`).
- Commits frequentes, um por tarefa, com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` ao final.
- A entrega termina com o instalador compilado e publicado (Tarefa 11). Commit sem `.exe` publicado não é entrega.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefas |
|---|---|---|
| `gclaude_indexer/engine_local.py` | confiança da peça, telemetria, calibração, retentativa, subdivisão | 1, 4, 5, 6, 7 |
| `gclaude_indexer/quality.py` | cobertura por folha e por grupo, cobertura classificada | 2, 3 |
| `gclaude_indexer/artifacts.py` | página física na linha, índice por grupo | 8, 9 |
| `gclaude_indexer/claude_package.py` | pacote do Projeto com os índices por grupo | 10 |
| `gclaude_indexer/i18n.py` | chaves novas nos três idiomas | 3, 6, 9 |
| `gclaude_indexer/web/templates/result.html` | páginas classificadas na tela de resultado | 3 |
| `tests/test_phase21.py` | **criar** — todos os testes desta fase | 1–10 |

---

# Parte 1 — Medição honesta

Entra primeiro. Sem ela não há como saber se o resto funcionou.

---

### Task 1: A página sem linha do modelo recebe confiança `low`

Hoje `confianca = "high" if dados.get("type") and dados.get("detail") else "medium"`. O `dados` vazio — o modelo não disse nada sobre a página — cai no mesmo `medium` de uma linha só incompleta. É por isso que a corrida fechou em `baixa=0` com 612 peças cegas.

**Files:**
- Modify: `gclaude_indexer/engine_local.py:797`
- Test: `tests/test_phase21.py` (criar)

**Interfaces:**
- Consumes: `_group_pages_into_items(pages, rows, model_engine="local") -> list[ClassifiedItem]`, `WindowPage(reference, file_name, text, has_table, image_count)`
- Produces: nenhuma assinatura nova. A peça cujas páginas não têm linha do modelo passa a sair com `confidence == "low"`.

- [ ] **Step 1: Criar o arquivo de teste com o cabeçalho e o helper de página**

Criar `tests/test_phase21.py`:

```python
# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 21: o contexto calibrado e a nota honesta.

A fase 20 corrigiu o contexto congelado e manteve a constante que o
alimenta. Medido contra o tokenizador do modelo, conteúdo tabular entrega
1,45 caracteres por token e não os 3,0 que o código supõe: o recálculo por
janela roda e chega curto toda vez. Numa corrida de 2904 páginas
(15/09/2026, `qwen3.5:4b`), 153 de 1449 janelas entraram no índice sem
classificação nenhuma, e a nota declarou 89/100.
"""

from __future__ import annotations

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import _group_pages_into_items


def _page(referencia: str, texto: str = "texto da pagina") -> WindowPage:
    return WindowPage(
        reference=referencia,
        file_name="acervo.pdf",
        text=texto,
        has_table=False,
        image_count=0,
    )


def test_pagina_sem_linha_do_modelo_recebe_confianca_baixa():
    """O modelo não respondeu nada sobre a janela. As páginas entram no
    índice pelo agrupamento — essa garantia fica — mas não podem se passar
    por classificadas: era isso que fazia o log fechar em `baixa=0` com 612
    peças cegas."""
    pages = [_page("f. 1"), _page("f. 2")]

    itens = _group_pages_into_items(pages, [])

    assert itens, "a garantia de cobertura precisa continuar valendo"
    assert all(item.confidence == "low" for item in itens)


def test_linha_incompleta_do_modelo_continua_media():
    """O modelo falou, mas sem tipo. Isso é diferente de não falar, e
    continua valendo `medium`."""
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "detail": "contrato de honorarios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["medium"]


def test_linha_completa_do_modelo_continua_alta():
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "type": "CONTRATO",
             "detail": "contrato de honorarios advocaticios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["high"]
```

- [ ] **Step 2: Rodar e confirmar que o primeiro teste falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -v
```
Expected: `test_pagina_sem_linha_do_modelo_recebe_confianca_baixa` FALHA com `assert 'medium' == 'low'`. Os outros dois passam.

- [ ] **Step 3: Distinguir os três casos**

Em `gclaude_indexer/engine_local.py`, dentro de `fechar()`, trocar a linha 797:

```python
        confianca = "high" if dados.get("type") and dados.get("detail") else "medium"
```

por:

```python
        # Três casos, não dois. Uma página sobre a qual o modelo não disse
        # NADA entra no índice pelo agrupamento — essa garantia é o que
        # impede a perda — mas não pode chegar ao relatório com a mesma
        # confiança de uma linha que ele respondeu pela metade. Medido numa
        # corrida real: 612 peças cegas saíram como `medium`, o resumo
        # fechou em `baixa=0` e a nota deu 89/100.
        respondida = any(linha for _pagina, linha in atual)
        if dados.get("type") and dados.get("detail"):
            confianca = "high"
        elif respondida:
            confianca = "medium"
        else:
            confianca = "low"
```

- [ ] **Step 4: Rodar os testes da tarefa**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -v
```
Expected: 3 passando.

- [ ] **Step 5: Rodar a suíte inteira**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 621 passando (618 + 3). Se algum teste antigo esperava `medium` para peça sem linha, ler o teste: se ele documentava o defeito, atualizar a expectativa e explicar no commit; se documentava outra coisa, a mudança está errada.

- [ ] **Step 6: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/engine_local.py
git commit -m "fix(classificação): página não respondida entra como confiança baixa

O agrupamento emite uma peça para toda página da janela, inclusive as que
o modelo não mencionou — é a garantia que impede a perda. Mas a peça saía
com 'medium', indistinguível de uma linha respondida pela metade: numa
corrida de 2904 páginas, 612 peças cegas passaram por medianas e o resumo
da etapa 6 fechou em 'baixa=0'.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A cobertura casa folha com folha, dentro do mesmo grupo

A consulta atual compara `page.number` — a página **dentro do arquivo**, 1..391 no maior PDF — com `item.start_order`, que é a folha **global do grupo**, 1..2830. Sem join por grupo. Removendo 967 peças do índice, um buraco real de 500 folhas, ela seguiu marcando 100,0% contra 82,7% reais.

**Files:**
- Modify: `gclaude_indexer/quality.py:123-133`
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `reference_number(reference: str) -> int` de `gclaude_indexer.classification`
- Produces: `_coverage(conn) -> tuple[int, int, int]` — `(total, cobertas, classificadas)`. A Tarefa 3 usa o terceiro valor.

- [ ] **Step 1: Escrever o teste que constrói um buraco real**

Acrescentar a `tests/test_phase21.py`:

```python
import sqlite3

from gclaude_indexer.quality import _coverage


def _banco_com_duas_familias() -> sqlite3.Connection:
    """Dois grupos cujas folhas se sobrepõem em numeração, que é o caso
    real: cada PDF numera as páginas de 1 a N, e a folha é do processo."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE file (id INTEGER PRIMARY KEY, group_key TEXT, name TEXT);
        CREATE TABLE page (id INTEGER PRIMARY KEY, file_id INTEGER,
                           number INTEGER, reference TEXT);
        CREATE TABLE item (id INTEGER PRIMARY KEY, group_key TEXT,
                           start_order INTEGER, end_order INTEGER,
                           confidence TEXT);
        """
    )
    conn.execute("INSERT INTO file VALUES (1, 'Processo', 'vol1.pdf')")
    conn.execute("INSERT INTO file VALUES (2, 'Avulsos', 'anexo.pdf')")
    # Processo: folhas 1 a 4, numeradas 1..4 dentro do proprio PDF.
    for n in range(1, 5):
        conn.execute("INSERT INTO page VALUES (?, 1, ?, ?)", (n, n, f"f. {n}"))
    # Avulsos: folhas 1 a 2, tambem numeradas 1..2 dentro do PDF.
    for n in range(1, 3):
        conn.execute("INSERT INTO page VALUES (?, 2, ?, ?)", (100 + n, n, f"f. {n}"))
    return conn


def test_cobertura_nao_conta_peca_de_outro_grupo():
    """O defeito: `page.number` é a página dentro do arquivo e
    `item.start_order` é a folha do grupo. Sem join, a peça de um grupo
    'cobria' a página de outro que por acaso tinha o mesmo número."""
    conn = _banco_com_duas_familias()
    # Uma unica peca, no grupo Processo, cobrindo as folhas 1 a 4.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 4, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert total == 6
    # As duas folhas de 'Avulsos' NAO estao cobertas: nenhuma peca daquele
    # grupo existe. A consulta antiga contava 6 de 6.
    assert cobertas == 4


def test_cobertura_enxerga_o_buraco():
    """Reprodução do que foi medido no acervo: removendo as peças de uma
    faixa, a cobertura tem de cair."""
    conn = _banco_com_duas_familias()
    # Cobre so as folhas 1 e 2 do Processo; 3 e 4 ficam de fora.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Avulsos', 1, 2, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 4)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k cobertura -v
```
Expected: FALHA com `ImportError: cannot import name '_coverage'`.

- [ ] **Step 3: Escrever `_coverage`**

Em `gclaude_indexer/quality.py`, acrescentar antes de `quality_summary`:

```python
def _coverage(conn) -> tuple[int, int, int]:
    """`(total, cobertas, classificadas)` das páginas do acervo.

    *Coberta* é a página que cai dentro de alguma peça **do seu próprio
    grupo**. *Classificada* é a página coberta por uma peça que o modelo de
    fato descreveu — uma peça de confiança `low` é a garantia de cobertura
    funcionando, não classificação.

    A consulta anterior fazia isto em SQL e comparava `page.number`, que é
    a página dentro do arquivo (1..391 no maior PDF do acervo), com
    `item.start_order`, que é a folha do grupo (1..2830), sem join. Os dois
    números não têm relação: removendo 967 peças do índice — um buraco de
    500 folhas — ela seguiu marcando 100,0% contra 82,7% reais. A folha
    sai de `page.reference` por `reference_number`, que é a mesma função
    que gerou `item.start_order`.
    """
    from .classification import reference_number

    faixas: dict[str, list[tuple[int, int, str]]] = {}
    for group_key, start, end, confidence in conn.execute(
        "SELECT group_key, start_order, end_order, confidence FROM item"
    ):
        faixas.setdefault(group_key, []).append((start, end, confidence))

    total = cobertas = classificadas = 0
    for group_key, reference in conn.execute(
        "SELECT file.group_key, page.reference "
        "FROM page JOIN file ON file.id = page.file_id"
    ):
        total += 1
        folha = reference_number(reference or "")
        dentro = [c for inicio, fim, c in faixas.get(group_key, []) if inicio <= folha <= fim]
        if dentro:
            cobertas += 1
            if any(c != "low" for c in dentro):
                classificadas += 1
    return total, cobertas, classificadas
```

- [ ] **Step 4: Rodar os testes da tarefa**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k cobertura -v
```
Expected: 2 passando.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/quality.py
git commit -m "fix(qualidade): a cobertura casa folha com folha do mesmo grupo

A consulta comparava page.number, que é a página dentro do arquivo, com
item.start_order, que é a folha do grupo, e não fazia join por grupo. Numa
prova direta, removendo 967 peças do índice — um buraco de 500 folhas —
ela continuou marcando 100,0% onde o valor real era 82,7%.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Os 40 pontos passam a medir cobertura classificada

Mesmo consertada, a métrica daria 100% sempre: `_group_pages_into_items` emite uma peça por página aconteça o que acontecer, então a página está sempre dentro de alguma peça. Ela pergunta "a página está no índice?" quando o que importa é "o índice diz algo útil sobre esta página?".

**Files:**
- Modify: `gclaude_indexer/quality.py:123-133` (o corpo de `quality_summary`) e o dicionário de retorno
- Modify: `gclaude_indexer/i18n.py` (três blocos)
- Modify: `gclaude_indexer/web/templates/result.html:80`
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `_coverage(conn) -> tuple[int, int, int]` da Tarefa 2
- Produces: `quality_summary` passa a devolver também `pages_classified: int` e `classified_pct: float`. `coverage_pct` e `coverage_points` passam a refletir a cobertura **classificada**; `pages_covered` continua sendo a presença no índice.

- [ ] **Step 1: Escrever o teste**

Acrescentar a `tests/test_phase21.py`:

```python
def test_cobertura_classificada_ignora_peca_cega():
    """Uma peça de confiança `low` é a rede de segurança funcionando, não
    classificação. Era isto que pagava 40 de 40 pontos numa corrida com 11%
    do índice cego."""
    conn = _banco_com_duas_familias()
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Processo', 3, 4, 'low')")
    conn.execute("INSERT INTO item VALUES (3, 'Avulsos', 1, 2, 'high')")

    total, cobertas, classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 6), "toda pagina segue no indice"
    assert classificadas == 4, "as duas folhas cegas nao contam como classificadas"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k classificada -v
```
Expected: PASSA — `_coverage` da Tarefa 2 já devolve o terceiro valor. Se falhar, a Tarefa 2 está incompleta; corrigir lá antes de seguir.

- [ ] **Step 3: Ligar `quality_summary` à cobertura classificada**

Em `gclaude_indexer/quality.py`, substituir o bloco das linhas 123–133:

```python
    total_pages = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]
    covered_pages = conn.execute(
        """
        SELECT COUNT(*) FROM page
        WHERE EXISTS (
            SELECT 1 FROM item
            WHERE page.number BETWEEN item.start_order AND item.end_order
        )
        """
    ).fetchone()[0]
    coverage = (covered_pages / total_pages) if total_pages else 0.0
```

por:

```python
    total_pages, covered_pages, classified_pages = _coverage(conn)
    # A nota mede a cobertura CLASSIFICADA, não a presença no índice.
    # `_group_pages_into_items` emite uma peça para toda página da janela,
    # então a presença é garantida por construção e valeria 40 de 40 pontos
    # mesmo numa corrida em que o modelo não respondeu nada. `covered_pages`
    # continua sendo reportado, porque distingue um buraco no índice — que
    # não tem conserto a jusante — de uma página presente e mal descrita.
    coverage = (classified_pages / total_pages) if total_pages else 0.0
```

E no dicionário de retorno, acrescentar depois de `"pages_covered": covered_pages,`:

```python
        "pages_classified": classified_pages,
        "classified_pct": round(coverage * 100, 1),
```

- [ ] **Step 4: Acrescentar a chave de interface nos três idiomas**

Em `gclaude_indexer/i18n.py`, ao lado de `"result.quality_missing_summary"` em cada um dos três blocos:

```python
        # pt-BR (perto da linha 708)
        "result.quality_pages_classified": "{n} de {total} página(s) descrita(s) pelo modelo",
```
```python
        # en
        "result.quality_pages_classified": "{n} of {total} page(s) described by the model",
```
```python
        # es
        "result.quality_pages_classified": "{n} de {total} página(s) descrita(s) por el modelo",
```

- [ ] **Step 5: Mostrar na tela de resultado**

Em `gclaude_indexer/web/templates/result.html`, depois da linha 80:

```html
    <li>{{ t('result.quality_pages_classified', n=qualidade.pages_classified, total=qualidade.pages_total) }}</li>
```

- [ ] **Step 6: Rodar a suíte inteira**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 624 passando. Testes antigos que afirmavam `coverage_pct == 100.0` com peça cega precisam ser lidos: se documentavam o defeito, atualizar; senão, a mudança está errada.

- [ ] **Step 7: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/quality.py gclaude_indexer/i18n.py gclaude_indexer/web/templates/result.html
git commit -m "fix(qualidade): os 40 pontos medem cobertura classificada

A métrica era tautológica: o agrupamento emite uma peça por página da
janela, então a página está sempre dentro de alguma peça e os 40 pontos
saíam de graça. Numa corrida com 11% do índice cego, a nota deu 89/100.
Medindo a cobertura classificada, a mesma corrida vale 83.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# Parte 2 — Classificação

É aqui que as 320 páginas cegas voltam a ser descritas.

---

### Task 4: A telemetria do Ollama para de ser jogada fora

`_generate` devolve só o texto. O `prompt_eval_count` e o `eval_count` que vêm na mesma resposta são a única forma de saber que o prompt foi cortado — e o código os descarta.

**Files:**
- Modify: `gclaude_indexer/engine_local.py:435-470` (`_generate`), `:384` e `:400` (chamadas)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Produces: `Generation` (dataclass, exportada do módulo) com `text: str`, `prompt_tokens: int`, `response_tokens: int`, `context: int`. `LocalEngine._generate(prompt) -> Generation`.

- [ ] **Step 1: Escrever o teste**

Acrescentar a `tests/test_phase21.py`:

```python
import json

from gclaude_indexer.engine_local import Generation, LocalEngine


class _OllamaFalso:
    """Substitui `urlopen`. Guarda o `num_ctx` pedido e devolve a
    telemetria que o Ollama real devolve."""

    def __init__(self, respostas: list[dict]):
        self.respostas = list(respostas)
        self.contextos: list[int] = []

    def __call__(self, request, timeout=None):
        corpo = json.loads(request.data.decode("utf-8"))
        self.contextos.append(corpo["options"].get("num_ctx"))
        return _Resposta(self.respostas.pop(0))


class _Resposta:
    def __init__(self, dados: dict):
        self._dados = dados

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self._dados).encode("utf-8")


def test_generate_devolve_a_telemetria(monkeypatch):
    """`prompt_eval_count` é a contagem de tokens do tokenizador do próprio
    modelo. É o dado que denuncia o truncamento, e ele vinha sendo
    descartado."""
    falso = _OllamaFalso([
        {"response": '{"pages": []}', "prompt_eval_count": 5091, "eval_count": 422}
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor.num_ctx = 6144

    resultado = motor._generate("prompt qualquer")

    assert isinstance(resultado, Generation)
    assert resultado.text == '{"pages": []}'
    assert resultado.prompt_tokens == 5091
    assert resultado.response_tokens == 422
    assert resultado.context == 6144
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k telemetria -v
```
Expected: FALHA com `ImportError: cannot import name 'Generation'`.

- [ ] **Step 3: Criar `Generation` e mudar `_generate`**

Em `gclaude_indexer/engine_local.py`, acrescentar perto das outras dataclasses (antes de `class LocalEngine`):

```python
@dataclass
class Generation:
    """O que uma chamada ao Ollama devolveu, com a telemetria junto.

    `prompt_tokens` é `prompt_eval_count`: quantos tokens do prompt o
    modelo realmente leu, contados pelo tokenizador dele. Quando é menor
    que o prompt enviado, o prompt foi cortado — e essa é a única forma de
    saber, já que o Ollama trunca em silêncio e não expõe um endpoint de
    tokenização.
    """

    text: str
    prompt_tokens: int = 0
    response_tokens: int = 0
    context: int = 0
```

Trocar o fim de `_generate` — o `return data.get("response") or data.get("thinking") or ""` — por:

```python
        return Generation(
            text=data.get("response") or data.get("thinking") or "",
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            response_tokens=int(data.get("eval_count") or 0),
            context=int(options.get("num_ctx") or 0),
        )
```

E mudar o tipo de retorno na assinatura: `def _generate(self, prompt: str) -> Generation:`.

- [ ] **Step 4: Ajustar os dois chamadores**

Na linha 384, em `classify_per_page`:
```python
        rows = _pages_json(self._generate(prompt))
```
vira:
```python
        rows = _pages_json(self._generate(prompt).text)
```

Na linha ~400, em `classify` (o modo de faixas):
```python
        response_text = self._generate(prompt)
```
vira:
```python
        response_text = self._generate(prompt).text
```

- [ ] **Step 5: Rodar a suíte inteira**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 625 passando. Testes antigos que fingiam `_generate` devolvendo `str` precisam devolver `Generation("...")` — o valor padrão dos outros campos é 0, então basta o texto.

- [ ] **Step 6: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/engine_local.py
git commit -m "feat(motor local): _generate devolve a telemetria da chamada

prompt_eval_count é a contagem de tokens do tokenizador do próprio modelo
e a única forma de saber que o Ollama truncou o prompt — ele corta em
silêncio e a versão 0.34 não expõe endpoint de tokenização. O dado vinha
na mesma resposta e era descartado.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A razão caracteres/token é calibrada pelo acervo

`_CHARS_PER_TOKEN = 3.0` é uma constante escolhida uma vez. O acervo tem prosa a 3,3 e tabela contábil a 1,45; qualquer valor fixo erra metade dele.

**Files:**
- Modify: `gclaude_indexer/engine_local.py:228` (constante), `:274-290` (`context_tokens_for`), `:315-325` (campos de `LocalEngine`)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `Generation` da Tarefa 4
- Produces: `context_tokens_for(prompt, model_limit=0, page_count=0, chars_per_token=_CHARS_PER_TOKEN) -> int`; `LocalEngine._chars_per_token: float`; `LocalEngine._calibrate(prompt: str, generation: Generation) -> None`; `_looks_truncated(generation: Generation) -> bool`.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/test_phase21.py`:

```python
from gclaude_indexer.engine_local import _looks_truncated, context_tokens_for


def test_contexto_cresce_quando_a_razao_cai():
    """O mesmo prompt precisa de mais contexto quando o conteúdo tokeniza
    pior. Medido no acervo: prosa a 3,3 caracteres por token, tabela
    contábil a 1,45."""
    prompt = "x" * 9000

    prosa = context_tokens_for(prompt, page_count=4, chars_per_token=3.0)
    tabela = context_tokens_for(prompt, page_count=4, chars_per_token=1.45)

    assert tabela > prosa


def test_calibracao_aprende_a_razao_do_acervo(monkeypatch):
    """A janela íntegra ensina a razão real: 8241 caracteres que o modelo
    leu como 5091 tokens são 1,62 caracteres por token, e não os 3,0 que a
    constante supunha."""
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    assert motor._chars_per_token == 3.0

    motor._calibrate("x" * 8241, Generation(text="{}", prompt_tokens=5091, context=8192))

    assert motor._chars_per_token < 1.7


def test_calibracao_ignora_a_chamada_truncada():
    """Num prompt cortado, `prompt_eval_count` descreve o pedaço que sobrou
    e não o prompt inteiro. Calibrar por ele ensinaria a razão errada."""
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    # 2050 tokens num contexto de 4096: a assinatura do truncamento.
    motor._calibrate("x" * 8241, Generation(text="", prompt_tokens=2050, context=4096))

    assert motor._chars_per_token == 3.0


def test_assinatura_do_truncamento():
    """Medido no Ollama 0.34: ele corta o prompt em exatamente metade do
    contexto — 1026/2048, 1538/3072, 2050/4096."""
    assert _looks_truncated(Generation(text="", prompt_tokens=2050, context=4096))
    assert _looks_truncated(Generation(text="", prompt_tokens=1026, context=2048))
    assert not _looks_truncated(Generation(text="", prompt_tokens=5091, context=6144))
    assert not _looks_truncated(Generation(text="", prompt_tokens=0, context=0))
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k "razao or calibracao or truncamento or contexto_cresce" -v
```
Expected: FALHA com `ImportError: cannot import name '_looks_truncated'`.

- [ ] **Step 3: Implementar piso, detecção e calibração**

Em `gclaude_indexer/engine_local.py`, abaixo de `_CHARS_PER_TOKEN = 3.0`, acrescentar:

```python
# Piso da calibração. Uma razão abaixo disto não descreve texto nenhum —
# é resposta corrompida ou telemetria absurda — e aceitá-la infla o
# contexto de todas as janelas seguintes, já que ele só cresce.
_CHARS_PER_TOKEN_FLOOR = 1.2

# Folga para reconhecer a assinatura do truncamento. O Ollama 0.34 corta o
# prompt em exatamente metade do `num_ctx`, medido em 1026/2048,
# 1538/3072 e 2050/4096 — sempre dois tokens acima da metade exata. 64 é
# folga larga para uma assinatura que vem com erro de 2.
_TRUNCATION_TOLERANCE = 64


def _looks_truncated(generation: "Generation") -> bool:
    """Se o Ollama cortou este prompt.

    Comportamento observado, não documentado: quando o prompt não cabe, o
    Ollama o trunca para metade do contexto pedido. É comportamento interno
    e pode mudar de versão — por isso ele NUNCA decide sozinho se a janela
    falhou (esse critério é o número de linhas devolvidas, em
    `_classify_pages`). Serve para escolher o próximo `num_ctx` e para
    descartar uma calibração que ensinaria a razão errada.
    """
    if not generation.context or not generation.prompt_tokens:
        return False
    return abs(generation.prompt_tokens - generation.context / 2) <= _TRUNCATION_TOLERANCE
```

Trocar a assinatura e o corpo de `context_tokens_for`:

```python
def context_tokens_for(
    prompt: str,
    model_limit: int = 0,
    page_count: int = 0,
    chars_per_token: float = _CHARS_PER_TOKEN,
) -> int:
```

e, dentro dela, a linha do `estimated`:

```python
    estimated = int(len(prompt) / chars_per_token) + _response_tokens_for(page_count)
```

Nos campos de `LocalEngine`, junto de `gpu_plan` e `_planned`:

```python
    # A razão caracteres/token deste acervo, aprendida durante a corrida.
    # `_CHARS_PER_TOKEN` é só a semente da primeira janela, quando ainda não
    # há medição. Guardamos o MÍNIMO observado, e não a média, pela mesma
    # assimetria que justificava a constante: superestimar custa um pouco de
    # VRAM, subestimar custa a janela inteira.
    _chars_per_token: float = field(default=_CHARS_PER_TOKEN, repr=False)
```

E o método de calibração, dentro de `LocalEngine`:

```python
    def _calibrate(self, prompt: str, generation: "Generation") -> None:
        """Aprende a razão caracteres/token com o que o modelo acabou de ler.

        Só vale para a chamada íntegra: num prompt truncado,
        `prompt_eval_count` conta o pedaço que sobrou, e a razão calculada
        sobre o prompt inteiro sairia otimista — exatamente o erro que se
        quer corrigir.
        """
        if not generation.prompt_tokens or _looks_truncated(generation):
            return
        observada = len(prompt) / generation.prompt_tokens
        self._chars_per_token = max(
            _CHARS_PER_TOKEN_FLOOR, min(self._chars_per_token, observada)
        )
```

- [ ] **Step 4: Usar a razão calibrada em `plan_gpu_use`**

Na linha do `context = context_tokens_for(...)` dentro de `plan_gpu_use`:

```python
        context = context_tokens_for(prompt, page_count=page_count)
```
vira:
```python
        context = context_tokens_for(
            prompt, page_count=page_count, chars_per_token=self._chars_per_token
        )
```

- [ ] **Step 5: Rodar os testes da tarefa e a suíte**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -v
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: os 4 novos passam; suíte em 629.

- [ ] **Step 6: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/engine_local.py
git commit -m "feat(motor local): a razão caracteres/token é medida, não suposta

_CHARS_PER_TOKEN = 3.0 descrevia prosa portuguesa. Medido contra o
tokenizador do modelo, o conteúdo tabular do acervo entrega 1,45 — e o
recálculo por janela da fase 20 chegava curto toda vez. A razão passa a
ser aprendida durante a corrida com prompt_eval_count, guardando o mínimo
observado, com piso de 1,2.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: A escada de retentativa

O sintoma é um só — `linhas devolvidas < páginas da janela` —, a causa se lê na telemetria, e a ação é sempre mais contexto.

**Files:**
- Modify: `gclaude_indexer/engine_local.py:373-395` (`classify_per_page`), `plan_gpu_use` (parâmetro `minimum`)
- Modify: `gclaude_indexer/i18n.py` (três blocos)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `Generation`, `_looks_truncated`, `_calibrate` das Tarefas 4 e 5
- Produces: `LocalEngine._classify_pages(pages) -> list[ClassifiedItem]`; `LocalEngine._context_needed(generation, page_count) -> int`; `plan_gpu_use(prompt, page_count=0, minimum=0)`; `LocalEngine.context_ceiling: int`.

- [ ] **Step 1: Escrever o teste da retentativa**

Acrescentar a `tests/test_phase21.py`:

```python
from gclaude_indexer import gpu_budget


def _plan_com_teto(monkeypatch, teto: int = 8192, camadas: int = 33):
    """O planejador devolve camadas até o teto e `None` acima dele — que é
    o comportamento medido na RTX 3060 Laptop: 33 de 33 camadas até 8192,
    nada em 12288."""
    monkeypatch.setattr(
        gpu_budget, "plan",
        lambda modelo, url, contexto: (
            (camadas, {"layers": camadas}) if contexto <= teto else (None, {})
        ),
    )


def test_janela_truncada_e_refeita_com_mais_contexto(monkeypatch):
    """A falha medida: prompt de 5091 tokens num contexto de 4096. O Ollama
    corta em 2050, o modelo nunca vê o gabarito e devolve 0 linhas. A
    segunda tentativa, com contexto maior, devolve as 4."""
    _plan_com_teto(monkeypatch)
    quatro_linhas = json.dumps({"pages": [
        {"n": i, "subject": "assunto", "type": "DOC", "detail": "detalhe"}
        for i in range(1, 5)
    ]})
    falso = _OllamaFalso([
        {"response": '{"document_type": "Financial Statement"}',
         "prompt_eval_count": 2050, "eval_count": 1588},
        {"response": quatro_linhas, "prompt_eval_count": 5091, "eval_count": 422},
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}", "texto " * 400) for n in range(1, 5)]

    itens = motor.classify_per_page(pages)

    assert len(falso.contextos) == 2, "a janela tinha de ser refeita"
    assert falso.contextos[1] > falso.contextos[0]
    assert all(item.confidence != "low" for item in itens)


def test_resposta_sem_orcamento_tambem_dispara_retentativa(monkeypatch):
    """O outro modo de falha, medido em num_ctx=5120: o prompt coube
    inteiro (5091) e sobraram 29 tokens para responder. Mesma mensagem de
    log do truncamento, causa oposta."""
    _plan_com_teto(monkeypatch)
    quatro_linhas = json.dumps({"pages": [
        {"n": i, "subject": "assunto", "type": "DOC", "detail": "detalhe"}
        for i in range(1, 5)
    ]})
    falso = _OllamaFalso([
        {"response": '{"pages": [{"n": 1,', "prompt_eval_count": 5091, "eval_count": 29},
        {"response": quatro_linhas, "prompt_eval_count": 5091, "eval_count": 422},
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}", "texto " * 400) for n in range(1, 5)]

    motor.classify_per_page(pages)

    assert len(falso.contextos) == 2
    # 5091 + 4 paginas x 220 = 5971, arredondado para 6144.
    assert falso.contextos[1] >= 6144


def test_janela_que_responde_de_primeira_nao_repete(monkeypatch):
    """A retentativa custa uma chamada. Ela só acontece quando precisa."""
    _plan_com_teto(monkeypatch)
    quatro_linhas = json.dumps({"pages": [
        {"n": i, "subject": "assunto", "type": "DOC", "detail": "detalhe"}
        for i in range(1, 5)
    ]})
    falso = _OllamaFalso([
        {"response": quatro_linhas, "prompt_eval_count": 3000, "eval_count": 422}
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}") for n in range(1, 5)]

    motor.classify_per_page(pages)

    assert len(falso.contextos) == 1
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k "retentativa or orcamento or primeira" -v
```
Expected: FALHA — `len(falso.contextos) == 1`, nenhuma retentativa acontece.

- [ ] **Step 3: Medir o teto da placa**

Em `gclaude_indexer/engine_local.py`, acrescentar a constante junto das outras:

```python
# Contextos testados, do maior para o menor, ao medir o teto da placa. O
# teto é o maior deles que o `gpu_budget` ainda consegue planejar sem
# empurrar camadas para a RAM — medido numa RTX 3060 Laptop de 6 GB com
# `qwen3.5:4b`: 33 de 33 camadas até 8192, nenhum plano em 12288.
_CONTEXT_CEILING_CANDIDATES = (16384, 12288, 8192, 6144, 4096)
```

E o campo mais o método em `LocalEngine`:

```python
    # Maior `num_ctx` que a placa comporta sem transbordar para a RAM.
    # Medido uma vez por corrida, junto do plano de GPU.
    context_ceiling: int = field(default=0, repr=False)
```

```python
    def _measure_ceiling(self) -> int:
        """O maior contexto que ainda cabe na placa.

        Uma janela que precise de mais que isto é subdividida, e não
        empurrada para a RAM: o acervo tem 1449 janelas, e uma janela seis
        vezes mais lenta multiplicada por algumas centenas custa horas.
        """
        if self.context_ceiling:
            return self.context_ceiling
        from .gpu_budget import plan

        self.context_ceiling = _OLLAMA_DEFAULT_CONTEXT
        for candidato in _CONTEXT_CEILING_CANDIDATES:
            try:
                layers, _details = plan(self.model, self.url_base, candidato)
            except Exception:
                continue
            if layers is not None:
                self.context_ceiling = candidato
                break
        return self.context_ceiling
```

- [ ] **Step 4: Aceitar um mínimo em `plan_gpu_use`**

Trocar a assinatura:

```python
    def plan_gpu_use(self, prompt: str, page_count: int = 0, minimum: int = 0) -> dict | None:
```

e, logo depois do cálculo do `context`:

```python
        context = max(context, minimum)
        teto = self._measure_ceiling()
        if teto:
            context = min(context, teto)
```

- [ ] **Step 5: Escrever a escada**

Substituir o corpo de `classify_per_page` (linhas 373–395) por:

```python
    def classify_per_page(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        """Uma linha por página, agrupadas em peças pelo código.

        A cobertura sai garantida por construção: `_group_pages_into_items`
        percorre as páginas da janela, não as linhas que o modelo devolveu,
        então uma página que ele esqueceu entra no índice de qualquer
        forma — com o que se souber dela.
        """
        self.last_window_warnings = []
        return self._classify_pages(pages)

    def _classify_pages(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        """A janela, subindo o contexto enquanto a resposta não a cobrir.

        O gatilho é `linhas devolvidas < páginas`, e não a assinatura do
        truncamento: o número de linhas é o que de fato importa e não
        depende de comportamento interno do Ollama. A telemetria só escolhe
        o próximo `num_ctx`.
        """
        prompt = _build_page_prompt(pages, self.config)
        self.plan_gpu_use(prompt, page_count=len(pages))
        generation = self._generate(prompt)
        self._calibrate(prompt, generation)
        rows = _pages_json(generation.text)

        if len(rows) < len(pages):
            alvo = self._context_needed(generation, len(pages))
            if alvo > (self.num_ctx or 0):
                self.plan_gpu_use(prompt, page_count=len(pages), minimum=alvo)
                generation = self._generate(prompt)
                self._calibrate(prompt, generation)
                novas = _pages_json(generation.text)
                if len(novas) > len(rows):
                    rows = novas

        # Ainda faltando e há o que dividir: duas janelas menores cabem
        # onde uma não coube. As peças são concatenadas, e não as linhas —
        # cada metade numera as suas páginas de 1 a N.
        if len(rows) < len(pages) and len(pages) > 1:
            meio = len(pages) // 2
            return self._classify_pages(pages[:meio]) + self._classify_pages(pages[meio:])

        faltantes = max(0, len(pages) - len(rows))
        if faltantes:
            # Não é motivo para recusar nada — o agrupamento cobre a página
            # de qualquer modo. É registrado porque distingue um modelo que
            # respondeu sobre tudo de um que respondeu sobre metade.
            self.last_window_warnings.append((
                "log.local_engine.pages_missing_from_answer",
                {"missing": faltantes, "total": len(pages)},
            ))
        return _group_pages_into_items(pages, rows)

    def _context_needed(self, generation: "Generation", page_count: int) -> int:
        """O contexto que esta janela pedia, lido da tentativa que falhou.

        Quando o prompt foi cortado não dá para saber de quanto ele
        precisava — `prompt_eval_count` conta só o pedaço lido. Dobrar o
        contexto é o passo que cobre a maior janela deste acervo numa
        tentativa só: 4096 vira 8192, e a janela de 5091 tokens cabe.
        """
        if _looks_truncated(generation):
            alvo = generation.context * 2
        else:
            alvo = generation.prompt_tokens + _response_tokens_for(page_count)
        alvo = -(-alvo // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
        teto = self._measure_ceiling()
        return min(alvo, teto) if teto else alvo
```

- [ ] **Step 6: Rodar os testes da tarefa e a suíte**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -v
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: os 3 novos passam; suíte em 632. `test_janela_mais_densa_que_a_primeira_amplia_o_contexto` (fase 20) continua verde — o mock `_plan_fixo` devolve camadas para qualquer contexto, então o teto fica em 16384 e não interfere.

- [ ] **Step 7: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/engine_local.py
git commit -m "feat(motor local): escada de retentativa para a janela não coberta

O gatilho é 'linhas devolvidas < páginas da janela', que não depende de
comportamento interno do Ollama. A telemetria só escolhe o próximo
num_ctx: prompt cortado (prompt_eval na metade do contexto) dobra, prompt
íntegro com resposta faminta usa prompt_eval + páginas x 220. Acima do
teto da placa, a janela é subdividida em vez de transbordar para a RAM.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: A janela acima do teto é subdividida

Coberto pela recursão da Tarefa 6; esta tarefa prova que ela funciona e que não há recursão infinita.

**Files:**
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `LocalEngine._classify_pages` da Tarefa 6

- [ ] **Step 1: Escrever o teste**

```python
def test_janela_acima_do_teto_e_subdividida(monkeypatch):
    """Nem no contexto máximo da placa a janela cabe. Em vez de transbordar
    para a RAM, ela é partida — e nenhuma página fica sem descrição."""
    _plan_com_teto(monkeypatch, teto=4096)
    duas_linhas = json.dumps({"pages": [
        {"n": i, "subject": "assunto", "type": "DOC", "detail": "detalhe"}
        for i in range(1, 3)
    ]})
    # As duas primeiras tentativas com 4 paginas nao cobrem a janela; as
    # metades, com 2 paginas cada, cobrem.
    falso = _OllamaFalso([
        {"response": "{}", "prompt_eval_count": 2050, "eval_count": 900},
        {"response": "{}", "prompt_eval_count": 2050, "eval_count": 900},
        {"response": duas_linhas, "prompt_eval_count": 1500, "eval_count": 300},
        {"response": duas_linhas, "prompt_eval_count": 1500, "eval_count": 300},
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}", "texto " * 400) for n in range(1, 5)]

    itens = motor.classify_per_page(pages)

    folhas = {ref for item in itens
              for ref in (item.start_ref, item.end_ref)}
    assert folhas == {"f. 1", "f. 2", "f. 3", "f. 4"}
    assert all(item.confidence != "low" for item in itens)


def test_janela_de_uma_pagina_nao_entra_em_recursao(monkeypatch):
    """Não há o que subdividir numa página só. A peça entra como `low` e a
    corrida segue — mas o processo não pode travar."""
    _plan_com_teto(monkeypatch, teto=4096)
    falso = _OllamaFalso([
        {"response": "{}", "prompt_eval_count": 2050, "eval_count": 900},
        {"response": "{}", "prompt_eval_count": 2050, "eval_count": 900},
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    itens = motor.classify_per_page([_page("f. 1", "texto " * 400)])

    assert [item.confidence for item in itens] == ["low"]
    assert motor.last_window_warnings, "a perda tem de ficar registrada"
```

- [ ] **Step 2: Rodar**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k "subdividida or recursao" -v
```
Expected: PASSAM com a implementação da Tarefa 6. Se `test_janela_de_uma_pagina_nao_entra_em_recursao` travar ou estourar a pilha, a guarda `len(pages) > 1` em `_classify_pages` está errada.

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase21.py
git commit -m "test(motor local): subdivisão da janela e a guarda da recursão

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# Parte 3 — Índice consultável

Não altera o que é classificado, só como o resultado é consultado.

---

### Task 8: A linha do índice leva à página física do PDF

A linha diz `f. 417 | … | Vol 2.pdf`. Mas `f. 417` é a **página 145** daquele PDF, e o grupo tem 21 arquivos. O dado está em `page.number` e não é exposto.

**Files:**
- Modify: `gclaude_indexer/artifacts.py:87-133` (`generate_index_md`)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Produces: `_physical_pages(conn) -> dict[tuple[str, int], tuple[str, int]]` — de `(group_key, folha)` para `(nome do arquivo, página no arquivo)`.

- [ ] **Step 1: Escrever o teste**

```python
from gclaude_indexer.artifacts import _physical_pages


def test_indice_sabe_a_pagina_fisica_do_pdf():
    """f. 417 é a página 145 do Vol 2.pdf. Sem isso, quem consulta o índice
    sabe o arquivo e não sabe onde abrir — o grupo tem 21 PDFs."""
    conn = _banco_com_duas_familias()

    mapa = _physical_pages(conn)

    assert mapa[("Processo", 3)] == ("vol1.pdf", 3)
    assert mapa[("Avulsos", 2)] == ("anexo.pdf", 2)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k fisica -v
```
Expected: FALHA com `ImportError: cannot import name '_physical_pages'`.

- [ ] **Step 3: Implementar o mapa e usá-lo na coluna de faixa**

Em `gclaude_indexer/artifacts.py`, acrescentar depois de `_cell`:

```python
def _physical_pages(conn) -> dict[tuple[str, int], tuple[str, int]]:
    """De `(grupo, folha)` para `(arquivo, página dentro do arquivo)`.

    A folha é a numeração do processo, contínua entre os PDFs do grupo; a
    página é a do arquivo, que recomeça em 1 a cada volume. O índice
    trazia só o nome do arquivo, e num grupo de 21 volumes isso não diz
    onde abrir.
    """
    from .classification import reference_number

    mapa: dict[tuple[str, int], tuple[str, int]] = {}
    for group_key, name, number, reference in conn.execute(
        "SELECT file.group_key, file.name, page.number, page.reference "
        "FROM page JOIN file ON file.id = page.file_id"
    ):
        mapa[(group_key, reference_number(reference or ""))] = (name, number)
    return mapa
```

Em `generate_index_md`, depois de `items = _items(conn)`:

```python
    physical = _physical_pages(conn)
```

E trocar a montagem do `span`:

```python
                span = f"{item['start_ref']} – {item['end_ref']}"
```

por:

```python
                span = f"{item['start_ref']} – {item['end_ref']}"
                origem = physical.get((item["group_key"], item["start_order"]))
                if origem:
                    arquivo, pagina = origem
                    span = f"{span} ({arquivo}, p. {pagina})"
```

- [ ] **Step 4: Rodar a suíte**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 635. Testes de `index.md` que casavam a coluna de faixa exata precisam acomodar o sufixo.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/artifacts.py
git commit -m "feat(índice): a linha leva à página física do PDF

f. 417 é a página 145 do Vol 2.pdf, e o grupo tem 21 volumes. O índice
nomeava o arquivo e parava aí.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Um índice por grupo, com sumário

`index.md` sai com 5443 linhas e 1,58 MB num arquivo só — demais para um Projeto do Claude recuperar de forma confiável.

**Files:**
- Modify: `gclaude_indexer/artifacts.py` (`generate_index_md`, `generate_all_artifacts`)
- Modify: `gclaude_indexer/i18n.py` (três blocos)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Produces: `generate_index_md` passa a devolver `list[Path]` — o sumário primeiro, depois um por grupo. `group_index_filename(group_key: str) -> str`.

- [ ] **Step 1: Escrever o teste**

```python
from gclaude_indexer.artifacts import generate_index_md, group_index_filename


def test_indice_sai_em_sumario_mais_um_arquivo_por_grupo(tmp_path):
    conn = _banco_com_duas_familias()
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 4, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Avulsos', 1, 2, 'high')")
    config = _config_minima(tmp_path)

    caminhos = generate_index_md(conn, config, "pt-BR")

    nomes = [caminho.name for caminho in caminhos]
    assert nomes[0] == "index.md"
    assert group_index_filename("Processo") in nomes
    assert group_index_filename("Avulsos") in nomes

    sumario = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "Processo" in sumario and "Avulsos" in sumario
    assert group_index_filename("Processo") in sumario, "o sumário aponta o caminho"
```

Acrescentar o helper de config junto dos outros:

```python
def _config_minima(tmp_path):
    from gclaude_indexer.config import ProjectConfig

    return ProjectConfig(name="Acervo", output_folder=str(tmp_path))
```

Se `ProjectConfig` exigir mais campos obrigatórios, ler a dataclass em `gclaude_indexer/config.py` e preencher só os obrigatórios — nada de valores inventados para campos opcionais.

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k sumario -v
```
Expected: FALHA com `ImportError: cannot import name 'group_index_filename'`.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/artifacts.py`, junto das constantes de nome:

```python
def group_index_filename(group_key: str) -> str:
    """`index-<grupo>.md`, com o nome do grupo reduzido a caracteres
    seguros para nome de arquivo em qualquer sistema."""
    seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in group_key)
    seguro = "-".join(parte for parte in seguro.split("-") if parte)
    return f"index-{seguro or 'grupo'}.md"
```

Substituir o corpo inteiro de `generate_index_md`:

```python
def generate_index_md(conn, config: ProjectConfig, language: str) -> list[Path]:
    """O sumário dos grupos, mais um índice por grupo.

    Saía tudo num arquivo só: 5443 linhas e 1,58 MB na coleção que motivou
    isto, demais para um Projeto do Claude recuperar de forma confiável. O
    sumário cabe em poucos KB e diz qual arquivo abrir.
    """
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    items = _items(conn)
    physical = _physical_pages(conn)
    by_group: dict[str, list] = {}
    for item in items:
        by_group.setdefault(item["group_key"], []).append(item)

    saida = Path(config.output_folder)
    header = (
        f"| {t('artifact.index.table_range')} | {t('artifact.index.table_type')} | "
        f"{t('artifact.index.table_date')} | {t('artifact.index.table_author')} | "
        f"{t('artifact.index.table_confidence')} | {t('artifact.index.table_source')} | "
        f"{t('artifact.index.table_summary')} |"
    )

    resumo = [
        f"# {t('artifact.index.title')} — {config.name}",
        "",
        t("artifact.index.generated", timestamp=_now_iso(), count=len(items)),
    ]
    if not items:
        resumo += ["", t("artifact.index.empty")]
    else:
        resumo += ["", f"## {t('artifact.index.summary_title')}", ""]

    caminhos: list[Path] = []
    for group in sorted(by_group):
        do_grupo = by_group[group]
        nome = group_index_filename(group)
        folhas = [item["start_order"] for item in do_grupo]
        folhas += [item["end_order"] for item in do_grupo]
        arquivos = {
            physical[(group, item["start_order"])][0]
            for item in do_grupo
            if (group, item["start_order"]) in physical
        }
        resumo.append(t(
            "artifact.index.summary_row",
            group=group,
            sheets=f"f. {min(folhas)}–{max(folhas)}" if folhas else "—",
            files=len(arquivos),
            file=nome,
        ))

        corpo = [
            f"# {t('artifact.index.title')} — {group}", "",
            header, "|---|---|---|---|---|---|---|",
        ]
        for item in do_grupo:
            span = f"{item['start_ref']} – {item['end_ref']}"
            origem = physical.get((group, item["start_order"]))
            if origem:
                arquivo, pagina = origem
                span = f"{span} ({arquivo}, p. {pagina})"
            corpo.append(
                "| " + " | ".join(
                    _cell(v) for v in (
                        span, item["type"], item["date"], item["author"],
                        item["confidence"], item["files"], item["summary"],
                    )
                ) + " |"
            )
        caminho = saida / nome
        caminho.write_text("\n".join(corpo) + "\n", encoding="utf-8")
        caminhos.append(caminho)

    principal = saida / INDEX_FILENAME
    principal.write_text("\n".join(resumo) + "\n", encoding="utf-8")
    return [principal] + caminhos
```

Em `generate_all_artifacts` (`artifacts.py:457`), o dicionário é montado como literal. Substituir:

```python
    written = {
        "index": generate_index_md(conn, config, language),
        "timeline": generate_timeline_md(conn, config, language),
```

por:

```python
    indices = generate_index_md(conn, config, language)
    written = {
        "index": indices[0],
        "timeline": generate_timeline_md(conn, config, language),
```

e, logo depois do fecho do dicionário e antes de `record_artifact_state(conn)`:

```python
    for extra in indices[1:]:
        written[f"index:{extra.stem}"] = extra
```

Quem consome `generate_all_artifacts` espera `dict[str, Path]` e itera as chaves conhecidas; as chaves `index:<grupo>` são novas e não quebram esses consumidores. Conferir com `grep -rn "generate_all_artifacts" --include=*.py gclaude_indexer/` antes de fechar a tarefa.

Acrescentar as chaves de sumário nos três blocos de `gclaude_indexer/i18n.py`:

```python
        "artifact.index.summary_title": "Índice por grupo",
        "artifact.index.summary_row": "- **{group}** — {sheets}, {files} arquivo(s) — `{file}`",
```
```python
        "artifact.index.summary_title": "Index by group",
        "artifact.index.summary_row": "- **{group}** — {sheets}, {files} file(s) — `{file}`",
```
```python
        "artifact.index.summary_title": "Índice por grupo",
        "artifact.index.summary_row": "- **{group}** — {sheets}, {files} archivo(s) — `{file}`",
```

Em `generate_all_artifacts`, acomodar a lista onde antes vinha um `Path` só.

- [ ] **Step 4: Rodar a suíte**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 636. Todo teste que chamava `generate_index_md(...)` esperando um `Path` precisa passar a ler `caminhos[0]`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/artifacts.py gclaude_indexer/i18n.py
git commit -m "feat(índice): sumário dos grupos e um índice por grupo

O index.md saía com 5443 linhas e 1,58 MB num arquivo só. O sumário cabe
em poucos KB e diz qual arquivo abrir.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: O pacote do Projeto leva os índices por grupo

**Files:**
- Modify: `gclaude_indexer/claude_package.py`
- Modify: `gclaude_indexer/artifacts.py` (`generate_project_instructions_md`)
- Test: `tests/test_phase21.py`

**Interfaces:**
- Consumes: `group_index_filename` da Tarefa 9

- [ ] **Step 1: Escrever o teste**

```python
import zipfile


def test_pacote_do_projeto_leva_os_indices_por_grupo(tmp_path):
    from gclaude_indexer.claude_package import generate_claude_project_package

    for nome in ("index.md", group_index_filename("Processo"), "timeline.md",
                 "review.md", "project_instructions.md"):
        (tmp_path / nome).write_text("conteudo", encoding="utf-8")
    config = _config_minima(tmp_path)

    dados = generate_claude_project_package(config, "pt-BR")

    with zipfile.ZipFile(__import__("io").BytesIO(dados)) as zf:
        nomes = zf.namelist()
    assert group_index_filename("Processo") in nomes
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_phase21.py -k pacote -v
```
Expected: FALHA — o zip só leva os quatro nomes fixos.

- [ ] **Step 3: Implementar**

Em `gclaude_indexer/claude_package.py`, dentro do `with zipfile.ZipFile(...)`, logo depois do laço de `ARTIFACT_NAMES`:

```python
        # Os índices por grupo (fase 21). O `index.md` virou sumário: sem
        # estes, o pacote leva o mapa e deixa o território para trás.
        for extra in sorted(output_folder.glob("index-*.md")):
            zip_file.write(extra, arcname=extra.name)
```

No texto de `_GUIDE`, nos três idiomas, trocar a frase que lista os arquivos do pacote pela que explica o caminho. Em pt:

```python
   arquivos deste pacote: `index.md` (o sumário dos grupos), os
   `index-<grupo>.md` de cada grupo, `timeline.md`, `review.md` e
   `project_instructions.md` — para achar um documento, o Claude lê o
   sumário, escolhe o grupo e abre o índice daquele grupo.
```

Em en:

```python
   files in this package: `index.md` (the summary of groups), one
   `index-<group>.md` per group, `timeline.md`, `review.md` and
   `project_instructions.md` — to find a document, Claude reads the
   summary, picks the group and opens that group's index.
```

Em es:

```python
   archivos de este paquete: `index.md` (el resumen de los grupos), los
   `index-<grupo>.md` de cada grupo, `timeline.md`, `review.md` y
   `project_instructions.md` — para encontrar un documento, Claude lee el
   resumen, elige el grupo y abre el índice de ese grupo.
```

Em `gclaude_indexer/artifacts.py`, `generate_project_instructions_md` monta o texto a partir de chaves que recebem `index_file=INDEX_FILENAME`. Acrescentar à instrução, nos três blocos de `i18n.py`, a frase que descreve o sumário — a chave já existente que cita `{index_file}` passa a explicar que ele é o sumário e que os índices por grupo estão ao lado.

- [ ] **Step 4: Rodar a suíte**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 637.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase21.py gclaude_indexer/claude_package.py gclaude_indexer/artifacts.py gclaude_indexer/i18n.py
git commit -m "feat(pacote): o zip do Projeto leva os índices por grupo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# Parte 4 — Entrega

---

### Task 11: Versão 1.3.2, instalador compilado e publicado

Entregar código commitado não é entregar: o usuário testa instalando o executável.

**Files:**
- Modify: `gclaude_indexer/web/app.py:78` (`SYSTEM_VERSION`)
- Modify: `CHANGELOG.md`, `README.md`, `docs/README.pt-BR.md`, `docs/README.es.md`

- [ ] **Step 1: Subir a versão**

Em `gclaude_indexer/web/app.py:78`: `SYSTEM_VERSION = "1.3.2"`.

- [ ] **Step 2: Escrever a entrada do CHANGELOG**

Em `CHANGELOG.md`, no topo, uma entrada `## 1.3.2` que narre os cinco defeitos com os números medidos: 153 de 1449 janelas, 612 peças cegas, razão 1,45 contra 3,0, cobertura que marcava 100,0% num índice com buraco de 500 folhas, nota de 89 para 83.

- [ ] **Step 3: Atualizar o nome do instalador nos três READMEs**

`README.md`, `docs/README.pt-BR.md` e `docs/README.es.md` citam `GClaude-Indexer-Setup-<versão>.exe` literalmente. Trocar para `1.3.2` nos três.

- [ ] **Step 4: Rodar a suíte inteira uma última vez**

Run:
```
"%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```
Expected: 637 passando, zero falhas. **Não seguir com falha nenhuma.**

- [ ] **Step 5: Compilar o instalador**

Run:
```
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```
Expected: `dist\GClaude-Indexer-Setup-1.3.2.exe`, ~3 MB. A versão é lida de `SYSTEM_VERSION`; nunca passar à mão.

- [ ] **Step 6: Commit, push e PR**

```bash
git add -A
git commit -m "chore(release): v1.3.2 — contexto calibrado e nota honesta

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin fix/razao-chars-token
gh pr create --title "Fase 21: contexto calibrado e nota honesta (v1.3.2)" --body "..."
```

O corpo do PR termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 7: Publicar o release com o `.exe`**

Depois do merge:

```bash
git tag v1.3.2 && git push origin v1.3.2
powershell -Command "Get-FileHash -Algorithm SHA256 dist\GClaude-Indexer-Setup-1.3.2.exe"
gh release create v1.3.2 dist\GClaude-Indexer-Setup-1.3.2.exe --title "v1.3.2" --notes "..."
```

Colar o SHA-256 nas notas e **conferir baixando o asset publicado de volta**. Só então relatar como pronto, dizendo explicitamente qual arquivo baixar para testar.

---

## Verificação na corrida real

Com a 1.3.2 instalada, reindexando o acervo do zero:

- o aviso `o modelo não respondeu sobre N de N página(s)` some, ou vem seguido da retentativa que o resolveu;
- o resumo da etapa 6 deixa de terminar em `baixa=0` quando houver página cega;
- `alta=` sobe das 4666 atuais, `media=` cai das 777;
- **a nota cai antes de subir**: 89 era falso, 83 é o valor honesto do resultado atual, e é sobre 83 que a correção precisa mostrar ganho;
- `index.md` abre como sumário, e `f. 417` leva a `Vol 2.pdf, p. 145`.

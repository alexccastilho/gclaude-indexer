# Fase 12 — Correções de Interface: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os 12 defeitos de interface do GClaude Indexer v1.0 levantados no primeiro uso real — internacionalização do status, comportamento da barra de progresso, legibilidade do formulário e dos temas, e limpeza de arquivos intermediários.

**Architecture:** Todas as mudanças ficam na camada web (`gclaude_indexer/web/`) e no `i18n.py`, exceto a Tarefa 11 (limpeza de intermediários), que acrescenta um módulo novo no pacote raiz. O princípio que guia a maior parte do trabalho: **a lógica de negócio devolve chaves estáveis em ASCII, o template traduz**. Hoje `app.py` devolve strings em português com acento (`"concluída"`) que servem simultaneamente como texto de tela, classe CSS e valor de comparação em `if` — três papéis num único valor, e é dessa sobrecarga que vêm quatro dos doze defeitos.

**Tech Stack:** Python 3.12, FastAPI 0.115, Jinja2 3.1, HTMX (vendorizado), SQLite, pytest 8.3.

**Spec:** `ESPECIFICACAO.md` (seções 6 = interface, 10.3 = dependências externas, 11 = instalação/execução). Este plano não altera nenhuma decisão da especificação: corrige a implementação para cumpri-la — a seção 6 já exige interface em português, inglês e espanhol.

## Global Constraints

Copiadas do estado atual do projeto. **Todas as tarefas herdam estas regras.**

- **Python 3.12** — o venv da máquina fica em `%LOCALAPPDATA%\GClaudeIndexer\venv`, nunca dentro da pasta sincronizada pelo Drive (seção 11.1). Interpretador dos testes: `%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe`.
- **Sem framework de front-end e sem build de JavaScript.** O único script vendorizado é `static/htmx.min.js`. JavaScript novo vai inline no template, em `(function () { ... })()`, sem dependência de rede.
- **Nenhuma chamada de rede externa.** O Ollama é sempre `http://127.0.0.1:11434` — host fixo em loopback, jamais vindo de configuração.
- **Três idiomas obrigatórios**: `pt`, `en`, `es`. Toda chave nova em `i18n.py` entra nos **três** dicionários. Uma chave presente só em `pt` cai no fallback e reintroduz exatamente o defeito da Tarefa 1.
- **Código e identificadores em português** (`varredura`, `pasta_saida`, `situacao`) — é a convenção de todo o repositório.
- **O projeto não é um repositório git.** Onde o fluxo TDD normalmente pediria um commit, este plano pede a execução da suíte inteira. Não invente um `git init`.
- **A suíte tem 171 testes e está verde.** Nenhuma tarefa pode terminar com regressão: `python -m pytest -q` precisa fechar com `N passed` e zero falhas.
- **Comando de teste padrão:**
  ```powershell
  & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -v
  ```
- **Arquivo de testes desta fase:** `tests/test_fase12.py`, criado na Tarefa 1 e estendido pelas demais. Segue o padrão de `tests/test_fase9.py`: fixture `cliente` com `monkeypatch` do `pasta_local_maquina`, helper `_criar_projeto`, helper `_esperar_etapa_terminar`.

---

## File Structure

| Arquivo | Responsabilidade | Tarefas |
|---|---|---|
| `gclaude_indexer/web/estado_etapas.py` | **(novo)** Chaves estáveis de etapa/situação e o cálculo do status, sem nenhum texto de idioma | 1 |
| `gclaude_indexer/web/app.py` | Rotas; passa a delegar o status para `estado_etapas.py` | 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12 |
| `gclaude_indexer/web/execucao_bg.py` | Tarefas em segundo plano, progresso e ETA | 2, 3, 4 |
| `gclaude_indexer/web/i18n.py` | Tabelas `pt`/`en`/`es` | 1, 4, 5, 6, 7, 8, 9, 10, 11, 12 |
| `gclaude_indexer/web/tema.py` | Catálogo de temas | 9 |
| `gclaude_indexer/web/modelos_ollama.py` | **(novo)** Consulta `/api/tags` do Ollama | 8 |
| `gclaude_indexer/limpeza.py` | **(novo)** Apaga intermediários da pasta de saída | 11 |
| `gclaude_indexer/tipos.py` | Categorias de extensão; ganha o agrupamento por família | 6 |
| `gclaude_indexer/web/templates/*.html` | Telas e fragmentos | quase todas |
| `gclaude_indexer/web/static/estilo.css` | Tokens `--cor-*` e regras de layout | 1, 5, 6, 9, 10, 11 |
| `tests/test_fase12.py` | **(novo)** Testes desta fase | todas |

O único arquivo que muda em quase toda tarefa é `i18n.py`, e sempre por acréscimo de chaves — sem conflito estrutural entre tarefas.

---

### Task 1: Chaves estáveis de situação e status traduzido

O defeito de origem, e pré-requisito das Tarefas 2, 4 e 12.

`app.py:_status_etapas()` devolve hoje `{"situacao": "concluída", "titulo": "1. Varredura", "contagem": "3 arquivo(s)"}` — português cru. Esse mesmo valor é usado em três lugares incompatíveis:

1. `_etapas.html:10` como texto na tela → fica em português mesmo com inglês selecionado;
2. no mesmo ponto como classe CSS, `class="situacao-concluída"` → seletor com acento e cedilha;
3. `app.py:_proxima_etapa_pendente()` compara `etapa["situacao"] not in ("concluída", "rodando")` → **traduzir sem corrigir isto quebra o botão "Rodar etapa seguinte"**, que passaria a reprocessar sempre a primeira etapa.

A correção separa os três papéis: chave ASCII para CSS e comparação, tradução para a tela.

**Files:**
- Create: `gclaude_indexer/web/estado_etapas.py`
- Create: `tests/test_fase12.py`
- Modify: `gclaude_indexer/web/app.py:190-253` (remover `_situacao_projeto` e `_status_etapas`), `:411-416` (`_proxima_etapa_pendente`), `:280-287` (`tela_projetos`)
- Modify: `gclaude_indexer/web/templates/_etapas.html:7-13`
- Modify: `gclaude_indexer/web/templates/projetos.html:20`
- Modify: `gclaude_indexer/web/i18n.py` (chaves `etapa.*` e `situacao.*` nos três idiomas)
- Modify: `gclaude_indexer/web/static/estilo.css` (seletores `.situacao-*`)
- Modify: `tests/test_fase9.py:159, 165-167, 176-196`

**Interfaces:**
- Produces:
  - `ETAPAS: tuple[str, ...]` = `("varredura", "conversao", "extracao", "janelas", "classificacao")`
  - `SITUACOES: tuple[str, ...]` = `("nao_iniciada", "pendente", "rodando", "concluida")`
  - `status_etapas(conn, esta_rodando) -> list[dict]` — `esta_rodando` é um callable `(chave: str) -> bool`, o que mantém o módulo sem dependência do `gerenciador_tarefas`. Cada item: `{"chave": str, "situacao": str, "vars": dict[str, int]}`.
  - `proxima_etapa_pendente(etapas) -> str | None`
  - `situacao_projeto(pasta_saida) -> tuple[str, dict[str, int]]` — chave de situação e variáveis para interpolação.
- Consumes: nada de tarefas anteriores.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_fase12.py` com o cabeçalho compartilhado (as demais tarefas acrescentam testes neste mesmo arquivo):

```python
"""Testes da Fase 12: correções de interface levantadas no primeiro uso real."""

from __future__ import annotations

import time

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalogo as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.web.app import app
from gclaude_indexer.web.execucao_bg import gerenciador_tarefas


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "pasta_local_maquina", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "pasta_local_maquina", lambda: pasta_local)
    return TestClient(app)


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_projeto(cliente, tmp_path, nome="Projeto fase 12", **campos_extra):
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / f"{nome.replace(' ', '_')}_indexado"
    _pdf(
        origem / "volume_1" / "peca.pdf",
        "OFÍCIO No 1\nAssunto: teste da fase 12, com texto suficiente para não acionar OCR.\n10/01/2024",
    )
    dados = {
        "nome": nome, "tema": "Acervo de teste", "pasta_origem": str(origem), "pasta_saida": str(saida),
        "tipo_acervo": "processo", "agrupador_modo": "subpasta", "agrupador_padrao": "",
        "extensoes": ["pdf", "docx", "imagens"], "paginas_por_bloco": "80", "paginas_por_janela": "16",
        "sobreposicao": "2", "caracteres_por_pagina": "2000", "idioma_ocr": "por",
        "motor_classificacao": "regras", "modelo_local": "automatico", "papel_instrucoes": "", "regras_extras": "",
    }
    dados.update(campos_extra)
    resposta = cliente.post("/projetos/novo", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


def _esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        tarefa = gerenciador_tarefas.obter(projeto_id, etapa)
        if tarefa is not None and not tarefa.rodando:
            return tarefa
        time.sleep(0.05)
    raise AssertionError(f"etapa '{etapa}' não terminou em {timeout}s")


# --- Tarefa 1: chaves estáveis de situação ---------------------------------


def test_status_etapas_devolve_chaves_ascii_e_nao_texto_de_tela(cliente, tmp_path):
    from gclaude_indexer.projeto import carregar_projeto
    from gclaude_indexer.web.estado_etapas import ETAPAS, SITUACOES, status_etapas

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    entrada = cliente.get("/projetos").text
    assert entrada  # a tela de projetos continua respondendo

    from gclaude_indexer.catalogo import buscar_projeto
    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        etapas = status_etapas(conn, lambda _chave: False)
    finally:
        conn.close()

    assert [e["chave"] for e in etapas] == list(ETAPAS)
    for item in etapas:
        assert item["situacao"] in SITUACOES, item
        assert item["situacao"].isascii(), "a situação vira classe CSS: precisa ser ASCII"
    assert etapas[0]["situacao"] == "concluida"
    assert etapas[0]["vars"] == {"total": 1}


def test_proxima_etapa_pendente_usa_chave_e_nao_texto_traduzido():
    from gclaude_indexer.web.estado_etapas import proxima_etapa_pendente

    etapas = [
        {"chave": "varredura", "situacao": "concluida", "vars": {}},
        {"chave": "conversao", "situacao": "rodando", "vars": {}},
        {"chave": "extracao", "situacao": "nao_iniciada", "vars": {}},
    ]
    assert proxima_etapa_pendente(etapas) == "extracao"


def test_tela_de_execucao_traduz_o_status_para_ingles(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    cliente.cookies.set("idioma", "en")
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao").text

    assert "1. Scan" in corpo
    assert "done" in corpo
    assert "concluída" not in corpo
    assert "1. Varredura" not in corpo
    assert 'situacao-concluida' in corpo  # classe CSS estável, sem acento
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'gclaude_indexer.web.estado_etapas'`.

- [ ] **Step 3: Criar `gclaude_indexer/web/estado_etapas.py`**

```python
"""Estado das etapas sem nenhum texto de idioma.

Este módulo devolve *chaves estáveis* (`"concluida"`, `"varredura"`), nunca
texto de tela. O texto vem de `i18n.py`, escolhido no template pelo idioma do
usuário. A separação existe porque a chave tem três consumidores com
exigências diferentes: o texto exibido (traduzível), a classe CSS (precisa
ser ASCII) e a comparação em `proxima_etapa_pendente` (não pode depender do
idioma — era esse acoplamento que fazia o botão "Rodar etapa seguinte"
reprocessar a primeira etapa quando o texto mudava).
"""

from __future__ import annotations

from typing import Callable

from ..projeto import carregar_projeto

ETAPAS: tuple[str, ...] = ("varredura", "conversao", "extracao", "janelas", "classificacao")
SITUACOES: tuple[str, ...] = ("nao_iniciada", "pendente", "rodando", "concluida")


def status_etapas(conn, esta_rodando: Callable[[str], bool]) -> list[dict]:
    """Situação de cada etapa a partir das contagens no banco.

    `esta_rodando(chave)` responde se há tarefa em segundo plano ativa para a
    etapa — passado de fora para este módulo não depender de `execucao_bg`.
    """
    total_arquivos = conn.execute("SELECT COUNT(*) FROM arquivo").fetchone()[0]
    descobertos = conn.execute("SELECT COUNT(*) FROM arquivo WHERE status = 'descoberto'").fetchone()[0]
    convertidos = conn.execute(
        "SELECT COUNT(*) FROM arquivo WHERE status IN ('convertido', 'extraido')"
    ).fetchone()[0]
    falharam = conn.execute("SELECT COUNT(*) FROM arquivo WHERE status = 'falhou'").fetchone()[0]
    extraidos = conn.execute("SELECT COUNT(*) FROM arquivo WHERE status = 'extraido'").fetchone()[0]
    total_paginas = conn.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
    total_janelas = conn.execute("SELECT COUNT(*) FROM janela").fetchone()[0]
    janelas_feitas = conn.execute("SELECT COUNT(*) FROM janela WHERE status = 'feita'").fetchone()[0]
    janelas_pendentes = total_janelas - janelas_feitas

    def concluida_ou(pronta: bool, iniciada: bool) -> str:
        if pronta:
            return "concluida"
        return "pendente" if iniciada else "nao_iniciada"

    bruto = [
        ("varredura", concluida_ou(total_arquivos > 0, total_arquivos > 0), {"total": total_arquivos}),
        ("conversao", concluida_ou(total_arquivos > 0 and descobertos == 0, total_arquivos > 0),
         {"convertidos": convertidos, "falharam": falharam, "pendentes": descobertos}),
        ("extracao", concluida_ou(convertidos > 0 and convertidos == extraidos, convertidos > 0),
         {"paginas": total_paginas}),
        ("janelas", concluida_ou(total_janelas > 0 and extraidos > 0, total_janelas > 0),
         {"janelas": total_janelas}),
        ("classificacao", concluida_ou(total_janelas > 0 and janelas_pendentes == 0, total_janelas > 0),
         {"feitas": janelas_feitas, "pendentes": janelas_pendentes}),
    ]

    return [
        {"chave": chave, "situacao": "rodando" if esta_rodando(chave) else situacao, "vars": variaveis}
        for chave, situacao, variaveis in bruto
    ]


def proxima_etapa_pendente(etapas: list[dict]) -> str | None:
    """Primeira etapa que ainda não terminou nem está em andamento."""
    for etapa in etapas:
        if etapa["situacao"] not in ("concluida", "rodando"):
            return etapa["chave"]
    return None


def situacao_projeto(pasta_saida: str) -> tuple[str, dict[str, int]]:
    """Resumo de uma linha para a tela de Projetos: chave e variáveis."""
    try:
        _config, conn = carregar_projeto(pasta_saida)
    except Exception:
        return "indisponivel", {}
    try:
        total_pecas = conn.execute("SELECT COUNT(*) FROM peca").fetchone()[0]
        janelas_pendentes = conn.execute(
            "SELECT COUNT(*) FROM janela WHERE status = 'pendente'"
        ).fetchone()[0]
        total_arquivos = conn.execute("SELECT COUNT(*) FROM arquivo").fetchone()[0]
    finally:
        conn.close()

    if total_arquivos == 0:
        return "nao_iniciado", {}
    if total_pecas > 0:
        return "importado", {"pecas": total_pecas}
    if janelas_pendentes > 0:
        return "classificacao_pendente", {"janelas": janelas_pendentes}
    return "em_processamento", {}
```

- [ ] **Step 4: Acrescentar as chaves aos três idiomas em `i18n.py`**

Dentro do dicionário `"pt"`:

```python
        "etapa.varredura.titulo": "1. Varredura",
        "etapa.conversao.titulo": "2–3. Conversão, OCR e fatiamento",
        "etapa.extracao.titulo": "4. Extração por página",
        "etapa.janelas.titulo": "5. Preparação de janelas",
        "etapa.classificacao.titulo": "6. Classificação",
        "etapa.varredura.contagem": "{total} arquivo(s)",
        "etapa.conversao.contagem": "{convertidos} convertido(s), {falharam} falhou(aram), {pendentes} pendente(s)",
        "etapa.extracao.contagem": "{paginas} página(s) extraída(s)",
        "etapa.janelas.contagem": "{janelas} janela(s)",
        "etapa.classificacao.contagem": "{feitas} feita(s), {pendentes} pendente(s)",
        "situacao.nao_iniciada": "não iniciada",
        "situacao.pendente": "pendente",
        "situacao.rodando": "rodando",
        "situacao.concluida": "concluída",
        "projeto.situacao.indisponivel": "indisponível",
        "projeto.situacao.nao_iniciado": "não iniciado",
        "projeto.situacao.importado": "{pecas} peça(s) importada(s)",
        "projeto.situacao.classificacao_pendente": "classificação pendente ({janelas} janela(s))",
        "projeto.situacao.em_processamento": "em processamento",
```

Dentro do dicionário `"en"`:

```python
        "etapa.varredura.titulo": "1. Scan",
        "etapa.conversao.titulo": "2–3. Conversion, OCR and slicing",
        "etapa.extracao.titulo": "4. Per-page extraction",
        "etapa.janelas.titulo": "5. Window preparation",
        "etapa.classificacao.titulo": "6. Classification",
        "etapa.varredura.contagem": "{total} file(s)",
        "etapa.conversao.contagem": "{convertidos} converted, {falharam} failed, {pendentes} pending",
        "etapa.extracao.contagem": "{paginas} page(s) extracted",
        "etapa.janelas.contagem": "{janelas} window(s)",
        "etapa.classificacao.contagem": "{feitas} done, {pendentes} pending",
        "situacao.nao_iniciada": "not started",
        "situacao.pendente": "pending",
        "situacao.rodando": "running",
        "situacao.concluida": "done",
        "projeto.situacao.indisponivel": "unavailable",
        "projeto.situacao.nao_iniciado": "not started",
        "projeto.situacao.importado": "{pecas} item(s) imported",
        "projeto.situacao.classificacao_pendente": "classification pending ({janelas} window(s))",
        "projeto.situacao.em_processamento": "in progress",
```

Dentro do dicionário `"es"`:

```python
        "etapa.varredura.titulo": "1. Barrido",
        "etapa.conversao.titulo": "2–3. Conversión, OCR y troceado",
        "etapa.extracao.titulo": "4. Extracción por página",
        "etapa.janelas.titulo": "5. Preparación de ventanas",
        "etapa.classificacao.titulo": "6. Clasificación",
        "etapa.varredura.contagem": "{total} archivo(s)",
        "etapa.conversao.contagem": "{convertidos} convertido(s), {falharam} fallaron, {pendentes} pendiente(s)",
        "etapa.extracao.contagem": "{paginas} página(s) extraída(s)",
        "etapa.janelas.contagem": "{janelas} ventana(s)",
        "etapa.classificacao.contagem": "{feitas} hecha(s), {pendentes} pendiente(s)",
        "situacao.nao_iniciada": "no iniciada",
        "situacao.pendente": "pendiente",
        "situacao.rodando": "en curso",
        "situacao.concluida": "concluida",
        "projeto.situacao.indisponivel": "no disponible",
        "projeto.situacao.nao_iniciado": "no iniciado",
        "projeto.situacao.importado": "{pecas} pieza(s) importada(s)",
        "projeto.situacao.classificacao_pendente": "clasificación pendiente ({janelas} ventana(s))",
        "projeto.situacao.em_processamento": "en proceso",
```

- [ ] **Step 5: Ligar `app.py` ao módulo novo**

Acrescente ao bloco de imports relativos de `app.py`:

```python
from .estado_etapas import proxima_etapa_pendente, situacao_projeto, status_etapas
```

Apague as funções `_situacao_projeto` (linhas 190-207), `_status_etapas` (210-253) e `_proxima_etapa_pendente` (411-416).

Substitua `_contexto_etapas`:

```python
def _contexto_etapas(projeto_id: int, entrada, config: ConfigProjeto, conn) -> dict:
    return {
        "projeto": entrada,
        "etapas": status_etapas(conn, lambda chave: _etapa_rodando(projeto_id, chave)),
        "mostrar_claude_code": config.motor_classificacao == "claude_code",
        "comando_claude_code": COMANDO_PARA_O_USUARIO,
    }


def _etapa_rodando(projeto_id: int, chave: str) -> bool:
    tarefa = gerenciador_tarefas.obter(projeto_id, chave)
    return tarefa is not None and tarefa.rodando
```

Em `tela_execucao` e `reverificar_claude_code`, troque `_status_etapas(projeto_id, conn, config)` por `status_etapas(conn, lambda chave: _etapa_rodando(projeto_id, chave))`.

Em `executar_proxima_etapa`, troque as duas chamadas encadeadas por:

```python
        proxima = proxima_etapa_pendente(status_etapas(conn, lambda chave: _etapa_rodando(projeto_id, chave)))
```

Em `tela_projetos`, desempacote a tupla:

```python
@app.get("/projetos", response_class=HTMLResponse)
def tela_projetos(request: Request):
    projetos = []
    for e in listar_projetos():
        chave, variaveis = situacao_projeto(e.pasta_saida)
        projetos.append({
            "id": e.id, "nome": e.nome, "criado_em": e.criado_em,
            "situacao_chave": chave, "situacao_vars": variaveis,
        })
    return render(request, "projetos.html", {"projetos": projetos})
```

- [ ] **Step 6: Atualizar os templates**

`_etapas.html`, linhas 7-13 — o `replace(' ', '-')` some junto com os acentos:

```html
    {% for etapa in etapas %}
    <tr>
      <td>{{ t('etapa.' + etapa.chave + '.titulo') }}</td>
      <td><span class="situacao situacao-{{ etapa.situacao }}">{{ t('situacao.' + etapa.situacao) }}</span></td>
      <td>{{ t('etapa.' + etapa.chave + '.contagem', **etapa.vars) }}</td>
    </tr>
    {% endfor %}
```

`projetos.html`, linha 20:

```html
      <td>{{ t('projeto.situacao.' + p.situacao_chave, **p.situacao_vars) }}</td>
```

- [ ] **Step 7: Ajustar os seletores de situação no CSS**

São as linhas 284-287 de `estilo.css`. O estado atual mostra o rastro do problema: a linha 284 já lista **os dois** seletores, `.situacao-concluída, .situacao-concluida`, porque alguém tropeçou nisto antes e resolveu duplicando em vez de corrigir a origem. A linha 286 usa hífen (`.situacao-não-iniciada`) porque vinha do `replace(' ', '-')` do template, que a Tarefa 1 remove.

Substitua as quatro linhas por:

```css
.situacao-concluida { color: var(--cor-ok); font-weight: 600; }
.situacao-pendente { color: var(--cor-aviso); font-weight: 600; }
.situacao-nao_iniciada { color: var(--cor-texto-fraco); }
.situacao-rodando { color: var(--cor-destaque); font-weight: 600; }
```

Não deixe o seletor acentuado como "compatibilidade": depois desta tarefa nenhum caminho de código produz `situacao-concluída`, e mantê-lo só faria a próxima pessoa duvidar de qual dos dois está em uso.

As classes `.situacao-barra-*` (linhas 398-400) pertencem à barra de progresso, vêm de `calcular_progresso` e **já são ASCII** — não as toque.

- [ ] **Step 8: Atualizar `tests/test_fase9.py`**

Estes testes estão acoplados ao texto em português; passam a usar as chaves. Linha 159:

```python
    assert "1. Varredura" in resposta.text  # continua válido: o padrão é pt
```

Linhas 165-167 — o helper localiza pela classe CSS, então basta o valor esperado mudar:

```python
def _situacao_da_etapa(html: str, titulo: str) -> str:
    trecho = html.split(titulo, 1)[1]
    return trecho.split('situacao-')[1].split('"')[0]
```

Linhas 176-196 — troque toda ocorrência de `== "concluída"` por `== "concluida"`, de `!= "concluída"` por `!= "concluida"` e de `assert "concluída" in trecho` por `assert "concluida" in trecho`.

- [ ] **Step 9: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -v
```

Esperado: PASS nos três testes da Tarefa 1.

- [ ] **Step 10: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `174 passed` (171 anteriores + 3 novos), zero falhas.

---

### Task 2: A barra de progresso não some quando a etapa termina

`app.py:fragmento_progresso()` pergunta `gerenciador_tarefas.etapa_rodando(projeto_id)` e, se a resposta for `None`, chama `calcular_progresso(..., None)`, que devolve `{"situacao": "nenhuma"}`. No instante em que a etapa acaba, `rodando` vira `False` e a caixa inteira é trocada por "Nenhuma etapa rodando no momento." — a barra desaparece em vez de assentar em 100%.

`_progresso.html` já traz os ramos `concluida`, `parada` e `erro` (linhas 16-22), completamente escritos e nunca alcançados. Não é preciso mexer no template: basta a rota continuar entregando a última tarefa depois que ela termina.

**Files:**
- Modify: `gclaude_indexer/web/execucao_bg.py` (`GerenciadorTarefas`, novo método `ultima_do_projeto`)
- Modify: `gclaude_indexer/web/app.py:464-475` (`fragmento_progresso`)
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Consumes: `gerenciador_tarefas` e `calcular_progresso` (já existentes).
- Produces: `GerenciadorTarefas.ultima_do_projeto(projeto_id) -> TarefaEtapa | None` — a tarefa em andamento se houver; senão, a mais recente por `iniciado_em`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 2: o progresso não some ao terminar ----------------------------


def test_progresso_mostra_concluida_depois_que_a_etapa_termina(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    corpo = cliente.get(f"/projetos/{projeto_id}/execucao/progresso").text

    assert "situacao-barra-concluida" in corpo
    assert "100%" in corpo
    assert "Nenhuma etapa rodando" not in corpo


def test_progresso_vazio_quando_o_projeto_nunca_rodou(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao/progresso").text
    assert "Nenhuma etapa rodando" in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k progresso -v
```

Esperado: FAIL em `test_progresso_mostra_concluida_depois_que_a_etapa_termina` — `assert "situacao-barra-concluida" in corpo` falha, porque a resposta traz "Nenhuma etapa rodando no momento.".

- [ ] **Step 3: Acrescentar `ultima_do_projeto` ao `GerenciadorTarefas`**

Em `execucao_bg.py`, logo depois de `etapa_rodando`:

```python
    def ultima_do_projeto(self, projeto_id: int) -> TarefaEtapa | None:
        """A tarefa que interessa mostrar na barra: a que está rodando, ou —
        quando nenhuma está — a última que rodou, para que a caixa assente em
        "concluída"/"pausada"/"erro" em vez de sumir da tela no instante em
        que a etapa acaba."""
        with self._trava:
            do_projeto = [tarefa for (pid, _etapa), tarefa in self._tarefas.items() if pid == projeto_id]
        if not do_projeto:
            return None
        rodando = [tarefa for tarefa in do_projeto if tarefa.rodando]
        if rodando:
            return max(rodando, key=lambda tarefa: tarefa.iniciado_em)
        return max(do_projeto, key=lambda tarefa: tarefa.iniciado_em)
```

- [ ] **Step 4: Usar o método novo na rota**

Substitua o corpo de `fragmento_progresso` em `app.py`:

```python
@app.get("/projetos/{projeto_id}/execucao/progresso", response_class=HTMLResponse)
def fragmento_progresso(request: Request, projeto_id: int):
    with _projeto_aberto(projeto_id) as (entrada, _config, _conn):
        tarefa = gerenciador_tarefas.ultima_do_projeto(projeto_id)
        progresso = calcular_progresso(entrada.pasta_saida, tarefa)
        progresso["tempo_decorrido"] = _formatar_tempo(
            None if tarefa is None else time.monotonic() - tarefa.iniciado_em
        )
        progresso["eta_formatado"] = _formatar_tempo(progresso.get("eta_segundos"))

    return render(request, "_progresso.html", {"projeto": entrada, "progresso": progresso})
```

- [ ] **Step 5: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k progresso -v
```

Esperado: PASS nos dois.

- [ ] **Step 6: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `176 passed`.

---

### Task 3: O total da varredura respeita as extensões escolhidas

`execucao_bg.py:_contar_arquivos_para_varrer()` percorre `pasta_origem.rglob("*")` e conta **todo** arquivo, sem consultar `extensao_permitida()`. Já `_contagem_atual(conn, "varredura")` conta linhas na tabela `arquivo`, onde só entra o que passou pelo filtro de extensões. Numerador filtrado, denominador não: num acervo com 500 arquivos dos quais 60 são PDF e só "pdf" foi marcado, a barra chega a 12% e para — dando a impressão de travamento.

**Files:**
- Modify: `gclaude_indexer/web/execucao_bg.py:56-63`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Consumes: `extensao_permitida(extensao_com_ponto, categorias)` de `gclaude_indexer/tipos.py`.
- Produces: nenhuma assinatura nova — `_contar_arquivos_para_varrer(config)` mantém a assinatura e passa a devolver a contagem filtrada.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 3: total da varredura filtrado por extensão --------------------


def test_total_da_varredura_conta_so_as_extensoes_marcadas(tmp_path):
    from gclaude_indexer.config import ConfigProjeto
    from gclaude_indexer.web.execucao_bg import _contar_arquivos_para_varrer

    origem = tmp_path / "origem"
    origem.mkdir()
    _pdf(origem / "a.pdf", "conteúdo")
    _pdf(origem / "b.pdf", "conteúdo")
    (origem / "planilha.xlsx").write_bytes(b"nao importa")
    (origem / "foto.jpg").write_bytes(b"nao importa")
    (origem / "notas.txt").write_text("nao importa", encoding="utf-8")

    config = ConfigProjeto(
        nome="Filtro", pasta_origem=str(origem), pasta_saida=str(tmp_path / "saida"),
        extensoes=["pdf"],
    )
    assert _contar_arquivos_para_varrer(config) == 2


def test_total_da_varredura_com_todos_ignora_binarios_bloqueados(tmp_path):
    from gclaude_indexer.config import ConfigProjeto
    from gclaude_indexer.web.execucao_bg import _contar_arquivos_para_varrer

    origem = tmp_path / "origem_todos"
    origem.mkdir()
    _pdf(origem / "a.pdf", "conteúdo")
    (origem / "notas.txt").write_text("x", encoding="utf-8")
    (origem / "programa.exe").write_bytes(b"MZ")

    config = ConfigProjeto(
        nome="Todos", pasta_origem=str(origem), pasta_saida=str(tmp_path / "saida_todos"),
        extensoes=["todos"],
    )
    assert _contar_arquivos_para_varrer(config) == 2
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k varredura -v
```

Esperado: FAIL — `assert 5 == 2` no primeiro teste, `assert 3 == 2` no segundo.

- [ ] **Step 3: Aplicar o filtro**

Em `execucao_bg.py`, acrescente ao bloco de imports relativos:

```python
from ..tipos import extensao_permitida
```

E substitua a função:

```python
def _contar_arquivos_para_varrer(config: ConfigProjeto) -> int:
    """Denominador da barra da varredura. Precisa usar exatamente o mesmo
    filtro que `varredura.py` aplica ao inserir na tabela `arquivo` — senão o
    numerador conta só os arquivos aceitos e o denominador conta a pasta
    inteira, e a barra trava numa fração que nunca chega a 100%."""
    pasta_origem = Path(config.pasta_origem).resolve()
    pasta_saida = Path(config.pasta_saida).resolve()
    total = 0
    for caminho in pasta_origem.rglob("*"):
        if not caminho.is_file() or caminho.is_relative_to(pasta_saida):
            continue
        if not extensao_permitida(caminho.suffix.lower(), config.extensoes):
            continue
        total += 1
    return total
```

> O `.lower()` é redundante — `extensao_permitida` já normaliza internamente (`tipos.py:61`) — mas repete literalmente o que `varredura.py:142` faz antes de chamar a mesma função. Os dois lados precisam ser lidos lado a lado e reconhecidos como idênticos.

- [ ] **Step 4: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k varredura -v
```

Esperado: PASS nos dois.

- [ ] **Step 5: Conferir que o filtro bate com o da varredura**

Abra `gclaude_indexer/varredura.py` e confirme que a condição de inclusão de arquivo usa `extensao_permitida(caminho.suffix, config.extensoes)` com os mesmos argumentos. Se a varredura aplicar alguma exclusão adicional (por exemplo, arquivos ocultos ou dentro da pasta de saída), replique-a aqui — os dois lados precisam contar o mesmo conjunto.

- [ ] **Step 6: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `178 passed`.

---

### Task 4: Nome legível da etapa na barra de progresso

`_progresso.html:7` imprime `{{ progresso.etapa }}`, e `calcular_progresso` devolve nesse campo a chave técnica: a barra mostra `conversao` — sem acento, sem numeração, sem tradução — onde a tabela logo acima mostra "2–3. Conversão, OCR e fatiamento". Com as chaves `etapa.*.titulo` já criadas na Tarefa 1, é só o template traduzir.

**Files:**
- Modify: `gclaude_indexer/web/templates/_progresso.html:7`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Consumes: `t('etapa.' + chave + '.titulo')` da Tarefa 1; `progresso["etapa"]`, que `calcular_progresso` já devolve como chave ASCII.
- Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 4: nome legível da etapa na barra ------------------------------


def test_barra_de_progresso_mostra_o_titulo_da_etapa_e_nao_a_chave(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    corpo = cliente.get(f"/projetos/{projeto_id}/execucao/progresso").text
    assert "1. Varredura" in corpo
    assert ">varredura<" not in corpo


def test_barra_de_progresso_traduz_o_titulo_da_etapa(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    cliente.cookies.set("idioma", "es")
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao/progresso").text
    assert "1. Barrido" in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k barra_de_progresso -v
```

Esperado: FAIL — a resposta traz `<strong>varredura</strong>`.

- [ ] **Step 3: Traduzir no template**

Em `_progresso.html`, linha 7:

```html
    <strong>{{ t('etapa.' + progresso.etapa + '.titulo') }}</strong>
```

- [ ] **Step 4: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k barra_de_progresso -v
```

Esperado: PASS nos dois.

- [ ] **Step 5: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `180 passed`.

---

### Task 5: Log ao vivo — mais linhas, filtro por nível e rolagem presa no fim

O painel de log já se atualiza a cada 2s via HTMX (`execucao.html:66`), mas: mostra só as 50 últimas linhas; a cada troca de conteúdo o navegador volta ao topo do bloco, então a linha mais recente sai de vista; e não há como isolar erros no meio de centenas de mensagens `info`.

O nível do evento já vem em `evento.nivel` e vira `class="log-{{ evento.nivel }}"` — o filtro pode ser puramente CSS, sem tocar no servidor.

**Files:**
- Modify: `gclaude_indexer/web/app.py:377-399` (`tela_execucao` e `fragmento_log`)
- Modify: `gclaude_indexer/web/templates/execucao.html:65-68`
- Modify: `gclaude_indexer/web/templates/_log.html`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces: constante `LINHAS_DE_LOG = 200` em `app.py`, usada pelas duas rotas que listam eventos.
- Consumes: `listar_eventos(conn)` (já existente), `evento.nivel` ∈ `{"info", "aviso", "erro"}`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 5: log ao vivo -------------------------------------------------


def test_log_mostra_ate_200_linhas(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.eventos import registrar_evento
    from gclaude_indexer.projeto import carregar_projeto

    projeto_id = _criar_projeto(cliente, tmp_path)
    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        for i in range(220):
            registrar_evento(conn, "varredura", "info", f"mensagem numero {i}")
        conn.commit()
    finally:
        conn.close()

    corpo = cliente.get(f"/projetos/{projeto_id}/execucao/log").text

    # Não asserte um número de mensagem específico na borda da janela: criar o
    # projeto já registra eventos próprios, então o corte de 200 cai num ponto
    # que depende de quantos foram. O que precisa valer é o teto e a cauda.
    assert "mensagem numero 219" in corpo, "a mensagem mais recente tem que aparecer"
    assert "mensagem numero 0" not in corpo, "as mais antigas têm que ficar de fora"
    assert corpo.count("<li") <= 200, "o painel não pode passar de 200 linhas"
    assert corpo.count("<li") >= 190, "e precisa estar de fato usando a janela nova"


def test_tela_de_execucao_tem_filtro_de_nivel_e_rolagem_automatica(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao").text
    assert 'id="filtro-log"' in corpo
    assert 'value="erro"' in corpo
    assert 'data-nivel-log' in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k log -v
```

Esperado: FAIL — o corpo traz só 50 linhas e não tem `id="filtro-log"`.

- [ ] **Step 3: Elevar o limite no servidor**

Em `app.py`, junto de `VERSAO_SISTEMA`:

```python
# 50 linhas cobriam menos de um minuto de varredura num acervo real — o
# painel rolava para fora antes de dar tempo de ler. 200 cabe na memória
# sem paginação e cobre a janela de acompanhamento que o usuário usa.
LINHAS_DE_LOG = 200
```

Em `tela_execucao` e em `fragmento_log`, troque `listar_eventos(conn)[-50:]` por `listar_eventos(conn)[-LINHAS_DE_LOG:]`.

- [ ] **Step 4: Marcar o nível em cada linha**

Em `_log.html`, acrescente o atributo que o CSS do filtro vai usar:

```html
<ul class="log">
  {% for evento in eventos %}
  <li class="log-{{ evento.nivel }}" data-nivel-log="{{ evento.nivel }}">
    <span class="log-hora">{{ data_hora(evento.criado_em) }}</span>
    <span class="log-etapa">{{ t('etapa.' + evento.etapa + '.titulo') if evento.etapa in etapas_conhecidas else evento.etapa }}</span>
    <span class="log-mensagem">{{ evento.mensagem }}</span>
  </li>
  {% else %}
  <li class="log-vazio">{{ t('execucao.log_vazio') }}</li>
  {% endfor %}
</ul>
```

Para que `etapas_conhecidas` exista nos dois pontos que renderizam o log, acrescente-a ao contexto em `tela_execucao` e em `fragmento_log`:

```python
    contexto_log = {"eventos": eventos, "etapas_conhecidas": set(ETAPAS)}
```

importando `ETAPAS` de `.estado_etapas` (Tarefa 1). Em `tela_execucao`, faça o mesmo acrescentando `"etapas_conhecidas": set(ETAPAS)` ao dicionário já existente.

- [ ] **Step 5: Filtro e rolagem no template da tela**

Em `execucao.html`, substitua o bloco do log (linhas 65-68):

```html
<h2>{{ t('execucao.titulo_log') }}</h2>
<div class="log-barra">
  <label for="filtro-log">{{ t('execucao.log_filtro') }}</label>
  <select id="filtro-log">
    <option value="todos">{{ t('execucao.log_filtro_todos') }}</option>
    <option value="info">{{ t('execucao.log_filtro_info') }}</option>
    <option value="aviso">{{ t('execucao.log_filtro_aviso') }}</option>
    <option value="erro">{{ t('execucao.log_filtro_erro') }}</option>
  </select>
  <label class="checkbox-inline">
    <input type="checkbox" id="seguir-log" checked>
    {{ t('execucao.log_seguir') }}
  </label>
</div>
<div id="log" class="log-caixa" hx-get="/projetos/{{ projeto.id }}/execucao/log" hx-trigger="load, every 2s" hx-swap="innerHTML">
  {% include "_log.html" %}
</div>
```

E acrescente, dentro do `<script>` já existente (antes do `})();` final):

```javascript
  var caixaLog = document.getElementById("log");
  var filtroLog = document.getElementById("filtro-log");
  var seguirLog = document.getElementById("seguir-log");

  function aplicarFiltroLog() {
    caixaLog.setAttribute("data-filtro", filtroLog.value);
  }
  function rolarLogParaOFim() {
    if (seguirLog.checked) caixaLog.scrollTop = caixaLog.scrollHeight;
  }

  filtroLog.addEventListener("change", aplicarFiltroLog);
  // O HTMX substitui o conteúdo do #log a cada 2s: sem reaplicar depois da
  // troca, o filtro valeria só até o próximo poll e a rolagem voltaria ao topo.
  document.body.addEventListener("htmx:afterSwap", function (evento) {
    if (evento.target && evento.target.id === "log") {
      aplicarFiltroLog();
      rolarLogParaOFim();
    }
  });
  aplicarFiltroLog();
```

- [ ] **Step 6: CSS do filtro e da caixa rolável**

Acrescente ao fim de `estilo.css`:

```css
.log-barra {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
  color: var(--cor-texto-fraco);
  font-size: 0.9rem;
}

.log-caixa {
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--cor-borda);
  border-radius: 6px;
}

.log-caixa[data-filtro="info"] li[data-nivel-log]:not([data-nivel-log="info"]),
.log-caixa[data-filtro="aviso"] li[data-nivel-log]:not([data-nivel-log="aviso"]),
.log-caixa[data-filtro="erro"] li[data-nivel-log]:not([data-nivel-log="erro"]) {
  display: none;
}
```

- [ ] **Step 7: Chaves de tradução**

Acrescente aos três dicionários de `i18n.py`:

```python
# pt
        "execucao.log_filtro": "Mostrar",
        "execucao.log_filtro_todos": "tudo",
        "execucao.log_filtro_info": "só informações",
        "execucao.log_filtro_aviso": "só avisos",
        "execucao.log_filtro_erro": "só erros",
        "execucao.log_seguir": "acompanhar o fim",
# en
        "execucao.log_filtro": "Show",
        "execucao.log_filtro_todos": "everything",
        "execucao.log_filtro_info": "info only",
        "execucao.log_filtro_aviso": "warnings only",
        "execucao.log_filtro_erro": "errors only",
        "execucao.log_seguir": "follow the tail",
# es
        "execucao.log_filtro": "Mostrar",
        "execucao.log_filtro_todos": "todo",
        "execucao.log_filtro_info": "solo información",
        "execucao.log_filtro_aviso": "solo avisos",
        "execucao.log_filtro_erro": "solo errores",
        "execucao.log_seguir": "seguir el final",
```

- [ ] **Step 8: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k log -v
```

Esperado: PASS nos dois.

- [ ] **Step 9: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `182 passed`.

---

### Task 6: Extensões agrupadas por família no formulário

`novo_projeto.html:78-86` percorre `sorted(categorias_validas())` e produz oito checkboxes em fila única — `docx, email, imagens, pdf, pptx, texto, todos, web_dados` — em ordem alfabética, que mistura "todos" (uma regra, não um conjunto) no meio das categorias comuns. Nada diz quais extensões cada rótulo cobre.

A correção agrupa por família, com as extensões visíveis, e separa "todos" numa faixa própria.

**Files:**
- Modify: `gclaude_indexer/tipos.py` (novo `FAMILIAS_CATEGORIAS` e `categorias_por_familia()`)
- Modify: `gclaude_indexer/web/app.py:293-299` (`tela_novo_projeto`) e o ramo de reexibição em `criar_novo_projeto`
- Modify: `gclaude_indexer/web/templates/novo_projeto.html:77-88`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces:
  - `FAMILIAS_CATEGORIAS: dict[str, tuple[str, ...]]` — `{"documentos": ("pdf", "docx", "xlsx", "pptx"), "imagens": ("imagens",), "texto_dados": ("texto", "web_dados"), "mensagens": ("email",)}`
  - `categorias_por_familia() -> list[tuple[str, list[dict]]]` — cada item: `(familia, [{"categoria": str, "extensoes": list[str]}, ...])`, ordenado como em `FAMILIAS_CATEGORIAS`. `CATEGORIA_TODOS` **não** aparece: continua fora, na faixa própria.
- Consumes: `EXTENSOES_CATEGORIAS`, `CATEGORIA_TODOS` (já existentes).

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 6: extensões agrupadas por família -----------------------------


def test_categorias_por_familia_cobre_todas_as_categorias_menos_todos():
    from gclaude_indexer.tipos import CATEGORIA_TODOS, EXTENSOES_CATEGORIAS, categorias_por_familia

    agrupadas = categorias_por_familia()
    vistas = {item["categoria"] for _familia, itens in agrupadas for item in itens}
    assert vistas == set(EXTENSOES_CATEGORIAS)
    assert CATEGORIA_TODOS not in vistas
    assert [familia for familia, _itens in agrupadas][0] == "documentos"


def test_categorias_por_familia_traz_as_extensoes_de_cada_categoria():
    from gclaude_indexer.tipos import categorias_por_familia

    por_categoria = {
        item["categoria"]: item["extensoes"]
        for _familia, itens in categorias_por_familia() for item in itens
    }
    assert por_categoria["pdf"] == [".pdf"]
    assert ".jpg" in por_categoria["imagens"]
    assert por_categoria["imagens"] == sorted(por_categoria["imagens"])


def test_formulario_agrupa_as_extensoes_e_mostra_o_que_cada_uma_cobre(cliente):
    corpo = cliente.get("/projetos/novo").text
    assert 'class="familia-extensoes"' in corpo
    assert ".pdf" in corpo
    assert ".jpeg" in corpo
    for categoria in ("pdf", "docx", "xlsx", "pptx", "imagens", "texto", "web_dados", "email", "todos"):
        assert f'value="{categoria}"' in corpo, categoria
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k familia -v
```

Esperado: FAIL com `ImportError: cannot import name 'categorias_por_familia'`.

- [ ] **Step 3: Acrescentar o agrupamento em `tipos.py`**

Ao fim de `gclaude_indexer/tipos.py`:

```python
# Agrupamento só para exibição no formulário (seção 6): a lista alfabética
# de oito checkboxes não dizia nada sobre o que cada rótulo cobre nem sobre
# o que é parecido com o quê. Não altera nenhuma regra de varredura —
# `EXTENSOES_CATEGORIAS` continua sendo a fonte da verdade.
FAMILIAS_CATEGORIAS: dict[str, tuple[str, ...]] = {
    "documentos": ("pdf", "docx", "xlsx", "pptx"),
    "imagens": ("imagens",),
    "texto_dados": ("texto", "web_dados"),
    "mensagens": ("email",),
}


def categorias_por_familia() -> list[tuple[str, list[dict]]]:
    """Categorias agrupadas para o formulário, cada uma com as extensões que
    cobre. `CATEGORIA_TODOS` fica de fora de propósito: é uma regra ("tudo,
    menos binário"), não um conjunto fixo, e o template a exibe à parte."""
    agrupadas: list[tuple[str, list[dict]]] = []
    for familia, categorias in FAMILIAS_CATEGORIAS.items():
        itens = [
            {"categoria": categoria, "extensoes": sorted(EXTENSOES_CATEGORIAS[categoria])}
            for categoria in categorias
            if categoria in EXTENSOES_CATEGORIAS
        ]
        if itens:
            agrupadas.append((familia, itens))
    return agrupadas
```

- [ ] **Step 4: Passar o agrupamento ao template**

Em `app.py`, no import de `..tipos`, acrescente `categorias_por_familia`:

```python
from ..tipos import CATEGORIA_TODOS, categorias_por_familia, categorias_validas
```

Em `tela_novo_projeto`, troque a chave `"categorias"`:

```python
@app.get("/projetos/novo", response_class=HTMLResponse)
def tela_novo_projeto(request: Request):
    return render(
        request, "novo_projeto.html",
        {
            "valores": _config_para_formulario(),
            "familias": categorias_por_familia(),
            "categoria_todos": CATEGORIA_TODOS,
            "erros": [],
        },
    )
```

Faça a mesma substituição em `criar_novo_projeto`, no ponto em que ele reexibe o formulário com erros de validação — procure por `"categorias": sorted(categorias_validas())` e troque pelas duas chaves acima. Se `categorias_validas` deixar de ser usada em `app.py`, remova-a do import.

- [ ] **Step 5: Reescrever o bloco no template**

Em `novo_projeto.html`, substitua as linhas 77-88:

```html
    <label>{{ t('novo_projeto.extensoes') }} {{ m.dica(t, 'dica.extensoes') }}</label>
    {% for familia, itens in familias %}
    <fieldset class="familia-extensoes">
      <legend>{{ t('novo_projeto.familia.' + familia) }}</legend>
      {% for item in itens %}
      <label class="checkbox-inline">
        <input type="checkbox" name="extensoes" value="{{ item.categoria }}"
               {% if item.categoria in valores.extensoes %}checked{% endif %}>
        <span class="categoria-nome">{{ t('novo_projeto.categoria.' + item.categoria) }}</span>
        <span class="categoria-extensoes">{{ item.extensoes | join(' ') }}</span>
      </label>
      {% endfor %}
    </fieldset>
    {% endfor %}
    <label class="checkbox-inline categoria-todos">
      <input type="checkbox" name="extensoes" value="{{ categoria_todos }}"
             {% if categoria_todos in valores.extensoes %}checked{% endif %}>
      <span class="categoria-nome">{{ t('novo_projeto.categoria.' + categoria_todos) }}</span>
    </label>
    <p class="ajuda">{{ t('novo_projeto.extensoes_ajuda_todos') }}</p>
```

- [ ] **Step 6: CSS**

Acrescente ao fim de `estilo.css`:

```css
.familia-extensoes {
  border: 1px solid var(--cor-borda);
  border-radius: 6px;
  padding: 8px 12px 10px;
  margin: 0 0 10px;
}

.familia-extensoes legend {
  padding: 0 6px;
  color: var(--cor-texto-fraco);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.categoria-extensoes {
  margin-left: 6px;
  color: var(--cor-texto-fraco);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
}
```

- [ ] **Step 7: Chaves de tradução**

Acrescente aos três dicionários de `i18n.py` (as chaves `novo_projeto.categoria.*` já existem — só as famílias são novas):

```python
# pt
        "novo_projeto.familia.documentos": "Documentos",
        "novo_projeto.familia.imagens": "Imagens",
        "novo_projeto.familia.texto_dados": "Texto e dados",
        "novo_projeto.familia.mensagens": "Mensagens",
# en
        "novo_projeto.familia.documentos": "Documents",
        "novo_projeto.familia.imagens": "Images",
        "novo_projeto.familia.texto_dados": "Text and data",
        "novo_projeto.familia.mensagens": "Messages",
# es
        "novo_projeto.familia.documentos": "Documentos",
        "novo_projeto.familia.imagens": "Imágenes",
        "novo_projeto.familia.texto_dados": "Texto y datos",
        "novo_projeto.familia.mensagens": "Mensajes",
```

- [ ] **Step 8: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k familia -v
```

Esperado: PASS nos três.

- [ ] **Step 9: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

O `test_formulario_novo_projeto_tem_os_padroes_da_secao_6` de `test_fase9.py` usa o helper `_checkbox_marcado`, que corta 60 caracteres depois de `value="pdf"` e procura `checked` antes do primeiro `>`. O `<input>` novo mantém `value` e `checked` no mesmo elemento, então o helper continua funcionando. Se ainda assim falhar, ajuste a janela de corte de 60 para 120 caracteres em `tests/test_fase9.py:127` — não relaxe a asserção.

Esperado: `185 passed`.

---

### Task 7: Descrições legíveis dos motores de classificação

`novo_projeto.html:113-117` monta o `<select>` de motor imprimindo o valor cru: o usuário lê `automatico`, `regras`, `local`, `claude_code`, `openrouter` — identificadores de código, sem acento, sem tradução e sem qualquer indicação do que cada um faz ou do que exige (o `claude_code` precisa de um comando rodado à mão; o `local` precisa do Ollama instalado).

**Files:**
- Modify: `gclaude_indexer/web/app.py` (contexto de `tela_novo_projeto` e da reexibição com erros)
- Modify: `gclaude_indexer/web/templates/novo_projeto.html:112-118`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces: `MOTORES_ORDENADOS: tuple[str, ...]` em `app.py` = `("automatico", "regras", "local", "claude_code", "openrouter")` — ordem de apresentação, do mais recomendado ao mais exigente. `MOTORES_CLASSIFICACAO` em `config.py` é um `set`, cuja iteração não tem ordem estável; a validação continua sendo feita por ele.
- Consumes: `t('motor.<chave>.nome')` e `t('motor.<chave>.descricao')`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 7: descrições dos motores --------------------------------------


def test_motores_ordenados_cobre_exatamente_os_motores_validos():
    from gclaude_indexer.config import MOTORES_CLASSIFICACAO
    from gclaude_indexer.web.app import MOTORES_ORDENADOS

    assert set(MOTORES_ORDENADOS) == MOTORES_CLASSIFICACAO
    assert MOTORES_ORDENADOS[0] == "automatico"


def test_formulario_mostra_nome_e_descricao_de_cada_motor(cliente):
    corpo = cliente.get("/projetos/novo").text
    assert "Automático" in corpo
    assert "Ollama" in corpo  # descrição do motor local diz do que ele depende
    assert '<option value="claude_code"' in corpo
    assert ">claude_code<" not in corpo  # o identificador cru não aparece mais
    assert 'class="motor-descricoes"' in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k motor -v
```

Esperado: FAIL com `ImportError: cannot import name 'MOTORES_ORDENADOS'`.

- [ ] **Step 3: Definir a ordem em `app.py`**

Junto de `LINHAS_DE_LOG`:

```python
# Ordem de apresentação dos motores no formulário, do mais simples de usar ao
# que exige mais do usuário. `MOTORES_CLASSIFICACAO` (config.py) é um set e
# não tem ordem estável — continua sendo a fonte da validação, nunca da
# apresentação. Um teste garante que os dois conjuntos coincidem.
MOTORES_ORDENADOS: tuple[str, ...] = ("automatico", "regras", "local", "claude_code", "openrouter")
```

Acrescente `"motores": MOTORES_ORDENADOS` ao contexto de `tela_novo_projeto` e ao da reexibição com erros em `criar_novo_projeto`, substituindo o que hoje alimenta o laço do `<select>`.

- [ ] **Step 4: Reescrever o bloco no template**

Em `novo_projeto.html`, substitua as linhas 112-118:

```html
    <label for="motor_classificacao">{{ t('novo_projeto.motor_classificacao') }} {{ m.dica(t, 'dica.motor_classificacao') }}</label>
    <select id="motor_classificacao" name="motor_classificacao">
      {% for motor in motores %}
      <option value="{{ motor }}" {% if valores.motor_classificacao == motor %}selected{% endif %}>{{ t('motor.' + motor + '.nome') }}</option>
      {% endfor %}
    </select>
    <ul class="motor-descricoes">
      {% for motor in motores %}
      <li><strong>{{ t('motor.' + motor + '.nome') }}</strong> — {{ t('motor.' + motor + '.descricao') }}</li>
      {% endfor %}
    </ul>
```

- [ ] **Step 5: CSS**

```css
.motor-descricoes {
  margin: 6px 0 0;
  padding-left: 18px;
  color: var(--cor-texto-fraco);
  font-size: 0.88rem;
  line-height: 1.5;
}
```

- [ ] **Step 6: Chaves de tradução**

```python
# pt
        "motor.automatico.nome": "Automático",
        "motor.automatico.descricao": "escolhe sozinho: usa o modelo local se o Ollama estiver respondendo, e cai nas regras se não estiver. Recomendado.",
        "motor.regras.nome": "Regras",
        "motor.regras.descricao": "só padrões de texto, sem modelo de linguagem. Instantâneo e sem dependência externa; erra mais em documentos fora do padrão.",
        "motor.local.nome": "Modelo local (Ollama)",
        "motor.local.descricao": "roda gemma4:e4b na sua máquina pelo Ollama, sem conta e sem internet. Exige o Ollama instalado; sem ele, cai nas regras com aviso.",
        "motor.claude_code.nome": "Claude Code (manual)",
        "motor.claude_code.descricao": "gera as janelas para você classificar com o Claude Code e rodar um comando à mão. Melhor qualidade, mas não termina sozinho.",
        "motor.openrouter.nome": "OpenRouter",
        "motor.openrouter.descricao": "usa um modelo remoto pelo OpenRouter. Exige chave de API e envia o texto do acervo para fora desta máquina.",
# en
        "motor.automatico.nome": "Automatic",
        "motor.automatico.descricao": "picks on its own: uses the local model when Ollama is responding, falls back to rules when it is not. Recommended.",
        "motor.regras.nome": "Rules",
        "motor.regras.descricao": "text patterns only, no language model. Instant and dependency-free; less accurate on documents that break the pattern.",
        "motor.local.nome": "Local model (Ollama)",
        "motor.local.descricao": "runs gemma4:e4b on your machine through Ollama, no account and no internet. Requires Ollama installed; without it, falls back to rules with a warning.",
        "motor.claude_code.nome": "Claude Code (manual)",
        "motor.claude_code.descricao": "prepares the windows for you to classify with Claude Code and run a command by hand. Best quality, but does not finish on its own.",
        "motor.openrouter.nome": "OpenRouter",
        "motor.openrouter.descricao": "uses a remote model through OpenRouter. Requires an API key and sends the collection's text off this machine.",
# es
        "motor.automatico.nome": "Automático",
        "motor.automatico.descricao": "elige solo: usa el modelo local si Ollama responde y recurre a las reglas si no. Recomendado.",
        "motor.regras.nome": "Reglas",
        "motor.regras.descricao": "solo patrones de texto, sin modelo de lenguaje. Instantáneo y sin dependencias; falla más en documentos fuera del patrón.",
        "motor.local.nome": "Modelo local (Ollama)",
        "motor.local.descricao": "ejecuta gemma4:e4b en tu máquina con Ollama, sin cuenta y sin internet. Requiere Ollama instalado; sin él, recurre a las reglas con aviso.",
        "motor.claude_code.nome": "Claude Code (manual)",
        "motor.claude_code.descricao": "prepara las ventanas para que las clasifiques con Claude Code y ejecutes un comando a mano. Mejor calidad, pero no termina solo.",
        "motor.openrouter.nome": "OpenRouter",
        "motor.openrouter.descricao": "usa un modelo remoto vía OpenRouter. Requiere clave de API y envía el texto del acervo fuera de esta máquina.",
```

- [ ] **Step 7: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k motor -v
```

Esperado: PASS nos dois.

- [ ] **Step 8: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `187 passed`.

---

### Task 8: Descoberta dos modelos instalados no Ollama

`novo_projeto.html:121` é um `<input type="text" disabled>` com o literal `"gemma4:e4b (fixo)"`. Por estar `disabled`, o campo nem é submetido — e `motor_local.py:38` documenta que "só uma escolha manual em `modelo_local` (form) sobrepõe isto", uma sobreposição que a interface tornou inalcançável. Quem tem outro modelo baixado não tem como escolhê-lo.

A correção consulta `GET /api/tags` do Ollama local e monta um `<select>` com o que está instalado, mantendo `gemma4:e4b` como padrão. Com o Ollama fora do ar, o campo degrada para o comportamento atual, com aviso.

**Files:**
- Create: `gclaude_indexer/web/modelos_ollama.py`
- Modify: `gclaude_indexer/web/app.py` (contexto de `tela_novo_projeto` e da reexibição com erros)
- Modify: `gclaude_indexer/web/templates/novo_projeto.html:119-123`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces: `listar_modelos_instalados(timeout_s: float = 2.0) -> list[str]` — nomes ordenados alfabeticamente, ou `[]` quando o Ollama não responde. **Nunca levanta exceção**: a tela de Novo projeto não pode quebrar porque o Ollama está parado.
- Consumes: `URL_BASE_OLLAMA` e `MODELO_LOCAL_PADRAO` de `gclaude_indexer/motor_local.py` — o host fica onde já está, e este módulo não define endereço próprio.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 8: descoberta de modelos do Ollama -----------------------------


def test_listar_modelos_devolve_nomes_ordenados(monkeypatch):
    import json
    import io
    from gclaude_indexer.web import modelos_ollama

    resposta = json.dumps({"models": [
        {"name": "qwen3:8b"}, {"name": "gemma4:e4b"}, {"name": "gemma4:26b"},
    ]}).encode("utf-8")

    class _Resposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(modelos_ollama.urllib.request, "urlopen", lambda *a, **k: _Resposta(resposta))
    assert modelos_ollama.listar_modelos_instalados() == ["gemma4:26b", "gemma4:e4b", "qwen3:8b"]


def test_listar_modelos_devolve_lista_vazia_quando_ollama_esta_fora(monkeypatch):
    import urllib.error
    from gclaude_indexer.web import modelos_ollama

    def _explode(*_args, **_kwargs):
        raise urllib.error.URLError("conexão recusada")

    monkeypatch.setattr(modelos_ollama.urllib.request, "urlopen", _explode)
    assert modelos_ollama.listar_modelos_instalados() == []


def test_formulario_oferece_os_modelos_instalados(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "listar_modelos_instalados", lambda: ["gemma4:e4b", "qwen3:8b"])
    corpo = cliente.get("/projetos/novo").text

    assert '<select id="modelo_local" name="modelo_local">' in corpo
    assert '<option value="qwen3:8b"' in corpo
    assert '<option value="gemma4:e4b" selected' in corpo
    assert "(fixo)" not in corpo


def test_formulario_avisa_quando_nao_ha_modelo_instalado(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "listar_modelos_instalados", lambda: [])
    corpo = cliente.get("/projetos/novo").text

    assert 'name="modelo_local"' in corpo
    assert "Ollama" in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k modelo -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'gclaude_indexer.web.modelos_ollama'`.

- [ ] **Step 3: Criar `gclaude_indexer/web/modelos_ollama.py`**

```python
"""Modelos instalados no Ollama desta máquina, para o formulário de projeto.

O endereço vem de `motor_local.URL_BASE_OLLAMA` — loopback fixo, nunca de
configuração externa (seção 7). Falha de conexão devolve lista vazia: a tela
de Novo projeto precisa abrir com o Ollama parado.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..motor_local import MODELO_LOCAL_PADRAO, URL_BASE_OLLAMA

__all__ = ["MODELO_LOCAL_PADRAO", "listar_modelos_instalados"]


def listar_modelos_instalados(timeout_s: float = 2.0) -> list[str]:
    """Nomes dos modelos baixados no Ollama local, em ordem alfabética.

    Devolve `[]` em qualquer falha (Ollama parado, resposta inesperada,
    tempo esgotado) — nunca levanta.
    """
    try:
        with urllib.request.urlopen(f"{URL_BASE_OLLAMA}/api/tags", timeout=timeout_s) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []

    modelos = dados.get("models") if isinstance(dados, dict) else None
    if not isinstance(modelos, list):
        return []

    nomes = {
        modelo["name"]
        for modelo in modelos
        if isinstance(modelo, dict) and isinstance(modelo.get("name"), str) and modelo["name"]
    }
    return sorted(nomes)
```

- [ ] **Step 4: Passar os modelos ao template**

Em `app.py`, acrescente ao bloco de imports relativos:

```python
from .modelos_ollama import MODELO_LOCAL_PADRAO, listar_modelos_instalados
```

Acrescente ao contexto de `tela_novo_projeto` e ao da reexibição com erros em `criar_novo_projeto`:

```python
            "modelos_locais": listar_modelos_instalados(),
            "modelo_local_padrao": MODELO_LOCAL_PADRAO,
```

> O teste monkeypatcha `app_mod.listar_modelos_instalados`, por isso a rota precisa chamar o nome importado no módulo (`listar_modelos_instalados()`), não `modelos_ollama.listar_modelos_instalados()`.

- [ ] **Step 5: Trocar o campo travado por um `<select>`**

Em `novo_projeto.html`, substitua as linhas 119-123:

```html
    <label for="modelo_local">{{ t('novo_projeto.modelo_local') }} {{ m.dica(t, 'dica.modelo_local') }}</label>
    {% if modelos_locais %}
    <select id="modelo_local" name="modelo_local">
      {% for modelo in modelos_locais %}
      <option value="{{ modelo }}" {% if (valores.modelo_local or modelo_local_padrao) == modelo %}selected{% endif %}>{{ modelo }}</option>
      {% endfor %}
    </select>
    <p class="ajuda">{{ t('novo_projeto.ajuda_modelo_local') }}</p>
    {% else %}
    <input type="text" id="modelo_local" name="modelo_local" value="{{ modelo_local_padrao }}">
    <p class="ajuda aviso-inline">{{ t('novo_projeto.modelo_local_sem_ollama', padrao=modelo_local_padrao) }}</p>
    {% endif %}
```

> Quando `valores.modelo_local` vem como `"automatico"` (o default do dataclass) e esse nome não está entre os instalados, nenhuma `<option>` fica `selected` e o navegador seleciona a primeira. Para que o padrão vença nesse caso, ajuste `_config_para_formulario` para que `modelo_local` já venha resolvido:
>
> ```python
>     base["extensoes"] = ["pdf", "docx", "imagens"]
>     if base.get("modelo_local") in ("", "automatico"):
>         base["modelo_local"] = MODELO_LOCAL_PADRAO
> ```

- [ ] **Step 6: Chaves de tradução**

```python
# pt
        "novo_projeto.modelo_local_sem_ollama": "O Ollama não está respondendo em 127.0.0.1:11434, então não dá para listar os modelos instalados. O valor acima ({padrao}) será usado se o Ollama estiver de pé na hora da classificação; senão, o sistema cai no motor de regras com aviso.",
# en
        "novo_projeto.modelo_local_sem_ollama": "Ollama is not responding on 127.0.0.1:11434, so the installed models cannot be listed. The value above ({padrao}) will be used if Ollama is up at classification time; otherwise the system falls back to the rules engine with a warning.",
# es
        "novo_projeto.modelo_local_sem_ollama": "Ollama no responde en 127.0.0.1:11434, así que no se pueden listar los modelos instalados. El valor de arriba ({padrao}) se usará si Ollama está activo al clasificar; si no, el sistema recurre al motor de reglas con aviso.",
```

- [ ] **Step 7: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k modelo -v
```

Esperado: PASS nos quatro.

- [ ] **Step 8: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Atenção: `test_fase9.py:_criar_projeto` envia `"modelo_local": "automatico"`. Como a validação em `config.py` não restringe esse campo a uma lista fechada, o POST continua válido. Se algum teste passar a falhar por causa do `<select>`, é porque ele conferia o `<input disabled>` antigo — atualize-o para conferir o `<select>`, sem afrouxar a asserção.

Esperado: `191 passed`.

---

### Task 9: Quatro temas visuais com seletor

`tema.py` conhece dois temas e `base.html:35-40` os alterna com um `<input type="hidden">` que calcula o "outro" tema — uma estrutura que só funciona com exatamente dois. O CSS, porém, já está inteiramente baseado em tokens `--cor-*` definidos em `:root` e sobrescritos em `html[data-tema="escuro"]`: cada tema novo é um bloco de variáveis, sem tocar em nenhuma regra de layout.

Os dois temas novos: **sépia** (claro, quente, para leitura longa) e **alto contraste** (escuro, para acessibilidade).

**Files:**
- Modify: `gclaude_indexer/web/tema.py`
- Modify: `gclaude_indexer/web/templates/base.html:35-40`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `gclaude_indexer/web/app.py:631-639` (`escolher_tema`)
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces: `TEMAS_DISPONIVEIS: tuple[str, ...]` = `("claro", "escuro", "sepia", "alto_contraste")`. `tema_valido()` mantém a assinatura e o fallback para `TEMA_PADRAO`.
- Consumes: `t('tema.<chave>')` para o rótulo de cada tema.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 9: quatro temas ------------------------------------------------


def test_tema_valido_aceita_os_quatro_e_recusa_desconhecido():
    from gclaude_indexer.web.tema import TEMAS_DISPONIVEIS, TEMA_PADRAO, tema_valido

    assert TEMAS_DISPONIVEIS == ("claro", "escuro", "sepia", "alto_contraste")
    for tema in TEMAS_DISPONIVEIS:
        assert tema_valido(tema) == tema
    assert tema_valido("roxo") == TEMA_PADRAO
    assert tema_valido(None) == TEMA_PADRAO


def test_cabecalho_traz_um_seletor_com_os_quatro_temas(cliente):
    corpo = cliente.get("/projetos").text
    assert 'name="tema"' in corpo
    for tema in ("claro", "escuro", "sepia", "alto_contraste"):
        assert f'<option value="{tema}"' in corpo, tema


def test_escolher_tema_grava_o_cookie_e_aplica_no_html(cliente):
    resposta = cliente.post("/preferencias/tema", data={"tema": "sepia"}, follow_redirects=False)
    assert resposta.status_code in (302, 303)
    corpo = cliente.get("/projetos").text
    assert 'data-tema="sepia"' in corpo


def test_tema_desconhecido_cai_no_padrao(cliente):
    cliente.post("/preferencias/tema", data={"tema": "roxo"}, follow_redirects=False)
    corpo = cliente.get("/projetos").text
    assert 'data-tema="claro"' in corpo


def test_css_define_os_tokens_dos_temas_novos():
    from pathlib import Path

    import gclaude_indexer.web.app as app_mod

    import re

    css = (Path(app_mod.RAIZ_WEB) / "static" / "estilo.css").read_text(encoding="utf-8")

    def tokens(bloco: str) -> set[str]:
        return set(re.findall(r"(--cor-[a-z0-9-]+)\s*:", bloco))

    def bloco_do_tema(nome: str) -> str:
        return css.split(f'html[data-tema="{nome}"] {{', 1)[1].split("}", 1)[0]

    for tema in ("sepia", "alto_contraste"):
        assert f'html[data-tema="{tema}"]' in css, tema

    # O piso é o que o tema `escuro` define, não o `:root` inteiro: o escuro
    # deixa de propósito 7 tokens herdados (--cor-log-* e --cor-cabecalho-*),
    # porque log e cabeçalho já são escuros no tema claro. Exigir paridade com
    # o `:root` reprovaria esse código, que está correto.
    minimo = tokens(bloco_do_tema("escuro"))
    assert len(minimo) >= 24
    for tema in ("sepia", "alto_contraste"):
        faltando = minimo - tokens(bloco_do_tema(tema))
        assert not faltando, f"tema {tema} não redefine: {sorted(faltando)}"
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k tema -v
```

Esperado: FAIL — `TEMAS_DISPONIVEIS` ainda é `("claro", "escuro")`.

- [ ] **Step 3: Ampliar `tema.py`**

```python
"""Tema visual (pedido do usuário), selecionável ao acessar o sistema e
persistido em cookie — sem depender de conta nem de banco.

Quatro opções: dois claros (`claro`, `sepia`) e dois escuros (`escuro`,
`alto_contraste`). Cada uma é só um conjunto de tokens `--cor-*` em
`estilo.css`; nenhuma regra de layout depende do tema escolhido.
"""

from __future__ import annotations

TEMA_PADRAO = "claro"
TEMAS_DISPONIVEIS: tuple[str, ...] = ("claro", "escuro", "sepia", "alto_contraste")
NOME_COOKIE_TEMA = "tema"


def tema_valido(tema: str | None) -> str:
    return tema if tema in TEMAS_DISPONIVEIS else TEMA_PADRAO
```

- [ ] **Step 4: Trocar o botão de alternância por um `<select>`**

Em `base.html`, substitua as linhas 35-40:

```html
    <form method="post" action="/preferencias/tema" class="form-preferencia">
      <select name="tema" onchange="this.form.submit()" aria-label="{{ t('tema.rotulo') }}">
        {% for tema in temas_disponiveis %}
        <option value="{{ tema }}" {% if tema == tema_atual %}selected{% endif %}>{{ t('tema.' + tema) }}</option>
        {% endfor %}
      </select>
    </form>
```

Em `app.py`, dentro de `render()`, acrescente junto das outras injeções de contexto:

```python
    contexto_completo.setdefault("temas_disponiveis", TEMAS_DISPONIVEIS)
```

e amplie o import de `.tema`:

```python
from .tema import NOME_COOKIE_TEMA, TEMA_PADRAO, TEMAS_DISPONIVEIS, tema_valido
```

`escolher_tema` (linha 631) **não precisa de mudança**: ele já faz `tema = tema_valido(str(form.get("tema", TEMA_PADRAO)))`, e como `tema_valido` passa a consultar a tupla de quatro, os temas novos são aceitos e um valor desconhecido continua caindo no padrão. É o que faz `test_tema_desconhecido_cai_no_padrao` passar sem tocar na rota.

- [ ] **Step 5: Acrescentar os dois temas ao CSS**

Depois do bloco `html[data-tema="escuro"]` em `estilo.css`. Os dois blocos precisam redefinir **todos** os tokens `--cor-*` de `:root` — o último teste da Tarefa 9 verifica exatamente isso; se `:root` tiver algum token além dos listados aqui, acrescente-o aos dois blocos.

```css
/* Sépia: claro e quente, para leitura longa de acervo. */
html[data-tema="sepia"] {
  --cor-texto: #3a2f24;
  --cor-texto-fraco: #6d5c4a;
  --cor-fundo: #f4ecdd;
  --cor-superficie: #fdf8ee;
  --cor-superficie-alt: #efe4d1;
  --cor-borda: #ddccb2;
  --cor-destaque: #8a5a1f;
  --cor-destaque-forte: #6d4615;
  --cor-destaque-fraca: #f0e2c9;
  --cor-destaque-texto: #fdf8ee;
  --cor-erro: #9c2b1f;
  --cor-erro-fundo: #f6e0da;
  --cor-ok: #4a6b2f;
  --cor-ok-fundo: #e6eed8;
  --cor-aviso: #8a5c00;
  --cor-aviso-fundo: #f7ead0;
  --cor-aviso-texto: #6b4a00;
  --cor-aviso-borda: #d9bd85;
  --cor-botao-hover: #eadfc8;
  --cor-grade: #e3d5bd;
  --cor-log-fundo: #2b241b;
  --cor-log-texto: #e6dcc9;
  --cor-log-hora: #9a8a72;
  --cor-log-etapa: #d8a657;
  --cor-previa-fundo: #efe4d1;
  --cor-cabecalho-fundo: #3a2f24;
  --cor-cabecalho-fundo-alt: #4a3c2d;
  --cor-cabecalho-texto: #f4ecdd;
  --cor-cpu: #4a6b2f;
  --cor-ram: #8a5a1f;
  --cor-gpu: #9c2b1f;
}

/* Alto contraste: escuro, para acessibilidade — sem tons intermediários. */
html[data-tema="alto_contraste"] {
  --cor-texto: #ffffff;
  --cor-texto-fraco: #d0d0d0;
  --cor-fundo: #000000;
  --cor-superficie: #0d0d0d;
  --cor-superficie-alt: #1a1a1a;
  --cor-borda: #ffffff;
  --cor-destaque: #ffe100;
  --cor-destaque-forte: #fff566;
  --cor-destaque-fraca: #33300a;
  --cor-destaque-texto: #000000;
  --cor-erro: #ff6b6b;
  --cor-erro-fundo: #2b0000;
  --cor-ok: #4dff88;
  --cor-ok-fundo: #002b11;
  --cor-aviso: #ffd24d;
  --cor-aviso-fundo: #2b2200;
  --cor-aviso-texto: #ffd24d;
  --cor-aviso-borda: #ffd24d;
  --cor-botao-hover: #262626;
  --cor-grade: #4d4d4d;
  --cor-log-fundo: #000000;
  --cor-log-texto: #ffffff;
  --cor-log-hora: #bdbdbd;
  --cor-log-etapa: #66d9ff;
  --cor-previa-fundo: #1a1a1a;
  --cor-cabecalho-fundo: #000000;
  --cor-cabecalho-fundo-alt: #1a1a1a;
  --cor-cabecalho-texto: #ffffff;
  --cor-cpu: #4dff88;
  --cor-ram: #ffe100;
  --cor-gpu: #ff6b6b;
}
```

- [ ] **Step 6: Chaves de tradução**

As chaves `tema.claro` e `tema.escuro` já existem, mas hoje descrevem a **ação** ("Escuro" era o rótulo do botão que ligava o escuro). Como agora são rótulos de opção, confirme que o texto nomeia o tema, não a ação, e acrescente as chaves novas:

```python
# pt
        "tema.rotulo": "tema",
        "tema.claro": "☀ Claro",
        "tema.escuro": "☾ Escuro",
        "tema.sepia": "◑ Sépia",
        "tema.alto_contraste": "◐ Alto contraste",
# en
        "tema.rotulo": "theme",
        "tema.claro": "☀ Light",
        "tema.escuro": "☾ Dark",
        "tema.sepia": "◑ Sepia",
        "tema.alto_contraste": "◐ High contrast",
# es
        "tema.rotulo": "tema",
        "tema.claro": "☀ Claro",
        "tema.escuro": "☾ Oscuro",
        "tema.sepia": "◑ Sepia",
        "tema.alto_contraste": "◐ Alto contraste",
```

- [ ] **Step 7: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k tema -v
```

Esperado: PASS nos cinco.

- [ ] **Step 8: Conferir na tela**

Suba o servidor e percorra os quatro temas na tela de Execução, que é a mais densa — tabela, barra de progresso, três gráficos em canvas e o log:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" executar_servidor.py
```

Confira em especial os gráficos de CPU/RAM/GPU: eles leem `--cor-cpu`, `--cor-ram`, `--cor-gpu`, `--cor-borda` e `--cor-texto-fraco` via `getComputedStyle` (`execucao.html:79-89`) e só releem a cada frame desenhado — a linha do gráfico assume a cor do tema novo no próximo ciclo de 500ms, sem precisar recarregar.

- [ ] **Step 9: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Se algum teste da Fase 9/10 conferir o botão de alternância antigo (procure por `botao-tema`), atualize-o para o `<select>`.

Esperado: `196 passed`.

---

### Task 10: Faixa "troca de máquina" dispensável

`base.html:43-45` exibe `t('aviso.troca_maquina')` numa faixa fixa no topo de **todas** as telas, sem botão de fechar. É um aviso operacional útil na primeira visita e ruído permanente depois — e come altura vertical justamente na tela de Execução, a mais cheia.

A dispensa fica no `localStorage`, por navegador: não requer cookie, rota nem banco, e o aviso volta se o usuário limpar os dados do site.

**Files:**
- Modify: `gclaude_indexer/web/templates/base.html:43-45`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:** nenhuma assinatura nova. Chave de `localStorage`: `"gclaude.aviso_troca_maquina_dispensado"`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 10: aviso dispensável ------------------------------------------


def test_aviso_de_troca_de_maquina_tem_botao_de_dispensar(cliente):
    corpo = cliente.get("/projetos").text
    assert 'id="aviso-troca-maquina"' in corpo
    assert 'id="fechar-aviso-troca-maquina"' in corpo
    assert "gclaude.aviso_troca_maquina_dispensado" in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k aviso -v
```

Esperado: FAIL — a faixa atual não tem `id` nem botão.

- [ ] **Step 3: Tornar a faixa dispensável**

Em `base.html`, substitua as linhas 43-45:

```html
<div class="aviso-fixo" id="aviso-troca-maquina" hidden>
  <span>{{ t('aviso.troca_maquina') }}</span>
  <button type="button" id="fechar-aviso-troca-maquina" class="aviso-fechar"
          aria-label="{{ t('aviso.dispensar') }}" title="{{ t('aviso.dispensar') }}">×</button>
</div>
<script>
(function () {
  // localStorage e não cookie: é preferência de exibição por navegador, não
  // precisa ir ao servidor a cada requisição. Começa `hidden` e só aparece
  // se não tiver sido dispensado — assim quem já dispensou nunca vê a faixa
  // piscar entre o carregamento do HTML e a execução deste script.
  var CHAVE = "gclaude.aviso_troca_maquina_dispensado";
  var faixa = document.getElementById("aviso-troca-maquina");
  var fechar = document.getElementById("fechar-aviso-troca-maquina");
  var dispensado = false;
  try { dispensado = localStorage.getItem(CHAVE) === "1"; } catch (erro) { dispensado = false; }
  if (!dispensado) faixa.hidden = false;
  fechar.addEventListener("click", function () {
    faixa.hidden = true;
    try { localStorage.setItem(CHAVE, "1"); } catch (erro) { /* modo privado: só não lembra */ }
  });
})();
</script>
```

- [ ] **Step 4: CSS do botão**

```css
.aviso-fixo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.aviso-fechar {
  flex: none;
  border: none;
  background: transparent;
  color: inherit;
  font-size: 1.1rem;
  line-height: 1;
  padding: 2px 8px;
  cursor: pointer;
  opacity: 0.7;
}

.aviso-fechar:hover {
  opacity: 1;
}
```

> Se `.aviso-fixo` já tiver um `display` definido antes neste arquivo, altere a regra existente em vez de acrescentar uma segunda — duas declarações do mesmo seletor dependendo da ordem de cascata é exatamente o tipo de fragilidade que a Tarefa 12 vem limpar.

- [ ] **Step 5: Chaves de tradução**

```python
# pt
        "aviso.dispensar": "dispensar este aviso",
# en
        "aviso.dispensar": "dismiss this notice",
# es
        "aviso.dispensar": "descartar este aviso",
```

- [ ] **Step 6: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k aviso -v
```

Esperado: PASS.

- [ ] **Step 7: Conferir no navegador**

Suba o servidor, feche a faixa, navegue entre telas e recarregue: ela não volta. Abra uma janela anônima: a faixa aparece de novo.

- [ ] **Step 8: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `197 passed`.

---

### Task 11: Limpar os arquivos intermediários da pasta de saída

A pasta de saída acumula `convertidos/` (PDFs com OCR e `.txt` por arquivo) e `blocos/` (as fatias) — de longe o que mais ocupa espaço, e descartável depois que os artefatos `.md` e o `projeto.db` estão prontos. Hoje o único jeito de recuperar esse espaço é excluir o projeto inteiro (`exclusao.py`), que apaga tudo, inclusive o resultado.

A limpeza preserva `projeto.db`, os quatro artefatos `.md`, `pecas_brutas.jsonl` e `logs/`; apaga apenas `convertidos/` e `blocos/`. As etapas são retomáveis, então o material apagado pode ser regerado rodando a conversão de novo.

**Files:**
- Create: `gclaude_indexer/limpeza.py`
- Modify: `gclaude_indexer/web/app.py` (rota nova + contexto de `tela_resultado`)
- Modify: `gclaude_indexer/web/templates/resultado.html`
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Produces:
  - `PASTAS_INTERMEDIARIAS: tuple[str, ...]` = `("convertidos", "blocos")`
  - `tamanho_intermediarios(pasta_saida: str) -> int` — bytes somados; `0` se nada existir.
  - `limpar_intermediarios(pasta_saida: str) -> int` — apaga as pastas e devolve quantos bytes foram liberados.
  - Ambas recusam caminho fora da pasta de saída, via `resolver_dentro` de `paths.py`.
- Consumes: `resolver_dentro(base, relativo)` de `gclaude_indexer/paths.py`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 11: limpeza de intermediários ----------------------------------


def test_limpar_intermediarios_apaga_so_convertidos_e_blocos(tmp_path):
    from gclaude_indexer.limpeza import limpar_intermediarios, tamanho_intermediarios

    saida = tmp_path / "saida"
    (saida / "convertidos" / "volume_1").mkdir(parents=True)
    (saida / "blocos" / "volume_1").mkdir(parents=True)
    (saida / "logs").mkdir()
    (saida / "convertidos" / "volume_1" / "peca.pdf").write_bytes(b"x" * 1000)
    (saida / "blocos" / "volume_1" / "bloco_1.txt").write_bytes(b"y" * 500)
    (saida / "logs" / "execucao.log").write_text("registro", encoding="utf-8")
    (saida / "projeto.db").write_bytes(b"banco")
    (saida / "indice.md").write_text("# Índice", encoding="utf-8")
    (saida / "pecas_brutas.jsonl").write_text("{}", encoding="utf-8")

    assert tamanho_intermediarios(str(saida)) == 1500
    assert limpar_intermediarios(str(saida)) == 1500

    assert not (saida / "convertidos").exists()
    assert not (saida / "blocos").exists()
    assert (saida / "projeto.db").exists()
    assert (saida / "indice.md").exists()
    assert (saida / "pecas_brutas.jsonl").exists()
    assert (saida / "logs" / "execucao.log").exists()
    assert tamanho_intermediarios(str(saida)) == 0


def test_limpar_intermediarios_e_idempotente_em_pasta_sem_intermediarios(tmp_path):
    from gclaude_indexer.limpeza import limpar_intermediarios, tamanho_intermediarios

    saida = tmp_path / "saida_limpa"
    saida.mkdir()
    (saida / "projeto.db").write_bytes(b"banco")

    assert tamanho_intermediarios(str(saida)) == 0
    assert limpar_intermediarios(str(saida)) == 0
    assert (saida / "projeto.db").exists()


def test_tela_de_resultado_oferece_a_limpeza(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projetos/{projeto_id}/resultado").text
    assert f"/projetos/{projeto_id}/limpar-intermediarios" in corpo


def test_rota_de_limpeza_libera_espaco_e_volta_para_o_resultado(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto

    projeto_id = _criar_projeto(cliente, tmp_path)
    saida = Path(buscar_projeto(projeto_id).pasta_saida)
    (saida / "convertidos").mkdir(parents=True, exist_ok=True)
    (saida / "convertidos" / "peca.pdf").write_bytes(b"z" * 2048)

    resposta = cliente.post(f"/projetos/{projeto_id}/limpar-intermediarios", follow_redirects=False)
    assert resposta.status_code in (302, 303)
    assert not (saida / "convertidos").exists()
    assert (saida / "projeto.db").exists()
```

Acrescente `from pathlib import Path` ao topo de `tests/test_fase12.py`.

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k intermediarios -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'gclaude_indexer.limpeza'`.

- [ ] **Step 3: Criar `gclaude_indexer/limpeza.py`**

```python
"""Limpeza dos arquivos intermediários da pasta de saída.

`convertidos/` (PDFs com OCR e texto por arquivo) e `blocos/` (as fatias)
respondem por quase todo o espaço ocupado por um projeto e são descartáveis
depois que os artefatos `.md` e o `projeto.db` estão prontos: as etapas são
retomáveis, então rodar a conversão de novo os regenera.

Nunca toca no banco, nos artefatos, no `pecas_brutas.jsonl` nem em `logs/`
— e jamais na pasta de origem. Diferente de `exclusao.py`, que apaga o
projeto inteiro, aqui o resultado do trabalho é preservado.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import resolver_dentro

PASTAS_INTERMEDIARIAS: tuple[str, ...] = ("convertidos", "blocos")


def _pastas_alvo(pasta_saida: str) -> list[Path]:
    """Resolve as pastas intermediárias dentro da pasta de saída, recusando
    qualquer escape (seção 7) — `resolver_dentro` levanta `ValueError`."""
    base = Path(pasta_saida)
    alvos = []
    for nome in PASTAS_INTERMEDIARIAS:
        caminho = resolver_dentro(base, nome)
        if caminho.is_dir():
            alvos.append(caminho)
    return alvos


def tamanho_intermediarios(pasta_saida: str) -> int:
    """Soma em bytes do que `limpar_intermediarios` apagaria agora."""
    total = 0
    for pasta in _pastas_alvo(pasta_saida):
        for caminho in pasta.rglob("*"):
            if caminho.is_file():
                total += caminho.stat().st_size
    return total


def limpar_intermediarios(pasta_saida: str) -> int:
    """Apaga `convertidos/` e `blocos/` inteiras. Devolve os bytes liberados.
    Chamar numa pasta que já não os tem devolve `0` sem erro."""
    liberado = tamanho_intermediarios(pasta_saida)
    for pasta in _pastas_alvo(pasta_saida):
        shutil.rmtree(pasta, ignore_errors=True)
    return liberado
```

- [ ] **Step 4: Rota e contexto em `app.py`**

Acrescente ao bloco de imports relativos:

```python
from ..limpeza import limpar_intermediarios, tamanho_intermediarios
```

Acrescente `"tamanho_intermediarios": tamanho_intermediarios(entrada.pasta_saida)` ao contexto de `tela_resultado`, e a rota nova logo depois dela:

```python
@app.post("/projetos/{projeto_id}/limpar-intermediarios")
def limpar_intermediarios_rota(projeto_id: int):
    """Libera o espaço de `convertidos/` e `blocos/` sem apagar o resultado.
    As etapas são retomáveis: rodar a conversão de novo regenera o que foi
    apagado aqui."""
    with _projeto_aberto(projeto_id) as (entrada, _config, _conn):
        pasta_saida = entrada.pasta_saida
    limpar_intermediarios(pasta_saida)
    return RedirectResponse(f"/projetos/{projeto_id}/resultado", status_code=303)
```

> A limpeza roda **fora** do `with`: `_projeto_aberto` mantém a conexão sqlite aberta, e no Windows não se apaga arquivo em uso. Como só `convertidos/` e `blocos/` são tocadas — e o banco não vive nelas — a ordem não é estritamente necessária, mas mantê-la evita uma armadilha caso a lista de pastas cresça.

- [ ] **Step 5: Botão na tela de Resultado**

Em `resultado.html`, logo depois do bloco `.pacote-claude` (linha 25):

```html
<div class="limpeza-caixa">
  <div>
    <strong>{{ t('resultado.limpeza_titulo') }}</strong>
    <p>{{ t('resultado.limpeza_texto') }}</p>
    <p class="ajuda">{{ t('resultado.limpeza_ocupado', mb=(tamanho_intermediarios / 1048576) | round(1)) }}</p>
  </div>
  <form method="post" action="/projetos/{{ projeto.id }}/limpar-intermediarios">
    <button type="submit" {% if tamanho_intermediarios == 0 %}disabled{% endif %}>
      {{ m.icone('lixeira') }} {{ t('resultado.limpeza_botao') }}
    </button>
  </form>
</div>
```

- [ ] **Step 6: CSS**

```css
.limpeza-caixa {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--cor-borda);
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0;
  background: var(--cor-superficie);
}

.limpeza-caixa p {
  margin: 4px 0 0;
}
```

- [ ] **Step 7: Chaves de tradução**

```python
# pt
        "resultado.limpeza_titulo": "Liberar espaço",
        "resultado.limpeza_texto": "Apaga as pastas convertidos/ e blocos/ — os PDFs com OCR e as fatias de texto. O banco, os relatórios e o log ficam intactos; se precisar delas de novo, é só rodar a conversão outra vez.",
        "resultado.limpeza_ocupado": "Ocupando agora: {mb} MB.",
        "resultado.limpeza_botao": "Apagar intermediários",
# en
        "resultado.limpeza_titulo": "Free up space",
        "resultado.limpeza_texto": "Deletes the convertidos/ and blocos/ folders — the OCR'd PDFs and the text slices. The database, reports and log stay untouched; if you need them again, just run the conversion once more.",
        "resultado.limpeza_ocupado": "Currently using: {mb} MB.",
        "resultado.limpeza_botao": "Delete intermediates",
# es
        "resultado.limpeza_titulo": "Liberar espacio",
        "resultado.limpeza_texto": "Borra las carpetas convertidos/ y blocos/ — los PDF con OCR y los trozos de texto. La base, los informes y el registro quedan intactos; si los necesitas otra vez, basta con volver a ejecutar la conversión.",
        "resultado.limpeza_ocupado": "Ocupando ahora: {mb} MB.",
        "resultado.limpeza_botao": "Borrar intermedios",
```

- [ ] **Step 8: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k intermediarios -v
```

Esperado: PASS nos quatro.

- [ ] **Step 9: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `201 passed`.

---

### Task 12: Fechar os furos de idioma restantes

Fechamento do trabalho iniciado na Tarefa 1. `resultado.html` tem quatro frases cruas em português no meio de um template que, no resto, é todo traduzido:

- linha 33: `{{ ... }} janela(s) ainda não classificada(s).`
- linhas 36-37: `Lacuna em <strong>...</strong>: faltam as folhas/páginas ...`
- linha 41: `Falhou: <code>...</code> — {{ falha.erro }}`

Esta tarefa também instala uma **rede de proteção**: um teste que percorre os três dicionários de `i18n.py` e falha se algum tiver chave que os outros não têm — o modo de falha mais provável ao acrescentar tradução, e que reintroduz silenciosamente o defeito da Tarefa 1 via fallback para o português.

**Files:**
- Modify: `gclaude_indexer/web/templates/resultado.html:31-43`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase12.py`

**Interfaces:**
- Consumes: `traduzir(idioma, chave, **variaveis)` e `_TRADUCOES` de `i18n.py`.
- Produces: nenhuma assinatura nova.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/test_fase12.py`:

```python
# --- Tarefa 12: paridade entre os três idiomas -----------------------------


def test_os_tres_idiomas_tem_exatamente_as_mesmas_chaves():
    from gclaude_indexer.web.i18n import IDIOMAS_DISPONIVEIS, _TRADUCOES

    assert set(_TRADUCOES) == set(IDIOMAS_DISPONIVEIS)
    referencia = set(_TRADUCOES["pt"])
    for idioma, tabela in _TRADUCOES.items():
        faltando = sorted(referencia - set(tabela))
        sobrando = sorted(set(tabela) - referencia)
        assert not faltando, f"{idioma} não traduz: {faltando}"
        assert not sobrando, f"{idioma} tem chave que 'pt' não tem: {sobrando}"


def test_toda_chave_com_variavel_usa_o_mesmo_conjunto_nos_tres_idiomas():
    import re
    from gclaude_indexer.web.i18n import _TRADUCOES

    def variaveis(texto: str) -> set[str]:
        return set(re.findall(r"\{(\w+)\}", texto))

    for chave, texto_pt in _TRADUCOES["pt"].items():
        esperado = variaveis(texto_pt)
        for idioma, tabela in _TRADUCOES.items():
            assert variaveis(tabela[chave]) == esperado, f"{idioma}/{chave}: variáveis não batem"


def test_tela_de_resultado_nao_tem_texto_cru_em_portugues(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.cookies.set("idioma", "en")
    corpo = cliente.get(f"/projetos/{projeto_id}/resultado").text

    assert "ainda não classificada" not in corpo
    assert "Lacuna em" not in corpo
    assert "faltam as folhas" not in corpo
    assert "Falhou:" not in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k idioma -v
```

Esperado: FAIL. Se `test_os_tres_idiomas_tem_exatamente_as_mesmas_chaves` acusar chaves faltando, é dívida real acumulada nas tarefas anteriores — corrija acrescentando as traduções ausentes antes de seguir.

- [ ] **Step 3: Traduzir o bloco de pendências**

Em `resultado.html`, substitua as linhas 31-43:

```html
<ul class="pendencias">
  {% if pendencias.janelas_pendentes > 0 %}
  <li>{{ t('resultado.pendencia_janelas', janelas=pendencias.janelas_pendentes) }}</li>
  {% endif %}
  {% for agrupador, intervalos in pendencias.lacunas.items() %}
  <li>{{ t('resultado.pendencia_lacuna', agrupador=agrupador) }}
    {% for a, b in intervalos %}{{ a }}{% if a != b %}-{{ b }}{% endif %}{% if not loop.last %}, {% endif %}{% endfor %}.
  </li>
  {% endfor %}
  {% for falha in pendencias.falhas %}
  <li>{{ t('resultado.pendencia_falha') }} <code>{{ falha.caminho_rel }}</code> — {{ falha.erro }}</li>
  {% endfor %}
</ul>
```

- [ ] **Step 4: Chaves de tradução**

```python
# pt
        "resultado.pendencia_janelas": "{janelas} janela(s) ainda não classificada(s).",
        "resultado.pendencia_lacuna": "Lacuna em {agrupador}: faltam as folhas/páginas",
        "resultado.pendencia_falha": "Falhou:",
# en
        "resultado.pendencia_janelas": "{janelas} window(s) not classified yet.",
        "resultado.pendencia_lacuna": "Gap in {agrupador}: missing sheets/pages",
        "resultado.pendencia_falha": "Failed:",
# es
        "resultado.pendencia_janelas": "{janelas} ventana(s) aún sin clasificar.",
        "resultado.pendencia_lacuna": "Hueco en {agrupador}: faltan las hojas/páginas",
        "resultado.pendencia_falha": "Falló:",
```

> O `<strong>` em volta do agrupador sai: o texto passa a ser um só, e embutir marcação HTML numa string traduzível obrigaria a marcar a chave como segura, abrindo caminho para injeção via nome de pasta. Se o destaque visual for necessário, ele volta como classe no `<li>`, não como tag dentro da tradução.

- [ ] **Step 5: Varrer o restante dos templates**

```powershell
Get-ChildItem gclaude_indexer\web\templates\*.html | Select-String -Pattern '>[^<>{}]*[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ][^<>{}]*<'
```

Cada acerto é texto em português fora do `t()`. Para cada um: crie a chave nos três idiomas e troque no template. Ignore os acertos dentro de `_icones.html` (é SVG) e valores de `value=` que sejam identificadores.

- [ ] **Step 6: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase12.py -k idioma -v
```

Esperado: PASS nos três.

- [ ] **Step 7: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `204 passed`.

- [ ] **Step 8: Conferência final nos três idiomas e nos quatro temas**

Suba o servidor e percorra as quatro telas — Projetos, Novo projeto, Execução, Resultado — trocando idioma e tema no cabeçalho. Nenhum texto em português deve sobrar com `en`/`es` selecionado, e nenhuma tela pode ficar ilegível em qualquer dos quatro temas.

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" executar_servidor.py
```

- [ ] **Step 9: Atualizar a documentação**

Acrescente a `ESPECIFICACAO.md` e a `README.md`:
- os quatro temas (a seção 6 hoje diz "claro/escuro");
- o seletor de modelo do Ollama, que substitui o campo travado;
- o botão de limpeza de intermediários na tela de Resultado;
- a regra de que `estado_etapas.py` devolve chaves e o template traduz — para que a próxima etapa acrescentada não reintroduza o defeito.

---

## Self-Review

**1. Cobertura.** Os 8 itens preservados no registro e os 4 confirmados por você mapeiam assim: sincronia do status → Tarefas 1 e 4; barras com ETA → Tarefas 2, 3 e 4; logs ao vivo → Tarefa 5; agrupamento por extensão → Tarefa 6; descrições do classificador → Tarefa 7; descoberta de modelos Ollama → Tarefa 8; 4 temas → Tarefa 9; limpeza → Tarefa 11; furos de i18n → Tarefas 1 e 12; total da varredura → Tarefa 3; progresso some ao terminar → Tarefa 2; faixa fixa → Tarefa 10. Sem lacuna.

**2. Placeholders.** Nenhum "TBD", nenhum "trate os erros adequadamente", nenhum "similar à Tarefa N". Todo passo de código traz o código.

**3. Consistência de tipos.** `status_etapas` devolve `{"chave", "situacao", "vars"}` na Tarefa 1 e é consumido com esses três nomes nas Tarefas 1 e 5. `situacao_projeto` devolve tupla e é desempacotada em `tela_projetos`. `ultima_do_projeto` (Tarefa 2) devolve `TarefaEtapa | None`, exatamente o que `calcular_progresso` já aceita. `listar_modelos_instalados` devolve `list[str]` e o template itera sobre ela. `limpar_intermediarios` e `tamanho_intermediarios` devolvem `int` em bytes, e o template converte para MB na exibição.

**4. Ordem.** A Tarefa 1 é pré-requisito das Tarefas 4, 5 e 12 (chaves `etapa.*.titulo`). As demais são independentes entre si e podem ser executadas em qualquer ordem depois dela.

**5. Ponto de atenção conhecido.** A contagem esperada de testes ao fim de cada tarefa (`174`, `176`, …, `204`) assume que nenhum teste existente é removido. Se a Tarefa 1 exigir reescrever em vez de ajustar algum teste da Fase 9, recalcule o total — o que não pode variar é o número de falhas: sempre zero.

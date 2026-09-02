# Fase 14 — Internationalization and Open-Source Preparation: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Traduzir o projeto inteiro para inglês — identificadores, docstrings, schema, chaves de tradução e testes — limpar os resíduos de desenvolvimento, e deixar o repositório pronto para publicação aberta sob GPL-3.0 e para um instalador Windows distribuível.

**Architecture:** A tradução acontece **de dentro para fora**, em camadas, com a suíte de 295 testes como rede a cada passo. Primeiro o schema do banco (sem migração: os acervos existentes eram testes), depois os módulos-folha, depois o núcleo, depois a web, e por fim os testes e a documentação. Nenhuma tarefa termina com a suíte vermelha.

**Tech Stack:** Python 3.12, FastAPI 0.115, Jinja2 3.1, HTMX, SQLite, pytest 8.3, PowerShell (instalador).

**Spec:** `ESPECIFICACAO.md` (será traduzido para `SPECIFICATION.md` na Tarefa 14).

---

## Global Constraints

- **Python 3.12**, venv em `%LOCALAPPDATA%\GClaudeIndexer\venv`. Testes: `%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe`.
- **Baseline: 295 testes passando.** Nenhuma tarefa pode terminar com regressão. A suíte é a única prova de que uma renomeação não quebrou nada.
- **Sem git.** Onde o fluxo TDD pediria commit, rode a suíte inteira.
- **Não derrube a instância do usuário na porta 8000.**
- **Renomeação é mecânica, comportamento não muda.** Se você sentir vontade de "melhorar" a lógica enquanto traduz, **não faça** — anote e siga. Misturar refatoração semântica com renomeação em massa é como se perdem defeitos.
- **Todo texto visível ao usuário final continua traduzível** pelo i18n (pt/en/es). Traduzir o código **não** significa deixar a interface só em inglês.
- **Comentários que explicam decisões custaram caro.** Traduza preservando o *porquê*, não só a frase. Um comentário que diz "isto existe porque X quebrou" tem de continuar dizendo isso.
- **O projeto é offline.** Nada de dependência nova, nada de rede em tempo de execução.

---

## Glossário de tradução — use exatamente estes termos

Consistência importa mais que elegância. Toda tarefa usa esta tabela; se precisar de um termo que não está aqui, acrescente-o e diga no relatório.

| Português | Inglês |
|---|---|
| varredura | `scan` |
| conversão | `conversion` |
| extração | `extraction` |
| janela | `window` |
| peça | `item`  *(documento individual dentro do acervo)* |
| classificação | `classification` |
| motor | `engine` |
| acervo | `collection` |
| pasta de origem / saída | `source_folder` / `output_folder` |
| caminho relativo | `relative_path` |
| agrupador | `group_key` |
| confiança | `confidence` |
| etapa | `step` |
| execução | `run` |
| evento | `event` |
| trava | `lock` |
| artefatos | `artifacts` |
| conferência | `review` |
| cronologia | `timeline` |
| índice | `index` |
| tema (visual) | `theme` |
| tema (do acervo) | `subject` |
| recursos (da máquina) | `resources` |
| paralelismo | `parallelism` |
| qualidade | `quality` |
| limpeza | `cleanup` |
| diagnóstico | `diagnostics` |
| instalação | `installation` |
| sensores | `sensors` |
| contadores | `counters` |
| descoberto / convertido / extraído / falhou / duplicado / ignorado | `discovered` / `converted` / `extracted` / `failed` / `duplicate` / `skipped` |
| alta / média / baixa | `high` / `medium` / `low` |
| pendente / feita | `pending` / `done` |

**Cuidado com `tema`**, que tem dois sentidos no projeto: `ConfigProjeto.tema` é o assunto do acervo (`subject`); o tema visual é `theme`. Traduzir os dois igual seria um defeito.

---

## File Structure

| Arquivo | Vira | Tarefa |
|---|---|---|
| `gclaude_indexer/` | `gclaude_indexer/` *(nome do pacote mantido)* | — |
| `db.py` | `db.py` — schema traduzido + migração | 3 |
| `tipos.py` | `file_types.py` | 4 |
| `paths.py` | `paths.py` | 4 |
| `subprocesso.py` | `subprocess_utils.py` | 4 |
| `eventos.py` | `events.py` | 4 |
| `config.py` | `config.py` | 5 |
| `varredura.py` | `scanning.py` | 6 |
| `conversao.py` | `conversion.py` | 6 |
| `extracao.py` | `extraction.py` | 6 |
| `janelas.py` | `windows_prep.py` | 6 |
| `classificacao.py` | `classification.py` | 7 |
| `motor_regras.py` | `engine_rules.py` | 7 |
| `motor_local.py` | `engine_local.py` | 7 |
| `motor_claude_code.py` | `engine_claude_code.py` | 7 |
| `orquestrador.py` | `orchestrator.py` | 7 |
| `hardware.py`, `recursos.py`, `sensores.py`, `contadores_windows.py` | `hardware.py`, `resources.py`, `sensors.py`, `windows_counters.py` | 8 |
| `paralelismo.py`, `qualidade.py`, `limpeza.py`, `importacao.py`, `artefatos.py`, `projeto.py`, `catalogo.py`, `trava.py`, `sincronizacao.py`, `revisao.py`, `exclusao.py`, `controle_execucao.py`, `instalador.py`, `diagnostico_instalacao.py` | `parallelism.py`, `quality.py`, `cleanup.py`, `import_items.py`, `artifacts.py`, `project.py`, `catalog.py`, `lock.py`, `sync.py`, `review.py`, `deletion.py`, `run_control.py`, `installer.py`, `install_diagnostics.py` | 8 |
| `web/app.py`, `web/i18n.py`, `web/tema.py`, `web/layout.py`, `web/estado_etapas.py`, `web/execucao_bg.py`, `web/formatacao.py`, `web/modelos_ollama.py`, `web/selecionador_pasta.py` | `web/app.py`, `web/i18n.py`, `web/theme.py`, `web/layout.py`, `web/step_state.py`, `web/background_runs.py`, `web/formatting.py`, `web/ollama_models.py`, `web/folder_picker.py` | 9 |
| `web/templates/*.html` | nomes em inglês | 9 |
| `tests/test_fase*.py` | `tests/test_phase*.py` | 10 |
| `README.md`, `ESPECIFICACAO.md` | `README.md` (inglês), `SPECIFICATION.md` | 11 |
| — | `LICENSE`, `.gitignore`, `CONTRIBUTING.md`, `CHANGELOG.md`, `ARCHITECTURE.md` | 2, 11 |

---

### Task 1: Limpeza dos resíduos

Antes de traduzir, tire o que não deve existir. Fazer isso primeiro reduz o que as tarefas seguintes têm de percorrer.

**Files:**
- Delete: `INSERT_PATH` (0 bytes, arquivo acidental), `_tmp_task7_check/` (pasta vazia, resíduo de agente), todas as pastas `__pycache__/`
- Create: `.gitignore`
- Modify: nada de código

- [ ] **Step 1: Inventariar antes de apagar**

```powershell
Get-ChildItem -Force | Select-Object Name, Length
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Select-Object FullName
```

**Não apague nada que não esteja na lista acima.** Se encontrar outro candidato a lixo, **liste no relatório e pergunte** em vez de remover por conta própria.

- [ ] **Step 2: Criar `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
venv/

# Machine-local development history (not part of the product)
.remember/
.superpowers/

# Test and tooling artifacts
.playwright-mcp/
*.log
_tmp_*/

# Windows
Thumbs.db
desktop.ini

# Project output — never commit a processed collection
convertidos/
blocos/
converted/
blocks/
*.db
pecas_brutas.jsonl
raw_items.jsonl
```

> `.remember/` e `.superpowers/` ficam **no disco** e fora do repositório: são registro de desenvolvimento, decisão do dono do projeto.

- [ ] **Step 3: Apagar os resíduos e rodar a suíte**

Esperado: **295 passed** — a limpeza não pode alterar comportamento.

---

### Task 2: Licença e arquivos de repositório

**Files:**
- Create: `LICENSE` (GPL-3.0 completa), `CONTRIBUTING.md`, `CHANGELOG.md`
- Modify: `gclaude_indexer/web/app.py` (cabeçalho de licença), `README.md` (badge/menção)

- [ ] **Step 1: `LICENSE`**

Texto **integral e literal** da GNU General Public License v3.0, como publicado pela FSF. Não resuma, não parafraseie, não gere de memória — copie a íntegra. Se não puder obter o texto oficial, **pare e diga**; uma licença adulterada é pior que nenhuma.

- [ ] **Step 2: Cabeçalho de licença nos módulos**

A GPL pede aviso em cada arquivo. Acrescente ao topo de cada `.py` de `gclaude_indexer/`:

```python
# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.
```

Isso é mecânico e some no meio do diff das tarefas seguintes — por isso vem agora.

- [ ] **Step 3: `CONTRIBUTING.md` e `CHANGELOG.md`**

`CONTRIBUTING.md` em inglês: como montar o ambiente (venv 3.12, `requirements.txt`, `instalar.ps1`), como rodar os testes, a convenção de que **todo texto de interface passa pelo i18n nos três idiomas**, e a regra de arquitetura das fases anteriores: *a lógica devolve chaves ASCII estáveis; o template traduz*.

`CHANGELOG.md` em inglês, no formato Keep a Changelog, com uma entrada por fase (12, 13, 14) resumindo o que mudou. Extraia dos planos em `docs/superpowers/plans/`, não invente.

- [ ] **Step 4: Rodar a suíte** — esperado **295 passed**.

---

### Task 3: Schema do banco em inglês

Sete tabelas (`projeto`, `arquivo`, `pagina`, `janela`, `peca`, `evento`, `execucao`) e dezenas de colunas em português.

**Sem migração.** O dono do projeto declarou que os acervos processados até aqui eram testes e podem ser perdidos. Isso remove o maior risco que esta tarefa teria: não há compatibilidade retroativa a manter, nem em schema nem em `config_json`. Projetos antigos simplesmente não abrem, e isso é aceito.

**Files:**
- Modify: `gclaude_indexer/db.py`
- Create: função de migração no mesmo módulo
- Modify: `tests/test_fase1.py` e todo teste que consulte tabela por nome

**Interfaces:**
- Produces: `migrar_schema_legado(conn) -> list[str]` — renomeia tabelas/colunas antigas, devolve o que migrou. Idempotente: rodar duas vezes não faz nada na segunda.

Mapeamento (use o glossário):

| Antes | Depois |
|---|---|
| `projeto` | `project` |
| `arquivo` | `file` |
| `pagina` | `page` |
| `janela` | `window` |
| `peca` | `item` |
| `evento` | `event` |
| `execucao` | `run` |
| `caminho_rel` | `relative_path` |
| `agrupador` | `group_key` |
| `confianca` | `confidence` |
| `criado_em` | `created_at` |
| `iniciado_em` / `terminado_em` | `started_at` / `finished_at` |
| `pasta_origem` / `pasta_saida` | `source_folder` / `output_folder` |
| `n_caracteres` | `char_count` |
| `hash_sha256` | `sha256` |

Complete a tabela lendo o schema real — estas são só as menos óbvias.

- [ ] **Step 1: Teste da migração (escreva primeiro)**

```python
def test_banco_antigo_e_migrado_para_o_schema_em_ingles(tmp_path):
    """O dono do projeto tem acervos processados com o schema antigo — eles
    precisam continuar abrindo depois da tradução."""
    import sqlite3
    from gclaude_indexer.db import conectar, inicializar_schema, migrar_schema_legado

    antigo = tmp_path / "antigo.db"
    conn = sqlite3.connect(antigo)
    conn.execute("CREATE TABLE arquivo (id INTEGER PRIMARY KEY, caminho_rel TEXT, status TEXT)")
    conn.execute("INSERT INTO arquivo (caminho_rel, status) VALUES ('vol/a.pdf','extraido')")
    conn.commit(); conn.close()

    conn = conectar(antigo)
    migrados = migrar_schema_legado(conn)
    inicializar_schema(conn)

    linhas = conn.execute("SELECT relative_path, status FROM file").fetchall()
    conn.close()

    assert ("vol/a.pdf", "extracted") == tuple(linhas[0]), "dados precisam sobreviver à migração"
    assert migrados, "a migração precisa relatar o que renomeou"


def test_migracao_e_idempotente(tmp_path):
    from gclaude_indexer.db import conectar, inicializar_schema, migrar_schema_legado

    novo = tmp_path / "novo.db"
    conn = conectar(novo)
    inicializar_schema(conn)
    assert migrar_schema_legado(conn) == [], "banco já novo não tem o que migrar"
    conn.close()
```

> Note que o teste espera **valores** migrados também (`extraido` → `extracted`), não só nomes de coluna. Os status são dados, não schema — a migração precisa convertê-los.

- [ ] **Step 2: Rodar, ver falhar, implementar**

Use `ALTER TABLE ... RENAME TO` e `ALTER TABLE ... RENAME COLUMN` (SQLite 3.25+). Para os valores de status, `UPDATE`.

- [ ] **Step 3: Chamar a migração ao carregar projeto**

`projeto.carregar_projeto` já chama `inicializar_schema` ao reabrir (Tarefa 15 da Fase 13). Chame `migrar_schema_legado` **antes** dele.

- [ ] **Step 4: Traduzir o schema novo** e atualizar todos os `SELECT`/`INSERT`/`UPDATE` do projeto. São muitos; use busca por nome de tabela para não deixar nenhum.

- [ ] **Step 5: Suíte inteira** — esperado **297 passed** (295 + 2).

- [ ] **Step 6: Verificação no acervo real do dono do projeto**

Ele tem um acervo em `H:\.shortcut-targets-by-id\...\Direito do Consumidor\IA2` com 14 arquivos, 1844 páginas e 132 janelas, schema antigo. **Faça uma cópia** para pasta temporária e abra com o código novo, confirmando que a migração preserva as contagens. **Não toque no original.** Reporte as contagens antes e depois.

---

### Task 4: Módulos-folha

Os quatro módulos com menos dependências, mas muito importados: traduzi-los primeiro estabelece o vocabulário.

**Files:** `tipos.py` → `file_types.py`; `paths.py`; `subprocesso.py` → `subprocess_utils.py`; `eventos.py` → `events.py`

- [ ] **Step 1: Renomear arquivos e conteúdo**

Identificadores, docstrings, comentários. Exemplos:
`EXTENSOES_CATEGORIAS` → `EXTENSION_CATEGORIES`; `categorias_validas()` → `valid_categories()`; `extensao_permitida()` → `is_extension_allowed()`; `registrar_evento()` → `record_event()`; `listar_eventos()` → `list_events()`; `executar_oculto()` → `run_hidden()`; `resolver_dentro()` → `resolve_within()`; `pasta_local_maquina()` → `machine_local_folder()`.

- [ ] **Step 2: Atualizar todos os importadores** — `config` (16), `eventos` (13), `paths` (8), `subprocesso` (6), `tipos` (5). Use busca global; não confie em memória.

- [ ] **Step 3: Suíte** — **297 passed**, sem novos testes. Se cair, alguma referência ficou para trás.

---

### Task 5: `config.py` — o mais importado

Importado por 16 módulos. Sozinho numa tarefa porque um erro aqui derruba tudo.

- [ ] **Step 1: Traduzir** `ConfigProjeto` → `ProjectConfig`, e os campos: `nome`→`name`, `tema`→**`subject`** (é o assunto do acervo, não o tema visual), `pasta_origem`→`source_folder`, `pasta_saida`→`output_folder`, `tipo_acervo`→`collection_type`, `agrupador_modo`→`group_mode`, `extensoes`→`extensions`, `paginas_por_bloco`→`pages_per_block`, `paginas_por_janela`→`pages_per_window`, `sobreposicao`→`overlap`, `caracteres_por_pagina`→`chars_per_page`, `idioma_ocr`→`ocr_language`, `motor_classificacao`→`classification_engine`, `modelo_local`→`local_model`, `modo_processamento`→`processing_mode`, `revisar_confianca_baixa`→`review_low_confidence`, `papel_instrucoes`→`role_instructions`, `regras_extras`→`extra_rules`, `paralelismo`→`parallelism`.

- [ ] **Step 2: Compatibilidade com `config_json` gravado**

`config_para_json` grava `asdict(config)` no banco. Projetos existentes têm as chaves **em português**. `carregar_config` precisa aceitar as duas grafias, mapeando as antigas. Escreva teste com um `config_json` antigo.

- [ ] **Step 3: Suíte** — **298 passed** (+1 do teste de compatibilidade).

---

### Task 6: Pipeline — scan, conversion, extraction, windows

**Files:** `varredura.py`→`scanning.py`, `conversao.py`→`conversion.py`, `extracao.py`→`extraction.py`, `janelas.py`→`windows_prep.py`

Estes quatro têm o paralelismo da Fase 13. **Traduza sem alterar a lógica de `ProcessPoolExecutor`** — nem a ordem das operações, nem o tratamento de `BrokenProcessPool`, nem o commit por arquivo. Cada um desses detalhes custou uma correção.

- [ ] **Step 1: Traduzir os quatro**, atualizando importadores.
- [ ] **Step 2: Suíte** — **298 passed**.
- [ ] **Step 3: Verificação funcional** — rode a conversão paralela num acervo de teste e confirme que o ganho continua (~5×). Renomear não pode custar desempenho; se custar, algo foi alterado além do nome.

---

### Task 7: Motores de classificação

**Files:** `classificacao.py`→`classification.py`, `motor_regras.py`→`engine_rules.py`, `motor_local.py`→`engine_local.py`, `motor_claude_code.py`→`engine_claude_code.py`, `orquestrador.py`→`orchestrator.py`

**Cuidados:**
- O `_PROMPT` de `motor_local.py` é **texto enviado ao modelo, em português**, e o acervo do usuário é em português. **Não traduza o prompt** — traduzir mudaria o comportamento da classificação. Traduza só o código em volta, e deixe um comentário explicando por que o prompt fica em português.
- Os valores de `MOTORES_VALIDOS` (`regras`/`local`/`claude_code`) são gravados em `item.engine` — traduzi-los exige migração de dados. **Traduza** (`rules`/`local`/`claude_code`) e acrescente a conversão à migração da Tarefa 3.
- A correção do canal `thinking` (Fase 13) e a normalização de referências precisam sobreviver intactas.

- [ ] **Step 1: Traduzir.** **Step 2: Suíte** — 298 passed. **Step 3:** rode uma classificação real com `gemma4:e4b` e confirme que ainda produz peças.

---

### Task 8: Infraestrutura e telemetria

**Files:** os 18 módulos restantes de `gclaude_indexer/` (ver File Structure).

Muitos arquivos, cada um pequeno. **Traduza em blocos de 4-5 e rode a suíte entre os blocos** — assim, se algo quebrar, você sabe onde.

Cuidado especial com `sensores.py` e `contadores_windows.py`: os comandos PowerShell embutidos referenciam contadores do Windows **em português** (`Informações do Processador`). Esses literais **não** podem ser traduzidos — são nomes do sistema operacional, não do nosso código.

- [ ] **Step 1-4: Traduzir por blocos.** **Step 5: Suíte** — 298 passed.

---

### Task 9: Camada web

**Files:** os 9 módulos de `web/`, os 16 templates, e as **278 chaves de i18n × 3 idiomas**.

O maior volume da fase. As chaves são a parte delicada:

- As chaves em si (`novo_projeto.titulo`) viram inglês (`new_project.title`).
- Os **valores** em `pt` continuam em português, em `en` em inglês, em `es` em espanhol — a interface segue trilíngue. **Traduzir chave não é traduzir conteúdo.**
- O teste de paridade da Fase 12 (`test_os_tres_idiomas_tem_exatamente_as_mesmas_chaves`) é a rede: se você renomear uma chave num idioma só, ele falha.

Nomes de template: `novo_projeto.html`→`new_project.html`, `execucao.html`→`run.html`, `resultado.html`→`result.html`, `projetos.html`→`projects.html`, `_etapas.html`→`_steps.html`, `_progresso.html`→`_progress.html`, `_log.html`→`_log.html`, `_icones.html`→`_icons.html`, `_macros.html`→`_macros.html`, `_campo_pasta.html`→`_folder_field.html`, `sobre.html`→`about.html`, `excluir_projeto.html`→`delete_project.html`, e os três de trava/sincronização conforme o glossário.

**As variáveis de contexto dos templates** (`{{ projeto.nome }}`) mudam junto com o Python. Renomeie os dois lados no mesmo passo, ou a tela quebra em runtime sem o teste pegar.

- [ ] **Step 1: Módulos web.** **Step 2: Chaves i18n.** **Step 3: Templates.** **Step 4: Suíte** — 298 passed.
- [ ] **Step 5: Verificação no navegador — obrigatória.** Suba o servidor (porta livre, **não a 8000**) e percorra as 4 telas nos 3 idiomas e nos 4 layouts. Renomeação de template ou de variável de contexto quebra em runtime, e o teste de HTML não pega tudo. Reporte o que viu.

---

### Task 13: Testes

**Files:** `tests/test_fase1.py` … `test_fase13.py` → `test_phase1.py` … `test_phase13.py`, mais `conftest.py`.

- [ ] **Step 1: Renomear arquivos e traduzir** nomes de teste, fixtures, helpers e docstrings. Os docstrings de teste explicam **por que** o teste existe — vários citam defeitos reais. Preserve o conteúdo.
- [ ] **Step 2: Suíte** — 298 passed, mesmos testes, nomes novos.

---

### Task 14: Documentação em três idiomas

**Files:**
- `README.md` — reescrito em inglês
- `ESPECIFICACAO.md` → `SPECIFICATION.md`, traduzido
- Create: `ARCHITECTURE.md`
- Modify: `docs/superpowers/plans/*` — **não traduzir** (registro histórico)

- [ ] **Step 1: `README.md`** — o que o sistema faz, para quem, requisitos (Windows, Python 3.12, Tesseract, Ghostscript, Ollama opcional), instalação, uso, os quatro temas e layouts, os motores de classificação, e as limitações conhecidas. **Honesto sobre o que não faz:** a pontuação de qualidade mede autoconfiança e preenchimento, não acerto; temperatura de CPU exige administrador; OCR não usa GPU.

- [ ] **Step 2: `SPECIFICATION.md`** — tradução da especificação. É longa (42 KB); traduza em blocos, verificando que nenhuma seção some.

- [ ] **Step 3: `ARCHITECTURE.md`** — novo, em inglês: o pipeline de 7 etapas, o modelo de dados, a separação lógica/apresentação (chaves estáveis + template traduz), o paralelismo, a camada de telemetria, e as decisões que não são óbvias (por que Vulkan e não ROCm; por que o prompt fica em português; por que a tabela `item` é recriada a cada importação).

- [ ] **Step 4: Suíte** — 298 passed.

---

### Task 15: Preparação para distribuição

Deixa o instalador pronto para a segunda tarefa futura (pacote Windows) sem construí-lo ainda.

- [ ] **Step 1: `instalar.ps1` → `install.ps1`**, com mensagens em inglês. **Mantenha a lógica intacta** — detecção de GPU, `-AutoInstalar` (→ `-AutoInstall`), idempotência.
- [ ] **Step 2: `Indexador.bat`/`.vbs` → `Indexer.bat`/`.vbs`**, ajustando o atalho.
- [ ] **Step 3: Documentar o caminho do instalador** em `CONTRIBUTING.md`: o que um pacote MSI/Inno Setup precisaria embutir (Python 3.12, o venv, Tesseract, Ghostscript, as DLLs de sensores) e o que fica como download opcional (Ollama e modelos, por serem grandes).
- [ ] **Step 4: Suíte final** — 298 passed. **Step 5:** rodar `install.ps1` nesta máquina e confirmar idempotência.

---

## Self-Review

**1. Cobertura.** Limpeza (T1), licença e arquivos de repositório (T2), tradução completa — schema com migração (T3), folhas (T4), config (T5), pipeline (T6), motores (T7), infraestrutura (T8), web (T9), testes (T10) —, documentação em inglês (T11) e preparação de distribuição (T12).

**2. O risco maior é a Tarefa 3.** Renomear schema com acervos processados existindo. Mitigado por migração idempotente, teste de dados sobreviventes, e verificação numa **cópia** do acervo real.

**3. O que deliberadamente não é traduzido:** o `_PROMPT` do motor local (mudaria a classificação de acervos em português), os nomes de contadores do Windows (são do SO), e os planos em `docs/superpowers/` (registro histórico).

**4. Ordem.** T1→T2 (limpeza e base) · T3 (schema, antes de tudo que o consome) · T4→T5→T6→T7→T8 (de dentro para fora) · T9 (web) · T10 (testes) · T11→T12 (documentação e distribuição).

**5. A suíte é a única rede.** 295 testes hoje, 298 ao fim. Toda tarefa termina rodando tudo. Uma renomeação que passe nos testes e quebre em runtime só é pega pela verificação no navegador da T9 — por isso ela é obrigatória.

---

### Task 10: Idioma do Windows como padrão

Hoje o idioma vem só de um cookie, e o padrão é `pt`. Quem abrir o sistema numa máquina em inglês ou espanhol vê tudo em português até trocar à mão. O dono do projeto pediu que a interface, os logs e os relatórios sigam o idioma do Windows.

**Files:**
- Create: `gclaude_indexer/locale_detect.py`
- Modify: `gclaude_indexer/web/i18n.py`, `gclaude_indexer/web/app.py`
- Modify: `tests/test_phase14.py`

**Interfaces:**
- Produces: `system_language() -> str` — devolve `"pt-BR"`, `"en"` ou `"es"`, caindo em `"en"` quando o idioma do sistema não é nenhum dos três. **Nunca levanta.**
- Códigos de idioma passam de `pt`/`en`/`es` para `pt-BR`/`en`/`es`. O dono do projeto usa **português do Brasil**, não de Portugal, e a distinção precisa estar explícita.

- [ ] **Step 1: Teste primeiro**

```python
def test_system_language_falls_back_to_english(monkeypatch):
    """An unsupported OS language must not leave the user in Portuguese."""
    from gclaude_indexer import locale_detect

    monkeypatch.setattr(locale_detect, "_raw_system_locale", lambda: "de-DE")
    assert locale_detect.system_language() == "en"


def test_system_language_maps_brazilian_portuguese(monkeypatch):
    from gclaude_indexer import locale_detect

    for raw in ("pt-BR", "pt_BR", "Portuguese_Brazil.1252"):
        monkeypatch.setattr(locale_detect, "_raw_system_locale", lambda r=raw: r)
        assert locale_detect.system_language() == "pt-BR"


def test_system_language_never_raises(monkeypatch):
    from gclaude_indexer import locale_detect

    def _boom():
        raise OSError("no locale")

    monkeypatch.setattr(locale_detect, "_raw_system_locale", _boom)
    assert locale_detect.system_language() == "en"


def test_interface_uses_system_language_when_no_cookie(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "system_language", lambda: "es")
    cliente.cookies.clear()
    body = cliente.get("/projects").text
    assert 'lang="es"' in body
```

- [ ] **Step 2: Implementar**

Use `locale.getlocale()` e, no Windows, `ctypes.windll.kernel32.GetUserDefaultUILanguage()` como fonte primária (mais confiável que a variável de ambiente). Normalize: qualquer variante de português brasileiro vira `pt-BR`; `pt-PT` cai em `pt-BR` com comentário explicando que só há uma variante de português no projeto; espanhol de qualquer região vira `es`; o resto vira `en`.

- [ ] **Step 3: O cookie continua vencendo**

Detecção é **padrão**, não imposição. Quem escolheu um idioma no seletor mantém a escolha. A ordem é: cookie → idioma do sistema → `en`.

- [ ] **Step 4: Renomear `pt` para `pt-BR`** nas chaves de `_TRADUCOES`, no cookie e no seletor. O teste de paridade dos três idiomas precisa continuar passando.

- [ ] **Step 5: Suíte** — esperado **302 passed**.

---

### Task 11: Arquivos de saída no idioma escolhido

Os quatro `.md` gerados (`index.md`, `timeline.md`, `review.md`, `project_instructions.md`) têm 16 linhas de texto fixo em português: `# Índice`, `## Peças`, `| Intervalo | Tipo | Data | Autor | Confiança |`. Quem usa o sistema em inglês recebe relatório em português.

**Files:**
- Modify: `gclaude_indexer/artifacts.py`
- Modify: `gclaude_indexer/web/i18n.py` (chaves novas nos três idiomas)
- Modify: `tests/test_phase14.py`

- [ ] **Step 1: Teste primeiro**

```python
def test_generated_index_follows_the_selected_language(tmp_path):
    """A collection processed by an English-speaking user must not get a
    Portuguese report."""
    from gclaude_indexer.artifacts import generate_index

    # ... monte um projeto mínimo com uma peça ...
    path = generate_index(conn, config, language="en")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Index")
    assert "Índice" not in text
```

- [ ] **Step 2: Passar o idioma até os artefatos**

`generate_*` recebe `language`. Quem chama é a rota de importação, que já conhece o idioma da requisição. **Não** invente um idioma dentro do módulo de artefatos: ele recebe, não decide.

- [ ] **Step 3: Chaves novas**

Cabeçalhos, colunas de tabela e rótulos, nos três idiomas. Prefixo `artifact.` para separar do resto.

- [ ] **Step 4: Cuidado com o conteúdo x rótulo**

Os **dados** (tipo da peça, autor, resumo) vêm do acervo e ficam como estão. Só os **rótulos** traduzem. Traduzir "OFÍCIO" para "LETTER" seria falsificar o documento.

- [ ] **Step 5: Suíte** — esperado **304 passed**.

---

### Task 12: Mensagens de log traduzíveis

A mais invasiva da fase. Hoje as mensagens são frases prontas em português, montadas dentro da lógica:

```python
registrar_evento(conn, "varredura", "info", f"varredura concluída: {n} novo(s), ...")
```

O dono do projeto pediu logs no idioma do sistema. Isso exige separar mensagem de dados, do mesmo jeito que a Fase 12 fez com o status das etapas.

**Files:**
- Modify: `gclaude_indexer/events.py` (assinatura), todos os módulos que registram evento (~13)
- Modify: `gclaude_indexer/web/i18n.py`, `web/templates/_log.html`
- Modify: `tests/test_phase14.py`

**Interfaces:**
- `record_event(conn, step, level, key, **params)` — grava **chave e parâmetros**, não a frase. A tradução acontece na exibição.
- A coluna `message` vira `message_key` mais `message_params` (JSON).

- [ ] **Step 1: Teste primeiro**

```python
def test_event_stores_key_and_params_not_a_sentence(tmp_path):
    """Storing a finished sentence freezes the log in one language."""
    from gclaude_indexer.events import record_event, list_events

    record_event(conn, "scan", "info", "scan.finished", new=3, updated=0)
    event = list_events(conn)[-1]
    assert event["message_key"] == "scan.finished"
    assert event["message_params"]["new"] == 3


def test_log_renders_in_the_selected_language(cliente, tmp_path):
    # roda uma varredura, pede o log em en e em pt-BR, compara
    ...
```

- [ ] **Step 2: Converter os pontos de registro**

São dezenas. **Faça módulo a módulo, rodando a suíte entre eles.** Cada mensagem vira uma chave `<etapa>.<evento>` com parâmetros nomeados.

- [ ] **Step 3: Compatibilidade não é necessária**

O dono do projeto autorizou perder os processamentos existentes. Não escreva camada de compatibilidade para logs antigos.

- [ ] **Step 4: O que NÃO traduzir**

Mensagens de exceção de biblioteca externa (`ocrmypdf falhou: ...`) entram como parâmetro, em inglês, sem tradução. Traduzir texto de erro de terceiro é inventar.

- [ ] **Step 5: Suíte** — esperado **306 passed**.

---

### Task 16: Endurecimento de segurança

O projeto está limpo (auditoria: zero SQL por interpolação de valor, zero `shell=True`, zero `eval`/`exec`, zero segredos). Estas são melhorias para um repositório que vai ficar público.

**Files:**
- Modify: `gclaude_indexer/quality.py`
- Create: `.github/workflows/tests.yml`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Allowlist de colunas**

`quality.py` interpola nome de coluna em duas queries (`_count_nulls`). Hoje os valores são literais do código, então não há injeção. Mas basta alguém passar entrada de usuário para virar uma. Valide contra um conjunto fixo:

```python
_NULLABLE_COLUMNS = frozenset({"item_type", "date", "summary"})

def _count_nulls(column: str) -> int:
    if column not in _NULLABLE_COLUMNS:
        raise ValueError(f"column not allowed in query: {column!r}")
```

Teste que uma coluna fora da lista levanta.

- [ ] **Step 2: `pip-audit` nas dependências**

Rode `pip-audit` sobre `requirements.txt` e **relate o resultado**. Se houver vulnerabilidade conhecida, liste e diga qual versão corrige. **Não atualize dependência por conta própria** — subir versão sem testar é como se quebra um sistema que funciona.

- [ ] **Step 3: CI no GitHub**

`.github/workflows/tests.yml` rodando a suíte em `windows-latest`, Python 3.12. O projeto é Windows-only (PowerShell, WMI, registro), então Linux não faz sentido. Documente isso no arquivo.

- [ ] **Step 4: Suíte** — esperado **307 passed**.

---

### Task 17: Verificação final ponta a ponta

Nenhum teste prova que o sistema funciona depois de 16 tarefas de renomeação. Esta tarefa prova.

- [ ] **Step 1: Suíte completa** — todos os testes, duas vezes, sem flakiness.

- [ ] **Step 2: Pipeline real**

Crie um acervo de teste com ao menos 5 PDFs (alguns exigindo OCR), rode as sete etapas até a importação, e confirme: arquivos varridos, páginas extraídas, janelas preparadas, peças classificadas, os quatro `.md` gerados com conteúdo.

**Use `gemma4:e4b`** (o `qwen3.5:9b` tem defeito conhecido, corrigido mas não revalidado em acervo grande).

- [ ] **Step 3: Interface completa**

Servidor em porta livre (**nunca a 8000**). Percorra as quatro telas em **três idiomas × quatro layouts × quatro temas**. Não são 48 combinações exaustivas: cubra cada idioma uma vez, cada layout uma vez, cada tema uma vez, e a tela de Execução em todas as combinações de layout e tema.

Procure: texto não traduzido, chave crua vazando (`scan.finished` aparecendo na tela em vez da frase), tabela estourando, gráfico cortado.

- [ ] **Step 4: Instalador**

Rode `install.ps1` e confirme idempotência: nada reinstalado, nenhuma pergunta, tudo OK.

- [ ] **Step 5: Scanner de segurança**

Rode o `revisar_codigo.py` da skill sobre `gclaude_indexer/` e `tests/`. O achado HIGH conhecido em `windows_counters.py` é falso positivo (PowerShell lido como SQL) — confirme que continua sendo o único.

- [ ] **Step 6: Limpeza**

Apague o acervo de teste, encerre o servidor, e confirme que o projeto não tem `.png`, `.log`, `__pycache__` nem pasta temporária.

- [ ] **Step 7: Relatório final**

Liste: total de testes, o que o pipeline produziu, o que foi verificado na interface, e **qualquer coisa que não pôde ser verificada e por quê**.

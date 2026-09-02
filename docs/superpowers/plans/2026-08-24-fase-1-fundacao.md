# Fase 1 — Fundação (estrutura, banco, config, eventos) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a fundação do GClaude Indexer: estrutura de pastas do
código, banco SQLite com o esquema completo da seção 4, carregamento e
validação de configuração de projeto, e registro de eventos — nada além
disso (fases 2+ ficam de fora).

**Architecture:** Pacote `gclaude_indexer/` com módulos pequenos e
independentes: `paths.py` (resolução de caminhos relativos à raiz do app,
sem caminho absoluto gravado), `db.py` (conexão SQLite com os pragmas da
seção 11.3 e criação do esquema da seção 4), `config.py` (dataclass de
configuração de projeto com defaults da seção 6 e validação), `eventos.py`
(registro/listagem na tabela `evento`), `projeto.py` (orquestra: cria pasta
de saída, banco, grava linha `projeto`). Teste único de ponta a ponta em
`tests/test_fase1.py`.

**Tech Stack:** Python 3.11+, `sqlite3` da biblioteca padrão, `pytest`.

**Spec:** `ESPECIFICACAO.md` (seções 3, 4,
6, 7, 9 fase 1, 11).

## Global Constraints

- Nenhum caminho absoluto gravado em código ou banco; raiz localizada pela
  posição do próprio arquivo em execução (seção 11.5).
- Nenhum ambiente virtual, cache ou temporário dentro da pasta sincronizada
  pelo Drive (seção 11.1, 11.2).
- Banco sempre aberto com `PRAGMA journal_mode=DELETE` e
  `PRAGMA synchronous=FULL`; nunca WAL (seção 11.3).
- Nenhuma escrita fora das pastas configuradas pelo usuário (seção 2, 7).
- SQL só com parâmetros vinculados, nunca concatenação (seção 7).
- `requirements.txt` com versões fixas, sem dependência que exija
  compilador (seção 3).
- Implementar apenas a Fase 1 (seção 9); nenhuma etapa de processamento
  (varredura, OCR, classificação etc.) entra aqui.

---

## Task 1: Resolução de caminhos e estrutura de pastas

**Files:**
- Create: `gclaude_indexer/__init__.py`
- Create: `gclaude_indexer/paths.py`
- Test: `tests/test_fase1.py` (função `test_raiz_projeto_sem_caminho_absoluto`)

**Interfaces:**
- Produces: `raiz_app() -> Path`, `resolver_dentro(base: Path, relativo: str) -> Path` (levanta `ValueError` se o resultado escapar de `base`, inclusive via `..`).

- [ ] Implementar `raiz_app()` usando `Path(__file__).resolve().parent.parent`.
- [ ] Implementar `resolver_dentro(base, relativo)`: resolve `base / relativo`, confirma com `os.path.commonpath` que o resultado está dentro de `base.resolve()`, senão `ValueError`.
- [ ] Escrever teste cobrindo caminho normal e tentativa de escape com `..`.
- [ ] Rodar teste, confirmar passa.

## Task 2: Banco SQLite — schema da seção 4

**Files:**
- Create: `gclaude_indexer/db.py`

**Interfaces:**
- Consumes: nada de tasks anteriores além de `pathlib.Path`.
- Produces: `conectar(caminho_db: Path) -> sqlite3.Connection`, `inicializar_schema(conn: sqlite3.Connection) -> None`.

- [ ] `conectar`: abre conexão, aplica `PRAGMA journal_mode=DELETE`, `PRAGMA synchronous=FULL`, `PRAGMA foreign_keys=ON`, `row_factory = sqlite3.Row`.
- [ ] `inicializar_schema`: `CREATE TABLE IF NOT EXISTS` para `projeto`, `arquivo`, `pagina`, `janela`, `peca`, `evento`, exatamente como a seção 4, mais os três índices (`arquivo(status)`, `pagina(arquivo_id)`, `peca(agrupador, ordem_inicial)`).
- [ ] Teste: conectar em banco temporário, inicializar schema duas vezes seguidas (idempotente), inspecionar `sqlite_master` e confirmar as 6 tabelas e 3 índices.

## Task 3: Configuração de projeto — carregamento e validação

**Files:**
- Create: `gclaude_indexer/config.py`

**Interfaces:**
- Produces: dataclass `ConfigProjeto` (campos da seção 6: `nome`, `tema`, `pasta_origem`, `pasta_saida`, `tipo_acervo`, `agrupador_modo`, `agrupador_padrao`, `extensoes`, `paginas_por_bloco`, `paginas_por_janela`, `sobreposicao`, `caracteres_por_pagina`, `idioma_ocr`, `motor_classificacao`, `modelo_local`, `revisar_confianca_baixa`, `papel_instrucoes`, `regras_extras`), `ErroConfig(Exception)`, `carregar_config(dados: dict) -> ConfigProjeto`, `config_para_json(config: ConfigProjeto) -> str`.
- Consumes: nada.

- [ ] Definir defaults exatamente como a tabela da seção 6 (`tipo_acervo="processo"`, `agrupador_modo="subpasta"`, `extensoes=["pdf","docx","imagens"]`, `paginas_por_bloco=80`, `paginas_por_janela=16`, `sobreposicao=2`, `caracteres_por_pagina=2000`, `idioma_ocr="por"`, `motor_classificacao="automatico"`, `revisar_confianca_baixa=False`).
- [ ] `carregar_config`: mescla `dados` com defaults, constrói `ConfigProjeto`.
- [ ] Validação (levanta `ErroConfig` com lista de mensagens): `nome` e `pasta_origem` obrigatórios e não vazios; `pasta_origem` existe e é diretório; `tipo_acervo` em `{"processo","biblioteca"}`; `agrupador_modo` em `{"subpasta","padrao_nome","tudo_junto"}`; `extensoes` não vazio; `paginas_por_bloco>0`; `paginas_por_janela>0`; `0<=sobreposicao<paginas_por_janela`; `caracteres_por_pagina>0`; `motor_classificacao` em `{"automatico","regras","local","claude_code","openrouter"}`.
- [ ] `config_para_json`: serializa via `dataclasses.asdict` + `json.dumps`.
- [ ] Testes: config válida mínima carrega com defaults corretos; pasta_origem inexistente levanta `ErroConfig`; sobreposicao >= paginas_por_janela levanta `ErroConfig`.

## Task 4: Registro de eventos

**Files:**
- Create: `gclaude_indexer/eventos.py`

**Interfaces:**
- Consumes: `sqlite3.Connection` (Task 2).
- Produces: `registrar_evento(conn, etapa: str, nivel: str, mensagem: str) -> int`, `listar_eventos(conn, etapa: str | None = None) -> list[dict]`.

- [ ] `registrar_evento`: valida `nivel` em `{"info","aviso","erro"}` (senão `ValueError`), insere com `criado_em = datetime.now().isoformat(timespec="seconds")`, retorna `id` inserido. Sem conteúdo de documento no log, só o texto passado (seção 7).
- [ ] `listar_eventos`: `SELECT` com parâmetro vinculado quando `etapa` informado, ordenado por `id`; retorna lista de dicts.
- [ ] Teste: registrar 3 eventos, listar todos, listar filtrando por `etapa`, confirmar ordem e conteúdo; nível inválido levanta `ValueError`.

## Task 5: Criação de projeto — orquestração

**Files:**
- Create: `gclaude_indexer/projeto.py`

**Interfaces:**
- Consumes: `ConfigProjeto`, `config_para_json` (Task 3); `conectar`, `inicializar_schema` (Task 2); `resolver_dentro` opcionalmente (Task 1).
- Produces: `criar_projeto(config: ConfigProjeto) -> tuple[sqlite3.Connection, int]` — cria `pasta_saida` se não existir, abre/inicializa `projeto.db` dentro dela, insere linha em `projeto`, retorna `(conn, projeto_id)`.

- [ ] Implementar `criar_projeto`: `Path(config.pasta_saida).mkdir(parents=True, exist_ok=True)`; `conectar(pasta_saida/"projeto.db")`; `inicializar_schema`; `INSERT INTO projeto (...) VALUES (...)` com `criado_em` ISO; commit; retorna.
- [ ] Teste coberto pelo teste de ponta a ponta da Task 6.

## Task 6: `requirements.txt`, `README.md` e teste de ponta a ponta

**Files:**
- Create: `requirements.txt`
- Create: `README.md`
- Modify: `tests/test_fase1.py` (adicionar teste de ponta a ponta)
- Modify: `ESPECIFICACAO.md` (marcar Fase 1 concluída na seção 12)

- [ ] `requirements.txt` com as bibliotecas da seção 3 (mesmo as que só entram em fases futuras, pois é artefato do projeto inteiro) em versões fixas, mais `pytest`, sem nenhuma que exija compilador.
- [ ] `README.md` curto: o que é, requisito (Python 3.11+), como criar venv **fora** da pasta do Drive (`%LOCALAPPDATA%\GClaudeIndexer\venv`), `pip install -r requirements.txt`, como rodar os testes (`pytest`).
- [ ] Teste de ponta a ponta `test_fase1_fluxo_completo`: cria projeto de exemplo em pasta temporária (`tmp_path`), chama `criar_projeto`, grava 3 eventos com `registrar_evento`, lê de volta com `listar_eventos`, confirma 3 registros com etapa/nível/mensagem corretos e a linha `projeto` gravada.
- [ ] Rodar `pytest -v` na raiz do projeto e confirmar todos os testes passam.
- [ ] Marcar `[x] Fase 1` na seção 12 do `ESPECIFICACAO.md`.

"""Os nomes dos motores de classificação.

Módulo de base, sem dependências: `config` (que valida o campo do formulário)
não pode importar `classification` (ciclo `classification → windows_prep →
config`), e os dois precisam dos mesmos nomes. Todo o pacote lê daqui.

Os valores são contrato gravado: aparecem em `config_json`
(`classification_engine`), em `run.engine`, em `item.engine` e nas linhas de
`raw_items.jsonl`. Mudar um valor daqui deixa os projetos antigos com um motor
que ninguém reconhece.
"""

from __future__ import annotations

ENGINE_RULES = "rules"
ENGINE_LOCAL = "local"
# Atos do Planalto lidos pela estrutura (`planalto.py`), em qualquer motor.
ENGINE_STRUCTURED = "structured"
# Saiu na 2.0.0. Continua válido só para importar linhas antigas de
# `raw_items.jsonl`; `project.load_project` converte um projeto salvo com ele.
ENGINE_CLAUDE_CODE = "claude_code"
# Sentinela do formulário (`config.classification_engine`), resolvida em
# `orchestrator`; nunca é gravada em `item.engine`.
ENGINE_AUTOMATIC = "automatic"

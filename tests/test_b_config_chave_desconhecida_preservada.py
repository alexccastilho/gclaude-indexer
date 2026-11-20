"""Etapa B: regravar a configuração não apaga do `config_json` um campo
que esta versão não conhece (gravado por uma versão mais nova).

`save_project_config`, a regravação pela mudança de pasta e a conversão do
`openrouter` gravavam só `asdict(config)`, e o campo desconhecido sumia:
abrir o projeto numa versão mais velha apagava a configuração da nova.
Agora as chaves desconhecidas do JSON gravado atravessam a regravação."""

from __future__ import annotations

import json
import shutil
import sqlite3

from gclaude_indexer.config import load_config
from gclaude_indexer.project import create_project, load_project, save_project_config


def _projeto(tmp_path, **extras):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({"name": "x", "subject": "y", "source_folder": str(origem), "output_folder": str(saida)})
    conn, _ = create_project(config)
    dados = json.loads(conn.execute("SELECT config_json FROM project").fetchone()[0])
    conn.execute("UPDATE project SET config_json = ?", (json.dumps(dados | extras),))
    conn.commit()
    conn.close()
    return saida


def _gravado(saida):
    conn = sqlite3.connect(saida / "project.db")
    try:
        return json.loads(conn.execute("SELECT config_json FROM project").fetchone()[0])
    finally:
        conn.close()


def test_salvar_a_configuracao_preserva_campo_desconhecido(tmp_path):
    saida = _projeto(tmp_path, campo_preservado_b={"a": 1})
    config, conn = load_project(saida)
    config.subject = "outro assunto"
    save_project_config(conn, config)
    conn.close()

    gravado = _gravado(saida)
    assert gravado["subject"] == "outro assunto"
    assert gravado["campo_preservado_b"] == {"a": 1}


def test_regravacao_pela_mudanca_de_pasta_preserva_campo_desconhecido(tmp_path):
    saida = _projeto(tmp_path, campo_preservado_b=7)
    nova = tmp_path / "saida_movida"
    shutil.move(str(saida), str(nova))

    config, conn = load_project(nova)
    conn.close()

    gravado = _gravado(nova)
    assert gravado["output_folder"] == str(nova)
    assert gravado["campo_preservado_b"] == 7


def test_conversao_do_openrouter_preserva_campo_desconhecido(tmp_path):
    saida = _projeto(tmp_path, campo_preservado_b="sim", classification_engine="openrouter")

    config, conn = load_project(saida)
    conn.close()

    gravado = _gravado(saida)
    assert gravado["classification_engine"] == "rules"
    assert gravado["campo_preservado_b"] == "sim"

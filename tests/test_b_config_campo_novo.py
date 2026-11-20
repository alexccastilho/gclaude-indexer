# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: um projeto gravado por uma versão mais nova (com um campo que
esta versão não conhece em `config_json`) abre normalmente; o campo é
ignorado e fica um aviso no log do app."""

from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from gclaude_indexer.config import ConfigError, config_from_input, load_config
from gclaude_indexer.web.readers import reader_pool
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def _acrescentar_campo(pasta, nome, valor):
    reader_pool.close_all()
    conn = sqlite3.connect(pasta / "project.db")
    texto = conn.execute("SELECT config_json FROM project ORDER BY id LIMIT 1").fetchone()[0]
    dados = json.loads(texto)
    dados[nome] = valor
    conn.execute("UPDATE project SET config_json = ?", (json.dumps(dados, ensure_ascii=False),))
    conn.commit()
    conn.close()


def test_projeto_com_campo_de_versao_mais_nova_abre(cliente, tmp_path, caplog):
    pid = _criar_projeto(cliente, tmp_path)
    _acrescentar_campo(tmp_path / "Projeto_de_teste_indexado", "campo_do_futuro", 7)
    with caplog.at_level(logging.WARNING):
        resposta = cliente.get(f"/projects/{pid}/run")
    assert resposta.status_code == 200
    assert "campo_do_futuro" in caplog.text


def test_load_config_ignora_campo_desconhecido_e_avisa(tmp_path, caplog):
    dados = {"name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")}
    with caplog.at_level(logging.WARNING):
        config = load_config(dados | {"campo_do_futuro_2": True})
    assert config.name == "x"
    assert not hasattr(config, "campo_do_futuro_2")
    assert "campo_do_futuro_2" in caplog.text


def test_entrada_do_usuario_com_campo_desconhecido_continua_recusada(tmp_path):
    dados = {"name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")}
    with pytest.raises(ConfigError):
        config_from_input(dados | {"campo_do_futuro": True})

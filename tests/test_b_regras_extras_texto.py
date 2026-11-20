# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: a tela de Instruções dizia que o modelo local usa os primeiros
700 caracteres das regras extras. Desde a 2.1.0 o prompt por página (o
único que a classificação usa) não leva o bloco do projeto: o modelo local
não lê as regras extras. O texto passa a dizer isso; o prompt não muda."""

from __future__ import annotations

from gclaude_indexer import i18n
from gclaude_indexer.config import load_config
from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import _build_page_prompt
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401


def test_prompt_da_classificacao_nao_leva_as_regras_extras(tmp_path):
    config = load_config({
        "name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path),
        "extra_rules": "REGRA-MARCADOR sempre cite o processo",
    })
    pagina = WindowPage(reference="f. 1", file_name="a.pdf", text="texto da página", has_table=False, image_count=0)
    assert "REGRA-MARCADOR" not in _build_page_prompt([pagina], config)


def test_tela_nao_promete_caracteres_ao_modelo_local(cliente, tmp_path):
    for idioma in ("pt", "en", "es"):
        texto = i18n.translate(idioma, "instructions.extra_rules.help", limit=4000, prompt=700)
        assert "700" not in texto and "{" not in texto
    pid = _criar_projeto(cliente, tmp_path)
    tela = cliente.get(f"/projects/{pid}/instructions", cookies={"language": "pt"}).text
    assert "primeiros 700" not in tela
    assert "o modelo local não as lê" in tela

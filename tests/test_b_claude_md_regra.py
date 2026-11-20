"""Decisão do usuário (etapa B): o CLAUDE.md do projeto simples traz a regra
inegociável (`SOURCE_OF_TRUTH_RULE`), como o CLAUDE.md do conjunto."""

from __future__ import annotations

from gclaude_indexer.artifacts import generate_claude_md
from gclaude_indexer.config import load_config
from gclaude_indexer.i18n import translate
from gclaude_indexer.managed_block import SOURCE_OF_TRUTH_RULE


def _config(tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir()
    return load_config({
        "name": "Regra no CLAUDE.md",
        "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida),
        "extensions": ["pdf"],
    })


def test_claude_md_do_projeto_traz_a_regra_inegociavel_nos_tres_idiomas(tmp_path):
    config = _config(tmp_path)
    for idioma in ("pt", "en", "es"):
        texto = generate_claude_md(config, idioma).read_text(encoding="utf-8")
        titulo = translate(idioma, "artifact.project_instructions.rule_section")
        assert f"## {titulo}\n\n{SOURCE_OF_TRUTH_RULE}\n" in texto, idioma
        assert texto.count(SOURCE_OF_TRUTH_RULE) == 1

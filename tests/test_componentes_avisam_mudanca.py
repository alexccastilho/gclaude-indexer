"""Instalar ou remover um componente avisa quem guardou o que estava
instalado, sem que `components` importe esses módulos (a camada de baixo
não conhece quem a usa; antes ela importava `settings_proposal` dentro de
`_changed`, o que fechava um ciclo components → settings_proposal →
ocr_languages → components)."""

import ast
from pathlib import Path

from gclaude_indexer import components, settings_proposal, tools


def test_mudanca_de_componente_esquece_os_idiomas_do_ocr(monkeypatch):
    monkeypatch.setattr(tools, "find", lambda _nome: None)
    settings_proposal.installed_ocr_languages.cache_clear()
    settings_proposal.installed_ocr_languages()
    assert settings_proposal.installed_ocr_languages.cache_info().currsize == 1
    components._changed()
    assert settings_proposal.installed_ocr_languages.cache_info().currsize == 0


def test_avisos_chamam_cada_interessado(monkeypatch):
    chamados = []
    monkeypatch.setattr(components, "_change_listeners", [lambda: chamados.append("a"), lambda: chamados.append("b")])
    components._changed()
    assert chamados == ["a", "b"]


def test_components_nao_importa_quem_o_usa():
    fonte = Path(components.__file__).read_text(encoding="utf-8")
    importados = {
        n.module for n in ast.walk(ast.parse(fonte)) if isinstance(n, ast.ImportFrom) and n.level
    }
    assert "settings_proposal" not in importados

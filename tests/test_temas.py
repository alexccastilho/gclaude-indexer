"""Temas novos e a camada de movimento.

Quatro temas a mais (Aurora, Toga, Grafite, Oceano), cada um com o conjunto
completo de cores, e uma folha `motion.css` com as transições — sempre
desligadas quando o Windows pede menos movimento (acessibilidade).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gclaude_indexer.i18n import _TRANSLATIONS
from gclaude_indexer.web.theme import AVAILABLE_THEMES

STATIC = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "static"
NOVOS = ("aurora", "toga", "graphite", "ocean")


def _tokens(bloco: str) -> set[str]:
    return set(re.findall(r"(--color-[a-z0-9-]+)\s*:", bloco))


def test_os_temas_novos_estao_disponiveis():
    for tema in NOVOS:
        assert tema in AVAILABLE_THEMES


@pytest.mark.parametrize("tema", NOVOS)
def test_tema_novo_define_todas_as_cores(tema):
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    raiz = _tokens(css.split(":root {", 1)[1].split("}", 1)[0])
    bloco = css.split(f'html[data-theme="{tema}"] {{', 1)[1].split("}", 1)[0]
    faltando = raiz - _tokens(bloco)
    assert not faltando, f"{tema} não define {sorted(faltando)}"


@pytest.mark.parametrize("tema", NOVOS)
def test_tema_novo_tem_nome_nos_tres_idiomas(tema):
    for idioma in ("pt", "en", "es"):
        assert _TRANSLATIONS[idioma].get(f"theme.{tema}"), (idioma, tema)


def test_movimento_respeita_quem_pede_menos_movimento():
    css = (STATIC / "motion.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    # Só propriedades baratas: nada de animar largura, altura ou posição.
    for proibida in ("transition: width", "transition: height", "transition: top", "transition: left"):
        assert proibida not in css


def test_motion_css_e_carregado_em_todas_as_telas():
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app

    assert "/static/motion.css" in TestClient(app).get("/projects").text


def test_barras_de_qualidade_usam_classes_que_o_css_define():
    """O template usava `qualidade-barra-high` e o CSS, `quality-bar-high`
    (sobra da tradução dos nomes na fase 14): as barras de confiança da
    tela Resultado ficavam sem cor nenhuma, invisíveis."""
    template = (STATIC.parent / "templates" / "result.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "quality-bar-fill quality-bar-{{ nivel }}" in template
    for nivel in ("high", "medium", "low"):
        assert f".quality-bar-fill.quality-bar-{nivel}" in css

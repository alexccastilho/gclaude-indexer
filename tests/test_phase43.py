# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.10.0: the workspace layout (side bar, tabs, command palette) and the
Studio themes. The other layouts and themes stay as they were."""

from __future__ import annotations

import json
import re
from pathlib import Path

from gclaude_indexer.web import app as modulo_app
from gclaude_indexer.web.layout import AVAILABLE_LAYOUTS, DEFAULT_LAYOUT, LAYOUT_COOKIE_NAME
from gclaude_indexer.web.theme import AVAILABLE_THEMES, DEFAULT_THEME
from tests.test_phase9 import _criar_projeto, cliente  # noqa: F401

_STATIC = Path(modulo_app.__file__).parent / "static"


def test_area_de_trabalho_e_o_padrao_e_os_outros_continuam():
    assert DEFAULT_LAYOUT == "workspace"
    assert set(AVAILABLE_LAYOUTS) >= {"workspace", "standard", "technical", "editorial", "compact"}
    assert DEFAULT_THEME == "studio"
    assert {"studio", "studio_dark", "light", "dark", "sepia", "high_contrast"} <= set(AVAILABLE_THEMES)
    # A new cookie name: whoever had a layout saved sees the new one once.
    assert LAYOUT_COOKIE_NAME != "layout"


def test_barra_lateral_lista_os_projetos_e_marca_a_tela(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path, nome="Acervo Lateral")
    modulo_app._side_bar_cache.clear()
    corpo = cliente.get(f"/projects/{pid}/run").text
    assert 'data-layout="workspace"' in corpo
    assert 'class="ws-side"' in corpo
    assert "Acervo Lateral" in corpo and ">AL<" in corpo
    assert f'href="/projects/{pid}/run" aria-current="page"' in corpo
    # The five screens of a project as tabs, the current one marked.
    abas = re.search(r'<nav class="ws-tabs".*?</nav>', corpo, re.S).group(0)
    for tela in ("run", "result", "search", "update", "instructions"):
        assert f"/projects/{pid}/{tela}" in abas
    assert abas.count('aria-current="page"') == 1


def test_paleta_tem_telas_projetos_e_preferencias(cliente, tmp_path):
    pid = _criar_projeto(cliente, tmp_path, nome="Acervo Paleta")
    modulo_app._side_bar_cache.clear()
    corpo = cliente.get("/projects").text
    assert 'id="ws-palette"' in corpo and 'role="dialog"' in corpo and 'role="listbox"' in corpo
    dados = re.search(r'<script type="application/json" id="ws-palette-data">(.*?)</script>', corpo, re.S).group(1)
    itens = json.loads(dados)
    urls = {item.get("url") for item in itens}
    assert {"/projects", "/projects/new", "/sets", "/help"} <= urls
    assert f"/projects/{pid}/search" in urls
    temas = [item for item in itens if item.get("pref") == "theme"]
    assert len(temas) == len(AVAILABLE_THEMES)
    assert sum(1 for item in temas if item["current"]) == 1
    # Only navigation and preferences: nothing in it starts work.
    assert all(("url" in item) != ("pref" in item) for item in itens)


def test_outro_layout_nao_tem_barra_lateral(cliente, tmp_path):
    cliente.post("/preferences/layout", data={"layout": "standard"}, follow_redirects=False)
    corpo = cliente.get("/projects").text
    assert 'data-layout="standard"' in corpo
    assert "ws-side" not in corpo and "ws-palette" not in corpo
    assert 'class="header"' in corpo


def test_barra_lateral_nao_abre_banco(cliente, tmp_path, monkeypatch):
    _criar_projeto(cliente, tmp_path)
    modulo_app._side_bar_cache.clear()
    import gclaude_indexer.web.step_state as step_state

    def proibido(*args, **kwargs):
        raise AssertionError("the side bar must not open a database")

    monkeypatch.setattr(step_state, "project_status", proibido)
    monkeypatch.setattr(modulo_app, "project_status", proibido)
    monkeypatch.setattr(modulo_app, "_open_project", proibido)
    corpo = cliente.get("/about").text
    assert 'class="ws-side"' in corpo and "Projeto de teste" in corpo


def test_fontes_vem_junto_com_o_programa():
    css = (_STATIC / "workspace.css").read_text(encoding="utf-8")
    for nome in re.findall(r'url\("/static/(fonts/[^"]+)"\)', css):
        assert (_STATIC / nome).is_file(), nome
    assert (_STATIC / "fonts" / "OFL-Inter.txt").is_file()
    assert "http" not in css  # runs offline


def test_temas_estudio_definem_todas_as_cores():
    css = (_STATIC / "style.css").read_text(encoding="utf-8")
    base = css[css.index(":root {"):]
    base = base[:base.index("}")]
    chaves = set(re.findall(r"(--color-[\w-]+):", base))
    for tema in ("studio", "studio_dark"):
        bloco = css[css.index(f'html[data-theme="{tema}"] {{'):]
        bloco = bloco[:bloco.index("}")]
        faltam = chaves - set(re.findall(r"(--color-[\w-]+):", bloco))
        assert not faltam, (tema, faltam)


def test_chaves_novas_nos_tres_idiomas_sem_travessao():
    from gclaude_indexer.i18n import _TRANSLATIONS

    chaves = [k for k in _TRANSLATIONS["pt"] if k.startswith("ws.")]
    chaves += ["theme.studio", "theme.studio_dark", "layout.workspace"]
    assert len(chaves) > 20
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            assert chave in _TRANSLATIONS[idioma], (idioma, chave)
            assert "—" not in _TRANSLATIONS[idioma][chave]


def test_projeto_novo_aparece_na_barra_lateral_na_hora(cliente, tmp_path):
    cliente.get("/projects")  # fills the side bar cache with no project
    _criar_projeto(cliente, tmp_path, nome="Recem Criado")
    assert "Recem Criado" in cliente.get("/about").text

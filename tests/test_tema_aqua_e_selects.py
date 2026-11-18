"""2.1.0: tema Aqua e a lista dos selects legível nos temas escuros.

- O nome dos temas, na lista aberta do seletor de tema, sumia nos temas
  escuros: `.preference-form select option { color: #111; }` fixava texto
  quase preto, e com `color-scheme: dark` a lista abria com fundo escuro.
  Quatro temas escuros nem declaravam `color-scheme`.
- O orçamento do pacote (tela Resultado, Conjuntos) usava cores de recuo
  creme fixas, com texto claro por cima nos temas escuros.
- Aqua: claro e translúcido, à moda do GNOME, sobre a base de vidro.
"""

from __future__ import annotations

import re

import pytest

from gclaude_indexer.i18n import _TRANSLATIONS
from gclaude_indexer.web.theme import AVAILABLE_THEMES, valid_theme
from tests.test_phase9 import cliente  # noqa: F401
from tests.test_temas_vidro_apple import _bloco, _contraste, _css, _rgba, _sobre, _tokens

ESCUROS = ("dark", "studio_dark", "high_contrast", "aurora", "graphite", "glass_dark", "apple_dark")


def test_opcoes_dos_selects_seguem_o_esquema_do_tema():
    css = _css("style.css")
    assert "option { color: #111; }" not in css
    assert re.search(r"select option, select optgroup \{ background-color: Canvas; color: CanvasText; \}", css)


def test_todo_tema_escuro_declara_color_scheme_dark():
    css = _css("style.css")
    regra = re.search(r"html:is\(([^)]*)\) \{ color-scheme: dark; \}", css, re.S)
    assert regra, "regra de color-scheme escuro não encontrada"
    declarados = set(re.findall(r'data-theme="([a-z_]+)"', regra.group(1)))
    assert declarados == set(ESCUROS)
    assert "html { color-scheme: light; }" in css


@pytest.mark.parametrize("tema", ESCUROS)
def test_tema_escuro_tem_fundo_escuro(tema):
    """A lista de temas escuros do `color-scheme` bate com as cores."""
    from tests.test_temas_vidro_apple import _luminancia

    cores = _tokens(_bloco(_css("style.css"), tema))
    assert _luminancia(_rgba(cores["--color-bg"])) < 0.1


def test_orcamento_usa_as_cores_do_tema():
    css = _css("style.css")
    assert "#fff4d6" not in css and "#fde2e4" not in css
    assert ".budget-rag { background: var(--color-warning-bg); }" in css
    assert ".budget-over { background: var(--color-error-bg); }" in css


def test_aqua_na_lista_e_nos_tres_idiomas():
    assert "aqua" in AVAILABLE_THEMES and valid_theme("aqua") == "aqua"
    assert AVAILABLE_THEMES[-1] == "aqua"  # no fim: as posições antigas não mudam
    for idioma in ("pt", "en", "es"):
        assert _TRANSLATIONS[idioma].get("theme.aqua")


def test_aqua_define_todas_as_cores():
    css = _css("style.css")
    raiz = set(_tokens(css.split(":root {", 1)[1].split("}", 1)[0]))
    assert not raiz - set(_tokens(_bloco(css, "aqua")))


def test_aqua_contraste_aa():
    cores = _tokens(_bloco(_css("style.css"), "aqua"))
    fundo = _rgba(cores["--color-bg"])
    superficie = _sobre(cores["--color-surface"], fundo)
    for frente, sob, minimo in (
        ("--color-text", fundo, 4.5), ("--color-text", superficie, 4.5),
        ("--color-text-weak", fundo, 4.5), ("--color-text-weak", superficie, 4.5),
        ("--color-accent", superficie, 4.5), ("--color-accent", fundo, 4.5),
        ("--color-ok", superficie, 4.5), ("--color-warning", superficie, 4.5),
        ("--color-error", superficie, 4.5),
    ):
        assert _contraste(_sobre(cores[frente], sob), sob) >= minimo, (frente, minimo)
    assert _contraste(_rgba(cores["--color-accent-text"]), _rgba(cores["--color-accent"])) >= 4.5


def test_aqua_usa_o_vidro_e_tem_recuo_opaco():
    css = _css("themes.css")
    assert '[data-theme="glass"], [data-theme="glass_dark"], [data-theme="aqua"]) body' in css
    assert 'html[data-theme="aqua"] {\n  --glass-blur' in css
    # transparência reduzida e navegador sem desfoque também valem para ele
    reduzida = css.split("@media (prefers-reduced-transparency: reduce)", 1)[1]
    assert '[data-theme="aqua"]' in reduzida


def test_rota_aplica_o_aqua(cliente):  # noqa: F811
    cliente.post("/preferences/theme", data={"theme": "aqua"}, follow_redirects=False)
    corpo = cliente.get("/projects").text
    assert 'data-theme="aqua"' in corpo
    assert '<option value="aqua" selected' in corpo

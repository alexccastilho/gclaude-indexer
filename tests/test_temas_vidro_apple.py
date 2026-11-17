"""2.0.0: temas "Vidro" (glassmorphism) e "Apple" (estilo iOS/macOS).

Cada um em par claro/escuro, como Estúdio/Estúdio escuro: `glass`,
`glass_dark`, `apple`, `apple_dark`. As cores moram em `style.css` (o mesmo
conjunto de tokens de todos os temas); o vidro, a tipografia e os
controles moram em `themes.css`, carregado por último em todas as telas.

O contraste é conferido aqui de verdade, com a fórmula da WCAG: um token
mexido sem querer que deixe o texto ilegível derruba o teste, não só a
captura de tela.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gclaude_indexer.i18n import _TRANSLATIONS
from gclaude_indexer.web.theme import AVAILABLE_THEMES, DEFAULT_THEME, valid_theme
from tests.test_phase9 import cliente  # noqa: F401

STATIC = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "static"
TEMPLATES = STATIC.parent / "templates"
NOVOS = ("glass", "glass_dark", "apple", "apple_dark")


def _css(nome: str) -> str:
    return (STATIC / nome).read_text(encoding="utf-8")


def _bloco(css: str, tema: str) -> str:
    return css.split(f'html[data-theme="{tema}"] {{', 1)[1].split("}", 1)[0]


def _tokens(bloco: str) -> dict[str, str]:
    return dict(re.findall(r"(--color-[a-z0-9-]+)\s*:\s*([^;]+);", bloco))


# --- cores e contraste (WCAG 2.x) ---------------------------------------


def _rgba(valor: str) -> tuple[float, float, float, float]:
    valor = valor.strip()
    if valor.startswith("#"):
        h = valor[1:]
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    partes = [float(p) for p in re.match(r"rgba?\(([^)]*)\)", valor).group(1).split(",")]
    return (partes[0], partes[1], partes[2], partes[3] if len(partes) > 3 else 1.0)


def _sobre(cima: str, baixo: tuple) -> tuple:
    r, g, b, a = _rgba(cima)
    return (r * a + baixo[0] * (1 - a), g * a + baixo[1] * (1 - a), b * a + baixo[2] * (1 - a), 1.0)


def _luminancia(cor: tuple) -> float:
    def canal(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(cor[0]) + 0.7152 * canal(cor[1]) + 0.0722 * canal(cor[2])


def _contraste(frente: tuple, fundo: tuple) -> float:
    a, b = sorted((_luminancia(frente), _luminancia(fundo)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_os_quatro_temas_estao_na_lista_e_sao_aceitos():
    for tema in NOVOS:
        assert tema in AVAILABLE_THEMES
        assert valid_theme(tema) == tema
    assert valid_theme("vidro") == DEFAULT_THEME
    # Os de antes continuam na mesma ordem (a guarda da fase 12 conta posições).
    assert AVAILABLE_THEMES[2:6] == ("light", "dark", "sepia", "high_contrast")


@pytest.mark.parametrize("tema", NOVOS)
def test_rota_de_preferencia_grava_cookie_e_aplica_o_tema(cliente, tema):  # noqa: F811
    resposta = cliente.post("/preferences/theme", data={"theme": tema}, follow_redirects=False)
    assert resposta.status_code in (302, 303)
    assert f"theme={tema}" in resposta.headers["set-cookie"]
    corpo = cliente.get("/projects").text
    assert f'data-theme="{tema}"' in corpo
    assert f'<option value="{tema}" selected' in corpo


def test_tema_desconhecido_volta_ao_padrao(cliente):  # noqa: F811
    cliente.post("/preferences/theme", data={"theme": "liquid"}, follow_redirects=False)
    assert f'data-theme="{DEFAULT_THEME}"' in cliente.get("/projects").text


@pytest.mark.parametrize("tema", NOVOS)
def test_nome_nos_tres_idiomas(tema):
    for idioma in ("pt", "en", "es"):
        nome = _TRANSLATIONS[idioma].get(f"theme.{tema}")
        assert nome, (idioma, tema)
        assert "—" not in nome


@pytest.mark.parametrize("tema", NOVOS)
def test_tema_define_todas_as_cores(tema):
    css = _css("style.css")
    raiz = set(_tokens(css.split(":root {", 1)[1].split("}", 1)[0]))
    faltando = raiz - set(_tokens(_bloco(css, tema)))
    assert not faltando, f"{tema} não define {sorted(faltando)}"


@pytest.mark.parametrize("tema", NOVOS)
def test_contraste_aa_dos_pares_principais(tema):
    cores = _tokens(_bloco(_css("style.css"), tema))
    fundo = _rgba(cores["--color-bg"])
    superficie = _sobre(cores["--color-surface"], fundo)
    alternativa = _sobre(cores["--color-surface-alt"], superficie)
    aviso = _sobre(cores["--color-warning-bg"], superficie)
    erro = _sobre(cores["--color-error-bg"], superficie)
    # Aviso de conclusão: fica direto sobre o fundo, tingido pelo destaque.
    conclusao = _sobre(cores["--color-accent-weak"], fundo)

    def cor(nome: str, sob: tuple) -> tuple:
        return _sobre(cores[nome], sob)

    texto = [
        ("texto/fundo", "--color-text", fundo),
        ("texto/superfície", "--color-text", superficie),
        ("texto/badge", "--color-text", alternativa),
        ("fraco/fundo", "--color-text-weak", fundo),
        ("fraco/superfície", "--color-text-weak", superficie),
        ("fraco/cabeçalho de tabela", "--color-text-weak", alternativa),
        ("destaque/superfície", "--color-accent", superficie),
        ("destaque/fundo", "--color-accent", fundo),
        ("botão primário", "--color-accent-text", _rgba(cores["--color-accent"])),
        ("concluído/superfície", "--color-ok", superficie),
        ("pendente/superfície", "--color-warning", superficie),
        ("erro/superfície", "--color-error", superficie),
        ("badge de aviso", "--color-warning-text", aviso),
        ("botão de perigo", "--color-error", erro),
        ("link no aviso de conclusão", "--color-accent", conclusao),
        ("texto no aviso de conclusão", "--color-text", conclusao),
        ("log", "--color-log-text", _rgba(cores["--color-log-bg"])),
        ("hora no log", "--color-log-time", _rgba(cores["--color-log-bg"])),
        ("cabeçalho", "--color-header-text", _sobre(cores["--color-header-bg"], fundo)),
        # O cabeçalho é translúcido e fixo: o log, sempre escuro, passa por baixo.
        ("cabeçalho sobre o log", "--color-header-text",
         _sobre(cores["--color-header-bg-alt"], _rgba(cores["--color-log-bg"]))),
    ]
    for rotulo, nome, sob in texto:
        razao = _contraste(cor(nome, sob), sob)
        assert razao >= 4.5, f"{tema}: {rotulo} {razao:.2f}"
    # Linhas dos gráficos de recursos: elemento gráfico, 3:1 basta.
    for nome in ("--color-cpu", "--color-ram", "--color-gpu"):
        razao = _contraste(cor(nome, superficie), superficie)
        assert razao >= 3, f"{tema}: {nome} {razao:.2f}"


def test_temas_escuros_avisam_o_navegador():
    css = _css("style.css")
    for tema in ("glass_dark", "apple_dark"):
        assert "color-scheme: dark" in _bloco(css, tema), tema


def test_orcamento_do_pacote_usa_as_cores_do_tema():
    """`.budget-rag`/`.budget-over` recuam para creme fixo se estes nomes
    faltarem: num tema escuro, texto claro sobre caixa clara."""
    css = _css("themes.css")
    for nome in ("--color-warning-weak", "--color-danger-weak", "--color-danger"):
        assert f"{nome}: var(--color-" in css, nome


def test_folha_dos_temas_e_carregada_por_ultimo_em_todas_as_telas(cliente):  # noqa: F811
    corpo = cliente.get("/projects").text
    folhas = re.findall(r'<link rel="stylesheet" href="(/static/[^"]+)">', corpo)
    assert folhas[-1] == "/static/themes.css"


def test_vidro_tem_alternativa_opaca_e_respeita_transparencia_reduzida():
    css = _css("themes.css")
    assert "blur(18px) saturate(" in css and "backdrop-filter: var(--glass-blur)" in css
    assert "-webkit-backdrop-filter" in css
    assert "@supports not ((backdrop-filter:" in css
    assert "prefers-reduced-transparency: reduce" in css
    assert "prefers-contrast: more" in css
    # Nada de fonte ou imagem baixada: o programa roda offline.
    assert "http" not in css and "@font-face" not in css and "url(" not in css


def test_apple_usa_a_fonte_do_sistema():
    css = _css("themes.css")
    assert '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable", "Segoe UI", system-ui' in css


def test_manual_lista_os_temas_novos():
    nomes = {
        "pt": ("Vidro", "Vidro escuro", "Apple", "Apple escuro"),
        "en": ("Glass", "Glass dark", "Apple", "Apple dark"),
        "es": ("Vidrio", "Vidrio oscuro", "Apple", "Apple oscuro"),
    }
    for idioma, esperados in nomes.items():
        manual = (TEMPLATES / "manual" / f"{idioma}.html").read_text(encoding="utf-8")
        linha = next(l for l in manual.splitlines() if "Aurora, Toga" in l)
        for nome in esperados:
            assert nome in linha, (idioma, nome)

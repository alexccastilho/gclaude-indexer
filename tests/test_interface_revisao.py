"""Revisão da interface depois da 2.0.0 (defeitos vistos no computador do trabalho).

- No layout Área de trabalho, as preferências (tema, layout, idioma) ficavam no
  fim da barra lateral, depois da lista inteira de projetos: numa tela baixa era
  preciso rolar a barra até embaixo para trocar o tema.
- CSS e JS eram servidos sem versão no endereço, e o navegador podia continuar
  com a folha antiga depois de uma atualização.
- A classe `.notice` (banner de atualização, relatórios desatualizados, índice de
  busca incompleto) não tinha regra nenhuma.
- A tabela de diagnóstico da tela Sobre usava classes em português que o CSS não
  conhece.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from gclaude_indexer.web.app import app

WEB = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web"


def _regra(css: str, seletor: str) -> str:
    """Corpo de todas as regras cujo seletor termina exatamente em `seletor`."""
    corpos = re.findall(re.escape(seletor) + r"\s*\{([^}]*)\}", css)
    return "\n".join(corpos)


def test_lista_de_projetos_rola_sozinha_e_as_preferencias_ficam_visiveis():
    css = (WEB / "static" / "workspace.css").read_text(encoding="utf-8")
    lista = _regra(css, 'html[data-layout="workspace"] .ws-projects')
    assert "overflow-y: auto" in lista
    assert "min-height" in lista
    rodape = _regra(css, 'html[data-layout="workspace"] .ws-foot')
    assert "margin-top: auto" in rodape


def test_css_e_js_vem_com_versao_no_endereco():
    corpo = TestClient(app).get("/projects").text
    folhas = re.findall(r'(?:href|src)="(/static/[^"]+\.(?:css|js)[^"]*)"', corpo)
    assert folhas, "nenhuma folha encontrada"
    for endereco in folhas:
        assert re.search(r"\?v=[0-9a-f]{10}$", endereco), endereco


def test_aviso_tem_estilo_proprio():
    css = (WEB / "static" / "style.css").read_text(encoding="utf-8")
    regra = _regra(css, ".notice")
    assert "border-left" in regra and "padding" in regra


def test_classes_do_diagnostico_existem_no_css():
    modelo = (WEB / "templates" / "about.html").read_text(encoding="utf-8")
    css = (WEB / "static" / "style.css").read_text(encoding="utf-8")
    assert "diagnostico-" not in modelo
    assert "diagnostic-{{ 'present' if item.present else 'missing' }}" in modelo
    assert ".diagnostic-present" in css and ".diagnostic-missing" in css


def test_botao_do_banner_de_atualizacao_tem_a_classe_base():
    modelo = (WEB / "templates" / "_update_banner.html").read_text(encoding="utf-8")
    assert 'class="button button-primary"' in modelo

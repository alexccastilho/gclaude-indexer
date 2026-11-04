"""O manual completo: uma tela própria, nos três idiomas, a um clique de
qualquer tela — o modal de ajuda de cada tela era só um resumo dela."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gclaude_indexer.web.app import app

MANUAL = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "templates" / "manual"


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.mark.parametrize("language, frase", [
    ("pt", "Começo rápido"), ("en", "Quick start"), ("es", "Inicio rápido"),
])
def test_manual_abre_no_idioma_da_interface(cliente, language, frase):
    cliente.cookies.set("language", language)
    resposta = cliente.get("/help")
    assert resposta.status_code == 200
    assert frase in resposta.text
    assert 'id="motores"' in resposta.text


def test_os_tres_manuais_tem_as_mesmas_secoes():
    def ancoras(nome):
        texto = (MANUAL / nome).read_text(encoding="utf-8")
        return set(re.findall(r'id="([^"]+)"', texto)), set(re.findall(r'href="#([^"]+)"', texto))

    pt = ancoras("pt.html")
    assert ancoras("en.html") == pt
    assert ancoras("es.html") == pt
    ids, links = pt
    assert links <= ids, "link do sumário apontando para seção que não existe"


def test_o_manual_esta_no_menu_de_todas_as_telas(cliente):
    for rota in ("/projects", "/projects/new", "/about"):
        assert 'href="/help"' in cliente.get(rota).text


def test_a_ajuda_de_cada_tela_leva_ao_manual(cliente):
    texto = cliente.get("/projects/new").text
    assert 'href="/help#novo-projeto"' in texto

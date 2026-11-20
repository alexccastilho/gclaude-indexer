"""Etapa P: o aviso de código velho só é conferido nas telas inteiras.

O aviso está em `base.html`; os fragmentos (`_*.html`) nunca o estendem e
são os polls de 2 s da tela de Execução. Conferir em cada um deles fazia um
`stat` de cada `.py` do pacote sem nada para mostrar."""

from __future__ import annotations

from starlette.requests import Request

from gclaude_indexer.web import rendering


def _pedido() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []})


def test_fragmento_nao_confere_o_codigo(monkeypatch):
    chamadas = []
    monkeypatch.setattr(rendering, "source_is_stale", lambda: chamadas.append(1) or True)

    resposta = rendering.render(_pedido(), "_log_items.html", {"eventos": [], "known_steps": []})

    assert resposta.status_code == 200
    assert chamadas == []
    assert "stale-banner" not in resposta.body.decode("utf-8")


def test_tela_inteira_confere_o_codigo(monkeypatch):
    chamadas = []
    monkeypatch.setattr(rendering, "source_is_stale", lambda: chamadas.append(1) or True)

    resposta = rendering.render(_pedido(), "base.html", {})

    assert chamadas == [1]
    assert "stale-banner" in resposta.body.decode("utf-8")

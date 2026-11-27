"""2.1.4: resposta que entra em laço é cortada e o trecho é dividido.

Num acervo grande, um trecho de 8 páginas (1.278 tokens de prompt) fez o
modelo repetir o número de um processo e a vara sem parar: sem teto de resposta, o pedido só acabava no tempo limite de 300 s.
Com temperatura 0 a resposta é sempre a mesma, então as 3 tentativas iguais
falhavam igual e o trecho ficava pendente. Medido: com teto de 8.000 tokens
a resposta volta com `done_reason: length` em vez de travar.
"""

from __future__ import annotations

import json

import pytest

from gclaude_indexer.engine_local import LocalEngine, ModelAnswerError, _response_tokens_for
from tests.test_phase21 import _Resposta, _linhas, _page, _plan_com_teto


class _OllamaEmLaco:
    """Responde em laço (cortado pelo teto) quando o trecho tem mais de
    `ate` páginas; trechos menores respondem normalmente."""

    def __init__(self, ate: int = 0):
        self.ate = ate
        self.pedidos: list[dict] = []

    def __call__(self, request, timeout=None):
        corpo = json.loads(request.data.decode("utf-8"))
        self.pedidos.append(corpo)
        paginas = corpo["prompt"].count("--- Página ")
        if paginas > self.ate:
            teto = corpo["options"]["num_predict"]
            return _Resposta({
                "response": '{"pages": [{"n": 1, "detail": "' + "processo 123 (Vara); " * 50,
                "prompt_eval_count": 1278, "eval_count": teto, "done_reason": "length",
            })
        return _Resposta({
            "response": _linhas(paginas), "prompt_eval_count": 300, "eval_count": 200, "done_reason": "stop",
        })


def _paginas(n):
    return [_page(f"f. {i}", f"Processo número {i} da vara do trabalho, com as partes e o pedido.") for i in range(1, n + 1)]


def test_pedido_leva_teto_de_resposta_proporcional_as_paginas(monkeypatch):
    _plan_com_teto(monkeypatch, teto=32768)
    ollama = _OllamaEmLaco(ate=99)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    LocalEngine(model="fake", url_base="http://127.0.0.1:9").classify(_paginas(8))
    teto = ollama.pedidos[0]["options"]["num_predict"]
    # Folga sobre a reserva da resposta (respostas reais de 8 páginas: 998 e
    # 1.470 tokens, a reserva é 1.760), mas longe dos milhares de um laço.
    # 2.1.6: o teto caiu de 3x para 1,8x a reserva — 3.168 tokens, mais que
    # o dobro da maior resposta medida, e um laço é cortado em metade do
    # tempo de antes.
    assert 1_470 * 2 <= teto <= _response_tokens_for(8) * 2


def test_resposta_cortada_pelo_teto_e_resposta_invalida(monkeypatch):
    _plan_com_teto(monkeypatch, teto=32768)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", _OllamaEmLaco(ate=0))
    with pytest.raises(ModelAnswerError):
        LocalEngine(model="fake", url_base="http://127.0.0.1:9").classify(_paginas(8))


def test_trecho_em_laco_e_dividido_e_as_metades_sao_classificadas(monkeypatch):
    from gclaude_indexer.engine_local import _classify_in_parts

    _plan_com_teto(monkeypatch, teto=32768)
    ollama = _OllamaEmLaco(ate=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    itens = _classify_in_parts(LocalEngine(model="fake", url_base="http://127.0.0.1:9"), _paginas(8))
    assert {n for item in itens for n in range(item.start_order, item.end_order + 1)} == set(range(1, 9))
    assert all(item.engine == "local" for item in itens)

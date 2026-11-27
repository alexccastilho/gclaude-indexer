"""2.1.6: a razão caracteres/token não fica presa ao pior caso da corrida.

Antes, `_calibrate` guardava o mínimo de toda a corrida: uma única página
cheia de códigos numéricos no começo (1,3 caractere por token) inflava o
contexto estimado de todas as janelas seguintes em mais de duas vezes — e,
em placas pequenas, dividia janelas que cabiam. Agora vale o mínimo das
últimas janelas íntegras: o conservadorismo continua dentro do trecho, mas
um ponto fora da curva é esquecido depois de algumas janelas de prosa.
"""

from __future__ import annotations

from gclaude_indexer.engine_local import (
    _CALIBRATION_MEMORY,
    _CHARS_PER_TOKEN,
    _CHARS_PER_TOKEN_FLOOR,
    Generation,
    LocalEngine,
)


def _motor():
    return LocalEngine(model="fake", url_base="http://127.0.0.1:9")


def _janela(motor, caracteres, tokens, contexto=16384):
    motor._calibrate("x" * caracteres, Generation(text="{}", prompt_tokens=tokens, context=contexto))


def test_pagina_numerica_nao_vale_para_a_corrida_inteira():
    motor = _motor()
    _janela(motor, 1300, 1000)          # 1,3: a página de códigos
    assert motor._chars_per_token == 1.3

    for _ in range(_CALIBRATION_MEMORY):
        _janela(motor, 2800, 1000)      # 2,8: prosa comum

    assert motor._chars_per_token == 2.8


def test_continua_o_minimo_das_janelas_recentes():
    motor = _motor()
    _janela(motor, 2800, 1000)
    _janela(motor, 1600, 1000)
    _janela(motor, 2800, 1000)

    assert motor._chars_per_token == 1.6


def test_nunca_acima_da_semente_nem_abaixo_do_piso():
    motor = _motor()
    _janela(motor, 4500, 1000)          # 4,5: mais otimista que a semente
    assert motor._chars_per_token == _CHARS_PER_TOKEN

    _janela(motor, 500, 1000)           # 0,5: telemetria absurda
    assert motor._chars_per_token == _CHARS_PER_TOKEN_FLOOR


def test_prompt_honesto_perto_da_metade_do_contexto_calibra():
    """A assinatura do corte (lido = metade do contexto) só vale quando a
    estimativa do prompt é bem maior que o lido. Um prompt íntegro que cai
    perto de `num_ctx / 2` ensina a razão como qualquer outro."""
    motor = _motor()
    # 6150 caracteres lidos como 4100 tokens num contexto de 8192: 1,5.
    # A estimativa (6150 / 3,0 = 2050) é menor que o lido — não é corte.
    _janela(motor, 6150, 4100, contexto=8192)

    assert motor._chars_per_token == 1.5

"""Etapa B: a chave do cache dos fragmentos da tela de Execução
(`caches._activity_key`) muda quando uma operação da `_generation_slot`
começa e termina. Antes, uma operação dessas não deixa rastro em
`_OPERATIONS`, a chave voltava a ser a mesma de antes dela, e a tela
reaproveitava por até 30 s o fragmento de antes da operação."""

from __future__ import annotations

from gclaude_indexer.web import caches
from gclaude_indexer.web.state import _generation_slot


def test_fragmento_e_refeito_depois_de_uma_operacao_da_vaga():
    projeto = 987654
    assert caches._idle_fragment(projeto, "steps", "pt", lambda: "antes") == "antes"
    chave_antes = caches._activity_key(projeto)

    with _generation_slot(projeto, "result.cleanup_button") as tomada:
        assert tomada
        assert caches._activity_key(projeto) is None

    assert caches._activity_key(projeto) != chave_antes
    assert caches._idle_fragment(projeto, "steps", "pt", lambda: "depois") == "depois"

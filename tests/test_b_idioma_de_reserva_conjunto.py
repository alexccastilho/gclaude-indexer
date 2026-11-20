"""Etapa B: o pacote combinado (Conjunto) usa a mesma regra de idioma de
reserva do projeto simples: idioma desconhecido cai no de referência
(`pt`), como em `artifacts.generate_claude_md` e no guia do pacote do
projeto. Antes o combinado caía no idioma da interface do Windows
(`DEFAULT_LANGUAGE`), e o mesmo pedido saía em idiomas diferentes conforme
a máquina."""

from __future__ import annotations

import pytest

from gclaude_indexer import combined_package, i18n
from gclaude_indexer.combined_package import CombinedPlan
from gclaude_indexer.sets import SetEntry


@pytest.fixture
def interface_em_ingles(monkeypatch):
    monkeypatch.setattr(combined_package, "DEFAULT_LANGUAGE", "en")
    monkeypatch.setattr(i18n, "DEFAULT_LANGUAGE", "en")


def _plano():
    return CombinedPlan(files=[], excluded=[], total_tokens=0, level="ok", unavailable=[], limit_tokens=1)


@pytest.mark.parametrize("gerar", [combined_package._guide, combined_package._claude_md])
def test_idioma_desconhecido_cai_no_de_referencia(interface_em_ingles, gerar):
    entrada = SetEntry(id=1, name="Conjunto")
    assert gerar(entrada, _plano(), "xx") == gerar(entrada, _plano(), "pt")
    assert gerar(entrada, _plano(), "xx") != gerar(entrada, _plano(), "en")

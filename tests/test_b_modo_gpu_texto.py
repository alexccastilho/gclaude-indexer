# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Etapa B: `processing_mode="gpu"` faz o mesmo que "automático" (os dois
mandam `num_gpu=-1`). A tela e a documentação passam a dizer isso, em vez
de prometer que "forçar GPU" força alguma coisa."""

from __future__ import annotations

from pathlib import Path

from gclaude_indexer import i18n
from gclaude_indexer.engine_local import _num_gpu_for

_RAIZ = Path(__file__).resolve().parent.parent
_MANUAL = _RAIZ / "gclaude_indexer" / "web" / "templates" / "manual"

_IGUAL = {"pt": "igual ao automático", "en": "same as automatic", "es": "igual que automático"}


def test_comportamento_continua_o_mesmo():
    assert _num_gpu_for("gpu") == _num_gpu_for("automatic") == -1
    assert _num_gpu_for("cpu") == 0


def test_formulario_diz_que_forcar_gpu_e_igual_ao_automatico():
    for idioma, texto in _IGUAL.items():
        assert texto in i18n.translate(idioma, "new_project.processing_mode_gpu")
        assert texto in i18n.translate(idioma, "new_project.help_processing_mode")
        assert texto in i18n.translate(idioma, "hint.processing_mode")


def test_manual_e_especificacao_dizem_que_e_igual():
    for idioma, texto in _IGUAL.items():
        assert texto in (_MANUAL / f"{idioma}.html").read_text(encoding="utf-8")
    spec = (_RAIZ / "docs" / "SPECIFICATION.md").read_text(encoding="utf-8")
    assert "`gpu` behaves exactly like `automatic`" in spec

"""Caracterização dos despachos de texto por tipo (rodada 3 do untangle).

Três caminhos tiram texto de um arquivo conforme o tipo: o arquivo do
acervo (`_extract_light_text`, pela categoria da extensão), o anexo de uma
mensagem (`_extract_attachment_text`, pelo tipo farejado) e o conteúdo de um
`.p7m` (`_signed_content_text`, pelo tipo farejado). A suíte cobria pouco dos
dois últimos. Este teste fixa o texto que cada um devolve hoje para uma
amostra de cada formato, para que a reorganização dos despachos não mude
nada sem querer.

`GERAR_CARACTERIZACAO=1 pytest tests/test_caracterizacao_despachos.py`
regrava o arquivo esperado (só quando a mudança de texto for intencional).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gclaude_indexer import conversion, light_formats
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.file_types import category_of_extension

AMOSTRAS = Path(__file__).parent / "fixtures" / "despachos"
ESPERADO = AMOSTRAS / "esperado.json"
TIPOS_DO_ASSINADO = {"text", "docx", "xlsx", "pptx", "odf", "rtf", "xls"}


def _config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(name="t", source_folder=str(tmp_path), output_folder=str(tmp_path), ocr_language="")


def _textos(tmp_path: Path) -> dict:
    config = _config(tmp_path)
    resultado = {}
    for amostra in sorted(AMOSTRAS.iterdir()):
        if amostra.name == ESPERADO.name:
            continue
        dados = amostra.read_bytes()
        extensao = amostra.suffix.lower().lstrip(".")
        categoria = category_of_extension("." + extensao)
        tipo = light_formats.sniff_content_type(dados)
        linha = {"categoria": categoria, "tipo": tipo}
        if categoria in conversion._TEXT_CATEGORIES:
            linha["acervo"] = conversion._extract_light_text(categoria, extensao, amostra)
        linha["anexo"] = conversion._extract_attachment_text(amostra, config)
        if tipo in TIPOS_DO_ASSINADO:
            linha["assinado"] = list(conversion._signed_content_text(tipo, dados, config))
        resultado[amostra.name] = linha
    return resultado


def test_texto_por_tipo_nos_tres_despachos(tmp_path):
    atual = _textos(tmp_path)
    if os.environ.get("GERAR_CARACTERIZACAO"):
        ESPERADO.write_text(json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip("arquivo esperado regravado")
    esperado = json.loads(ESPERADO.read_text(encoding="utf-8"))
    assert set(atual) == set(esperado)
    for nome in esperado:
        assert atual[nome] == esperado[nome], nome

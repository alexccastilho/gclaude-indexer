# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 20: o que uma corrida real perdia em silêncio.

Três defeitos observados numa indexação de 2904 páginas com
`qwen3.5:4b` (15/09/2026), todos na etapa 6:

1. O modelo devolve a data de competência que o documento traz
   ("competência 01/2020") como `2020-01`. A validação exigia
   `AAAA-MM-DD` estrito e a peça INTEIRA era descartada — resumo, tipo,
   autor e tudo — por causa de um campo opcional. Foram 20 peças.

2. A garantia de cobertura rodava ANTES da validação, então as páginas
   cobertas só por uma peça descartada ficavam fora do índice. Numa
   ferramenta cujo propósito é dizer em que página está a informação,
   essa é a falha que não pode existir.

3. O contexto do Ollama era medido na primeira janela e congelado para a
   corrida inteira. Janelas mais densas que a primeira estouravam o
   limite, o JSON voltava truncado e o parser recebia zero linhas — 72
   das 484 janelas entraram no índice sem classificação nenhuma.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from gclaude_indexer import gpu_budget
from gclaude_indexer.classification import (
    ClassifiedItem,
    item_to_dict,
    normalize_date,
    validate_item,
)
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.engine_local import LocalEngine, classify_pending
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows


# --- 1. datas de precisão reduzida -----------------------------------------


def test_data_de_competencia_sem_dia_e_preservada():
    """`2020-01` é o que o documento diz. Inventar o dia 1 seria afirmar
    um fato que ele não traz; descartar a peça perderia o resto."""
    assert normalize_date("2020-01") == "2020-01"


def test_data_so_com_ano_e_preservada():
    assert normalize_date("2026") == "2026"


def test_data_completa_e_valida_segue_intacta():
    assert normalize_date("2024-05-15") == "2024-05-15"


def test_dia_que_nao_existe_no_calendario_cai_para_o_mes():
    """`2021-09-31` veio de uma leitura errada do dia. O mês continua
    confiável, e é o que sobra."""
    assert normalize_date("2021-09-31") == "2021-09"


def test_mes_que_nao_existe_cai_para_o_ano():
    assert normalize_date("2021-13") == "2021"


def test_intervalo_de_datas_nao_vira_data():
    assert normalize_date("2021-07-14 a 2021-07-15") is None


def test_data_em_formato_brasileiro_nao_vira_data():
    assert normalize_date("15/05/2024") is None


def test_ausencia_de_data_continua_ausente():
    assert normalize_date(None) is None
    assert normalize_date("") is None


def _peca_bruta(**campos):
    peca = {
        "group": "volume_1", "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": None,
        "date": None, "author": None, "summary": None,
        "has_table": False, "has_image": False, "engine": "local",
        "confidence": "high", "files": "a.pdf",
    }
    peca.update(campos)
    return peca


def test_validar_peca_aceita_data_de_competencia():
    assert validate_item(_peca_bruta(date="2020-01")) == []


def test_validar_peca_aceita_data_so_com_ano():
    assert validate_item(_peca_bruta(date="2026")) == []


def test_validar_peca_ainda_rejeita_data_que_nao_e_data():
    """A validação continua sendo rede de segurança: afrouxar a precisão
    não é aceitar qualquer texto no campo."""
    assert validate_item(_peca_bruta(date="15/05/2024")) != []


def test_validar_peca_ainda_rejeita_dia_inexistente():
    assert validate_item(_peca_bruta(date="2021-09-31")) != []


def _peca_classificada(date):
    return ClassifiedItem(
        start_ref="f. 1", end_ref="f. 1", start_order=1, end_order=1,
        type="OFÍCIO", date=date, author=None, summary="resumo",
        has_table=False, has_image=False, engine="local",
        confidence="high", files=["a.pdf"],
    )


def test_item_to_dict_normaliza_a_data_antes_da_validacao():
    """O ponto por onde todo motor passa. Depois daqui, nenhuma peça é
    descartada por causa da precisão da data."""
    peca = item_to_dict(_peca_classificada("2021-09-31"), "volume_1::000001-000001", "volume_1")

    assert peca["date"] == "2021-09"
    assert validate_item(peca) == []


def test_item_to_dict_descarta_so_o_campo_quando_a_data_e_lixo():
    peca = item_to_dict(_peca_classificada("2021-07-14 a 2021-07-15"), "v::000001-000001", "v")

    assert peca["date"] is None
    assert peca["summary"] == "resumo"
    assert validate_item(peca) == []


# --- 2. cobertura garantida depois da validação ----------------------------


def _pdf(caminho, paginas_textos):
    documento = fitz.open()
    for texto in paginas_textos:
        pagina = documento.new_page()
        pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


TEXTO_DE_PAGINA = (
    "Texto solto de teste, longo o bastante para não acionar OCR, sem "
    "nenhum marcador de tipo reconhecível nesta página específica aqui."
)


def _projeto_pronto_para_classificar(tmp_path, paginas_textos, **extra_config):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"
    _pdf(origem / "volume_1" / "peca.pdf", paginas_textos)

    dados = {"name": "Fase 20", "source_folder": str(origem), "output_folder": str(saida)}
    dados.update(extra_config)
    config = load_config(dados)

    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    return config, conn


def test_pagina_de_peca_descartada_nao_fica_fora_do_indice(tmp_path, monkeypatch):
    """O requisito central: uma página fora do índice é informação que
    ninguém mais encontra. Uma peça recusada na validação não pode levar
    as páginas dela junto."""
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_DE_PAGINA, TEXTO_DE_PAGINA])
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    invalida = ClassifiedItem(
        start_ref="f. 1", end_ref="f. 2", start_order=1, end_order=2,
        type="OFÍCIO", date=None, author=None, summary="resumo",
        has_table=False, has_image=False, engine="local",
        confidence="certeza_absoluta",  # valor que a validação recusa
        files=["peca.pdf"],
    )
    monkeypatch.setattr(LocalEngine, "is_available", lambda self: True)
    monkeypatch.setattr(LocalEngine, "classify", lambda self, pages: [invalida])

    resultado = classify_pending(conn, config, local_engine=motor)

    assert resultado.invalid_items == 1

    linhas = (Path(config.output_folder) / "raw_items.jsonl").read_text(encoding="utf-8").splitlines()
    cobertas = set()
    for linha in linhas:
        peca = json.loads(linha)
        cobertas.update(range(peca["order_start"], peca["order_end"] + 1))

    assert cobertas == {1, 2}
    conn.close()


# --- 3. contexto medido por janela, não só na primeira ---------------------


def _plan_fixo(monkeypatch, camadas=33):
    monkeypatch.setattr(
        gpu_budget, "plan", lambda modelo, url, contexto: (camadas, {"layers": camadas})
    )


def test_janela_mais_densa_que_a_primeira_amplia_o_contexto(monkeypatch):
    """O defeito que deixou 72 janelas sem classificação: o contexto saía
    da primeira janela e nunca mais crescia, então a resposta das janelas
    densas voltava truncada e o JSON não fechava."""
    _plan_fixo(monkeypatch)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    motor.plan_gpu_use("x" * 3000, page_count=8)
    curto = motor.num_ctx

    motor.plan_gpu_use("x" * 60000, page_count=8)

    assert motor.num_ctx > curto


def test_janela_mais_curta_nao_encolhe_o_contexto(monkeypatch):
    """Um `num_ctx` que oscila faz o Ollama recarregar o modelo a cada
    janela. Ele só cresce."""
    _plan_fixo(monkeypatch)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    motor.plan_gpu_use("x" * 60000, page_count=8)
    largo = motor.num_ctx

    motor.plan_gpu_use("x" * 100, page_count=8)

    assert motor.num_ctx == largo


def test_modo_cpu_continua_sem_planejar_nada(monkeypatch):
    """`num_gpu=0` é o usuário pedindo a CPU de propósito, e nenhuma
    medição passa por cima disso."""
    _plan_fixo(monkeypatch)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9", num_gpu=0)

    motor.plan_gpu_use("x" * 60000, page_count=8)

    assert motor.num_gpu == 0

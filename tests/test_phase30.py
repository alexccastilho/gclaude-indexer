# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.5.17: o que a importação de um acervo grande, com muitos atos do
Planalto, mostrou.

- muitos atos do Planalto sem autor: a assinatura fica depois do corte da
  página, e os atos do Congresso não têm o fecho do Presidente;
- o mesmo presidente escrito de três jeitos e centenas de tipos de documento, muitos
  só sem acento ("INDICE" ao lado de "ÍNDICE");
- o resumo do hardware repetido a cada etapa no log.
"""

from __future__ import annotations

from gclaude_indexer import hardware, planalto
from gclaude_indexer.engine_rules import classify_pending as classify_rules
from gclaude_indexer.fulltext import index_pending
from gclaude_indexer.import_items import import_and_consolidate
from gclaude_indexer.item_normalize import BLANK_PAGE_TYPE, normalize_types
from gclaude_indexer.windows_prep import prepare_windows

from .test_busca_texto_completo import _extrair, _projeto


def test_nome_do_presidente_tem_uma_grafia_so():
    assert planalto.person_name("ERNESTO GEISEL") == "Ernesto Geisel"
    assert planalto.person_name("ernesto  geisel") == "Ernesto Geisel"
    assert planalto.person_name("LUIZ INÁCIO LULA DA SILVA") == "Luiz Inácio Lula da Silva"
    assert planalto.person_name("Senador RENAN CALHEIROS") == "Senador Renan Calheiros"
    assert planalto.person_name("D. PEDRO II") == "D. Pedro II"


def test_autor_pela_assinatura_e_pelo_orgao():
    lei = "Art. 2º Revoga-se.\nBrasília, 21 de dezembro de 2022; 201º da Independência e 134º da República.\nLUIZ INÁCIO LULA DA SILVA\nFernando Haddad\nEste texto não substitui o publicado"
    assert planalto.find_author(lei, "LEI") == "Luiz Inácio Lula da Silva"

    congresso = "Art. 3º Entra em vigor.\nCongresso Nacional, em 21 de junho de 2005\nSenador RENAN CALHEIROS\nPresidente"
    assert planalto.find_author(congresso, "DECRETO LEGISLATIVO") == "Senador Renan Calheiros"

    republica_velha = "Art. 4º Revogam-se.\nCapital Federal, 8 de agosto de 1891, 3º da Republica.\nMANOEL DEODORO DA FONSECA.\nT. de Alencar Araripe."
    assert planalto.find_author(republica_velha, "LEI") == "Manoel Deodoro da Fonseca"

    # Emenda: assinada pelas duas Mesas, uma dúzia de nomes.
    assert planalto.find_author("…\nSenador IRAJÁ\n1º Secretário", "EMENDA CONSTITUCIONAL") == (
        "Mesas da Câmara dos Deputados e do Senado Federal"
    )
    # Ato da Mesa cortado antes da assinatura: o órgão.
    assert planalto.find_author("O PRESIDENTE DA MESA DO CONGRESSO NACIONAL, cumprindo…",
                                "ATO DO PRESIDENTE DA MESA DO CONGRESSO NACIONAL") == (
        "Presidente da Mesa do Congresso Nacional"
    )
    # Lei cortada antes do fecho: nada a inventar.
    assert planalto.find_author("Art. 1º Fica criado…", "LEI") is None


def test_tipos_com_e_sem_acento_viram_um_nome():
    pecas = (
        [{"type": "INDICE"}] * 92 + [{"type": "ÍNDICE"}] * 84
        + [{"type": "TEORIA"}] * 91 + [{"type": "TEÓRIA"}] * 30
        + [{"type": "Lei Federal"}, {"type": "LEI"}]
        + [{"type": None, "summary": "Página em branco: sem texto legível."}, {"type": None, "summary": "Outra coisa"}]
    )
    pecas = [dict(p) for p in pecas]
    normalize_types(pecas)
    tipos = {p["type"] for p in pecas}
    assert "ÍNDICE" in tipos and "INDICE" not in tipos
    assert "TEORIA" in tipos and "TEÓRIA" not in tipos
    assert "LEI FEDERAL" in tipos and "LEI" in tipos  # nomes diferentes nunca se juntam
    assert pecas[-2]["type"] == BLANK_PAGE_TYPE
    assert pecas[-1]["type"] is None


def _lei_longa() -> str:
    artigos = "".join(
        f"<p>Art. {n}º " + f"Disposição número {n} sobre a matéria regulada. " * 20 + "</p>"
        for n in range(1, 30)
    )
    return (
        "<html><body><p>Presidência da República</p><p>LEI Nº 9.999, DE 1º DE JANEIRO DE 2020.</p>"
        "<p>Dispõe sobre a matéria regulada.</p>"
        "<p>O PRESIDENTE DA REPÚBLICA Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:</p>"
        f"{artigos}"
        "<p>Brasília, 1º de janeiro de 2020; 199º da Independência e 132º da República.</p>"
        "<p>JAIR MESSIAS BOLSONARO</p><p>Este texto não substitui o publicado no DOU de 2.1.2020</p>"
        "</body></html>"
    )


def test_importacao_acha_a_assinatura_depois_do_corte_da_pagina(tmp_path):
    origem, config, conn = _projeto(tmp_path, chars_per_page=2000)
    (origem / "l9999.htm").write_text(_lei_longa(), encoding="utf-8")
    _extrair(conn, config)
    index_pending(conn, config)
    prepare_windows(conn, config)
    classify_rules(conn, config)

    pagina = conn.execute("SELECT text FROM page").fetchone()[0]
    assert "BOLSONARO" not in pagina  # a assinatura ficou depois do corte

    import_and_consolidate(conn, config)
    lei = conn.execute("SELECT type, author, engine FROM item WHERE type = 'LEI'").fetchone()
    assert lei is not None and lei["engine"] == "structured"
    assert lei["author"] == "Jair Messias Bolsonaro"
    conn.close()


def test_resumo_do_hardware_nao_se_repete_a_cada_etapa(tmp_path):
    _, _config, conn = _projeto(tmp_path)
    hardware.diagnose(conn, space_folder=tmp_path)
    hardware.diagnose(conn, space_folder=tmp_path)
    hardware.diagnose(conn, space_folder=tmp_path)
    vezes = conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.hardware.diagnose'"
    ).fetchone()[0]
    assert vezes == 1

    # Passado o intervalo, o resumo volta ao log (uma nova execução).
    conn.execute("UPDATE event SET created_at = '2000-01-01T00:00:00' WHERE message_key = 'log.hardware.diagnose'")
    conn.commit()
    hardware.diagnose(conn, space_folder=tmp_path)
    vezes = conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.hardware.diagnose'"
    ).fetchone()[0]
    assert vezes == 2
    conn.close()


# --- 1.5.18: a trava é solta quando ninguém usa o projeto ------------------------


def _gerente(tmp_path, ocupado=lambda _pasta: False):
    from gclaude_indexer.lock import LOCK_FILE_NAME, LockManager

    pasta = tmp_path / "saida"
    pasta.mkdir()
    gerente = LockManager(heartbeat_interval_s=3600, idle_release_s=0.05, keep_alive=ocupado)
    gerente.open(pasta)
    return gerente, pasta, pasta / LOCK_FILE_NAME


def test_trava_e_solta_quando_o_navegador_fecha(tmp_path):
    """Navegador fechado, servidor ainda no ar: a outra máquina via "em uso,
    última atividade há 1 minuto" para sempre."""
    import time

    gerente, pasta, arquivo = _gerente(tmp_path)
    gerente.heartbeat()
    assert arquivo.exists()  # usado agora há pouco

    time.sleep(0.1)
    gerente.heartbeat()
    assert not arquivo.exists()
    assert not gerente.is_open(pasta)


def test_tela_aberta_ou_pedido_em_andamento_seguram_a_trava(tmp_path):
    import time

    gerente, pasta, arquivo = _gerente(tmp_path)
    time.sleep(0.1)
    gerente.touch(pasta)  # a tela avisou que continua aberta
    gerente.heartbeat()
    assert arquivo.exists()

    gerente.begin_use(pasta)  # uma importação de vários minutos
    time.sleep(0.1)
    gerente.heartbeat()
    assert arquivo.exists()
    gerente.end_use(pasta)
    time.sleep(0.1)
    gerente.heartbeat()
    assert not arquivo.exists()


def test_etapa_rodando_sem_tela_aberta_segura_a_trava(tmp_path):
    import time

    rodando = {"sim": True}
    gerente, _pasta, arquivo = _gerente(tmp_path, ocupado=lambda _p: rodando["sim"])
    time.sleep(0.1)
    gerente.heartbeat()
    assert arquivo.exists()  # classificação de madrugada, navegador fechado

    rodando["sim"] = False
    gerente.heartbeat()
    assert not arquivo.exists()


def test_tela_avisa_que_continua_aberta(tmp_path):
    from fastapi.testclient import TestClient

    from gclaude_indexer.web import app as aplicacao

    cliente = TestClient(aplicacao.app)
    resposta = cliente.post("/projects/999999/alive")
    assert resposta.status_code == 204


# --- 1.5.19: o idioma do OCR sem administrador -----------------------------------


def _tesseract_falso(tmp_path, idiomas):
    pasta = tmp_path / "Tesseract-OCR"
    (pasta / "tessdata").mkdir(parents=True)
    exe = pasta / "tesseract.exe"
    exe.write_bytes(b"")
    for idioma in idiomas:
        (pasta / "tessdata" / f"{idioma}.traineddata").write_bytes(idioma.encode())
    return str(exe)


def test_idioma_que_falta_vai_para_a_pasta_da_maquina(tmp_path, monkeypatch):
    """Numa instalação, a cópia para Program Files pedia administrador e
    não aconteceu; o idioma obrigatório ficou faltando."""
    import os

    from gclaude_indexer import ocr_languages

    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)  # máquina limpa, como a de casa
    exe = _tesseract_falso(tmp_path, ["eng", "osd"])

    def _baixa(idioma, destino):
        destino.write_bytes(b"baixado")
        return True

    monkeypatch.setattr(ocr_languages, "_download", _baixa)
    assert ocr_languages.ensure("por", exe) == []
    privada = tmp_path / "local" / "tessdata"
    assert os.environ["TESSDATA_PREFIX"] == str(privada)
    # O que o Tesseract já sabia veio junto: apontar para cá não o faz esquecer o inglês.
    assert {p.name for p in privada.glob("*.traineddata")} >= {"por.traineddata", "eng.traineddata", "osd.traineddata"}


def test_tesseract_que_ja_tem_o_idioma_fica_como_esta(tmp_path, monkeypatch):
    import os

    from gclaude_indexer import ocr_languages

    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)  # máquina limpa, como a de casa
    exe = _tesseract_falso(tmp_path, ["eng", "por"])
    # Fase 34: "pronta" exige também `configs/` (toda instalação real os tem).
    from tests.test_phase34 import _com_configs

    _com_configs(exe)
    assert ocr_languages.ensure("por", exe) == []
    assert "TESSDATA_PREFIX" not in os.environ
    assert not (tmp_path / "local" / "tessdata").exists()


def test_sem_internet_o_idioma_continua_faltando(tmp_path, monkeypatch):
    import os

    from gclaude_indexer import ocr_languages

    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)  # máquina limpa, como a de casa
    exe = _tesseract_falso(tmp_path, ["eng"])
    assert ocr_languages.ensure("por+eng", exe) == ["por"]
    assert "TESSDATA_PREFIX" not in os.environ  # nunca aponta para uma pasta incompleta

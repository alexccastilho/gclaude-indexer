# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Tarefa 12 (2.0.0): qualquer idioma — escrita e idioma por documento, OCR
no idioma certo, tipo e resumo no idioma do documento e busca em escritas
sem espaço."""

import hashlib
import os
import shutil
from dataclasses import replace

import fitz
import pytest
from PIL import Image

from gclaude_indexer import conversion, language_detect, ocr_detection, ocr_languages, tools
from gclaude_indexer.classification import WindowPage
from gclaude_indexer.conversion import convert, ocr_retry_count
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.scanning import scan

from .test_componentes import _componente, _manifesto, _servidor
from .test_phase3 import _preparar_projeto
from .test_phase30 import _tesseract_falso

# Capturados antes do conftest trocá-los (downloads e modelos presentes).
_DOWNLOAD_DE_VERDADE = ocr_languages._download
_PRESENTES_DE_VERDADE = ocr_languages.present_models

ALEMAO = (
    "Der Vertrag wurde heute von beiden Parteien unterzeichnet und tritt sofort in Kraft. "
    "Die Vergütung beträgt monatlich zweitausend Euro und wird am Ende jedes Monats gezahlt. "
)
RUSSO = (
    "Правительство сегодня приняло решение об изменении закона о государственной службе. "
    "Договор вступает в силу с момента его подписания обеими сторонами. "
)
ARABE = "قررت الحكومة اليوم تعديل القانون المتعلق بالخدمة العامة والإدارة في البلاد وفقا للدستور."
JAPONES = "今日は良い天気ですね。私は学校に行きます。東京都の会議で新しい法律について話し合いました。"
CHINES = "我们今天去学校学习中文，天气很好。政府今天决定修改关于公共服务的法律。这个文件说明了会议的主要内容。"
CHINES_TRADICIONAL = "我們今天去學校學習中文，天氣很好。政府今天決定修改關於公共服務的法律。這個文件說明了會議的主要內容。"
COREANO = "오늘 날씨가 좋네요. 학교에 갑니다. 정부는 오늘 공공 서비스에 관한 법률을 개정하기로 결정했습니다."


# --- escrita e idioma -------------------------------------------------------------


def test_escrita_pelos_blocos_unicode():
    assert language_detect.script_of("a") == "latin"
    assert language_detect.script_of("ж") == "cyrillic"
    assert language_detect.script_of("λ") == "greek"
    assert language_detect.script_of("ب") == "arabic"
    assert language_detect.script_of("ש") == "hebrew"
    assert language_detect.script_of("中") == "han"
    assert language_detect.script_of("の") == "kana"
    assert language_detect.script_of("カ") == "kana"
    assert language_detect.script_of("한") == "hangul"
    assert language_detect.script_of("क") == "devanagari"
    assert language_detect.script_of("ก") == "thai"
    assert language_detect.script_of("7") is None and language_detect.script_of("。") is None
    assert language_detect.dominant_script(RUSSO) == "cyrillic"
    # Japonês tem mais kanji que kana com frequência e continua japonês.
    assert language_detect.dominant_script(JAPONES) == "kana"
    assert language_detect.dominant_script(CHINES) == "han"
    assert language_detect.is_unspaced(CHINES) and language_detect.is_unspaced("ภาษาไทยไม่มีช่องว่าง")
    assert not language_detect.is_unspaced(ALEMAO)
    assert language_detect.collapse_unspaced_spaces("东京 都 Tokyo 大学") == "东京都 Tokyo 大学"


def test_chines_e_japones_e_coreano_pela_escrita():
    assert language_detect.detect_languages(JAPONES) == ["ja"]
    assert language_detect.detect_languages(CHINES) == ["zh"]
    assert language_detect.detect_languages(COREANO) == ["ko"]
    assert language_detect.tesseract_languages(["ja"], JAPONES) == ["jpn"]
    assert language_detect.tesseract_languages(["zh"], CHINES) == ["chi_sim"]
    assert language_detect.tesseract_languages(["zh"], CHINES_TRADICIONAL) == ["chi_tra"]
    # Han sem pista de qual forma: as duas.
    assert language_detect.tesseract_languages(["zh"], "中文法律文件") == ["chi_sim", "chi_tra"]
    assert language_detect.tesseract_languages(["ko"], COREANO) == ["kor"]


@pytest.mark.parametrize("texto, iso, modelo", [
    (ALEMAO, "de", "deu"), (RUSSO, "ru", "rus"), (ARABE, "ar", "ara"),
])
def test_alemao_russo_e_arabe_detectados_no_texto_nativo(texto, iso, modelo):
    assert language_detect.detect_languages(texto) == [iso]
    assert language_detect.tesseract_languages([iso], texto) == [modelo]


def test_texto_com_dois_idiomas_e_texto_curto():
    misto = (ALEMAO + "\n") * 3 + ("This agreement is governed by the laws of the State of New York.\n") * 2
    assert language_detect.detect_languages(misto) == ["de", "en"]
    assert language_detect.detect_languages("Assinatura") == []
    idiomas, maioria = language_detect.majority_language([ALEMAO, ALEMAO, "O contrato de prestação de serviços foi assinado hoje pelas duas partes."])
    assert maioria == "de" and "pt" in idiomas


def test_idioma_sem_modelo_no_tesseract_cai_no_modelo_da_escrita():
    assert language_detect.tesseract_languages(["xx"], RUSSO) == ["script/Cyrillic"]
    assert language_detect.tesseract_languages(["xx"], "texto latino qualquer") == ["script/Latin"]
    assert language_detect.model_script("rus") == "cyrillic"
    assert language_detect.model_script("chi_tra") == "han"
    assert language_detect.model_script("script/Japanese") == "kana"
    assert language_detect.model_script("por") == "latin"


def test_todo_modelo_da_tabela_esta_no_manifesto():
    """Sem rede: o manifesto local fixado (Tarefa 7) tem cada modelo para
    o qual a detecção pode mandar o OCR."""
    for modelo in set(language_detect.TESSERACT_CODES.values()):
        assert ocr_languages.downloadable(modelo), modelo
    for escrita in language_detect.SCRIPT_MODELS:
        assert ocr_languages.downloadable(language_detect.script_model(escrita)), escrita
    assert ocr_languages.downloadable("osd")


def test_nomes_que_o_osd_da_viram_escritas():
    assert language_detect.script_from_osd("Latin") == "latin"
    assert language_detect.script_from_osd("Han") == "han"
    assert language_detect.script_from_osd("Japanese") == "kana"
    assert language_detect.script_from_osd("Korean") == "hangul"
    assert language_detect.script_from_osd("Cyrillic") == "cyrillic"
    assert language_detect.script_from_osd("Klingon") is None


def test_plano_de_idiomas_por_grupo_de_paginas():
    plano = ocr_detection.format_plan([([1, 2, 3, 7], ["chi_sim", "eng"]), ([4, 5, 6], ["deu"])])
    assert plano == "1-3,7:chi_sim+eng|4-6:deu"
    assert ocr_detection.parse_plan(plano) == [([1, 2, 3, 7], ["chi_sim", "eng"]), ([4, 5, 6], ["deu"])]
    assert ocr_detection.parse_plan("deu+eng") == [(None, ["deu", "eng"])]
    assert ocr_detection.plan_models(plano) == ["chi_sim", "eng", "deu"]
    assert ocr_detection.restrict_plan(plano, {"eng", "deu"}) == ("1-3,7:eng|4-6:deu", True)
    assert ocr_detection.restrict_plan("deu+eng", {"deu", "eng"}) == ("deu+eng", False)
    assert ocr_detection.group_pages([1, 2, 3, 4], {1: "latin", 4: "cyrillic"}) == {
        "latin": [1, 2], "cyrillic": [3, 4],
    }


# --- conversão --------------------------------------------------------------------


def _pdf(caminho, paginas):
    """Cada item de `paginas`: um texto (página nativa) ou `None` (página
    escaneada: só uma imagem)."""
    documento = fitz.open()
    imagem = caminho.with_suffix(".png")
    Image.new("RGB", (600, 200), "white").save(imagem)
    for texto in paginas:
        pagina = documento.new_page(width=600, height=800)
        if texto is None:
            pagina.insert_image(fitz.Rect(0, 0, 600, 200), filename=str(imagem))
        else:
            pagina.insert_textbox(fitz.Rect(40, 40, 560, 760), texto, fontsize=10)
    documento.save(caminho)
    documento.close()
    imagem.unlink()


class _OcrFalso:
    """Troca o `ocrmypdf`: anota cada chamada e copia a entrada para a saída."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, origem, destino, idiomas, jobs=1, pages=None, **outros):
        self.chamadas.append({"origem": origem, "destino": destino, "idiomas": idiomas, "paginas": pages, **outros})
        shutil.copyfile(origem, destino)


def _projeto(tmp_path):
    origem, saida, config, conn = _preparar_projeto(tmp_path)
    return origem, saida, replace(config, parallelism="economy"), conn


def _linha(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


def test_pdf_nativo_em_alemao_com_pagina_escaneada_e_lido_em_alemao(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    _pdf(origem / "vertrag.pdf", [ALEMAO * 3, None])
    scan(conn, config)
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    ocr = _OcrFalso()
    monkeypatch.setattr(conversion, "_run_ocrmypdf", ocr)

    assert convert(conn, config, language="pt-BR").failed == 0

    assert [(c["paginas"], c["idiomas"]) for c in ocr.chamadas] == [([2], "deu")]
    linha = _linha(conn, "vertrag.pdf")
    assert (linha["ocr_lang"], linha["language"], linha["ocr_failed"]) == ("deu", "de", 0)
    eventos = [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]
    assert any("Idioma detectado antes do OCR em 1 arquivo(s): de (1)" in m for m in eventos), eventos


def test_pdf_com_duas_escritas_roda_o_ocr_por_grupo_de_paginas(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    _pdf(origem / "misto.pdf", [None, None, None])
    scan(conn, config)
    presentes = frozenset({"osd", "eng", "rus", "deu", "por"})
    monkeypatch.setattr(ocr_languages, "present_models", lambda _exe: presentes)
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    escritas = iter([("cyrillic", 0), ("cyrillic", 0), ("latin", 0)])
    monkeypatch.setattr(ocr_detection, "osd_image", lambda _imagem: next(escritas))
    amostras = []

    def _amostra(_imagem, modelo):
        amostras.append(modelo)
        return RUSSO if modelo == "rus" else ALEMAO

    monkeypatch.setattr(ocr_detection, "ocr_sample", _amostra)
    ocr = _OcrFalso()
    monkeypatch.setattr(conversion, "_run_ocrmypdf", ocr)

    assert convert(conn, config, language="pt-BR").failed == 0

    # A amostra latina sai do inglês que já está aqui (não do script/Latin, de 89 MB).
    assert sorted(set(amostras)) == ["eng", "rus"]
    assert [(c["paginas"], c["idiomas"]) for c in ocr.chamadas] == [([1, 2], "rus"), ([3], "deu")]
    # Encadeado: a segunda passada lê a saída da primeira, e a parte some.
    assert ocr.chamadas[1]["origem"] == ocr.chamadas[0]["destino"]
    assert not ocr.chamadas[0]["destino"].exists()
    # Com o OSD presente, as páginas são endireitadas pelo ocrmypdf.
    assert all(c.get("rotate") for c in ocr.chamadas)
    linha = _linha(conn, "misto.pdf")
    assert linha["ocr_lang"] == "1-2:rus|3:deu" and linha["language"] == "ru,de"
    assert (linha["needs_ocr"], linha["ocr_failed"]) == (1, 0)


def test_amostra_de_han_pelo_ocr_nao_decide_entre_simplificado_e_tradicional():
    from gclaude_indexer.conversion import _decide_plan

    amostra = {"ocr_pages": [1], "scripts": {1: "han"}, "samples": {"han": CHINES}}
    assert _decide_plan(amostra, lambda: "por") == ("chi_sim+chi_tra", ["zh"], False)
    # Texto nativo diz: simplificado.
    assert _decide_plan({"native": CHINES * 3}, lambda: "por")[0] == "chi_sim"
    # Escrita vista sem modelo para a amostra: indisponível, e o modelo da escrita
    # (o português do projeto não lê cirílico).
    assert _decide_plan({"ocr_pages": [1], "scripts": {1: "cyrillic"}, "samples": {}}, lambda: "por") == (
        "script/Cyrillic", [], True,
    )


def test_deteccao_no_trabalhador_le_ja_no_idioma_do_texto():
    from gclaude_indexer.conversion import _detect_in_worker, _resolve_language

    usaveis = ["por", "eng", "deu", "jpn", "chi_sim", "chi_tra", "script/Cyrillic"]
    notas: dict = {}
    assert _detect_in_worker(ALEMAO * 3, "por", False, usaveis, notas) == ("deu", False)
    assert (notas["ocr_lang"], notas["language"]) == ("deu", "de")
    assert _detect_in_worker(JAPONES * 5, "por", False, usaveis, {}) == ("jpn", False)
    # Tradicional decidido pela mesma amostra nos dois processos.
    notas = {}
    assert _detect_in_worker(CHINES_TRADICIONAL * 3, "por", False, usaveis, notas) == ("chi_tra", False)
    assert _resolve_language({"language_sample": notas["language_sample"], "ocr_used": "chi_tra",
                              "ocr_applied": True}) == (("chi_tra", "zh"), False)
    # Russo sem o `rus`: o modelo da escrita lê por ora e o arquivo volta marcado.
    notas = {}
    assert _detect_in_worker(RUSSO * 3, "por", False, usaveis, notas) == ("script/Cyrillic", True)
    assert notas["ocr_lang"] == "rus"
    # Pouco texto nativo: fica o plano que veio.
    assert _detect_in_worker("Seite 1", "por", False, usaveis, {}) == ("por", False)


def test_conferencia_no_principal_so_manda_refazer_o_que_nao_foi_lido_no_idioma():
    from gclaude_indexer.conversion import _resolve_language

    info = {"language_sample": ALEMAO * 3, "ocr_used": "deu", "ocr_applied": True}
    assert _resolve_language(info) == (("deu", "de"), False)
    assert _resolve_language({**info, "ocr_used": "deu+eng"}) == (("deu", "de"), False)
    # O modelo da escrita no lugar do idioma (que faltava) conta como lido.
    assert _resolve_language({**info, "ocr_used": "script/Latin"}) == (("deu", "de"), False)
    russo = {"language_sample": RUSSO * 3, "ocr_used": "script/Cyrillic", "ocr_applied": True}
    assert _resolve_language(russo) == (("rus", "ru"), False)
    # Lido com outro idioma: refazer.
    assert _resolve_language({**info, "ocr_used": "por"}) == (("deu", "de"), True)
    assert _resolve_language({**info, "ocr_used": "por", "ocr_applied": False}) == (("deu", "de"), False)


def _sem_py3langid_nos_trabalhadores(monkeypatch, carregados):
    """Troca `_process_file` (o que roda no processo do conjunto) por um que
    anota se o `py3langid` foi pedido lá dentro."""
    original = conversion._process_file
    modelo = language_detect._model

    def _no_trabalhador(config, row, jobs):
        def _anota():
            carregados.append(row["name"])
            return modelo()

        with monkeypatch.context() as dentro:
            dentro.setattr(language_detect, "_model", _anota)
            return original(config, row, jobs)

    monkeypatch.setattr(conversion, "_process_file", _no_trabalhador)


def test_formato_que_vira_pdf_na_conversao_e_lido_no_idioma_do_texto_numa_passada(tmp_path, monkeypatch):
    """Um `.epub` (paginados) só vira PDF no trabalhador: o idioma sai lá,
    do texto nativo, e as páginas escaneadas já são lidas em alemão."""
    from gclaude_indexer import light_formats

    origem, _saida, config, conn = _projeto(tmp_path)
    _pdf(tmp_path / "livro.pdf", [ALEMAO * 3, None])
    conteudo = (tmp_path / "livro.pdf").read_bytes()
    (origem / "buch.epub").write_bytes(b"epub de teste")
    scan(conn, config)
    monkeypatch.setattr(light_formats, "convert_to_pdf_bytes", lambda _caminho: conteudo)
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    ocr = _OcrFalso()
    monkeypatch.setattr(conversion, "_run_ocrmypdf", ocr)
    carregados: list = []
    _sem_py3langid_nos_trabalhadores(monkeypatch, carregados)

    assert convert(conn, config, language="pt-BR").failed == 0
    assert [(c["paginas"], c["idiomas"]) for c in ocr.chamadas] == [([2], "deu")]
    linha = _linha(conn, "buch.epub")
    assert (linha["ocr_lang"], linha["language"], linha["ocr_failed"]) == ("deu", "de", 0)
    assert set(carregados) == {"buch.epub"}  # só por este caminho

    # Nada volta à fila.
    assert ocr_retry_count(conn) == 0


def test_pdf_e_imagem_nunca_carregam_o_py3langid_no_trabalhador(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    _pdf(origem / "vertrag.pdf", [ALEMAO * 3, None])
    Image.new("RGB", (300, 100), "white").save(origem / "foto.png")
    scan(conn, config)
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    monkeypatch.setattr(conversion, "_run_ocrmypdf", _OcrFalso())
    monkeypatch.setattr(conversion, "_extract_text_image", lambda _p, lang, rotate=0: "")
    carregados: list = []
    _sem_py3langid_nos_trabalhadores(monkeypatch, carregados)

    assert convert(conn, config, language="pt-BR").failed == 0
    assert carregados == []
    assert _linha(conn, "vertrag.pdf")["ocr_lang"] == "deu"  # decidido no processo principal


def test_pdf_todo_nativo_nao_pede_idioma_de_ocr(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    _pdf(origem / "nativo.pdf", [ALEMAO * 3, ALEMAO * 3])
    scan(conn, config)
    pedidos = []
    monkeypatch.setattr(ocr_languages, "ensure", lambda lang, _exe, download=True: pedidos.append(lang) or [])

    def _sem_reserva(*_a, **_k):
        raise AssertionError("PDF sem página a ler não precisa de plano de OCR")

    monkeypatch.setattr(conversion, "_fallback_plan", _sem_reserva)
    monkeypatch.setattr(conversion, "_run_ocrmypdf", _OcrFalso())

    assert convert(conn, config, language="pt-BR").failed == 0
    assert all("deu" not in pedido for pedido in pedidos), pedidos


def test_imagem_de_lado_e_endireitada_e_lida_no_idioma_da_amostra(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    Image.new("RGB", (300, 100), "white").save(origem / "foto.png")
    scan(conn, config)
    monkeypatch.setattr(ocr_languages, "present_models", lambda _exe: frozenset({"osd", "eng", "rus"}))
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    monkeypatch.setattr(ocr_detection, "osd_image", lambda _imagem: ("cyrillic", 90))
    monkeypatch.setattr(ocr_detection, "ocr_sample", lambda _imagem, _modelo: RUSSO)
    pedidos = []
    monkeypatch.setattr(
        conversion, "_extract_text_image", lambda _p, lang, rotate=0: pedidos.append((lang, rotate)) or "текст"
    )

    convert(conn, config, language="pt-BR")

    assert pedidos == [("rus", 90)]
    assert _linha(conn, "foto.png")["language"] == "ru"


def test_pouco_texto_vale_o_idioma_do_grupo(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    pasta = origem / "akte"
    pasta.mkdir()
    (pasta / "brief.txt").write_text(ALEMAO * 3, encoding="utf-8")
    Image.new("RGB", (300, 100), "white").save(pasta / "stempel.png")
    scan(conn, config)
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    pedidos = []
    monkeypatch.setattr(conversion, "_extract_text_image", lambda _p, lang, rotate=0: pedidos.append(lang) or "")

    convert(conn, config, language="pt-BR")

    assert pedidos == ["deu"]
    assert _linha(conn, "brief.txt")["language"] == "de"  # o texto lido para decidir fica gravado


def _maquina_com_tesseract_falso(tmp_path, monkeypatch):
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    # `convert` põe a pasta das ferramentas no `PATH` do processo; sem isto,
    # o `tesseract.exe` vazio deste teste ficaria no `PATH` dos seguintes.
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setattr(ocr_languages, "present_models", _PRESENTES_DE_VERDADE)
    exe = _tesseract_falso(tmp_path, ["eng", "osd"])
    real_find = tools.find
    monkeypatch.setattr(tools, "find", lambda nome: exe if nome == "tesseract" else real_find(nome))
    return exe


def test_sem_rede_o_idioma_detectado_fica_para_depois_e_refaz(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    config = replace(config, ocr_language="eng")
    _pdf(origem / "vertrag.pdf", [ALEMAO * 3, None])
    scan(conn, config)
    _maquina_com_tesseract_falso(tmp_path, monkeypatch)
    ocr = _OcrFalso()
    monkeypatch.setattr(conversion, "_run_ocrmypdf", ocr)

    assert convert(conn, config, language="pt-BR").failed == 0

    # Sem o alemão, nada de OCR com o idioma errado: o arquivo fica para depois.
    assert ocr.chamadas == []
    linha = _linha(conn, "vertrag.pdf")
    assert (linha["status"], linha["ocr_failed"], linha["ocr_lang"]) == ("converted", 1, "deu")
    avisos = [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]
    assert any("idioma do OCR deu" in m for m in avisos), avisos
    assert ocr_retry_count(conn) == 1

    # A rede voltou: a conversão seguinte baixa o que o arquivo pediu e refaz.
    monkeypatch.setattr(ocr_languages, "_download", _DOWNLOAD_DE_VERDADE)
    deu = _componente("tessdata/deu", b"modelo alemao", target="tessdata/deu.traineddata")
    _manifesto(monkeypatch, deu)
    _servidor(monkeypatch, {"tessdata/deu": b"modelo alemao"})
    assert convert(conn, config, language="pt-BR").failed == 0
    assert [(c["paginas"], c["idiomas"]) for c in ocr.chamadas] == [([2], "deu")]
    linha = _linha(conn, "vertrag.pdf")
    assert (linha["status"], linha["ocr_failed"]) == ("converted", 0)


def test_download_recusado_pelo_hash_nao_usa_o_arquivo_e_refaz_depois(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    config = replace(config, ocr_language="eng")
    Image.new("RGB", (300, 100), "white").save(origem / "foto.png")
    scan(conn, config)
    _maquina_com_tesseract_falso(tmp_path, monkeypatch)
    monkeypatch.setattr(ocr_languages, "_download", _DOWNLOAD_DE_VERDADE)
    monkeypatch.setattr(ocr_detection, "osd_image", lambda _imagem: ("cyrillic", 0))
    amostras = []
    monkeypatch.setattr(ocr_detection, "ocr_sample", lambda _imagem, modelo: amostras.append(modelo) or RUSSO)
    certo = b"modelo russo certo"
    adulterado = b"modelo russo errad"  # mesmo tamanho: quem recusa é o hash
    escrita = _componente("tessdata/script/Cyrillic", b"cirilico", target="tessdata/script/Cyrillic.traineddata")
    rus = _componente("tessdata/rus", certo, target="tessdata/rus.traineddata")
    assert rus.sha256 == hashlib.sha256(certo).hexdigest()
    _manifesto(monkeypatch, escrita, rus)
    _servidor(monkeypatch, {"script/Cyrillic": b"cirilico", "tessdata/rus": adulterado})
    pedidos = []
    monkeypatch.setattr(conversion, "_extract_text_image", lambda _p, lang, rotate=0: pedidos.append(lang) or "текст")

    assert convert(conn, config, language="pt-BR").failed == 0

    # O modelo da escrita foi baixado para a amostra; o do idioma, recusado.
    assert amostras == ["script/Cyrillic"]
    assert not (tmp_path / "local" / "tessdata" / "rus.traineddata").exists()
    assert pedidos == []  # nada de OCR em inglês num texto russo
    linha = _linha(conn, "foto.png")
    assert (linha["ocr_failed"], linha["ocr_lang"], linha["language"]) == (1, "rus", "ru")
    avisos = [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]
    assert any("idioma do OCR rus" in m for m in avisos), avisos

    _servidor(monkeypatch, {"script/Cyrillic": b"cirilico", "tessdata/rus": certo})
    assert convert(conn, config, language="pt-BR").failed == 0
    assert pedidos == ["rus"]
    assert _linha(conn, "foto.png")["ocr_failed"] == 0


def test_conteudo_trocado_esquece_o_idioma(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "a.txt").write_text("um", encoding="utf-8")
    scan(conn, config)
    conn.execute("UPDATE file SET ocr_lang = 'deu', language = 'de'")
    conn.commit()
    (origem / "a.txt").write_text("outro conteúdo", encoding="utf-8")
    scan(conn, config)
    linha = _linha(conn, "a.txt")
    assert (linha["ocr_lang"], linha["language"]) == (None, None)


def test_colunas_novas_num_banco_antigo(tmp_path):
    conn = connect(tmp_path / "project.db")
    conn.executescript(
        "CREATE TABLE file (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, name TEXT NOT NULL,"
        " extension TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, group_key TEXT,"
        " page_count INTEGER, needs_ocr INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT);"
    )
    init_schema(conn)
    init_schema(conn)  # duas vezes, como na abertura do projeto
    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(file)")}
    assert {"ocr_lang", "language"} <= colunas
    conn.close()


# --- extração e classificação -----------------------------------------------------


def test_limite_por_pagina_menor_para_chines_japones_e_coreano():
    from gclaude_indexer.auto_settings import CJK_CHARS_PER_PAGE
    from gclaude_indexer.extraction import capped_text

    assert CJK_CHARS_PER_PAGE == 800
    assert len(capped_text(CHINES * 100, 2500)) == 800
    assert len(capped_text(JAPONES * 100, 2500)) == 800
    assert len(capped_text(ALEMAO * 100, 2500)) == 2500
    assert capped_text(CHINES, 500) == CHINES[:500]  # limite menor que o da escrita: vale ele


def _paginas(*textos):
    return [
        WindowPage(reference=f"p. {n}", file_name="doc.pdf", text=texto, has_table=False, image_count=0)
        for n, texto in enumerate(textos, start=1)
    ]


def test_tipo_e_resumo_pedidos_no_idioma_do_documento():
    from gclaude_indexer.engine_local import _build_page_prompt, _build_prompt

    prompt = _build_prompt(_paginas(ALEMAO * 2))
    assert "Idioma do texto desta janela: alemão (de)." in prompt
    assert 'Escreva "type" e "summary" em alemão (de), o idioma do documento' in prompt
    # O prompt em si continua em português, de propósito.
    assert "Você é um classificador de peças" in prompt

    prompt = _build_page_prompt(_paginas(JAPONES * 3))
    assert 'Escreva "subject", "type" e "detail" em japonês (ja)' in prompt


def test_janela_com_idiomas_misturados_usa_o_da_maior_parte():
    from gclaude_indexer.engine_local import _build_prompt

    prompt = _build_prompt(_paginas(RUSSO * 3, RUSSO * 3, ALEMAO))
    assert "Idioma do texto desta janela: russo (ru) na maior parte; também aparece alemão (de)." in prompt
    assert "use o da maior parte (russo (ru))" in prompt


def test_janela_sem_texto_nao_ganha_linha_de_idioma():
    from gclaude_indexer.engine_local import _build_prompt

    assert "Idioma do texto" not in _build_prompt(_paginas("", "f. 3"))


def test_janela_em_portugues_fica_com_o_prompt_de_sempre():
    from gclaude_indexer.engine_local import _build_prompt

    portugues = (
        "O contrato de prestação de serviços foi assinado hoje pelas duas partes e entra em vigor "
        "imediatamente. O pagamento será feito no fim de cada mês, mediante nota fiscal. "
    )
    assert "Idioma do texto" not in _build_prompt(_paginas(portugues * 3))


def test_agrupamento_por_assunto_em_escrita_sem_espaco():
    from gclaude_indexer.engine_local import _same_topic_start, _subject_key

    assert _same_topic_start(_subject_key("会議の議事録 第一部"), _subject_key("会議の議事録 第二部"))
    assert not _same_topic_start(_subject_key("会議の議事録"), _subject_key("売買契約書"))


def test_datas_numericas_e_iso_em_qualquer_idioma_nas_regras():
    from gclaude_indexer.engine_rules import RulesEngine, load_rules

    motor = RulesEngine.__new__(RulesEngine)
    motor._rules = load_rules()
    assert motor._find_date("Datum: 2023-05-12, Berlin") == "2023-05-12"
    assert motor._find_date("Fecha 12-05-2023.") == "2023-05-12"
    assert motor._find_date("日期2023年5月12日签署") == "2023-05-12"
    assert motor._find_date("２０２３年５月１２日") == "2023-05-12"
    assert motor._find_date("2024년 3월 1일") == "2024-03-01"
    assert motor._find_date("protocolo 12345-12-1234") is None
    # Numeração única do CNJ: nada de "2023-08-26" saído do meio do número.
    assert motor._find_date("Processo n. 0001234-56.2023.8.26.0100") is None
    assert motor._find_date("Processo 1234-56.2023.8.26.0100") is None
    assert motor._find_date("2023-05/12") is None  # separadores misturados
    assert motor._find_date("ref 2023-05-12-7") is None
    assert motor._find_date("id 1234-12-05-2023") is None
    assert motor._find_date("em 2023.05.12.") == "2023-05-12"  # ponto final não atrapalha


# --- busca ------------------------------------------------------------------------


def _banco_com_trechos(tmp_path, trechos):
    from gclaude_indexer import fulltext

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    for file_id, textos in trechos.items():
        conn.execute(
            "INSERT INTO file (id, relative_path, name, extension, size, sha256, status)"
            " VALUES (?, ?, ?, 'pdf', 1, ?, 'extracted')",
            (file_id, f"{file_id}.pdf", f"{file_id}.pdf", str(file_id)),
        )
        fulltext._store_passages(
            conn, {"id": file_id}, [fulltext.Passage(texto, f"p. {n}", 0) for n, texto in enumerate(textos, 1)]
        )
    conn.commit()
    return conn


def test_busca_em_chines_acha_palavra_de_dois_e_de_quatro_caracteres(tmp_path):
    from gclaude_indexer import fulltext

    # O OCR põe espaço entre ideogramas; a busca acha mesmo assim.
    conn = _banco_com_trechos(tmp_path, {
        1: ["政府 今天 决定 修改 关于 公共 服务 的 法律。", "Vigência da lei"],
        2: [CHINES],
    })

    hits, total = fulltext.search(conn, "法律")  # dois caracteres: abaixo do trigrama
    assert total == 2 and {h.file_id for h in hits} == {1, 2}
    hits, total = fulltext.search(conn, "公共服务")
    assert total == 2
    assert fulltext.MATCH_START + "公共服务" + fulltext.MATCH_END in hits[0].snippet
    assert fulltext.search(conn, "不存在")[1] == 0
    # A busca por palavras de antes continua igual.
    assert fulltext.search(conn, "vigencia")[1] == 1

    fulltext.remove_file(conn, 1)
    assert conn.execute("SELECT COUNT(*) FROM fulltext_trigram").fetchone()[0] == 1
    assert fulltext.search(conn, "法律")[1] == 1
    conn.close()


def test_busca_paginada_conta_a_uniao_sem_repetir(tmp_path):
    from gclaude_indexer import fulltext

    conn = _banco_com_trechos(tmp_path, {n: [f"第{n}号文件 法律 Tokyo"] for n in range(1, 6)})
    primeira, total = fulltext.search(conn, "法律 Tokyo", limit=3)
    segunda, _ = fulltext.search(conn, "法律 Tokyo", limit=3, offset=3)
    assert total == 5 and len(primeira) == 3 and len(segunda) == 2
    assert len({h.file_id for h in primeira + segunda}) == 5
    conn.close()


def test_projeto_antigo_recebe_os_trechos_na_tabela_trigram_uma_vez(tmp_path):
    from gclaude_indexer import fulltext

    conn = _banco_com_trechos(tmp_path, {1: [CHINES, ALEMAO]})
    # Como um banco anterior à 2.0.0: trechos só na `fulltext`.
    conn.execute("DELETE FROM fulltext_trigram")
    conn.execute("UPDATE fulltext_trigram_state SET backfilled = 0")
    conn.commit()
    # Todo indexado, sem passar por `index_pending`: a tabela trigram vazia
    # não é consultada; a busca cai para substring na `fulltext` e acha.
    hits, total = fulltext.search(conn, "学校")
    assert total == 1 and hits[0].file_id == 1
    assert fulltext.search(conn, "公共服务")[1] == 1

    assert fulltext.backfill_trigram(conn) == 1
    assert fulltext.search(conn, "学校")[1] == 1
    assert fulltext.backfill_trigram(conn) == 0  # uma vez só
    conn.close()


def test_remover_arquivo_indexado_sem_faixa_tira_tambem_os_trechos_trigram(tmp_path):
    from gclaude_indexer import fulltext

    conn = _banco_com_trechos(tmp_path, {1: [CHINES], 2: [CHINES]})
    # Como um arquivo indexado antes da 1.5.9: sem a faixa de rowids.
    conn.execute("UPDATE fulltext_file SET first_rowid = NULL, last_rowid = NULL WHERE file_id = 1")
    conn.commit()
    fulltext.remove_file(conn, 1)
    restantes = {linha[0] for linha in conn.execute("SELECT rowid FROM fulltext_trigram")}
    assert restantes == {linha[0] for linha in conn.execute("SELECT rowid FROM fulltext WHERE file_id = 2")}
    assert {h.file_id for h in fulltext.search(conn, "学校")[0]} == {2}
    conn.close()


def test_sem_tokenizador_trigram_a_busca_cai_para_substring(tmp_path):
    from gclaude_indexer import fulltext

    conn = _banco_com_trechos(tmp_path, {1: [CHINES]})
    conn.execute("DROP TABLE fulltext_trigram")
    conn.commit()
    hits, total = fulltext.search(conn, "学校")
    assert total == 1 and hits[0].file_id == 1
    conn.close()

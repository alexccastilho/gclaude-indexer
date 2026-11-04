"""Proposta automática de "Fatiamento, janelas e OCR" a partir da pasta de origem."""

from __future__ import annotations

import fitz
import pytest
from PIL import Image

from gclaude_indexer.settings_proposal import FolderSurvey, propose, survey_folder

PT = (
    "O servidor público que, no exercício de suas atribuições, praticar ato de improbidade "
    "será punido nos termos da lei, sem prejuízo das sanções penais e civis cabíveis, e a "
    "administração pública deverá instaurar o processo para apurar a responsabilidade dos "
    "agentes que concorreram para o dano ao erário, com a garantia do contraditório. "
)
ES = (
    "El servidor público que, en el ejercicio de sus funciones, cometa un acto de corrupción "
    "será sancionado según la ley, sin perjuicio de las sanciones penales y civiles, y la "
    "administración deberá iniciar el procedimiento para determinar la responsabilidad de los "
    "agentes que causaron el daño al erario, con la garantía de la defensa. "
)


def _pdf(caminho, paginas, texto=PT, repetir=6):
    documento = fitz.open()
    for _ in range(paginas):
        documento.new_page().insert_textbox(fitz.Rect(30, 30, 580, 820), texto * repetir, fontsize=7)
    documento.save(caminho)
    documento.close()


def _pdf_escaneado(caminho, paginas=3):
    imagem = caminho.with_suffix(".png")
    Image.new("RGB", (400, 300), "white").save(imagem)
    documento = fitz.open()
    for _ in range(paginas):
        documento.new_page().insert_image(fitz.Rect(0, 0, 400, 300), filename=str(imagem))
    documento.save(caminho)
    documento.close()
    imagem.unlink()


def _html(caminho, texto=PT):
    caminho.write_bytes(f"<html><body><p>LEI Nº 1</p><p>{texto * 3}</p></body></html>".encode("cp1252"))


def test_so_html_propoe_janela_grande_sem_sobreposicao(tmp_path):
    for n in range(30):
        _html(tmp_path / f"lei{n}.htm")

    proposta = propose(survey_folder(tmp_path, ["web_dados"]))

    assert proposta.overlap == 0
    assert proposta.pages_per_window == 16
    assert proposta.chars_per_page == 2000
    assert proposta.ocr_language == "por"
    assert {r.key for r in proposta.reasons["ocr_language"]} >= {"proposal.reason.ocr_unused"}


def test_pdfs_longos_e_densos_propoem_janela_menor_e_mais_caracteres(tmp_path):
    for n in range(3):
        _pdf(tmp_path / f"coletanea{n}.pdf", paginas=40, repetir=10)

    proposta = propose(survey_folder(tmp_path, ["pdf"]))

    assert proposta.pages_per_window <= 12
    assert proposta.overlap == 2
    assert proposta.chars_per_page > 2000
    assert proposta.chars_per_page * proposta.pages_per_window <= 40_000
    assert proposta.pages_per_block == 80


def test_pdfs_escaneados_propoem_blocos_menores(tmp_path):
    for n in range(4):
        _pdf_escaneado(tmp_path / f"scan{n}.pdf")

    proposta = propose(survey_folder(tmp_path, ["pdf"]))

    assert proposta.pages_per_block == 40
    assert "proposal.reason.ocr_unused" not in {r.key for r in proposta.reasons["ocr_language"]}


def test_acervo_misto_com_poucos_pdfs_segue_os_documentos_inteiros_mas_mantem_sobreposicao(tmp_path):
    (tmp_path / "Leis").mkdir()
    for n in range(40):
        _html(tmp_path / "Leis" / f"lei{n}.htm")
    _pdf(tmp_path / "parecer.pdf", paginas=10, repetir=2)
    (tmp_path / "nota.txt").write_text(PT, encoding="utf-8")

    proposta = propose(survey_folder(tmp_path, ["pdf", "web_dados", "text"]))

    assert proposta.pages_per_window == 16
    assert proposta.overlap > 0  # há documentos de várias páginas no acervo
    assert proposta.survey.by_category["web_dados"] == 40


def test_idioma_espanhol_e_detectado(tmp_path):
    for n in range(5):
        (tmp_path / f"doc{n}.txt").write_text(ES * 2, encoding="utf-8")
    proposta = propose(survey_folder(tmp_path, ["text"]), installed=frozenset({"por", "spa", "eng", "osd"}))
    assert proposta.ocr_language == "spa"


def test_idioma_sem_dados_no_tesseract_fica_de_fora(tmp_path):
    for n in range(5):
        (tmp_path / f"doc{n}.txt").write_text(ES * 2, encoding="utf-8")
    proposta = propose(survey_folder(tmp_path, ["text"]), installed=frozenset({"por", "eng"}))
    assert proposta.ocr_language == "por"
    assert "proposal.reason.ocr_missing" in {r.key for r in proposta.reasons["ocr_language"]}


def test_pasta_grande_e_amostrada_sem_travar(tmp_path, monkeypatch):
    from gclaude_indexer import settings_proposal

    monkeypatch.setattr(settings_proposal, "_WALK_MAX_FILES", 25)
    for n in range(60):
        (tmp_path / f"a{n}.txt").write_text(PT, encoding="utf-8")
    pesquisa = survey_folder(tmp_path, ["text"])
    assert pesquisa.partial
    assert pesquisa.files == 25


def test_pasta_vazia_nao_quebra():
    proposta = propose(FolderSurvey())
    assert proposta.pages_per_window >= 4


# --- tela ----------------------------------------------------------------------


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import gclaude_indexer.catalog as catalogo_mod
    import gclaude_indexer.hardware as hardware_mod
    from gclaude_indexer.web.app import app

    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app, base_url="http://127.0.0.1")


def _post(cliente, dados):
    return cliente.post(
        "/projects/propose-settings", data=dados,
        headers={"Origin": "http://127.0.0.1", "HX-Request": "true"},
    )


@pytest.mark.parametrize("idioma, titulo", [
    ("pt", "Configuração proposta"), ("en", "Proposed settings"), ("es", "Configuración propuesta"),
])
def test_rota_devolve_a_proposta_com_os_valores_para_aplicar(tmp_path, cliente, idioma, titulo):
    for n in range(5):
        _html(tmp_path / f"lei{n}.htm")
    cliente.cookies.set("language", idioma)

    resposta = _post(cliente, {"source_folder": str(tmp_path), "extensions": ["web_dados"]})

    assert resposta.status_code == 200
    assert titulo in resposta.text
    assert 'data-overlap="0"' in resposta.text
    assert 'data-pages_per_window="16"' in resposta.text
    assert "proposal." not in resposta.text  # nenhuma chave sem tradução


def test_rota_sem_pasta_pede_a_pasta(cliente):
    resposta = _post(cliente, {"source_folder": ""})
    assert resposta.status_code == 200
    assert "data-proposal" not in resposta.text


def test_formulario_tem_o_painel_de_proposta(cliente):
    resposta = cliente.get("/projects/new")
    assert 'id="settings_proposal"' in resposta.text
    assert "sourceFolderChosen" in resposta.text


def test_escolher_a_pasta_de_origem_dispara_a_proposta(cliente, monkeypatch, tmp_path):
    from gclaude_indexer.web import app as modulo

    monkeypatch.setattr(modulo, "choose_folder", lambda **_kw: str(tmp_path))
    resposta = cliente.post(
        "/select-folder", data={"field": "source_folder", "source_folder": ""},
        headers={"Origin": "http://127.0.0.1", "HX-Request": "true"},
    )
    assert resposta.headers.get("HX-Trigger") == "sourceFolderChosen"

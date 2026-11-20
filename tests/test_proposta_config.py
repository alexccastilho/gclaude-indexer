"""Configuração automática depois da varredura (2.0.0): janela, sobreposição,
caracteres por página e idioma do OCR saem do acervo, não do formulário."""

from __future__ import annotations

import json
import threading
import time

import fitz
import pytest
from PIL import Image

from gclaude_indexer import auto_settings
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import WHOLE_DOCUMENT_CHARS, chars_limit_for, extract_pages
from gclaude_indexer.project import create_project, load_project
from gclaude_indexer.scanning import scan
from gclaude_indexer.pipeline import _scan_step
from gclaude_indexer.windows_prep import prepare_windows
from gclaude_indexer.web import routes_projects

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
TESSERACT = frozenset({"por", "spa", "eng", "osd"})


@pytest.fixture(autouse=True)
def _tesseract_conhecido(monkeypatch):
    monkeypatch.setattr(auto_settings, "installed_ocr_languages", lambda: TESSERACT)


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


def _projeto(tmp_path, motor="rules", **extra):
    """Projeto novo (banco criado) com a pasta `origem` já varrida, sem
    resolver nada: o que `scan` sozinho deixa."""
    origem = tmp_path / "origem"
    origem.mkdir(exist_ok=True)
    return origem, lambda: _abrir(tmp_path, origem, motor, extra)


def _abrir(tmp_path, origem, motor, extra):
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Acervo", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["all"], "classification_engine": motor, **extra,
    })
    conn, _ = create_project(config)
    scan(conn, config)
    return config, conn


def _do_banco(conn):
    return load_config(json.loads(conn.execute("SELECT config_json FROM project").fetchone()[0]))


# --- valores por perfil de acervo --------------------------------------------


def test_so_html_com_regras_janela_16_sem_sobreposicao(tmp_path):
    origem, abrir = _projeto(tmp_path)
    for n in range(30):
        _html(origem / f"lei{n}.htm")
    config, conn = abrir()

    decisao = auto_settings.resolve_auto_settings(conn, config)

    assert (decisao.pages_per_window, decisao.overlap) == (16, 0)
    gravado = _do_banco(conn)
    assert (gravado.pages_per_window, gravado.overlap) == (16, 0)
    assert gravado.chars_per_page == 2000  # sem PDF para medir, fica o valor em vigor
    assert gravado.ocr_language == "por"


def test_motor_local_usa_janela_8(tmp_path):
    origem, abrir = _projeto(tmp_path, motor="local")
    for n in range(10):
        _html(origem / f"lei{n}.htm")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    assert _do_banco(conn).pages_per_window == 8


def test_motor_automatico_decide_pelo_motor_efetivo(tmp_path, monkeypatch):
    origem, abrir = _projeto(tmp_path, motor="automatic")
    _html(origem / "lei.htm")
    config, conn = abrir()
    from gclaude_indexer import orchestrator

    monkeypatch.setattr(orchestrator, "resolve_effective_engine", lambda *_a, **_k: "local")
    assert auto_settings.resolve_auto_settings(conn, config).pages_per_window == 8


def test_motor_que_nao_se_descobre_cai_no_configurado(tmp_path, monkeypatch):
    origem, abrir = _projeto(tmp_path, motor="local")
    _html(origem / "lei.htm")
    config, conn = abrir()
    from gclaude_indexer import orchestrator

    def falha(*_a, **_k):
        raise RuntimeError("Ollama fora do ar")

    monkeypatch.setattr(orchestrator, "resolve_effective_engine", falha)
    assert auto_settings.resolve_auto_settings(conn, config).pages_per_window == 8


def test_pdfs_longos_e_densos_pedem_janela_8_sobreposicao_2_e_mais_caracteres(tmp_path):
    origem, abrir = _projeto(tmp_path, motor="local")
    for n in range(3):
        _pdf(origem / f"coletanea{n}.pdf", paginas=40, repetir=10)
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    gravado = _do_banco(conn)
    assert (gravado.pages_per_window, gravado.overlap) == (8, 2)
    assert 2000 < gravado.chars_per_page <= 4000
    assert gravado.chars_per_page % 500 == 0


def test_pdfs_escaneados_nao_mexem_nos_caracteres(tmp_path):
    origem, abrir = _projeto(tmp_path)
    for n in range(4):
        _pdf_escaneado(origem / f"scan{n}.pdf")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    gravado = _do_banco(conn)
    assert gravado.chars_per_page == 2000
    assert gravado.overlap == 2


def test_acervo_misto_com_poucos_pdfs_mantem_a_sobreposicao(tmp_path):
    origem, abrir = _projeto(tmp_path)
    (origem / "Leis").mkdir()
    for n in range(40):
        _html(origem / "Leis" / f"lei{n}.htm")
    _pdf(origem / "parecer.pdf", paginas=10, repetir=2)
    (origem / "nota.txt").write_text(PT, encoding="utf-8")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    gravado = _do_banco(conn)
    assert gravado.pages_per_window == 16
    assert gravado.overlap == 2  # há documentos de várias páginas no acervo


def test_arquivos_ignorados_nao_entram_em_nenhuma_estatistica(tmp_path):
    origem, abrir = _projeto(tmp_path)
    for n in range(30):
        _html(origem / f"lei{n}.htm")
    for n in range(10):
        _pdf(origem / f"ignorado{n}.pdf", paginas=5)
    config, conn = abrir()
    conn.execute("UPDATE file SET status = 'skipped', error = 'x' WHERE extension = 'pdf'")
    conn.commit()

    auto_settings.resolve_auto_settings(conn, config)

    gravado = _do_banco(conn)
    assert gravado.overlap == 0  # os PDFs ignorados não contaram como acervo de várias páginas
    assert gravado.chars_per_page == 2000  # nem foram abertos para medir texto


def test_idioma_que_se_baixa_entra_mesmo_sem_estar_no_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_settings, "installed_ocr_languages", lambda: frozenset({"por", "eng"}))
    origem, abrir = _projeto(tmp_path)
    for n in range(5):
        (origem / f"doc{n}.txt").write_text(ES * 2, encoding="utf-8")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    assert _do_banco(conn).ocr_language == "spa"


def test_idioma_espanhol_e_detectado(tmp_path):
    origem, abrir = _projeto(tmp_path)
    for n in range(5):
        (origem / f"doc{n}.txt").write_text(ES * 2, encoding="utf-8")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    assert _do_banco(conn).ocr_language == "spa"


def test_idioma_sem_dados_no_tesseract_fica_de_fora(tmp_path, monkeypatch):
    # 2.0.0: o idioma que o Tesseract não tem mas que se baixa (manifesto)
    # entra; fica de fora só o que nem se baixa.
    from gclaude_indexer import ocr_languages

    monkeypatch.setattr(auto_settings, "installed_ocr_languages", lambda: frozenset({"por", "eng"}))
    monkeypatch.setattr(ocr_languages, "downloadable", lambda _code: False)
    origem, abrir = _projeto(tmp_path)
    for n in range(5):
        (origem / f"doc{n}.txt").write_text(ES * 2, encoding="utf-8")
    config, conn = abrir()

    auto_settings.resolve_auto_settings(conn, config)

    assert _do_banco(conn).ocr_language == "por"


def test_pasta_vazia_nao_quebra_nem_grava(tmp_path):
    _origem, abrir = _projeto(tmp_path)
    config, conn = abrir()
    assert auto_settings.resolve_auto_settings(conn, config) is None
    assert not [e for e in list_events(conn) if (e["message_key"] or "").startswith("log.settings")]


def test_regras_de_sobreposicao_e_de_caracteres():
    assert auto_settings.overlap_for(16, 0.0) == 0
    assert auto_settings.overlap_for(8, 0.5) == 2
    assert auto_settings.overlap_for(6, 0.5) == 1
    assert auto_settings.chars_from_page_lengths([]) is None
    assert auto_settings.chars_from_page_lengths([300] * 10) == 1500  # piso
    assert auto_settings.chars_from_page_lengths([2100] * 10) == 2500
    assert auto_settings.chars_from_page_lengths([9000] * 10) == 4000  # teto


# --- quando resolver ------------------------------------------------------------


def _extraido(tmp_path, motor="rules", **extra):
    origem, abrir = _projeto(tmp_path, motor=motor, **extra)
    for n in range(4):
        pasta = origem / f"g{n % 2}"
        pasta.mkdir(exist_ok=True)
        _html(pasta / f"lei{n}.htm")
    config, conn = abrir()
    convert(conn, config)
    extract_pages(conn, config)
    return config, conn


def test_com_paginas_e_sem_janelas_so_janela_e_sobreposicao(tmp_path):
    config, conn = _extraido(tmp_path)
    conn.execute(
        "UPDATE project SET config_json = json_set(config_json, '$.chars_per_page', 2500,"
        " '$.ocr_language', 'eng', '$.pages_per_window', 5, '$.overlap', 1)"
    )
    conn.commit()
    config = _do_banco(conn)

    decisao = auto_settings.resolve_auto_settings(conn, config)

    assert decisao.scope == auto_settings.SCOPE_WINDOWS
    gravado = _do_banco(conn)
    assert (gravado.pages_per_window, gravado.overlap) == (16, 0)
    assert (gravado.chars_per_page, gravado.ocr_language) == (2500, "eng")
    assert [e["message_key"] for e in list_events(conn, step="scan")][-1:] == ["log.settings.window"]


def test_projeto_com_janelas_nunca_muda_e_nao_derruba_grupos(tmp_path):
    config, conn = _extraido(tmp_path, motor="local")
    conn.execute(
        "UPDATE project SET config_json = json_set(config_json, '$.pages_per_window', 5, '$.overlap', 1)"
    )
    conn.commit()
    config = _do_banco(conn)
    prepare_windows(conn, config)
    janelas = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
    assert janelas > 0

    assert auto_settings.resolve_auto_settings(conn, config) is None
    _scan_step(conn, config, should_stop=lambda: False, language="pt")  # nova varredura, como "Executar tudo"

    gravado = _do_banco(conn)
    assert (gravado.pages_per_window, gravado.overlap) == (5, 1)
    assert conn.execute("SELECT COUNT(*) FROM window").fetchone()[0] == janelas
    chaves = {e["message_key"] for e in list_events(conn)}
    assert "log.update.layout_mismatch" not in chaves
    assert "log.settings.window" not in chaves


def test_a_varredura_pausada_nao_resolve(tmp_path):
    origem, abrir = _projeto(tmp_path)
    _html(origem / "lei.htm")
    config, conn = abrir()
    _scan_step(conn, config, should_stop=lambda: True, language="pt")
    assert conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.settings.window'"
    ).fetchone()[0] == 0


def test_eventos_com_valores_e_motivos_nos_tres_idiomas(tmp_path):
    origem, abrir = _projeto(tmp_path, motor="local")
    for n in range(3):
        _pdf(origem / f"c{n}.pdf", paginas=20, repetir=10)
    config, conn = abrir()
    auto_settings.resolve_auto_settings(conn, config, language="pt")

    for idioma in ("pt", "en", "es"):
        eventos = list_events(conn, step="scan", language=idioma)
        mensagens = " ".join(e["message"] for e in eventos)
        assert "log." not in mensagens and "auto.reason" not in mensagens
        assert "{" not in mensagens
        assert [e["message_key"] for e in eventos if (e["message_key"] or "").startswith("log.settings")] == [
            "log.settings.window", "log.settings.chars_per_page", "log.settings.ocr_language",
        ]
    pt = next(e["message"] for e in list_events(conn, step="scan", language="pt") if e["message_key"] == "log.settings.window")
    assert "8 página" in pt and "sobreposição de 2" in pt


# --- limite de texto por tipo ----------------------------------------------------


def test_limite_de_texto_por_categoria(tmp_path):
    config = load_config(
        {"name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "s"), "chars_per_page": 1500}
    )
    assert chars_limit_for("pdf", config) == 1500
    assert chars_limit_for("imagens", config) == 1500
    for categoria in ("docx", "pptx", "xlsx", "web_dados", "text", "email", None):
        assert chars_limit_for(categoria, config) == WHOLE_DOCUMENT_CHARS == 4000


def test_extracao_corta_pdf_no_limite_do_projeto_e_documento_inteiro_em_4000(tmp_path):
    origem, abrir = _projeto(tmp_path, chars_per_page=1500)
    _pdf(origem / "p.pdf", paginas=1, repetir=12)
    (origem / "longo.txt").write_text(PT * 30, encoding="utf-8")
    config, conn = abrir()
    convert(conn, config)
    extract_pages(conn, config)

    tamanhos = {
        r["name"]: r["n"] for r in conn.execute(
            "SELECT f.name AS name, MAX(p.char_count) AS n FROM page p JOIN file f ON f.id = p.file_id"
            " GROUP BY f.name"
        )
    }
    assert tamanhos["p.pdf"] == 1500
    assert tamanhos["longo.txt"] == 4000


# --- o formulário e o servidor -----------------------------------------------------


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


_CABECALHOS = {"Origin": "http://127.0.0.1", "HX-Request": "true"}


def test_formulario_nao_tem_mais_fatiamento_janelas_nem_ocr(cliente):
    corpo = cliente.get("/projects/new").text
    for campo in ("pages_per_block", "pages_per_window", "overlap", "chars_per_page", "ocr_language"):
        assert f'name="{campo}"' not in corpo
    assert "settings_proposal" not in corpo and "sourceFolderChosen" not in corpo


def test_rota_de_proposta_nao_existe_mais(cliente):
    resposta = cliente.post("/projects/propose-settings", data={"source_folder": "x"}, headers=_CABECALHOS)
    assert resposta.status_code in (404, 405)


def test_escolher_a_pasta_nao_dispara_mais_a_proposta(cliente, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_projects, "choose_folder", lambda **_kw: str(tmp_path))
    resposta = cliente.post(
        "/select-folder", data={"field": "source_folder", "source_folder": ""}, headers=_CABECALHOS,
    )
    assert "HX-Trigger" not in resposta.headers


def _novo_projeto(cliente, tmp_path, **extra):
    origem = tmp_path / "origem"
    origem.mkdir(exist_ok=True)
    for n in range(6):
        (origem / f"nota{n}.txt").write_text(PT, encoding="utf-8")
    dados = {
        "name": "Auto", "subject": "Acervo", "source_folder": str(origem),
        "output_folder": str(tmp_path / "saida"), "collection_type": "processo",
        "group_mode": "subfolder", "group_pattern": "", "extensions": ["text"],
        "classification_engine": "local", "local_model": "automatic", **extra,
    }
    resposta = cliente.post("/projects/new", data=dados, headers=_CABECALHOS, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2]), tmp_path / "saida"


def test_campos_forjados_sao_ignorados(cliente, tmp_path):
    _projeto_id, saida = _novo_projeto(
        cliente, tmp_path, pages_per_block="3", pages_per_window="3", overlap="1",
        chars_per_page="5", ocr_language="xx",
    )
    config, conn = load_project(saida)
    conn.close()
    assert not hasattr(config, "pages_per_block")
    assert (config.pages_per_window, config.overlap) == (16, 2)
    assert (config.chars_per_page, config.ocr_language) == (2000, "por")


def test_executar_tudo_usa_os_valores_resolvidos_em_todas_as_etapas(cliente, tmp_path, monkeypatch):
    from gclaude_indexer import pipeline
    from gclaude_indexer.web.background_runs import task_manager

    projeto_id, saida = _novo_projeto(cliente, tmp_path)
    config_antiga, conn = load_project(saida)
    conn.close()
    assert (config_antiga.pages_per_window, config_antiga.overlap) == (16, 2)

    vistos: dict[str, tuple] = {}

    def espiao(etapa):
        def passo(_conn, config, **_extra):
            vistos[etapa] = (config.pages_per_window, config.overlap)
        return passo

    for etapa in ("conversion", "extraction", "windows", "classification"):
        monkeypatch.setitem(pipeline.STEP_FUNCTIONS, etapa, espiao(etapa))
    task_manager._tasks.clear()

    task_manager.start_all(projeto_id, str(saida))
    limite = time.monotonic() + 60
    while projeto_id in task_manager._chains and time.monotonic() < limite:
        threading.Event().wait(0.05)

    assert vistos == {
        etapa: (8, 0) for etapa in ("conversion", "extraction", "windows", "classification")
    }

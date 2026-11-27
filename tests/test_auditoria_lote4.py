"""2.1.6: pequenas correções da auditoria (lote 4)."""
from __future__ import annotations

from dataclasses import replace

from gclaude_indexer import conversion, parallelism
from gclaude_indexer.config import ProjectConfig


def _config(mode: str) -> ProjectConfig:
    return replace(ProjectConfig(name="XPTO", source_folder="", output_folder=""), parallelism=mode)


def test_ocr_dos_legados_respeita_o_modo_economia(monkeypatch):
    monkeypatch.setattr(parallelism, "_physical_cores", lambda: 8)
    monkeypatch.setattr(conversion, "_physical_cores", lambda: 8)

    assert conversion._legacy_ocr_jobs(_config("economy")) == 1
    assert conversion._legacy_ocr_jobs(_config("automatic")) == 4
    assert conversion._legacy_ocr_jobs(_config("maximum")) == 4


# --- "Criar janelas" depois de uma atualização incremental ------------------------


def _projeto_texto(tmp_path):
    from gclaude_indexer.config import load_config
    from gclaude_indexer.db import connect, init_schema

    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    (origem / "volume_1" / "oficio.txt").write_text("Ofício da Diretoria / Região Sul sobre saneamento.", encoding="utf-8")
    saida = tmp_path / "saida"
    config = replace(load_config({
        "name": "XPTO", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["all"], "group_mode": "subfolder",
    }), parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, config, conn


def _ate_extrair(conn, config):
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.scanning import scan

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)


def _situacao(conn, chave):
    from gclaude_indexer.web.step_state import step_status

    return next(e["status"] for e in step_status(conn, lambda _k: False) if e["chave"] == chave)


def test_grupo_novo_extraido_deixa_a_etapa_de_janelas_pendente(tmp_path):
    from gclaude_indexer.windows_prep import prepare_windows

    origem, config, conn = _projeto_texto(tmp_path)
    _ate_extrair(conn, config)
    prepare_windows(conn, config)
    assert _situacao(conn, "windows") == "done"

    # Um volume novo chega: extraído, mas ainda sem janelas.
    (origem / "volume_2").mkdir()
    (origem / "volume_2" / "ata.txt").write_text("Ata de ANTONIO PEREIRA sobre saneamento.", encoding="utf-8")
    _ate_extrair(conn, config)
    assert _situacao(conn, "windows") != "done"

    prepare_windows(conn, config)
    assert _situacao(conn, "windows") == "done"
    conn.close()


def test_grupo_extraido_sem_paginas_nao_prende_a_etapa_de_janelas(tmp_path):
    # Um grupo cujo único arquivo não deu página nenhuma não ganha janela
    # (`prepare_windows` pula); a etapa não pode ficar pendente para sempre.
    from gclaude_indexer.windows_prep import prepare_windows

    origem, config, conn = _projeto_texto(tmp_path)
    _ate_extrair(conn, config)
    prepare_windows(conn, config)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key)"
        " VALUES ('vazio/x.txt', 'x.txt', '.txt', 0, 'abc', 'extracted', 'vazio')"
    )
    conn.commit()
    assert _situacao(conn, "windows") == "done"
    conn.close()


def test_reimportar_o_mesmo_numero_de_pecas_nao_serve_o_resumo_antigo():
    from gclaude_indexer.web import caches

    caches._quality_cache[(7, "quality")] = (("assinatura",), {"nota": 60})
    caches._quality_cache[(8, "quality")] = (("assinatura",), {"nota": 80})

    caches.forget_project_summaries(7)

    assert (7, "quality") not in caches._quality_cache
    assert (8, "quality") in caches._quality_cache
    caches._quality_cache.clear()


# --- .docx: a tabela vem da conversão, sem reabrir o original no Drive ----------


def _docx(caminho, com_tabela):
    from docx import Document

    documento = Document()
    documento.add_paragraph("Contrato XPTO de saneamento")
    if com_tabela:
        tabela = documento.add_table(rows=1, cols=2)
        tabela.rows[0].cells[0].text = "valor"
        tabela.rows[0].cells[1].text = "R$ 10"
    documento.save(caminho)


def _tem_tabela(conn, nome):
    return conn.execute(
        "SELECT page.has_table FROM page JOIN file ON file.id = page.file_id WHERE file.name = ?", (nome,)
    ).fetchone()[0]


def test_extracao_do_docx_nao_reabre_o_original(tmp_path, monkeypatch):
    from gclaude_indexer import extraction
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.scanning import scan

    origem, config, conn = _projeto_texto(tmp_path)
    _docx(origem / "volume_1" / "com.docx", True)
    _docx(origem / "volume_1" / "sem.docx", False)
    scan(conn, config)
    convert(conn, config)

    def nao_reabrir(_path):
        raise AssertionError("a extração reabriu o .docx original")

    monkeypatch.setattr(extraction, "_docx_has_table", nao_reabrir)
    extraction.extract_pages(conn, config)

    assert _tem_tabela(conn, "com.docx") == 1
    assert _tem_tabela(conn, "sem.docx") == 0
    conn.close()


def test_docx_convertido_por_versao_anterior_ainda_reabre_o_original(tmp_path):
    # Sem a marca gravada pela conversão (projeto convertido antes da
    # 2.1.6), a extração volta a perguntar ao original.
    from gclaude_indexer import extraction, workdir
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.scanning import scan

    origem, config, conn = _projeto_texto(tmp_path)
    _docx(origem / "volume_1" / "com.docx", True)
    scan(conn, config)
    convert(conn, config)
    for marca in workdir.work_folder(config.output_folder).rglob("*.tables"):
        marca.unlink()

    extraction.extract_pages(conn, config)

    assert _tem_tabela(conn, "com.docx") == 1
    conn.close()


# --- Diagnóstico: o Ghostscript não está mais no winget -------------------------


import pytest  # noqa: E402


@pytest.mark.parametrize("idioma, trecho", [
    ("pt-BR", "instalador do GClaude Indexer"),
    ("en", "GClaude Indexer installer"),
    ("es", "instalador de GClaude Indexer"),
])
def test_diagnostico_nao_manda_instalar_o_ghostscript_pelo_winget(monkeypatch, idioma, trecho):
    import gclaude_indexer.install_diagnostics as dm

    monkeypatch.setattr(dm, "find_ghostscript", lambda: None)
    itens = {i["key"]: i for i in dm.check_installation(idioma)}

    comando = itens["ghostscript"]["install_command"]
    assert "winget" not in comando
    assert trecho in comando
    assert "ghostscript.com" in comando


def test_guia_do_pacote_lista_as_normas_citadas_no_passo_dos_arquivos():
    from gclaude_indexer.claude_package import _GUIDE, _guide_names

    for idioma, guia in _GUIDE.items():
        texto = guia.format(name="XPTO", **_guide_names(idioma))
        passo_3 = texto.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
        assert _guide_names(idioma)["norms"] in passo_3, idioma

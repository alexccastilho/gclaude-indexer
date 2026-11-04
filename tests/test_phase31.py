# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 31: o pacote cabe num Projeto do Claude.

Caso visto num acervo grande, com mais de cem mil peças: o
`index-<grupo>.md` passava de 30 MB, quase todo de atos do Planalto, e o
`timeline.md` tinha tamanho parecido repetindo o índice. O Projeto do Claude aceita
30 MB por arquivo e degrada acima de alguns milhões de tokens.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from gclaude_indexer.artifacts import (
    generate_all_artifacts,
    generate_index_md,
    generate_project_instructions_md,
    generate_timeline_md,
    group_index_filename,
    group_timeline_filename,
)
from gclaude_indexer.claude_package import generate_claude_project_package, package_files
from gclaude_indexer.config import ProjectConfig, load_config
from gclaude_indexer.db import connect, init_schema


def _config(tmp_path, **extra) -> ProjectConfig:
    return ProjectConfig(name="Acervo", source_folder=".", output_folder=str(tmp_path), **extra)


def _banco(tmp_path, db_name="p.db", arquivos=None):
    """O esquema de verdade: um PDF de 4 páginas no grupo `Processo`, um
    `.htm` do Planalto de 1 página no mesmo grupo e um PDF de 2 páginas em
    `Avulsos` — ou os `arquivos` (nome, extensão, grupo, páginas) pedidos."""
    conn = connect(tmp_path / db_name)
    init_schema(conn)
    arquivos = arquivos or [
        ("vol1.pdf", "pdf", "Processo", 4),
        ("lei.htm", "htm", "Processo", 1),
        ("anexo.pdf", "pdf", "Avulsos", 2),
    ]
    for ordem, (nome, ext, grupo, paginas) in enumerate(arquivos, start=1):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key) "
            "VALUES (?, ?, ?, 1, ?, 'extracted', ?)",
            (nome, nome, ext, f"h{ordem}", grupo),
        )
        for numero in range(1, paginas + 1):
            conn.execute(
                "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
                "VALUES (?, ?, ?, 100, 0, 0, 'x')",
                (ordem, numero, f"f. {numero}"),
            )
    conn.commit()
    return conn


def _peca(conn, grupo, inicio, fim, tipo, arquivo, *, engine="local", data="2026-01-01",
          confianca="high", resumo="resumo"):
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
        "type, date, engine, confidence, files, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (grupo, f"f. {inicio}", f"f. {fim}", inicio, fim, tipo, data, engine, confianca, arquivo, resumo),
    )
    conn.commit()


def _acervo_com_lei(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    _peca(conn, "Processo", 5, 5, "LEI", "lei.htm", engine="structured", data="1990-07-11",
          resumo="Lei 8.078 — Código de Defesa do Consumidor")
    _peca(conn, "Avulsos", 1, 2, "OFÍCIO", "anexo.pdf")
    return conn


def _nomes_do_zip(config) -> list[str]:
    conteudo = generate_claude_project_package(config, "pt")
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        return z.namelist()


# --- Tarefa 1: a legislação do Planalto fora do índice e do pacote ------------


def test_ato_do_planalto_sai_do_indice_do_grupo(tmp_path):
    """Num acervo grande, quase todas as linhas do índice do grupo eram atos
    do Planalto que o Claude consulta melhor em planalto.gov.br."""
    conn = _acervo_com_lei(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")

    indice = (tmp_path / group_index_filename("Processo")).read_text(encoding="utf-8")

    assert "LAUDO" in indice and "Código de Defesa" not in indice


def test_sumario_conta_documentos_e_atos_separados(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")

    sumario = (tmp_path / "index.md").read_text(encoding="utf-8")
    linha = next(l for l in sumario.splitlines() if "**Processo**" in l)
    assert "1 documento(s) do acervo" in linha
    assert "1 página(s) do Planalto" in linha
    assert "fora do pacote" in sumario


def test_legislacao_fica_fora_do_zip_por_padrao(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    config = _config(tmp_path)
    generate_index_md(conn, config, "pt")

    nomes = _nomes_do_zip(config)
    assert group_index_filename("Processo") in nomes
    assert "legislacao-Processo.md" not in nomes


def test_instrucoes_mandam_buscar_legislacao_no_planalto(tmp_path):
    conn = _acervo_com_lei(tmp_path)
    config = _config(tmp_path, existing_instructions="MINHAS REGRAS ANTIGAS")

    texto = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "normas-citadas.md" in texto
    assert "1 página" in texto
    assert texto.index("MINHAS REGRAS ANTIGAS") < texto.index("normas-citadas.md")


def test_acervo_sem_planalto_nao_ganha_legislacao(tmp_path):
    """Um acervo só de PDFs não muda de cara."""
    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    config = _config(tmp_path)

    generate_all_artifacts(conn, config, "pt")

    assert list(tmp_path.glob("legislacao-*.md")) == []
    sumario = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "Planalto" not in sumario
    instrucoes = (tmp_path / "project_instructions.md").read_text(encoding="utf-8")
    assert "normas-citadas.md" not in instrucoes


def test_config_antiga_sem_campo_carrega_com_padrao(tmp_path):
    config = load_config({"name": "a", "source_folder": str(tmp_path), "output_folder": str(tmp_path)})
    assert config.package_token_limit == 2_000_000
    assert config.timeline_split_items == 2000


def _app_com_projeto(tmp_path, monkeypatch):
    """Servidor de teste com um projeto pronto, no mesmo isolamento da fase 18."""
    from fastapi.testclient import TestClient

    from gclaude_indexer import paths
    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json
    from gclaude_indexer.web.app import app

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _banco(saida, "project.db")
    config = ProjectConfig(name="acervo", source_folder=str(origem), output_folder=str(saida))
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-11-01T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()
    _peca(conn, "Processo", 5, 5, "LEI", "lei.htm", engine="structured")
    entry = register_project(config.name, str(saida))
    return TestClient(app), entry.id, conn, config


# --- Tarefa 2: a cronologia não repete o índice ------------------------------


def _cronologia(tmp_path, config) -> str:
    return (tmp_path / "timeline.md").read_text(encoding="utf-8")


def test_cronologia_exclui_atos_do_planalto(tmp_path):
    """Quase todas as linhas da cronologia eram o índice do grupo
    reordenado por data."""
    conn = _acervo_com_lei(tmp_path)
    config = _config(tmp_path)

    generate_timeline_md(conn, config, "pt")
    texto = _cronologia(tmp_path, config)
    assert "1990-07-11" not in texto and "LAUDO" in texto
    assert "2 peça(s) com data identificada" in texto


def test_grupo_grande_ganha_cronologia_propria(tmp_path):
    conn = _banco(tmp_path)
    for folha in (1, 2, 3):
        _peca(conn, "Processo", folha, folha, "OFÍCIO", "vol1.pdf", data=f"2026-01-0{folha}")
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf", data="2026-02-01")
    config = _config(tmp_path, timeline_split_items=2)

    caminhos = generate_timeline_md(conn, config, "pt")

    assert [c.name for c in caminhos] == ["timeline.md", group_timeline_filename("Processo")]
    principal = _cronologia(tmp_path, config)
    proprio = (tmp_path / group_timeline_filename("Processo")).read_text(encoding="utf-8")
    assert "2026-02-01" in principal and "2026-01-02" not in principal
    assert "2026-01-02" in proprio and "2026-02-01" not in proprio
    assert f"`{group_timeline_filename('Processo')}`" in principal
    assert "3 peça(s)" in principal


def test_linha_da_cronologia_sem_coluna_origem(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    generate_timeline_md(conn, _config(tmp_path), "pt")

    linhas = _cronologia(tmp_path, _config(tmp_path)).splitlines()
    cabecalho = next(l for l in linhas if l.startswith("| "))
    assert cabecalho == "| Data | Tipo | Referência | Agrupador | Resumo |"
    assert "|---|---|---|---|---|" in linhas
    assert "| f. 1 – f. 2 (anexo.pdf, p. 1) |" in next(l for l in linhas if "ATA" in l)


def test_cronologia_orfa_e_apagada(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 1, "LAUDO", "vol1.pdf")
    orfao = tmp_path / group_timeline_filename("Velho")
    orfao.write_text("x", encoding="utf-8")

    generate_timeline_md(conn, _config(tmp_path), "pt")

    assert not orfao.exists()


def test_generate_all_registra_a_cronologia_por_grupo(tmp_path):
    conn = _banco(tmp_path)
    for folha in (1, 2, 3):
        _peca(conn, "Processo", folha, folha, "OFÍCIO", "vol1.pdf", data=f"2026-01-0{folha}")
    escritos = generate_all_artifacts(conn, _config(tmp_path, timeline_split_items=2), "pt")
    assert f"timeline:{group_timeline_filename('Processo')[:-3]}" in escritos


def test_cronologia_por_grupo_fica_fora_do_zip(tmp_path):
    """Num acervo grande o timeline-<grupo>.md tinha centenas de milhares de
    tokens e repetia o índice do grupo por data: sozinho fazia o total do
    pacote crescer em cerca de 40%. Fica na pasta, fora do pacote."""
    conn = _banco(tmp_path)
    for folha in (1, 2, 3):
        _peca(conn, "Processo", folha, folha, "OFÍCIO", "vol1.pdf", data=f"2026-01-0{folha}")
    config = _config(tmp_path, timeline_split_items=2)
    generate_timeline_md(conn, config, "pt")
    assert (tmp_path / group_timeline_filename("Processo")).exists()
    assert group_timeline_filename("Processo") not in _nomes_do_zip(config)
    assert "timeline.md" in _nomes_do_zip(config)


def test_orcamento_lista_o_que_ficou_fora_do_pacote(tmp_path):
    """A tela diz que o arquivo existe e pode ser enviado à parte."""
    from gclaude_indexer.claude_package import budget

    conn = _acervo_com_lei(tmp_path)
    for folha in (1, 2, 3):
        _peca(conn, "Avulsos", folha, folha, "OFÍCIO", "anexo.pdf", data=f"2026-01-0{folha}")
    config = _config(tmp_path, timeline_split_items=2)
    generate_all_artifacts(conn, config, "pt")

    orcamento = budget(config)
    fora = {e.name for e in orcamento.outside}
    assert fora == {group_timeline_filename("Avulsos")}
    assert not fora & {e.name for e in orcamento.entries}
    assert all(e.tokens > 0 for e in orcamento.outside)


def test_tela_de_resultado_mostra_os_arquivos_fora_do_pacote(tmp_path, monkeypatch):
    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    for folha in (1, 2, 3):
        _peca(conn, "Avulsos", folha, folha, "OFÍCIO", "anexo.pdf", data=f"2026-01-0{folha}")
    config.timeline_split_items = 2
    from gclaude_indexer.project import save_project_config
    save_project_config(conn, config)
    generate_all_artifacts(conn, config, "pt")

    corpo = cliente.get(f"/projects/{projeto_id}/result").text
    assert 'id="package-outside"' in corpo
    assert group_timeline_filename("Avulsos") in corpo[corpo.index('id="package-outside"'):]


def test_guia_explica_a_cronologia_por_grupo_fora_do_pacote(tmp_path):
    import io
    import zipfile

    from gclaude_indexer.claude_package import GUIDE_FILENAME

    config = _config(tmp_path)
    for idioma in ("pt", "en", "es"):
        with zipfile.ZipFile(io.BytesIO(generate_claude_project_package(config, idioma))) as z:
            guia = z.read(GUIDE_FILENAME).decode("utf-8")
        assert "timeline-<" in guia
        assert any(p in guia for p in ("à parte", "separately", "por separado"))


# --- Tarefa 3: orçamento de tokens antes de empacotar -------------------------


def test_orcamento_lista_o_que_vai_no_zip(tmp_path):
    from gclaude_indexer.claude_package import GUIDE_FILENAME, budget

    conn = _acervo_com_lei(tmp_path)
    config = _config(tmp_path)
    generate_all_artifacts(conn, config, "pt")

    nomes = [entrada.name for entrada in budget(config).entries]
    assert nomes == [n for n in _nomes_do_zip(config) if n != GUIDE_FILENAME]
    assert "legislacao-Processo.md" not in nomes


def test_orcamento_estima_a_3_caracteres_por_token(tmp_path):
    """3,0 é estimativa conservadora para o Claude em markdown tabular em
    português (pouco acima de 3 na prática); o 1,45 da fase 21 é do modelo local."""
    from gclaude_indexer.claude_package import CLAUDE_CHARS_PER_TOKEN, budget

    assert CLAUDE_CHARS_PER_TOKEN == 3.0
    (tmp_path / "index.md").write_bytes(b"x" * 3000)
    orcamento = budget(_config(tmp_path))
    assert orcamento.entries[0].size_bytes == 3000
    assert orcamento.entries[0].tokens == 1000
    assert orcamento.total_tokens == 1000
    assert orcamento.level == "ok"


def test_orcamento_nivel_rag_acima_de_500_mil(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    assert claude_package.RAG_THRESHOLD_TOKENS == 500_000
    monkeypatch.setattr(claude_package, "RAG_THRESHOLD_TOKENS", 100)
    (tmp_path / "index.md").write_bytes(b"x" * 600)
    assert claude_package.budget(_config(tmp_path)).level == "rag"


def test_orcamento_nivel_over_acima_do_limite(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    monkeypatch.setattr(claude_package, "RAG_THRESHOLD_TOKENS", 100)
    (tmp_path / "index.md").write_bytes(b"x" * 600)
    orcamento = claude_package.budget(_config(tmp_path, package_token_limit=150))
    assert orcamento.level == "over"
    assert orcamento.limit_tokens == 150


def test_orcamento_marca_arquivo_acima_de_30_mb(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    assert claude_package.MAX_FILE_BYTES == 30 * 1024 * 1024
    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 100)
    (tmp_path / "index.md").write_bytes(b"x" * 50)
    (tmp_path / "timeline.md").write_bytes(b"x" * 150)
    orcamento = claude_package.budget(_config(tmp_path))
    por_nome = {e.name: e for e in orcamento.entries + orcamento.excluded}
    assert por_nome["index.md"].too_big is False
    assert por_nome["timeline.md"].too_big is True


def test_orcamento_de_pasta_vazia(tmp_path):
    from gclaude_indexer.claude_package import budget

    orcamento = budget(_config(tmp_path))
    assert orcamento.entries == []
    assert orcamento.total_tokens == 0
    assert orcamento.level == "ok"


def test_tela_de_resultado_mostra_o_orcamento(tmp_path, monkeypatch):
    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    generate_all_artifacts(conn, config, "pt")

    corpo = cliente.get(f"/projects/{projeto_id}/result").text

    assert 'id="package-budget"' in corpo
    inicio = corpo.index('id="package-budget"')
    assert "index.md" in corpo[inicio:] and group_index_filename("Processo") in corpo[inicio:]
    assert 'data-budget-level="ok"' in corpo


def test_tela_de_resultado_avisa_arquivo_grande_sem_travar_o_botao(tmp_path, monkeypatch):
    from gclaude_indexer import claude_package

    cliente, projeto_id, conn, config = _app_com_projeto(tmp_path, monkeypatch)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    generate_all_artifacts(conn, config, "pt")
    monkeypatch.setattr(claude_package, "MAX_FILE_BYTES", 10)

    corpo = cliente.get(f"/projects/{projeto_id}/result").text

    assert 'id="package-excluded"' in corpo
    assert "ficou fora" in corpo and "index.md" in corpo
    assert f"/projects/{projeto_id}/result/claude-package" in corpo


# --- Tarefa 4: índice de grupo grande fatiado em partes -----------------------


def _acervo_de_dois_volumes(tmp_path, grupo="Vol"):
    """Dois PDFs de 3 páginas no mesmo grupo, uma peça por página com
    resumo longo: cada bloco de arquivo tem ~500 bytes."""
    conn = _banco(tmp_path, arquivos=[("volA.pdf", "pdf", grupo, 3), ("volB.pdf", "pdf", grupo, 3)])
    for folha in range(1, 7):
        arquivo = "volA.pdf" if folha <= 3 else "volB.pdf"
        _peca(conn, grupo, folha, folha, f"TIPO{folha}", arquivo, resumo=f"peça {folha} " + "x" * 120)
    return conn


def _partes(tmp_path, prefixo="index-Vol-"):
    return sorted(p for p in tmp_path.glob(f"{prefixo}*.md"))


def test_indice_grande_e_fatiado_na_fronteira_do_arquivo(tmp_path, monkeypatch):
    from gclaude_indexer import artifacts

    assert artifacts.INDEX_PART_BYTES == 25 * 1024 * 1024
    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 700)
    conn = _acervo_de_dois_volumes(tmp_path)

    caminhos = generate_index_md(conn, _config(tmp_path), "pt")

    nomes = [c.name for c in caminhos]
    assert nomes == ["index.md", "index-Vol-1.md", "index-Vol-2.md"]
    parte1 = (tmp_path / "index-Vol-1.md").read_text(encoding="utf-8")
    parte2 = (tmp_path / "index-Vol-2.md").read_text(encoding="utf-8")
    assert "volB.pdf" not in parte1 and "volA.pdf" not in parte2
    assert all(f"TIPO{n}" in parte1 for n in (1, 2, 3))
    assert all(f"TIPO{n}" in parte2 for n in (4, 5, 6))
    for parte in (parte1, parte2):
        linhas = parte.splitlines()
        assert linhas[0].startswith("# ") and "|---|" in linhas[3]


def test_sumario_lista_as_partes_com_a_faixa_de_folhas(tmp_path, monkeypatch):
    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 700)
    conn = _acervo_de_dois_volumes(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")

    sumario = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "`index-Vol-1.md` — f. 1–3" in sumario
    assert "`index-Vol-2.md` — f. 4–6" in sumario


def test_partes_entram_em_usados_e_sobrevivem_a_limpeza(tmp_path, monkeypatch):
    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 700)
    conn = _acervo_de_dois_volumes(tmp_path)
    inteiro_antigo = tmp_path / "index-Vol.md"
    inteiro_antigo.write_text("de uma geração anterior", encoding="utf-8")

    generate_index_md(conn, _config(tmp_path), "pt")

    assert not inteiro_antigo.exists()
    assert [p.name for p in _partes(tmp_path)] == ["index-Vol-1.md", "index-Vol-2.md"]


def test_arquivo_de_origem_maior_que_o_corte_fica_inteiro(tmp_path, monkeypatch):
    """Um bloco nunca é dividido: a parte sai maior que o corte, sem laço
    nem parte vazia, e o orçamento avisa."""
    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 50)
    conn = _banco(tmp_path, arquivos=[("volA.pdf", "pdf", "Vol", 3)])
    for folha in (1, 2, 3):
        _peca(conn, "Vol", folha, folha, f"TIPO{folha}", "volA.pdf", resumo="y" * 100)

    caminhos = generate_index_md(conn, _config(tmp_path), "pt")

    assert [c.name for c in caminhos] == ["index.md", "index-Vol.md"]
    assert (tmp_path / "index-Vol.md").stat().st_size > 50


def test_parte_nao_colide_com_grupo_de_nome_numerado(tmp_path, monkeypatch):
    """Grupo `Vol-1` ao lado do grupo `Vol` fatiado: `index-Vol-1.md` é do
    grupo `Vol-1`, nunca uma parte de `Vol`."""
    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 700)
    conn = _acervo_de_dois_volumes(tmp_path)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key) "
        "VALUES ('outro.pdf','outro.pdf','pdf',1,'h9','extracted','Vol-1')"
    )
    conn.execute(
        "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
        "VALUES (3, 1, 'f. 1', 100, 0, 0, 'x')"
    )
    conn.commit()
    _peca(conn, "Vol-1", 1, 1, "ATA-ESPECIAL", "outro.pdf")

    generate_index_md(conn, _config(tmp_path), "pt")

    do_grupo_numerado = (tmp_path / "index-Vol-1.md").read_text(encoding="utf-8")
    assert "ATA-ESPECIAL" in do_grupo_numerado and "TIPO1" not in do_grupo_numerado
    demais = [p for p in _partes(tmp_path) if p.name != "index-Vol-1.md"]
    texto = "".join(p.read_text(encoding="utf-8") for p in demais)
    assert all(f"TIPO{n}" in texto for n in range(1, 7))


# --- Tarefa 5: linhas enxutas e instruções que descrevem as colunas -----------


def _indice_avulsos(tmp_path) -> list[str]:
    return (tmp_path / group_index_filename("Avulsos")).read_text(encoding="utf-8").splitlines()


def test_intervalo_sem_repetir_a_origem(tmp_path):
    """A coluna Intervalo repetia o arquivo que já está em Origem: 20 a
    30% do tamanho de cada linha."""
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    generate_index_md(conn, _config(tmp_path), "pt")

    linha = next(l for l in _indice_avulsos(tmp_path) if "ATA" in l)
    assert linha.startswith("| f. 1 – f. 2 (p. 1) |")
    assert linha.count("anexo.pdf") == 1


def test_intervalo_mantem_o_arquivo_quando_a_origem_difere(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf; outro.pdf")
    generate_index_md(conn, _config(tmp_path), "pt")

    linha = next(l for l in _indice_avulsos(tmp_path) if "ATA" in l)
    assert linha.startswith("| f. 1 – f. 2 (anexo.pdf, p. 1) |")


def test_confianca_omitida_quando_tudo_e_high(tmp_path):
    """`high` em 150.319 de 150.475 linhas: uma coluna que não informa."""
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    generate_index_md(conn, _config(tmp_path), "pt")

    linhas = _indice_avulsos(tmp_path)
    assert linhas[2] == "| Intervalo | Tipo | Data | Autor | Origem | Resumo |"
    assert linhas[3] == "|---|---|---|---|---|---|"
    assert "high" not in next(l for l in linhas if "ATA" in l)


def test_confianca_volta_com_peca_media(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf", confianca="medium")
    generate_index_md(conn, _config(tmp_path), "pt")

    linhas = _indice_avulsos(tmp_path)
    assert linhas[2] == "| Intervalo | Tipo | Data | Autor | Confiança | Origem | Resumo |"
    assert linhas[3] == "|---|---|---|---|---|---|---|"
    assert "| medium |" in next(l for l in linhas if "ATA" in l)


def test_confianca_volta_com_revisao_ligada(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    generate_index_md(conn, _config(tmp_path, review_low_confidence=True), "pt")

    assert "Confiança" in _indice_avulsos(tmp_path)[2]


def test_confianca_e_decidida_pelo_projeto_inteiro(tmp_path):
    """Uma peça média num grupo põe a coluna em todos: as instruções
    descrevem as colunas uma vez só."""
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    _peca(conn, "Processo", 1, 1, "LAUDO", "vol1.pdf", confianca="low")
    generate_index_md(conn, _config(tmp_path), "pt")

    assert "Confiança" in _indice_avulsos(tmp_path)[2]


def test_instrucoes_descrevem_as_colunas(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 1, 2, "ATA", "anexo.pdf")
    config = _config(tmp_path)

    texto = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "## Colunas dos arquivos" in texto
    assert "Intervalo" in texto and "(p. N)" in texto and "Origem" in texto
    assert "Referência" in texto and "Agrupador" in texto
    assert "Confiança" not in texto

    _peca(conn, "Avulsos", 2, 2, "OFÍCIO", "anexo.pdf", confianca="medium")
    texto = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "Confiança" in texto


# --- Passe de correção após a revisão -----------------------------------------


def test_exclusao_conhece_a_legislacao_e_a_cronologia_por_grupo():
    """"Excluir projeto com os arquivos" deixava `legislacao-*.md` e
    `timeline-*.md` para trás, e a pasta sobrevivia à exclusão."""
    from fnmatch import fnmatch

    from gclaude_indexer.deletion import GENERATED_FILES

    for nome in ("legislacao-Processo.md", "timeline-Processo.md", "index-Vol-2.md"):
        assert any(fnmatch(nome, padrao) for padrao in GENERATED_FILES), nome


def test_regras_ficam_antes_da_secao_de_colunas(tmp_path):
    """A regra da legislação aparecia sob o título "Colunas dos arquivos"."""
    conn = _acervo_com_lei(tmp_path)
    texto = generate_project_instructions_md(conn, _config(tmp_path), "pt").read_text(encoding="utf-8")
    assert texto.index("normas-citadas.md") < texto.index("## Colunas dos arquivos")


def test_cronologia_mantem_o_arquivo_sem_pagina_fisica(tmp_path):
    """Sem a coluna Origem, uma peça fora do mapa de páginas perdia o nome
    do arquivo — e a regra da fonte original depende dele."""
    conn = _banco(tmp_path)
    _peca(conn, "Avulsos", 90, 91, "ATA", "anexo.pdf")
    generate_timeline_md(conn, _config(tmp_path), "pt")

    linha = next(l for l in _cronologia(tmp_path, _config(tmp_path)).splitlines() if "ATA" in l)
    assert "anexo.pdf" in linha


def test_orcamento_ignora_arquivo_apagado_no_meio(tmp_path, monkeypatch):
    """A limpeza de órfãos de uma regeneração em curso não pode virar
    erro 500 na tela de resultado."""
    from gclaude_indexer import claude_package

    (tmp_path / "index.md").write_bytes(b"x" * 300)
    monkeypatch.setattr(
        claude_package, "candidate_files",
        lambda config: [tmp_path / "index.md", tmp_path / "index-sumiu.md"],
    )
    orcamento = claude_package.budget(_config(tmp_path))
    assert [e.name for e in orcamento.entries] == ["index.md"]


# --- Minors que aparecem para o usuário ----------------------------------------


def test_textos_do_pacote_nao_falam_em_quatro_arquivos(tmp_path):
    """Desde a fase 21 o pacote leva um índice por grupo; agora também a
    cronologia por grupo e, por opção, a legislação. "Quatro arquivos" era
    da fase 6."""
    import io
    import zipfile

    from gclaude_indexer.claude_package import GUIDE_FILENAME
    from gclaude_indexer.i18n import translate

    config = _config(tmp_path)
    proibidas = ("quatro arquivos", "four files", "cuatro archivos", "os quatro", "the four", "los cuatro")
    for idioma in ("pt", "en", "es"):
        with zipfile.ZipFile(io.BytesIO(generate_claude_project_package(config, idioma))) as z:
            guia = z.read(GUIDE_FILENAME).decode("utf-8").lower()
        textos = [guia, translate(idioma, "result.package_text").lower(), translate(idioma, "help.result.p3").lower()]
        for texto in textos:
            assert not any(p in texto for p in proibidas), (idioma, texto[:120])


def test_partes_na_colisao_levam_o_mesmo_sufixo(tmp_path, monkeypatch):
    """Na colisão `Vol`/`Vol-1`, a parte 1 saía `index-Vol-1-<hash>.md` e a
    parte 2 `index-Vol-2.md`: todas as partes do grupo levam o mesmo
    sufixo, `index-Vol-<hash>-1.md`, `-2.md`."""
    import re

    from gclaude_indexer import artifacts

    monkeypatch.setattr(artifacts, "INDEX_PART_BYTES", 700)
    conn = _acervo_de_dois_volumes(tmp_path)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key) "
        "VALUES ('outro.pdf','outro.pdf','pdf',1,'h9','extracted','Vol-1')"
    )
    conn.execute(
        "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
        "VALUES (3, 1, 'f. 1', 100, 0, 0, 'x')"
    )
    conn.commit()
    _peca(conn, "Vol-1", 1, 1, "ATA-ESPECIAL", "outro.pdf")

    caminhos = generate_index_md(conn, _config(tmp_path), "pt")

    partes = sorted(c.name for c in caminhos if c.name not in ("index.md", "index-Vol-1.md"))
    assert len(partes) == 2
    sufixos = {re.fullmatch(r"index-Vol-([0-9a-f]{6})-([12])\.md", nome) for nome in partes}
    assert all(sufixos), partes
    assert len({m.group(1) for m in sufixos}) == 1, "mesmo sufixo nas duas partes"
    assert {m.group(2) for m in sufixos} == {"1", "2"}


# --- Ajuste 2: página do Planalto que o leitor não reconheceu ------------------


def _acervo_com_pasta_de_legislacao(tmp_path):
    """Num acervo grande, milhares de peças vinham de páginas .htm da mesma pasta
    dos atos reconhecidos (`Direito/Legislacao/...`) que o `planalto.py`
    não leu — retificações, mensagens, decretos fora do padrão — e o modelo
    classificou. Elas quase dobravam o índice do pacote.

    Os atos reconhecidos ficam em subpastas diferentes (Decretos e Leis), como
    costuma acontecer: a pasta de legislação é a raiz comum, `Direito/Legislacao`."""
    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    arquivos = [
        ("Direito/Legislacao/Decretos/1967/d1.htm", "d1.htm", "htm"),
        ("Direito/Legislacao/Leis/1990/l5.htm", "l5.htm", "htm"),
        ("Direito/Legislacao/Retificacoes/ret2.htm", "ret2.htm", "htm"),
        ("Manuais/guia.htm", "guia.htm", "htm"),
        ("vol1.pdf", "vol1.pdf", "pdf"),
    ]
    for ordem, (rel, nome, ext) in enumerate(arquivos, start=1):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, status, group_key) "
            "VALUES (?, ?, ?, 1, ?, 'extracted', 'G')", (rel, nome, ext, f"h{ordem}"),
        )
        conn.execute(
            "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text) "
            "VALUES (?, 1, 'p. 1', 100, 0, 0, 'x')", (ordem,),
        )
    conn.commit()
    _peca(conn, "G", 1, 1, "DECRETO", "d1.htm", engine="structured", data="1967-01-01", resumo="ato reconhecido")
    _peca(conn, "G", 2, 2, "LEI", "l5.htm", engine="structured", data="1990-05-05", resumo="lei reconhecida")
    _peca(conn, "G", 3, 3, "RETIFICAÇÃO", "ret2.htm", data="1983-12-02", resumo="retificação não reconhecida",
          confianca="medium")
    _peca(conn, "G", 4, 4, "MANUAL", "guia.htm", data="2020-01-01", resumo="manual interno em html")
    _peca(conn, "G", 5, 5, "OFÍCIO", "vol1.pdf", data="2026-01-01", resumo="documento do acervo")
    return conn


def test_pagina_htm_da_pasta_dos_atos_sai_do_indice(tmp_path):
    conn = _acervo_com_pasta_de_legislacao(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")

    indice = (tmp_path / group_index_filename("G")).read_text(encoding="utf-8")
    assert "retificação não reconhecida" not in indice and "ato reconhecido" not in indice
    assert "manual interno em html" in indice, "página .htm fora da pasta dos atos fica no índice"
    assert "documento do acervo" in indice


def test_sumario_conta_paginas_do_planalto(tmp_path):
    conn = _acervo_com_pasta_de_legislacao(tmp_path)
    generate_index_md(conn, _config(tmp_path), "pt")
    linha = next(l for l in (tmp_path / "index.md").read_text(encoding="utf-8").splitlines() if "**G**" in l)
    assert "2 documento(s) do acervo" in linha
    assert "3 página(s) do Planalto" in linha


def test_cronologia_e_confianca_seguem_a_mesma_regra(tmp_path):
    conn = _acervo_com_pasta_de_legislacao(tmp_path)
    config = _config(tmp_path)
    generate_all_artifacts(conn, config, "pt")

    cronologia = (tmp_path / "timeline.md").read_text(encoding="utf-8")
    assert "1983-12-02" not in cronologia and "2020-01-01" in cronologia
    assert "Confiança" not in (tmp_path / group_index_filename("G")).read_text(encoding="utf-8").splitlines()[2], (
        "a retificação de confiança média está fora do pacote"
    )
    instrucoes = (tmp_path / "project_instructions.md").read_text(encoding="utf-8")
    assert "3 página" in instrucoes


def test_grupo_sem_ato_reconhecido_mantem_as_paginas_htm_no_indice(tmp_path):
    """Sem ato reconhecido não há pasta de legislação: nada muda."""
    conn = _acervo_com_pasta_de_legislacao(tmp_path)
    conn.execute("DELETE FROM item WHERE engine = 'structured'")
    conn.commit()
    generate_index_md(conn, _config(tmp_path), "pt")

    indice = (tmp_path / group_index_filename("G")).read_text(encoding="utf-8")
    assert "retificação não reconhecida" in indice

"""Phase 6 tests: importing items and generating output artifacts."""

from __future__ import annotations

import json

import fitz

from gclaude_indexer.artifacts import (
    generate_review_md,
    generate_timeline_md,
    generate_index_md,
    generate_project_instructions_md,
    generate_all_artifacts,
)
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.import_items import import_and_consolidate
from gclaude_indexer.scanning import scan


def _pdf(caminho, n_paginas, texto="Texto nativo de teste com bastante conteúdo para não acionar OCR nenhum."):
    documento = fitz.open()
    for indice in range(n_paginas):
        pagina = documento.new_page()
        pagina.insert_textbox((50, 50, 550, 750), f"{texto} (pagina {indice + 1})", fontsize=12)
    documento.save(caminho)
    documento.close()


def _projeto_com_paginas(tmp_path, n_paginas=6):
    """Projeto com um agrupador 'volume_1' de N páginas já extraídas — só o
    necessário para validar intervalo e gerar os artefatos, sem depender de
    janelas nem do motor de classificação."""
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"
    _pdf(origem / "volume_1" / "peca.pdf", n_paginas)

    config = load_config({"name": "Fase 6", "subject": "Acervo de teste", "source_folder": str(origem), "output_folder": str(saida)})
    conn = connect(saida / "project.db")
    init_schema(conn)

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)

    return origem, saida, config, conn


def _escrever_jsonl(saida, linhas: list[dict | str]):
    caminho = saida / "raw_items.jsonl"
    with open(caminho, "a", encoding="utf-8") as arquivo:
        for linha in linhas:
            if isinstance(linha, str):
                arquivo.write(linha + "\n")
            else:
                arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")


def _peca(**sobrescreve) -> dict:
    base = {
        "window": "volume_1::000001-000006",
        "group": "volume_1",
        "ref_start": "f. 1",
        "ref_end": "f. 1",
        "order_start": 1,
        "order_end": 1,
        "type": "OFÍCIO",
        "date": "2024-03-15",
        "author": None,
        "summary": "resumo de teste",
        "has_table": False,
        "has_image": False,
        "engine": "rules",
        "confidence": "high",
        "files": "peca.pdf",
    }
    base.update(sobrescreve)
    return base


# --- validação -------------------------------------------------------------


def test_linha_json_invalida_e_ignorada_com_evento(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(saida, ["{isto nao e json valido"])

    resultado = import_and_consolidate(conn, config)

    assert resultado.lines_read == 1
    assert resultado.invalid_lines == 1
    assert resultado.consolidated_items == 0

    eventos_erro = [e for e in list_events(conn, step="import") if e["level"] == "error"]
    assert len(eventos_erro) == 1
    assert "JSON inválido" in eventos_erro[0]["message"]

    conn.close()


def test_campo_obrigatorio_ausente_e_rejeitado(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    peca_sem_agrupador = _peca()
    del peca_sem_agrupador["group"]
    _escrever_jsonl(saida, [peca_sem_agrupador])

    resultado = import_and_consolidate(conn, config)
    assert resultado.invalid_lines == 1
    assert resultado.consolidated_items == 0

    conn.close()


def test_data_em_formato_invalido_e_rejeitada(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(saida, [_peca(date="15/03/2024")])  # não é ISO

    resultado = import_and_consolidate(conn, config)
    assert resultado.invalid_lines == 1

    eventos_erro = [e for e in list_events(conn, step="import") if e["level"] == "error"]
    assert any("data" in e["message"] for e in eventos_erro)

    conn.close()


def test_intervalo_fora_do_agrupador_e_rejeitado(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    _escrever_jsonl(saida, [_peca(order_start=40, order_end=41, ref_start="f. 40", ref_end="f. 41")])

    resultado = import_and_consolidate(conn, config)
    assert resultado.invalid_lines == 1

    eventos_erro = [e for e in list_events(conn, step="import") if e["level"] == "error"]
    assert any("fora do intervalo" in e["message"] for e in eventos_erro)

    conn.close()


def test_linha_invalida_nao_impede_as_demais(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(
        saida,
        [
            "não é json",
            _peca(ref_start="f. 2", ref_end="f. 2", order_start=2, order_end=2),
        ],
    )

    resultado = import_and_consolidate(conn, config)
    assert resultado.invalid_lines == 1
    assert resultado.consolidated_items == 1

    conn.close()


# --- duplicata e peça partida ---------------------------------------------


def test_duplicata_de_sobreposicao_e_descartada(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    # a mesma peça, vista por duas janelas vizinhas que se sobrepõem
    _escrever_jsonl(
        saida,
        [
            _peca(window="volume_1::000001-000004", ref_start="f. 1", ref_end="f. 2", order_start=1, order_end=2),
            _peca(window="volume_1::000003-000006", ref_start="f. 1", ref_end="f. 2", order_start=1, order_end=2),
        ],
    )

    resultado = import_and_consolidate(conn, config)
    assert resultado.valid_items == 2
    assert resultado.consolidated_items == 1  # uma das duas foi descartada como duplicata

    peca = conn.execute("SELECT * FROM item").fetchone()
    assert peca["start_order"] == 1 and peca["end_order"] == 2

    conn.close()


def test_peca_partida_entre_janelas_e_colada(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    # janela 1 viu a peça completa (f.1-f.4); janela 2, sem o contexto da
    # janela 1, só viu o fragmento final (f.4-f.4) como página solta
    _escrever_jsonl(
        saida,
        [
            _peca(
                window="volume_1::000001-000004", ref_start="f. 1", ref_end="f. 4",
                order_start=1, order_end=4, type="MEMORANDO", confidence="high", summary="assunto do memorando",
            ),
            _peca(
                window="volume_1::000004-000006", ref_start="f. 4", ref_end="f. 4",
                order_start=4, order_end=4, type=None, confidence="low", summary=None, author="Fulano de Tal",
            ),
        ],
    )

    resultado = import_and_consolidate(conn, config)
    assert resultado.valid_items == 2
    assert resultado.consolidated_items == 1

    peca = conn.execute("SELECT * FROM item").fetchone()
    assert peca["start_order"] == 1
    assert peca["end_order"] == 4  # colada, não truncada em f.3
    assert peca["type"] == "MEMORANDO"
    assert peca["confidence"] == "high"  # herdou a confiança do fragmento mais confiável
    assert peca["author"] == "Fulano de Tal"  # preenchido a partir do fragmento que tinha essa informação
    assert peca["summary"] == "assunto do memorando"

    conn.close()


def test_pecas_de_tipos_diferentes_sobrepostos_nao_sao_coladas(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    _escrever_jsonl(
        saida,
        [
            _peca(ref_start="f. 1", ref_end="f. 3", order_start=1, order_end=3, type="OFÍCIO"),
            _peca(ref_start="f. 3", ref_end="f. 5", order_start=3, order_end=5, type="DESPACHO"),
        ],
    )

    resultado = import_and_consolidate(conn, config)
    assert resultado.consolidated_items == 2  # tipos incompatíveis: não colar

    conn.close()


def test_importacao_e_idempotente_recalcula_do_zero(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(saida, [_peca()])

    import_and_consolidate(conn, config)
    resultado_segunda = import_and_consolidate(conn, config)

    assert resultado_segunda.consolidated_items == 1
    assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 1

    conn.close()


# --- artefatos -------------------------------------------------------------


def test_gerar_todos_os_artefatos_cria_os_quatro_arquivos(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(saida, [_peca()])
    import_and_consolidate(conn, config)

    caminhos = generate_all_artifacts(conn, config, "pt")

    assert set(caminhos) == {"index", "timeline", "review", "project_instructions"}
    for caminho in caminhos.values():
        assert caminho.exists()
        assert caminho.stat().st_size > 0

    conn.close()


def test_indice_lista_peca_por_agrupador(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    _escrever_jsonl(saida, [_peca(type="MEMORANDO", summary="resumo do memorando")])
    import_and_consolidate(conn, config)

    conteudo = generate_index_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "## volume_1" in conteudo
    assert "MEMORANDO" in conteudo
    assert "resumo do memorando" in conteudo


def test_cronologia_so_lista_pecas_com_data(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    _escrever_jsonl(
        saida,
        [
            _peca(ref_start="f. 1", ref_end="f. 1", order_start=1, order_end=1, date="2024-03-15"),
            _peca(ref_start="f. 5", ref_end="f. 5", order_start=5, order_end=5, date=None),
        ],
    )
    import_and_consolidate(conn, config)

    conteudo = generate_timeline_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "2024-03-15" in conteudo
    assert "1 peça(s) com data identificada" in conteudo


def test_conferencia_acusa_zero_lacunas_quando_cobertura_completa(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=4)
    _escrever_jsonl(saida, [_peca(ref_start="f. 1", ref_end="f. 4", order_start=1, order_end=4)])
    import_and_consolidate(conn, config)

    conteudo = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "Nenhuma lacuna encontrada." in conteudo


def test_conferencia_acusa_lacuna_real(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    # cobre só f.1-f.2 e f.5-f.6: faltam f.3 e f.4
    _escrever_jsonl(
        saida,
        [
            _peca(ref_start="f. 1", ref_end="f. 2", order_start=1, order_end=2),
            _peca(ref_start="f. 5", ref_end="f. 6", order_start=5, order_end=6),
        ],
    )
    import_and_consolidate(conn, config)

    conteudo = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "volume_1" in conteudo
    assert "3-4" in conteudo


def test_conferencia_lista_arquivo_com_falha(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)
    (origem / "corrompido.pdf").write_bytes(b"nao e um pdf valido")
    scan(conn, config)
    convert(conn, config)

    conteudo = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "corrompido.pdf" in conteudo


def test_instrucoes_projeto_contem_regra_de_fonte_original(tmp_path):
    origem, saida, config, conn = _projeto_com_paginas(tmp_path)

    conteudo = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "nunca do índice" in conteudo
    assert "arquivo original" in conteudo
    assert config.name in conteudo


def test_instrucoes_projeto_usa_papel_e_regras_do_formulario(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "origem_indexado"
    config = load_config(
        {
            "name": "Projeto com papel customizado",
            "source_folder": str(origem),
            "output_folder": str(saida),
            "role_instructions": "Você é um assistente jurídico especializado em direito administrativo.",
            "extra_rules": "Sempre cite o número do processo.",
        }
    )
    conn = connect(saida / "project.db")
    init_schema(conn)

    conteudo = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "assistente jurídico especializado" in conteudo
    assert "Sempre cite o número do processo." in conteudo

    conn.close()

"""Phase 5 tests: the `rules` classification engine."""

from __future__ import annotations

import json

import fitz

from gclaude_indexer.classification import WindowPage, validate_item
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.windows_prep import prepare_windows
from gclaude_indexer.engine_rules import DEFAULT_RULES_PATH, RulesEngine, load_rules, classify_pending
from gclaude_indexer.scanning import scan


def _pagina(texto, referencia="f. 1", arquivo_nome="doc.pdf", tem_tabela=False, n_imagens=0):
    return WindowPage(
        reference=referencia, file_name=arquivo_nome, text=texto, has_table=tem_tabela, image_count=n_imagens
    )


def _motor():
    return RulesEngine(load_rules())


# --- config editável -------------------------------------------------------


def test_dicionario_de_regras_vem_de_arquivo_editavel_fora_do_codigo():
    assert DEFAULT_RULES_PATH.exists()
    regras = load_rules()
    assert "OFÍCIO" in regras.types
    assert "MEMORANDO" in regras.types
    assert len(regras.date_patterns) == 3


# --- datas -----------------------------------------------------------------


def test_data_formato_barra():
    pecas = _motor().classify([_pagina("OFÍCIO No 1\nEmitido em 15/05/2024 pelo setor.", "f. 1")])
    assert pecas[0].date == "2024-05-15"


def test_data_formato_ponto():
    pecas = _motor().classify([_pagina("OFÍCIO No 1\nEmitido em 15.05.2024 pelo setor.", "f. 1")])
    assert pecas[0].date == "2024-05-15"


def test_data_por_extenso():
    pecas = _motor().classify([_pagina("OFÍCIO No 1\nEmitido em 15 de maio de 2024.", "f. 1")])
    assert pecas[0].date == "2024-05-15"


def test_data_invalida_no_calendario_e_rejeitada():
    pecas = _motor().classify([_pagina("OFÍCIO No 1\nData: 31/02/2024 (inválida).", "f. 1")])
    assert pecas[0].date is None


# --- tipo e confiança --------------------------------------------------


def test_tipo_marcado_no_inicio_da_pagina_gera_confianca_alta():
    pecas = _motor().classify(
        [_pagina("MEMORANDO No 7\nAssunto: encaminhamento de documentos ao setor competente.", "f. 1")]
    )
    assert len(pecas) == 1
    assert pecas[0].type == "MEMORANDO"
    assert pecas[0].confidence == "high"


def test_tipo_do_inicio_da_pagina_vence_marcador_que_aparece_so_no_corpo():
    """Regressão: 'DESPACHO' no começo da página deve vencer 'PARECER'
    aparecendo só depois, dentro de 'conforme parecer técnico anexo' — o
    marcador mais próximo do início real da página vence, não o primeiro
    encontrado na ordem do dicionário de tipos."""
    pecas = _motor().classify(
        [_pagina("DESPACHO\nDefiro o pedido conforme parecer técnico anexo aos autos.\n02.04.2024", "f. 1")]
    )
    assert len(pecas) == 1
    assert pecas[0].type == "DESPACHO"


def test_pagina_sem_marcador_algum_entra_na_peca_anterior_com_confianca_baixa():
    paginas = [
        _pagina("OFÍCIO No 178\nAssunto: solicitação de informações ao setor.", "f. 1"),
        _pagina("Página de continuação, mantendo o mesmo assunto, sem qualquer marcador novo aqui.", "f. 2"),
    ]
    pecas = _motor().classify(paginas)

    assert len(pecas) == 1  # a página 2 não abre peça nova, entra na mesma
    assert pecas[0].start_ref == "f. 1"
    assert pecas[0].end_ref == "f. 2"
    assert pecas[0].confidence == "low"  # rebaixada pela página sem marcador


def test_pagina_em_branco_anterior_abre_nova_peca():
    paginas = [
        _pagina("Texto qualquer, sem marcador de tipo reconhecido nesta página.", "f. 1"),
        _pagina("   \n  \n", "f. 2"),  # página em branco
        _pagina("Outro texto qualquer, também sem marcador de tipo.", "f. 3"),
    ]
    pecas = _motor().classify(paginas)

    assert len(pecas) == 2
    assert pecas[0].start_ref == "f. 1" and pecas[0].end_ref == "f. 2"
    assert pecas[0].confidence == "low"  # página 1 já não tinha marcador nenhum
    assert pecas[1].start_ref == "f. 3" and pecas[1].end_ref == "f. 3"
    assert pecas[1].confidence == "medium"  # abriu por sinal fraco (branco anterior), sem tipo


def test_toda_peca_recebe_algum_nivel_de_confianca():
    paginas = [_pagina("Texto solto qualquer, nada de especial aqui.", "f. 1")]
    pecas = _motor().classify(paginas)
    assert pecas[0].confidence in {"high", "medium", "low"}


# --- resumo e autor ------------------------------------------------------


def test_resumo_por_marcador_assunto():
    pecas = _motor().classify(
        [_pagina("OFÍCIO No 1\nAssunto: pedido de esclarecimentos sobre o processo em tramitação.", "f. 1")]
    )
    assert pecas[0].summary == "pedido de esclarecimentos sobre o processo em tramitação."


def test_resumo_cai_para_primeira_frase_longa_sem_marcador():
    texto = "Curto. Esta é uma frase razoavelmente longa que deve servir de resumo padrão."
    pecas = _motor().classify([_pagina(f"DESPACHO\n{texto}", "f. 1")])
    assert pecas[0].summary is not None
    assert len(pecas[0].summary) > 40


def test_autor_por_marcador_de_rodape_mesma_linha():
    pecas = _motor().classify(
        [_pagina("DESPACHO\nDefiro o pedido.\nResponsável: Fulano de Tal", "f. 1")]
    )
    assert pecas[0].author == "Fulano de Tal"


def test_autor_por_bloco_de_assinatura_linha_seguinte():
    pecas = _motor().classify(
        [_pagina("DESPACHO\nDefiro o pedido conforme parecer.\nAtenciosamente,\nCiclana da Silva", "f. 1")]
    )
    assert pecas[0].author == "Ciclana da Silva"


# --- sinais estruturais e metadados --------------------------------------


def test_tem_tabela_e_tem_imagem_agregam_por_ou_entre_paginas():
    paginas = [
        _pagina("PARECER\ntexto da primeira página.", "f. 1", tem_tabela=False, n_imagens=0),
        _pagina("continuação com uma tabela embutida.", "f. 2", tem_tabela=True, n_imagens=2),
    ]
    pecas = _motor().classify(paginas)
    assert len(pecas) == 1
    assert pecas[0].has_table is True
    assert pecas[0].has_image is True


def test_arquivos_da_peca_lista_nomes_unicos_em_ordem():
    paginas = [
        _pagina("PARECER\ntexto.", "f. 1", arquivo_nome="a.pdf"),
        _pagina("continuação.", "f. 2", arquivo_nome="a.pdf"),
        _pagina("continuação em outro arquivo.", "f. 3", arquivo_nome="b.pdf"),
    ]
    pecas = _motor().classify(paginas)
    assert len(pecas) == 1
    assert pecas[0].files == ["a.pdf", "b.pdf"]


def test_motor_sempre_regras():
    pecas = _motor().classify([_pagina("PARECER\ntexto qualquer.", "f. 1")])
    assert pecas[0].engine == "rules"


# --- validação da seção 7 -------------------------------------------------


def test_validar_peca_aceita_peca_bem_formada():
    peca = {
        "group": "volume_1",
        "ref_start": "f. 1",
        "ref_end": "f. 2",
        "order_start": 1,
        "order_end": 2,
        "type": "OFÍCIO",
        "date": "2024-05-15",
        "author": None,
        "summary": None,
        "has_table": False,
        "has_image": False,
        "engine": "rules",
        "confidence": "high",
        "files": "a.pdf",
    }
    assert validate_item(peca) == []


def test_validar_peca_rejeita_data_fora_do_iso():
    peca = {
        "group": "volume_1", "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": None,
        "date": "15/05/2024", "author": None, "summary": None,
        "has_table": False, "has_image": False, "engine": "rules",
        "confidence": "high", "files": "a.pdf",
    }
    assert validate_item(peca) != []


def test_validar_peca_rejeita_confianca_invalida():
    peca = {
        "group": "volume_1", "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": None,
        "date": None, "author": None, "summary": None,
        "has_table": False, "has_image": False, "engine": "rules",
        "confidence": "certeza_absoluta", "files": "a.pdf",
    }
    assert validate_item(peca) != []


# --- pipeline completo -----------------------------------------------------


def _pdf(caminho, paginas_textos):
    documento = fitz.open()
    for texto in paginas_textos:
        pagina = documento.new_page()
        pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def test_classificar_pendentes_grava_jsonl_e_marca_janela_feita(tmp_path):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"

    _pdf(
        origem / "volume_1" / "peca.pdf",
        [
            "OFÍCIO No 1\nAssunto: abertura do processo administrativo.\n10/01/2024",
            "PARECER\nAssunto: análise técnica do pedido apresentado nos autos.\n12/01/2024",
        ],
    )

    config = load_config(
        {
            "name": "Fase 5", "source_folder": str(origem), "output_folder": str(saida),
            "pages_per_window": 5, "overlap": 1,
        }
    )
    conn = connect(saida / "project.db")
    init_schema(conn)

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)

    resultado = classify_pending(conn, config)

    assert resultado.windows_processed == 1
    assert resultado.items_generated == 2
    assert resultado.invalid_items == 0

    janela = conn.execute("SELECT status FROM window").fetchone()
    assert janela["status"] == "done"

    caminho_jsonl = saida / "raw_items.jsonl"
    linhas = caminho_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    primeira = json.loads(linhas[0])
    assert primeira["engine"] == "rules"
    assert primeira["confidence"] in {"high", "medium", "low"}
    assert primeira["group"] == "volume_1"

    conn.close()


def test_classificar_pendentes_e_idempotente(tmp_path):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"
    _pdf(origem / "volume_1" / "peca.pdf", ["OFÍCIO No 1\nAssunto: teste.\n10/01/2024"])

    config = load_config({"name": "Fase 5", "source_folder": str(origem), "output_folder": str(saida)})
    conn = connect(saida / "project.db")
    init_schema(conn)

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    classify_pending(conn, config)

    total_linhas_antes = len((saida / "raw_items.jsonl").read_text(encoding="utf-8").splitlines())

    resultado_segunda = classify_pending(conn, config)
    assert resultado_segunda.windows_processed == 0

    total_linhas_depois = len((saida / "raw_items.jsonl").read_text(encoding="utf-8").splitlines())
    assert total_linhas_depois == total_linhas_antes

    conn.close()

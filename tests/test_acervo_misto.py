"""Acervos que misturam formatos: cada arquivo de documento inteiro é uma peça.

Três defeitos presos aqui, todos vistos no acervo de legislação do Planalto
(105 mil leis em HTML, uma por arquivo):

1. O motor de regras juntava leis consecutivas numa peça só — toda página
   começa por "Presidência da República", nenhum marcador de tipo casava
   com "LEI Nº", e a troca de arquivo não contava como sinal.
2. No tipo "biblioteca" a referência recomeça em "p. 1" a cada arquivo, e
   a posição da página no grupo era tirada dessa referência. Num grupo com
   vários arquivos, todas as peças tinham a mesma posição, e a
   consolidação as fundia.
3. O mapa de página física do índice, a cobertura e as lacunas usavam a
   mesma posição errada.
"""

from __future__ import annotations

import fitz

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.engine_rules import RulesEngine, classify_pending, load_rules
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.import_items import import_and_consolidate
from gclaude_indexer.scanning import scan
from gclaude_indexer.windows_prep import prepare_windows

CABECALHO = (
    "<p>Presidência da República</p><p>Casa Civil</p>"
    "<p>Subchefia para Assuntos Jurídicos</p>"
)


def _lei(numero: str, data: str, ementa: str, tachado: str = "") -> str:
    revogado = f"<p><strike>{tachado}</strike></p>" if tachado else ""
    return (
        f"<html><body>{CABECALHO}<p><b>LEI N<sup>o</sup> {numero}, DE {data}.</b></p>"
        f"<p>{ementa}</p><p>O PRESIDENTE DA REPÚBLICA Faço saber que o Congresso "
        f"Nacional decreta e eu sanciono a seguinte Lei:</p>{revogado}"
        f"<p>Art. 1º Esta Lei entra em vigor na data de sua publicação.</p></body></html>"
    )


def _pagina(texto: str, arquivo: str, ordem: int) -> WindowPage:
    return WindowPage(
        reference="p. 1", file_name=arquivo, text=texto, has_table=False, image_count=0, order=ordem,
    )


# --- motor de regras -----------------------------------------------------------


def test_cada_arquivo_html_vira_uma_peca_mesmo_sem_marcador():
    motor = RulesEngine(load_rules())
    texto = "Presidência da República\nCasa Civil\nTexto qualquer sem tipo reconhecível."
    paginas = [_pagina(texto, f"doc{i}.htm", i) for i in (1, 2, 3)]

    pecas = motor.classify(paginas)

    assert [p.files for p in pecas] == [["doc1.htm"], ["doc2.htm"], ["doc3.htm"]]
    assert [(p.start_order, p.end_order) for p in pecas] == [(1, 1), (2, 2), (3, 3)]


def test_paginas_de_um_mesmo_pdf_continuam_podendo_formar_uma_peca():
    motor = RulesEngine(load_rules())
    paginas = [
        WindowPage(reference=f"p. {n}", file_name="livro.pdf", text=f"continuação do capítulo {n}",
                   has_table=False, image_count=0, order=n)
        for n in (1, 2, 3)
    ]
    assert len(motor.classify(paginas)) == 1


def test_imagens_escaneadas_em_sequencia_podem_formar_uma_peca():
    motor = RulesEngine(load_rules())
    paginas = [
        WindowPage(reference=f"f. {n}", file_name=f"scan{n}.jpg", text=f"continuação {n}",
                   has_table=False, image_count=1, order=n)
        for n in (1, 2)
    ]
    assert len(motor.classify(paginas)) == 1


def test_epigrafe_legislativa_vira_tipo():
    motor = RulesEngine(load_rules())
    casos = {
        "LEI Nº 13.146, DE 6 DE JULHO DE 2015.": "LEI",
        "LEI COMPLEMENTAR Nº 101, DE 4 DE MAIO DE 2000.": "LEI COMPLEMENTAR",
        "DECRETO-LEI Nº 2.848, DE 7 DE DEZEMBRO DE 1940.": "DECRETO-LEI",
        "DECRETO Nº 9.830, DE 10 DE JUNHO DE 2019.": "DECRETO",
        "MEDIDA PROVISÓRIA Nº 1.154, DE 1º DE JANEIRO DE 2023.": "MEDIDA PROVISÓRIA",
        "EMENDA CONSTITUCIONAL Nº 132, DE 20 DE DEZEMBRO DE 2023": "EMENDA CONSTITUCIONAL",
        "LEI DE 15 DE OUTUBRO DE 1827.": "LEI",
    }
    for epigrafe, tipo in casos.items():
        texto = f"Presidência da República\nCasa Civil\nSubchefia para Assuntos Jurídicos\n{epigrafe}\nDispõe."
        [peca] = motor.classify([_pagina(texto, "a.htm", 1)])
        assert peca.type == tipo, epigrafe
        assert peca.confidence == "high"


def test_citacao_de_lei_no_meio_do_texto_nao_vira_tipo():
    motor = RulesEngine(load_rules())
    texto = "nos termos da Lei nº 8.112, de 11 de dezembro de 1990, fica deferido o pedido."
    [peca] = motor.classify([_pagina(texto, "a.pdf", 1)])
    assert peca.type is None


def test_data_com_ordinal_e_reconhecida():
    motor = RulesEngine(load_rules())
    texto = "MEDIDA PROVISÓRIA Nº 1.154, DE 1º DE JANEIRO DE 2023.\nEstabelece a organização."
    [peca] = motor.classify([_pagina(texto, "a.htm", 1)])
    assert peca.date == "2023-01-01"


# --- de ponta a ponta, acervo misto em "biblioteca" -----------------------------


def _projeto(tmp_path, tipo="biblioteca"):
    origem = tmp_path / "origem"
    (origem / "Leis").mkdir(parents=True)
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Misto",
        "source_folder": str(origem),
        "output_folder": str(saida),
        "extensions": ["pdf", "web_dados", "text", "docx"],
        "collection_type": tipo,
        "classification_engine": "rules",
        "pages_per_window": 4,
        "overlap": 1,
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


def _rodar(conn, config):
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    classify_pending(conn, config)
    return import_and_consolidate(conn, config)


def test_biblioteca_com_varios_arquivos_nao_funde_as_pecas(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path)
    pasta = origem / "Leis"
    (pasta / "l1.htm").write_bytes(_lei("1", "2 DE JANEIRO DE 2001", "Dispõe sobre a primeira matéria.").encode("cp1252"))
    (pasta / "l2.htm").write_bytes(
        _lei("2", "3 DE FEVEREIRO DE 2002", "Dispõe sobre a segunda matéria.", "Art. 2º Revogado.").encode("cp1252")
    )
    (pasta / "l3.html").write_text(_lei("3", "4 DE MARÇO DE 2003", "Dispõe sobre a terceira matéria."), encoding="utf-8")
    (pasta / "nota.txt").write_bytes("Nota técnica sobre as três leis acima, com observações gerais.".encode("cp1252"))
    documento = fitz.open()
    for n in range(3):
        documento.new_page().insert_text((72, 72), f"Análise jurídica contínua, página {n + 1}.")
    documento.save(pasta / "parecer.pdf")
    documento.close()

    _rodar(conn, config)

    pecas = conn.execute("SELECT * FROM item ORDER BY start_order").fetchall()
    por_arquivo = {p["files"]: p for p in pecas}
    assert set(por_arquivo) == {"l1.htm", "l2.htm", "l3.html", "nota.txt", "parecer.pdf"}
    assert por_arquivo["l1.htm"]["type"] == "LEI"
    assert por_arquivo["l1.htm"]["date"] == "2001-01-02"
    assert por_arquivo["l2.htm"]["date"] == "2002-02-03"
    assert por_arquivo["l3.html"]["date"] == "2003-03-04"
    assert (por_arquivo["parecer.pdf"]["start_ref"], por_arquivo["parecer.pdf"]["end_ref"]) == ("p. 1", "p. 3")
    # Posições distintas e contínuas no grupo, mesmo com todo HTML em "p. 1".
    intervalos = sorted((p["start_order"], p["end_order"]) for p in pecas)
    assert intervalos == [(1, 1), (2, 2), (3, 3), (4, 4), (5, 7)]
    conn.close()


def test_indice_aponta_o_arquivo_certo_de_cada_peca(tmp_path):
    from gclaude_indexer.artifacts import generate_index_md, generate_review_md

    origem, saida, config, conn = _projeto(tmp_path)
    for n in (1, 2, 3):
        (origem / "Leis" / f"l{n}.htm").write_text(
            _lei(str(n), f"{n} DE MAIO DE 2010", f"Dispõe sobre a matéria {n}."), encoding="utf-8"
        )
    _rodar(conn, config)

    texto = "\n".join(p.read_text(encoding="utf-8") for p in generate_index_md(conn, config, "pt"))
    for n in (1, 2, 3):
        assert f"(l{n}.htm, p. 1)" in texto

    revisao = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "Leis" not in revisao.split("##")[-1] or "lacuna" not in revisao.lower()
    conn.close()


def test_processo_continua_numerando_folhas_entre_arquivos(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path, tipo="processo")
    for nome, paginas in (("vol1.pdf", 2), ("vol2.pdf", 2)):
        documento = fitz.open()
        for n in range(paginas):
            documento.new_page().insert_text((72, 72), f"DESPACHO {nome} {n}")
        documento.save(origem / "Leis" / nome)
        documento.close()

    _rodar(conn, config)

    refs = [(p["start_ref"], p["start_order"]) for p in conn.execute("SELECT * FROM item ORDER BY start_order")]
    assert refs == [("f. 1", 1), ("f. 2", 2), ("f. 3", 3), ("f. 4", 4)]
    conn.close()


# --- motor local e Claude Code -------------------------------------------------


def test_motor_local_por_pagina_nunca_junta_dois_arquivos_de_documento_inteiro():
    from gclaude_indexer.engine_local import _group_pages_into_items

    paginas = [_pagina(f"Lei {i}", f"l{i}.htm", i) for i in (1, 2)]
    # Mesmo assunto e "continues" nas duas: o modelo acha que é um documento só.
    respostas = [
        {"n": 1, "subject": "Lei", "type": "LEI", "continues": False},
        {"n": 2, "subject": "Lei", "type": "LEI", "continues": True},
    ]

    pecas = _group_pages_into_items(paginas, respostas)
    assert [p.files for p in pecas] == [["l1.htm"], ["l2.htm"]]
    assert [p.start_order for p in pecas] == [1, 2]


def test_janela_do_claude_code_traz_a_posicao_de_cada_pagina(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path)
    for n in (1, 2):
        (origem / "Leis" / f"l{n}.htm").write_text(_lei(str(n), "1 DE MAIO DE 2010", "Dispõe."), encoding="utf-8")
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)

    janela = next((saida / "windows").glob("*.txt")).read_text(encoding="utf-8")
    assert "--- p. 1 (l1.htm) [#1] ---" in janela
    assert "--- p. 1 (l2.htm) [#2] ---" in janela
    conn.close()


def test_claude_md_manda_usar_a_posicao_e_separar_arquivos(tmp_path):
    from gclaude_indexer.windows_prep import generate_claude_md

    config = load_config({"name": "X", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "s")})
    (tmp_path / "s").mkdir()
    for idioma in ("pt", "en", "es"):
        texto = generate_claude_md(config, idioma).read_text(encoding="utf-8")
        assert "[#" in texto
        assert ".htm" in texto

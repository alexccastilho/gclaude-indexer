"""2.1.4: página que só tem o rodapé repetido do documento não vai ao modelo.

Nos processos do órgão, os arquivos 33, 51 e 38 têm 18.414 páginas vazias com
só o rodapé "Para verificar as assinaturas, acesse ... código NNNNNNNN." e um
ícone. Elas escapavam da regra da página em branco (sem texto e sem imagem),
e o modelo lia uma a uma: 4.951 janelas, umas 69 horas de classificação.

A página entra na regra quando o texto inteiro dela, curto, se repete igual
em boa parte das páginas do mesmo arquivo. Slides com títulos curtos e
diferentes, e um título igual em poucas páginas, continuam indo ao modelo.
"""

from __future__ import annotations

import json
from pathlib import Path

from gclaude_indexer import engine_local
from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import (
    BLANK_PAGE_SUMMARY, BLANK_PAGE_TYPE, LocalEngine, classify_pending, repeated_footer_texts,
    split_blank_pages,
)

from tests.test_phase8 import _projeto_pronto_para_classificar

RODAPE = "Para verificar as assinaturas, acesse www.exemplo.gov.br/autenticidade e informe o código 12345678."
TEXTO = "Ofício número {n}: o Tribunal comunica a decisão tomada no processo, com os prazos e anexos."


class _MotorQueAnota(LocalEngine):
    vistas: list = []

    def is_available(self):
        return True

    def classify(self, pages):
        self.vistas.extend(page.reference for page in pages)
        linhas = [
            {"n": i + 1, "subject": f"assunto {page.reference}", "type": "OFÍCIO", "detail": "x"}
            for i, page in enumerate(pages)
        ]
        return engine_local._group_pages_into_items(pages, linhas)


def _classificar(tmp_path, textos, *, ocr_falhou=False):
    config, conn = _projeto_pronto_para_classificar(tmp_path, textos)
    if ocr_falhou:
        conn.execute("UPDATE file SET ocr_failed = 1")
        conn.commit()
    motor = _MotorQueAnota(model="fake", url_base="http://127.0.0.1:9")
    motor.vistas = []
    classify_pending(conn, config, local_engine=motor)
    linhas = (Path(config.output_folder) / "raw_items.jsonl").read_text("utf-8").splitlines()
    conn.close()
    return sorted(set(motor.vistas), key=lambda ref: int(ref.split()[-1])), [json.loads(l) for l in linhas]


def test_paginas_so_com_o_rodape_nao_vao_ao_modelo(tmp_path):
    textos = [TEXTO.format(n=1)] + [RODAPE] * 28 + [TEXTO.format(n=2)]
    vistas, pecas = _classificar(tmp_path, textos)
    assert vistas == ["f. 1", "f. 30"]
    vazias = [p for p in pecas if p["type"] == BLANK_PAGE_TYPE]
    assert vazias and all(p["confidence"] == "high" for p in vazias)
    # Não é "sem texto e sem imagem": a página tem o rodapé.
    assert all(p["summary"] != BLANK_PAGE_SUMMARY for p in vazias)
    cobertas = {n for p in vazias for n in range(p["order_start"], p["order_end"] + 1)}
    assert cobertas == set(range(2, 30))


def test_slides_com_titulos_curtos_diferentes_continuam_indo_ao_modelo(tmp_path):
    textos = [TEXTO.format(n=n) for n in range(1, 21)] + [f"PROPOSTA COMERCIAL {n}" for n in range(1, 11)]
    vistas, _ = _classificar(tmp_path, textos)
    assert len(vistas) == 30


def test_titulo_igual_em_poucas_paginas_continua_indo_ao_modelo(tmp_path):
    textos = [TEXTO.format(n=n) for n in range(1, 28)] + ["M&A CAPITAL ADVISORY"] * 3
    vistas, _ = _classificar(tmp_path, textos)
    assert len(vistas) == 30


def test_arquivo_com_ocr_falho_fica_fora_da_regra(tmp_path):
    # Página escaneada cujo OCR falhou: o rodapé é o único texto, mas a folha
    # pode ter conteúdo. Vai ao modelo como antes.
    textos = [TEXTO.format(n=1)] + [RODAPE] * 28 + [TEXTO.format(n=2)]
    vistas, _ = _classificar(tmp_path, textos, ocr_falhou=True)
    assert len(vistas) == 30


def _pagina(numero, texto=RODAPE, imagens=1):
    return WindowPage(
        reference=f"f. {numero}", file_name="33.pdf", text=texto, has_table=False, image_count=imagens,
        order=numero, file_id=7,
    )


def test_pagina_com_mais_imagens_que_o_resto_do_arquivo_vai_ao_modelo():
    # O ícone do rodapé está em toda página (1 imagem); uma foto a mais na
    # folha é conteúdo, mesmo que o único texto seja o rodapé.
    rodapes = {7: (frozenset({RODAPE}), 1)}
    pecas, restantes = split_blank_pages([_pagina(1), _pagina(2, imagens=2), _pagina(3)], rodapes)
    assert [p.reference for p in restantes] == ["f. 2"]
    assert [(p.start_order, p.end_order) for p in pecas] == [(1, 1), (3, 3)]


def test_rodapes_do_banco(tmp_path):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO.format(n=1)] + [RODAPE] * 28 + [TEXTO.format(n=2)])
    rodapes = repeated_footer_texts(conn)
    assert list(rodapes.values()) == [(frozenset({RODAPE}), 0)]
    conn.close()

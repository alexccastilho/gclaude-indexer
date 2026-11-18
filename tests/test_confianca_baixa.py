"""2.0.0, tarefa 14: menos confiança baixa, sem segunda passada.

A página em branco não vai ao modelo; a página sem resposta e a respondida
sem tipo ganham UMA segunda tentativa na mesma passada, dentro de um teto de
15% de pedidos extras; as regras só mantêm `medium` na continuação de uma
peça aberta por marcador.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from gclaude_indexer import engine_local
from gclaude_indexer.classification import ClassifiedItem, WindowPage
from gclaude_indexer.engine_local import (
    BLANK_PAGE_TYPE, EXTRA_REQUEST_SHARE, Generation, LocalEngine, classify_pending, is_blank_page,
    split_blank_pages,
)

from tests.test_phase8 import _projeto_pronto_para_classificar


def _pagina(numero, texto="texto da página", nome="doc.pdf", imagens=0):
    return WindowPage(
        reference=f"f. {numero}", file_name=nome, text=texto, has_table=False, image_count=imagens,
        order=numero, file_id=1,
    )


# --- página em branco ---------------------------------------------------------


def test_pagina_em_branco_e_so_a_de_documento_paginado_sem_texto_e_sem_imagem():
    assert is_blank_page(_pagina(1, texto="  \n "))
    assert not is_blank_page(_pagina(1, texto="algo"))
    # Folha escaneada sem OCR: tem imagem, vai ao modelo (que diz que está ilegível).
    assert not is_blank_page(_pagina(1, texto="", imagens=1))
    # Mensagem vazia de uma caixa de e-mail ou trecho de transcrição não é folha em branco.
    assert not is_blank_page(_pagina(1, texto="", nome="caixa.mbox"))
    assert not is_blank_page(_pagina(1, texto="", nome="caixa.pst"))
    assert not is_blank_page(_pagina(1, texto="", nome="reuniao.mp4"))
    # Arquivo de documento inteiro vazio continua pelo caminho de sempre.
    assert not is_blank_page(_pagina(1, texto="", nome="vazio.txt"))


def test_paginas_em_branco_seguidas_viram_uma_peca_de_confianca_alta():
    paginas = [_pagina(1), _pagina(2, texto=""), _pagina(3, texto=""), _pagina(4)]
    pecas, restantes = split_blank_pages(paginas)
    assert [p.reference for p in restantes] == ["f. 1", "f. 4"]
    assert len(pecas) == 1
    assert (pecas[0].start_order, pecas[0].end_order) == (2, 3)
    assert (pecas[0].type, pecas[0].confidence) == (BLANK_PAGE_TYPE, "high")


def test_peca_nao_atravessa_a_pagina_em_branco_que_ficou_de_fora():
    """A peça da página 1 e a da página 3 têm o mesmo assunto, mas a 2 não foi
    ao modelo: juntá-las faria a peça cobrir uma página que ela não tem."""
    linhas = [
        {"n": 1, "subject": "contrato", "type": "TERMO", "detail": "a"},
        {"n": 2, "subject": "contrato", "type": "TERMO", "detail": "b", "continues": True},
    ]
    pecas = engine_local._group_pages_into_items([_pagina(1), _pagina(3)], linhas)
    assert [(p.start_order, p.end_order) for p in pecas] == [(1, 1), (3, 3)]


class _MotorQueNaoVeEmBranco(LocalEngine):
    vistas: list = []

    def is_available(self):
        return True

    def classify(self, pages):
        self.vistas.extend(page.reference for page in pages)
        linhas = [
            {"n": i + 1, "subject": f"assunto {i}", "type": "OFÍCIO", "detail": "x"}
            for i in range(len(pages))
        ]
        return engine_local._group_pages_into_items(pages, linhas)


def test_pagina_em_branco_nao_vai_ao_modelo_e_sai_no_indice(tmp_path):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [
        "Ofício número 1, texto da primeira página do volume.", "",
        "Ofício número 2, texto da terceira página do volume.",
    ])
    motor = _MotorQueNaoVeEmBranco(model="fake", url_base="http://127.0.0.1:9")
    motor.vistas = []
    resultado = classify_pending(conn, config, local_engine=motor)

    assert motor.vistas == ["f. 1", "f. 3"]
    assert resultado.blank_pages == 1
    pecas = [json.loads(l) for l in (Path(config.output_folder) / "raw_items.jsonl").read_text("utf-8").splitlines()]
    em_branco = [p for p in pecas if p["type"] == BLANK_PAGE_TYPE]
    assert len(em_branco) == 1 and em_branco[0]["confidence"] == "high"
    assert em_branco[0]["ref_start"] == "f. 2"
    conn.close()


# --- segunda tentativa --------------------------------------------------------


def _motor(**campos):
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor.context_ceiling = 1_000_000
    motor.num_ctx = 1_000_000
    motor.plan_gpu_use = lambda *a, **k: None
    for nome, valor in campos.items():
        setattr(motor, nome, valor)
    return motor


def _responder(motor, regra):
    """`_generate` que lê as páginas do prompt e responde com `regra(ref, nota)`."""
    chamadas: list[dict] = []

    def gerar(prompt, schema=None):
        referencias = re.findall(r"--- Página (\d+) \((f\. \d+),", prompt)
        nota = "segunda leitura" in prompt or "COM O TEXTO INTEIRO" in prompt
        chamadas.append({"refs": [r for _n, r in referencias], "retry": nota})
        linhas = []
        for numero, ref in referencias:
            linha = regra(ref, nota, prompt)
            if linha is not None:
                linhas.append({"n": int(numero), **linha})
        return Generation(text=json.dumps({"pages": linhas}), prompt_tokens=100, response_tokens=10, context=1_000_000)

    motor._generate = gerar
    return chamadas


def _linha(ref, tipo="OFÍCIO"):
    return {"subject": f"assunto {ref}", "type": tipo, "detail": f"detalhe {ref}"}


def test_pagina_sem_resposta_recebe_exatamente_uma_nova_tentativa_com_as_vizinhas():
    motor = _motor(base_requests=20)
    chamadas = _responder(motor, lambda ref, retry, prompt: None if ref == "f. 2" and not retry else _linha(ref))
    paginas = [_pagina(1), _pagina(2), _pagina(3)]
    pecas = motor.classify_per_page(paginas)

    extras = [c for c in chamadas if c["retry"]]
    assert len(extras) == 1
    assert extras[0]["refs"] == ["f. 1", "f. 2", "f. 3"]  # a faltante e uma vizinha de cada lado
    assert (motor.extra_requests, motor.second_missing, motor.second_capped) == (1, 1, 0)
    segunda = next(p for p in pecas if p.start_order <= 2 <= p.end_order)
    assert segunda.confidence == "high" and segunda.type == "OFÍCIO"


def test_pagina_que_continua_sem_resposta_nao_ganha_uma_terceira_tentativa():
    motor = _motor(base_requests=100)
    chamadas = _responder(motor, lambda ref, retry, prompt: None if ref == "f. 2" else _linha(ref))
    paginas = [_pagina(1), _pagina(2), _pagina(3)]
    motor.classify_per_page(paginas)
    motor.classify_per_page(paginas)  # a mesma página numa janela sobreposta

    assert sum(1 for c in chamadas if c["retry"]) == 1
    assert motor.extra_requests == 1


def test_teto_de_15_por_cento_de_pedidos_extras(monkeypatch):
    motor = _motor()
    _responder(motor, lambda ref, retry, prompt: None if ref.endswith("2") and not retry else _linha(ref))
    for janela in range(40):
        base = janela * 10
        motor.classify_per_page([_pagina(base + 1), _pagina(base + 2), _pagina(base + 3)])
        # Em nenhum momento, nem no meio da execução, passa do teto.
        assert motor.extra_requests <= EXTRA_REQUEST_SHARE * motor.base_requests
    assert motor.extra_requests > 0  # o teto não é zero: dá para usar
    assert motor.second_capped > 0  # e o que não coube ficou contado


def test_sem_pedidos_normais_ainda_nao_ha_teto_para_extras():
    motor = _motor()
    chamadas = _responder(motor, lambda ref, retry, prompt: None if ref == "f. 2" and not retry else _linha(ref))
    pecas = motor.classify_per_page([_pagina(1), _pagina(2), _pagina(3)])
    assert not any(c["retry"] for c in chamadas)
    assert motor.extra_requests == 0 and motor.second_capped == 1
    assert {p.confidence for p in pecas} == {"high", "low"}  # a página sem resposta entra, honesta


def test_pagina_sem_tipo_e_lida_de_novo_com_o_texto_inteiro_do_indice():
    inteiro = "OFÍCIO Nº 7/2026 " + "texto do corpo do ofício, " * 40
    motor = _motor(base_requests=20, page_text=lambda page: inteiro)

    def regra(ref, retry, prompt):
        if "COM O TEXTO INTEIRO" in prompt:
            assert "OFÍCIO Nº 7/2026" in prompt
            return _linha(ref, "OFÍCIO")
        return {"subject": "algo", "type": None, "detail": "texto sem título"}

    chamadas = _responder(motor, regra)
    pecas = motor.classify_per_page([_pagina(1, texto="corpo sem o cabeçalho")])

    assert [c["retry"] for c in chamadas] == [False, True]
    assert (motor.extra_requests, motor.second_untyped) == (1, 1)
    assert pecas[0].type == "OFÍCIO"


def test_pagina_sem_tipo_cujo_texto_ja_estava_inteiro_nao_gasta_pedido_extra():
    motor = _motor(base_requests=20, page_text=lambda page: page.text)
    chamadas = _responder(motor, lambda ref, retry, prompt: {"subject": "a", "type": None, "detail": "d"})
    motor.classify_per_page([_pagina(1, texto="texto curto e completo")])
    assert len(chamadas) == 1 and motor.extra_requests == 0


def test_pagina_sem_tipo_nao_ganha_segunda_tentativa_se_ja_foi_a_da_resposta_faltante():
    """No máximo uma extra por página: a que veio da página sem resposta
    conta, mesmo que a releitura volte sem tipo."""
    inteiro = "texto " * 200
    motor = _motor(base_requests=100, page_text=lambda page: inteiro)

    def regra(ref, retry, prompt):
        if ref == "f. 1" and not retry:
            return None
        return {"subject": "a", "type": None, "detail": "d"}

    chamadas = _responder(motor, regra)
    motor.classify_per_page([_pagina(1, texto="curto")])
    assert sum(1 for c in chamadas if c["retry"]) == 1


def test_contexto_tem_so_o_que_o_usuario_escreveu(tmp_path):
    """2.1.0: o perfil tirado dos arquivos e a natureza do acervo saíram do
    prompt; medidos, os dois pioravam a divisão em documentos."""
    from gclaude_indexer.config import load_config

    (tmp_path / "origem").mkdir()
    base = {"name": "x", "source_folder": str(tmp_path / "origem"), "output_folder": str(tmp_path / "saida")}
    assert engine_local.build_context(load_config(base)) == ""
    contexto = engine_local.build_context(load_config({**base, "subject": "Obras da escola"}))
    assert "Obras da escola" in contexto
    assert "Natureza do acervo" not in contexto and "Perfil do acervo" not in contexto


# --- texto inteiro da página no índice ---------------------------------------


def test_texto_inteiro_da_pagina_vem_do_indice_de_busca(tmp_path):
    from gclaude_indexer import fulltext
    from gclaude_indexer.db import connect, init_schema

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    fid = conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status)"
        " VALUES ('a.pdf', 'a.pdf', 'pdf', 1, 'x', 'g', 'extracted')"
    ).lastrowid
    conn.commit()
    row = {"id": fid}
    conn.execute("BEGIN IMMEDIATE")
    fulltext._store_passages(conn, row, [
        fulltext.Passage("texto da página um, inteiro", "f. 1", 0),
        fulltext.Passage("texto da página dez", "f. 10", 0),
        fulltext.Passage("mensagem 3, parte A", "f. 3 · Assunto", 0),
        fulltext.Passage("mensagem 3, parte B", "f. 3 · Corpo", 0),
    ])
    conn.commit()
    assert fulltext.page_text(conn, fid, "f. 1") == "texto da página um, inteiro"  # "f. 10" não entra
    assert fulltext.page_text(conn, fid, "f. 3") == "mensagem 3, parte A\nmensagem 3, parte B"
    assert fulltext.page_text(conn, fid, "f. 99") == ""
    assert fulltext.page_text(conn, fid + 1, "f. 1") == ""
    conn.close()


# --- regras --------------------------------------------------------------------


def test_regras_continuacao_de_peca_aberta_por_marcador_fica_medium_se_ligado(monkeypatch):
    """A medição (docs/QUALITY.md) não sustentou a mudança: o padrão é `low`;
    o mecanismo continua testado com a chave ligada."""
    from gclaude_indexer import engine_rules
    from gclaude_indexer.engine_rules import RulesEngine, load_rules

    assert engine_rules.CONTINUATION_KEEPS_MEDIUM is False
    monkeypatch.setattr(engine_rules, "CONTINUATION_KEEPS_MEDIUM", True)
    motor = RulesEngine(load_rules())
    paginas = [
        _pagina(1, "OFÍCIO Nº 10/2026\nSenhor Prefeito, segue o pedido."),
        _pagina(2, "segue a folha dois do mesmo documento, sem nenhum marcador aqui"),
    ]
    pecas = motor.classify(paginas)
    assert [(p.type, p.confidence) for p in pecas] == [("OFÍCIO", "medium")]


def test_regras_peca_sem_marcador_de_abertura_continua_low():
    from gclaude_indexer.engine_rules import RulesEngine, load_rules

    motor = RulesEngine(load_rules())
    pecas = motor.classify([
        _pagina(1, "texto solto da primeira página, sem marcador algum"),
        _pagina(2, "mais texto solto na segunda página, sem marcador algum"),
    ])
    assert [p.confidence for p in pecas] == ["low"]


# --- OCR refeito uma vez, com o modelo da escrita ---------------------------------


def test_plano_com_o_modelo_que_falta_so_para_plano_de_um_grupo():
    from gclaude_indexer import conversion

    assert conversion._plan_with_models("por", ["script/Latin"]) == "por+script/Latin"
    assert conversion._plan_with_models("deu+eng", ["script/Latin"]) == "deu+eng+script/Latin"
    assert conversion._plan_with_models("por+eng+deu", ["script/Latin"]) == "por+eng+deu"  # no máximo 3
    assert conversion._plan_with_models("1-3:chi_sim|4-6:deu", ["script/Latin"]) is None


def test_imagem_de_ocr_curto_e_lida_de_novo_com_o_modelo_da_escrita(tmp_path, monkeypatch):
    from PIL import Image

    from gclaude_indexer import conversion

    caminho = tmp_path / "carta.png"
    Image.new("L", (40, 40), 255).save(caminho)
    lidos = []
    monkeypatch.setattr(conversion.ocr_detection, "osd_image", lambda image: ("cyrillic", 0))
    monkeypatch.setattr(
        conversion, "_extract_text_image",
        lambda path, languages, rotate=0: lidos.append(languages) or "Текст письма, прочитанный заново " * 5,
    )
    eventos: list = []
    texto, faltam = conversion._reread_image(
        caminho, "xx", "por", 0, ["por", "script/Cyrillic"], eventos, "carta.png"
    )
    assert lidos == ["script/Cyrillic"] and faltam == []
    assert texto.startswith("Текст письма")
    assert eventos[0][2] == "log.conversion.ocr_reread"

    # Modelo da escrita ausente nesta máquina: nada é lido, e ele é pedido.
    lidos.clear()
    texto, faltam = conversion._reread_image(caminho, "xx", "por", 0, ["por"], [], "carta.png")
    assert (texto, faltam, lidos) == ("xx", ["script/Cyrillic"], [])

    # O modelo da escrita já foi o usado: ler de novo daria o mesmo texto.
    texto, faltam = conversion._reread_image(
        caminho, "xx", "script/Cyrillic", 0, ["script/Cyrillic"], [], "carta.png"
    )
    assert (texto, faltam, lidos) == ("xx", [], [])

    # O OSD sem resposta (página sem texto): nada a fazer.
    monkeypatch.setattr(conversion.ocr_detection, "osd_image", lambda image: None)
    assert conversion._reread_image(caminho, "xx", "por", 0, ["por"], [], "carta.png") == ("xx", [])


def _escrever(origem, saida, paginas, texto):
    """Falso `ocrmypdf`: copia `origem` e põe `texto` nas `paginas` (a camada de texto nova)."""
    import fitz

    documento = fitz.open(origem)
    for numero in paginas:
        pagina = documento[numero - 1]
        pagina.insert_text((60, 400), texto, fontsize=6)
    documento.save(saida)
    documento.close()


def test_releitura_mais_curta_nao_substitui_a_pagina_original(tmp_path, monkeypatch):
    """O OSD de uma página quase vazia erra a escrita: se a releitura devolve
    menos texto, a página de antes fica."""
    import fitz

    from gclaude_indexer import conversion

    origem = tmp_path / "origem.pdf"
    destino = tmp_path / "convertido.pdf"
    documento = fitz.open()
    for _ in range(2):
        pagina = documento.new_page()
        pagina.insert_text((60, 100), "sessenta caracteres de texto lido pelo primeiro OCR ok", fontsize=8)
    documento.save(origem)
    documento.save(destino)
    documento.close()

    def ocr_pior(origem_, saida, idiomas, jobs=1, pages=None, rotate=False):
        # Pagina 1: texto novo MENOR (lixo); página 2: texto novo maior.
        copia = fitz.open(origem_)
        for numero in pages:
            pagina = copia[numero - 1]
            pagina.add_redact_annot(pagina.rect)
            pagina.apply_redactions()
            pagina.insert_text((60, 100), "xx" if numero == 1 else "texto bem mais longo lido de novo, " * 4, fontsize=8)
        copia.save(saida)
        copia.close()

    monkeypatch.setattr(conversion, "_run_ocrmypdf", ocr_pior)
    monkeypatch.setattr(conversion.ocr_detection, "osd_image", lambda image: ("cyrillic", 0))
    eventos: list = []
    # `weak` exige menos de 100 caracteres: as duas páginas têm ~55.
    faltam, leu = conversion._reread_weak_pdf_pages(
        "origem.pdf", origem, destino, [1, 2], ["por"], ["por", "script/Cyrillic"], 1, False, eventos, {}
    )
    resultado = fitz.open(destino)
    textos = [resultado[i].get_text().strip() for i in range(2)]
    resultado.close()
    assert textos[0].startswith("sessenta caracteres")  # a original sobreviveu
    assert textos[1].startswith("texto bem mais longo")  # a mais longa entrou
    assert leu is True and "(1)" in eventos[-1][3]["models"]

    # Se nenhuma página melhora, nada muda e nada é registrado.
    monkeypatch.setattr(conversion, "_run_ocrmypdf", lambda o, s, i, jobs=1, pages=None, rotate=False: _escrever(o, s, pages, ""))
    antes = destino.read_bytes()
    eventos.clear()
    conversion._reread_weak_pdf_pages(
        "origem.pdf", origem, destino, [1, 2], ["por"], ["por", "script/Cyrillic"], 1, False, eventos, {}
    )
    assert destino.read_bytes() == antes and eventos == []


def test_pdf_de_paginas_fracas_e_relido_so_nelas_e_uma_vez_por_modelo(tmp_path, monkeypatch):
    import shutil

    import fitz

    from gclaude_indexer import conversion

    origem = tmp_path / "origem.pdf"
    destino = tmp_path / "convertido.pdf"
    documento = fitz.open()
    for _ in range(3):
        pagina = documento.new_page()
        pagina.draw_rect(fitz.Rect(50, 50, 300, 300))
    documento.save(origem)
    documento.close()
    shutil.copy(origem, destino)

    chamadas = []

    def falso_ocrmypdf(origem_, saida, idiomas, jobs=1, pages=None, rotate=False):
        chamadas.append((idiomas, pages))
        _escrever(origem_, saida, pages, "texto lido de novo " * 10)

    monkeypatch.setattr(conversion, "_run_ocrmypdf", falso_ocrmypdf)
    escritas = {1: "cyrillic", 2: "cyrillic", 3: "latin"}
    ordem = iter([1, 2, 3])
    monkeypatch.setattr(conversion.ocr_detection, "osd_image", lambda image: (escritas[next(ordem)], 0))
    eventos: list = []
    faltam, leu = conversion._reread_weak_pdf_pages(
        "origem.pdf", origem, destino, [1, 2, 3], ["por"], ["por", "script/Cyrillic"], 1, False, eventos, {}
    )
    assert chamadas == [("script/Cyrillic", [1, 2])]  # uma vez por modelo; a latina não está aqui
    assert faltam == ["script/Latin"] and leu is True
    assert destino.is_file() and not list(tmp_path.glob("*.releitura*"))
    assert eventos[-1][2] == "log.conversion.ocr_reread"

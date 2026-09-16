# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 21: o contexto calibrado e a nota honesta.

A fase 20 corrigiu o contexto congelado e manteve a constante que o
alimenta. Medido contra o tokenizador do modelo, conteúdo tabular entrega
1,45 caracteres por token e não os 3,0 que o código supõe: o recálculo por
janela roda e chega curto toda vez. Numa corrida de 2904 páginas
(15/09/2026, `qwen3.5:4b`), 153 de 1449 janelas entraram no índice sem
classificação nenhuma, e a nota declarou 89/100.
"""

from __future__ import annotations

import json
import sqlite3

from gclaude_indexer import gpu_budget
from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import (
    Generation,
    LocalEngine,
    _group_pages_into_items,
    _looks_truncated,
    context_tokens_for,
)
from gclaude_indexer.quality import _coverage


def _page(referencia: str, texto: str = "texto da pagina") -> WindowPage:
    return WindowPage(
        reference=referencia,
        file_name="acervo.pdf",
        text=texto,
        has_table=False,
        image_count=0,
    )


def test_pagina_sem_linha_do_modelo_recebe_confianca_baixa():
    """O modelo não respondeu nada sobre a janela. As páginas entram no
    índice pelo agrupamento — essa garantia fica — mas não podem se passar
    por classificadas: era isso que fazia o log fechar em `baixa=0` com 612
    peças cegas."""
    pages = [_page("f. 1"), _page("f. 2")]

    itens = _group_pages_into_items(pages, [])

    assert itens, "a garantia de cobertura precisa continuar valendo"
    assert all(item.confidence == "low" for item in itens)


def test_linha_incompleta_do_modelo_continua_media():
    """O modelo falou, mas sem tipo. Isso é diferente de não falar, e
    continua valendo `medium`."""
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "detail": "contrato de honorarios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["medium"]


def test_linha_completa_do_modelo_continua_alta():
    pages = [_page("f. 1")]
    rows = [{"n": 1, "subject": "Contrato", "type": "CONTRATO",
             "detail": "contrato de honorarios advocaticios"}]

    itens = _group_pages_into_items(pages, rows)

    assert [item.confidence for item in itens] == ["high"]


# --- Cobertura: a consulta comparava numerações diferentes -----------------

def _banco_com_duas_familias() -> sqlite3.Connection:
    """Dois grupos cujas folhas se sobrepõem em numeração, que é o caso
    real: cada PDF numera as páginas de 1 a N, e a folha é do processo."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE file (id INTEGER PRIMARY KEY, group_key TEXT, name TEXT);
        CREATE TABLE page (id INTEGER PRIMARY KEY, file_id INTEGER,
                           number INTEGER, reference TEXT);
        CREATE TABLE item (id INTEGER PRIMARY KEY, group_key TEXT,
                           start_order INTEGER, end_order INTEGER,
                           confidence TEXT);
        """
    )
    conn.execute("INSERT INTO file VALUES (1, 'Processo', 'vol1.pdf')")
    conn.execute("INSERT INTO file VALUES (2, 'Avulsos', 'anexo.pdf')")
    # Processo: folhas 1 a 4, numeradas 1..4 dentro do proprio PDF.
    for n in range(1, 5):
        conn.execute("INSERT INTO page VALUES (?, 1, ?, ?)", (n, n, f"f. {n}"))
    # Avulsos: folhas 1 a 2, tambem numeradas 1..2 dentro do PDF.
    for n in range(1, 3):
        conn.execute("INSERT INTO page VALUES (?, 2, ?, ?)", (100 + n, n, f"f. {n}"))
    return conn


def test_cobertura_nao_conta_peca_de_outro_grupo():
    """O defeito: `page.number` é a página dentro do arquivo e
    `item.start_order` é a folha do grupo. Sem join, a peça de um grupo
    'cobria' a página de outro que por acaso tinha o mesmo número."""
    conn = _banco_com_duas_familias()
    # Uma unica peca, no grupo Processo, cobrindo as folhas 1 a 4.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 4, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert total == 6
    # As duas folhas de 'Avulsos' NAO estao cobertas: nenhuma peca daquele
    # grupo existe. A consulta antiga contava 6 de 6.
    assert cobertas == 4


def test_cobertura_enxerga_o_buraco():
    """Reprodução do que foi medido no acervo: removendo as peças de uma
    faixa, a cobertura tem de cair."""
    conn = _banco_com_duas_familias()
    # Cobre so as folhas 1 e 2 do Processo; 3 e 4 ficam de fora.
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Avulsos', 1, 2, 'high')")

    total, cobertas, _classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 4)


def test_cobertura_classificada_ignora_peca_cega():
    """Uma peça de confiança `low` é a rede de segurança funcionando, não
    classificação. Era isto que pagava 40 de 40 pontos numa corrida com 11%
    do índice cego."""
    conn = _banco_com_duas_familias()
    conn.execute("INSERT INTO item VALUES (1, 'Processo', 1, 2, 'high')")
    conn.execute("INSERT INTO item VALUES (2, 'Processo', 3, 4, 'low')")
    conn.execute("INSERT INTO item VALUES (3, 'Avulsos', 1, 2, 'high')")

    total, cobertas, classificadas = _coverage(conn)

    assert (total, cobertas) == (6, 6), "toda pagina segue no indice"
    assert classificadas == 4, "as duas folhas cegas nao contam como classificadas"


# --- A telemetria que o Ollama devolve e o código jogava fora --------------

class _Resposta:
    def __init__(self, dados: dict):
        self._dados = dados

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self._dados).encode("utf-8")


class _OllamaFalso:
    """Substitui `urlopen`. Guarda o `num_ctx` pedido em cada chamada e
    devolve a telemetria que o Ollama real devolve."""

    def __init__(self, respostas: list[dict]):
        self.respostas = list(respostas)
        self.contextos: list[int] = []

    def __call__(self, request, timeout=None):
        corpo = json.loads(request.data.decode("utf-8"))
        self.contextos.append(corpo["options"].get("num_ctx"))
        return _Resposta(self.respostas.pop(0))


def test_generate_devolve_a_telemetria(monkeypatch):
    """`prompt_eval_count` é a contagem de tokens do tokenizador do próprio
    modelo. É o dado que denuncia o truncamento, e ele vinha sendo
    descartado."""
    falso = _OllamaFalso([
        {"response": '{"pages": []}', "prompt_eval_count": 5091, "eval_count": 422}
    ])
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor.num_ctx = 6144

    resultado = motor._generate("prompt qualquer")

    assert isinstance(resultado, Generation)
    assert resultado.text == '{"pages": []}'
    assert resultado.prompt_tokens == 5091
    assert resultado.response_tokens == 422
    assert resultado.context == 6144


# --- A razão caracteres/token: constante chutada vs. medida ---------------

def test_contexto_cresce_quando_a_razao_cai():
    """O mesmo prompt precisa de mais contexto quando o conteúdo tokeniza
    pior. Medido no acervo: prosa a 3,3 caracteres por token, tabela
    contábil a 1,45."""
    prompt = "x" * 9000

    prosa = context_tokens_for(prompt, page_count=4, chars_per_token=3.0)
    tabela = context_tokens_for(prompt, page_count=4, chars_per_token=1.45)

    assert tabela > prosa


def test_calibracao_aprende_a_razao_do_acervo():
    """A janela íntegra ensina a razão real: 8241 caracteres que o modelo
    leu como 5091 tokens são 1,62 caracteres por token, e não os 3,0 que a
    constante supunha."""
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    assert motor._chars_per_token == 3.0

    motor._calibrate("x" * 8241, Generation(text="{}", prompt_tokens=5091, context=8192))

    assert motor._chars_per_token < 1.7


def test_calibracao_ignora_a_chamada_truncada():
    """Num prompt cortado, `prompt_eval_count` descreve o pedaço que sobrou
    e não o prompt inteiro. Calibrar por ele ensinaria a razão errada."""
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    # 2050 tokens num contexto de 4096: a assinatura do truncamento.
    motor._calibrate("x" * 8241, Generation(text="", prompt_tokens=2050, context=4096))

    assert motor._chars_per_token == 3.0


def test_assinatura_do_truncamento():
    """Medido no Ollama 0.34: ele corta o prompt em exatamente metade do
    contexto — 1026/2048, 1538/3072, 2050/4096."""
    assert _looks_truncated(Generation(text="", prompt_tokens=2050, context=4096))
    assert _looks_truncated(Generation(text="", prompt_tokens=1026, context=2048))
    assert not _looks_truncated(Generation(text="", prompt_tokens=5091, context=6144))
    assert not _looks_truncated(Generation(text="", prompt_tokens=0, context=0))


# --- A escada de retentativa ----------------------------------------------

def _plan_com_teto(monkeypatch, teto: int = 8192, camadas: int = 33):
    """O planejador devolve camadas até o teto e `None` acima dele — o
    comportamento medido na RTX 3060 Laptop: 33 de 33 camadas até 8192,
    nenhum plano em 12288."""
    monkeypatch.setattr(
        gpu_budget, "plan",
        lambda modelo, url, contexto: (
            (camadas, {"layers": camadas}) if contexto <= teto else (None, {})
        ),
    )


def _linhas(quantas: int) -> str:
    return json.dumps({"pages": [
        {"n": i, "subject": "assunto", "type": "DOC", "detail": "detalhe"}
        for i in range(1, quantas + 1)
    ]})


class _OllamaSimulado:
    """Imita os três regimes do Ollama medidos em bancada.

    - prompt maior que o contexto: cortado em metade do `num_ctx` — foi o
      que se mediu em 1026/2048, 1538/3072 e 2050/4096. O modelo nunca vê o
      bloco de instruções e inventa o próprio esquema JSON;
    - prompt cabe, resposta não: medido em `num_ctx` 5120, com o prompt de
      5091 tokens deixando 29 para responder. O JSON sai cortado;
    - os dois cabem: a resposta vem inteira.
    """

    def __init__(self, prompt_tokens: int, paginas: int, resposta_tokens: int = 422):
        self.prompt_tokens = prompt_tokens
        self.paginas = paginas
        self.resposta_tokens = resposta_tokens
        self.contextos: list[int] = []

    def __call__(self, request, timeout=None):
        corpo = json.loads(request.data.decode("utf-8"))
        contexto = corpo["options"].get("num_ctx")
        self.contextos.append(contexto)

        if self.prompt_tokens > contexto:
            return _Resposta({
                "response": '{"document_type": "Financial Statement", "sections": []}',
                "prompt_eval_count": contexto // 2 + 2,
                "eval_count": max(1, contexto // 2 - 400),
            })

        sobra = contexto - self.prompt_tokens
        if sobra < self.resposta_tokens:
            return _Resposta({
                "response": '{"pages": [{"n": 1,',
                "prompt_eval_count": self.prompt_tokens,
                "eval_count": sobra,
            })

        return _Resposta({
            "response": _linhas(self.paginas),
            "prompt_eval_count": self.prompt_tokens,
            "eval_count": self.resposta_tokens,
        })


def test_janela_truncada_e_refeita_com_mais_contexto(monkeypatch):
    """A falha que deixou 153 janelas cegas: o prompt não cabe, o Ollama o
    corta pela metade, o modelo nunca vê o gabarito e devolve zero linhas.
    A escada mede o corte pela telemetria e refaz a janela."""
    _plan_com_teto(monkeypatch)
    # Páginas curtas em caracteres e caras em tokens: é exatamente o
    # conteúdo tabular que a constante de 3,0 subestimava.
    ollama = _OllamaSimulado(prompt_tokens=5091, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}", "texto " * 200) for n in range(1, 5)]

    itens = motor.classify_per_page(pages)

    assert len(ollama.contextos) >= 2, "a janela tinha de ser refeita"
    assert ollama.contextos[0] < 5091, "a primeira tentativa saiu curta, como na corrida real"
    assert ollama.contextos[-1] >= 5091 + 880, "a ultima cabe prompt e resposta"
    assert [item.confidence for item in itens] != ["low"] * len(itens)
    assert not motor.last_window_warnings, "a janela foi coberta; nao ha perda a registrar"


def test_resposta_sem_orcamento_tambem_dispara_retentativa(monkeypatch):
    """O outro modo de falha, medido em num_ctx=5120: o prompt coube
    inteiro (5091) e sobraram 29 tokens para responder. Mesma mensagem de
    log do truncamento, causa oposta — uma correção que só olhasse o
    tamanho do prompt deixaria esta passar."""
    _plan_com_teto(monkeypatch)
    ollama = _OllamaSimulado(prompt_tokens=5091, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    # Calibrado para a estimativa inicial cair em 5120 — a faixa estreita
    # em que o prompt de 5091 cabe e sobram 29 tokens para responder, que
    # e exatamente o que se mediu em bancada.
    pages = [_page(f"f. {n}", "texto " * 400) for n in range(1, 5)]

    motor.classify_per_page(pages)

    # Os numeros da bancada, na ordem: 5120 deixa 29 tokens para responder,
    # 5091 + 4 x 220 = 5971 arredonda para 6144, e ai a resposta sai inteira.
    assert ollama.contextos == [5120, 6144]
    assert ollama.contextos[0] - 5091 == 29


def test_janela_que_responde_de_primeira_nao_repete(monkeypatch):
    """A retentativa custa uma chamada. Ela só acontece quando precisa."""
    _plan_com_teto(monkeypatch)
    ollama = _OllamaSimulado(prompt_tokens=1200, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}") for n in range(1, 5)]

    motor.classify_per_page(pages)

    assert len(ollama.contextos) == 1


def test_janela_acima_do_teto_e_subdividida(monkeypatch):
    """Nem no contexto máximo da placa a janela cabe. Em vez de transbordar
    para a RAM — uma janela seis vezes mais lenta, multiplicada por
    centenas, custa horas —, ela é partida, e nenhuma página fica sem
    descrição."""
    _plan_com_teto(monkeypatch, teto=4096)

    class _SoAceitaMetade(_OllamaSimulado):
        """A janela inteira nunca cabe; as metades cabem."""

        def __call__(self, request, timeout=None):
            corpo = json.loads(request.data.decode("utf-8"))
            paginas = corpo["prompt"].count("--- Página ")
            self.prompt_tokens = 9000 if paginas > 2 else 1500
            self.paginas = paginas
            return super().__call__(request, timeout)

    ollama = _SoAceitaMetade(prompt_tokens=9000, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    pages = [_page(f"f. {n}", "texto " * 400) for n in range(1, 5)]

    itens = motor.classify_per_page(pages)

    cobertas = set()
    for item in itens:
        for folha in range(item.start_order, item.end_order + 1):
            cobertas.add(folha)
    assert cobertas == {1, 2, 3, 4}, "toda folha continua descrita"
    assert all(item.confidence != "low" for item in itens)


def test_janela_de_uma_pagina_nao_entra_em_recursao(monkeypatch):
    """Não há o que subdividir numa página só. A peça entra como `low` e a
    corrida segue — mas o processo não pode travar."""
    _plan_com_teto(monkeypatch, teto=4096)
    ollama = _OllamaSimulado(prompt_tokens=90000, paginas=1)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    itens = motor.classify_per_page([_page("f. 1", "texto " * 400)])

    assert [item.confidence for item in itens] == ["low"]
    assert motor.last_window_warnings, "a perda tem de ficar registrada"

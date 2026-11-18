"""2.1.0: a resposta por página vai restrita por um JSON Schema (`format`)."""

from __future__ import annotations

import json

from gclaude_indexer import engine_local
from gclaude_indexer.engine_local import Generation, LocalEngine, _page_schema


def test_schema_exige_uma_linha_por_pagina_e_n_dentro_da_janela():
    schema = _page_schema(5)
    pages = schema["properties"]["pages"]
    assert pages["minItems"] == pages["maxItems"] == 5
    n = pages["items"]["properties"]["n"]
    assert n["type"] == "integer" and n["minimum"] == 1 and n["maximum"] == 5
    assert set(pages["items"]["required"]) >= {"n", "subject", "detail", "continues"}


def test_pedido_leva_o_schema_no_format(monkeypatch):
    enviados: list[dict] = []

    class _Resposta:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"response": '{"pages": []}'}).encode()

    def _urlopen(request, timeout=None):
        enviados.append(json.loads(request.data.decode()))
        return _Resposta()

    monkeypatch.setattr(engine_local.urllib.request, "urlopen", _urlopen)
    motor = LocalEngine(model="fake")
    motor._generate("x", _page_schema(3))
    motor._generate("y")
    assert enviados[0]["format"]["properties"]["pages"]["maxItems"] == 3
    assert enviados[1]["format"] == "json"


def test_desligado_volta_ao_json_livre(monkeypatch):
    recebidos: list = []
    motor = LocalEngine(model="fake", structured_output=False)
    monkeypatch.setattr(motor, "_generate", lambda prompt, schema=None: recebidos.append(schema) or Generation('{"pages": []}'))
    monkeypatch.setattr(motor, "_measure_ceiling", lambda: 0)
    motor._attempt("p", 2)
    assert recebidos == [None]


# --- 2.1.0: `continues` com o mesmo tipo junta as páginas ---------------------

def _pagina(ref, arquivo="processo.pdf"):
    from gclaude_indexer.engine_local import WindowPage

    return WindowPage(reference=ref, file_name=arquivo, text="texto", has_table=False, image_count=0)


def _linha(n, assunto, tipo, continua):
    return {"n": n, "subject": assunto, "type": tipo, "detail": "d", "continues": continua}


def test_mesmo_tipo_com_continues_vira_uma_peca():
    """O relatório de 29 páginas do processo real saía em ~25 peças: o assunto
    de cada página é o parágrafo que ela traz, mas o tipo é o mesmo."""
    from gclaude_indexer.engine_local import _group_pages_into_items

    paginas = [_pagina(f"f. {i}") for i in (1, 2, 3)]
    linhas = [_linha(1, "Exame da defesa do responsável", "RELATÓRIO", False),
              _linha(2, "Jurisprudência sobre débito", "RELATÓRIO", True),
              _linha(3, "Conclusão da análise", "RELATÓRIO", True)]
    itens = _group_pages_into_items(paginas, linhas)
    assert [(i.start_ref, i.end_ref) for i in itens] == [("f. 1", "f. 3")]


def test_tipo_diferente_ou_sem_continues_separa():
    from gclaude_indexer.engine_local import _group_pages_into_items

    paginas = [_pagina(f"f. {i}") for i in (1, 2, 3)]
    linhas = [_linha(1, "Exame da defesa", "RELATÓRIO", False),
              _linha(2, "Ementa do julgado", "ACÓRDÃO", True),
              _linha(3, "Outra ementa", "ACÓRDÃO", False)]
    itens = _group_pages_into_items(paginas, linhas)
    assert len(itens) == 3


def test_mesmo_tipo_em_outro_arquivo_nao_junta():
    """Dois termos iguais, um em cada PDF, continuam duas peças."""
    from gclaude_indexer.engine_local import _group_pages_into_items

    paginas = [_pagina("f. 1", "a.pdf"), _pagina("f. 2", "b.pdf")]
    linhas = [_linha(1, "Endereço de Fulano no cadastro", "TERMO", False),
              _linha(2, "Busca por Beltrano na Receita", "TERMO", True)]
    assert len(_group_pages_into_items(paginas, linhas)) == 2


def test_prompt_por_pagina_nao_leva_o_bloco_do_projeto():
    """2.1.0: medido com gabarito, o Tema no prompt fez o modelo cortar pior
    os documentos (F1 73,7% -> 50,0% num processo real); o prompt por página
    fica como sempre foi numa execução pela interface, sem o bloco."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.engine_local import _build_page_prompt

    config = ProjectConfig(name="x", source_folder=".", output_folder=".", subject="Obras da escola municipal",
                           extra_rules="Observar a legislação")
    prompt = _build_page_prompt([_pagina("f. 1")], config)
    assert "Obras da escola" not in prompt and "Observar a legislação" not in prompt
    assert "Contexto deste acervo" not in prompt

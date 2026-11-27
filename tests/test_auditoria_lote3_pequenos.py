"""2.1.6: correções pequenas do motor local apontadas na auditoria."""

from __future__ import annotations

from gclaude_indexer.classification import WindowPage
from gclaude_indexer.engine_local import LocalEngine, _group_pages_into_items


def _pagina(arquivo, referencia, ordem):
    return WindowPage(
        reference=referencia, file_name=arquivo, text="texto", has_table=False, image_count=0, order=ordem,
    )


def test_assunto_do_documento_anterior_nao_vaza_para_o_seguinte():
    """Ao abrir um documento novo, o assunto da peça anterior é esquecido. A
    1ª página do documento B veio sem assunto; a 2ª, com o mesmo assunto da
    peça A e `continues` falso, era juntada à 1ª porque o código ainda
    comparava com o assunto de A."""
    paginas = [_pagina("a.docx", "f. 1", 1), _pagina("b.pdf", "f. 2", 2), _pagina("b.pdf", "f. 3", 3)]
    linhas = [
        {"n": 1, "subject": "Contrato de manutenção", "type": "CONTRATO", "continues": False},
        {"n": 2, "subject": None, "type": "OFÍCIO", "continues": False},
        {"n": 3, "subject": "Contrato de manutenção", "type": "RELATÓRIO", "continues": False},
    ]
    pecas = _group_pages_into_items(paginas, linhas)
    assert [(p.start_ref, p.end_ref) for p in pecas] == [("f. 1", "f. 1"), ("f. 2", "f. 2"), ("f. 3", "f. 3")]


class _MotorQueDivide(LocalEngine):
    """Recusa (resposta inválida) trechos de mais de uma página; cada página
    sozinha sai com uma nota de contexto, como o motor real deixaria."""

    def is_available(self):
        return True

    def classify(self, pages):
        from gclaude_indexer.engine_local import ModelAnswerError

        self.last_window_warnings = []
        self.last_window_notes = []
        if len(pages) > 1:
            raise ModelAnswerError("answer cut at 3168 tokens (repetition loop)")
        self.last_window_notes = [(
            "log.local_engine.window_context_raised", {"from": 4096, "to": 8192},
        )]
        linhas = [{"n": 1, "subject": f"assunto {pages[0].reference}", "type": "OFÍCIO", "detail": "x"}]
        return _group_pages_into_items(pages, linhas)


def test_notas_da_janela_dividida_vao_para_o_log(tmp_path):
    """Quando a resposta da janela inteira é inválida e ela é dividida, as
    notas das metades (contexto aumentado, divisão por tamanho) também são
    gravadas — antes o ramo da divisão pulava o registro delas."""
    from gclaude_indexer.engine_local import classify_pending
    from tests.test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar

    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR] * 3)
    motor = _MotorQueDivide(model="fake", url_base="http://127.0.0.1:9")
    resultado = classify_pending(conn, config, local_engine=motor)
    notas = conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.local_engine.window_note'"
    ).fetchone()[0]
    conn.close()
    assert notas >= 3
    assert resultado.windows_context_raised >= 3


def test_janela_sem_carregador_tambem_limpa_texto_binario(tmp_path):
    """`load_window_pages` sem o carregador devolvia o texto cru: os bytes de
    um binário antigo (com `\x00`) chegavam ao modelo por esse caminho."""
    from gclaude_indexer.classification import WindowPageLoader, load_window_pages
    from tests.test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar

    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR] * 2)
    conn.execute("UPDATE page SET text = ? WHERE id = (SELECT MIN(id) FROM page)", ("PK\x03\x04\x00\x00lixo",))
    conn.commit()
    janela = conn.execute("SELECT * FROM window ORDER BY id LIMIT 1").fetchone()
    sem = load_window_pages(conn, janela)
    com = load_window_pages(conn, janela, loader=WindowPageLoader(conn))
    conn.close()
    assert [p.text for p in sem] == [p.text for p in com]
    assert sem[0].text == ""

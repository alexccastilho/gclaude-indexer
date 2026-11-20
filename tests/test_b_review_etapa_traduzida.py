"""A seção de erros do review.md mostra a etapa pelo nome traduzido, como a
tela de log (`_log_items.html`), e não pelo id gravado em `event.step`."""

from __future__ import annotations

from gclaude_indexer.artifacts import generate_review_md
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import record_event
from gclaude_indexer.i18n import translate


def _projeto(tmp_path):
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Etapa no review",
        "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida),
        "extensions": ["pdf"],
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return config, conn


def test_etapa_do_erro_sai_com_o_nome_do_idioma_do_relatorio(tmp_path):
    config, conn = _projeto(tmp_path)
    record_event(conn, "conversion", "error", "log.conversion.failed", {"name": "a.pdf", "error": "x"})
    record_event(conn, "instructions", "error", "texto solto sem chave")

    for idioma in ("pt", "en", "es"):
        texto = generate_review_md(conn, config, idioma).read_text(encoding="utf-8")
        assert f"({translate(idioma, 'step.conversion.title')}) " in texto
        assert f"({translate(idioma, 'step.instructions.title')}) texto solto sem chave" in texto
        assert "(conversion)" not in texto and "(instructions)" not in texto
    conn.close()


def test_etapa_desconhecida_sai_como_foi_gravada(tmp_path):
    config, conn = _projeto(tmp_path)
    record_event(conn, "etapa_que_nao_existe", "error", "algo falhou")

    texto = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")

    assert "(etapa_que_nao_existe) algo falhou" in texto
    conn.close()

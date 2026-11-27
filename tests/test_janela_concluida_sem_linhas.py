"""Janela `done` sem nenhuma linha no `raw_items.jsonl`.

Caso real (2.1.5): o projeto foi classificado em dois PCs pela
mesma pasta do Google Drive. O banco chegou ao segundo PC com as janelas
do primeiro marcadas `done`, mas as linhas que o primeiro acrescentou ao
`raw_items.jsonl` não chegaram. A importação gravou o índice só com o que
havia no arquivo, e centenas de janelas viraram "lacunas" no Resultado sem nenhum
aviso. Como estavam `done`, nada as classificaria de novo.

Toda janela classificada deixa ao menos uma linha (a garantia de
cobertura dos dois motores). Uma janela `done` sem linha nenhuma, então,
perdeu as peças: ela volta para a fila, na importação e no começo da
classificação, com um aviso dizendo quantas e de quais grupos."""

from __future__ import annotations

import json
from pathlib import Path

from gclaude_indexer import engine_rules
from gclaude_indexer.events import list_events
from gclaude_indexer.import_items import import_and_consolidate
from gclaude_indexer.paths import RAW_ITEMS_FILE_NAME

from tests.test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar


def _classificado(tmp_path):
    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [f"{TEXTO_LONGO_SEM_MARCADOR} Página {n}." for n in range(1, 24 + 1)],
        pages_per_window=8, overlap=0,
    )
    engine_rules.classify_pending(conn, config, language="pt")
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0] == 0
    return config, conn


def _caminho(config) -> Path:
    return Path(config.output_folder) / RAW_ITEMS_FILE_NAME


def _janelas_com_linhas(config) -> set[str]:
    return {
        json.loads(linha)["window"]
        for linha in _caminho(config).read_text(encoding="utf-8").splitlines()
        if linha.strip()
    }


def _apagar_linhas_da_janela(config, chave: str) -> None:
    caminho = _caminho(config)
    linhas = caminho.read_text(encoding="utf-8").splitlines(keepends=True)
    restantes = [linha for linha in linhas if json.loads(linha)["window"] != chave]
    assert len(restantes) < len(linhas)
    caminho.write_text("".join(restantes), encoding="utf-8")


def _segunda_janela(conn) -> str:
    return conn.execute("SELECT key FROM window ORDER BY id LIMIT 1 OFFSET 1").fetchone()[0]


def _pendentes(conn) -> list[str]:
    return [linha[0] for linha in conn.execute("SELECT key FROM window WHERE status = 'pending' ORDER BY id")]


def _eventos(conn, chave: str) -> list[dict]:
    return [evento for evento in list_events(conn, language="pt") if evento["message_key"] == chave]


def test_importacao_devolve_para_a_fila_a_janela_concluida_sem_linhas(tmp_path):
    config, conn = _classificado(tmp_path)
    perdida = _segunda_janela(conn)
    _apagar_linhas_da_janela(config, perdida)

    import_and_consolidate(conn, config, language="pt")

    assert _pendentes(conn) == [perdida]
    avisos = _eventos(conn, "log.import.windows_without_items")
    assert len(avisos) == 1
    assert avisos[0]["level"] == "warning"
    assert "1 trecho" in avisos[0]["message"]
    conn.close()


def test_importacao_sem_janela_perdida_nao_avisa_nem_mexe_na_fila(tmp_path):
    config, conn = _classificado(tmp_path)

    import_and_consolidate(conn, config, language="pt")

    assert _pendentes(conn) == []
    assert _eventos(conn, "log.import.windows_without_items") == []
    conn.close()


def test_classificacao_refaz_a_janela_concluida_sem_linhas(tmp_path):
    """Quem roda a classificação sem importar antes também recupera a janela."""
    config, conn = _classificado(tmp_path)
    perdida = _segunda_janela(conn)
    _apagar_linhas_da_janela(config, perdida)

    resultado = engine_rules.classify_pending(conn, config, language="pt")

    assert resultado.windows_processed == 1
    assert perdida in _janelas_com_linhas(config)
    assert _pendentes(conn) == []
    assert len(_eventos(conn, "log.classification.windows_without_items")) == 1
    conn.close()


def test_mensagens_novas_existem_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave in (
            "log.import.windows_without_items",
            "log.classification.windows_without_items",
            "result.process_pending",
        ):
            assert translate(idioma, chave) != chave, (idioma, chave)


# --- botão "Classificar as pendências" no Resultado ---------------------------


def test_resultado_com_janela_pendente_oferece_classificar_as_pendencias(tmp_path, monkeypatch):
    from gclaude_indexer.i18n import translate
    from tests.test_phase31 import _app_com_projeto

    cliente, pid, conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    conn.execute(
        "INSERT INTO window (key, group_key, start_ref, end_ref, status)"
        " VALUES ('Processo::000001-000008', 'Processo', 'f. 1', 'f. 8', 'pending')"
    )
    conn.commit()

    resposta = cliente.get(f"/projects/{pid}/result", cookies={"language": "pt"})

    assert f'action="/projects/{pid}/process-pending"' in resposta.text
    assert translate("pt", "result.process_pending") in resposta.text


def test_resultado_sem_pendencia_nenhuma_nao_oferece_o_botao(tmp_path, monkeypatch):
    from tests.test_phase31 import _app_com_projeto, _peca

    cliente, pid, conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    # O fixture só cobre a folha 5 de "Processo": o resto vira peça também,
    # para não sobrar lacuna.
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    _peca(conn, "Avulsos", 1, 2, "OFÍCIO", "anexo.pdf")

    resposta = cliente.get(f"/projects/{pid}/result", cookies={"language": "pt"})

    assert "/process-pending" not in resposta.text


def test_rota_de_pendencias_roda_a_cadeia_da_etapa_pendente_e_vai_para_a_execucao(tmp_path, monkeypatch):
    from gclaude_indexer.run_control import StopSignal
    from gclaude_indexer.web.background_runs import task_manager
    from gclaude_indexer.web.step_state import next_pending_step, step_status
    from tests.test_phase31 import _app_com_projeto

    cliente, pid, conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas: list[dict] = []
    monkeypatch.setattr(task_manager, "start_all", lambda *a, **k: chamadas.append(k) or StopSignal())
    esperada = next_pending_step(step_status(conn, lambda _k: False))

    resposta = cliente.post(
        f"/projects/{pid}/process-pending", cookies={"language": "pt"}, follow_redirects=False
    )

    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/projects/{pid}/run"
    assert [c.get("first_step") for c in chamadas] == [esperada]


# --- a sequência real: lacunas no Resultado, sem janela pendente --------------


def _app_com_projeto_que_perdeu_linhas(tmp_path):
    """O estado do caso real: classificado, importado e só depois com as linhas de
    uma janela sumidas do arquivo. Nenhuma janela pendente; o Resultado
    mostra a lacuna."""
    from fastapi.testclient import TestClient

    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json
    from gclaude_indexer.web.app import app

    config, conn = _classificado(tmp_path)
    import_and_consolidate(conn, config, language="pt")
    perdida = _segunda_janela(conn)
    _apagar_linhas_da_janela(config, perdida)
    conn.execute("DELETE FROM project")
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-11-26T00:00:00')",
        (config.name, config.source_folder, config.output_folder, config_to_json(config)),
    )
    # A importação de antes da perda gravou as peças; agora o índice perde a
    # janela, como depois de importar o arquivo incompleto.
    conn.execute("DELETE FROM item WHERE start_order BETWEEN 9 AND 16")
    conn.commit()
    entry = register_project(config.name, config.output_folder)
    return TestClient(app), entry.id, conn, perdida


def test_resultado_com_lacuna_e_sem_janela_pendente_oferece_o_botao(tmp_path, monkeypatch):
    cliente, pid, conn, _perdida = _app_com_projeto_que_perdeu_linhas(tmp_path)
    assert _pendentes(conn) == []

    resposta = cliente.get(f"/projects/{pid}/result", cookies={"language": "pt"})

    assert f'action="/projects/{pid}/process-pending"' in resposta.text
    conn.close()


def test_botao_devolve_a_janela_sem_linhas_e_comeca_pela_classificacao(tmp_path, monkeypatch):
    from gclaude_indexer.run_control import StopSignal
    from gclaude_indexer.web.background_runs import task_manager

    cliente, pid, conn, perdida = _app_com_projeto_que_perdeu_linhas(tmp_path)
    chamadas: list[dict] = []
    monkeypatch.setattr(task_manager, "start_all", lambda *a, **k: chamadas.append(k) or StopSignal())

    resposta = cliente.post(
        f"/projects/{pid}/process-pending", cookies={"language": "pt"}, follow_redirects=False
    )

    assert resposta.status_code == 303
    assert _pendentes(conn) == [perdida]
    assert [c.get("first_step") for c in chamadas] == ["classification"]
    conn.close()

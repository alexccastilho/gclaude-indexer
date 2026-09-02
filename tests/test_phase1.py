"""Phase 1 tests: database schema, project configuration and event log."""

from __future__ import annotations

import sqlite3

import pytest

from gclaude_indexer.config import ProjectConfig, ConfigError, load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import record_event, list_events
from gclaude_indexer.paths import app_root, resolve_within
from gclaude_indexer.project import create_project


# --- paths ---------------------------------------------------------------


def test_raiz_app_sem_caminho_absoluto_fixo():
    raiz = app_root()
    assert raiz.is_dir()
    assert (raiz / "gclaude_indexer").is_dir()


def test_resolver_dentro_aceita_caminho_valido(tmp_path):
    (tmp_path / "sub").mkdir()
    resultado = resolve_within(tmp_path, "sub/arquivo.txt")
    assert resultado == (tmp_path / "sub" / "arquivo.txt").resolve()


def test_resolver_dentro_recusa_escape_por_dotdot(tmp_path):
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "../fora.txt")


# --- db --------------------------------------------------------------------


def test_inicializar_schema_cria_tabelas_e_indices(tmp_path):
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    init_schema(conn)  # idempotente

    tabelas = {
        linha["name"]
        for linha in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"project", "file", "page", "window", "item", "event"} <= tabelas

    indices = {
        linha["name"]
        for linha in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {
        "idx_file_status",
        "idx_page_file_id",
        "idx_item_group_key_order",
    } <= indices

    modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "delete"

    conn.close()


# --- config ------------------------------------------------------------


def test_carregar_config_aplica_defaults(tmp_path):
    config = load_config(
        {"name": "Processo 123", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "saida")}
    )
    assert isinstance(config, ProjectConfig)
    assert config.collection_type == "processo"
    assert config.pages_per_block == 80
    assert config.pages_per_window == 16
    assert config.overlap == 2
    assert config.extensions == ["pdf", "docx", "imagens"]


def test_carregar_config_pasta_origem_inexistente():
    with pytest.raises(ConfigError):
        load_config(
            {"name": "X", "source_folder": "Z:/nao/existe", "output_folder": "Z:/saida"}
        )


def test_config_error_carrega_chave_e_parametros_no_lugar_de_texto_fixo():
    """Defect 3 (Task 18): `_validate()` used to build ready-made Portuguese
    sentences (`f"source_folder não existe: {path}"`), shown verbatim by
    `new_project.html` regardless of the interface's language. `errors`
    must carry a `ConfigErrorMessage(key, params)` instead — text rendered
    by whoever displays it, in whichever language that is (see `config.py`'s
    module docstring)."""
    from gclaude_indexer.config import ConfigErrorMessage
    from gclaude_indexer.i18n import translate

    with pytest.raises(ConfigError) as info:
        load_config({"name": "X", "source_folder": "Z:/nao/existe/xyz", "output_folder": "Z:/saida"})

    erros = info.value.errors
    assert all(isinstance(e, ConfigErrorMessage) for e in erros)
    alvo = next(e for e in erros if e.key == "config_error.source_folder_not_found")
    assert alvo.params == {"path": "Z:/nao/existe/xyz"}

    # same key, three different renderings — no hardcoded language baked in.
    assert "não existe" in translate("pt", alvo.key, **alvo.params)
    assert "does not exist" in translate("en", alvo.key, **alvo.params)
    assert "no existe" in translate("es", alvo.key, **alvo.params)


def test_carregar_config_sobreposicao_invalida(tmp_path):
    with pytest.raises(ConfigError):
        load_config(
            {
                "name": "X",
                "source_folder": str(tmp_path),
                "output_folder": str(tmp_path / "saida"),
                "pages_per_window": 5,
                "overlap": 5,
            }
        )


# --- eventos -----------------------------------------------------------


def test_registrar_e_listar_eventos(tmp_path):
    conn = connect(tmp_path / "project.db")
    init_schema(conn)

    record_event(conn, "scan", "info", "início")
    record_event(conn, "scan", "warning", "arquivo estranho")
    record_event(conn, "conversion", "error", "falhou")

    todos = list_events(conn)
    assert len(todos) == 3
    assert [e["level"] for e in todos] == ["info", "warning", "error"]

    so_varredura = list_events(conn, step="scan")
    assert len(so_varredura) == 2

    conn.close()


def test_registrar_evento_nivel_invalido(tmp_path):
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    with pytest.raises(ValueError):
        record_event(conn, "scan", "critico", "x")
    conn.close()


# --- Tarefa 12 (Fase 14): chave + parâmetros, retraduzidos na leitura ------


def test_evento_com_chave_grava_message_key_e_params_e_traduz_no_idioma_gravado(tmp_path):
    """Sem `language` explícito, `record_event` usa `DEFAULT_LANGUAGE` — o
    teste fixa isso lendo de volta com o mesmo `language=None`, então
    comparando com uma tradução explícita para o mesmo idioma."""
    from gclaude_indexer.i18n import DEFAULT_LANGUAGE, translate

    conn = connect(tmp_path / "project.db")
    init_schema(conn)

    record_event(conn, "scan", "info", "log.scan.content_changed", {"name": "x.pdf"})

    linha = conn.execute("SELECT * FROM event").fetchone()
    assert linha["message_key"] == "log.scan.content_changed"
    assert linha["message_params"] is not None
    assert linha["message"] == translate(DEFAULT_LANGUAGE, "log.scan.content_changed", name="x.pdf")

    conn.close()


def test_evento_com_chave_e_retraduzido_ao_listar_em_outro_idioma(tmp_path):
    """O ponto central da Tarefa 12: gravar em um idioma não congela o
    histórico — `list_events(conn, language=...)` traduz de novo, para
    qualquer um dos três idiomas, a partir de `message_key`/`message_params`."""
    conn = connect(tmp_path / "project.db")
    init_schema(conn)

    record_event(
        conn, "scan", "warning", "log.scan.extension_not_allowed",
        {"name": "estranho.xyz", "extension": "xyz"}, language="pt",
    )

    em_pt = list_events(conn, language="pt")[0]["message"]
    em_en = list_events(conn, language="en")[0]["message"]
    em_es = list_events(conn, language="es")[0]["message"]

    assert "ignorado" in em_pt
    assert "ignored" in em_en
    assert "ignorada" in em_es
    # o parâmetro (não traduzível) aparece nas três versões
    assert "estranho.xyz" in em_pt and "estranho.xyz" in em_en and "estranho.xyz" in em_es

    # sem `language`, `list_events` devolve o texto exatamente como gravado
    # (idioma de escrita, "pt" aqui) — mesmo comportamento do arquivo de log.
    assert list_events(conn)[0]["message"] == em_pt

    conn.close()


def test_evento_com_texto_literal_sem_chave_correspondente_nao_e_traduzido(tmp_path):
    """`record_event` aceita texto solto (sem entrada na tabela de tradução)
    como um evento sem chave — legado/ad hoc — mostrado como está, em
    qualquer idioma: "sem chave, mostra `message`"."""
    conn = connect(tmp_path / "project.db")
    init_schema(conn)

    record_event(conn, "scan", "info", "texto qualquer, não é uma chave i18n")

    linha = conn.execute("SELECT * FROM event").fetchone()
    assert linha["message_key"] is None
    assert linha["message_params"] is None
    assert linha["message"] == "texto qualquer, não é uma chave i18n"

    for idioma in ("pt", "en", "es"):
        assert list_events(conn, language=idioma)[0]["message"] == "texto qualquer, não é uma chave i18n"

    conn.close()


def test_init_schema_duas_vezes_nao_quebra_as_colunas_de_message_key(tmp_path):
    """`ALTER TABLE ADD COLUMN` não é `IF NOT EXISTS` — `init_schema` (chamado
    de novo a cada `load_project`, ver `project.py`) precisa continuar
    idempotente depois de adicionar `message_key`/`message_params`."""
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    init_schema(conn)  # não pode levantar "duplicate column name"

    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(event)").fetchall()}
    assert {"message_key", "message_params"} <= colunas

    conn.close()


# --- fluxo de ponta a ponta ----------------------------------------------


def test_fase1_fluxo_completo(tmp_path):
    """Cria um projeto de exemplo, grava três eventos e lê de volta."""
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "documento.txt").write_text("conteúdo de exemplo", encoding="utf-8")
    saida = tmp_path / "origem_indexado"

    config = load_config(
        {
            "name": "Projeto de Exemplo",
            "subject": "Acervo de teste",
            "source_folder": str(origem),
            "output_folder": str(saida),
        }
    )

    conn, projeto_id = create_project(config)
    try:
        assert projeto_id == 1
        assert (saida / "project.db").exists()

        linha_projeto = conn.execute(
            "SELECT * FROM project WHERE id = ?", (projeto_id,)
        ).fetchone()
        assert linha_projeto["name"] == "Projeto de Exemplo"
        assert linha_projeto["source_folder"] == str(origem)

        record_event(conn, "scan", "info", "1 arquivo encontrado")
        record_event(conn, "conversion", "info", "documento.txt extraído")
        record_event(conn, "conversion", "warning", "sem camada de texto detectável")

        eventos = list_events(conn)
        assert len(eventos) == 3
        assert [e["step"] for e in eventos] == ["scan", "conversion", "conversion"]
        assert [e["message"] for e in eventos] == [
            "1 arquivo encontrado",
            "documento.txt extraído",
            "sem camada de texto detectável",
        ]
    finally:
        conn.close()

    # Reabrir o banco confirma que os dados sobrevivem ao fechamento da conexão.
    conn2 = connect(saida / "project.db")
    eventos_persistidos = list_events(conn2)
    assert len(eventos_persistidos) == 3
    conn2.close()

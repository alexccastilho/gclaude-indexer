"""O CLAUDE.md gravado ou mudado entra na lista de `log.artifacts.changed`,
como os outros arquivos de saída: é a lista do que mandar de novo."""

from __future__ import annotations

import json

from gclaude_indexer import artifacts
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.output_names import CLAUDE_MD_FILENAME


def _projeto(tmp_path):
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Log do CLAUDE.md",
        "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida),
        "extensions": ["pdf"],
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return config, conn


def _ultima_lista(conn) -> list[str]:
    linha = conn.execute(
        "SELECT message_params FROM event WHERE message_key = 'log.artifacts.changed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert linha is not None
    return json.loads(linha[0])["files"].split(", ")


def test_claude_md_novo_aparece_entre_os_arquivos_mudados(tmp_path):
    config, conn = _projeto(tmp_path)

    artifacts.generate_all_artifacts(conn, config, "pt")

    assert CLAUDE_MD_FILENAME in _ultima_lista(conn)
    conn.close()


def test_claude_md_mudado_aparece_e_igual_nao_aparece(tmp_path):
    config, conn = _projeto(tmp_path)
    artifacts.generate_all_artifacts(conn, config, "pt")

    # Outro idioma muda a prosa do CLAUDE.md (e a dos demais arquivos).
    artifacts.generate_all_artifacts(conn, config, "en")
    assert CLAUDE_MD_FILENAME in _ultima_lista(conn)

    antes = conn.execute("SELECT COUNT(*) FROM event WHERE message_key = 'log.artifacts.changed'").fetchone()[0]
    artifacts.generate_all_artifacts(conn, config, "en")
    depois = conn.execute("SELECT COUNT(*) FROM event WHERE message_key = 'log.artifacts.changed'").fetchone()[0]
    if depois > antes:
        assert CLAUDE_MD_FILENAME not in _ultima_lista(conn)
    conn.close()

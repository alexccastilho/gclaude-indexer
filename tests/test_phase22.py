"""Phase 22 tests: making "import and generate reports" usable on a real
acquis stored on a network drive.

The two defects this phase fixes were found on a live project whose output
folder lives on Google Drive (`H:`), with 5230 items across 3 groups:

1. `_validate_range_within_group` re-ran the same "all pages of this group"
   query once per item — 5230 queries where 3 would do. Measured on that
   project: 9.3 ms per item on a local SSD, 488 ms per item on the Drive,
   i.e. ~41 minutes for a single import.

2. The route ran the import synchronously inside the HTTP handler, outside
   `task_manager`. With no progress feedback the user clicked again, and a
   stack dump showed 4 concurrent `import_and_generate` threads fighting over
   the GIL and the same SQLite file.
"""

from __future__ import annotations

from gclaude_indexer.import_items import import_and_consolidate

from .test_phase6 import _escrever_jsonl, _peca, _projeto_com_paginas


class _ContadorDeConsultas:
    """Counts how many times the page-range query reaches SQLite.

    Uses `set_trace_callback`, so it counts statements actually executed by
    the connection — not calls to a Python helper that a fix could rename.
    """

    def __init__(self, conn):
        self.conn = conn
        self.consultas_de_pagina = 0

    def __enter__(self):
        self.conn.set_trace_callback(self._registrar)
        return self

    def __exit__(self, *_):
        self.conn.set_trace_callback(None)
        return False

    def _registrar(self, sql: str) -> None:
        normalizada = " ".join(sql.split()).lower()
        if "from page join file" in normalizada and "group_key" in normalizada:
            self.consultas_de_pagina += 1


def test_validacao_de_intervalo_consulta_as_paginas_uma_vez_por_agrupador(tmp_path):
    """Importing many items of the same group must not re-read that group's
    pages once per item — the range check only depends on the group."""
    origem, saida, config, conn = _projeto_com_paginas(tmp_path, n_paginas=6)
    _escrever_jsonl(saida, [_peca(order_start=indice, order_end=indice) for indice in range(1, 7)])

    with _ContadorDeConsultas(conn) as contador:
        resultado = import_and_consolidate(conn, config)

    assert resultado.valid_items == 6, "as 6 peças são válidas e devem ser importadas"
    assert contador.consultas_de_pagina == 1, (
        f"o agrupador é sempre o mesmo, então basta uma consulta de páginas; "
        f"foram {contador.consultas_de_pagina}"
    )


# --- concurrency guard on "import and generate reports" --------------------


def _projeto_registrado(tmp_path, monkeypatch):
    """A project the web app can open, the way `test_phase17` builds one."""
    from gclaude_indexer import db, paths
    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.config import config_to_json, load_config

    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(tmp_path / "local"))

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()

    config = load_config(
        {"name": "Fase 22", "subject": "Acervo", "source_folder": str(origem), "output_folder": str(saida)}
    )
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO project (name, source_folder, output_folder, config_json, created_at)"
        " VALUES (?, ?, ?, ?, '2026-09-16T00:00:00')",
        (config.name, str(origem), str(saida), config_to_json(config)),
    )
    conn.commit()

    return register_project("acervo", str(saida)).id


def test_importar_e_gerar_nao_roda_duas_vezes_ao_mesmo_tempo(tmp_path, monkeypatch):
    """Clicking the button again while the import is still running must not
    start a second import.

    On the live project this is exactly what happened: with no progress
    feedback the user clicked again, and a stack dump of the server showed 4
    concurrent `import_and_generate` threads, each about to run
    `DELETE FROM item` followed by thousands of inserts on the same file.
    """
    import threading

    from fastapi.testclient import TestClient

    from gclaude_indexer.web import app as app_module

    project_id = _projeto_registrado(tmp_path, monkeypatch)

    entrou = threading.Event()
    liberar = threading.Event()
    chamadas = []

    def _import_lento(conn, config, language=None):
        chamadas.append(language)
        entrou.set()
        liberar.wait(timeout=10)

    monkeypatch.setattr(app_module, "import_and_consolidate", _import_lento)
    monkeypatch.setattr(app_module, "generate_all_artifacts", lambda *a, **k: None)

    cliente = TestClient(app_module.app)
    rota = f"/projects/{project_id}/import-and-generate"

    primeira = threading.Thread(target=lambda: cliente.post(rota, follow_redirects=False))
    primeira.start()
    assert entrou.wait(timeout=10), "a primeira importação deveria ter começado"

    cliente.post(rota, follow_redirects=False)  # segundo clique, com a primeira presa

    liberar.set()
    primeira.join(timeout=10)

    assert len(chamadas) == 1, (
        f"o segundo clique não pode iniciar outra importação; foram {len(chamadas)} execuções"
    )

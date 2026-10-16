"""O que acontece quando um documento sai da pasta de origem.

A análise da remoção (fase 17) achou cinco furos, um teste para cada:

1. remover o original de um par de duplicatas tirava o documento do índice,
   embora a cópia continuasse na pasta;
2. `removed_file` só crescia — um arquivo devolvido seguia "removido" para
   sempre, e remover o mesmo caminho duas vezes gravava duas linhas;
3. o intermediário em `converted/` do arquivo removido ficava no disco;
4. o `index-<grupo>.md` de um grupo que sumiu continuava na pasta de saída e
   ia para o pacote do Claude;
5. a renumeração das folhas dos volumes seguintes não era dita a ninguém.
"""

from __future__ import annotations

import hashlib

from gclaude_indexer.artifacts import generate_index_md, group_index_filename
from gclaude_indexer.events import list_events
from gclaude_indexer.invalidation import apply_update_plan
from gclaude_indexer.update_plan import build_update_plan, detect_changes

from tests.test_phase17 import _config, _conn, _group_key, _registrar_com_paginas


def _acervo(tmp_path, nomes=("a.pdf", "b.pdf", "c.pdf")):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = _conn(saida)
    grupo = _group_key(origem, saida)
    for nome in nomes:
        (origem / nome).write_text(nome, encoding="utf-8")
        _registrar_com_paginas(conn, origem, nome, 10, grupo)
    return origem, saida, conn, _config(origem, saida)


def _aplicar(conn, config):
    return apply_update_plan(conn, config, build_update_plan(conn, config), language="pt")


def test_remover_o_original_devolve_a_copia_ao_acervo(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path)
    copia = origem / "copia-de-b.pdf"
    copia.write_text("b.pdf", encoding="utf-8")
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status)"
        " VALUES (?, ?, 'pdf', 5, ?, ?, 'duplicate')",
        ("copia-de-b.pdf", "copia-de-b.pdf",
         hashlib.sha256(b"b.pdf").hexdigest(), copia.stat().st_mtime),
    )
    conn.commit()
    (origem / "b.pdf").unlink()

    _aplicar(conn, config)

    # A cópia deixa de ser "duplicata de algo que não existe mais": a
    # próxima atualização a enxerga como documento novo e a indexa.
    novos = [c.relative_path for c in detect_changes(conn, config)[0] if c.kind == "new"]
    assert novos == ["copia-de-b.pdf"]
    mensagens = " ".join(e["message"] for e in list_events(conn, language="pt"))
    assert "copia-de-b.pdf" in mensagens


def test_removido_registrado_uma_vez_e_esquecido_quando_volta(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path)
    (origem / "c.pdf").unlink()
    _aplicar(conn, config)
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 1

    # Devolvido à pasta e reindexado: não pode seguir listado como removido.
    from gclaude_indexer.scanning import scan

    (origem / "c.pdf").write_text("c.pdf", encoding="utf-8")
    scan(conn, config)
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0


def test_intermediario_do_removido_sai_do_disco(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path)
    conn.execute("UPDATE file SET needs_ocr = 1 WHERE relative_path = 'b.pdf'")
    conn.commit()
    intermediario = saida / "converted" / "b.pdf"
    intermediario.parent.mkdir()
    intermediario.write_bytes(b"pdf com ocr")
    (origem / "b.pdf").unlink()

    _aplicar(conn, config)

    assert not intermediario.exists()


def test_indice_de_grupo_que_sumiu_e_apagado(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path)
    velho = saida / group_index_filename("grupo-que-nao-existe-mais")
    velho.write_text("peças antigas", encoding="utf-8")

    generate_index_md(conn, config, "pt")

    assert not velho.exists()


def test_grupos_com_nomes_parecidos_nao_dividem_o_mesmo_indice(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path, nomes=())
    for grupo in ("A/B", "A-B"):
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order,"
            " type, engine, confidence, files)"
            " VALUES (?, 'f. 1', 'f. 1', 1, 1, 'OFÍCIO', 'rules', 'high', 'x.pdf')",
            (grupo,),
        )
    conn.commit()

    caminhos = generate_index_md(conn, config, "pt")

    assert len({c.name for c in caminhos}) == 3  # sumário + um por grupo


def test_renumeracao_e_avisada_com_os_nomes(tmp_path):
    origem, saida, conn, config = _acervo(tmp_path)
    (origem / "b.pdf").unlink()

    _aplicar(conn, config)

    avisos = [e for e in list_events(conn, language="pt") if e["level"] == "warning"]
    assert any("c.pdf" in e["message"] and "f." in e["message"] for e in avisos)


def test_projeto_que_nunca_rodou_nao_avisa_que_a_pasta_mudou(tmp_path, monkeypatch):
    """Antes da primeira execução, todo documento é "novo" para o plano de
    atualização — e a tela Execução recebia quem acabou de criar o projeto
    com "A pasta de origem mudou: 3 novos" e um botão de atualizar. A
    primeira execução já lê tudo; o aviso só faz sentido depois dela."""
    from fastapi.testclient import TestClient

    from gclaude_indexer.catalog import register_project
    from gclaude_indexer.project import create_project
    from gclaude_indexer.web.app import app, lock_manager

    local = tmp_path / "local"
    for alvo in ("gclaude_indexer.catalog.machine_local_folder",
                 "gclaude_indexer.hardware.machine_local_folder",
                 "gclaude_indexer.sync.machine_local_folder"):
        monkeypatch.setattr(alvo, lambda: local)
    lock_manager.close_all()

    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    saida = tmp_path / "saida"
    config = _config(origem, saida)
    conn, _ = create_project(config)
    conn.close()
    entrada = register_project(config.name, str(saida))

    resposta = TestClient(app).get(f"/projects/{entrada.id}/update/banner")
    assert resposta.status_code == 200
    lock_manager.close_all()
    assert resposta.text.strip() == ""

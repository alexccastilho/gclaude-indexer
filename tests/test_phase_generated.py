# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""2.0.0: nenhum arquivo gerado por qualquer projeto entra no inventário."""

from __future__ import annotations

from pathlib import Path

from gclaude_indexer import db
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.invalidation import apply_pending_changes
from gclaude_indexer.paths import OUTPUT_MARKER_NAME
from gclaude_indexer.source_folder import walk_source_stats
from gclaude_indexer.update_plan import build_update_plan


def _config(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="all_together", extensions=["pdf", "text"],
    )


def _nomes(listagem, origem: Path) -> set[str]:
    return {item.path.relative_to(origem).as_posix() for item in listagem}


def test_saida_de_outro_projeto_dentro_da_origem_e_pulada(tmp_path):
    origem = tmp_path / "origem"
    outro = origem / "outro-ai"
    outro.mkdir(parents=True)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    (outro / "project.db").write_bytes(b"")
    (outro / "index.md").write_text("gerado", encoding="utf-8")

    listagem = walk_source_stats(origem.resolve(), (tmp_path / "saida").resolve())

    assert _nomes(listagem, origem.resolve()) == {"a.pdf"}
    assert listagem.skipped_folders == ["outro-ai"]


def test_pasta_de_conjunto_com_marcador_e_pulada(tmp_path):
    origem = tmp_path / "origem"
    conjunto = origem / "sub" / "combinada"
    conjunto.mkdir(parents=True)
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    (conjunto / OUTPUT_MARKER_NAME).write_text("x", encoding="utf-8")
    (conjunto / "atas__index.md").write_text("gerado", encoding="utf-8")

    listagem = walk_source_stats(origem.resolve(), (tmp_path / "saida").resolve())

    assert _nomes(listagem, origem.resolve()) == {"a.pdf"}


def _registrar(conn, relative_path: str, group_key: str) -> None:
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, page_count, status)"
        " VALUES (?, ?, 'pdf', 1, ?, 1.0, ?, 1, 'extracted')",
        (relative_path, Path(relative_path).name, "h" + relative_path, group_key),
    )
    file_id = conn.execute("SELECT id FROM file WHERE relative_path = ?", (relative_path,)).fetchone()[0]
    conn.execute(
        "INSERT INTO page (file_id, number, reference, char_count, image_count, has_table, text)"
        " VALUES (?, 1, 'f. 1', 1, 0, 0, 'x')",
        (file_id,),
    )
    conn.commit()


def test_linhas_antigas_saem_como_generated_e_nao_como_removidas(tmp_path):
    origem = tmp_path / "origem"
    gerada = origem / "outro-ai"
    gerada.mkdir(parents=True)
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "a.pdf").write_text("a", encoding="utf-8")
    (gerada / "project.db").write_bytes(b"")
    (gerada / "index.pdf").write_text("gerado", encoding="utf-8")
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    config = _config(origem, saida)
    grupo = origem.resolve().name  # `all_together`: o grupo é o nome da origem
    _registrar(conn, "a.pdf", grupo)
    _registrar(conn, "outro-ai/index.pdf", grupo)
    # a.pdf igual ao que está na pasta, para não contar como alterado.
    conn.execute(
        "UPDATE file SET size = ?, mtime = ? WHERE relative_path = 'a.pdf'",
        ((origem / "a.pdf").stat().st_size, (origem / "a.pdf").stat().st_mtime),
    )
    conn.commit()

    plano = build_update_plan(conn, config, record_warnings=False)
    assert [c.relative_path for c in plano.generated] == ["outro-ai/index.pdf"]
    assert plano.removed == ()

    resultado = apply_pending_changes(conn, config)

    assert resultado is not None and resultado.files_generated == 1
    caminhos = {r[0] for r in conn.execute("SELECT relative_path FROM file")}
    assert caminhos == {"a.pdf"}
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 1  # a página de a.pdf fica
    assert conn.execute("SELECT COUNT(*) FROM removed_file").fetchone()[0] == 0
    from gclaude_indexer.i18n import translate

    esperado = translate("pt", "log.update.generated_removed", count=1)
    eventos = [r[0] for r in conn.execute("SELECT message FROM event WHERE message = ?", (esperado,))]
    assert len(eventos) == 1
    conn.close()


def test_conjunto_gravado_dentro_de_uma_origem_e_recusado(tmp_path, monkeypatch):
    import pytest

    from gclaude_indexer.combined_package import ProtectedFolderError, write_folder
    from tests.test_phase38 import _conjunto_de_dois

    entry, a, b = _conjunto_de_dois(tmp_path, monkeypatch)
    origem = tmp_path / "origem-saida-a"
    assert origem.is_dir()
    with pytest.raises(ProtectedFolderError):
        write_folder(entry, origem / "novo", "pt")
    assert not (origem / "novo").exists()


def test_conjunto_grava_o_marcador(tmp_path, monkeypatch):
    from gclaude_indexer.combined_package import write_folder
    from tests.test_phase38 import _conjunto_de_dois

    entry, _a, _b = _conjunto_de_dois(tmp_path, monkeypatch)
    pasta = tmp_path / "combinada"
    write_folder(entry, pasta, "pt")
    assert (pasta / OUTPUT_MARKER_NAME).is_file()

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.8.1: the update notice that never showed up in time.

On a large Drive collection the check behind "the folder changed" took
minutes, one `stat` per file, while the Execution screen showed nothing —
the user added documents, opened the project and concluded the program did
not see them. The folder listing already carries size and time (seconds
for the same folder)."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from gclaude_indexer import db
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.scanning import SourceFile, scan, walk_source_stats
from gclaude_indexer.update_plan import detect_changes


def _config(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="all_together", extensions=["pdf"],
    )


def _registrar(conn, relative_path: str, conteudo: str, mtime: float) -> None:
    digest = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime,"
        " group_key, status) VALUES (?, ?, 'pdf', ?, ?, ?, 'g', 'extracted')",
        (relative_path, Path(relative_path).name, len(conteudo), digest, mtime),
    )
    conn.commit()


def _acervo(tmp_path: Path):
    origem = tmp_path / "origem"
    (origem / "sub").mkdir(parents=True)
    saida = tmp_path / "saida"
    saida.mkdir()
    (origem / "igual.pdf").write_text("igual", encoding="utf-8")
    (origem / "sub" / "novo.pdf").write_text("novo", encoding="utf-8")
    conn = db.connect(tmp_path / "project.db")
    db.init_schema(conn)
    _registrar(conn, "igual.pdf", "igual", (origem / "igual.pdf").stat().st_mtime)
    _registrar(conn, "sumiu.pdf", "sumiu", 1.0)
    return origem, saida, conn


def _vigiar_stat_de_arquivo(monkeypatch, origem: Path) -> list[str]:
    """Records every `Path.stat` of a *file* of the collection (folders are
    still asked, by `is_dir`, and that is fine)."""
    chamados: list[str] = []
    stat_real = Path.stat

    def stat(self, *args, **kwargs):
        resultado = stat_real(self, *args, **kwargs)
        if self.suffix == ".pdf" and origem in self.parents:
            chamados.append(self.name)
        return resultado

    monkeypatch.setattr(Path, "stat", stat)
    return chamados


def test_a_listagem_traz_tamanho_e_data_de_cada_arquivo(tmp_path):
    origem, saida, _conn = _acervo(tmp_path)

    encontrados = walk_source_stats(origem, saida)

    assert [item.path.relative_to(origem).as_posix() for item in encontrados] == [
        "igual.pdf", "sub/novo.pdf",
    ]
    for item in encontrados:
        assert isinstance(item, SourceFile)
        info = item.path.stat()
        assert (item.size, item.mtime) == (info.st_size, info.st_mtime)


def test_a_deteccao_nao_pede_o_stat_de_cada_arquivo(tmp_path, monkeypatch):
    origem, saida, conn = _acervo(tmp_path)
    chamados = _vigiar_stat_de_arquivo(monkeypatch, origem)

    mudancas, inalterados, _ = detect_changes(conn, _config(origem, saida))

    assert {m.kind: m.relative_path for m in mudancas} == {
        "new": "sub/novo.pdf", "removed": "sumiu.pdf",
    }
    assert inalterados == 1
    assert chamados == []


def test_a_impressao_digital_e_a_mesma_de_antes(tmp_path):
    """A tela de confirmação e o POST comparam a impressão digital da
    pasta: ela tem de continuar feita de caminho, tamanho e data."""
    from gclaude_indexer.update_plan import _fingerprint

    origem, saida, conn = _acervo(tmp_path)
    esperado = _fingerprint([
        (p.relative_to(origem).as_posix(), p.stat().st_size, p.stat().st_mtime)
        for p in (origem / "igual.pdf", origem / "sub" / "novo.pdf")
    ])

    _, _, impressao = detect_changes(conn, _config(origem, saida))

    assert impressao == esperado


def test_a_varredura_usa_os_valores_da_listagem(tmp_path, monkeypatch):
    origem, saida, _ = _acervo(tmp_path)
    conn = db.connect(tmp_path / "novo.db")
    db.init_schema(conn)
    config = _config(origem, saida)
    listados = walk_source_stats(origem, saida)
    chamados = _vigiar_stat_de_arquivo(monkeypatch, origem)

    resultado = scan(conn, config, files=listados)

    assert resultado.discovered == 2
    assert chamados == []
    gravados = dict(conn.execute("SELECT relative_path, mtime FROM file").fetchall())
    assert gravados == {
        item.path.relative_to(origem).as_posix(): item.mtime for item in listados
    }


def test_a_varredura_ainda_aceita_caminhos_soltos(tmp_path):
    origem, saida, _ = _acervo(tmp_path)
    conn = db.connect(tmp_path / "novo.db")
    db.init_schema(conn)

    resultado = scan(conn, _config(origem, saida), files=[origem / "igual.pdf"])

    assert resultado.discovered == 1


# --- a new folder and a whole folder removed (the user's two cases) -------


def _config_por_pasta(origem: Path, saida: Path) -> ProjectConfig:
    return ProjectConfig(
        name="acervo", source_folder=str(origem), output_folder=str(saida),
        group_mode="subfolder", extensions=["pdf"], classification_engine="rules",
        pages_per_window=4, overlap=1,
    )


def _pipeline(conn, config) -> None:
    from gclaude_indexer.artifacts import generate_all_artifacts
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.import_items import import_and_consolidate
    from gclaude_indexer.orchestrator import run_classification
    from gclaude_indexer.windows_prep import prepare_windows

    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    run_classification(conn, config)
    import_and_consolidate(conn, config)
    generate_all_artifacts(conn, config, "pt")


def test_pasta_nova_entra_e_pasta_retirada_sai_do_indice(tmp_path):
    from tests.test_phase17 import _pdf_de_paginas, _sem_carimbo

    from gclaude_indexer.invalidation import apply_update_plan
    from gclaude_indexer.update_plan import build_update_plan

    origem = tmp_path / "origem"
    for pasta in ("Atas", "Compras"):
        (origem / pasta).mkdir(parents=True)
    _pdf_de_paginas(origem / "Atas" / "ata-1.pdf", "ATA", 6)
    _pdf_de_paginas(origem / "Compras" / "pedido.pdf", "PEDIDO", 5)

    saida = tmp_path / "saida"
    saida.mkdir()
    config = _config_por_pasta(origem, saida)
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    _pipeline(conn, config)
    assert (saida / "index-Compras.md").exists()

    # Uma pasta inteira nova; outra retirada inteira.
    (origem / "Doações").mkdir()
    _pdf_de_paginas(origem / "Doações" / "oficio.pdf", "OFICIO", 3)
    (origem / "Compras" / "pedido.pdf").unlink()
    (origem / "Compras").rmdir()

    plano = build_update_plan(conn, config)
    assert [c.relative_path for c in plano.new] == ["Doações/oficio.pdf"]
    assert [c.relative_path for c in plano.removed] == ["Compras/pedido.pdf"]

    apply_update_plan(conn, config, plano)
    _pipeline(conn, config)
    # O log diz o que tirar do Projeto do Claude.
    apagados = conn.execute(
        "SELECT message_params FROM event WHERE message_key = 'log.artifacts.removed'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "index-Compras.md" in apagados
    conn.close()

    indice = (saida / "index.md").read_text(encoding="utf-8")
    assert "Doações" in indice
    assert "Compras" not in indice
    assert "oficio.pdf" in (saida / "index-Doações.md").read_text(encoding="utf-8")
    assert not (saida / "index-Compras.md").exists()

    # O mesmo acervo indexado do zero dá o mesmo índice.
    do_zero = tmp_path / "do_zero"
    do_zero.mkdir()
    conn_zero = db.connect(do_zero / "project.db")
    db.init_schema(conn_zero)
    _pipeline(conn_zero, _config_por_pasta(origem, do_zero))
    conn_zero.close()
    for nome in ("index.md", "index-Atas.md", "index-Doações.md", "timeline.md"):
        assert _sem_carimbo((saida / nome).read_text(encoding="utf-8")) == _sem_carimbo(
            (do_zero / nome).read_text(encoding="utf-8")
        ), nome


# --- the user's instructions: asked for, kept, and not duplicated ----------

from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK, replace_user_part, user_part  # noqa: E402

INSTRUCOES_DO_USUARIO = "# Minhas instruções\n\n## 1. Papel\n\nVocê assessora a Diretoria."


def _acervo_de_uma_ata(tmp_path: Path):
    from tests.test_phase17 import _pdf_de_paginas

    origem = tmp_path / "origem"
    (origem / "Atas").mkdir(parents=True)
    _pdf_de_paginas(origem / "Atas" / "ata.pdf", "ATA", 3)
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    return origem, saida, conn


def test_bloco_gerado_vira_secao_das_instrucoes_do_usuario(tmp_path):
    origem, saida, conn = _acervo_de_uma_ata(tmp_path)
    (saida / "project_instructions.md").write_text(INSTRUCOES_DO_USUARIO, encoding="utf-8")

    _pipeline(conn, _config_por_pasta(origem, saida))

    texto = (saida / "project_instructions.md").read_text(encoding="utf-8")
    assert texto.startswith(INSTRUCOES_DO_USUARIO)
    bloco = texto[texto.index(BEGIN_MARK):]
    # Um documento só: nenhum segundo título nem um "Papel" genérico que
    # contradiga o do usuário.
    assert "\n# " not in bloco
    assert "## Papel" not in bloco
    assert "## Acervo indexado pelo GClaude Indexer: acervo" in bloco
    assert "### Como localizar uma peça" in bloco


def test_sem_instrucoes_do_usuario_o_arquivo_continua_completo(tmp_path):
    origem, saida, conn = _acervo_de_uma_ata(tmp_path)

    _pipeline(conn, _config_por_pasta(origem, saida))

    texto = (saida / "project_instructions.md").read_text(encoding="utf-8")
    assert "# Instruções do projeto: acervo" in texto
    assert "## Papel" in texto


def _arquivo_com_bloco(pasta: Path) -> Path:
    caminho = pasta / "project_instructions.md"
    caminho.write_text(
        f"Antigas\n\n{BEGIN_MARK}\n## Acervo\n\n153251 peças\n{END_MARK}\n", encoding="utf-8"
    )
    return caminho


def test_instrucoes_coladas_substituem_so_a_parte_do_usuario(tmp_path):
    caminho = _arquivo_com_bloco(tmp_path)

    assert replace_user_part(caminho, INSTRUCOES_DO_USUARIO, stamp="20261103-150000")

    texto = caminho.read_text(encoding="utf-8")
    assert texto.startswith(INSTRUCOES_DO_USUARIO)
    assert "Antigas" not in texto
    assert f"{BEGIN_MARK}\n## Acervo\n\n153251 peças\n{END_MARK}" in texto
    copia = tmp_path / "project_instructions.md.20261103-150000.bak"
    assert copia.read_text(encoding="utf-8").startswith("Antigas")
    assert user_part(caminho) == INSTRUCOES_DO_USUARIO


def test_colar_o_arquivo_inteiro_nao_duplica_o_bloco(tmp_path):
    """No Projeto do Claude a pessoa pode ter colado o arquivo inteiro,
    com o bloco gerado: só o que está fora dele é dela."""
    caminho = _arquivo_com_bloco(tmp_path)
    colado = f"{INSTRUCOES_DO_USUARIO}\n\n{BEGIN_MARK}\n## Acervo velho\n{END_MARK}\n"

    replace_user_part(caminho, colado, stamp="x")

    texto = caminho.read_text(encoding="utf-8")
    assert texto.count(BEGIN_MARK) == 1
    assert "Acervo velho" not in texto
    assert "153251 peças" in texto


def test_texto_vazio_ou_igual_nao_mexe_no_arquivo(tmp_path):
    caminho = _arquivo_com_bloco(tmp_path)
    antes = caminho.read_bytes()

    assert not replace_user_part(caminho, "   \r\n", stamp="a")
    assert not replace_user_part(caminho, "Antigas\r\n", stamp="b")

    assert caminho.read_bytes() == antes
    assert list(tmp_path.glob("*.bak")) == []


def test_tela_de_atualizacao_pede_e_aplica_as_instrucoes(tmp_path, monkeypatch):
    from tests.test_phase17 import _app_com_projeto

    cliente, projeto_id, conn = _app_com_projeto(tmp_path, monkeypatch)
    conn.execute("UPDATE file SET status = 'extracted'")
    conn.commit()
    saida = tmp_path / "saida"
    _arquivo_com_bloco(saida)
    (tmp_path / "origem" / "novo.pdf").write_text("novo", encoding="utf-8")

    tela = cliente.get(f"/projects/{projeto_id}/update")
    assert tela.status_code == 200
    assert 'name="current_instructions"' in tela.text
    assert "Antigas" in tela.text  # já vem preenchido com o que existe
    impressao = re.search(r'name="fingerprint" value="([0-9a-f]+)"', tela.text).group(1)

    resposta = cliente.post(
        f"/projects/{projeto_id}/update",
        data={"fingerprint": impressao, "current_instructions": INSTRUCOES_DO_USUARIO},
        follow_redirects=False,
    )

    assert resposta.status_code == 303
    assert user_part(saida / "project_instructions.md") == INSTRUCOES_DO_USUARIO
    assert list(saida.glob("project_instructions.md.*.bak"))


def test_a_tela_de_execucao_avisa_que_esta_conferindo_a_pasta(tmp_path, monkeypatch):
    from tests.test_phase17 import _app_com_projeto

    cliente, projeto_id, _ = _app_com_projeto(tmp_path, monkeypatch)

    tela = cliente.get(f"/projects/{projeto_id}/run")

    assert "Conferindo a pasta de origem" in tela.text


# --- output files: only what changed is rewritten ------------------------

_DATA_ANTIGA = 1_000_000_000_000_000_000


def test_gerar_de_novo_sem_mudanca_nao_regrava_nenhum_arquivo(tmp_path):
    from gclaude_indexer.artifacts import generate_all_artifacts

    origem, saida, conn = _acervo_de_uma_ata(tmp_path)
    config = _config_por_pasta(origem, saida)
    _pipeline(conn, config)
    gerados = list(saida.glob("*.md"))
    assert gerados
    for caminho in gerados:
        os.utime(caminho, ns=(_DATA_ANTIGA, _DATA_ANTIGA))

    generate_all_artifacts(conn, config, "pt")

    assert [p.name for p in gerados if p.stat().st_mtime_ns != _DATA_ANTIGA] == []
    ultimo = conn.execute("SELECT message_key FROM event ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert ultimo == "log.artifacts.unchanged"


def test_so_o_grupo_que_mudou_e_regravado(tmp_path):
    from tests.test_phase17 import _pdf_de_paginas

    from gclaude_indexer.invalidation import apply_update_plan
    from gclaude_indexer.update_plan import build_update_plan

    origem = tmp_path / "origem"
    for pasta in ("Atas", "Compras"):
        (origem / pasta).mkdir(parents=True)
    _pdf_de_paginas(origem / "Atas" / "ata.pdf", "ATA", 3)
    _pdf_de_paginas(origem / "Compras" / "pedido.pdf", "PEDIDO", 3)
    saida = tmp_path / "saida"
    saida.mkdir()
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    config = _config_por_pasta(origem, saida)
    _pipeline(conn, config)
    atas_antes = (saida / "index-Atas.md").read_bytes()
    os.utime(saida / "index-Atas.md", ns=(_DATA_ANTIGA, _DATA_ANTIGA))

    _pdf_de_paginas(origem / "Compras" / "pedido-2.pdf", "PEDIDO DOIS", 2)
    apply_update_plan(conn, config, build_update_plan(conn, config))
    _pipeline(conn, config)

    assert (saida / "index-Atas.md").read_bytes() == atas_antes
    assert (saida / "index-Atas.md").stat().st_mtime_ns == _DATA_ANTIGA
    assert "pedido-2.pdf" in (saida / "index-Compras.md").read_text(encoding="utf-8")
    mudou = conn.execute(
        "SELECT message_params FROM event WHERE message_key = 'log.artifacts.changed'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "index-Compras.md" in mudou
    assert "index-Atas.md" not in mudou


def test_as_chaves_novas_existem_nos_tres_idiomas():
    from gclaude_indexer.i18n import _TRANSLATIONS

    chaves = [
        "update.checking", "update.instructions_title", "update.instructions_label",
        "update.instructions_help", "log.update.instructions_replaced",
        "log.artifacts.changed", "log.artifacts.unchanged",
        "artifact.project_instructions.collection_title",
        "artifact.project_instructions.collection_intro",
    ]
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            assert chave in _TRANSLATIONS[idioma], (idioma, chave)

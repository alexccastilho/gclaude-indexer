# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""O pacote combinado grava instruções e `CLAUDE.md` como o projeto simples:
mesma seção de segurança, mesmo `write_managed` (cópia `.bak`, arquivo
igual não é reescrito). E a remoção de `normas-citadas.md` entra no
relatório do que sumiu."""

from __future__ import annotations

import pytest

from gclaude_indexer.artifacts import CLAUDE_MD_SECURITY, generate_all_artifacts
from gclaude_indexer.managed_block import BACKUP_SUFFIX, BEGIN_MARK, write_managed
from tests.test_phase38 import _banco, _config, _conjunto_de_dois, _peca


@pytest.mark.parametrize("idioma", ["pt", "en", "es"])
def test_claude_md_combinado_tem_a_secao_de_seguranca(tmp_path, monkeypatch, idioma):
    from gclaude_indexer.combined_package import write_folder

    entry, _a, _b = _conjunto_de_dois(tmp_path, monkeypatch)
    pasta = tmp_path / "combinada"
    write_folder(entry, pasta, idioma)

    claude_md = (pasta / "CLAUDE.md").read_text(encoding="utf-8")
    bloco = claude_md[claude_md.index(BEGIN_MARK):]
    assert CLAUDE_MD_SECURITY[idioma] in bloco
    assert "UNTRUSTED" in bloco


def test_write_managed_diz_se_escreveu(tmp_path):
    arquivo = tmp_path / "x.md"
    assert write_managed(arquivo, "gerado") is True
    assert write_managed(arquivo, "gerado") is False
    assert write_managed(arquivo, "outro") is True


def test_pasta_combinada_guarda_bak_e_nao_reescreve_o_que_nao_mudou(tmp_path, monkeypatch):
    from gclaude_indexer import combined_package

    entry, _a, _b = _conjunto_de_dois(tmp_path, monkeypatch)
    pasta = tmp_path / "combinada"
    pasta.mkdir()
    meu_claude = "# Regras minhas\n\nNunca apague nada.\n"
    minhas_instrucoes = "Instruções minhas, sem marcas.\n"
    (pasta / "CLAUDE.md").write_text(meu_claude, encoding="utf-8")
    (pasta / "project_instructions.md").write_text(minhas_instrucoes, encoding="utf-8")

    escritas: dict[str, bool] = {}
    original = combined_package.write_managed

    def espiao(path, *args, **kwargs):
        escritas[path.name] = original(path, *args, **kwargs)
        return escritas[path.name]

    monkeypatch.setattr(combined_package, "write_managed", espiao)

    combined_package.write_folder(entry, pasta, "pt")
    # A primeira vez que um arquivo sem marcas é tocado fica a cópia.
    assert (pasta / f"CLAUDE.md{BACKUP_SUFFIX}").read_text(encoding="utf-8") == meu_claude
    assert (pasta / f"project_instructions.md{BACKUP_SUFFIX}").read_text(encoding="utf-8") == minhas_instrucoes
    assert escritas == {"CLAUDE.md": True, "project_instructions.md": True}
    assert (pasta / "CLAUDE.md").read_text(encoding="utf-8").startswith("# Regras minhas")

    escritas.clear()
    escritos = combined_package.write_folder(entry, pasta, "pt")
    assert escritas == {"CLAUDE.md": False, "project_instructions.md": False}
    # Mesmo sem reescrever, os dois continuam na lista do que a pasta tem.
    assert {"CLAUDE.md", "project_instructions.md"} <= {p.name for p in escritos}


def test_normas_citadas_apagada_entra_no_relatorio_do_que_saiu(tmp_path):
    conn = _banco(tmp_path)
    _peca(conn, "Processo", 1, 4, "LAUDO", "vol1.pdf")
    _peca(conn, "Processo", 5, 5, "LEI", "lei.htm", engine="structured", data="1990-07-11",
          resumo="LEI Nº 8.078: Código de Defesa do Consumidor")
    config = _config(tmp_path)
    generate_all_artifacts(conn, config, "pt")
    assert (tmp_path / "normas-citadas.md").exists()

    conn.execute("DELETE FROM item WHERE engine = 'structured'")
    conn.commit()
    generate_all_artifacts(conn, config, "pt")

    assert not (tmp_path / "normas-citadas.md").exists()
    apagados = conn.execute(
        "SELECT message_params FROM event WHERE message_key = 'log.artifacts.removed'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert apagados is not None and "normas-citadas.md" in apagados[0]

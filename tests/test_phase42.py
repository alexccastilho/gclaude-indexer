# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.9.2: the user's part of the instructions repeating the managed block.

A real project had copied the block's sections into its own part by hand
(the non-negotiable rule, how to locate an item, the columns, a count of
Planalto pages), and every generation appended the block below: all of it
twice, with the copy's numbers frozen. The fixtures here are built from the
block the program writes, never from that project's text.
"""

from __future__ import annotations

import re
import unicodedata

from gclaude_indexer.artifacts import generate_project_instructions_md
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.instructions_dedup import apply, detect
from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK, generated_part, user_part
from tests.test_instrucoes_complementares import _config, _conn

PROPRIAS_ANTES = """# Instruções do meu projeto

## 1. Papel

Você é a assessoria da diretoria. Siga sempre a regra da seção 3 ao citar o acervo.

## 2. Tom

Escreva de forma direta, sem jargão.
"""

PROPRIAS_DEPOIS = """## 7. Hierarquia das fontes

Constituição, leis, decretos e normas internas, nessa ordem.

## 8. Arquivos do projeto

| Arquivo | Para que serve | Abrir quando |
|---|---|---|
| Papel timbrado.pdf | Base de todo documento | Sempre |
| index.md | Índice geral do acervo | Localizar uma peça |
| Arquivos originais do acervo | Fonte única de valores | Antes de citar |

## 9. Checklist

1. A competência está correta.
2. Todo valor vindo do acervo foi conferido no arquivo original.
3. Ortografia revisada.
"""


def _bloco(tmp_path):
    """The block as the program writes it for a project with no user part."""
    (tmp_path / "ref").mkdir(exist_ok=True)
    config, saida = _config(tmp_path / "ref")
    conn = _conn(saida)
    caminho = generate_project_instructions_md(conn, config, "pt")
    conn.close()
    return generated_part(caminho)


def _secoes_copiadas(bloco: str, primeira: int = 3) -> str:
    """The block's `### X` sections pasted by hand as `## N. X`, the way
    people did it."""
    partes = re.split(r"^#{2,3} ", bloco, flags=re.MULTILINE)[1:]
    texto = []
    numero = primeira
    for parte in partes:
        titulo, _, corpo = parte.partition("\n")
        if titulo.startswith(("Regras extras", "Papel", "Extra project", "Role")):
            continue
        texto.append(f"## {numero}. {titulo}\n{corpo.strip()}\n")
        numero += 1
    return "\n".join(texto)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _projeto_com(tmp_path, parte_manual: str):
    config, saida = _config(tmp_path)
    (saida / "project_instructions.md").write_text(parte_manual, encoding="utf-8")
    return config, saida, _conn(saida)


# --- 1. no copy: appended normally, and twice is the same as once -------------

def test_sem_copia_anexa_normalmente_e_e_idempotente(tmp_path):
    config, saida, conn = _projeto_com(tmp_path, PROPRIAS_ANTES + "\n" + PROPRIAS_DEPOIS)
    caminho = generate_project_instructions_md(conn, config, "pt")
    primeira = caminho.read_bytes()
    generate_project_instructions_md(conn, config, "pt")
    assert caminho.read_bytes() == primeira
    texto = primeira.decode("utf-8")
    assert texto.count(BEGIN_MARK) == 1 and texto.count(END_MARK) == 1
    assert "Atenção: a parte manual" not in texto
    assert user_part(caminho).startswith("# Instruções do meu projeto")
    assert "Escreva de forma direta" in user_part(caminho)
    conn.close()


# --- 2. identical copy: detected, notice, offered removal ---------------------

def test_copia_identica_e_detectada_e_avisada_sem_mexer_na_parte_manual(tmp_path):
    copia = _secoes_copiadas(_bloco(tmp_path))
    manual = PROPRIAS_ANTES + "\n" + copia + "\n" + PROPRIAS_DEPOIS
    config, saida, conn = _projeto_com(tmp_path, manual)
    caminho = generate_project_instructions_md(conn, config, "pt")

    assert user_part(caminho).strip() == manual.strip()       # untouched
    bloco = generated_part(caminho)
    assert bloco.splitlines()[2].startswith("> Atenção: a parte manual deste arquivo")
    assert "Regra inegociável" in bloco.splitlines()[2]
    eventos = [e for e in list_events(conn, step="instructions") if e["level"] == "warning"]
    assert eventos and "repetem" in eventos[-1]["message"]

    # Idempotent with the notice too.
    antes = caminho.read_bytes()
    generate_project_instructions_md(conn, config, "pt")
    assert caminho.read_bytes() == antes
    conn.close()


def test_remocao_deixa_so_o_bloco_e_aponta_as_referencias(tmp_path):
    copia = _secoes_copiadas(_bloco(tmp_path))
    manual = PROPRIAS_ANTES + "\n" + copia + "\n" + PROPRIAS_DEPOIS
    relatorio = detect(manual, "Tema do acervo")
    titulos = relatorio.copy_titles()
    assert titulos == ["3. Sobre este acervo", "4. Regra inegociável", "5. Como localizar uma peça",
                       "6. Colunas dos arquivos"]
    assert relatorio.references == [(4, "seção 3")]

    novo, regras = apply(relatorio, "pt", remove_copies=True, move=set())
    assert regras == []
    assert "Regra inegociável" not in novo and "Como localizar" not in novo
    assert 'seção "Acervo indexado pelo GClaude Indexer", no fim deste arquivo' in novo
    assert "## 2. Tom" in novo and "## 7. Hierarquia das fontes" in novo   # numbers kept
    assert "| Papel timbrado.pdf |" in novo


def test_numeros_que_mudam_sao_apontados(tmp_path):
    manual = PROPRIAS_ANTES + (
        "\n## 3. Legislação\n\nLegislação federal: as 143972 página(s) do Planalto deste acervo "
        "(leis, decretos, medidas provisórias, retificações, mensagens e afins) **não estão no "
        "conhecimento deste Projeto**.\n"
    )
    relatorio = detect(manual)
    assert [linha for _i, linha in relatorio.volatile_lines] == [
        manual.splitlines()[-1]
    ]


# --- 3. lightly altered copy: still detected ----------------------------------

def test_copia_levemente_alterada_e_detectada(tmp_path):
    copia = _secoes_copiadas(_bloco(tmp_path), primeira=10)
    alterada = _sem_acento(copia).replace(": ", " - ").replace("—", ":").upper()
    alterada = re.sub(r"^## (\d+)\. ", r"## \1) ", alterada, flags=re.MULTILINE)
    alterada = alterada.replace("PECA(S) CLASSIFICADA(S)", "PECA(S)  CLASSIFICADA(S)")
    relatorio = detect(PROPRIAS_ANTES + "\n" + alterada)
    assert len(relatorio.copies) == 4


def test_copia_em_ingles_com_a_tela_em_portugues(tmp_path):
    (tmp_path / "en").mkdir(exist_ok=True)
    config, saida = _config(tmp_path / "en")
    conn = _conn(saida)
    bloco_en = generated_part(generate_project_instructions_md(conn, config, "en"))
    conn.close()
    relatorio = detect(PROPRIAS_ANTES + "\n" + _secoes_copiadas(bloco_en))
    assert len(relatorio.copies) == 4


def test_regras_do_usuario_podem_ir_para_as_regras_extras(tmp_path):
    copia = _secoes_copiadas(_bloco(tmp_path))
    manual = PROPRIAS_ANTES + "\n" + copia + "\n" + PROPRIAS_DEPOIS
    relatorio = detect(manual)
    textos = {c.text: c for c in relatorio.candidates}
    assert "**index.md**: Para que serve: Índice geral do acervo; Abrir quando: Localizar uma peça" in textos
    assert any("conferido no arquivo original" in t for t in textos)
    assert not any("Papel timbrado" in t for t in textos)
    escolhidos = {c.id for c in relatorio.candidates if c.suggested}
    novo, regras = apply(relatorio, "pt", remove_copies=True, move=escolhidos)
    assert "| index.md |" not in novo
    # The checklist is renumbered after the item left it.
    assert "1. A competência está correta.\n2. Ortografia revisada." in novo
    assert len(regras) == len(escolhidos)


# --- the legacy check no longer eats the user's text ---------------------------

def test_arquivo_sem_marcas_com_a_regra_copiada_a_mao_nao_e_descartado(tmp_path):
    copia = _secoes_copiadas(_bloco(tmp_path))
    manual = PROPRIAS_ANTES + "\n" + copia            # no marks at all
    config, saida, conn = _projeto_com(tmp_path, manual)
    caminho = generate_project_instructions_md(conn, config, "pt")
    texto = caminho.read_text(encoding="utf-8")
    assert "Escreva de forma direta" in texto
    assert texto.index("Escreva de forma direta") < texto.index(BEGIN_MARK)
    conn.close()


# --- the screen ---------------------------------------------------------------

def _web(tmp_path, monkeypatch):
    import gclaude_indexer.catalog as catalogo_mod
    import gclaude_indexer.hardware as hardware_mod
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app
    from tests.test_phase9 import _criar_projeto

    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    cliente = TestClient(app)
    cliente.cookies.set("language", "pt")
    pid = _criar_projeto(cliente, tmp_path)
    from gclaude_indexer.catalog import find_project

    return cliente, pid, find_project(pid).output_folder


def _escrever_com_copia(tmp_path, pasta, assunto):
    from gclaude_indexer.project import load_project

    config, conn = load_project(pasta)
    copia = _secoes_copiadas(_bloco(tmp_path))
    manual = PROPRIAS_ANTES + "\n" + copia + "\n" + PROPRIAS_DEPOIS
    caminho = generate_project_instructions_md(conn, config, "pt")
    caminho.write_text(manual + "\n" + caminho.read_text(encoding="utf-8"), encoding="utf-8")
    conn.close()
    return caminho


def test_tela_oferece_e_remove(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    caminho = _escrever_com_copia(tmp_path, pasta, "")
    assert "repetem trechos do bloco automático" in cliente.get(f"/projects/{pid}/run").text
    tela = cliente.get(f"/projects/{pid}/instructions").text
    assert "A sua parte repete o bloco automático" in tela
    impressao = re.search(r'name="fingerprint" value="([0-9a-f]+)"', tela).group(1)

    resposta = cliente.post(
        f"/projects/{pid}/instructions/dedup",
        data={"action": "remove", "fingerprint": impressao, "move": []},
    )
    assert resposta.status_code == 200
    assert "Pronto: 4 seção(ões) repetida(s) removida(s)" in resposta.text
    texto = caminho.read_text(encoding="utf-8")
    assert texto.count("Regra inegociável") == 1
    assert "Atenção: a parte manual" not in texto
    assert list(caminho.parent.glob("project_instructions.md.*.bak"))
    assert "repetem trechos do bloco automático" not in cliente.get(f"/projects/{pid}/run").text


def test_tela_manter_registra_e_some_o_aviso_da_tela(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    caminho = _escrever_com_copia(tmp_path, pasta, "")
    antes = caminho.read_bytes()
    tela = cliente.get(f"/projects/{pid}/instructions").text
    impressao = re.search(r'name="fingerprint" value="([0-9a-f]+)"', tela).group(1)
    resposta = cliente.post(
        f"/projects/{pid}/instructions/dedup", data={"action": "keep", "fingerprint": impressao},
    )
    assert "Mantido como está" in resposta.text
    assert caminho.read_bytes() == antes
    assert "repetem trechos do bloco automático" not in cliente.get(f"/projects/{pid}/run").text


def test_tela_recusa_analise_velha(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    caminho = _escrever_com_copia(tmp_path, pasta, "")
    antes = caminho.read_bytes()
    resposta = cliente.post(
        f"/projects/{pid}/instructions/dedup", data={"action": "remove", "fingerprint": "0000"},
    )
    assert "O arquivo mudou desde que esta tela foi aberta" in resposta.text
    assert caminho.read_bytes() == antes


def test_chaves_novas_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave in ("instructions.dedup.title", "instructions.dedup.remove", "instructions.dedup.keep",
                      "log.instructions.duplicates", "artifact.project_instructions.duplicate_notice"):
            texto = translate(idioma, chave, sections="x", count=1, numbers=1, title="t")
            assert texto and texto != chave and "—" not in texto

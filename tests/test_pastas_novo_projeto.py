"""2.0.0, tarefa 1: caminhos e criação de projeto.

A saída nunca é igual, está dentro ou contém a origem; a sugestão é
`<origem>-AI`; a regra vale na criação (não ao abrir projetos antigos)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
import gclaude_indexer.paths as paths_mod
from gclaude_indexer.config import load_config
from gclaude_indexer.paths import (
    check_new_project_folders, suggest_output_folder,
)
from gclaude_indexer.project import create_project, load_project
from gclaude_indexer.web.app import app
from gclaude_indexer.web import routes_projects

HEADERS = {"Origin": "http://testserver", "HX-Request": "true"}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


def _chaves(erros):
    return [erro.key for erro in erros]


def _dados(origem, saida):
    return {
        "name": "Projeto", "subject": "", "source_folder": str(origem), "output_folder": saida,
        "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
        "extensions": ["pdf"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "automatic",
        "role_instructions": "", "extra_rules": "",
    }


@pytest.fixture
def origem(tmp_path):
    pasta = tmp_path / "Acervo"
    pasta.mkdir()
    return pasta


# --- regras de pasta ----------------------------------------------------------


def test_saida_igual_a_origem(origem):
    assert _chaves(check_new_project_folders(str(origem), str(origem))) == ["config_error.output_same_as_source"]


def test_saida_dentro_da_origem(origem):
    erros = check_new_project_folders(str(origem), str(origem / "sub" / "saida"))
    assert _chaves(erros) == ["config_error.output_inside_source"]


def test_saida_que_contem_a_origem(tmp_path, origem):
    assert _chaves(check_new_project_folders(str(origem), str(tmp_path))) == ["config_error.source_inside_output"]


def test_diferenca_so_de_maiusculas(tmp_path, origem):
    erros = check_new_project_folders(str(origem), str(tmp_path / "ACERVO"))
    assert _chaves(erros) == ["config_error.output_same_as_source"]
    erros = check_new_project_folders(str(origem), str(tmp_path / "ACERVO" / "x"))
    assert _chaves(erros) == ["config_error.output_inside_source"]


def test_ponto_e_espaco_finais_sao_cortados(tmp_path, origem):
    erros = check_new_project_folders(str(origem), str(origem) + ". ")
    assert _chaves(erros) == ["config_error.output_same_as_source"]


def test_irma_da_origem_e_aceita(tmp_path, origem):
    assert check_new_project_folders(str(origem), str(tmp_path / "Acervo-AI")) == []


def test_prefixo_de_nome_nao_e_contencao(tmp_path, origem):
    # `Acervo2` começa com `Acervo` mas não está dentro dele.
    assert check_new_project_folders(str(origem), str(tmp_path / "Acervo2")) == []


def test_junction_para_dentro_da_origem(tmp_path, origem):
    if os.name != "nt":
        pytest.skip("junction é coisa do Windows")
    atalho = tmp_path / "atalho"
    resultado = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(atalho), str(origem)], capture_output=True,
    )
    if resultado.returncode != 0:
        pytest.skip("o sistema não permitiu criar a junction")
    erros = check_new_project_folders(str(origem), str(atalho / "saida"))
    assert _chaves(erros) == ["config_error.output_inside_source"]


@pytest.mark.skipif(os.name != "nt", reason="raiz de unidade e UNC são do Windows")
def test_raiz_de_unidade_e_unc():
    unidade = Path(sys.executable).anchor
    assert suggest_output_folder(unidade) is None
    assert _chaves(check_new_project_folders(unidade, unidade + "x")) == ["config_error.source_is_drive_root"]
    assert suggest_output_folder("\\\\servidor\\compartilhamento") is None
    erros = check_new_project_folders("\\\\servidor\\compartilhamento", "\\\\servidor\\compartilhamento\\x")
    assert _chaves(erros) == ["config_error.source_is_drive_root"]


@pytest.mark.skipif(os.name != "nt", reason="`H:XYZ` é sintaxe do Windows")
def test_unidade_sem_barra_e_relativa(origem):
    assert _chaves(check_new_project_folders(str(origem), "H:XYZ")) == ["config_error.output_not_absolute"]
    assert _chaves(check_new_project_folders("H:XYZ", str(origem) + "-AI")) == ["config_error.output_not_absolute"]
    assert suggest_output_folder("H:XYZ") is None


def test_caminho_relativo_e_recusado(origem):
    assert _chaves(check_new_project_folders(str(origem), "saida")) == ["config_error.output_not_absolute"]


def test_sugestao_e_irma_com_sufixo(tmp_path, origem):
    assert suggest_output_folder(str(origem)) == str(tmp_path / "Acervo-AI")


def test_destino_ocupado_vai_para_o_proximo_sufixo(tmp_path, origem):
    ocupada = tmp_path / "Acervo-AI"
    ocupada.mkdir()
    (ocupada / "algo.txt").write_text("x")
    assert suggest_output_folder(str(origem)) == str(tmp_path / "Acervo-AI-2")
    (tmp_path / "Acervo-AI-2").mkdir()
    (tmp_path / "Acervo-AI-2" / "y.txt").write_text("y")
    assert suggest_output_folder(str(origem)) == str(tmp_path / "Acervo-AI-3")

    erros = check_new_project_folders(str(origem), str(ocupada))
    assert _chaves(erros) == ["config_error.output_not_empty"]
    assert erros[0].params["suggestion"] == str(tmp_path / "Acervo-AI-3")


def test_destino_vazio_e_aceito(tmp_path, origem):
    (tmp_path / "Acervo-AI").mkdir()
    assert check_new_project_folders(str(origem), str(tmp_path / "Acervo-AI")) == []
    assert suggest_output_folder(str(origem)) == str(tmp_path / "Acervo-AI")


def test_destino_com_project_db_segue_o_fluxo_atual(tmp_path, origem):
    saida = tmp_path / "Acervo-AI"
    saida.mkdir()
    (saida / "project.db").write_bytes(b"")
    assert check_new_project_folders(str(origem), str(saida)) == []


# --- criação pela tela --------------------------------------------------------


def test_saida_vazia_no_post_usa_a_sugestao(cliente, tmp_path, origem):
    resposta = cliente.post("/projects/new", data=_dados(origem, ""), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 303
    assert (tmp_path / "Acervo-AI" / "project.db").exists()


def test_post_forjado_com_saida_dentro_da_origem_e_recusado(cliente, origem):
    saida = origem / "gerado"
    resposta = cliente.post("/projects/new", data=_dados(origem, str(saida)), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 400
    assert "dentro da pasta de origem" in resposta.text or "inside the source" in resposta.text
    assert not saida.exists()


def test_post_com_saida_igual_a_origem_nao_cria_nada(cliente, origem):
    resposta = cliente.post("/projects/new", data=_dados(origem, str(origem)), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 400
    assert not (origem / "project.db").exists()


def test_sem_permissao_vira_erro_traduzido(cliente, tmp_path, origem, monkeypatch):
    def negar(self, *args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(Path, "mkdir", negar)
    resposta = cliente.post("/projects/new", data=_dados(origem, str(tmp_path / "Nova")), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 400
    assert not (tmp_path / "Nova").exists()


def test_falha_do_banco_remove_a_pasta_criada(cliente, tmp_path, origem, monkeypatch):
    def quebrar(config):
        raise sqlite3.OperationalError("disco cheio")

    monkeypatch.setattr(routes_projects, "create_project", quebrar)
    saida = tmp_path / "Nova" / "Saida"
    resposta = cliente.post("/projects/new", data=_dados(origem, str(saida)), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 400
    assert not saida.exists()


def test_prova_de_escrita_e_removida(tmp_path):
    saida = tmp_path / "Nova"
    assert paths_mod.ensure_writable_folder(str(saida)) is True
    assert list(saida.iterdir()) == []
    assert paths_mod.ensure_writable_folder(str(saida)) is False


# --- rota de sugestão e Procurar ---------------------------------------------


def test_rota_de_sugestao_nao_cria_nada(cliente, tmp_path, origem):
    antes = sorted(p.name for p in tmp_path.iterdir())
    resposta = cliente.post("/projects/suggest-output", data={"source_folder": str(origem)}, headers=HEADERS)
    assert resposta.status_code == 200
    assert str(tmp_path / "Acervo-AI") in resposta.text
    assert 'name="output_touched"' in resposta.text
    assert sorted(p.name for p in tmp_path.iterdir()) == antes


def test_rota_de_sugestao_respeita_saida_editada(cliente, origem):
    resposta = cliente.post(
        "/projects/suggest-output", data={"source_folder": str(origem), "output_touched": "1"}, headers=HEADERS,
    )
    assert resposta.status_code == 204


def test_rota_de_sugestao_sem_origem_valida_nao_troca_o_campo(cliente):
    resposta = cliente.post("/projects/suggest-output", data={"source_folder": "H:XYZ"}, headers=HEADERS)
    assert resposta.status_code == 204


def test_rota_de_sugestao_fica_sob_a_protecao_das_demais(cliente, origem):
    resposta = cliente.post(
        "/projects/suggest-output", data={"source_folder": str(origem)},
        headers={"Origin": "http://outro-site.example", "HX-Request": "true"},
    )
    assert resposta.status_code == 403


def test_procurar_a_origem_preenche_a_saida(cliente, tmp_path, origem, monkeypatch):
    monkeypatch.setattr(routes_projects, "choose_folder", lambda **_kw: str(origem))
    resposta = cliente.post("/select-folder", data={"field": "source_folder", "source_folder": ""}, headers=HEADERS)
    assert 'hx-swap-oob="innerHTML"' in resposta.text
    assert str(tmp_path / "Acervo-AI") in resposta.text


def test_procurar_a_origem_nao_sobrescreve_saida_editada(cliente, origem, monkeypatch):
    monkeypatch.setattr(routes_projects, "choose_folder", lambda **_kw: str(origem))
    resposta = cliente.post(
        "/select-folder", data={"field": "source_folder", "source_folder": "", "output_touched": "1"}, headers=HEADERS,
    )
    assert "hx-swap-oob" not in resposta.text


def test_tela_nao_traz_mais_o_js_de_indexado(cliente):
    resposta = cliente.get("/projects/new")
    assert "_indexado" not in resposta.text
    assert "adjustDefaultOutputFolder" not in resposta.text


# --- reancoragem --------------------------------------------------------------


def _criar_no_disco(origem, saida):
    config = load_config({
        "name": "P", "source_folder": str(origem), "output_folder": str(saida), "extensions": ["pdf"],
    })
    conn, _ = create_project(config)
    conn.close()


def test_load_project_reancora_a_pasta_renomeada(tmp_path, origem):
    antiga = tmp_path / "antiga"
    _criar_no_disco(origem, antiga)
    nova = tmp_path / "nova"
    antiga.rename(nova)

    config, conn = load_project(nova)
    assert Path(config.output_folder) == nova
    conn.close()

    config, conn = load_project(nova)
    assert Path(config.output_folder) == nova
    linha = conn.execute("SELECT output_folder, config_json FROM project").fetchone()
    assert Path(linha["output_folder"]) == nova and str(nova).replace("\\", "\\\\") in linha["config_json"]
    conn.close()


def test_load_project_nao_regrava_quando_igual(tmp_path, origem):
    saida = tmp_path / "saida"
    _criar_no_disco(origem, saida)
    config, conn = load_project(saida)
    antes = conn.total_changes
    conn.close()
    config, conn = load_project(saida)
    assert conn.total_changes == 0 and antes == 0
    conn.close()


def test_projeto_salvo_abre_com_a_origem_fora_do_ar(cliente, tmp_path, origem):
    """A origem sumiu (pendrive tirado, rede fora): a lista e a tela do
    projeto abrem; a falta aparece só onde a origem é usada. Antes, as duas
    davam 500 porque a carga revalidava a existência da pasta."""
    import shutil

    resposta = cliente.post("/projects/new", data=_dados(origem, ""), headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 303
    endereco = resposta.headers["location"]
    saida = tmp_path / "Acervo-AI"
    shutil.rmtree(origem)

    config, conn = load_project(saida)
    assert config.source_folder == str(origem)
    conn.close()

    assert cliente.get("/projects").status_code == 200
    tela = cliente.get(endereco)
    assert tela.status_code == 200


def test_telas_de_projeto_varrido_abrem_com_a_origem_fora_do_ar(cliente, tmp_path, origem):
    import shutil
    import time

    from gclaude_indexer.web.background_runs import task_manager

    (origem / "a.txt").write_text("conteúdo", encoding="utf-8")
    dados = _dados(origem, "")
    dados["extensions"] = ["all"]
    resposta = cliente.post("/projects/new", data=dados, headers=HEADERS, follow_redirects=False)
    projeto_id = int(resposta.headers["location"].split("/")[2])
    task_manager._tasks.clear()
    task_manager.start_step(projeto_id, str(tmp_path / "Acervo-AI"), "scan", language="pt")
    limite = time.monotonic() + 30
    while task_manager.get(projeto_id, "scan").running and time.monotonic() < limite:
        time.sleep(0.05)
    assert task_manager.get(projeto_id, "scan").finished_ok
    task_manager._tasks.clear()
    shutil.rmtree(origem)

    lista = cliente.get("/projects")
    assert lista.status_code == 200
    from gclaude_indexer.web.step_state import project_status

    assert project_status(str(tmp_path / "Acervo-AI"))[0] != "unavailable"
    for tela in (
        "/run", "/run/log", "/run/steps", "/run/progress", "/update/banner", "/result", "/search",
        "/instructions", "/delete", "/activity",
    ):
        assert cliente.get(f"/projects/{projeto_id}{tela}").status_code == 200, tela
    # A atualização é onde a origem é usada: explica, sem 500.
    atualizacao = cliente.get(f"/projects/{projeto_id}/update")
    assert atualizacao.status_code == 409 and "update.source_unavailable" not in atualizacao.text


def test_etapa_com_a_origem_fora_do_ar_avisa_sem_rodar(cliente, tmp_path, origem):
    import shutil
    import time

    from gclaude_indexer.web.background_runs import task_manager

    resposta = cliente.post("/projects/new", data=_dados(origem, ""), headers=HEADERS, follow_redirects=False)
    projeto_id = int(resposta.headers["location"].split("/")[2])
    shutil.rmtree(origem)

    task_manager._tasks.clear()
    task_manager.start_step(projeto_id, str(tmp_path / "Acervo-AI"), "scan", language="pt")
    limite = time.monotonic() + 20
    while task_manager.get(projeto_id, "scan").running and time.monotonic() < limite:
        time.sleep(0.05)
    tarefa = task_manager.get(projeto_id, "scan")
    assert not tarefa.running and not tarefa.finished_ok
    assert str(origem) in tarefa.error
    conn = sqlite3.connect(tmp_path / "Acervo-AI" / "project.db")
    assert conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0
    conn.close()
    task_manager._tasks.clear()


def test_projeto_antigo_com_saida_dentro_da_origem_continua_abrindo(tmp_path, origem):
    saida = origem / "_indexado"
    _criar_no_disco(origem, saida)
    config, conn = load_project(saida)
    assert Path(config.output_folder) == saida
    conn.close()

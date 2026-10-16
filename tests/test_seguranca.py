"""Correções da auditoria de segurança.

O servidor escuta só em 127.0.0.1, mas qualquer página aberta no navegador do
usuário consegue mandar pedidos para lá. Sem checar de onde vem o pedido, um
site malicioso podia excluir um projeto (com os arquivos), criar projetos em
qualquer pasta ou fazer o Windows se autenticar num servidor de rede dele.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gclaude_indexer.catalog import CatalogEntry
from gclaude_indexer.deletion import delete_project
from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK
from gclaude_indexer.web.app import _back_to, app


@pytest.fixture
def cliente():
    return TestClient(app)


# --- de onde vem o pedido ------------------------------------------------------


def test_post_de_outro_site_e_recusado(cliente):
    resposta = cliente.post(
        "/preferences/theme", data={"theme": "dark"},
        headers={"Origin": "https://site-malicioso.example"}, follow_redirects=False,
    )
    assert resposta.status_code == 403


def test_post_do_proprio_programa_passa(cliente):
    resposta = cliente.post(
        "/preferences/theme", data={"theme": "dark"},
        headers={"Origin": "http://testserver"}, follow_redirects=False,
    )
    assert resposta.status_code == 303


def test_pedido_marcado_pelo_navegador_como_de_outro_site_e_recusado(cliente):
    resposta = cliente.get(
        "/projects/open?folder=%5C%5Catacante%5Cpasta",
        headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"},
    )
    assert resposta.status_code == 403


def test_link_simples_vindo_de_outro_site_ainda_abre_a_tela(cliente):
    resposta = cliente.get(
        "/projects",
        headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
    )
    assert resposta.status_code == 200


def test_link_de_outro_site_com_parametros_e_recusado(cliente):
    resposta = cliente.get(
        "/projects/open?folder=%5C%5Catacante%5Cpasta",
        headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
    )
    assert resposta.status_code == 403


def test_host_estranho_e_recusado_contra_dns_rebinding():
    cliente = TestClient(app, base_url="http://rebind.attacker.example:8000")
    assert cliente.get("/projects").status_code == 403


def test_voltar_nunca_redireciona_para_outro_host():
    class Pedido:
        headers = {"referer": "https://a.example//evil.example/x"}

    assert _back_to(Pedido()) == "/projects"


# --- excluir um projeto -----------------------------------------------------------


def _entrada(pasta):
    return CatalogEntry(id=999, name="x", output_folder=str(pasta), created_at="2026-10-16")


def test_excluir_apaga_so_o_que_o_programa_criou(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.deletion.remove_project", lambda _id: None)
    pasta = tmp_path / "saida"
    (pasta / "windows").mkdir(parents=True)
    (pasta / "windows" / "g_j0001-0016.txt").write_text("x", encoding="utf-8")
    (pasta / "project.db").write_bytes(b"db")
    (pasta / "index.md").write_text("x", encoding="utf-8")
    (pasta / "index-grupo.md").write_text("x", encoding="utf-8")
    (pasta / "minha-planilha.xlsx").write_bytes(b"do usuario")

    delete_project(_entrada(pasta), delete_files=True)

    assert (pasta / "minha-planilha.xlsx").exists()
    assert not (pasta / "project.db").exists()
    assert not (pasta / "windows").exists()
    assert not (pasta / "index-grupo.md").exists()


def test_excluir_remove_a_pasta_quando_ela_fica_vazia(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.deletion.remove_project", lambda _id: None)
    pasta = tmp_path / "saida"
    pasta.mkdir()
    (pasta / "project.db").write_bytes(b"db")

    delete_project(_entrada(pasta), delete_files=True)

    assert not pasta.exists()


def test_excluir_pasta_sem_project_db_nao_apaga_nada(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.deletion.remove_project", lambda _id: None)
    pasta = tmp_path / "documentos"
    pasta.mkdir()
    (pasta / "index.md").write_text("um arquivo do usuário com o mesmo nome", encoding="utf-8")

    resultado = delete_project(_entrada(pasta), delete_files=True)

    assert (pasta / "index.md").exists()
    assert resultado.folder_deleted is False


def test_excluir_mantem_as_instrucoes_do_usuario_no_claude_md(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.deletion.remove_project", lambda _id: None)
    pasta = tmp_path / "saida"
    pasta.mkdir()
    (pasta / "project.db").write_bytes(b"db")
    (pasta / "CLAUDE.md").write_text(
        f"Regra minha.\n\n{BEGIN_MARK}\ngerado\n{END_MARK}\n", encoding="utf-8"
    )

    delete_project(_entrada(pasta), delete_files=True)

    conteudo = (pasta / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Regra minha." in conteudo
    assert "gerado" not in conteudo and BEGIN_MARK not in conteudo


# --- motor claude_code ----------------------------------------------------------


@pytest.mark.parametrize("language", ["pt", "en", "es"])
def test_claude_md_avisa_que_o_texto_das_janelas_e_so_dado(tmp_path, language):
    from gclaude_indexer.config import load_config
    from gclaude_indexer.windows_prep import generate_claude_md

    origem = tmp_path / "origem"
    origem.mkdir()
    config = load_config({"name": "x", "source_folder": str(origem),
                          "output_folder": str(tmp_path / "saida")})
    (tmp_path / "saida").mkdir()
    conteudo = generate_claude_md(config, language).read_text(encoding="utf-8")
    assert "UNTRUSTED" in conteudo

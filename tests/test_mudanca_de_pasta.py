"""2.0.0, tarefa 13: mudança da pasta de saída que está dentro da origem.

A saída de um projeto da 1.10 pode estar dentro da origem. A mudança a leva
para `<origem>-AI`, com diário na pasta local da máquina, retomada ou
desfeita a cada abertura, sem nunca sobrescrever nem seguir links."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
from gclaude_indexer import paths, relocation, sync, workdir
from gclaude_indexer.catalog import find_project, register_project
from gclaude_indexer.combined_package import load_members
from gclaude_indexer.config import ProjectConfig
from gclaude_indexer.lock import LockInfo, LOCK_FILE_NAME
from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK
from gclaude_indexer.project import create_project
from gclaude_indexer.sets import SetEntry, SetMember, find_set, save_set
from gclaude_indexer.web import rendering, routes_projects, routes_sets
from gclaude_indexer.web.app import app
from gclaude_indexer.web import state
from gclaude_indexer.web import readers
from gclaude_indexer.web import project_access
from gclaude_indexer.web import routes_relocation

HEADERS = {"Origin": "http://testserver"}


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Pasta local da máquina e pasta de trabalho isoladas no teste."""
    pasta = tmp_path / "local"
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(pasta))
    monkeypatch.setenv(workdir.WORK_FOLDER_ENV, str(pasta / "work"))
    monkeypatch.setattr(catalogo_mod, "catalog_folder", lambda: None)
    for modulo in (rendering, state, routes_projects, routes_sets):
        monkeypatch.setattr(modulo, "catalog_folder", lambda: None)
    return pasta


@pytest.fixture
def deteccao_ligada(monkeypatch):
    monkeypatch.setattr(
        project_access, "_relocation_due",
        lambda config: relocation.output_inside_source(config.source_folder, config.output_folder),
    )


@pytest.fixture
def cliente(local, deteccao_ligada):
    yield TestClient(app)
    for entrada in catalogo_mod.list_projects():
        state.lock_manager.close(entrada.output_folder)
        readers.reader_pool.close(entrada.output_folder)


def _criar(origem: Path, saida: Path, nome: str = "Projeto"):
    origem.mkdir(parents=True, exist_ok=True)
    config = ProjectConfig(name=nome, source_folder=str(origem), output_folder=str(saida))
    conn, _ = create_project(config)
    conn.close()
    return register_project(nome, str(saida))


def _gerados(saida: Path) -> None:
    """O que um projeto da 1.10 deixa na saída."""
    (saida / "index.md").write_text("# índice\n", encoding="utf-8")
    (saida / "index-2.md").write_text("# parte 2\n", encoding="utf-8")
    (saida / "timeline.md").write_text("linha\n", encoding="utf-8")
    (saida / "buscar.bat").write_text("@echo off\n", encoding="utf-8")
    (saida / "raw_items.jsonl").write_text("{}\n", encoding="utf-8")
    (saida / "logs").mkdir()
    (saida / "logs" / "execucao.log").write_text("log\n", encoding="utf-8")
    (saida / "converted" / "grupo").mkdir(parents=True)
    (saida / "converted" / "grupo" / "a.pdf").write_bytes(b"%PDF-1.4 ocr antigo")
    (saida / "converted" / "grupo" / "b.docx.txt").write_text("texto", encoding="utf-8")
    # Os intermediários são de documentos que o projeto conhece.
    conn = sqlite3.connect(saida / "project.db")
    conn.executemany(
        "INSERT INTO file (relative_path, name, extension, size, sha256, status) VALUES (?, ?, ?, 0, '', 'extracted')",
        [("grupo/a.pdf", "a.pdf", "pdf"), ("grupo/b.docx", "b.docx", "docx")],
    )
    conn.commit()
    conn.close()
    (saida / "windows").mkdir()
    (saida / "windows" / "grupo_j0001-0016.txt").write_text("janela", encoding="utf-8")
    (saida / "blocks").mkdir()
    (saida / "blocks" / "fatia.pdf").write_bytes(b"%PDF fatia")
    (saida / "CLAUDE.md").write_text(f"{BEGIN_MARK}\ngerado\n{END_MARK}\n", encoding="utf-8")


def _conteudo(pasta: Path) -> dict[str, str]:
    """Cada arquivo (caminho relativo → SHA-256), para provar que nada se perdeu."""
    resultado = {}
    for caminho in sorted(pasta.rglob("*")):
        if caminho.is_file():
            resultado[caminho.relative_to(pasta).as_posix()] = hashlib.sha256(caminho.read_bytes()).hexdigest()
    return resultado


def _saida_gravada(pasta: Path) -> tuple[str, str]:
    conn = sqlite3.connect(pasta / "project.db")
    try:
        output, config_json = conn.execute("SELECT output_folder, config_json FROM project").fetchone()
    finally:
        conn.close()
    return output, json.loads(config_json)["output_folder"]


# --- detecção ------------------------------------------------------------------


def test_detecta_saida_dentro_e_igual_a_origem(tmp_path):
    origem = tmp_path / "Acervo"
    origem.mkdir()
    assert relocation.output_inside_source(str(origem), str(origem / "saida"))
    assert relocation.output_inside_source(str(origem), str(origem))
    assert not relocation.output_inside_source(str(origem), str(tmp_path / "Acervo-AI"))
    assert not relocation.output_inside_source("", str(origem))


# --- pasta só nossa: muda de nome inteira ---------------------------------------


def test_pasta_so_com_itens_gerados_muda_inteira(local, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    trabalho = workdir.ensure_work_folder(saida)
    (trabalho / "converted").mkdir()
    (trabalho / "converted" / "x.txt").write_text("texto com OCR", encoding="utf-8")
    sync.mark_synced(saida)
    antes = _conteudo(saida)

    plano = relocation.build_plan(str(origem), str(saida))
    assert plano.mode == "rename"
    assert plano.new == str(tmp_path / "Acervo-AI")
    assert plano.carried[-1] == "project.db"
    assert "converted" in plano.carried
    assert sorted(plano.dropped) == ["blocks", "windows"]

    nova = Path(relocation.execute(plano))

    assert not saida.exists()
    depois = _conteudo(nova)
    obsoletos = {"windows/grupo_j0001-0016.txt", "blocks/fatia.pdf"}
    for nome, digest in antes.items():
        if nome in obsoletos:
            assert nome not in depois
        elif not nome.startswith(("logs/", "project.db")):  # o caminho novo e o evento entram no banco e no log
            assert depois[nome] == digest, nome
    assert not (nova / "windows").exists() and not (nova / "blocks").exists()
    assert (nova / "converted" / "grupo" / "a.pdf").read_bytes() == b"%PDF-1.4 ocr antigo"

    assert _saida_gravada(nova) == (str(nova), str(nova))
    movido = find_project(entrada.id)
    assert movido.output_folder == str(nova)

    # A pasta de trabalho local acompanha: nada de refazer OCR.
    assert not workdir.work_folder(saida).exists()
    novo_trabalho = workdir.work_folder(nova)
    assert (novo_trabalho / "converted" / "x.txt").read_text(encoding="utf-8") == "texto com OCR"
    assert (novo_trabalho / workdir.ORIGIN_FILE_NAME).read_text(encoding="utf-8").strip() == str(nova)

    registro = json.loads((local / sync.REGISTRY_FILE_NAME).read_text(encoding="utf-8"))
    assert str(nova.resolve()) in registro and str(saida.resolve()) not in registro
    assert relocation.pending_for(saida) is None and relocation.pending_for(nova) is None

    conn = sqlite3.connect(nova / "project.db")
    chaves = [linha[0] for linha in conn.execute("SELECT message_key FROM event")]
    conn.close()
    assert "log.relocation.done" in chaves


# --- pasta com arquivos do usuário -------------------------------------------


def test_arquivos_do_usuario_permanecem(local, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    (saida / "minhas notas.docx").write_bytes(b"do usuario")
    (saida / "Pessoal").mkdir()
    (saida / "Pessoal" / "foto.jpg").write_bytes(b"jpg")
    (saida / "CLAUDE.md").write_text(
        f"Minhas regras.\n\n{BEGIN_MARK}\ngerado\n{END_MARK}\n", encoding="utf-8"
    )

    plano = relocation.build_plan(str(origem), str(saida))
    assert plano.mode == "items"
    assert plano.kept == 2
    assert plano.copied_instructions == ["CLAUDE.md"]

    nova = Path(relocation.execute(plano))

    assert (saida / "minhas notas.docx").read_bytes() == b"do usuario"
    assert (saida / "Pessoal" / "foto.jpg").read_bytes() == b"jpg"
    for nome in ("project.db", "index.md", "index-2.md", "timeline.md", "buscar.bat", "raw_items.jsonl"):
        assert not (saida / nome).exists(), nome
        assert (nova / nome).is_file(), nome
    assert not (saida / "converted").exists() and (nova / "converted" / "grupo" / "a.pdf").is_file()
    # As sobras saem do lugar antigo; a pasta do usuário fica.
    assert not (saida / "windows").exists() and not (saida / "blocks").exists()
    # Instruções com texto do usuário: cópia inteira no lugar novo, e o
    # original fica só com o texto dele.
    assert "Minhas regras." in (nova / "CLAUDE.md").read_text(encoding="utf-8")
    assert BEGIN_MARK in (nova / "CLAUDE.md").read_text(encoding="utf-8")
    restante = (saida / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Minhas regras." in restante and BEGIN_MARK not in restante
    assert find_project(entrada.id).output_folder == str(nova)


def test_saida_igual_a_origem_move_so_os_gerados(local, tmp_path):
    origem = tmp_path / "Acervo"
    origem.mkdir()
    (origem / "processo.pdf").write_bytes(b"%PDF documento")
    entrada = _criar(origem, origem)
    (origem / "index.md").write_text("# índice\n", encoding="utf-8")

    plano = relocation.build_plan(str(origem), str(origem))
    assert plano.mode == "items"
    nova = Path(relocation.execute(plano))

    assert origem.is_dir() and (origem / "processo.pdf").read_bytes() == b"%PDF documento"
    assert not (origem / "project.db").exists()
    assert (nova / "project.db").is_file() and (nova / "index.md").is_file()
    assert find_project(entrada.id).output_folder == str(nova)


# --- destino ocupado, links, espaço ------------------------------------------------


def test_destino_ocupado_nunca_e_sobrescrito(local, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    ocupado = tmp_path / "Acervo-AI"
    ocupado.mkdir()
    (ocupado / "alheio.txt").write_text("não é nosso", encoding="utf-8")

    with pytest.raises(relocation.RelocationError) as erro:
        relocation.build_plan(str(origem), str(saida), destination=str(ocupado))
    assert erro.value.key == "relocation.error.destination_taken"

    # A sugestão pula para o próximo nome livre.
    plano = relocation.build_plan(str(origem), str(saida))
    assert plano.new == str(tmp_path / "Acervo-AI-2")
    relocation.execute(plano)
    assert (ocupado / "alheio.txt").read_text(encoding="utf-8") == "não é nosso"
    assert sorted(p.name for p in ocupado.iterdir()) == ["alheio.txt"]


def test_colisao_no_meio_desfaz_e_nao_sobrescreve(local, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    _gerados(saida)
    (saida / "meu.txt").write_text("usuario", encoding="utf-8")
    antes = _conteudo(saida)
    plano = relocation.build_plan(str(origem), str(saida))
    nova = Path(plano.new)

    original = os.rename
    chamadas = []

    def rename_com_intruso(origem_item, destino_item):
        chamadas.append(destino_item)
        if len(chamadas) == 3:
            # Alguém grava no destino no meio da mudança.
            Path(plano.new, plano.carried[3]).write_text("intruso", encoding="utf-8")
        return original(origem_item, destino_item)

    monkeypatch.setattr(relocation.os, "rename", rename_com_intruso)
    with pytest.raises(relocation.RelocationError) as erro:
        relocation.execute(plano)
    monkeypatch.setattr(relocation.os, "rename", original)

    assert erro.value.key == "relocation.error.collision"
    assert _conteudo(saida) == antes
    assert (nova / plano.carried[3]).read_text(encoding="utf-8") == "intruso"
    assert relocation.pending_for(saida) is None


@pytest.mark.skipif(sys.platform != "win32", reason="junção é do Windows")
def test_juncao_recusa_a_mudanca(local, tmp_path):
    import _winapi

    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    alvo = tmp_path / "fora"
    alvo.mkdir()
    (alvo / "segredo.txt").write_text("x", encoding="utf-8")
    _winapi.CreateJunction(str(alvo), str(saida / "converted"))

    with pytest.raises(relocation.RelocationError) as erro:
        relocation.build_plan(str(origem), str(saida))
    assert erro.value.key == "relocation.error.link"
    assert (alvo / "segredo.txt").exists()


def test_volume_diferente_copia_confere_e_so_depois_apaga(local, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    (saida / "meu.txt").write_text("usuario", encoding="utf-8")
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    antes = _conteudo(saida)

    plano = relocation.build_plan(str(origem), str(saida))
    assert not plano.same_volume and plano.total_bytes > 0
    nova = Path(relocation.execute(plano))

    depois = _conteudo(nova)
    for nome in ("index.md", "converted/grupo/a.pdf", "raw_items.jsonl"):
        assert depois[nome] == antes[nome], nome
    assert sorted(p.name for p in saida.iterdir()) == ["meu.txt"]
    assert find_project(entrada.id).output_folder == str(nova)


def test_copia_que_nao_confere_desfaz(local, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    _gerados(saida)
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    antes = _conteudo(saida)
    monkeypatch.setattr(relocation, "_sha256", lambda caminho: "0" * 64)

    plano = relocation.build_plan(str(origem), str(saida))
    with pytest.raises(relocation.RelocationError) as erro:
        relocation.execute(plano)

    assert erro.value.key == "relocation.error.copy_mismatch"
    assert _conteudo(saida) == antes
    assert not Path(plano.new).exists()
    assert relocation.pending_for(saida) is None


def test_sem_espaco_livre_nao_comeca(local, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    monkeypatch.setattr(
        relocation.shutil, "disk_usage", lambda caminho: type("U", (), {"free": 1024})()
    )
    plano = relocation.build_plan(str(origem), str(saida))
    with pytest.raises(relocation.RelocationError) as erro:
        relocation.execute(plano)
    assert erro.value.key == "relocation.error.space"
    assert (saida / "project.db").is_file() and not Path(plano.new).exists()


# --- queda em cada passo e retomada ----------------------------------------------


class _Queda(BaseException):
    """O processo morreu: nada de `except Exception` pega, nem o desfazer."""


def _preparar_queda(local, tmp_path, usuario: bool):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    if usuario:
        (saida / "meu.txt").write_text("usuario", encoding="utf-8")
    workdir.ensure_work_folder(saida)
    return origem, saida, entrada


@pytest.mark.parametrize(
    ("usuario", "queda_no_rename"),
    # Pasta inteira: 1 = o próprio rename da pasta, 2 = o da pasta de trabalho
    # (depois da confirmação). Itens: cada rename de item, e 99 = queda ao
    # anotar "committed" com tudo já movido.
    [(False, 1), (False, 2), (False, 99), (True, 1), (True, 2), (True, 4), (True, 99)],
    ids=["pasta-1", "pasta-2", "pasta-99", "itens-1", "itens-2", "itens-4", "itens-99"],
)
def test_queda_no_meio_dos_renames_e_retomada(local, tmp_path, monkeypatch, usuario, queda_no_rename):
    origem, saida, entrada = _preparar_queda(local, tmp_path, usuario)
    antes = {
        k: v for k, v in _conteudo(saida).items()
        if not k.startswith(("windows/", "blocks/", "logs/", "project.db")) and k != "meu.txt"
    }
    plano = relocation.build_plan(str(origem), str(saida))
    nova = Path(plano.new)

    original = os.rename
    contagem = {"n": 0}

    def rename_que_cai(a, b):
        contagem["n"] += 1
        if contagem["n"] == queda_no_rename:
            raise _Queda()
        return original(a, b)

    monkeypatch.setattr(relocation.os, "rename", rename_que_cai)
    monkeypatch.setattr(relocation, "_undo", lambda journal: (_ for _ in ()).throw(_Queda()))
    if queda_no_rename == 99:
        # Todos os renames passam; a queda vem ao anotar "committed".
        gravar = relocation._write_journal

        def gravar_e_cair(journal):
            if journal.get("phase") == "committed":
                raise _Queda()
            return gravar(journal)

        monkeypatch.setattr(relocation, "_write_journal", gravar_e_cair)

    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(local))
    monkeypatch.setenv(workdir.WORK_FOLDER_ENV, str(local / "work"))
    monkeypatch.setattr(catalogo_mod, "catalog_folder", lambda: None)

    assert relocation.pending_for(saida) is not None
    assert relocation.recover(saida)
    assert relocation.pending_for(saida) is None

    # Sempre um lado só: o catálogo aponta para onde está o banco, e o outro
    # lado não tem banco nenhum.
    destino = Path(find_project(entrada.id).output_folder)
    assert (destino / "project.db").is_file()
    assert not ((nova if destino == saida else saida) / "project.db").exists()
    if queda_no_rename == 1:
        assert destino == saida and not nova.exists()  # nada tinha mudado: desfeito
    if queda_no_rename == 99:
        assert destino == nova  # tudo já estava no destino: concluído
    depois = _conteudo(destino)
    for nome, digest in antes.items():
        assert depois.get(nome) == digest, nome
    if usuario:
        assert (saida / "meu.txt").read_text(encoding="utf-8") == "usuario"


@pytest.mark.parametrize("passo", ["_rewrite_project_paths", "relocate_catalog_entry", "_rename_work_folder", "_record_done"])
def test_queda_depois_da_confirmacao_conclui_na_abertura(local, tmp_path, monkeypatch, passo):
    origem, saida, entrada = _preparar_queda(local, tmp_path, usuario=True)
    plano = relocation.build_plan(str(origem), str(saida))
    nova = Path(plano.new)
    monkeypatch.setattr(relocation, passo, lambda *a, **k: (_ for _ in ()).throw(_Queda()))

    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(local))
    monkeypatch.setenv(workdir.WORK_FOLDER_ENV, str(local / "work"))
    monkeypatch.setattr(catalogo_mod, "catalog_folder", lambda: None)

    assert relocation.pending_for(saida)["phase"] == "committed"
    assert relocation.recover(saida)
    assert find_project(entrada.id).output_folder == str(nova)
    assert _saida_gravada(nova) == (str(nova), str(nova))
    assert workdir.work_folder(nova).is_dir() and not workdir.work_folder(saida).exists()
    assert (saida / "meu.txt").is_file() and not (saida / "project.db").exists()


def test_queda_e_retomada_pela_abertura_do_projeto(cliente, tmp_path, monkeypatch):
    """A abertura do projeto (qualquer tela) processa o diário antes de abrir
    o banco: nunca cria um `project.db` vazio no lugar antigo."""
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    relocation.postpone(saida)
    plano = relocation.build_plan(str(origem), str(saida))
    monkeypatch.setattr(relocation, "_rename_work_folder", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.setattr(relocation, "_rename_work_folder", lambda *a: None)

    resposta = cliente.get(f"/projects/{entrada.id}/run")

    assert resposta.status_code == 200
    assert not (saida / "project.db").exists()
    assert find_project(entrada.id).output_folder == plano.new
    assert relocation.pending_for(saida) is None


# --- tela, pré-condições e fluxo web ----------------------------------------------


def test_tela_de_interrupcao_e_mover_agora(cliente, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)

    tela = cliente.get(f"/projects/{entrada.id}/run")
    assert tela.status_code == 409
    assert "Mover agora" in tela.text and "Adiar" in tela.text
    assert str(tmp_path / "Acervo-AI") in tela.text
    assert "index.md" in tela.text

    resposta = cliente.post(f"/projects/{entrada.id}/relocate", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/projects/{entrada.id}/run"
    nova = tmp_path / "Acervo-AI"
    assert find_project(entrada.id).output_folder == str(nova)
    assert not saida.exists()

    execucao = cliente.get(f"/projects/{entrada.id}/run")
    assert execucao.status_code == 200
    assert "relocation-banner" not in execucao.text


def test_post_ignora_destino_vindo_do_formulario(cliente, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    outro = tmp_path / "escolhido-por-fora"

    cliente.post(
        f"/projects/{entrada.id}/relocate", headers=HEADERS,
        data={"destination": str(outro), "new": str(outro)}, follow_redirects=False,
    )
    assert not outro.exists()
    assert find_project(entrada.id).output_folder == str(tmp_path / "Acervo-AI")


def test_mover_agora_com_operacao_rodando_responde_ocupado(cliente, tmp_path):
    """Com a vaga tomada, a rota respondia de dentro da trava da vaga, e a
    página de ocupado tomava a mesma trava (não reentrante): o pedido
    travava e levava junto `/activity`, o Parar e toda operação seguinte."""
    from gclaude_indexer.i18n import translate

    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    with state._generation_slot(entrada.id, "run.import_and_generate") as tomada:
        assert tomada
        resposta = cliente.post(
            f"/projects/{entrada.id}/relocate", headers=HEADERS,
            cookies={"language": "pt"}, follow_redirects=False,
        )
    assert resposta.status_code == 409
    assert translate("pt", "run.import_and_generate") in resposta.text
    assert (saida / "project.db").is_file()


def test_post_de_outro_site_e_recusado(cliente, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    resposta = cliente.post(
        f"/projects/{entrada.id}/relocate", headers={"Origin": "https://malicioso.example"},
        follow_redirects=False,
    )
    assert resposta.status_code == 403
    assert (saida / "project.db").is_file()


def test_adiar_mostra_o_aviso_a_cada_abertura(cliente, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)

    resposta = cliente.post(f"/projects/{entrada.id}/relocate/postpone", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 303
    assert relocation.is_postponed(saida)

    for _ in range(2):
        state.lock_manager.close(str(saida))  # abertura nova, como numa sessão nova
        readers.reader_pool.close(str(saida))
        execucao = cliente.get(f"/projects/{entrada.id}/run")
        assert execucao.status_code == 200
        assert "relocation-banner" in execucao.text
        assert str(tmp_path / "Acervo-AI") in execucao.text
    assert (saida / "project.db").is_file()

    # O aviso não move nada: o botão é um link para a tela de confirmação
    # (decisão 10 do usuário).
    banner = execucao.text[execucao.text.index('id="relocation-banner"'):]
    banner = banner[: banner.index("</div>\n</div>")]
    assert "<form" not in banner and 'method="post"' not in banner
    assert f'href="/projects/{entrada.id}/relocate"' in banner
    confirmacao = cliente.get(f"/projects/{entrada.id}/relocate")
    assert confirmacao.status_code == 200
    assert "Mover agora" in confirmacao.text
    assert (saida / "project.db").is_file() and not (tmp_path / "Acervo-AI").exists()

    # Só o "Mover agora" da tela de confirmação faz a mudança.
    resposta = cliente.post(f"/projects/{entrada.id}/relocate", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 303
    assert find_project(entrada.id).output_folder == str(tmp_path / "Acervo-AI")
    assert not relocation.is_postponed(saida)


def test_trava_ativa_de_outra_maquina_recusa(cliente, tmp_path):
    from datetime import datetime

    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    agora = datetime.now().isoformat(timespec="seconds")
    (saida / LOCK_FILE_NAME).write_text(
        json.dumps(LockInfo(machine="OUTRA-MAQUINA", user="u", created_at=agora, updated_at=agora).__dict__),
        encoding="utf-8",
    )

    resposta = cliente.post(f"/projects/{entrada.id}/relocate", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 409
    assert "OUTRA-MAQUINA" in resposta.text
    assert (saida / "project.db").is_file()
    assert not (tmp_path / "Acervo-AI").exists()


def test_etapa_em_curso_recusa(cliente, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    monkeypatch.setattr(
        state.task_manager, "latest_for_project", lambda pid: type("T", (), {"running": True})()
    )

    resposta = cliente.post(f"/projects/{entrada.id}/relocate", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 409
    assert "etapa" in resposta.text
    assert (saida / "project.db").is_file()


def test_sincronizacao_com_aviso_recusa(cliente, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    monkeypatch.setattr(routes_relocation, "check_sync", lambda pasta: sync.SyncCheckResult(False, "sync.incomplete"))

    resposta = cliente.post(f"/projects/{entrada.id}/relocate", headers=HEADERS, follow_redirects=False)
    assert resposta.status_code == 409
    assert (saida / "project.db").is_file()


def test_origem_na_raiz_mostra_aviso_sem_botao_de_mover(cliente, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    monkeypatch.setattr(relocation.paths, "suggest_output_folder", lambda origem: None)
    monkeypatch.setattr(routes_relocation, "suggest_output_folder", lambda origem: None)

    tela = cliente.get(f"/projects/{entrada.id}/run")
    assert tela.status_code == 409
    assert "Adiar" in tela.text
    assert f'action="/projects/{entrada.id}/relocate"' not in tela.text


# --- catálogo e Conjunto ---------------------------------------------------------


def test_catalogo_compartilhado_e_local_atualizados_com_o_mesmo_id(local, tmp_path, monkeypatch):
    compartilhada = tmp_path / "Drive" / "Catalogo"
    compartilhada.mkdir(parents=True)
    origem = tmp_path / "Drive" / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)  # entra no catálogo local
    monkeypatch.setattr(catalogo_mod, "catalog_folder", lambda: compartilhada)
    catalogo_mod.adopt_local_projects()

    relocation.execute(relocation.build_plan(str(origem), str(saida)))
    nova = tmp_path / "Drive" / "Acervo-AI"

    for arquivo in (compartilhada / "projects.json", local / "projects.json"):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        assert [(d["id"], d["output_folder"]) for d in dados] == [(entrada.id, str(nova))], arquivo
    compartilhado = json.loads((compartilhada / "projects.json").read_text(encoding="utf-8"))[0]
    assert compartilhado["relative_output_folder"] == os.path.relpath(str(nova), str(compartilhada))
    assert find_project(entrada.id).output_folder == str(nova)


def test_conjunto_continua_valido(local, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    conjunto = save_set(SetEntry(id=0, name="Tudo", members=[SetMember(project_id=entrada.id, alias="acervo")]))

    relocation.execute(relocation.build_plan(str(origem), str(saida)))

    membros = load_members(find_set(conjunto.id))
    assert len(membros) == 1 and membros[0].available, membros[0].reason
    assert membros[0].catalog.output_folder == str(tmp_path / "Acervo-AI")


def test_abrir_pasta_sem_banco_nao_cria_banco_vazio(tmp_path):
    from gclaude_indexer.project import load_project

    pasta = tmp_path / "vazia"
    pasta.mkdir()
    with pytest.raises(FileNotFoundError):
        load_project(pasta)
    assert not (pasta / "project.db").exists()


def test_tela_de_projetos_com_mudanca_interrompida_nao_abre_o_banco(cliente, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    (saida / "meu.txt").write_text("usuario", encoding="utf-8")
    plano = relocation.build_plan(str(origem), str(saida))
    monkeypatch.setattr(relocation, "_rewrite_project_paths", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)

    tela = cliente.get("/projects")

    assert tela.status_code == 200
    assert not (saida / "project.db").exists()
    assert relocation.pending_for(saida) is not None


def test_diario_com_pastas_fora_do_ar_fica_para_depois(local, tmp_path):
    """Unidade desmontada: a retomada não decide nada e não apaga o diário."""
    ausente = tmp_path / "unidade-fora" / "Acervo"
    diario = {
        "version": 1, "source": str(ausente), "old": str(ausente / "saida"), "new": str(ausente) + "-AI",
        "mode": "rename", "same_volume": True, "ops": [], "strip": [], "dropped": [],
        "created_new": False, "phase": "moving",
    }
    relocation._write_journal(diario)

    assert not relocation.recover(ausente / "saida")
    assert relocation.pending_for(ausente / "saida") is not None


# --- rodada de correções 1 ---------------------------------------------------------


def _religar(monkeypatch, local, tmp_path):
    """Depois de `monkeypatch.undo()` (que também desfaz o conftest)."""
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(local))
    monkeypatch.setenv(workdir.WORK_FOLDER_ENV, str(local / "work"))
    monkeypatch.setattr(catalogo_mod, "catalog_folder", lambda: None)
    monkeypatch.setattr(project_access, "_relocation_due", lambda config: False)


def test_colisao_numa_copia_entre_volumes_nao_apaga_o_intruso(local, tmp_path, monkeypatch):
    """Item que nunca começou não é desfeito: o arquivo que outro gravou no
    destino dele fica (antes, o desfazer o apagava achando que era cópia nossa)."""
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    _criar(origem, saida)
    for nome in ("index.md", "timeline.md", "buscar.bat"):
        (saida / nome).write_text(nome, encoding="utf-8")
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    antes = _conteudo(saida)
    plano = relocation.build_plan(str(origem), str(saida))
    alvo = Path(plano.new) / plano.carried[1]
    real = relocation._copy_tree_verified
    chamadas = {"n": 0}

    def copiar_e_intrometer(origem_item, destino_item, on_created=None):
        real(origem_item, destino_item, on_created=on_created)
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            alvo.write_text("INTRUSO", encoding="utf-8")

    monkeypatch.setattr(relocation, "_copy_tree_verified", copiar_e_intrometer)
    with pytest.raises(relocation.RelocationError) as erro:
        relocation.execute(plano)

    assert erro.value.key == "relocation.error.collision"
    assert alvo.read_text(encoding="utf-8") == "INTRUSO"
    assert not (Path(plano.new) / plano.carried[0]).exists()  # a cópia nossa saiu
    assert _conteudo(saida) == antes
    assert relocation.pending_for(saida) is None


def test_queda_durante_a_copia_e_retomada_preserva_o_intruso(local, tmp_path, monkeypatch):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    antes = _conteudo(saida)
    plano = relocation.build_plan(str(origem), str(saida))
    nova = Path(plano.new)
    real = relocation._copy_tree_verified
    chamadas = {"n": 0}

    def copiar_e_cair(origem_item, destino_item, on_created=None):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            Path(destino_item).write_bytes(b"pela metade")  # a cópia criou o destino e caiu
            on_created()
            # Um arquivo de outro no destino de um item que ainda não começou.
            (nova / plano.carried[-1]).write_text("de outro", encoding="utf-8")
            raise _Queda()
        return real(origem_item, destino_item, on_created=on_created)

    monkeypatch.setattr(relocation, "_copy_tree_verified", copiar_e_cair)
    monkeypatch.setattr(relocation, "_undo", lambda journal: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)

    assert relocation.recover(saida)
    assert _conteudo(saida) == antes
    assert find_project(entrada.id).output_folder == str(saida)
    assert (nova / plano.carried[-1]).read_text(encoding="utf-8") == "de outro"
    assert sorted(p.name for p in nova.iterdir()) == [plano.carried[-1]]


@pytest.mark.skipif(sys.platform != "win32", reason="junção é do Windows")
def test_saida_que_e_juncao_nao_e_seguida(local, tmp_path):
    import subprocess

    origem = tmp_path / "Acervo"
    origem.mkdir()
    real = tmp_path / "fora" / "saida-real"
    _criar(tmp_path / "fora", real)
    juncao = origem / "saida"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(juncao), str(real)], check=True, capture_output=True)
    assert relocation._is_link(juncao)

    assert relocation.output_inside_source(str(origem), str(juncao))
    with pytest.raises(relocation.RelocationError) as erro:
        relocation.build_plan(str(origem), str(juncao))
    assert erro.value.key == "relocation.error.link"
    assert (real / "project.db").is_file()


def test_diario_achado_com_outra_grafia_do_caminho(cliente, local, tmp_path, monkeypatch):
    """O catálogo pode guardar uma grafia (com `..`, nome curto) e o plano a
    resolvida: as duas acham o mesmo diário, e a abertura conclui a mudança."""
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    relocation.postpone(saida)
    (origem / "outra").mkdir()
    torto = str(origem / "outra" / ".." / "saida")
    catalogo = local / "projects.json"
    dados = json.loads(catalogo.read_text(encoding="utf-8"))
    dados[0]["output_folder"] = torto
    catalogo.write_text(json.dumps(dados), encoding="utf-8")
    plano = relocation.build_plan(str(origem), torto)
    monkeypatch.setattr(relocation, "relocate_catalog_entry", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)
    assert find_project(entrada.id).output_folder == torto
    assert relocation.pending_for(torto) is not None

    resposta = cliente.get(f"/projects/{entrada.id}/run")

    assert resposta.status_code == 200
    assert find_project(entrada.id).output_folder == plano.new
    assert relocation.pending_for(torto) is None


@pytest.mark.parametrize("outro_volume", [False, True], ids=["mesmo-volume", "outro-volume"])
def test_pastas_logs_e_converted_do_usuario_ficam(local, tmp_path, monkeypatch, outro_volume):
    origem = tmp_path / "Acervo"
    origem.mkdir()
    (origem / "logs").mkdir()
    (origem / "logs" / "servidor.log").write_text("do usuário", encoding="utf-8")
    (origem / "converted").mkdir()
    (origem / "converted" / "planilha.xlsx").write_bytes(b"do usuario")
    (origem / "processo.pdf").write_bytes(b"%PDF")
    entrada = _criar(origem, origem)
    (origem / "index.md").write_text("# índice\n", encoding="utf-8")
    if outro_volume:
        monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)

    plano = relocation.build_plan(str(origem), str(origem))
    assert "logs" not in plano.carried and "converted" not in plano.carried
    nova = Path(relocation.execute(plano))

    assert (origem / "logs" / "servidor.log").read_text(encoding="utf-8") == "do usuário"
    assert (origem / "converted" / "planilha.xlsx").read_bytes() == b"do usuario"
    # Na pasta nova, `logs/` só tem o log do próprio programa (o evento da mudança).
    assert not (nova / "converted").exists()
    assert not (nova / "logs" / "servidor.log").exists()
    assert (nova / "project.db").is_file() and find_project(entrada.id).output_folder == str(nova)


def test_pastas_nossas_sao_listadas_como_pastas_na_confirmacao(cliente, tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    plano = relocation.build_plan(str(origem), str(saida))
    assert sorted(plano.carried_folders) == ["converted", "logs"]

    tela = cliente.get(f"/projects/{entrada.id}/relocate")
    assert "<code>converted/</code>" in tela.text and "<code>logs/</code>" in tela.text


def test_origem_vazia_nunca_e_removida_e_retomada_tolera(local, tmp_path, monkeypatch):
    """Saída = origem, sem documentos: a origem fica, mesmo vazia. E se a
    pasta antiga sumir depois da confirmação, a retomada conclui assim mesmo."""
    origem = tmp_path / "Acervo"
    entrada = _criar(origem, origem)
    nova = Path(relocation.execute(relocation.build_plan(str(origem), str(origem))))
    assert origem.is_dir()
    assert find_project(entrada.id).output_folder == str(nova)

    origem2 = tmp_path / "Outro"
    saida2 = origem2 / "saida"
    entrada2 = _criar(origem2, saida2)
    (saida2 / "meu.txt").write_text("u", encoding="utf-8")
    plano = relocation.build_plan(str(origem2), str(saida2))
    monkeypatch.setattr(relocation, "relocate_catalog_entry", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)
    # O usuário esvaziou e apagou a pasta antiga antes da próxima abertura.
    (saida2 / "meu.txt").unlink()
    for resto in saida2.iterdir():
        resto.unlink()
    saida2.rmdir()

    assert relocation.recover(saida2)
    assert find_project(entrada2.id).output_folder == plano.new


# --- rodada de correções 2 ---------------------------------------------------------


@pytest.mark.parametrize("nome", ["Acervo #1", "Acervo%20Dois", "Acervo #2%41"])
def test_caminho_com_cerquilha_ou_percentual_nao_cria_arquivo_nem_perde_converted(local, tmp_path, nome):
    """A URI de só leitura do SQLite é escapada: `#` não corta o caminho (o
    que abria o banco truncado em leitura e escrita e criava um arquivo vazio
    ao lado da origem) e `%20` não é decodificado."""
    origem = tmp_path / nome
    saida = origem / "saida"
    _criar(origem, saida)
    _gerados(saida)
    antes = sorted(p.name for p in tmp_path.iterdir())

    plano = relocation.build_plan(str(origem), str(saida))

    assert sorted(p.name for p in tmp_path.iterdir()) == antes  # nada criado ao lado
    assert "converted" in plano.carried_folders
    assert plano.mode == "rename"


def test_describe_project_com_cerquilha_no_caminho(tmp_path):
    from gclaude_indexer.project import describe_project

    origem = tmp_path / "Acervo #1"
    saida = origem / "saida"
    origem.mkdir()
    conn, _ = create_project(ProjectConfig(name="P", source_folder=str(origem), output_folder=str(saida)))
    conn.close()
    antes = sorted(p.name for p in tmp_path.iterdir())
    resumo = describe_project(saida)
    assert resumo is not None and resumo.name == "P"
    assert sorted(p.name for p in tmp_path.iterdir()) == antes


def test_uri_de_so_leitura_escapa_e_aceita_unc():
    assert paths.sqlite_readonly_uri(r"C:\A #1\x%20y\project.db") == "file:///C:/A%20%231/x%2520y/project.db?mode=ro"
    assert paths.sqlite_readonly_uri(r"\\srv\share\p.db").startswith("file:////srv/share/")


def _projeto_com_tres_arquivos(tmp_path):
    origem = tmp_path / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    for nome in ("index.md", "timeline.md", "buscar.bat"):
        (saida / nome).write_text(nome, encoding="utf-8")
    return origem, saida, entrada


def test_intruso_entre_a_conferencia_e_a_criacao_fica(local, tmp_path, monkeypatch):
    """Revisão: o arquivo aparece no destino depois de anotado `started` e
    antes do `xb`. A criação exclusiva falha e o desfazer não o toca."""
    origem, saida, _ = _projeto_com_tres_arquivos(tmp_path)
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    plano = relocation.build_plan(str(origem), str(saida))
    alvo = Path(plano.new) / plano.carried[1]
    gravar = relocation._write_journal

    def gravar_e_intrometer(journal):
        gravar(journal)
        ops = journal.get("ops", [])
        if len(ops) > 1 and ops[1].get("started") and not alvo.exists():
            alvo.write_text("INTRUSO", encoding="utf-8")

    monkeypatch.setattr(relocation, "_write_journal", gravar_e_intrometer)
    with pytest.raises(relocation.RelocationError):
        relocation.execute(plano)
    assert alvo.read_text(encoding="utf-8") == "INTRUSO"
    assert (saida / plano.carried[1]).is_file() and (saida / "project.db").is_file()


def test_queda_depois_de_started_e_intruso_antes_da_retomada(local, tmp_path, monkeypatch):
    origem, saida, entrada = _projeto_com_tres_arquivos(tmp_path)
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    plano = relocation.build_plan(str(origem), str(saida))
    alvo = Path(plano.new) / plano.carried[1]
    gravar = relocation._write_journal

    def gravar_e_cair(journal):
        gravar(journal)
        ops = journal.get("ops", [])
        if len(ops) > 1 and ops[1].get("started"):
            raise _Queda()

    monkeypatch.setattr(relocation, "_write_journal", gravar_e_cair)
    monkeypatch.setattr(relocation, "_undo", lambda journal: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)
    assert relocation.pending_for(saida) is not None
    alvo.write_text("INTRUSO", encoding="utf-8")

    assert relocation.recover(saida)
    assert alvo.read_text(encoding="utf-8") == "INTRUSO"
    assert not (Path(plano.new) / plano.carried[0]).exists()  # a cópia nossa (criada) saiu
    assert find_project(entrada.id).output_folder == str(saida)


@pytest.mark.skipif(sys.platform != "win32", reason="junção é do Windows")
def test_juncao_acima_da_saida_nao_e_seguida(local, tmp_path):
    import subprocess

    origem = tmp_path / "Acervo"
    origem.mkdir()
    fora = tmp_path / "fora"
    real = fora / "saida"
    fora.mkdir()
    conn, _ = create_project(ProjectConfig(name="P", source_folder=str(origem), output_folder=str(real)))
    conn.close()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(origem / "link"), str(fora)], check=True, capture_output=True)
    escrito = origem / "link" / "saida"
    assert relocation.output_inside_source(str(origem), str(escrito))

    with pytest.raises(relocation.RelocationError) as erro:
        relocation.build_plan(str(origem), str(escrito))
    assert erro.value.key == "relocation.error.link"
    assert (real / "project.db").is_file()


def test_pasta_antiga_fora_do_ar_depois_da_confirmacao_nao_conclui(local, tmp_path, monkeypatch):
    """Cópia entre volumes confirmada, e a unidade da origem sai do ar antes
    de apagar os originais: a retomada espera, em vez de largar tudo lá."""
    origem = tmp_path / "Unidade" / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    _gerados(saida)
    (saida / "meu.txt").write_text("u", encoding="utf-8")
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    nova_base = tmp_path / "Outra"
    nova_base.mkdir()
    plano = relocation.build_plan(str(origem), str(saida), destination=str(nova_base / "Acervo-AI"))
    monkeypatch.setattr(relocation, "_rewrite_project_paths", lambda *a: (_ for _ in ()).throw(_Queda()))
    # A queda vem já na limpeza: força-a antes de apagar os originais.
    monkeypatch.setattr(relocation, "_remove_tree", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)
    assert relocation.pending_for(saida)["phase"] == "committed"

    fora_do_ar = tmp_path / "Unidade-desmontada"
    (tmp_path / "Unidade").rename(fora_do_ar)
    assert not relocation.recover(saida)
    assert relocation.pending_for(saida) is not None

    fora_do_ar.rename(tmp_path / "Unidade")
    assert relocation.recover(saida)
    assert not (saida / "project.db").exists() and (saida / "meu.txt").is_file()
    assert find_project(entrada.id).output_folder == plano.new


# --- rodada de correções 3 ---------------------------------------------------------


def test_pasta_inteira_entre_volumes_com_origem_fora_do_ar_nao_conclui(local, tmp_path, monkeypatch):
    """Troca da pasta inteira para outro volume (cópia), queda depois da
    confirmação ao apagar os originais, e a unidade antiga sai do ar: a
    retomada espera; com a unidade de volta, conclui e não sobra o projeto
    antigo na origem."""
    origem = tmp_path / "Unidade" / "Acervo"
    saida = origem / "saida"
    entrada = _criar(origem, saida)
    for nome in ("index.md", "timeline.md", "buscar.bat"):
        (saida / nome).write_text(nome, encoding="utf-8")
    monkeypatch.setattr(relocation, "_same_volume", lambda a, b: False)
    (tmp_path / "Outra").mkdir()
    plano = relocation.build_plan(str(origem), str(saida), destination=str(tmp_path / "Outra" / "Acervo-AI"))
    assert plano.mode == "rename" and not plano.same_volume
    monkeypatch.setattr(relocation, "_remove_tree", lambda *a: (_ for _ in ()).throw(_Queda()))
    with pytest.raises(_Queda):
        relocation.execute(plano)
    monkeypatch.undo()
    _religar(monkeypatch, local, tmp_path)
    assert relocation.pending_for(saida)["phase"] == "committed"

    fora_do_ar = tmp_path / "Unidade-desmontada"
    (tmp_path / "Unidade").rename(fora_do_ar)
    assert not relocation.recover(saida)
    assert relocation.pending_for(saida) is not None

    fora_do_ar.rename(tmp_path / "Unidade")
    assert relocation.recover(saida)
    assert not (saida / "project.db").exists()
    assert find_project(entrada.id).output_folder == plano.new

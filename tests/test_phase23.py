"""1.5.3: the run buttons answer at once on a huge source folder, a second
click never starts a second run, and `.ini` files are never indexed."""

from __future__ import annotations

import threading
import time

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.file_types import is_extension_allowed
from gclaude_indexer.web import background_runs
from gclaude_indexer.web.app import app
from gclaude_indexer.web.background_runs import task_manager


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


@pytest.fixture(autouse=True)
def limpar_gerenciador():
    task_manager._tasks.clear()
    yield
    task_manager._tasks.clear()


def _criar_projeto(cliente, tmp_path, extensoes=("pdf",)):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    documento = fitz.open()
    documento.new_page().insert_textbox(
        (50, 50, 550, 750), "OFÍCIO No 1\nTexto suficiente para não acionar o OCR na conversão.", fontsize=12
    )
    documento.save(origem / "volume_1" / "peca.pdf")
    documento.close()
    dados = {
        "name": "Projeto 1.5.3", "subject": "Acervo de teste", "source_folder": str(origem),
        "output_folder": str(tmp_path / "saida"), "collection_type": "processo",
        "group_mode": "subfolder", "group_pattern": "", "extensions": list(extensoes),
        "pages_per_block": "80", "pages_per_window": "16", "overlap": "2", "chars_per_page": "2000",
        "ocr_language": "por", "classification_engine": "rules", "local_model": "automatic",
        "role_instructions": "", "extra_rules": "",
    }
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2]), origem


def _contagem_lenta(monkeypatch):
    """Simula a contagem de uma pasta enorme no Drive: só termina quando o
    teste solta o `liberar`."""
    liberar = threading.Event()
    original = background_runs._scan_totals

    def lenta(config, **kwargs):
        if kwargs.get("on_found"):
            kwargs["on_found"](7)
        liberar.wait(10)
        return original(config, **kwargs)

    monkeypatch.setattr(background_runs, "_scan_totals", lenta)
    return liberar


def _esperar(condicao, timeout=30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError("condição não atingida a tempo")


def test_rodar_etapa_seguinte_responde_antes_de_contar_a_pasta(cliente, tmp_path, monkeypatch):
    projeto_id, _ = _criar_projeto(cliente, tmp_path)
    liberar = _contagem_lenta(monkeypatch)

    inicio = time.monotonic()
    resposta = cliente.post(f"/projects/{projeto_id}/run-next")
    decorrido = time.monotonic() - inicio
    try:
        assert resposta.status_code == 200
        assert decorrido < 3, f"a resposta esperou a contagem da pasta ({decorrido:.1f}s)"
        tarefa = task_manager.get(projeto_id, "scan")
        assert tarefa is not None and tarefa.running
    finally:
        liberar.set()
    _esperar(lambda: not task_manager.get(projeto_id, "scan").running)
    assert task_manager.get(projeto_id, "scan").finished_ok


def test_rodar_tudo_mostra_a_etapa_enquanto_conta_a_pasta(cliente, tmp_path, monkeypatch):
    projeto_id, _ = _criar_projeto(cliente, tmp_path)
    liberar = _contagem_lenta(monkeypatch)
    try:
        cliente.post(f"/projects/{projeto_id}/run-all")
        _esperar(lambda: task_manager.get(projeto_id, "scan") is not None, timeout=3)
        html = cliente.get(f"/projects/{projeto_id}/run/progress").text
        assert "Nenhuma etapa rodando" not in html
        # um contador que cresce: a tela mostra que o sistema não travou
        assert "Contando os arquivos" in html
        assert "7 arquivo(s) encontrado(s)" in html
    finally:
        liberar.set()
        task_manager.pause(projeto_id)
    _esperar(lambda: not any(t.running for (pid, _), t in task_manager._tasks.items() if pid == projeto_id))


def test_segundo_clique_nao_abre_outra_varredura(cliente, tmp_path, monkeypatch):
    projeto_id, _ = _criar_projeto(cliente, tmp_path)
    liberar = _contagem_lenta(monkeypatch)
    chamadas = []
    original = background_runs._STEP_FUNCTIONS["scan"]

    def contar_chamadas(*args, **kwargs):
        chamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setitem(background_runs._STEP_FUNCTIONS, "scan", contar_chamadas)

    respostas = []
    cliques = [
        threading.Thread(target=lambda: respostas.append(cliente.post(f"/projects/{projeto_id}/run-next")))
        for _ in range(3)
    ]
    for clique in cliques:
        clique.start()
    for clique in cliques:
        clique.join(5)
    liberar.set()
    _esperar(lambda: not task_manager.get(projeto_id, "scan").running)

    assert len(respostas) == 3
    assert len(chamadas) == 1


def test_contagem_ignora_os_arquivos_de_sistema_como_a_varredura(cliente, tmp_path):
    projeto_id, origem = _criar_projeto(cliente, tmp_path)
    (origem / "volume_1" / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")

    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar(lambda: task_manager.get(projeto_id, "scan") is not None
             and not task_manager.get(projeto_id, "scan").running)

    tarefa = task_manager.get(projeto_id, "scan")
    assert tarefa.total == 1
    html = cliente.get(f"/projects/{projeto_id}/run/progress").text
    assert "1 / 1 (100%)" in html


def test_ini_nunca_entra_nem_com_todas_as_extensoes():
    assert not is_extension_allowed(".ini", ["all"])
    assert not is_extension_allowed(".INI", ["all"])
    # os HTML continuam entrando
    assert is_extension_allowed(".htm", ["all"])
    assert is_extension_allowed(".html", ["web_dados"])


def test_a_pasta_de_origem_e_percorrida_uma_vez_so(cliente, tmp_path, monkeypatch):
    """A contagem entrega a lista pronta à varredura: no Drive, cada
    caminhada pela pasta de 145 mil arquivos custa minutos."""
    from gclaude_indexer import scanning

    projeto_id, _ = _criar_projeto(cliente, tmp_path)
    caminhadas = []
    original = scanning.walk_source_files

    def contar(*args, **kwargs):
        caminhadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(scanning, "walk_source_files", contar)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar(lambda: task_manager.get(projeto_id, "scan") is not None
             and not task_manager.get(projeto_id, "scan").running)

    assert task_manager.get(projeto_id, "scan").finished_ok
    assert len(caminhadas) == 1


def test_caminhada_informa_cada_arquivo_encontrado(tmp_path):
    from gclaude_indexer.scanning import walk_source_files

    origem = tmp_path / "origem"
    (origem / "a").mkdir(parents=True)
    for nome in ("b.txt", "a/c.txt", "a/desktop.ini"):
        (origem / nome).write_text("x", encoding="utf-8")
    vistos = []

    encontrados = walk_source_files(origem, tmp_path / "saida", on_found=vistos.append)

    assert [p.relative_to(origem).as_posix() for p, _ in encontrados] == ["a/c.txt", "b.txt"]
    assert [tamanho for _, tamanho in encontrados] == [1, 1]
    assert vistos == [1, 2]

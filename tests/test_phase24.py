"""1.5.4: a second scan of an unchanged source folder does not read the
files again, and its progress bar moves while it runs instead of sitting
at 0% until the end."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer import scanning
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.scanning import scan
from gclaude_indexer.web.app import app
from gclaude_indexer.web.background_runs import task_manager


def _config(origem, saida):
    return load_config(
        {"name": "X", "source_folder": str(origem), "output_folder": str(saida), "extensions": ["text"]}
    )


def _conn(tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir(exist_ok=True)
    conn = connect(saida / "project.db")
    init_schema(conn)
    return conn


def _acervo(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.txt").write_text("primeiro", encoding="utf-8")
    (origem / "b.txt").write_text("segundo documento", encoding="utf-8")
    return origem


def _proibir_leitura(monkeypatch):
    def nao_pode_ler(caminho):
        raise AssertionError(f"a varredura leu os bytes de {caminho}")

    monkeypatch.setattr(scanning, "compute_hash", nao_pode_ler)


def test_segunda_varredura_nao_le_arquivo_sem_mudanca(tmp_path, monkeypatch):
    """No Drive, reabrir 145 mil arquivos só para confirmar o hash custa
    horas. Tamanho e data iguais bastam, como já bastam em `update_plan`."""
    origem = _acervo(tmp_path)
    conn = _conn(tmp_path)
    config = _config(origem, tmp_path / "saida")
    scan(conn, config)

    _proibir_leitura(monkeypatch)
    resultado = scan(conn, config)

    assert resultado.skipped == 2
    assert resultado.discovered == 0 and resultado.updated == 0


def test_mudanca_com_mesmo_tamanho_ainda_e_detectada(tmp_path):
    origem = _acervo(tmp_path)
    conn = _conn(tmp_path)
    config = _config(origem, tmp_path / "saida")
    scan(conn, config)

    arquivo = origem / "a.txt"
    antes = arquivo.stat().st_mtime
    arquivo.write_text("PRIMEIRO", encoding="utf-8")  # mesmo tamanho
    os.utime(arquivo, (antes + 10, antes + 10))

    resultado = scan(conn, config)

    assert resultado.updated == 1
    assert resultado.skipped == 1


def test_tamanho_errado_gravado_e_corrigido_sem_reler_depois(tmp_path, monkeypatch):
    """O Drive às vezes devolve `st_size = 16384` logo após gravar. Se esse
    valor chegou ao banco, a varredura seguinte confere o hash uma vez e
    corrige o tamanho, para não reler o arquivo em toda varredura."""
    origem = _acervo(tmp_path)
    conn = _conn(tmp_path)
    config = _config(origem, tmp_path / "saida")
    scan(conn, config)
    conn.execute("UPDATE file SET size = 16384 WHERE relative_path = 'a.txt'")
    conn.commit()

    resultado = scan(conn, config)
    assert resultado.skipped == 2
    gravado = conn.execute("SELECT size FROM file WHERE relative_path = 'a.txt'").fetchone()[0]
    assert gravado == (origem / "a.txt").stat().st_size

    _proibir_leitura(monkeypatch)
    assert scan(conn, config).skipped == 2


def test_varredura_informa_o_avanco_a_cada_arquivo(tmp_path):
    origem = _acervo(tmp_path)
    conn = _conn(tmp_path)
    config = _config(origem, tmp_path / "saida")
    scan(conn, config)

    avanco = []
    scan(conn, config, on_progress=lambda feitos, bytes_feitos: avanco.append((feitos, bytes_feitos)))

    total_bytes = sum(p.stat().st_size for p in origem.iterdir())
    assert avanco[-1] == (2, total_bytes)
    feitos = [f for f, _ in avanco]
    assert feitos == sorted(feitos)


# --- tela de execução -------------------------------------------------------


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


def _esperar(condicao, timeout=30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError("condição não atingida a tempo")


def _criar_projeto(cliente, tmp_path):
    origem = _acervo(tmp_path)
    dados = {
        "name": "Projeto 1.5.4", "subject": "Acervo de teste", "source_folder": str(origem),
        "output_folder": str(tmp_path / "saida"), "collection_type": "processo",
        "group_mode": "subfolder", "group_pattern": "", "extensions": ["text"],
        "pages_per_block": "80", "pages_per_window": "16", "overlap": "2", "chars_per_page": "2000",
        "ocr_language": "por", "classification_engine": "rules", "local_model": "automatic",
        "role_instructions": "", "extra_rules": "",
    }
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


def _varrer(cliente, projeto_id):
    task_manager._tasks.clear()
    task_manager.start_step(
        projeto_id, *_saida_e_config(cliente, projeto_id), "scan"
    )
    _esperar(lambda: not task_manager.get(projeto_id, "scan").running)
    assert task_manager.get(projeto_id, "scan").finished_ok


def _saida_e_config(cliente, projeto_id):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    entrada = find_project(projeto_id)
    config, conn = load_project(entrada.output_folder)
    conn.close()
    return entrada.output_folder, config


def test_barra_da_segunda_varredura_conta_os_arquivos_conferidos(cliente, tmp_path):
    """Antes, a barra media linhas novas no banco: numa segunda varredura,
    sem nada novo, ficava em "0 / N" do começo ao fim."""
    projeto_id = _criar_projeto(cliente, tmp_path)
    _varrer(cliente, projeto_id)
    _varrer(cliente, projeto_id)

    html = cliente.get(f"/projects/{projeto_id}/run/progress").text
    assert "2 / 2 (100%)" in html

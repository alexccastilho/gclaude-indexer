"""Phase 10 tests: run lock, machine sync and the projects catalog."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
import gclaude_indexer.lock as lock_mod
from gclaude_indexer.i18n import translate
from gclaude_indexer.sync import check_sync, mark_synced
from gclaude_indexer.lock import (
    LockManager,
    LockInfo,
    refresh_lock,
    lock_path,
    create_lock,
    read_lock,
    remove_lock,
    check_lock,
)


def _escrever_trava_manual(pasta_saida: Path, maquina: str, usuario: str, minutos_atras: float) -> None:
    quando = (datetime.now() - timedelta(minutes=minutos_atras)).isoformat(timespec="seconds")
    trava = LockInfo(machine=maquina, user=usuario, created_at=quando, updated_at=quando)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    lock_path(pasta_saida).write_text(json.dumps(trava.__dict__, ensure_ascii=False), encoding="utf-8")


# --- lock.py: criação, leitura, verificação --------------------------------


def test_criar_e_ler_trava(tmp_path):
    trava = create_lock(tmp_path)
    lida = read_lock(tmp_path)
    assert lida == trava
    assert lock_path(tmp_path).name == "project.lock"


def test_trava_grava_chaves_json_em_ingles(tmp_path):
    """`project.lock` is state persisted to disk (spec 11.3) — same language
    requirement as the SQLite database (Task 3, Phase 14), so its JSON keys
    must be the English ones, not `maquina`/`usuario`/`criado_em`/`atualizado_em`."""
    create_lock(tmp_path)
    dados = json.loads(lock_path(tmp_path).read_text(encoding="utf-8"))
    assert set(dados.keys()) == {"machine", "user", "created_at", "updated_at"}


def test_ler_trava_ausente_devolve_none(tmp_path):
    assert read_lock(tmp_path) is None


def test_verificar_trava_livre_quando_nao_existe(tmp_path):
    resultado = check_lock(tmp_path)
    assert resultado.status == "free"


def test_verificar_trava_propria_maquina(tmp_path):
    maquina_atual, usuario_atual = lock_mod.machine_identity()
    _escrever_trava_manual(tmp_path, maquina_atual, usuario_atual, minutos_atras=2)
    resultado = check_lock(tmp_path)
    assert resultado.status == "same_machine"


def test_verificar_trava_bloqueada_para_maquina_diferente_recente(tmp_path):
    _escrever_trava_manual(tmp_path, "NOTEBOOK-OUTRA-MAQUINA", "outro.usuario", minutos_atras=3)
    resultado = check_lock(tmp_path)
    assert resultado.status == "blocked"
    # A mensagem virou chave + parâmetros para que as três telas de trava
    # sigam o idioma da interface. Cobrar os parâmetros é mais forte que
    # cobrar o texto: prova que máquina e usuário chegam a quem renderiza,
    # em qualquer idioma.
    assert resultado.message_key == "lock.blocked"
    assert resultado.message_params["machine"] == "NOTEBOOK-OUTRA-MAQUINA"
    assert resultado.message_params["user"] == "outro.usuario"
    assert translate("en", resultado.message_key, **resultado.message_params).startswith("Machine")


def test_verificar_trava_abandonada_para_maquina_diferente_antiga(tmp_path):
    _escrever_trava_manual(tmp_path, "NOTEBOOK-OUTRA-MAQUINA", "outro.usuario", minutos_atras=15)
    resultado = check_lock(tmp_path)
    assert resultado.status == "abandoned"
    assert resultado.message_key == "lock.abandoned"
    assert resultado.message_params["machine"] == "NOTEBOOK-OUTRA-MAQUINA"
    assert "confirme" in translate("pt", resultado.message_key, **resultado.message_params).lower()


def test_atualizar_trava_preserva_identidade_e_avanca_relogio(tmp_path):
    original = create_lock(tmp_path)
    time.sleep(1.1)
    atualizada = refresh_lock(tmp_path, original)
    assert atualizada.machine == original.machine
    assert atualizada.created_at == original.created_at
    assert atualizada.updated_at != original.updated_at


def test_remover_trava(tmp_path):
    create_lock(tmp_path)
    assert lock_path(tmp_path).exists()
    remove_lock(tmp_path)
    assert not lock_path(tmp_path).exists()
    remove_lock(tmp_path)  # remover de novo não deve levantar erro


def test_trava_corrompida_e_tratada_como_ausente(tmp_path):
    lock_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    lock_path(tmp_path).write_text("isto nao e json", encoding="utf-8")
    assert read_lock(tmp_path) is None
    assert check_lock(tmp_path).status == "free"


# --- LockManager: heartbeat e liberação -------------------------------


def test_gerenciador_travas_abre_e_o_heartbeat_atualiza(tmp_path):
    gerenciador = LockManager(heartbeat_interval_s=0.05)
    gerenciador.open(tmp_path)
    trava_inicial = read_lock(tmp_path)

    time.sleep(0.2)

    trava_depois = read_lock(tmp_path)
    assert trava_depois.updated_at >= trava_inicial.updated_at
    assert trava_depois.created_at == trava_inicial.created_at

    gerenciador.close_all()


def test_gerenciador_travas_fechar_tudo_remove_o_arquivo(tmp_path):
    gerenciador = LockManager(heartbeat_interval_s=5)
    gerenciador.open(tmp_path)
    assert lock_path(tmp_path).exists()

    gerenciador.close_all()

    assert not lock_path(tmp_path).exists()


def test_gerenciador_travas_esta_aberta(tmp_path):
    gerenciador = LockManager(heartbeat_interval_s=5)
    assert gerenciador.is_open(tmp_path) is False
    gerenciador.open(tmp_path)
    assert gerenciador.is_open(tmp_path) is True
    gerenciador.close_all()


# --- sync.py --------------------------------------------------------


def test_checar_sincronizacao_ok_quando_banco_nao_existe(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.sync.machine_local_folder", lambda: tmp_path / "local")
    resultado = check_sync(tmp_path / "projeto_sem_banco")
    assert resultado.ok is True


def test_checar_sincronizacao_ok_na_primeira_vez_e_registra(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.sync.machine_local_folder", lambda: tmp_path / "local")
    pasta_saida = tmp_path / "saida"
    pasta_saida.mkdir()
    (pasta_saida / "project.db").write_bytes(b"fake")

    resultado = check_sync(pasta_saida)
    assert resultado.ok is True

    mark_synced(pasta_saida)
    resultado2 = check_sync(pasta_saida)
    assert resultado2.ok is True


def test_checar_sincronizacao_detecta_arquivo_mais_antigo(tmp_path, monkeypatch):
    monkeypatch.setattr("gclaude_indexer.sync.machine_local_folder", lambda: tmp_path / "local")
    pasta_saida = tmp_path / "saida"
    pasta_saida.mkdir()
    caminho_banco = pasta_saida / "project.db"
    caminho_banco.write_bytes(b"fake")

    mark_synced(pasta_saida)

    # simula um arquivo que "voltou no tempo" — sincronização incompleta
    tempo_passado = (datetime.now() - timedelta(minutes=5)).timestamp()
    import os

    os.utime(caminho_banco, (tempo_passado, tempo_passado))

    resultado = check_sync(pasta_saida)
    assert resultado.ok is False
    assert resultado.message_key == "sync.incomplete"
    assert "sincroniz" in translate("pt", resultado.message_key).lower()
    assert "sync" in translate("en", resultado.message_key).lower()


# --- iniciador.py ------------------------------------------------------------


def test_iniciador_hash_arquivo_muda_com_o_conteudo(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import launcher

    caminho = tmp_path / "requirements.txt"
    caminho.write_text("fastapi==0.115.0\n", encoding="utf-8")
    hash_antes = launcher._hash_arquivo(caminho)
    assert hash_antes == launcher._hash_arquivo(caminho)  # determinístico

    caminho.write_text("fastapi==0.115.1\n", encoding="utf-8")
    assert launcher._hash_arquivo(caminho) != hash_antes


def test_iniciador_so_reinstala_quando_hash_muda(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import launcher

    chamadas = []
    monkeypatch.setattr(
        launcher, "run_hidden",
        lambda comando, timeout=None: chamadas.append(comando) or type("R", (), {"returncode": 0, "stderr": ""})(),
    )

    caminho_requirements = tmp_path / "requirements.txt"
    caminho_requirements.write_text("fastapi==0.115.0\n", encoding="utf-8")
    caminho_hash = tmp_path / "hash.txt"
    pasta_venv = tmp_path / "venv"

    mudou1 = launcher._garantir_dependencias(pasta_venv, caminho_requirements, caminho_hash)
    assert mudou1 is True
    assert len(chamadas) == 1

    mudou2 = launcher._garantir_dependencias(pasta_venv, caminho_requirements, caminho_hash)
    assert mudou2 is False
    assert len(chamadas) == 1  # não rodou pip install de novo

    caminho_requirements.write_text("fastapi==0.116.0\n", encoding="utf-8")
    mudou3 = launcher._garantir_dependencias(pasta_venv, caminho_requirements, caminho_hash)
    assert mudou3 is True
    assert len(chamadas) == 2


def test_iniciador_python_do_venv_windows(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import launcher

    if sys.platform == "win32":
        assert launcher._python_do_venv(tmp_path).name == "python.exe"
        assert "Scripts" in str(launcher._python_do_venv(tmp_path))


# --- integração web: bloqueio real na tela de Execução ----------------------


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr("gclaude_indexer.sync.machine_local_folder", lambda: pasta_local)

    from gclaude_indexer.web.app import app, lock_manager

    lock_manager.close_all()  # começa cada teste sem travas residuais
    yield TestClient(app)
    lock_manager.close_all()


def _criar_projeto_web(cliente, tmp_path, nome="Projeto Trava"):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "saida"
    _pdf(origem / "volume_1" / "peca.pdf", "OFÍCIO No 1\nAssunto: teste de trava, com texto suficiente.\n10/01/2024")

    resposta = cliente.post(
        "/projects/new",
        data={
            "name": nome, "subject": "x", "source_folder": str(origem), "output_folder": str(saida),
            "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
            "extensions": ["pdf"], "pages_per_block": "80", "pages_per_window": "16",
            "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
            "classification_engine": "rules", "local_model": "automatic",
            "role_instructions": "", "extra_rules": "",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    projeto_id = int(resposta.headers["location"].split("/")[2])
    return projeto_id, saida


def test_web_recusa_abertura_com_trava_de_outra_maquina_recente(cliente, tmp_path):
    projeto_id, saida = _criar_projeto_web(cliente, tmp_path)
    _escrever_trava_manual(saida, "PC-DA-OUTRA-SALA", "colega", minutos_atras=1)

    resposta = cliente.get(f"/projects/{projeto_id}/run")

    assert resposta.status_code == 423
    assert "PC-DA-OUTRA-SALA" in resposta.text
    assert "colega" in resposta.text


def test_web_trava_abandonada_pede_confirmacao_e_depois_libera(cliente, tmp_path):
    projeto_id, saida = _criar_projeto_web(cliente, tmp_path)
    _escrever_trava_manual(saida, "PC-ANTIGO", "ex.usuario", minutos_atras=20)

    bloqueado = cliente.get(f"/projects/{projeto_id}/run")
    assert bloqueado.status_code == 409
    assert "Assumir mesmo assim" in bloqueado.text
    assert "PC-ANTIGO" in bloqueado.text

    assumir = cliente.post(f"/projects/{projeto_id}/take-lock", follow_redirects=False)
    assert assumir.status_code == 303

    depois = cliente.get(f"/projects/{projeto_id}/run")
    assert depois.status_code == 200

    trava_atual = read_lock(saida)
    maquina_atual, _ = lock_mod.machine_identity()
    assert trava_atual.machine == maquina_atual


def test_web_aviso_fixo_de_troca_de_maquina_aparece(cliente):
    resposta = cliente.get("/projects")
    assert "feche este aplicativo" in resposta.text.lower()


def test_web_sincronizacao_incompleta_pede_confirmacao(cliente, tmp_path):
    import os

    projeto_id, saida = _criar_projeto_web(cliente, tmp_path)
    mark_synced(saida)

    tempo_passado = (datetime.now() - timedelta(minutes=5)).timestamp()
    os.utime(saida / "project.db", (tempo_passado, tempo_passado))

    resposta = cliente.get(f"/projects/{projeto_id}/run")
    assert resposta.status_code == 409
    assert "Continuar mesmo assim" in resposta.text

    continuar = cliente.post(f"/projects/{projeto_id}/continue-anyway", follow_redirects=False)
    assert continuar.status_code == 303

    depois = cliente.get(f"/projects/{projeto_id}/run")
    assert depois.status_code == 200

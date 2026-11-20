"""Registros JSON por máquina (sincronização, catálogo, conjuntos,
preferências, mudança de pasta) e a identidade de pasta que eles usam."""

from __future__ import annotations

import pytest

from gclaude_indexer import paths, sync


@pytest.fixture
def pasta_local(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(local))
    monkeypatch.setattr("gclaude_indexer.sync.machine_local_folder", lambda: local)
    return local


def _projeto(tmp_path, nome="Saida"):
    pasta = tmp_path / nome
    pasta.mkdir()
    (pasta / paths.PROJECT_DB_NAME).write_bytes(b"")
    return pasta


@pytest.mark.parametrize(
    "estragar",
    [
        # Uma pasta no lugar do arquivo: `read_text` levanta `PermissionError`
        # no Windows (`IsADirectoryError` noutros sistemas), os dois `OSError`.
        lambda caminho: caminho.mkdir(),
        lambda caminho: caminho.write_bytes(b"\xff\xfe\x00{"),
        lambda caminho: caminho.write_text("[1, 2]", encoding="utf-8"),
    ],
    ids=["ilegivel", "nao_utf8", "nao_objeto"],
)
def test_sincronizacao_ilegivel_nao_impede_abrir(tmp_path, pasta_local, estragar):
    estragar(pasta_local / sync.REGISTRY_FILE_NAME)
    saida = _projeto(tmp_path)

    assert sync.check_sync(saida).ok
    sync.mark_synced(saida)  # gravar também não pode derrubar a abertura
    assert sync.check_sync(saida).ok


def test_sincronizacao_sem_espaco_ao_gravar_nao_impede_abrir(tmp_path, pasta_local, monkeypatch):
    saida = _projeto(tmp_path)

    def disco_cheio(_registro):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(sync, "_write_registry", disco_cheio)
    sync.mark_synced(saida)
    assert sync.check_sync(saida).ok

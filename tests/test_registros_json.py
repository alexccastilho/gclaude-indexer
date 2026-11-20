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


# --- gravação atômica -----------------------------------------------------------


def _replace_que_falha(*_args, **_kwargs):
    raise PermissionError(13, "Acesso negado")


def _gravar_catalogo(local, tmp_path):
    from gclaude_indexer import catalog

    catalog.register_project("Novo", str(tmp_path / "Novo-AI"))


def _gravar_conjunto(local, tmp_path):
    from gclaude_indexer import sets

    sets.save_set(sets.SetEntry(id=0, name="Novo"))


def _gravar_preferencia(local, tmp_path):
    from gclaude_indexer import settings

    settings.set_shared_catalog_folder("")


def _gravar_sincronizacao(local, tmp_path):
    sync._write_registry({"novo": 1.0})


@pytest.mark.parametrize(
    "arquivo, gravar",
    [
        ("projects.json", _gravar_catalogo),
        ("sets.json", _gravar_conjunto),
        ("settings.json", _gravar_preferencia),
        (sync.REGISTRY_FILE_NAME, _gravar_sincronizacao),
    ],
    ids=["catalogo", "conjuntos", "preferencias", "sincronizacao"],
)
def test_registro_que_falha_ao_gravar_fica_inteiro(tmp_path, pasta_local, monkeypatch, arquivo, gravar):
    """Uma gravação que não termina deixa o arquivo antigo como estava: o
    texto novo vai para um temporário e só troca de lugar no fim."""
    from gclaude_indexer import catalog

    monkeypatch.setattr(catalog, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr("gclaude_indexer.sets.machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr("gclaude_indexer.settings.machine_local_folder", lambda: pasta_local)
    if arquivo == "projects.json":
        assert catalog.CATALOG_FILE_NAME == arquivo
    antigo = "[]" if arquivo in ("projects.json", "sets.json") else "{}"
    (pasta_local / arquivo).write_text(antigo, encoding="utf-8")
    monkeypatch.setattr(paths, "_REPLACE_RETRY_SECONDS", ())
    monkeypatch.setattr(paths.os, "replace", _replace_que_falha)

    with pytest.raises(PermissionError):
        gravar(pasta_local, tmp_path)

    assert (pasta_local / arquivo).read_text(encoding="utf-8") == antigo
    assert not (pasta_local / (arquivo + ".tmp")).exists()


def test_gravacoes_simultaneas_nao_falham(tmp_path):
    """As rotas rodam em várias threads: antes, duas gravações dividiam o
    `.tmp` e quase todas falhavam."""
    import threading

    alvo = tmp_path / "registro.json"
    alvo.write_text("{}", encoding="utf-8")
    erros: list[BaseException] = []

    def gravar(n):
        for i in range(20):
            try:
                paths.write_text_atomic(alvo, '{"n": %d, "i": %d}' % (n, i))
            except OSError as exc:
                erros.append(exc)

    gravadores = [threading.Thread(target=gravar, args=(n,)) for n in range(4)]
    for thread in gravadores:
        thread.start()
    for thread in gravadores:
        thread.join()

    assert erros == []
    assert alvo.read_text(encoding="utf-8").startswith('{"n": ')


def test_gravacao_espera_leitor_que_segura_o_arquivo(tmp_path):
    """No NTFS, `os.replace` sobre um arquivo aberto para leitura falha;
    `write_text` não falhava. A gravação espera o leitor soltar."""
    import threading

    alvo = tmp_path / "registro.json"
    alvo.write_text("{}", encoding="utf-8")
    leitor = open(alvo, encoding="utf-8")
    threading.Timer(0.05, leitor.close).start()

    paths.write_text_atomic(alvo, '{"novo": true}')

    assert alvo.read_text(encoding="utf-8") == '{"novo": true}'

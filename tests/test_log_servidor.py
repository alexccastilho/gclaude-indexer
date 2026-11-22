"""2.1.3: o `servidor.log` crescia sem limite.

O servidor sem console grava stdout e stderr em `servidor.log`, aberto em
modo de acréscimo a cada início. A tela de Execução consulta o servidor
cinco vezes a cada 2 s, e cada consulta deixa uma linha de acesso: numa
máquina em uso o arquivo passou de 19 MB.
"""

from __future__ import annotations

from gclaude_indexer import server_log


def test_log_pequeno_continua_no_mesmo_arquivo(tmp_path):
    (tmp_path / "servidor.log").write_text("linha antiga\n", encoding="utf-8")
    with server_log.open_server_log(tmp_path) as log:
        log.write("linha nova\n")
    assert (tmp_path / "servidor.log").read_text(encoding="utf-8") == "linha antiga\nlinha nova\n"
    assert not (tmp_path / "servidor.log.1").exists()


def test_log_grande_vira_o_anterior_e_comeca_outro(tmp_path):
    (tmp_path / "servidor.log").write_text("x" * (server_log.MAX_BYTES + 1), encoding="utf-8")
    (tmp_path / "servidor.log.1").write_text("o anterior do anterior", encoding="utf-8")
    with server_log.open_server_log(tmp_path) as log:
        log.write("começo\n")
    assert (tmp_path / "servidor.log").read_text(encoding="utf-8") == "começo\n"
    assert (tmp_path / "servidor.log.1").stat().st_size == server_log.MAX_BYTES + 1


def test_pasta_inexistente_e_criada(tmp_path):
    pasta = tmp_path / "GClaudeIndexer"
    with server_log.open_server_log(pasta) as log:
        log.write("ok\n")
    assert (pasta / "servidor.log").exists()

"""O campo `files` de uma peça é gravado com ", " entre os nomes
(`raw_items.files_field`); quem lê precisa dividir pelo mesmo separador."""

from __future__ import annotations

from gclaude_indexer import artifacts, planalto
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.raw_items import files_field


def _projeto(tmp_path):
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Campo files",
        "source_folder": str(tmp_path / "origem"),
        "output_folder": str(saida),
        "extensions": ["pdf"],
    })
    conn = connect(saida / "project.db")
    init_schema(conn)
    return config, conn


def _arquivo(conn, nome, caminho, grupo="g1"):
    extensao = nome.rsplit(".", 1)[-1]
    cursor = conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status)"
        " VALUES (?, ?, ?, 1, 'x', ?, 'extracted')",
        (caminho, nome, extensao, grupo),
    )
    return cursor.lastrowid


def _peca(conn, arquivos, engine="rules", grupo="g1"):
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, type, date, author, summary,"
        " has_table, has_image, engine, confidence, files) VALUES (?, 'f. 1', 'f. 2', 1, 2, 'LEI',"
        " '2020-01-02', 'Fulano', 'Resumo', 0, 0, ?, 'high', ?)",
        (grupo, engine, files_field(arquivos)),
    )


def test_primeiro_arquivo_de_uma_peca_com_varios_arquivos():
    assert artifacts._first_file(files_field(["a.htm", "b.htm"])) == "a.htm"
    assert artifacts._first_file("a.htm") == "a.htm"
    assert artifacts._first_file(None) == ""


def test_ato_de_varios_arquivos_ainda_marca_seu_primeiro_arquivo_como_legislacao(tmp_path):
    config, conn = _projeto(tmp_path)
    _arquivo(conn, "lei.htm", "Legislacao/lei.htm")
    _arquivo(conn, "anexo.htm", "Legislacao/anexo.htm")
    _peca(conn, ["lei.htm", "anexo.htm"], engine=planalto.ENGINE)
    conn.commit()

    e_legislacao = artifacts.legislation_file_test(conn)

    assert e_legislacao("g1", "lei.htm")
    conn.close()


def test_assinatura_do_segundo_arquivo_da_peca_aparece_na_coluna_origem(tmp_path):
    config, conn = _projeto(tmp_path)
    _arquivo(conn, "capa.pdf", "capa.pdf")
    assinado = _arquivo(conn, "contrato.pdf", "contrato.pdf")
    conn.execute(
        "INSERT INTO file_signature (file_id, signer, holder_document, signed_at, source)"
        " VALUES (?, 'FULANO DE TAL', NULL, NULL, 'p7m')",
        (assinado,),
    )
    _peca(conn, ["capa.pdf", "contrato.pdf"])
    conn.commit()

    caminhos = artifacts.generate_index_md(conn, config, "pt-BR")

    texto = "\n".join(caminho.read_text(encoding="utf-8") for caminho in caminhos)
    assert "assinado por FULANO DE TAL" in texto
    conn.close()

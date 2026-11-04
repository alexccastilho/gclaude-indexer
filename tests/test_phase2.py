"""Phase 2 tests: source-folder scan, grouping and duplicate detection."""

from __future__ import annotations

from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.scanning import compute_hash, derive_group_key, scan


def _criar_acervo_exemplo(base):
    origem = base / "origem"
    (origem / "volume_1").mkdir(parents=True)
    (origem / "volume_2").mkdir(parents=True)

    (origem / "volume_1" / "peca1.pdf").write_bytes(b"%PDF-1.4 conteudo simulado de pdf")
    (origem / "volume_1" / "peca2.docx").write_bytes(b"PK conteudo simulado de docx")
    (origem / "volume_2" / "planilha.xlsx").write_bytes(b"PK conteudo simulado de xlsx")
    (origem / "volume_2" / "apresentacao.pptx").write_bytes(b"PK conteudo simulado de pptx")
    (origem / "volume_2" / "nota.txt").write_text("nota em texto simples", encoding="utf-8")
    (origem / "volume_2" / "leiame.md").write_text("# leia-me", encoding="utf-8")
    (origem / "volume_2" / "foto.jpg").write_bytes(b"\xff\xd8\xff conteudo simulado de jpg")
    (origem / "volume_2" / "scan.png").write_bytes(b"\x89PNG conteudo simulado de png")
    (origem / "volume_2" / "mensagem.eml").write_text("From: a@b.com\n\nolá", encoding="utf-8")
    (origem / "arquivo_desconhecido.xyz").write_bytes(b"formato nao suportado")

    return origem


def _config_exemplo(origem, saida):
    return load_config(
        {
            "name": "Acervo de Teste",
            "source_folder": str(origem),
            "output_folder": str(saida),
            "extensions": ["pdf", "docx", "xlsx", "pptx", "imagens", "text", "email"],
        }
    )


def test_calcular_hash_e_estavel(tmp_path):
    arquivo = tmp_path / "x.txt"
    arquivo.write_text("mesmo conteúdo", encoding="utf-8")
    assert compute_hash(arquivo) == compute_hash(arquivo)


def test_derivar_agrupador_subpasta(tmp_path):
    config = load_config(
        {"name": "X", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "saida")}
    )
    assert derive_group_key("volume_1/peca1.pdf", tmp_path, config) == "volume_1"
    assert derive_group_key("solto.pdf", tmp_path, config) == tmp_path.name


def test_derivar_agrupador_tudo_junto(tmp_path):
    config = load_config(
        {
            "name": "X",
            "source_folder": str(tmp_path),
            "output_folder": str(tmp_path / "saida"),
            "group_mode": "all_together",
        }
    )
    assert derive_group_key("volume_1/peca1.pdf", tmp_path, config) == tmp_path.name


def test_derivar_agrupador_padrao_nome(tmp_path):
    config = load_config(
        {
            "name": "X",
            "source_folder": str(tmp_path),
            "output_folder": str(tmp_path / "saida"),
            "group_mode": "name_pattern",
            "group_pattern": r"^(proc\d+)",
        }
    )
    assert derive_group_key("proc42_pag1.pdf", tmp_path, config) == "proc42"
    assert derive_group_key("sem_padrao.pdf", tmp_path, config) is None


def test_varrer_inventario_e_ignorados(tmp_path):
    origem = _criar_acervo_exemplo(tmp_path)
    saida = tmp_path / "origem_indexado"
    saida.mkdir()
    config = _config_exemplo(origem, saida)

    conn = connect(saida / "project.db")
    init_schema(conn)

    resultado = scan(conn, config)

    assert resultado.total_found == 10
    assert resultado.discovered == 9
    assert resultado.ignored == 1
    assert resultado.skipped == 0

    linhas = conn.execute("SELECT * FROM file ORDER BY relative_path").fetchall()
    assert len(linhas) == 10

    por_nome = {linha["name"]: linha for linha in linhas}

    assert por_nome["peca1.pdf"]["status"] == "discovered"
    assert por_nome["peca1.pdf"]["group_key"] == "volume_1"
    assert por_nome["peca1.pdf"]["extension"] == "pdf"

    ignorado = por_nome["arquivo_desconhecido.xyz"]
    assert ignorado["status"] == "skipped"
    assert ignorado["group_key"] is None

    eventos = list_events(conn, step="scan")
    mensagens = [e["message"] for e in eventos]
    assert any("arquivo_desconhecido.xyz" in m and "ignorado" in m for m in mensagens)
    assert any("varredura concluída" in m for m in mensagens)

    conn.close()


def test_varrer_com_extensoes_padrao_ignora_o_que_nao_esta_na_lista(tmp_path):
    origem = _criar_acervo_exemplo(tmp_path)
    saida = tmp_path / "origem_indexado"
    saida.mkdir()
    # Config sem "extensions" explícito usa o padrão da seção 6: pdf, docx, imagens.
    config = load_config(
        {"name": "Acervo de Teste", "source_folder": str(origem), "output_folder": str(saida)}
    )

    conn = connect(saida / "project.db")
    init_schema(conn)

    resultado = scan(conn, config)

    # pdf, docx, jpg, png => 4 incluídos; xlsx, pptx, txt, md, eml, xyz => 6 ignorados
    assert resultado.discovered == 4
    assert resultado.ignored == 6

    conn.close()


def test_varrer_e_idempotente(tmp_path):
    origem = _criar_acervo_exemplo(tmp_path)
    saida = tmp_path / "origem_indexado"
    saida.mkdir()
    config = _config_exemplo(origem, saida)

    conn = connect(saida / "project.db")
    init_schema(conn)

    scan(conn, config)
    total_apos_primeira = conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]

    resultado_segunda = scan(conn, config)

    assert resultado_segunda.discovered == 0
    assert resultado_segunda.ignored == 0
    assert resultado_segunda.skipped == 10
    assert conn.execute("SELECT COUNT(*) FROM file").fetchone()[0] == total_apos_primeira

    conn.close()


def test_varrer_processa_so_arquivo_novo(tmp_path):
    origem = _criar_acervo_exemplo(tmp_path)
    saida = tmp_path / "origem_indexado"
    saida.mkdir()
    config = _config_exemplo(origem, saida)

    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)

    (origem / "volume_1" / "peca3_nova.pdf").write_bytes(b"%PDF conteudo novo, nunca visto")

    resultado = scan(conn, config)

    assert resultado.discovered == 1
    assert resultado.skipped == 10

    nova = conn.execute(
        "SELECT * FROM file WHERE name = ?", ("peca3_nova.pdf",)
    ).fetchone()
    assert nova is not None
    assert nova["status"] == "discovered"

    conn.close()


def test_varrer_nao_indexa_pasta_de_saida(tmp_path):
    origem = _criar_acervo_exemplo(tmp_path)
    saida = origem / "_indexado"
    saida.mkdir()
    (saida / "gerado.pdf").write_bytes(b"artefato gerado, nao deve ser varrido")

    config = _config_exemplo(origem, saida)
    conn = connect(saida / "project.db")
    init_schema(conn)

    resultado = scan(conn, config)

    assert resultado.total_found == 10  # não conta o "gerado.pdf" dentro de _indexado
    nomes = {linha["name"] for linha in conn.execute("SELECT name FROM file").fetchall()}
    assert "gerado.pdf" not in nomes

    conn.close()

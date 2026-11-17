"""2.0.0, tarefa 3: o que pode ser indexado, atalhos do Google, mídia e o
padrão de extensões. Uma regra só (`file_types.index_decision`) decide, antes
do hash, e o arquivo ignorado fica no inventário com o motivo."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from gclaude_indexer import scanning, update_plan
from gclaude_indexer.config import ProjectConfig, load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.file_types import (
    has_private_key_marker,
    index_decision,
    is_extension_allowed,
    normalize_categories,
)
from gclaude_indexer.scanning import scan


def _config(origem: Path, saida: Path, extensions=None) -> ProjectConfig:
    dados = {"name": "P", "source_folder": str(origem), "output_folder": str(saida)}
    if extensions is not None:
        dados["extensions"] = extensions
    return load_config(dados)


def _banco(saida: Path):
    saida.mkdir(parents=True, exist_ok=True)
    conn = connect(saida / "project.db")
    init_schema(conn)
    return conn


# --- decisão -----------------------------------------------------------------


@pytest.mark.parametrize("nome, motivo", [
    ("desktop.ini", "system"),
    ("Thumbs.db", "system"),
    ("ata.gdoc", "google_doc"),
    ("planilha.GSHEET", "google_doc"),
    ("a.gslides", "google_doc"),
    ("a.gjam", "google_doc"),
    ("pasta.zip", "archive"),
    ("pasta.7z", "archive"),
    ("pasta.tar", "archive"),
    ("pasta.tgz", "archive"),
    ("programa.exe", "blocked_extension"),
    ("banco.sqlite", "blocked_extension"),
    ("banco.mdb", "blocked_extension"),
    ("fonte.ttf", "blocked_extension"),
    ("fonte.woff2", "blocked_extension"),
    ("planta.dwg", "blocked_extension"),
    ("disco.iso", "blocked_extension"),
    ("filme.mp4", "media_not_selected"),
    ("som.MP3", "media_not_selected"),
    ("cert.pfx", "secret"),
    ("chave.pem", "secret"),
    ("cofre.kdbx", "secret"),
    (".env", "secret"),
    ("id_rsa", "secret"),
    ("id_rsa.pub", "secret"),
    ("id_ed25519", "secret"),
])
def test_motivo_decidido_so_pelo_nome(nome, motivo):
    # Sem bytes: nada foi lido, e mesmo assim o motivo é conhecido.
    assert index_decision(nome, None) == motivo


@pytest.mark.parametrize("nome", ["a.pdf", "a.docx", "nota.txt", "dados.xyz", "sem_extensao"])
def test_o_que_pode_ser_indexado_segue(nome):
    assert index_decision(nome, b"texto comum de um documento") is None


def test_ordem_das_regras_google_antes_de_compactado_e_bloqueado():
    # O nome decide na ordem do contrato: o primeiro motivo que casa vence.
    assert index_decision("x.gdoc", b"-----BEGIN PRIVATE KEY-----\n...PRIVATE KEY-----") == "google_doc"
    assert index_decision("x.zip", b"\x00\x01") == "archive"


def test_marcador_de_chave_privada_no_inicio_e_segredo():
    chave = b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"
    assert index_decision("notas.txt", chave) == "secret"
    # Marcador de certificado público não é chave privada.
    assert index_decision("cert.txt", b"-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----") is None


def test_extensao_desconhecida_com_byte_nulo_e_binaria():
    assert index_decision("dados.xyz", b"abc\x00def") == "binary"


def test_extensao_desconhecida_com_muito_controle_e_binaria():
    assert index_decision("dados.xyz", bytes([1, 2, 3, 4, 5, 6, 7, 8] * 20) + b"abc") == "binary"


@pytest.mark.parametrize("codificacao", ["utf-16", "utf-32", "utf-8-sig"])
def test_texto_com_bom_nao_e_binario(codificacao):
    conteudo = "Documento em português, ação e informação.".encode(codificacao)
    assert b"\x00" in conteudo or codificacao == "utf-8-sig"
    assert index_decision("texto.xyz", conteudo) is None


def test_extensao_conhecida_nao_passa_pelo_teste_de_binario():
    # Um .docx é um zip (cheio de bytes de controle) e é documento.
    assert index_decision("a.docx", b"PK\x03\x04\x00\x00\x00") is None


def test_so_os_primeiros_8192_bytes_contam():
    cabeca = b"a" * 8192
    assert index_decision("dados.xyz", cabeca + b"\x00" * 100) is None


# --- padrão e normalização -----------------------------------------------------


def test_padrao_novo_de_extensoes_e_todos():
    assert ProjectConfig(name="x", source_folder="a", output_folder="b").extensions == ["all"]


def test_todos_nao_cobre_midia_mas_cobre_o_resto():
    assert is_extension_allowed(".xyz", ["all"])
    assert not is_extension_allowed(".mp4", ["all"])
    assert not is_extension_allowed(".mp3", ["all"])
    assert is_extension_allowed(".mp4", ["all", "midia"])
    assert is_extension_allowed(".mp3", ["midia"])
    assert not is_extension_allowed(".pdf", ["midia"])


def test_normaliza_todos_mais_categorias_especificas():
    assert normalize_categories(["all", "pdf", "docx"]) == ["all"]
    assert normalize_categories(["pdf", "all", "midia"]) == ["all", "midia"]
    assert normalize_categories(["pdf", "docx"]) == ["pdf", "docx"]
    assert normalize_categories(["midia"]) == ["midia"]


def test_formulario_novo_traz_tudo_marcado_menos_midia():
    from fastapi.testclient import TestClient

    from gclaude_indexer.web.app import app

    import re

    corpo = TestClient(app).get("/projects/new").text
    entradas = re.findall(r'<input type="checkbox" name="extensions" value="([^"]+)"([^>]*)>', corpo)
    marcadas = {valor for valor, resto in entradas if "checked" in resto}
    # Todas as específicas aparecem marcadas junto com TODOS; só a mídia (opt-in) não.
    assert "all" in marcadas and "pdf" in marcadas
    assert marcadas == {valor for valor, _ in entradas} - {"midia"}
    assert "midia" in {valor for valor, _ in entradas}


# --- varredura -----------------------------------------------------------------


def _acervo(origem: Path) -> None:
    origem.mkdir(parents=True)
    (origem / "ata.txt").write_text("ata da reunião", encoding="utf-8")
    (origem / "doc.gdoc").write_text('{"url": "https://docs.google.com/document/d/x"}', encoding="utf-8")
    (origem / "tudo.zip").write_bytes(b"PK\x03\x04conteudo")
    (origem / "filme.mp4").write_bytes(b"\x00\x00\x00 ftypmp42")
    (origem / "cert.pem").write_text("-----BEGIN PRIVATE KEY-----\nSEGREDO\n-----END PRIVATE KEY-----", encoding="utf-8")
    (origem / "dados.xyz").write_bytes(b"\x00\x01\x02binario")


def test_varredura_registra_cada_motivo_e_nao_cria_coluna(tmp_path):
    origem = tmp_path / "origem"
    _acervo(origem)
    conn = _banco(tmp_path / "saida")
    resultado = scan(conn, _config(origem, tmp_path / "saida", ["all"]))

    linhas = {r["name"]: r for r in conn.execute("SELECT * FROM file")}
    assert linhas["ata.txt"]["status"] == "discovered"
    for nome, motivo in [
        ("doc.gdoc", "google_doc"), ("tudo.zip", "archive"), ("filme.mp4", "media_not_selected"),
        ("cert.pem", "secret"), ("dados.xyz", "binary"),
    ]:
        assert linhas[nome]["status"] == "skipped", nome
        assert linhas[nome]["error"] == motivo, nome
        assert linhas[nome]["group_key"] is None
        assert linhas[nome]["sha256"] == ""
    assert resultado.ignored == 5 and resultado.discovered == 1
    assert resultado.ignored_by_reason["google_doc"] == 1


def test_um_evento_resumo_por_execucao_e_aviso_de_google(tmp_path):
    origem = tmp_path / "origem"
    _acervo(origem)
    conn = _banco(tmp_path / "saida")
    scan(conn, _config(origem, tmp_path / "saida", ["all"]), language="pt")
    mensagens = [e["message"] for e in list_events(conn, step="scan")]
    resumos = [m for m in mensagens if "ignorado(s) por não poderem ser indexados" in m]
    assert len(resumos) == 1
    assert "5 arquivo(s)" in resumos[0] and "compactado: 1" in resumos[0]
    assert not any("doc.gdoc" in m for m in mensagens)
    google = [m for m in mensagens if "atalho(s) do Google Drive" in m]
    assert len(google) == 1 and "exporte" in google[0]


def test_arquivo_ignorado_por_nome_nao_e_lido(tmp_path, monkeypatch):
    origem = tmp_path / "origem"
    origem.mkdir()
    for nome in ("filme.mp4", "tudo.zip", "doc.gdoc", "banco.sqlite", "cert.pem", "grande.mkv"):
        (origem / nome).write_bytes(b"x" * 100)
    (origem / "ata.txt").write_text("ata", encoding="utf-8")
    conn = _banco(tmp_path / "saida")

    abertos: list[str] = []
    abrir_original = builtins.open

    def espiao(arquivo, *args, **kwargs):
        if isinstance(arquivo, (str, Path)):
            abertos.append(Path(arquivo).name)
        return abrir_original(arquivo, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", espiao)
    scan(conn, _config(origem, tmp_path / "saida", ["all"]))
    # O espião enxerga as leituras (ata.txt foi aberto, para o começo e para o
    # hash); nenhum dos recusados pelo nome foi aberto.
    assert "ata.txt" in abertos
    recusados = {"filme.mp4", "tudo.zip", "doc.gdoc", "banco.sqlite", "cert.pem", "grande.mkv"}
    assert recusados.isdisjoint(abertos)


def test_segredo_nao_entra_no_banco(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "anotacoes.txt").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nSEGREDO-NUNCA-GRAVAR\n-----END RSA PRIVATE KEY-----",
        encoding="utf-8",
    )
    (origem / "cert.pem").write_text("SEGREDO-NUNCA-GRAVAR", encoding="utf-8")
    saida = tmp_path / "saida"
    conn = _banco(saida)
    scan(conn, _config(origem, saida, ["all"]))
    assert {r["status"] for r in conn.execute("SELECT status FROM file")} == {"skipped"}
    assert {r["error"] for r in conn.execute("SELECT error FROM file")} == {"secret"}
    conn.commit()
    conn.close()
    brutos = b"".join(p.read_bytes() for p in saida.glob("project.db*"))
    assert b"SEGREDO-NUNCA-GRAVAR" not in brutos


def test_midia_so_entra_com_midia_marcada(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "aula.mp3").write_bytes(b"ID3\x00\x00")
    sem = _banco(tmp_path / "sem")
    scan(sem, _config(origem, tmp_path / "sem", ["all"]))
    assert sem.execute("SELECT status, error FROM file").fetchone()[:] == ("skipped", "media_not_selected")

    com = _banco(tmp_path / "com")
    scan(com, _config(origem, tmp_path / "com", ["all", "midia"]))
    linha = com.execute("SELECT status, error, sha256 FROM file").fetchone()
    assert linha["status"] == "discovered" and linha["error"] is None and linha["sha256"]


def test_segunda_varredura_nao_mexe_no_que_ja_foi_ignorado(tmp_path, monkeypatch):
    origem = tmp_path / "origem"
    _acervo(origem)
    saida = tmp_path / "saida"
    conn = _banco(saida)
    config = _config(origem, saida, ["all"])
    scan(conn, config)
    monkeypatch.setattr(scanning, "compute_hash", lambda p: pytest.fail(f"hash de {p}"))
    monkeypatch.setattr(scanning, "read_head", lambda p: pytest.fail(f"leu {p}"))
    segunda = scan(conn, config)
    assert segunda.ignored == 0 and segunda.skipped == 6


def test_arquivos_ignorados_nao_viram_duplicados_entre_si(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.zip").write_bytes(b"mesmo")
    (origem / "b.zip").write_bytes(b"mesmo")
    (origem / "c.gdoc").write_bytes(b"mesmo")
    conn = _banco(tmp_path / "saida")
    scan(conn, _config(origem, tmp_path / "saida", ["all"]))
    assert {r["status"] for r in conn.execute("SELECT status FROM file")} == {"skipped"}


# --- plano de atualização --------------------------------------------------------


def test_plano_nao_recalcula_hash_de_ignorado(tmp_path, monkeypatch):
    origem = tmp_path / "origem"
    _acervo(origem)
    saida = tmp_path / "saida"
    conn = _banco(saida)
    config = _config(origem, saida, ["all"])
    scan(conn, config)
    (origem / "tudo.zip").write_bytes(b"PK\x03\x04outro conteudo maior")
    chamados: list[Path] = []
    original = update_plan.compute_hash
    monkeypatch.setattr(update_plan, "compute_hash", lambda p: chamados.append(p) or original(p))
    mudancas, _sem_mudanca, _impressao = update_plan.detect_changes(conn, config)
    assert Path("tudo.zip") not in [Path(p.name) for p in chamados]
    assert [m for m in mudancas if m.relative_path == "tudo.zip"] == []


def test_arquivo_indexado_por_versao_antiga_e_agora_ignorado_sai_com_confirmacao(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "filme.mp4").write_bytes(b"x" * 10)
    (origem / "nota.txt").write_text("nota", encoding="utf-8")
    saida = tmp_path / "saida"
    conn = _banco(saida)
    config = _config(origem, saida, ["all"])
    stat = (origem / "filme.mp4").stat()
    # Como um 1.x com "TODOS" o deixou: lido, convertido, com hash.
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status) "
        "VALUES ('filme.mp4', 'filme.mp4', 'mp4', ?, 'abc', ?, 'converted')", (stat.st_size, stat.st_mtime),
    )
    conn.commit()
    mudancas, _n, _i = update_plan.detect_changes(conn, config)
    tipos = {(m.relative_path, m.kind) for m in mudancas}
    assert ("filme.mp4", "removed") in tipos
    assert ("nota.txt", "new") in tipos
    sem_remocao, _n, _i = update_plan.detect_changes(conn, config, include_removed=False)
    assert not [m for m in sem_remocao if m.kind == "removed"]


# --- review.md --------------------------------------------------------------------


def test_review_lista_ignorados_por_motivo_e_extensao(tmp_path):
    from gclaude_indexer.artifacts import generate_review_md

    origem = tmp_path / "origem"
    _acervo(origem)
    saida = tmp_path / "saida"
    conn = _banco(saida)
    config = _config(origem, saida, ["all"])
    scan(conn, config)
    texto = generate_review_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "## Arquivos ignorados" in texto
    assert "atalho do Google Drive: 1" in texto
    assert ".gdoc: 1" in texto and "`doc.gdoc`" in texto
    assert "exporte-os para DOCX, XLSX ou PDF" in texto
    assert "SEGREDO" not in texto


# --- conversão ----------------------------------------------------------------------


def test_conversao_de_extensao_desconhecida_le_so_o_comeco_para_decidir(tmp_path, monkeypatch):
    from gclaude_indexer import conversion

    assert conversion.looks_binary(b"abc\x00") is True
    assert conversion.looks_binary("olá".encode("utf-16")) is False


def test_indexado_por_versao_antiga_nao_vira_ignorado_sem_invalidar(tmp_path):
    """Recusado só pelo nome mas já com páginas: a varredura não o troca por
    `skipped` por conta própria (ficariam páginas órfãs); o plano é que o tira,
    com confirmação."""
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "filme.mp4").write_bytes(b"x" * 10)
    saida = tmp_path / "saida"
    conn = _banco(saida)
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status) "
        "VALUES ('filme.mp4', 'filme.mp4', 'mp4', 1, 'abc', 1.0, 'extracted')"
    )
    conn.commit()
    resultado = scan(conn, _config(origem, saida, ["all"]))
    linha = conn.execute("SELECT status, sha256 FROM file").fetchone()
    assert (linha["status"], linha["sha256"]) == ("extracted", "abc")
    assert resultado.ignored == 0


def test_post_novo_projeto_normaliza_todos_mais_especificas(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gclaude_indexer.project import load_project
    from gclaude_indexer.web.app import app

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    dados = {
        "name": "Norm", "subject": "x", "source_folder": str(origem), "output_folder": str(saida),
        "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
        "extensions": ["all", "pdf", "midia"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "gemma4:e4b", "role_instructions": "",
    }
    resposta = TestClient(app).post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code in (302, 303), resposta.text[:300]
    config, conn = load_project(saida)
    conn.close()
    assert config.extensions == ["all", "midia"]


def test_cartao_da_varredura_mostra_os_ignorados(tmp_path):
    from gclaude_indexer.web.step_state import step_status

    origem = tmp_path / "origem"
    _acervo(origem)
    conn = _banco(tmp_path / "saida")
    scan(conn, _config(origem, tmp_path / "saida", ["all"]))
    etapas = step_status(conn, lambda chave: False)
    assert etapas[0]["vars"] == {"total": 6, "ignored": 5}


def test_indexado_cujo_conteudo_vira_chave_perde_paginas_busca_e_intermediario(tmp_path):
    """Já indexado como texto e depois reescrito como chave privada: numa
    varredura direta (sem o plano antes), o texto antigo sai do índice."""
    import os

    from gclaude_indexer.conversion import convert, converted_artifact_path
    from gclaude_indexer.extraction import extract_pages

    origem = tmp_path / "origem"
    origem.mkdir()
    alvo = origem / "notas.txt"
    alvo.write_text("TEXTO-ANTIGO-SIGILOSO sobre o contrato", encoding="utf-8")
    saida = tmp_path / "saida"
    conn = _banco(saida)
    config = _config(origem, saida, ["all"])
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0] >= 1
    artefato = converted_artifact_path(config.output_folder, "notas.txt", "txt", False)
    assert artefato is not None and artefato.exists()

    alvo.write_text(
        "-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----\n", encoding="utf-8"
    )
    os.utime(alvo, (1_000_000_000, 1_000_000_000))
    scan(conn, config)

    linha = conn.execute("SELECT status, error FROM file").fetchone()
    assert (linha["status"], linha["error"]) == ("skipped", "secret")
    assert conn.execute("SELECT COUNT(*) FROM page").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0] == 0
    assert not artefato.exists()


def test_chave_privada_pgp_tambem_e_segredo():
    """Revisão final: o marcador só casava `PRIVATE KEY-----`; a chave PGP
    termina em `PRIVATE KEY BLOCK-----` e entrava no índice."""
    chave = (
        b"-----BEGIN PGP PRIVATE KEY BLOCK-----\n\nlQOYBF0abc\n-----END PGP PRIVATE KEY BLOCK-----\n"
    )
    assert index_decision("chave.asc", chave) == "secret"
    assert has_private_key_marker(b"texto antes\n" + chave)
    # A chave pública PGP não é segredo.
    publica = b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nmQENBF0abc\n-----END PGP PUBLIC KEY BLOCK-----\n"
    assert index_decision("publica.txt", publica) is None

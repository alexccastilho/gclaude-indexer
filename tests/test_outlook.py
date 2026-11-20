# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Arquivos do Outlook (`.pst`, `.ost`) da 2.0.0, com um leitor simulado no
lugar do `libpff` (não existe gerador de `.pst` aqui): o leitor entrega
mensagens e anexos, e o resto (conversão, páginas, busca, retomada) é o de
verdade."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from gclaude_indexer import fulltext, ocr_languages, outlook, workdir
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.i18n import translate
from gclaude_indexer.outlook import PstMessage, sanitize_attachment_name
from gclaude_indexer.scanning import scan
from gclaude_indexer.workdir import PAGE_SEPARATOR


@dataclass
class Anexo:
    name: str
    data: bytes
    reads: list

    @property
    def size(self) -> int:
        return len(self.data)

    def read(self, limit: int) -> bytes:
        self.reads.append(self.name)
        return self.data[:limit]


class LeitorSimulado:
    def __init__(self, mensagens):
        self._mensagens = mensagens
        self.fechado = False
        self.unreadable = 0

    def messages(self):
        yield from self._mensagens

    def close(self):
        self.fechado = True


def _projeto(tmp_path, extensoes=("outlook",)):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Outlook", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": list(extensoes),
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


@pytest.fixture(autouse=True)
def _sem_idioma_faltando(monkeypatch):
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])


def _docx(texto: str) -> bytes:
    from docx import Document

    documento = Document()
    documento.add_paragraph(texto)
    saida = io.BytesIO()
    documento.save(saida)
    return saida.getvalue()


def _pdf(texto: str) -> bytes:
    import fitz

    documento = fitz.open()
    documento.new_page().insert_text((72, 72), texto)
    return documento.tobytes()


def _zip(nome: str, texto: str) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as arquivo:
        arquivo.writestr(nome, texto)
    return saida.getvalue()


def _paginas(conn, nome):
    return [
        row["text"] for row in conn.execute(
            "SELECT p.text AS text FROM page p JOIN file f ON f.id = p.file_id WHERE f.name = ?"
            " ORDER BY p.number", (nome,),
        )
    ]


def _arquivo(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


def _com_leitor(monkeypatch, mensagens):
    leitor = LeitorSimulado(mensagens)
    monkeypatch.setattr(outlook, "open_reader", lambda _path: leitor)
    return leitor


def _caixa(leituras):
    return [
        PstMessage(
            folder="Caixa de Entrada/Projetos", sender="Ana <ana@x.com>", recipients="Bia <bia@x.com>",
            date="2026-01-05 10:00:00", subject="Contrato de locação", plain="Segue o contrato em anexo.",
            attachments=[
                Anexo("minuta.docx", _docx("Cláusula quinta do aluguel"), leituras),
                Anexo("../../escapou.pdf", _pdf("Planilha de custos anexa"), leituras),
                Anexo("pacote.zip", _zip("dentro.txt", "segredo no compactado"), leituras),
                Anexo("sem-extensao.dat", _pdf("PDF disfarçado de dat"), leituras),
            ],
        ),
        PstMessage(
            folder="Enviados", sender="Bia", recipients="Ana", date="2026-01-06",
            subject="Re: Contrato", html="<p>Combinado, <b>assinamos</b> amanhã.</p>",
        ),
        PstMessage(folder="", sender="Cris", subject="Só RTF", rtf=r"{\rtf1\ansi Texto em RTF puro}"),
    ]


def test_cada_mensagem_e_uma_pagina_com_cabecalho_e_os_anexos_vem_logo_depois(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Arquivo.pst").write_bytes(b"!BDN")
    leituras: list = []
    leitor = _com_leitor(monkeypatch, _caixa(leituras))

    scan(conn, config)
    resultado = convert(conn, config)
    extract_pages(conn, config)

    assert resultado.failed == 0, [dict(r) for r in conn.execute("SELECT name, error FROM file")]
    paginas = _paginas(conn, "Arquivo.pst")
    # Mensagem 1, três anexos com texto (o .zip fica de fora), mensagem 2, mensagem 3.
    assert len(paginas) == 6
    assert _arquivo(conn, "Arquivo.pst")["page_count"] == 6
    primeira = paginas[0]
    for linha in (
        "De: Ana <ana@x.com>", "Para: Bia <bia@x.com>", "Data: 2026-01-05 10:00:00",
        "Assunto: Contrato de locação", "Pasta: Caixa de Entrada/Projetos", "Segue o contrato em anexo.",
    ):
        assert linha in primeira
    assert paginas[1].startswith("Anexo: minuta.docx (mensagem: Contrato de locação)")
    assert "Cláusula quinta do aluguel" in paginas[1]
    # O nome do anexo é saneado (sem caminho) e o tipo real é o do conteúdo.
    assert "Anexo: escapou.pdf" in paginas[2] and "Planilha de custos anexa" in paginas[2]
    assert "Anexo: sem-extensao.dat" in paginas[3] and "PDF disfarçado de dat" in paginas[3]
    assert "segredo no compactado" not in "".join(paginas)
    assert "pacote.zip" not in "".join(paginas)
    assert "assinamos" in paginas[4] and "<b>" not in paginas[4] and "Pasta: Enviados" in paginas[4]
    assert "Texto em RTF puro" in paginas[5] and "Assunto: Só RTF" in paginas[5]
    # O leitor foi fechado e nenhum anexo ficou em disco.
    assert leitor.fechado
    assert not list((workdir.work_folder(saida) / "converted").rglob("anexos"))
    # A busca cita a página da mensagem.
    achados = fulltext.passages_for_file(conn, config, _arquivo(conn, "Arquivo.pst"))
    assert any("assinamos" in p.text and p.locator.startswith("f. 5") for p in achados)
    conn.close()


def test_anexo_compactado_e_ignorado_pelo_nome_e_pelos_bytes(tmp_path):
    from gclaude_indexer.conversion import _attachment_text

    config = load_config({"name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")})
    zip_certo = tmp_path / "a.zip"
    zip_certo.write_bytes(_zip("x.txt", "oculto"))
    zip_disfarcado = tmp_path / "b.txt"
    zip_disfarcado.write_bytes(_zip("x.txt", "oculto"))
    sete_z = tmp_path / "c.7z"
    sete_z.write_bytes(b"7z\xbc\xaf\x27\x1c" + bytes(range(256)))
    assert _attachment_text(zip_certo, config) is None
    assert _attachment_text(zip_disfarcado, config) is None
    assert _attachment_text(sete_z, config) is None


def test_anexos_vao_para_o_extrator_do_tipo_real(tmp_path):
    from gclaude_indexer.conversion import _attachment_text

    config = load_config({"name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")})
    casos = {
        "a.docx": (_docx("texto do word"), "texto do word"),
        "b.dat": (_docx("word sem extensão"), "word sem extensão"),
        "c.pdf": (_pdf("texto do pdf"), "texto do pdf"),
        "d.txt": ("texto simples ç".encode("utf-8"), "texto simples ç"),
        "e.rtf": (rb"{\rtf1\ansi Texto rtf}", "Texto rtf"),
        "f.html": (b"<html><body><p>pagina html</p></body></html>", "pagina html"),
        "g.eml": (b"From: a@x.com\nSubject: Assunto interno\n\nCorpo interno\n", "Corpo interno"),
    }
    for nome, (dados, esperado) in casos.items():
        arquivo = tmp_path / nome
        arquivo.write_bytes(dados)
        assert esperado in (_attachment_text(arquivo, config) or ""), nome
    # Imagem sem idioma de OCR: não há o que ler.
    imagem = tmp_path / "foto.png"
    imagem.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    assert _attachment_text(imagem, replace(config, ocr_language="")) is None


@pytest.mark.parametrize("nome, esperado", [
    ("relatório.pdf", "relatório.pdf"),
    ("..\\..\\Windows\\system32\\x.exe", "x.exe"),
    ("a/b/c.txt", "c.txt"),
    ("CON", "_CON"),
    ("nul.txt", "_nul.txt"),
    ("COM1.pdf", "_COM1.pdf"),
    ("", "anexo"),
    ("...", "anexo"),
    ("arquivo.", "arquivo"),
    ('a<b>:"c|d?*.txt', "a_b___c_d__.txt"),
])
def test_nome_de_anexo_saneado(nome, esperado):
    assert sanitize_attachment_name(nome) == esperado


def test_nome_de_anexo_gigante_e_encurtado_mantendo_a_extensao():
    saneado = sanitize_attachment_name("x" * 500 + ".pdf")
    assert saneado.endswith(".pdf") and len(saneado) <= 125


def test_parar_respeitado_entre_mensagens_e_retomada_nao_refaz_os_anexos(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Grande.pst").write_bytes(b"!BDN")
    leituras: list = []
    mensagens = [
        PstMessage(
            folder="Caixa", subject=f"Mensagem {n}", plain=f"Corpo {n}",
            attachments=[Anexo(f"anexo{n}.txt", f"texto do anexo {n}".encode(), leituras)],
        )
        for n in range(1, 31)
    ]
    _com_leitor(monkeypatch, mensagens)
    scan(conn, config)

    # Para depois de 10 mensagens inteiras (o Parar é consultado antes de cada uma).
    parar = lambda: len(leituras) >= 10  # noqa: E731
    convert(conn, config, should_stop=parar)
    assert _arquivo(conn, "Grande.pst")["status"] == "discovered"
    assert len(leituras) == 10

    leituras.clear()
    resultado = convert(conn, config)
    assert resultado.failed == 0
    # Só as 20 mensagens que faltavam foram lidas de novo (anexos inclusive).
    assert len(leituras) == 20 and "anexo1.txt" not in leituras and "anexo30.txt" in leituras
    extract_pages(conn, config)
    paginas = _paginas(conn, "Grande.pst")
    assert len(paginas) == 60
    assert [p for p in paginas if p.startswith("De:")][0].count("Assunto: Mensagem 1") == 1
    assunto = [line for p in paginas for line in p.splitlines() if line.startswith("Assunto: Mensagem")]
    assert assunto == [f"Assunto: Mensagem {n}" for n in range(1, 31)]
    # Nada sobra do progresso.
    pasta = workdir.work_folder(saida) / "converted"
    assert not list(pasta.rglob("*.partial")) and not list(pasta.rglob("*.progress"))
    conn.close()


def test_progresso_de_outro_arquivo_de_origem_e_descartado(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    caixa = origem / "Troca.pst"
    caixa.write_bytes(b"!BDN" * 10)
    mensagens = [PstMessage(subject=f"M{n}", plain=f"corpo {n}") for n in range(1, 6)]
    _com_leitor(monkeypatch, mensagens)
    scan(conn, config)
    pedidos = []
    convert(conn, config, should_stop=lambda: (pedidos.append(1), len(pedidos) > 2)[1])
    assert _arquivo(conn, "Troca.pst")["status"] == "discovered"
    # O arquivo mudou entre as execuções: recomeça do zero, sem duplicar.
    caixa.write_bytes(b"!BDN" * 11)
    convert(conn, config)
    extract_pages(conn, config)
    assert len(_paginas(conn, "Troca.pst")) == 5
    conn.close()


def test_teto_de_mensagens_corta_e_avisa(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Lotada.ost").write_bytes(b"!BDN")
    monkeypatch.setattr(outlook, "MAX_MESSAGES", 3)
    _com_leitor(monkeypatch, [PstMessage(subject=f"M{n}", plain="x") for n in range(10)])
    scan(conn, config)
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config)
    assert len(_paginas(conn, "Lotada.ost")) == 3
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("limite de 3 mensagens" in a for a in avisos), avisos
    conn.close()


def test_anexo_grande_demais_e_o_orcamento_total_sao_respeitados(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Pesada.pst").write_bytes(b"!BDN")
    monkeypatch.setattr(outlook, "MAX_ATTACHMENT_BYTES", 100)
    monkeypatch.setattr(outlook, "MAX_EXTRACTED_BYTES", 150)
    leituras: list = []
    _com_leitor(monkeypatch, [PstMessage(
        subject="Anexos", plain="corpo",
        attachments=[
            Anexo("enorme.txt", b"e" * 500, leituras),
            Anexo("a.txt", b"primeiro " * 9, leituras),
            Anexo("b.txt", b"segundo " * 10, leituras),
        ],
    )])
    scan(conn, config)
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config)
    texto = "".join(_paginas(conn, "Pesada.pst"))
    assert "primeiro" in texto and "segundo" not in texto and "eeee" not in texto
    assert "enorme.txt" not in leituras
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("grande(s) demais" in a for a in avisos), avisos
    conn.close()


def test_sem_a_biblioteca_o_arquivo_fica_ignorado_como_sem_leitor(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "A.pst").write_bytes(b"!BDN")
    (origem / "B.ost").write_bytes(b"!BDN2")

    def indisponivel(_path):
        raise outlook.ReaderUnavailable("leitor de Outlook indisponível neste computador")

    monkeypatch.setattr(outlook, "open_reader", indisponivel)
    scan(conn, config)
    resultado = convert(conn, config, language="pt-BR")
    assert resultado.failed == 0
    for nome in ("A.pst", "B.ost"):
        linha = _arquivo(conn, nome)
        assert linha["status"] == "skipped" and linha["error"] == "unsupported"
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert sum("Leitor de Outlook indisponível neste computador: 2 arquivo(s)" in a for a in avisos) == 1
    conn.close()


def test_arquivo_ilegivel_falha_sem_derrubar_os_demais(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path, ("outlook", "text"))
    (origem / "quebrado.pst").write_bytes(b"nao e um pst")
    (origem / "nota.txt").write_text("nota comum", encoding="utf-8")

    def ilegivel(_path):
        raise outlook.OutlookError("arquivo do Outlook ilegível ou protegido")

    monkeypatch.setattr(outlook, "open_reader", ilegivel)
    scan(conn, config)
    resultado = convert(conn, config)
    assert resultado.failed == 1 and resultado.converted == 1
    assert _arquivo(conn, "quebrado.pst")["status"] == "failed"
    assert _arquivo(conn, "nota.txt")["status"] == "converted"
    conn.close()


def test_leitor_real_recusa_arquivo_que_nao_e_pst(tmp_path):
    pytest.importorskip("pypff")
    lixo = tmp_path / "lixo.pst"
    lixo.write_bytes(b"isto nao e um arquivo do Outlook" * 20)
    with pytest.raises(outlook.OutlookError):
        outlook.open_reader(lixo)


def test_caixa_vazia_vira_uma_pagina_vazia(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Vazia.pst").write_bytes(b"!BDN")
    _com_leitor(monkeypatch, [])
    scan(conn, config)
    assert convert(conn, config).failed == 0
    extract_pages(conn, config)
    assert _arquivo(conn, "Vazia.pst")["status"] == "extracted" or _arquivo(conn, "Vazia.pst")["page_count"] == 1
    conn.close()


def test_separador_de_pagina_nunca_aparece_dentro_de_uma_mensagem(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Feed.pst").write_bytes(b"!BDN")
    _com_leitor(monkeypatch, [PstMessage(subject="Com\x0cavanço", plain="a\x0cb"), PstMessage(subject="Outra", plain="c")])
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    assert len(_paginas(conn, "Feed.pst")) == 2
    conn.close()


def test_rotulos_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        for chave in (
            "new_project.category.outlook", "log.conversion.outlook_unavailable",
            "log.conversion.outlook_truncated", "log.conversion.outlook_attachments_skipped",
        ):
            assert translate(idioma, chave) != chave
    assert PAGE_SEPARATOR  # o mesmo separador da caixa .mbox


# --- rodada de correções 1 ------------------------------------------------------------------------


def test_anexo_com_tipo_diferente_da_extensao_nao_deixa_nada_em_disco_entre_mensagens(tmp_path):
    from gclaude_indexer.conversion import _attachment_text

    config = load_config({"name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")})
    raiz = tmp_path / "anexos"
    sobras: list = []
    leituras: list = []

    def extrair(caminho, nome):
        texto = _attachment_text(caminho, config, nome)
        return texto

    class Espiao(PstMessage):
        pass

    mensagens = [
        PstMessage(subject="Um", plain="a", attachments=[Anexo("planilha.dat", _docx("texto escondido"), leituras)]),
        PstMessage(subject="Dois", plain="b"),
    ]

    class Leitor(LeitorSimulado):
        def messages(self):
            yield mensagens[0]
            # Ao pedir a segunda mensagem, a primeira já tem que ter ido embora.
            sobras.extend(p for p in raiz.rglob("*") if p.is_file())
            yield mensagens[1]

    destino = tmp_path / "saida.txt"
    (tmp_path / "x.pst").write_bytes(b"1")
    resultado = outlook.convert_pst(
        tmp_path / "x.pst", destino, raiz, extrair, reader_factory=lambda _p: Leitor([]),
    )
    assert resultado.pages == 3
    assert "texto escondido" in destino.read_text(encoding="utf-8")
    assert sobras == []


def test_teto_de_anexos_vale_tambem_na_retomada(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Teto.pst").write_bytes(b"!BDN")
    monkeypatch.setattr(outlook, "MAX_EXTRACTED_BYTES", 150)
    leituras: list = []
    _com_leitor(monkeypatch, [
        PstMessage(subject=f"M{n}", plain="c", attachments=[Anexo(f"a{n}.txt", (f"anexo{n} " * 12).encode()[:100], leituras)])
        for n in (1, 2)
    ])
    scan(conn, config)
    convert(conn, config, should_stop=lambda: len(leituras) >= 1)
    assert _arquivo(conn, "Teto.pst")["status"] == "discovered" and leituras == ["a1.txt"]
    leituras.clear()
    convert(conn, config)
    extract_pages(conn, config)
    # Os 100 bytes da primeira execução contam: o segundo anexo estoura os 150.
    assert leituras == []
    texto = "".join(_paginas(conn, "Teto.pst"))
    assert "anexo1" in texto and "anexo2" not in texto
    conn.close()


def test_teto_do_texto_escrito_corta_e_avisa(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Texto.pst").write_bytes(b"!BDN")
    monkeypatch.setattr(outlook, "MAX_OUTPUT_BYTES", 400)
    leituras: list = []
    # Um anexo pequeno que vira muito texto (compressível) não fura o teto.
    _com_leitor(monkeypatch, [
        PstMessage(subject=f"M{n}", plain="corpo " * 20, attachments=[Anexo("g.txt", b"y" * 5000, leituras)])
        for n in range(20)
    ])
    scan(conn, config)
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config)
    paginas = _paginas(conn, "Texto.pst")
    assert 0 < len(paginas) < 40
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("passou do limite de" in a and "MB" in a for a in avisos), avisos
    conn.close()


_CHAVE = b"-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----\n"


def test_anexos_de_segredo_nunca_chegam_ao_texto(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Segredos.pst").write_bytes(b"!BDN")
    leituras: list = []
    _com_leitor(monkeypatch, [PstMessage(subject="Segredos", plain="corpo", attachments=[
        Anexo(".env", b"SENHA_DO_BANCO=hunter2\n", leituras),
        Anexo("id_rsa", b"conteudo de chave ssh qualquer", leituras),
        Anexo("id_rsa.txt", b"chave ssh renomeada", leituras),
        Anexo("notas.txt", b"previa\n" + _CHAVE, leituras),
        Anexo("escondida.docx", _docx(_CHAVE.decode()), leituras),
        Anexo("cofre.pfx", b"pfx-secreto" * 10, leituras),
        Anexo("normal.txt", b"anexo comum sem segredo", leituras),
    ])])
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    texto = "\n".join(_paginas(conn, "Segredos.pst"))
    for proibido in ("hunter2", "ssh qualquer", "ssh renomeada", "PRIVATE KEY", "MIIBOg", "pfx-secreto"):
        assert proibido not in texto, proibido
    assert "anexo comum sem segredo" in texto
    conn.close()


def test_nome_com_ponto_inicial_nao_perde_o_ponto_para_a_checagem():
    # `.env` chega à checagem com o nome original (o saneamento não o altera
    # para algo que a regra da varredura não reconheça).
    from gclaude_indexer.file_types import index_decision

    assert index_decision(".env", b"X=1", ["all"]) == "secret"
    assert sanitize_attachment_name(".env").endswith(".env")


def test_iter_pages_junta_separador_cortado_entre_pedaços(tmp_path):
    from gclaude_indexer.light_formats import iter_pages

    caminho = tmp_path / "caixa.txt"
    paginas = ["um", "dois\ncom linhas", "", "quatro"]
    caminho.write_text(PAGE_SEPARATOR.join(paginas), encoding="utf-8")
    for pedaco in (1, 2, 3, 4, 7, 1000):
        assert list(iter_pages(caminho, pedaco)) == paginas, pedaco


# --- rodada de correções 2 ------------------------------------------------------------------------


def test_nomes_disfarcados_de_segredo_sao_recusados_e_o_normal_passa(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Disfarces.pst").write_bytes(b"!BDN")
    leituras: list = []
    _com_leitor(monkeypatch, [PstMessage(subject="Disfarces", plain="corpo", attachments=[
        Anexo(".env ", b"SENHA_A=alfa1\n", leituras),
        Anexo("id_rsa.", b"chave ssh beta2", leituras),
        Anexo("chave.pem. ", b"pem gama3", leituras),
        Anexo("segredo.env", b"SENHA_D=delta4\n", leituras),
        Anexo(".env\x00.txt", b"SENHA_E=epsilon5\n", leituras),
        Anexo("relatorio.txt", b"relatorio comum liberado", leituras),
    ])])
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    texto = "\n".join(_paginas(conn, "Disfarces.pst"))
    for proibido in ("alfa1", "beta2", "gama3", "delta4"):
        assert proibido not in texto, proibido
    assert "relatorio comum liberado" in texto
    conn.close()


def test_extensao_de_segredo_de_arquivo_com_ponto_inicial_e_reconhecida(tmp_path):
    from gclaude_indexer.conversion import _attachment_text

    config = load_config({"name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "o")})
    alvo = tmp_path / ".env"
    alvo.write_bytes(b"A=1\n")
    assert _attachment_text(alvo, config, "qualquer.txt") is None
    ok = tmp_path / "relatorio.txt"
    ok.write_bytes(b"texto liberado")
    assert _attachment_text(ok, config, "relatorio.txt") == "texto liberado"


def _caixa_grande(tmp_path, paginas=60):
    from gclaude_indexer.workdir import PAGE_SEPARATOR

    caminho = tmp_path / "grande.txt"
    caminho.write_text(
        PAGE_SEPARATOR.join(f"Assunto: M{n}\n\ncorpo numero {n}" for n in range(paginas)), encoding="utf-8",
    )
    return caminho


def test_extracao_de_caixa_de_mensagens_e_preguicosa(tmp_path, monkeypatch):
    from gclaude_indexer import extraction, light_formats

    puxadas = []
    original = light_formats.iter_pages

    def espiao(caminho, *a, **k):
        for pagina in original(caminho, *a, **k):
            puxadas.append(1)
            yield pagina

    monkeypatch.setattr(light_formats, "iter_pages", espiao)
    paginas = extraction.MessagePages(_caixa_grande(tmp_path), 4000)
    assert puxadas == []  # nada lido ao criar (nem ao cruzar o pool)
    iterador = iter(paginas)
    primeiras = [next(iterador) for _ in range(3)]
    assert len(puxadas) == 3 and primeiras[0][0].startswith("Assunto: M0")
    assert len(list(paginas)) == 60  # pode ser percorrido de novo


def test_indexacao_de_caixa_de_mensagens_e_preguicosa_e_em_lotes(tmp_path, monkeypatch):
    from gclaude_indexer import fulltext, light_formats

    puxadas = []
    original = light_formats.iter_pages

    def espiao(caminho, *a, **k):
        for pagina in original(caminho, *a, **k):
            puxadas.append(1)
            yield pagina

    monkeypatch.setattr(light_formats, "iter_pages", espiao)
    trechos = fulltext.MessagePassages(_caixa_grande(tmp_path), {})
    assert puxadas == []
    iterador = iter(trechos)
    primeiro = next(iterador)
    # Um trecho por vez: só a primeira página foi lida, não o arquivo.
    assert len(puxadas) == 1 and primeiro.locator.startswith("p. 1")

    # E o armazenamento consome sem montar lista: a cada inserção, no máximo
    # uma página à frente do que já foi gravado.
    (tmp_path / "p").mkdir()
    origem, saida, config, conn = _projeto(tmp_path / "p")
    (origem / "L.pst").write_bytes(b"!BDN")
    scan(conn, config)
    linha = conn.execute("SELECT * FROM file").fetchone()
    puxadas.clear()
    maximo = []

    class Medidor:
        def __iter__(self_inner):
            for passagem in trechos:
                maximo.append(len(puxadas))
                yield passagem

    conn.execute("BEGIN IMMEDIATE")
    gravados = fulltext._store_passages(conn, linha, Medidor())
    conn.commit()
    assert gravados == 60 and max(maximo) <= 60 and maximo == list(range(1, 61))
    assert conn.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0] == 60
    intervalo = conn.execute("SELECT first_rowid, last_rowid FROM fulltext_file").fetchone()
    assert intervalo[1] - intervalo[0] == 59
    conn.close()


# --- o que fica fora de um arquivo do Outlook sempre aparece no log -----------------------------


class _AnexoIlegivel:
    name = "quebrado.txt"
    size = 10

    def read(self, limit: int) -> bytes:
        raise OSError("bloco corrompido")


def test_anexo_que_nao_pode_ser_lido_e_avisado(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Anexo.pst").write_bytes(b"!BDN")
    _com_leitor(monkeypatch, [PstMessage(subject="M1", plain="corpo", attachments=[_AnexoIlegivel()])])
    scan(conn, config)
    assert convert(conn, config, language="pt-BR").failed == 0
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("Anexo.pst" in a and "1 anexo(s) não puderam ser lidos" in a for a in avisos), avisos
    conn.close()


def test_mensagens_ou_pastas_ilegiveis_sao_avisadas(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Danificada.pst").write_bytes(b"!BDN")
    leitor = _com_leitor(monkeypatch, [PstMessage(subject="M1", plain="ok")])
    leitor.unreadable = 2
    scan(conn, config)
    assert convert(conn, config, language="pt-BR").failed == 0
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("Danificada.pst" in a and "2 mensagem(ns) ou pasta(s)" in a for a in avisos), avisos
    conn.close()


def test_avisos_de_conteudo_ilegivel_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        for chave in ("log.conversion.outlook_attachments_unreadable", "log.conversion.outlook_items_unreadable"):
            assert translate(idioma, chave) != chave


def test_anexo_que_o_extrator_nao_consegue_ler_e_avisado_e_o_tipo_nao_lido_nao(tmp_path):
    notas: list = []
    leituras: list = []
    mensagens = [PstMessage(subject="M", plain="c", attachments=[
        Anexo("corrompido.docx", b"nao e docx", leituras), Anexo("pacote.zip", b"PK", leituras),
    ])]

    def extrair(caminho, nome):
        if nome.endswith(".docx"):
            raise ValueError("docx corrompido")
        return None  # tipo que não é lido

    (tmp_path / "x.pst").write_bytes(b"1")
    outlook.convert_pst(
        tmp_path / "x.pst", tmp_path / "saida.txt", tmp_path / "anexos", extrair,
        reader_factory=lambda _p: LeitorSimulado(mensagens), on_note=lambda tipo, dados: notas.append((tipo, dados["name"])),
    )
    assert notas == [("attachment_unreadable", "corrompido.docx")]


class _PastaFalsa:
    """Pasta do pypff: mensagens e subpastas por índice; `None` é um item
    que o arquivo danificado não deixa abrir."""

    def __init__(self, name, mensagens=(), pastas=()):
        self.name = name
        self._mensagens = list(mensagens)
        self._pastas = list(pastas)
        self.number_of_sub_messages = len(self._mensagens)
        self.number_of_sub_folders = len(self._pastas)

    def get_sub_message(self, index):
        if self._mensagens[index] is None:
            raise OSError("bloco corrompido")
        return self._mensagens[index]

    def get_sub_folder(self, index):
        if self._pastas[index] is None:
            raise OSError("bloco corrompido")
        return self._pastas[index]


def test_leitor_real_conta_mensagens_e_pastas_que_nao_abrem():
    class _Msg:
        def __init__(self, assunto):
            self.subject = assunto

    class _Arquivo:
        def get_root_folder(self):
            return _PastaFalsa("", [_Msg("A"), None], [None, _PastaFalsa("Caixa", [_Msg("B")])])

    leitor = object.__new__(outlook._PypffReader)
    leitor.unreadable = 0
    leitor._file = _Arquivo()
    assert [m.subject for m in leitor.messages()] == ["A", "B"]
    assert leitor.unreadable == 2


def test_retoma_progresso_gravado_pela_versao_anterior(tmp_path):
    """O `.progress` que as versões até a 2.1.0 gravavam, escrito à mão: uma
    conversão parada antes da atualização continua depois dela."""
    origem = tmp_path / "x.pst"
    origem.write_bytes(b"1")
    destino = tmp_path / "saida.txt"
    feito = "Assunto: M1\n\ncorpo 1".encode("utf-8")
    (tmp_path / "saida.txt.partial").write_bytes(feito)
    info = origem.stat()
    (tmp_path / "saida.txt.progress").write_text(json.dumps({
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "messages": 1, "bytes": len(feito),
        "pages": 1, "extracted": 0,
    }), encoding="utf-8")
    lidas = []

    class Leitor(LeitorSimulado):
        def messages(self):
            for mensagem in super().messages():
                lidas.append(mensagem.subject)
                yield mensagem

    resultado = outlook.convert_pst(
        origem, destino, tmp_path / "anexos", lambda p, n: None,
        reader_factory=lambda _p: Leitor([PstMessage(subject="M1", plain="nunca"), PstMessage(subject="M2", plain="corpo 2")]),
    )
    assert resultado.pages == 2
    texto = destino.read_text(encoding="utf-8")
    assert "corpo 1" in texto and "corpo 2" in texto and "nunca" not in texto
    assert not (tmp_path / "saida.txt.progress").exists()

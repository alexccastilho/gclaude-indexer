# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""2.0.0, Task 9 — formatos antigos (`.doc`, `.ppt`, `.wpd`…) pelo LibreOffice.

Não há LibreOffice real na suíte: o `soffice` é um simulador (um script
Python que lê o arquivo recebido e escreve um PDF de verdade), colocado no
lugar de `legacy_office._popen`. O que se prova é o nosso lado: a linha de
comando, o perfil temporário, o tempo limite que mata a árvore de processos,
caminhos com espaços e acentos, o componente que falta e a fila de
reconversão. Os tetos de extração do ZIP e o redirecionamento só para HTTPS
(pedidos na revisão da Task 7) também são testados aqui, no gerenciador.
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import replace
from pathlib import Path

import psutil
import pytest

from gclaude_indexer import components, conversion, legacy_office, ocr_languages
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert, converted_artifact_path, ocr_retry_count
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.file_types import (
    EXTENSION_CATEGORIES, categories_by_family, category_of_extension, index_decision, is_whole_document_file,
)
from gclaude_indexer.i18n import translate
from gclaude_indexer.scanning import scan

LEGADOS = {
    ".doc", ".dot", ".ppt", ".pps", ".pot", ".wpd", ".wps", ".pub", ".vsd", ".vsdx",
    ".sxw", ".sxc", ".sxi", ".sdw", ".123", ".wk1", ".wb2",
}

# O `soffice` de mentira: lê o último argumento (o arquivo), escreve em
# `--outdir` um PDF com o texto dele, e anota como foi chamado.
_SIMULADOR = r"""
import json, os, sys
import fitz
args = sys.argv[1:]
outdir = args[args.index("--outdir") + 1]
entrada = args[-1]
log = os.environ.get("SIMULADOR_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
modo = os.environ.get("SIMULADOR_MODO", "ok")
if modo == "falha":
    sys.exit(81)
if modo == "sem_saida":
    sys.exit(0)
texto = open(entrada, "rb").read().decode("utf-8", "replace")
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), texto)
nome = os.path.splitext(os.path.basename(entrada))[0] + ".pdf"
doc.save(os.path.join(outdir, nome))
"""

_TRAVADO = r"""
import os, subprocess, sys, time
neto = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(os.environ["SIMULADOR_PIDS"], "w") as f:
    f.write(f"{os.getpid()} {neto.pid}")
time.sleep(120)
"""


@pytest.fixture(autouse=True)
def _pasta_local(tmp_path, monkeypatch):
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))


@pytest.fixture
def simulador(tmp_path, monkeypatch):
    """`soffice` simulado; devolve o caminho do arquivo de chamadas."""
    chamadas = tmp_path / "chamadas.jsonl"
    monkeypatch.setenv("SIMULADOR_LOG", str(chamadas))
    monkeypatch.delenv("SIMULADOR_MODO", raising=False)
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso)
    real = legacy_office._popen

    def _popen(comando, env):
        return real([sys.executable, "-c", _SIMULADOR, *comando[1:]], env)

    monkeypatch.setattr(legacy_office, "_popen", _popen)
    return chamadas


def _chamadas(arquivo: Path) -> list[list[str]]:
    import json

    if not arquivo.exists():
        return []
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


def _projeto(tmp_path, extensoes=("legados",)):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Antigos", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": list(extensoes),
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


def _paginas(conn, nome):
    return [
        row["text"] for row in conn.execute(
            "SELECT p.text AS text FROM page p JOIN file f ON f.id = p.file_id WHERE f.name = ? ORDER BY p.number",
            (nome,),
        )
    ]


# --- categoria -------------------------------------------------------------------


def test_categoria_legados_cobre_as_extensoes_pedidas():
    assert EXTENSION_CATEGORIES["legados"] == LEGADOS
    assert all(category_of_extension(ext) == "legados" for ext in LEGADOS)
    # `.pages` só entraria com uma conversão de teste que funcionasse: não entrou.
    assert ".pages" not in LEGADOS
    assert index_decision("Apresentação.pages", categories=["all"]) == "unsupported"
    assert index_decision("Contrato.doc", categories=["all"]) is None
    # Tem páginas de verdade (o intermediário é um PDF).
    assert not is_whole_document_file("Contrato.doc")
    familias = dict(categories_by_family())
    assert "legados" in [item["categoria"] for item in familias["documentos"]]


def test_rotulos_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        for chave in (
            "new_project.category.legados", "ignored.reason.unsupported",
            "ignored.reason.component_unavailable",
        ):
            assert translate(idioma, chave) != chave
        texto = translate(idioma, "log.conversion.component_unavailable", component="LibreOffice", count=3)
        assert "LibreOffice" in texto and "3" in texto


# --- conversão com o simulador ---------------------------------------------------


def test_doc_vira_pdf_intermediario_e_entra_no_indice(tmp_path, simulador, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "Contrato antigo.doc").write_bytes("Cláusula primeira do contrato legado.".encode("utf-8"))
    monkeypatch.setattr(conversion, "_run_ocrmypdf", lambda *a, **k: (_ for _ in ()).throw(AssertionError("texto nativo")))

    scan(conn, config)
    resultado = convert(conn, config)
    extract_pages(conn, config)

    assert resultado.failed == 0
    linha = conn.execute("SELECT * FROM file WHERE name = 'Contrato antigo.doc'").fetchone()
    assert linha["status"] == "extracted" and linha["page_count"] == 1 and linha["needs_ocr"] == 0
    assert "Cláusula primeira" in _paginas(conn, "Contrato antigo.doc")[0]
    intermediario = converted_artifact_path(saida, "Contrato antigo.doc", ".doc", False)
    assert intermediario.name == "Contrato antigo.doc.pdf" and intermediario.exists()
    assert not list(intermediario.parent.glob("*.raw.pdf"))
    conn.close()


def test_pdf_do_libreoffice_sem_texto_passa_pelo_ocr(tmp_path, simulador, monkeypatch):
    """Um `.ppt` só de imagem sai do LibreOffice como PDF sem texto: o resto
    do caminho (OCR das páginas sem texto) é o do PDF."""
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "slides.ppt").write_bytes(b" ")
    config = replace(config, ocr_language="por")
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    chamado = []

    def _ocr(origem_pdf, destino, idioma, jobs=1, pages=None, rotate=False):
        chamado.append(pages)
        Path(destino).write_bytes(Path(origem_pdf).read_bytes())

    monkeypatch.setattr(conversion, "_run_ocrmypdf", _ocr)
    # O simulador desenha um quadrado, sem texto, para a página "precisar" de OCR.
    monkeypatch.setattr(conversion, "_pdf_pages_needing_ocr", lambda _p: ([1], 1))
    # 2.0.0: os formatos que viram PDF na conversão leem páginas e amostra do
    # texto nativo de uma vez (`ocr_detection.scan_pdf`).
    from gclaude_indexer import ocr_detection

    monkeypatch.setattr(ocr_detection, "scan_pdf", lambda _p: ([1], 1, ""))

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.failed == 0 and chamado == [[1]]
    linha = conn.execute("SELECT * FROM file WHERE name = 'slides.ppt'").fetchone()
    assert linha["status"] == "converted" and linha["needs_ocr"] == 1
    conn.close()


def test_linha_de_comando_perfil_isolado_sem_shell(tmp_path, simulador, monkeypatch):
    chamadas = []
    real = legacy_office._popen

    def _espiao(comando, env):
        chamadas.append(list(comando))
        return real(comando, env)

    monkeypatch.setattr(legacy_office, "_popen", _espiao)
    origem = tmp_path / "pasta com espaço" / "Relatório ção"
    origem.mkdir(parents=True)
    arquivo = origem / "Relatório ção — versão 2.doc"
    arquivo.write_bytes("texto".encode("utf-8"))

    for _ in range(2):
        pdf = legacy_office.convert_to_pdf_bytes(arquivo, tmp_path / "soffice.exe")
        assert pdf.startswith(b"%PDF")

    primeira, segunda = chamadas
    assert primeira[0] == str(tmp_path / "soffice.exe")
    for opcao in ("--headless", "--norestore", "--convert-to"):
        assert opcao in primeira
    assert primeira[primeira.index("--convert-to") + 1] == "pdf"
    perfis = [next(a for a in c if a.startswith("-env:UserInstallation=file:///")) for c in chamadas]
    # Um perfil novo por execução, nunca o do usuário.
    assert perfis[0] != perfis[1]
    assert all("gclaude-lo-" in p for p in perfis)
    # O arquivo chega ao LibreOffice com nome simples (espaços e acentos ficam de fora).
    entrada = primeira[-1]
    assert entrada.endswith("documento.doc") and "Relatório" not in entrada
    # O simulador recebeu os mesmos argumentos, em lista (sem shell).
    assert _chamadas(simulador)[0][-1] == entrada


def test_pasta_de_origem_com_espacos_e_acentos_converte(tmp_path, simulador):
    origem, saida, config, conn = _projeto(tmp_path)
    sub = origem / "Prestação de contas" / "ano 2009"
    sub.mkdir(parents=True)
    (sub / "Ofício nº 12 — resposta.wps").write_bytes("Ofício respondido.".encode("utf-8"))

    scan(conn, config)
    resultado = convert(conn, config)
    extract_pages(conn, config)

    assert resultado.failed == 0
    assert "Ofício respondido" in _paginas(conn, "Ofício nº 12 — resposta.wps")[0]
    conn.close()


def test_falha_do_libreoffice_falha_so_aquele_arquivo(tmp_path, simulador, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "protegido.doc").write_bytes(b"x")
    monkeypatch.setenv("SIMULADOR_MODO", "falha")

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.failed == 1
    linha = conn.execute("SELECT * FROM file WHERE name = 'protegido.doc'").fetchone()
    assert linha["status"] == "failed" and "LibreOffice" in linha["error"] and linha["ocr_failed"] == 0
    conn.close()


def test_saida_ausente_e_erro(tmp_path, simulador, monkeypatch):
    monkeypatch.setenv("SIMULADOR_MODO", "sem_saida")
    arquivo = tmp_path / "a.doc"
    arquivo.write_bytes(b"x")
    with pytest.raises(legacy_office.LegacyOfficeError):
        legacy_office.convert_to_pdf_bytes(arquivo, tmp_path / "soffice.exe")


# --- tempo limite ----------------------------------------------------------------


def test_tempo_limite_mata_a_arvore_de_processos(tmp_path, monkeypatch):
    pids = tmp_path / "pids.txt"
    monkeypatch.setenv("SIMULADOR_PIDS", str(pids))
    real = legacy_office._popen
    monkeypatch.setattr(
        legacy_office, "_popen", lambda comando, env: real([sys.executable, "-c", _TRAVADO], env)
    )
    arquivo = tmp_path / "travado.doc"
    arquivo.write_bytes(b"x")

    inicio = time.monotonic()
    with pytest.raises(legacy_office.LegacyOfficeError, match="passou de"):
        legacy_office.convert_to_pdf_bytes(arquivo, tmp_path / "soffice.exe", timeout=3)
    assert time.monotonic() - inicio < 60

    pai, neto = (int(valor) for valor in pids.read_text().split())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (psutil.pid_exists(pai) or psutil.pid_exists(neto)):
        time.sleep(0.1)
    assert not psutil.pid_exists(pai) and not psutil.pid_exists(neto)


def test_um_libreoffice_por_vez(tmp_path, simulador, monkeypatch):
    import threading

    simultaneos = []
    ativos = [0]
    real = legacy_office._popen

    def _contador(comando, env):
        ativos[0] += 1
        simultaneos.append(ativos[0])
        try:
            return real(comando, env)
        finally:
            pass

    class _Embrulho:
        def __init__(self, processo):
            self.processo = processo

        def wait(self, timeout=None):
            try:
                return self.processo.wait(timeout=timeout)
            finally:
                ativos[0] -= 1

        def __getattr__(self, nome):
            return getattr(self.processo, nome)

    monkeypatch.setattr(legacy_office, "_popen", lambda c, e: _Embrulho(_contador(c, e)))
    arquivo = tmp_path / "a.doc"
    arquivo.write_bytes(b"x")
    fios = [
        threading.Thread(target=legacy_office.convert_to_pdf_bytes, args=(arquivo, tmp_path / "soffice.exe"))
        for _ in range(3)
    ]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert max(simultaneos) == 1


# --- componente indisponível -----------------------------------------------------


def test_sem_libreoffice_o_arquivo_fica_pendente_e_volta_a_fila(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "antigo.doc").write_bytes(b"x")
    # Sem componente (manifesto sem a entrada, rede fechada) e sem instalação.
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: None)

    scan(conn, config)
    resultado = convert(conn, config)

    assert resultado.failed == 0
    linha = conn.execute("SELECT * FROM file WHERE name = 'antigo.doc'").fetchone()
    assert linha["status"] == "skipped" and linha["error"] == "component_unavailable"
    assert linha["ocr_failed"] == 1
    avisos = list_events(conn, step="conversion", language="pt-BR")
    assert any("LibreOffice" in e["message"] and e["level"] == "warning" for e in avisos)
    assert ocr_retry_count(conn) == 1

    # Quando o componente aparece, a próxima conversão refaz.
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso)
    real = legacy_office._popen
    monkeypatch.setattr(legacy_office, "_popen", lambda c, e: real([sys.executable, "-c", _SIMULADOR, *c[1:]], e))
    resultado = convert(conn, config)
    extract_pages(conn, config)
    linha = conn.execute("SELECT * FROM file WHERE name = 'antigo.doc'").fetchone()
    assert resultado.failed == 0 and linha["status"] == "extracted" and linha["ocr_failed"] == 0
    conn.close()


def test_baixa_o_componente_so_quando_ha_formato_antigo(tmp_path, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path, ["all"])
    (origem / "nota.txt").write_text("só texto", encoding="utf-8")
    pedidos = []
    monkeypatch.setattr(components, "ensure", lambda nomes, download=True, **_k: pedidos.append(list(nomes)) or {})
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: None)

    scan(conn, config)
    convert(conn, config)
    assert pedidos == []

    (origem / "antigo.ppt").write_bytes(b"x")
    scan(conn, config)
    convert(conn, config)
    assert pedidos == [["libreoffice"]]
    conn.close()


# --- ZIP de componente: tetos e redirecionamento (revisão da Task 7) -----------------


def _zip(membros: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        for nome, dados in membros.items():
            arquivo.writestr(nome, dados)
    return buffer.getvalue()


def _componente_zip(dados: bytes, **extras):
    import hashlib

    return components.Component(
        name="pacote", url="https://example.invalid/pacote.zip", sha256=hashlib.sha256(dados).hexdigest(),
        size=len(dados), license="MPL-2.0", kind="zip", target="teste/pacote", **extras,
    )


def _instalar(monkeypatch, componente, dados):
    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    monkeypatch.setattr(components, "manifest", lambda: {componente.name: componente})
    monkeypatch.setattr(components, "_open_url", lambda url: _R(dados))
    return components.ensure(["pacote"])


def test_zip_que_incha_alem_do_teto_e_recusado_antes_de_extrair(tmp_path, monkeypatch):
    dados = _zip({"grande.bin": b"\0" * 1_000_000})
    # Teto do manifesto abaixo do que o ZIP promete descomprimir.
    item = _componente_zip(dados, max_extracted=500_000)
    assert _instalar(monkeypatch, item, dados) == {"pacote": components.STATUS_UNAVAILABLE}
    pasta = tmp_path / "local" / "teste"
    assert not (pasta / "pacote").exists() and not (pasta / "pacote.extracting").exists()


def test_teto_padrao_e_um_multiplo_do_tamanho(monkeypatch):
    dados = _zip({"grande.bin": b"\0" * 5_000_000})  # comprime a quase nada
    item = _componente_zip(dados)
    assert item.extracted_limit == item.size * components.DEFAULT_EXTRACTED_FACTOR
    assert _instalar(monkeypatch, item, dados) == {"pacote": components.STATUS_UNAVAILABLE}


def test_zip_dentro_do_teto_e_extraido(monkeypatch):
    dados = _zip({"a.txt": b"a" * 100, "b/c.txt": b"c" * 100})
    item = _componente_zip(dados, max_extracted=1000, max_members=5)
    assert _instalar(monkeypatch, item, dados) == {"pacote": components.STATUS_INSTALLED}
    assert (components.path_of("pacote") / "b" / "c.txt").is_file()


def test_zip_com_membros_demais_e_recusado(monkeypatch):
    dados = _zip({f"{i}.txt": b"x" for i in range(10)})
    item = _componente_zip(dados, max_extracted=10_000, max_members=5)
    assert _instalar(monkeypatch, item, dados) == {"pacote": components.STATUS_UNAVAILABLE}
    assert components.path_of("pacote") is None


def test_manifesto_aceita_e_valida_os_tetos(tmp_path):
    import json

    entrada = {
        "name": "x", "url": "https://example.invalid/x.zip", "sha256": "0" * 64, "size": 10,
        "license": "MPL-2.0", "kind": "zip", "target": "x", "max_extracted": 100, "max_members": 7,
    }
    (tmp_path / "m.json").write_text(json.dumps({"format": 1, "components": [entrada]}), encoding="utf-8")
    carregado = components.load_manifest(tmp_path)["x"]
    assert (carregado.max_extracted, carregado.max_members) == (100, 7)
    entrada["max_extracted"] = -1
    (tmp_path / "m.json").write_text(json.dumps({"format": 1, "components": [entrada]}), encoding="utf-8")
    with pytest.raises(ValueError):
        components.load_manifest(tmp_path)


def test_redirecionamento_para_http_e_recusado():
    manipulador = components._HttpsOnlyRedirects()
    pedido = urllib.request.Request("https://mirror.example.invalid/a.zip")
    with pytest.raises(urllib.error.URLError, match="HTTPS"):
        manipulador.redirect_request(pedido, None, 302, "Found", {}, "http://mirror.example.invalid/a.zip")
    with pytest.raises(urllib.error.URLError):
        manipulador.redirect_request(pedido, None, 302, "Found", {}, "ftp://mirror.example.invalid/a.zip")
    seguido = manipulador.redirect_request(pedido, None, 302, "Found", {}, "https://outro.example.invalid/a.zip")
    assert seguido.full_url == "https://outro.example.invalid/a.zip"


def test_o_abridor_de_verdade_usa_o_manipulador_de_redirecionamento():
    assert any(isinstance(h, components._HttpsOnlyRedirects) for h in components._opener.handlers)


# --- componente `msi` (extração administrativa), com o msiexec simulado -----------------


def _msiexec_falso(monkeypatch, arquivos=None, codigo=0, chamadas=None, erro=None):
    """Troca `components._run_msiexec`: lê o TARGETDIR da linha de comando e
    escreve lá o que um `msiexec /a` escreveria (inclusive a cópia do .msi)."""
    import re

    def _rodar(linha, timeout):
        if chamadas is not None:
            chamadas.append((linha, timeout))
        if erro is not None:
            raise erro
        destino = Path(re.search(r'TARGETDIR="([^"]+)"', linha).group(1))
        pacote = re.search(r'/a "([^"]+)"', linha).group(1)
        assert Path(pacote).suffix == ".msi" and Path(pacote).is_file()
        for nome, dados in (arquivos or {}).items():
            alvo = destino / nome
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(dados)
        (destino / "pacote.msi").write_bytes(b"copia")
        return codigo

    monkeypatch.setattr(components, "_run_msiexec", _rodar)


def _componente_msi(dados: bytes, **extras):
    import hashlib

    base = dict(check="program/soffice.exe", max_extracted=10_000, max_members=50)
    base.update(extras)
    return components.Component(
        name="pacote", url="https://example.invalid/pacote.msi", sha256=hashlib.sha256(dados).hexdigest(),
        size=len(dados), license="MPL-2.0", kind="msi", target="teste/pacote", **base,
    )


def test_msi_e_extraido_com_msiexec_marcado_e_o_msi_apagado(tmp_path, monkeypatch):
    dados = b"conteudo do msi"
    chamadas = []
    _msiexec_falso(monkeypatch, {"program/soffice.exe": b"MZ", "share/a.txt": b"a"}, chamadas=chamadas)
    assert _instalar(monkeypatch, _componente_msi(dados), dados) == {"pacote": components.STATUS_INSTALLED}

    pasta = components.path_of("pacote")
    assert (pasta / "program" / "soffice.exe").is_file()
    assert not list(pasta.glob("*.msi"))  # a cópia do administrativo sai
    teste = tmp_path / "local" / "teste"
    assert not list(teste.glob("*.msi")) and not list(teste.glob("*.part"))
    assert not (teste / "pacote.extracting").exists()
    linha, timeout = chamadas[0]
    # Uma linha só, sem shell, com o TARGETDIR entre aspas (o caminho pode ter espaço).
    assert linha.lower().count("msiexec.exe") == 1 and " /a " in linha and " /qn " in linha
    assert 'TARGETDIR="' in linha and timeout == 15 * 60
    # Marcado: já está instalado.
    assert components.ensure(["pacote"]) == {"pacote": components.STATUS_PRESENT}
    assert [c.name for c in components.installed_components()] == ["pacote"]
    assert components.remove("pacote") and components.path_of("pacote") is None


@pytest.mark.parametrize("cenario", ["codigo", "tempo", "sem_executavel", "teto", "membros"])
def test_msi_com_problema_fica_indisponivel_sem_sobras(tmp_path, monkeypatch, cenario):
    dados = b"msi"
    arquivos = {"program/soffice.exe": b"MZ"}
    codigo, erro = 0, None
    if cenario == "codigo":
        codigo = 1625  # exige elevação / política recusa
    elif cenario == "tempo":
        erro = subprocess.TimeoutExpired("msiexec", 1)
    elif cenario == "sem_executavel":
        arquivos = {"outra/coisa.txt": b"x"}
    elif cenario == "teto":
        arquivos = {"program/soffice.exe": b"M" * 20_000}
    elif cenario == "membros":
        arquivos = {"program/soffice.exe": b"MZ", **{f"m{i}.txt": b"x" for i in range(60)}}
    _msiexec_falso(monkeypatch, arquivos, codigo=codigo, erro=erro)
    assert _instalar(monkeypatch, _componente_msi(dados), dados) == {"pacote": components.STATUS_UNAVAILABLE}
    teste = tmp_path / "local" / "teste"
    assert components.path_of("pacote") is None
    assert not (teste / "pacote").exists() and not (teste / "pacote.extracting").exists()
    assert not list(teste.glob("*.msi")) and not list(teste.glob("*.part"))


@pytest.mark.skipif(sys.platform != "win32", reason="msiexec só existe no Windows")
def test_msiexec_no_tempo_limite_morre_com_os_filhos(tmp_path, monkeypatch):
    """O `msiexec` falso (um Python que abre um neto e trava) passa do tempo:
    pai e neto morrem, nenhum fica órfão segurando a pasta de extração."""
    pids = tmp_path / "pids.txt"
    monkeypatch.setenv("SIMULADOR_PIDS", str(pids))
    script = tmp_path / "msiexec_travado.py"
    script.write_text(_TRAVADO, encoding="utf-8")
    linha = f'"{sys.executable}" "{script}"'

    with pytest.raises(subprocess.TimeoutExpired):
        components._run_msiexec(linha, timeout=3)

    pai, neto = (int(valor) for valor in pids.read_text().split())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (psutil.pid_exists(pai) or psutil.pid_exists(neto)):
        time.sleep(0.1)
    assert not psutil.pid_exists(pai) and not psutil.pid_exists(neto)


def test_junction_ou_link_no_extraido_e_recusado(tmp_path, monkeypatch):
    import re

    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.txt").write_text("não pode sair", encoding="utf-8")
    dados = b"msi"

    def _rodar(linha, timeout):
        destino = Path(re.search(r'TARGETDIR="([^"]+)"', linha).group(1))
        (destino / "program").mkdir(parents=True)
        (destino / "program" / "soffice.exe").write_bytes(b"MZ")
        atalho = destino / "atalho"
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(atalho), str(fora)], check=True, capture_output=True)
        else:
            atalho.symlink_to(fora, target_is_directory=True)
        return 0

    monkeypatch.setattr(components, "_run_msiexec", _rodar)
    assert _instalar(monkeypatch, _componente_msi(dados), dados) == {"pacote": components.STATUS_UNAVAILABLE}
    assert (fora / "segredo.txt").exists()  # nada foi apagado através do link
    assert components.path_of("pacote") is None


def test_manifesto_do_pacote_tem_o_libreoffice_msi_oficial_fixado():
    item = components.load_manifest()["libreoffice"]
    assert item.kind == "msi" and item.license == "MPL-2.0"
    assert item.url.startswith("https://download.documentfoundation.org/libreoffice/stable/")
    assert item.url.endswith("_Win_x86-64.msi") and len(item.sha256) == 64 and item.size > 100_000_000
    assert item.check == legacy_office.SOFFICE_RELATIVE
    # A árvore real: cerca de 1,2 GB e 19,5 mil arquivos.
    assert item.max_extracted >= 1_300_000_000 and item.members_limit >= 25_000


# --- perfil travado e versão do LibreOffice do sistema (revisão de segurança) -------------


def test_perfil_travado_e_gravado_antes_de_abrir_o_soffice(tmp_path, simulador, monkeypatch):
    import re
    import urllib.parse
    import xml.etree.ElementTree as ET

    vistos = []
    real = legacy_office._popen

    def _espiao(comando, env):
        uri = next(a for a in comando if a.startswith("-env:UserInstallation="))[len("-env:UserInstallation="):]
        perfil = Path(urllib.request.url2pathname(urllib.parse.urlparse(uri).path))
        arquivo = perfil / "user" / "registrymodifications.xcu"
        vistos.append(arquivo.read_text(encoding="utf-8") if arquivo.is_file() else None)
        return real(comando, env)

    monkeypatch.setattr(legacy_office, "_popen", _espiao)
    arquivo = tmp_path / "a.doc"
    arquivo.write_bytes(b"x")
    legacy_office.convert_to_pdf_bytes(arquivo, tmp_path / "soffice.exe")

    xcu = vistos[0]
    assert xcu is not None
    ET.fromstring(xcu)  # XML bem formado
    esperados = {
        ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
        ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
        ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
        ("/org.openoffice.Office.Calc/Content/Update", "Link", "2"),
        ("/org.openoffice.Office.Writer/Content/Update", "Link", "2"),
        ("/org.openoffice.Office.Writer/Content/Update", "Field", "false"),
        ("/org.openoffice.Office.Update/Update", "Enabled", "false"),
    }
    achados = set(re.findall(
        r'<item oor:path="([^"]+)"><prop oor:name="([^"]+)" oor:op="fuse"><value>([^<]*)</value>', xcu
    ))
    assert esperados <= achados


def _instalacao_do_sistema(tmp_path, monkeypatch, produto):
    base = tmp_path / "ProgramFiles"
    programa = base / "LibreOffice" / "program"
    programa.mkdir(parents=True)
    (programa / "soffice.exe").write_bytes(b"MZ")
    if produto is not None:
        (programa / "bootstrap.ini").write_text(f"[Bootstrap]\nProductKey={produto}\n", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(base))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    return programa / "soffice.exe"


@pytest.mark.parametrize(
    "produto, aceito",
    [("LibreOffice 7.5", False), ("LibreOffice 6.4", False), (None, False), ("Outra coisa", False),
     ("LibreOffice 7.6", True), ("LibreOffice 24.2", True), ("LibreOffice 26.2", True)],
)
def test_libreoffice_do_sistema_exige_versao_minima(tmp_path, monkeypatch, produto, aceito):
    exe = _instalacao_do_sistema(tmp_path, monkeypatch, produto)
    assert (legacy_office.soffice_path() == exe) is aceito


def test_componente_vem_antes_do_libreoffice_do_sistema(tmp_path, monkeypatch):
    _instalacao_do_sistema(tmp_path, monkeypatch, "LibreOffice 26.2")
    pasta = tmp_path / "componente"
    (pasta / "program").mkdir(parents=True)
    (pasta / "program" / "soffice.exe").write_bytes(b"MZ")
    monkeypatch.setattr(components, "path_of", lambda nome: pasta)
    assert legacy_office.soffice_path() == pasta / "program" / "soffice.exe"


# --- fila de reconversão: só o que ficou pendente por falta do componente --------------


def _linha(conn, nome, extensao, status, erro, ocr_failed):
    conn.execute(
        "INSERT INTO file (relative_path, name, extension, size, sha256, mtime, status, error, ocr_failed)"
        " VALUES (?, ?, ?, 1, '', 0, ?, ?, ?)",
        (nome, nome, extensao, status, erro, ocr_failed),
    )
    conn.commit()


def test_fila_de_reconversao_nao_reabre_o_que_a_varredura_recusou(tmp_path):
    origem, saida, config, conn = _projeto(tmp_path)
    recusados = ("secret", "binary", "archive", "blocked_extension", "unsupported")
    for erro in recusados:
        _linha(conn, f"{erro}.x", "x", "skipped", erro, 1)  # estado impossível, mas não pode reabrir
    _linha(conn, "pendente.doc", "doc", "skipped", "component_unavailable", 1)

    assert ocr_retry_count(conn) == 1
    conversion.requeue_ocr_failures(conn)
    estados = {r["name"]: r["status"] for r in conn.execute("SELECT name, status FROM file")}
    assert estados["pendente.doc"] == "discovered"
    assert all(estados[f"{e}.x"] == "skipped" for e in recusados)
    conn.close()


def test_varredura_zera_ocr_failed_quando_o_arquivo_vira_ignorado(tmp_path):
    from gclaude_indexer import scanning

    origem, saida, config, conn = _projeto(tmp_path)
    _linha(conn, "chave.doc", "doc", "skipped", "component_unavailable", 1)
    scanning._update_file(conn, "chave.doc", "chave.doc", "doc", 5, "", 1.0, None, "skipped", "secret")
    linha = conn.execute("SELECT status, error, ocr_failed FROM file").fetchone()
    assert (linha["status"], linha["error"], linha["ocr_failed"]) == ("skipped", "secret", 0)

    _linha(conn, "outro.pdf", "pdf", "failed", "x", 1)
    scanning._update_file(conn, "outro.pdf", "outro.pdf", "pdf", 5, "h", 1.0, None, "discovered")
    assert conn.execute("SELECT ocr_failed FROM file WHERE name = 'outro.pdf'").fetchone()[0] == 1
    conn.close()

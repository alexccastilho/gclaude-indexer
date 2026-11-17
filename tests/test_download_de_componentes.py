# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Download grande de componente: avisado antes e interrompido por Parar
(revisão final da 2.0.0, I2).

A primeira conversão com um `.doc` baixava 373 MB do LibreOffice (e a
primeira mídia, um modelo de até 1,5 GB) sem nada no log, com a barra
parada, e Parar só valia depois do fim. Todo download aqui é simulado: a
suíte nunca usa a rede.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest

from gclaude_indexer import components, legacy_office, ocr_languages
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.scanning import scan


@pytest.fixture(autouse=True)
def _pasta_local(tmp_path, monkeypatch):
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    # O idioma do OCR não é o assunto aqui.
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])


class _Resposta(io.BytesIO):
    """A resposta HTTP simulada; `ao_ler` roda a cada bloco lido."""

    def __init__(self, dados: bytes, ao_ler=None):
        super().__init__(dados)
        self.ao_ler = ao_ler
        self.blocos = 0

    def read(self, *args):
        bloco = super().read(*args)
        if bloco:
            self.blocos += 1
            if self.ao_ler is not None:
                self.ao_ler(self.blocos)
        return bloco

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _componente(dados: bytes) -> components.Component:
    return components.Component(
        name="modelo", url="https://example.invalid/modelo.bin", sha256=hashlib.sha256(dados).hexdigest(),
        size=len(dados), license="MIT", kind="file", target="teste/modelo.bin",
    )


def test_aviso_antes_do_download_e_nada_para_o_que_ja_existe(monkeypatch):
    dados = b"x" * 1000
    componente = _componente(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    ordem: list[str] = []
    monkeypatch.setattr(components, "_open_url", lambda url: ordem.append("rede") or _Resposta(dados))

    estado = components.ensure(["modelo"], on_download=lambda c: ordem.append(f"aviso {c.name} {c.size}"))
    assert estado == {"modelo": components.STATUS_INSTALLED}
    assert ordem == ["aviso modelo 1000", "rede"]

    ordem.clear()
    assert components.ensure(["modelo"], on_download=lambda c: ordem.append("aviso")) == {
        "modelo": components.STATUS_PRESENT
    }
    assert ordem == []


def test_erro_no_aviso_nao_impede_o_download(monkeypatch):
    dados = b"y" * 10
    componente = _componente(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    monkeypatch.setattr(components, "_open_url", lambda url: _Resposta(dados))

    def _quebra(_c):
        raise RuntimeError("banco ocupado")

    assert components.ensure(["modelo"], on_download=_quebra) == {"modelo": components.STATUS_INSTALLED}


def test_parar_no_meio_do_download_corta_e_apaga_o_parcial(monkeypatch):
    dados = b"z" * (3 * components._BLOCK + 10)
    componente = _componente(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    parar = {"agora": False}
    resposta = _Resposta(dados, ao_ler=lambda n: parar.update(agora=n >= 1))
    monkeypatch.setattr(components, "_open_url", lambda url: resposta)

    estado = components.ensure(["modelo"], should_stop=lambda: parar["agora"])

    assert estado == {"modelo": components.STATUS_UNAVAILABLE}
    # Um bloco lido e nenhum outro: o resto do arquivo nem é pedido.
    assert resposta.blocos == 1
    alvo = components.target_path(componente)
    assert not alvo.exists()
    assert not alvo.with_name(alvo.name + ".part").exists()
    assert components.path_of("modelo") is None


def test_parar_antes_nao_baixa_nada(monkeypatch):
    componente = _componente(b"w")
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    avisos: list = []
    monkeypatch.setattr(components, "_open_url", lambda url: pytest.fail("não devia abrir a rede"))
    estado = components.ensure(["modelo"], should_stop=lambda: True, on_download=avisos.append)
    assert estado == {"modelo": components.STATUS_UNAVAILABLE} and avisos == []


# --- na conversão ---------------------------------------------------------------


def _projeto(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Antigos", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["legados"],
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    (origem / "antigo.doc").write_bytes(b"\xd0\xcf\x11\xe0documento antigo")
    return origem, saida, config, conn


def test_conversao_avisa_nome_e_tamanho_antes_de_baixar_o_libreoffice(tmp_path, monkeypatch):
    """Com o manifesto de verdade: o aviso traz o nome e os megabytes do
    MSI fixado. A rede é a fechada pelo conftest, então o download falha
    e o arquivo fica pendente, como sempre."""
    _origem, _saida, config, conn = _projeto(tmp_path)
    monkeypatch.setattr(legacy_office, "_STANDARD_LOCATIONS", ())
    tamanho = round(components.get("libreoffice").size / 1_000_000)

    scan(conn, config)
    assert convert(conn, config, language="pt-BR").failed == 0

    eventos = list_events(conn, step="conversion", language="pt-BR")
    mensagens = [e["message"] for e in eventos]
    baixando = [i for i, m in enumerate(mensagens) if m.startswith("Baixando o LibreOffice")]
    assert len(baixando) == 1, mensagens
    assert f"({tamanho} MB)" in mensagens[baixando[0]]
    linha = conn.execute("SELECT status, error FROM file WHERE name = 'antigo.doc'").fetchone()
    assert tuple(linha) == ("skipped", "component_unavailable")
    conn.close()


def test_parar_durante_o_download_deixa_o_arquivo_pendente_sem_falha(tmp_path, monkeypatch):
    _origem, _saida, config, conn = _projeto(tmp_path)
    monkeypatch.setattr(legacy_office, "_STANDARD_LOCATIONS", ())
    dados = b"m" * (4 * components._BLOCK)
    componente = replace(
        components.get("libreoffice"), sha256=hashlib.sha256(dados).hexdigest(), size=len(dados),
    )
    monkeypatch.setattr(components, "manifest", lambda: {"libreoffice": componente})
    parar = {"agora": False}
    resposta = _Resposta(dados, ao_ler=lambda n: parar.update(agora=True))
    monkeypatch.setattr(components, "_open_url", lambda url: resposta)
    monkeypatch.setattr(components, "_run_msiexec", lambda *a: pytest.fail("não devia abrir o pacote"))

    scan(conn, config)
    resultado = convert(conn, config, should_stop=lambda: parar["agora"], language="pt-BR")

    assert resultado.failed == 0 and resposta.blocos == 1
    linha = conn.execute("SELECT status, error FROM file WHERE name = 'antigo.doc'").fetchone()
    # Continua na fila: a próxima conversão tenta de novo.
    assert tuple(linha) == ("discovered", None)
    mensagens = [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]
    assert any(m.startswith("Baixando o LibreOffice") for m in mensagens)
    assert not any("obter o LibreOffice" in m for m in mensagens), mensagens
    assert not list((tmp_path / "local").rglob("*.part"))
    conn.close()


def test_midia_avisa_cada_componente_que_vai_baixar():
    """`media.prepare` passa o aviso adiante; sem rede (conftest) nada vem,
    mas cada download tentado foi anunciado antes, com o tamanho."""
    from gclaude_indexer import media

    avisos: list = []
    ferramentas, faltando = media.prepare(on_download=lambda c: avisos.append((c.name, c.size)))
    assert ferramentas is None and faltando
    assert [nome for nome, _ in avisos] == ["ffmpeg", "whisper-cpp"]
    assert all(tamanho > 1_000_000 for _, tamanho in avisos)


# --- endereço de reserva (R1) ---------------------------------------------------


def _com_reserva(dados: bytes) -> components.Component:
    return replace(
        _componente(dados),
        url="https://estavel.invalid/modelo.bin",
        fallback_urls=("https://arquivo.invalid/modelo.bin",),
    )


@pytest.mark.parametrize("primeiro", ["sem_rede", "bytes_errados", "maior"])
def test_endereco_de_reserva_entra_quando_o_primeiro_falha(monkeypatch, primeiro):
    dados = b"r" * (components._BLOCK + 7)
    componente = _com_reserva(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    pedidos: list[str] = []

    def _abrir(url):
        pedidos.append(url)
        if url == componente.url:
            if primeiro == "sem_rede":
                raise OSError("404")
            if primeiro == "bytes_errados":
                return _Resposta(b"x" * len(dados))
            return _Resposta(dados + b"a mais")
        return _Resposta(dados)

    monkeypatch.setattr(components, "_open_url", _abrir)
    assert components.ensure(["modelo"]) == {"modelo": components.STATUS_INSTALLED}
    assert pedidos == list(componente.urls)
    assert components.path_of("modelo").read_bytes() == dados


def test_reserva_com_hash_errado_tambem_e_recusada(monkeypatch):
    dados = b"q" * 50
    componente = _com_reserva(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    monkeypatch.setattr(
        components, "_open_url",
        lambda url: (_ for _ in ()).throw(OSError("fora")) if url == componente.url else _Resposta(b"p" * 50),
    )
    assert components.ensure(["modelo"]) == {"modelo": components.STATUS_UNAVAILABLE}
    alvo = components.target_path(componente)
    assert not alvo.exists() and not alvo.with_name(alvo.name + ".part").exists()


def test_parar_nao_passa_para_o_endereco_de_reserva(monkeypatch):
    dados = b"s" * (2 * components._BLOCK)
    componente = _com_reserva(dados)
    monkeypatch.setattr(components, "manifest", lambda: {"modelo": componente})
    parar = {"agora": False}
    pedidos: list[str] = []

    def _abrir(url):
        pedidos.append(url)
        return _Resposta(dados, ao_ler=lambda n: parar.update(agora=True))

    monkeypatch.setattr(components, "_open_url", _abrir)
    assert components.ensure(["modelo"], should_stop=lambda: parar["agora"]) == {
        "modelo": components.STATUS_UNAVAILABLE
    }
    assert pedidos == [componente.url]


def test_manifesto_recusa_reserva_fora_do_https(tmp_path):
    import json

    entrada = {
        "name": "x", "url": "https://a.invalid/x.bin", "fallback_urls": ["http://b.invalid/x.bin"],
        "sha256": "0" * 64, "size": 1, "license": "MIT", "kind": "file", "target": "x/x.bin",
    }
    (tmp_path / "m.json").write_text(json.dumps({"format": 1, "components": [entrada]}), encoding="utf-8")
    with pytest.raises(ValueError, match="HTTPS"):
        components.load_manifest(tmp_path)


def test_libreoffice_tem_reserva_no_arquivo_da_tdf_com_o_mesmo_hash():
    """O "stable" da TDF some quando sai a versão seguinte; o arquivo
    histórico guarda o mesmo MSI (26.2.7.3, conferido byte a byte contra o
    SHA-256 fixado ao incluir a reserva). O hash continua um só."""
    item = components.load_manifest()["libreoffice"]
    assert item.url.startswith("https://download.documentfoundation.org/libreoffice/stable/")
    assert item.fallback_urls == (
        "https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.3/win/x86_64/"
        "LibreOffice_26.2.7.3_Win_x86-64.msi",
    )
    assert item.sha256 == "480fecf759fc6393bd614fbf43753eb95a8198fc1a065d41b727e3b664cd1e59"
    assert item.size == 373121024

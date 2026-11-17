"""2.0.0, Task 7 — gerenciador de componentes sob demanda.

Idiomas do OCR (e, nas Tasks 9 e 11, LibreOffice, ffmpeg e whisper.cpp)
são baixados na primeira vez em que fazem falta, só do manifesto fixado e
com SHA-256 conferido. Nada aqui acessa a rede: a resposta do servidor é
simulada em `components._open_url`.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gclaude_indexer import components, conversion, ocr_languages, tools
from gclaude_indexer.conversion import convert, ocr_retry_count, requeue_ocr_failures
from gclaude_indexer.events import list_events
from gclaude_indexer.scanning import scan

from .test_phase3 import _criar_pdf_escaneado, _preparar_projeto
from .test_phase30 import _tesseract_falso

# Capturado antes do conftest trocá-lo por um que nunca baixa: aqui o
# caminho de verdade (pelo gerenciador) é o que se testa.
_DOWNLOAD_DE_VERDADE = ocr_languages._download
_COMMIT = "65727574dfcd264acbb0c3e07860e4e9e9b22185"


@pytest.fixture(autouse=True)
def _pasta_local(tmp_path, monkeypatch):
    """Toda escrita vai para tmp_path: um teste de remoção contra a pasta
    privada real apagaria os idiomas do OCR desta máquina."""
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))
    return tmp_path / "local"


def _componente(nome: str, conteudo: bytes, kind: str = "file", target: str | None = None, **outros):
    return components.Component(
        name=nome,
        url=f"https://example.invalid/{nome}",
        sha256=outros.get("sha256", hashlib.sha256(conteudo).hexdigest()),
        size=outros.get("size", len(conteudo)),
        license="Apache-2.0",
        kind=kind,
        target=target or f"teste/{nome}.bin",
    )


def _manifesto(monkeypatch, *itens):
    monkeypatch.setattr(components, "manifest", lambda: {item.name: item for item in itens})


class _Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _servidor(monkeypatch, conteudos: dict[str, bytes], chamadas: list | None = None, atraso: float = 0.0):
    def _abrir(url):
        if chamadas is not None:
            chamadas.append(url)
        if atraso:
            time.sleep(atraso)
        nome = url.rsplit("/", 1)[1] if "/" in url else url
        for chave, dados in conteudos.items():
            if url.endswith("/" + chave):
                return _Resposta(dados)
        raise OSError(f"404 {nome}")

    monkeypatch.setattr(components, "_open_url", _abrir)


def _zip(membros: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        for nome, dados in membros.items():
            arquivo.writestr(nome, dados)
    return buffer.getvalue()


# --- download --------------------------------------------------------------------


def test_baixa_confere_e_grava_no_destino(monkeypatch, _pasta_local):
    item = _componente("dados", b"conteudo certo")
    _manifesto(monkeypatch, item)
    _servidor(monkeypatch, {"dados": b"conteudo certo"})

    assert components.ensure(["dados"]) == {"dados": components.STATUS_INSTALLED}
    destino = _pasta_local / "teste" / "dados.bin"
    assert destino.read_bytes() == b"conteudo certo"
    assert components.path_of("dados") == destino.resolve()
    # Já está lá: nada é baixado de novo.
    _servidor(monkeypatch, {})
    assert components.ensure(["dados"]) == {"dados": components.STATUS_PRESENT}


def test_hash_errado_e_recusado_e_o_part_apagado(monkeypatch, _pasta_local):
    item = _componente("dados", b"conteudo certo")
    _manifesto(monkeypatch, item)
    _servidor(monkeypatch, {"dados": b"conteudo trok"})  # mesmo tamanho, outro hash

    assert components.ensure(["dados"]) == {"dados": components.STATUS_UNAVAILABLE}
    pasta = _pasta_local / "teste"
    assert not (pasta / "dados.bin").exists()
    assert not (pasta / "dados.bin.part").exists()


def test_arquivo_maior_que_o_manifesto_e_cortado(monkeypatch, _pasta_local):
    item = _componente("dados", b"abc")
    _manifesto(monkeypatch, item)
    _servidor(monkeypatch, {"dados": b"abc" + b"x" * (3 << 20)})

    assert components.ensure(["dados"]) == {"dados": components.STATUS_UNAVAILABLE}
    assert list((_pasta_local / "teste").iterdir()) == []


def test_nome_fora_do_manifesto_fica_indisponivel_sem_rede(monkeypatch):
    chamadas = []
    _manifesto(monkeypatch)
    _servidor(monkeypatch, {}, chamadas)
    assert components.ensure(["tessdata/../../x"]) == {"tessdata/../../x": components.STATUS_UNAVAILABLE}
    assert chamadas == []


def test_sem_rede_fica_indisponivel(monkeypatch, _pasta_local):
    # A rede fechada é a do conftest.
    _manifesto(monkeypatch, _componente("dados", b"abc"))
    assert components.ensure(["dados"]) == {"dados": components.STATUS_UNAVAILABLE}
    assert components.path_of("dados") is None


def test_downloads_simultaneos_do_mesmo_componente_baixam_uma_vez(monkeypatch, _pasta_local):
    item = _componente("dados", b"conteudo")
    _manifesto(monkeypatch, item)
    chamadas = []
    _servidor(monkeypatch, {"dados": b"conteudo"}, chamadas, atraso=0.3)

    resultados = []
    linhas = [threading.Thread(target=lambda: resultados.append(components.ensure(["dados"])["dados"])) for _ in range(4)]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join()

    assert len(chamadas) == 1
    assert sorted(resultados) == sorted([components.STATUS_INSTALLED] + [components.STATUS_PRESENT] * 3)


def test_componente_grande_nao_segura_um_pequeno(monkeypatch, _pasta_local):
    grande = _componente("grande", b"g")
    pequeno = _componente("pequeno", b"p")
    _manifesto(monkeypatch, grande, pequeno)
    liberar = threading.Event()

    def _abrir(url):
        if url.endswith("/grande"):
            liberar.wait(5)
            return _Resposta(b"g")
        return _Resposta(b"p")

    monkeypatch.setattr(components, "_open_url", _abrir)
    linha = threading.Thread(target=lambda: components.ensure(["grande"]))
    linha.start()
    try:
        inicio = time.monotonic()
        assert components.ensure(["pequeno"]) == {"pequeno": components.STATUS_INSTALLED}
        assert time.monotonic() - inicio < 2
    finally:
        liberar.set()
        linha.join()


# --- ZIP ---------------------------------------------------------------------------


def test_zip_e_extraido_na_pasta_e_marcado(monkeypatch, _pasta_local):
    dados = _zip({"bin/programa.exe": b"MZ", "LEIAME.txt": b"oi"})
    item = _componente("programa", dados, kind="zip", target="programas/programa")
    _manifesto(monkeypatch, item)
    _servidor(monkeypatch, {"programa": dados})

    assert components.ensure(["programa"]) == {"programa": components.STATUS_INSTALLED}
    pasta = _pasta_local / "programas" / "programa"
    assert (pasta / "bin" / "programa.exe").read_bytes() == b"MZ"
    assert (pasta / components.ZIP_MARKER_NAME).is_file()
    assert not (pasta.parent / "programa.part").exists()
    assert not (pasta.parent / "programa.extracting").exists()


@pytest.mark.parametrize("membro", ["../fora.txt", "a/../../fora.txt", "/absoluto.txt", "C:/fora.txt", "a\\..\\..\\fora.txt"])
def test_zip_com_caminho_para_fora_e_recusado(monkeypatch, _pasta_local, membro):
    dados = _zip({"ok.txt": b"ok", membro: b"mal"})
    item = _componente("programa", dados, kind="zip", target="programas/programa")
    _manifesto(monkeypatch, item)
    _servidor(monkeypatch, {"programa": dados})

    assert components.ensure(["programa"]) == {"programa": components.STATUS_UNAVAILABLE}
    assert not (_pasta_local / "programas" / "programa").exists()
    assert not (_pasta_local / "fora.txt").exists()
    assert not (_pasta_local / "programas" / "fora.txt").exists()
    assert sorted(p.name for p in (_pasta_local / "programas").iterdir()) == []


# --- manifesto ------------------------------------------------------------------


def test_manifesto_do_pacote_tem_todos_os_idiomas_e_escritas_fixados():
    todos = components.load_manifest()
    tessdata = {nome: item for nome, item in todos.items() if nome.startswith("tessdata/")}
    assert len(tessdata) > 100
    # Os quatro de sempre continuam com os mesmos hashes (install.ps1, 1.10.x).
    assert tessdata["tessdata/por"].sha256 == "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb"
    assert tessdata["tessdata/eng"].sha256 == "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
    assert tessdata["tessdata/spa"].sha256 == "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464"
    assert tessdata["tessdata/osd"].sha256 == "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff"
    assert "tessdata/script/Latin" in tessdata and "tessdata/script/Cyrillic" in tessdata
    assert ocr_languages.downloadable("por") and ocr_languages.downloadable("script/Latin")
    assert not ocr_languages.downloadable("xyz")
    for nome, item in tessdata.items():
        assert item.url.startswith(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{_COMMIT}/")
        assert item.kind == "file" and item.license == "Apache-2.0"
        assert item.target == nome + ".traineddata"
        assert item.size > 0


def test_manifesto_invalido_e_recusado(tmp_path):
    bom = {"name": "a", "url": "https://x.example/a", "sha256": "0" * 64, "size": 1,
           "license": "MIT", "kind": "file", "target": "a/a.bin"}

    def _carregar(*entradas):
        pasta = tmp_path / f"m{len(list(tmp_path.iterdir()))}"
        pasta.mkdir()
        (pasta / "x.json").write_text(json.dumps({"format": 1, "components": list(entradas)}), encoding="utf-8")
        return components.load_manifest(pasta)

    assert set(_carregar(bom)) == {"a"}
    for errado in (
        {"url": "http://x.example/a"},
        {"sha256": "abc"},
        {"size": 0},
        {"kind": "exe"},
        {"target": "../fora.bin"},
        {"target": "C:/fora.bin"},
        {"target": "/fora.bin"},
        {"target": "a\\..\\b"},
    ):
        with pytest.raises(ValueError):
            _carregar({**bom, **errado})
    with pytest.raises(ValueError):
        _carregar(bom, bom)


# --- idiomas do OCR pelo gerenciador ------------------------------------------


def test_idioma_antigo_continua_sendo_baixado_pelo_gerenciador(tmp_path, monkeypatch, _pasta_local):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(ocr_languages, "_download", _DOWNLOAD_DE_VERDADE)
    exe = _tesseract_falso(tmp_path, ["eng"])
    por = _componente("tessdata/por", b"dados do por", target="tessdata/por.traineddata")
    osd = _componente("tessdata/osd", b"dados do osd", target="tessdata/osd.traineddata")
    _manifesto(monkeypatch, por, osd)
    _servidor(monkeypatch, {"tessdata/por": b"dados do por", "tessdata/osd": b"dados do osd"})

    assert ocr_languages.ensure("por", exe) == []
    privada = _pasta_local / "tessdata"
    assert (privada / "por.traineddata").read_bytes() == b"dados do por"
    assert (privada / "osd.traineddata").is_file()
    assert (privada / "eng.traineddata").is_file()  # copiado do Tesseract, como antes


def test_escrita_vai_para_a_subpasta_script(tmp_path, monkeypatch, _pasta_local):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(ocr_languages, "_download", _DOWNLOAD_DE_VERDADE)
    exe = _tesseract_falso(tmp_path, ["eng", "osd"])
    latin = _componente("tessdata/script/Latin", b"latin", target="tessdata/script/Latin.traineddata")
    _manifesto(monkeypatch, latin)
    _servidor(monkeypatch, {"Latin": b"latin"})

    assert ocr_languages.ensure("script/Latin", exe) == []
    assert (_pasta_local / "tessdata" / "script" / "Latin.traineddata").read_bytes() == b"latin"


def test_sem_rede_o_idioma_fica_faltando_pelo_gerenciador(tmp_path, monkeypatch):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(ocr_languages, "_download", _DOWNLOAD_DE_VERDADE)
    exe = _tesseract_falso(tmp_path, ["eng"])
    # Manifesto de verdade, rede fechada pelo conftest.
    assert ocr_languages.ensure("por+eng", exe) == ["por"]
    assert ocr_languages.usable("por+eng", exe) == ["eng"]


# --- conversão: sem o idioma, refaz depois e nunca falha ----------------------


def _imagem(caminho: Path):
    Image.new("RGB", (300, 100), "white").save(caminho)


def _sem_idioma(monkeypatch, usaveis: list[str]):
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: ["por"])
    monkeypatch.setattr(ocr_languages, "usable", lambda _lang, _exe: usaveis)
    monkeypatch.setattr(ocr_languages, "active_folder", lambda _exe: Path("C:/tesseract/tessdata"))
    real_find = tools.find
    monkeypatch.setattr(tools, "find", lambda nome: "C:/tesseract/tesseract.exe" if nome == "tesseract" else real_find(nome))


def _avisos(conn):
    return [e["message"] for e in list_events(conn, step="conversion", language="pt-BR")]


def test_sem_nenhum_idioma_a_imagem_e_o_escaneado_ficam_para_refazer(tmp_path, monkeypatch):
    origem, _saida, config, conn = _preparar_projeto(tmp_path)
    config = replace(config, parallelism="economy")
    _imagem(origem / "foto.png")
    _criar_pdf_escaneado(origem / "escaneado.pdf")
    scan(conn, config)
    _sem_idioma(monkeypatch, [])

    def _nao_chama(*_a, **_k):
        raise AssertionError("sem idioma não há OCR")

    monkeypatch.setattr(conversion, "_extract_text_image", _nao_chama)
    monkeypatch.setattr(conversion, "_run_ocrmypdf", _nao_chama)

    resultado = convert(conn, config, language="pt-BR")

    assert resultado.failed == 0
    for nome in ("foto.png", "escaneado.pdf"):
        linha = conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()
        assert linha["status"] == "converted", nome
        assert linha["ocr_failed"] == 1, nome
    assert any("idioma do OCR por" in m for m in _avisos(conn))
    assert ocr_retry_count(conn) == 2
    assert requeue_ocr_failures(conn) == 2
    conn.close()


def test_com_parte_dos_idiomas_le_com_o_que_tem_e_refaz_depois(tmp_path, monkeypatch):
    origem, _saida, config, conn = _preparar_projeto(tmp_path)
    config = replace(config, parallelism="economy", ocr_language="por+eng")
    _imagem(origem / "foto.png")
    scan(conn, config)
    _sem_idioma(monkeypatch, ["eng"])
    pedidos = []
    monkeypatch.setattr(conversion, "_extract_text_image", lambda _p, lang: pedidos.append(lang) or "texto")

    resultado = convert(conn, config, language="pt-BR")

    assert pedidos == ["eng"]
    assert resultado.failed == 0 and resultado.ocr_applied == 1
    linha = conn.execute("SELECT * FROM file WHERE name = 'foto.png'").fetchone()
    assert linha["status"] == "converted" and linha["ocr_failed"] == 1

    # O idioma chegou: a próxima conversão refaz e desmarca.
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])
    convert(conn, config, language="pt-BR")
    assert pedidos == ["eng", "por+eng"]
    linha = conn.execute("SELECT * FROM file WHERE name = 'foto.png'").fetchone()
    assert linha["status"] == "converted" and linha["ocr_failed"] == 0
    conn.close()


def test_sem_saber_a_pasta_do_tesseract_o_ocr_segue_como_antes(tmp_path, monkeypatch):
    origem, _saida, config, conn = _preparar_projeto(tmp_path)
    config = replace(config, parallelism="economy")
    _imagem(origem / "foto.png")
    scan(conn, config)
    _sem_idioma(monkeypatch, [])
    monkeypatch.setattr(ocr_languages, "active_folder", lambda _exe: None)
    pedidos = []
    monkeypatch.setattr(conversion, "_extract_text_image", lambda _p, lang: pedidos.append(lang) or "texto")

    convert(conn, config, language="pt-BR")

    assert pedidos == [config.ocr_language]
    linha = conn.execute("SELECT * FROM file WHERE name = 'foto.png'").fetchone()
    assert linha["status"] == "converted" and linha["ocr_failed"] == 0
    conn.close()


# --- tela: lista e remoção ------------------------------------------------------


@pytest.fixture
def instalado(monkeypatch, _pasta_local):
    item = _componente("tessdata/xyz", b"dados", target="tessdata/xyz.traineddata")
    _manifesto(monkeypatch, item)
    destino = _pasta_local / "tessdata" / "xyz.traineddata"
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"x" * 2048)
    return destino


def test_lista_os_componentes_baixados_com_tamanho(instalado):
    assert components.installed_components() == [components.InstalledComponent("tessdata/xyz", 2048, "Apache-2.0")]


def test_tela_sobre_lista_e_remove(instalado):
    from gclaude_indexer.web.app import app

    cliente = TestClient(app)
    tela = cliente.get("/about").text
    assert "tessdata/xyz" in tela and 'action="/about/components/remove"' in tela

    resposta = cliente.post(
        "/about/components/remove", data={"name": "tessdata/xyz"},
        headers={"Origin": "http://testserver"}, follow_redirects=False,
    )
    assert resposta.status_code == 303
    assert not instalado.exists()
    assert "foi removido" in cliente.get(resposta.headers["location"]).text


def test_remocao_vinda_de_outro_site_e_recusada(instalado):
    from gclaude_indexer.web.app import app

    resposta = TestClient(app).post(
        "/about/components/remove", data={"name": "tessdata/xyz"},
        headers={"Origin": "https://site-malicioso.example"}, follow_redirects=False,
    )
    assert resposta.status_code == 403
    assert instalado.exists()


def test_remocao_so_de_nome_do_manifesto(instalado, _pasta_local):
    from gclaude_indexer.web.app import app

    alvo = _pasta_local / "outro.txt"
    alvo.write_text("fica")
    resposta = TestClient(app).post(
        "/about/components/remove", data={"name": "../outro.txt"},
        headers={"Origin": "http://testserver"}, follow_redirects=False,
    )
    assert resposta.status_code == 303
    assert alvo.exists() and instalado.exists()
    assert components.remove("../outro.txt") is False

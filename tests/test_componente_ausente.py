# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Arquivo à espera de um componente (LibreOffice, ffmpeg/whisper) não é
"alterado" a cada execução (revisão final da 2.0.0, I1).

Sem rede, o `.doc` e o vídeo ficam `skipped`/`component_unavailable` com
`ocr_failed = 1`. Antes da correção, o plano de atualização via essa marca
como "alterado" e a execução descartava as janelas do grupo inteiro em toda
rodada, e o aviso de "Atualizar" nunca sumia. Agora o plano só os aponta
quando o componente está nesta máquina, sem ler os bytes; até lá eles
esperam fora da fila enquanto o grupo tem janelas (como os `extracted` cujo
OCR falhou), mesmo editados: o plano os deixa quietos e a varredura grava o
hash novo sem tirá-los da espera.
"""

from __future__ import annotations

from dataclasses import replace

import fitz
import pytest

from gclaude_indexer import legacy_office, media, update_plan
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert, ocr_retry_count
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.file_types import is_waiting_component
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.invalidation import apply_pending_changes
from gclaude_indexer.scanning import scan
from gclaude_indexer.update_plan import build_update_plan
from gclaude_indexer.windows_prep import prepare_windows


@pytest.fixture(autouse=True)
def _pasta_local(tmp_path, monkeypatch):
    monkeypatch.setenv("GCLAUDE_INDEXER_LOCAL_FOLDER", str(tmp_path / "local"))


def _pdf(caminho, textos):
    documento = fitz.open()
    for texto in textos:
        pagina = documento.new_page()
        pagina.insert_text((72, 72), texto)
    documento.save(str(caminho))
    documento.close()


def _projeto(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Espera", "source_folder": str(origem), "output_folder": str(saida),
        "extensions": ["legados", "pdf", "midia"],
        "pages_per_window": 2, "overlap": 0,
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    (origem / "a_antigo.doc").write_bytes(b"\xd0\xcf\x11\xe0documento antigo")
    _pdf(origem / "b.pdf", ["Primeira página do b com texto nativo.", "Segunda página do b."])
    _pdf(origem / "c.pdf", ["Primeira página do c com texto nativo.", "Segunda página do c.",
                            "Terceira página do c."])
    (origem / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42video")
    return origem, saida, config, conn


@pytest.fixture
def sem_componentes(monkeypatch):
    """Nem LibreOffice nem ffmpeg/whisper nesta máquina, e a rede fechada.
    Devolve a lista do que a conversão pediu para baixar."""
    pedidos: list[str] = []

    def _libreoffice(**_k):
        pedidos.append("libreoffice")
        return None

    def _midia(download=True, **_k):
        pedidos.append("midia")
        return None, ["ffmpeg", "whisper.cpp", "Whisper small"]

    monkeypatch.setattr(legacy_office, "soffice_path", lambda: None)
    monkeypatch.setattr(legacy_office, "ensure_available", _libreoffice)
    monkeypatch.setattr(media, "prepare", _midia)
    monkeypatch.setattr(media, "tools_present", lambda: False, raising=False)
    return pedidos


def _rodada(conn, config):
    """O que "Executar" faz, sem a classificação: a atualização automática
    antes da varredura e as quatro etapas."""
    aplicado = apply_pending_changes(conn, config, language="pt-BR")
    scan(conn, config, language="pt-BR")
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config, language="pt-BR")
    prepare_windows(conn, config, language="pt-BR")
    return aplicado


def _janelas(conn):
    return [(r["key"], r["status"]) for r in conn.execute("SELECT key, status FROM window ORDER BY key")]


def _estado(conn, nome):
    linha = conn.execute("SELECT status, error, ocr_failed FROM file WHERE name = ?", (nome,)).fetchone()
    return tuple(linha)


def test_sem_componente_nada_e_descartado_nas_rodadas_seguintes(tmp_path, sem_componentes):
    _origem, _saida, config, conn = _projeto(tmp_path)

    assert _rodada(conn, config) is None
    janelas = _janelas(conn)
    assert janelas, "o grupo precisa ter janelas para o teste valer"
    for nome in ("a_antigo.doc", "video.mp4"):
        assert _estado(conn, nome) == ("skipped", "component_unavailable", 1)
    # Marca as janelas como já classificadas: um descarte as traria de volta
    # como pendentes, com outra chave ou sem linha.
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    classificadas = _janelas(conn)

    for _ in range(2):
        assert _rodada(conn, config) is None
        assert _janelas(conn) == classificadas
        plano = build_update_plan(conn, config, record_warnings=False)
        assert plano.changed == () and plano.groups == () and plano.is_empty
        for nome in ("a_antigo.doc", "video.mp4"):
            assert _estado(conn, nome) == ("skipped", "component_unavailable", 1)

    mensagens = [e["message"] for e in list_events(conn, language="pt-BR")]
    assert not any("descartado(s) para nova classificação" in m for m in mensagens), mensagens
    # Esperam fora da fila: a tela de execução não os conta como pendentes.
    assert ocr_retry_count(conn) == 0
    # Mas a conversão segue tentando obter o componente (a rede pode ter
    # voltado), e diz no log por que eles ficaram de fora.
    assert sem_componentes.count("libreoffice") >= 3 and sem_componentes.count("midia") >= 3
    assert any("a_antigo.doc" in m and "LibreOffice" in m for m in mensagens), mensagens
    conn.close()


def test_com_o_componente_presente_o_arquivo_e_apontado_e_entra(tmp_path, sem_componentes, monkeypatch):
    _origem, _saida, config, conn = _projeto(tmp_path)
    _rodada(conn, config)
    assert _janelas(conn)
    assert build_update_plan(conn, config, record_warnings=False).changed == ()

    # O LibreOffice apareceu (baixado numa conversão, ou instalado na máquina).
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso)
    plano = build_update_plan(conn, config, record_warnings=False)
    assert [c.relative_path for c in plano.changed] == ["a_antigo.doc"]
    assert plano.groups, "o grupo do arquivo tem janelas a refazer"

    # O ffmpeg/whisper também.
    monkeypatch.setattr(media, "tools_present", lambda: True)
    plano = build_update_plan(conn, config, record_warnings=False)
    assert sorted(c.relative_path for c in plano.changed) == ["a_antigo.doc", "video.mp4"]

    # A execução aplica a atualização por conta própria: o arquivo volta à
    # fila e as janelas do grupo são refeitas a partir dele.
    resultado = apply_pending_changes(conn, config, language="pt-BR")
    assert resultado is not None and resultado.files_reset == 2
    for nome in ("a_antigo.doc", "video.mp4"):
        assert _estado(conn, nome)[0] == "discovered"
    conn.close()


def test_grupo_sem_janelas_devolve_o_arquivo_a_fila(tmp_path, sem_componentes):
    """Sem janelas no grupo não há o que desatualizar: o arquivo volta à
    fila como antes, e a conversão tenta de novo."""
    origem, _saida, config, conn = _projeto(tmp_path)
    for nome in ("b.pdf", "c.pdf", "video.mp4"):
        (origem / nome).unlink()
    scan(conn, config)
    convert(conn, config)
    assert _estado(conn, "a_antigo.doc") == ("skipped", "component_unavailable", 1)
    assert ocr_retry_count(conn) == 1
    convert(conn, config)
    assert sem_componentes.count("libreoffice") == 2
    conn.close()


@pytest.mark.parametrize("desfecho", ["converte", "falha"])
def test_depois_de_entrar_a_rodada_seguinte_fica_quieta(tmp_path, sem_componentes, monkeypatch, desfecho):
    """Com o componente presente o arquivo entra uma vez só: convertido ou
    falhado por outro motivo (`.doc` corrompido), a rodada seguinte não o
    aponta de novo nem descarta janelas."""
    _origem, _saida, config, conn = _projeto(tmp_path)
    (_origem / "video.mp4").unlink()
    _rodada(conn, config)
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso)

    def _pdf_do_doc(_origem_doc, _soffice):
        if desfecho == "falha":
            raise legacy_office.LegacyOfficeError("documento corrompido")
        documento = fitz.open()
        documento.new_page().insert_text((72, 72), "Texto do documento antigo convertido.")
        dados = documento.tobytes()
        documento.close()
        return dados

    monkeypatch.setattr(legacy_office, "convert_to_pdf_bytes", _pdf_do_doc)
    assert _rodada(conn, config) is not None  # entra: janelas do grupo refeitas
    esperado = "extracted" if desfecho == "converte" else "failed"
    assert _estado(conn, "a_antigo.doc")[0] == esperado
    assert _estado(conn, "a_antigo.doc")[2] == 0
    janelas = _janelas(conn)

    assert _rodada(conn, config) is None
    assert _janelas(conn) == janelas
    assert build_update_plan(conn, config, record_warnings=False).is_empty
    conn.close()


def _sem_ler_bytes(monkeypatch):
    """O plano não pode ler o arquivo em espera: no Drive, cada leitura é
    um download, e um vídeo de 2 GB seria baixado a cada abertura da tela."""
    def _proibido(caminho):
        raise AssertionError(f"o plano leu {caminho}")

    monkeypatch.setattr(update_plan, "compute_hash", _proibido)


def test_arquivo_em_espera_editado_sem_o_componente_nao_mexe_nas_janelas(tmp_path, sem_componentes, monkeypatch):
    """O `.doc` em espera foi editado enquanto o LibreOffice faltava. Sem o
    componente ele continua com zero páginas e o grupo sai idêntico: o plano
    o deixa quieto, sem ler os bytes, e a varredura só grava o hash novo,
    mantendo-o em espera. A rede volta e a conversão desta rodada obtém o
    LibreOffice, mas não o converte (as páginas cairiam por cima das janelas
    já classificadas); a rodada seguinte o aponta como alterado e refaz as
    janelas do grupo junto."""
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "video.mp4").unlink()
    _rodada(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    classificadas = _janelas(conn)

    (origem / "a_antigo.doc").write_bytes(b"\xd0\xcf\x11\xe0documento antigo EDITADO com mais bytes")
    with monkeypatch.context() as m:
        _sem_ler_bytes(m)
        assert build_update_plan(conn, config, record_warnings=False).is_empty

    _libreoffice_chega_na_conversao(tmp_path, monkeypatch)
    assert _rodada(conn, config) is None
    assert _estado(conn, "a_antigo.doc") == ("skipped", "component_unavailable", 1)
    assert _janelas(conn) == classificadas

    plano = build_update_plan(conn, config, record_warnings=False)
    assert [c.relative_path for c in plano.changed] == ["a_antigo.doc"]
    resultado = _rodada(conn, config)
    assert resultado is not None and resultado.windows_deleted > 0
    assert _estado(conn, "a_antigo.doc")[0] == "extracted"
    # Janelas coerentes: nenhuma classificada sobrou de antes, nada sobreposto.
    assert all(status != "done" for _key, status in _janelas(conn)), _janelas(conn)
    conn.close()


def test_edicao_sem_o_componente_atravessa_varias_rodadas_sem_descartar(tmp_path, sem_componentes):
    origem, _saida, config, conn = _projeto(tmp_path)
    _rodada(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    classificadas = _janelas(conn)

    (origem / "a_antigo.doc").write_bytes(b"\xd0\xcf\x11\xe0documento antigo EDITADO com mais bytes")
    (origem / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42video editado e maior")
    for _ in range(3):
        assert _rodada(conn, config) is None
        assert _janelas(conn) == classificadas
        assert build_update_plan(conn, config, record_warnings=False).is_empty
        for nome in ("a_antigo.doc", "video.mp4"):
            assert _estado(conn, nome) == ("skipped", "component_unavailable", 1)
    # A varredura gravou os bytes novos: a próxima não lê nada de novo.
    for nome in ("a_antigo.doc", "video.mp4"):
        linha = conn.execute("SELECT size FROM file WHERE name = ?", (nome,)).fetchone()
        assert linha["size"] == (origem / nome).stat().st_size
    conn.close()


def test_edicao_do_mesmo_tamanho_grava_o_hash_novo_e_continua_em_espera(tmp_path, sem_componentes, monkeypatch):
    import os

    origem, _saida, config, conn = _projeto(tmp_path)
    _rodada(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    classificadas = _janelas(conn)
    caminho = origem / "a_antigo.doc"
    antes = caminho.stat()
    hash_antigo = conn.execute("SELECT sha256 FROM file WHERE name = 'a_antigo.doc'").fetchone()[0]

    caminho.write_bytes(b"\xd0\xcf\x11\xe0DOCUMENTO ANTIGO")  # mesmo tamanho, bytes outros
    assert caminho.stat().st_size == antes.st_size
    os.utime(caminho, (antes.st_atime, antes.st_mtime + 60))
    with monkeypatch.context() as m:
        _sem_ler_bytes(m)
        assert build_update_plan(conn, config, record_warnings=False).is_empty

    assert _rodada(conn, config) is None
    assert _janelas(conn) == classificadas
    assert _estado(conn, "a_antigo.doc") == ("skipped", "component_unavailable", 1)
    assert conn.execute("SELECT sha256 FROM file WHERE name = 'a_antigo.doc'").fetchone()[0] != hash_antigo

    # Com o componente, sai como alterado (sem ler os bytes: o que falta é a
    # conversão, não a comparação).
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso)
    _sem_ler_bytes(monkeypatch)
    plano = build_update_plan(conn, config, record_warnings=False)
    assert [c.relative_path for c in plano.changed] == ["a_antigo.doc"]
    conn.close()


def test_video_em_espera_editado_so_sai_como_alterado_com_o_componente(tmp_path, sem_componentes, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    _rodada(conn, config)
    (origem / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42video editado e maior")
    _sem_ler_bytes(monkeypatch)
    assert build_update_plan(conn, config, record_warnings=False).is_empty
    monkeypatch.setattr(media, "tools_present", lambda: True)
    plano = build_update_plan(conn, config, record_warnings=False)
    assert [c.relative_path for c in plano.changed] == ["video.mp4"]
    conn.close()


def test_arquivo_em_espera_com_so_a_data_mexida_continua_quieto(tmp_path, sem_componentes):
    """O Drive reescreve a data sem mudar o conteúdo: sem o componente, o
    plano deixa o arquivo em espera quieto sem ler os bytes, e a varredura,
    que lê, vê o mesmo hash e só grava a data nova."""
    import os

    origem, _saida, config, conn = _projeto(tmp_path)
    _rodada(conn, config)
    caminho = origem / "a_antigo.doc"
    os.utime(caminho, (caminho.stat().st_atime, caminho.stat().st_mtime + 3600))
    assert build_update_plan(conn, config, record_warnings=False).changed == ()
    assert _rodada(conn, config) is None
    conn.close()


def _libreoffice_chega_na_conversao(tmp_path, monkeypatch):
    """A rede volta no meio da execução: a próxima conversão obtém o
    LibreOffice (falso) e o `.doc` vira um PDF de uma página."""
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"MZ")
    estado = {"tem": False}
    monkeypatch.setattr(legacy_office, "soffice_path", lambda: falso if estado["tem"] else None)

    def _obtem(**_k):
        estado["tem"] = True
        return falso

    def _pdf_do_doc(_origem_doc, _soffice):
        documento = fitz.open()
        documento.new_page().insert_text((72, 72), "Texto do documento antigo editado.")
        dados = documento.tobytes()
        documento.close()
        return dados

    monkeypatch.setattr(legacy_office, "ensure_available", _obtem)
    monkeypatch.setattr(legacy_office, "convert_to_pdf_bytes", _pdf_do_doc)


def test_varredura_sem_a_atualizacao_antes_mantem_o_arquivo_em_espera(tmp_path, sem_componentes, monkeypatch):
    """A atualização automática antes da varredura falhou (pasta
    inalcançável num instante, Parar) e a varredura rodou assim mesmo sobre
    o `.doc` em espera, editado. Ela grava o hash novo, mas o arquivo
    continua em espera: se virasse `discovered`, a conversão que obtém o
    LibreOffice na mesma execução poria as páginas no começo do grupo, por
    cima das janelas já classificadas, sem que nada as invalidasse."""
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "video.mp4").unlink()
    _rodada(conn, config)
    conn.execute("UPDATE window SET status = 'done'")
    conn.commit()
    classificadas = _janelas(conn)
    hash_antigo = conn.execute("SELECT sha256 FROM file WHERE name = 'a_antigo.doc'").fetchone()[0]

    (origem / "a_antigo.doc").write_bytes(b"\xd0\xcf\x11\xe0documento antigo EDITADO com mais bytes")
    varredura = scan(conn, config, language="pt-BR")  # sem `apply_pending_changes` antes
    # Continua em espera: não é "atualizado" (não volta à fila), e o log diz
    # que o conteúdo mudou e que ele segue aguardando o componente, sem
    # prometer que será processado.
    assert varredura.updated == 0 and varredura.waiting_updated == 1
    # E o resumo da varredura fecha a conta com ele.
    resumo = conn.execute(
        "SELECT message FROM event WHERE message_key LIKE 'log.scan.summary%' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "1 alterado(s) à espera de componente" in resumo, resumo
    assert conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.scan.content_changed_waiting'"
        " AND message LIKE '%a_antigo.doc%'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.scan.content_changed'"
    ).fetchone()[0] == 0
    linha = conn.execute("SELECT sha256, size FROM file WHERE name = 'a_antigo.doc'").fetchone()
    assert linha["sha256"] != hash_antigo
    assert linha["size"] == (origem / "a_antigo.doc").stat().st_size
    assert _estado(conn, "a_antigo.doc") == ("skipped", "component_unavailable", 1)

    _libreoffice_chega_na_conversao(tmp_path, monkeypatch)
    convert(conn, config, language="pt-BR")
    extract_pages(conn, config, language="pt-BR")
    prepare_windows(conn, config, language="pt-BR")
    # Esta execução só obteve o componente: nenhuma página nova, janelas intactas.
    assert _estado(conn, "a_antigo.doc") == ("skipped", "component_unavailable", 1)
    assert _janelas(conn) == classificadas

    # A seguinte o aponta como alterado e refaz as janelas do grupo.
    resultado = _rodada(conn, config)
    assert resultado is not None and resultado.windows_deleted > 0
    assert _estado(conn, "a_antigo.doc")[0] == "extracted"
    assert all(status != "done" for _key, status in _janelas(conn)), _janelas(conn)
    conn.close()


def test_predicado_unico_do_arquivo_em_espera():
    assert is_waiting_component("skipped", "component_unavailable")
    assert not is_waiting_component("skipped", "secret")
    assert not is_waiting_component("discovered", "component_unavailable")
    assert not is_waiting_component("extracted", None)

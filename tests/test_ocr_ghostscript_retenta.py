"""2.1.4: falha passageira do Ghostscript não marca o arquivo para refazer.

No processo 52 (1.227 páginas), o OCR de 2 páginas falhou com "Ghostscript
rasterizing failed" (código 7) enquanto vários arquivos rodavam juntos. As
mesmas páginas, de novo, passaram. Antes o arquivo seguia sem essas páginas
e ficava marcado para refazer o OCR na próxima conversão.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gclaude_indexer import conversion

GS_FALHOU = (
    " 1066 GPL Ghostscript 10.07.1: Unrecoverable error, exit code 255\n"
    "SubprocessOutputError: Ghostscript rasterizing failed"
)


def _rodadas(monkeypatch, resultados):
    chamadas = []

    def run_hidden(command, env=None):
        chamadas.append(command)
        return resultados[len(chamadas) - 1]

    monkeypatch.setattr(conversion, "run_hidden", run_hidden)
    return chamadas


def _jobs(command):
    return command[command.index("--jobs") + 1]


def test_falha_do_ghostscript_tenta_de_novo_com_um_processo(tmp_path, monkeypatch):
    chamadas = _rodadas(monkeypatch, [
        SimpleNamespace(returncode=7, stderr=GS_FALHOU, stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout=""),
    ])
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=4, pages=[1066, 1068])
    assert len(chamadas) == 2
    assert (_jobs(chamadas[0]), _jobs(chamadas[1])) == ("4", "1")


def test_ghostscript_que_falha_de_novo_vira_erro(tmp_path, monkeypatch):
    chamadas = _rodadas(monkeypatch, [SimpleNamespace(returncode=7, stderr=GS_FALHOU, stdout="")] * 2)
    with pytest.raises(conversion.OcrError):
        conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=4, pages=[1])
    assert len(chamadas) == 2


def test_outra_falha_nao_tenta_de_novo(tmp_path, monkeypatch):
    chamadas = _rodadas(monkeypatch, [SimpleNamespace(returncode=2, stderr="argumento inválido", stdout="")])
    with pytest.raises(conversion.OcrError):
        conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=4, pages=[1])
    assert len(chamadas) == 1


def test_nova_tentativa_ainda_tem_o_arquivo_de_paginas(tmp_path, monkeypatch):
    # Com muitas páginas, `--pages` vai num `@arquivo`; ele tem de existir
    # também na segunda rodada.
    monkeypatch.setattr(conversion, "_PAGES_INLINE_MAX_CHARS", 0)
    vistos = []

    def run_hidden(command, env=None):
        argfile = next(arg[1:] for arg in command if arg.startswith("@"))
        vistos.append(open(argfile, encoding="utf-8").read())
        return SimpleNamespace(returncode=7 if len(vistos) == 1 else 0, stderr=GS_FALHOU, stdout="")

    monkeypatch.setattr(conversion, "run_hidden", run_hidden)
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=2, pages=[1, 3])
    assert vistos == ["--pages\n1,3\n"] * 2
    assert not list(tmp_path.glob("*.args"))


def test_ocr_do_arquivo_inteiro_nao_tenta_de_novo(tmp_path, monkeypatch):
    # Sem `pages` o ocrmypdf lê o arquivo todo; refazer com um processo só
    # pode dobrar o tempo de um livro inteiro. Fica para a próxima conversão.
    chamadas = _rodadas(monkeypatch, [SimpleNamespace(returncode=7, stderr=GS_FALHOU, stdout="")])
    with pytest.raises(conversion.OcrError):
        conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", jobs=4)
    assert len(chamadas) == 1

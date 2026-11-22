"""2.1.3: PDF escaneado de milhares de páginas.

O `--pages` levava a lista de páginas por extenso ("15,17,19,..."). Num PDF
de 8.201 páginas escaneadas a lista passava de 39 mil caracteres, acima do
limite de 32.767 da linha de comando do Windows, e o arquivo inteiro falhava
com `[WinError 206] O nome do arquivo ou a extensão é muito grande`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ocrmypdf._validation import _pages_from_ranges
from ocrmypdf.cli import get_parser

from gclaude_indexer import conversion

# Limite do `CreateProcess` no Windows, em caracteres, para a linha inteira.
WINDOWS_COMMAND_LINE_LIMIT = 32767


def _capture(monkeypatch) -> dict:
    captured: dict = {}

    def fake_run_hidden(command, env=None, **_kwargs):
        captured["command"] = list(command)
        # O arquivo de argumentos só existe enquanto o ocrmypdf roda.
        captured["argfiles"] = {
            arg: Path(arg[1:]).read_text(encoding="utf-8") for arg in command if arg.startswith("@")
        }
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(conversion, "run_hidden", fake_run_hidden)
    return captured


def _ocrmypdf_pages(captured: dict, tmp_path: Path) -> set[int]:
    """As páginas (contadas do 0) que o próprio ocrmypdf lê do comando
    montado. O arquivo `@` já foi apagado: volta aqui como foi gravado."""
    runner = captured["command"].index("gclaude_indexer._ocr_runner")
    args: list[str] = []
    for arg in captured["command"][runner + 1 :]:
        args.extend(captured["argfiles"][arg].split() if arg in captured["argfiles"] else [arg])
    options = get_parser().parse_args(args)
    return _pages_from_ranges(options.pages)


def _pdf(path: Path, pages: int) -> None:
    import fitz

    document = fitz.open()
    for _ in range(pages):
        document.new_page()
    document.save(path)
    document.close()


def _exit_code(monkeypatch, code: int, write_pages: int | None):
    def fake_run_hidden(command, env=None, **_kwargs):
        if write_pages is not None:
            _pdf(Path(command[-1]), write_pages)
        return subprocess.CompletedProcess(command, code, "", "The generated PDF is INVALID")

    monkeypatch.setattr(conversion, "run_hidden", fake_run_hidden)


# 2.1.3: código 4 do ocrmypdf é "saída gravada, mas a validação reclamou". Um
# original com número malformado no conteúdo ("5.68434E") dava isso, e o OCR
# de 7 páginas, bom, era jogado fora.
def test_codigo_4_com_saida_completa_fica_com_o_ocr(tmp_path, monkeypatch):
    _pdf(tmp_path / "a.pdf", 3)
    _exit_code(monkeypatch, 4, write_pages=3)
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", pages=[2])
    assert (tmp_path / "b.pdf").exists()


def test_codigo_4_sem_saida_continua_falhando(tmp_path, monkeypatch):
    import pytest

    _pdf(tmp_path / "a.pdf", 3)
    _exit_code(monkeypatch, 4, write_pages=None)
    with pytest.raises(conversion.OcrError):
        conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", pages=[2])


def test_codigo_4_com_saida_truncada_continua_falhando(tmp_path, monkeypatch):
    import pytest

    _pdf(tmp_path / "a.pdf", 3)
    _exit_code(monkeypatch, 4, write_pages=1)
    with pytest.raises(conversion.OcrError):
        conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", pages=[2])


def test_intervalos_compactam_paginas_seguidas():
    assert conversion._page_ranges([1, 2, 3, 5, 7, 8, 10]) == "1-3,5,7-8,10"


def test_livro_escaneado_inteiro_cabe_na_linha_de_comando(tmp_path, monkeypatch):
    captured = _capture(monkeypatch)
    pages = [n for n in range(1, 8202) if n not in (5, 900, 4000, 8000)]
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", pages=pages)

    assert len(subprocess.list2cmdline(captured["command"])) < WINDOWS_COMMAND_LINE_LIMIT
    assert _ocrmypdf_pages(captured, tmp_path) == {n - 1 for n in pages}


def test_paginas_alternadas_vao_por_arquivo_de_argumentos(tmp_path, monkeypatch):
    # Pior caso: nenhuma página seguida da outra, intervalos não ajudam.
    captured = _capture(monkeypatch)
    pages = list(range(1, 19000, 2))
    conversion._run_ocrmypdf(tmp_path / "a.pdf", tmp_path / "b.pdf", "por", pages=pages)

    assert len(subprocess.list2cmdline(captured["command"])) < WINDOWS_COMMAND_LINE_LIMIT
    assert captured["argfiles"], "a lista longa deveria ir num arquivo @"
    assert _ocrmypdf_pages(captured, tmp_path) == {n - 1 for n in pages}
    assert not list(tmp_path.glob("*.args")), "o arquivo de argumentos deve ser apagado"

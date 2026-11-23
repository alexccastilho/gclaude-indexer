"""2.1.3: OSD de páginas quase vazias pedindo escritas que o documento não tem.

Nos volumes do Conselho Federal de Odontologia (português), as poucas páginas
com assinatura ou carimbo davam ao OSD "Greek", "Arabic", "Devanagari" com
confiança de 0 a 11 — a mesma faixa de uma página grega de verdade, então a
confiança não separa os casos. Cada uma marcava o arquivo inteiro para ser
refeito com `por+script/Arabic+script/Devanagari` (`ocr_failed`). Um modelo
ausente só é pedido para o arquivo quando as páginas fracas são a maioria do
que passou pelo OCR: aí sim o idioma do plano não serviu.
"""

from __future__ import annotations

import fitz

from gclaude_indexer import conversion

TEXTO = "O Conselho Federal de Odontologia aprovou o parecer da comissão de ética. " * 4


def _pdf(path, weak_pages: set[int], total: int):
    document = fitz.open()
    for number in range(1, total + 1):
        page = document.new_page(width=595, height=842)
        if number not in weak_pages:
            page.insert_textbox(fitz.Rect(50, 50, 545, 800), TEXTO, fontsize=11)
    document.save(path)
    document.close()


def _reread(tmp_path, monkeypatch, weak: set[int], total: int, ocr_pages: list[int] | None = None) -> list[str]:
    source = tmp_path / "origem.pdf"
    destination = tmp_path / "lido.pdf"
    _pdf(source, weak, total)
    _pdf(destination, weak, total)
    monkeypatch.setattr(conversion, "_reread_model", lambda image, used, usable: ("script/Arabic", 0, True))
    missing, _read = conversion._reread_weak_pdf_pages(
        "vol.pdf", source, destination, ocr_pages or list(range(1, total + 1)), ["por"], ["por", "osd"],
        1, False, [], {},
    )
    return missing


def test_poucas_paginas_fracas_nao_pedem_escrita_ausente(tmp_path, monkeypatch):
    assert _reread(tmp_path, monkeypatch, weak={3, 7}, total=12) == []


def test_documento_quase_todo_ilegivel_ainda_pede_a_escrita(tmp_path, monkeypatch):
    assert _reread(tmp_path, monkeypatch, weak=set(range(1, 11)), total=12) == ["script/Arabic"]


# 2.1.4: no projeto recriado, 8 volumes do CFO ainda pediam japonês, grego,
# árabe ou cirílico. Só uma parte pequena do volume é escaneada (17 de 316
# páginas no Vol 4: slides com um título), e essas páginas são quase todas
# fracas. A maioria tem de ser do documento, não só das páginas escaneadas.


def test_slides_escaneados_num_volume_de_texto_nao_pedem_escrita(tmp_path, monkeypatch):
    escaneadas = list(range(290, 307))
    fracas = set(escaneadas[:15])
    assert _reread(tmp_path, monkeypatch, weak=fracas, total=316, ocr_pages=escaneadas) == []

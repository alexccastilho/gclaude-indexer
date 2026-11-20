# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Sampling a collection: PDF text per page and the language of the text.

Until 2.0.0 this module proposed the "Slicing, windows and OCR" values in a
panel of the New project form. The section and the panel are gone; what
remains is the way of *looking* at a collection, which `auto_settings.py`
reuses after the scan: a handful of PDFs are opened (a few pages each) and a
handful of text files are read, never the whole collection.

The scan's own listing is what the automatic settings read: this module never
walks a folder by itself.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .ocr_detection import MIN_AVG_CHARS_PER_PAGE


_PDF_SAMPLE = 12
_PDF_PAGES_SAMPLED = 6
_TEXT_SAMPLE = 16
_TEXT_BYTES = 64 * 1024


_MULTI_PAGE_CATEGORIES = {"pdf", "imagens", "paginados", "legados"}

@dataclass
class FolderSurvey:
    files: int = 0
    by_category: Counter = field(default_factory=Counter)
    partial: bool = False
    seconds: float = 0.0
    pdf_pages: list[int] = field(default_factory=list)  # pages of each sampled PDF
    pdf_scanned: int = 0  # sampled PDFs that need OCR
    native_page_chars: list[int] = field(default_factory=list)
    language_counts: Counter = field(default_factory=Counter)

    @property
    def pdf_files(self) -> int:
        return self.by_category["pdf"]

    @property
    def whole_document_files(self) -> int:
        return sum(n for c, n in self.by_category.items() if c not in _MULTI_PAGE_CATEGORIES)

    def estimated_pdf_pages(self) -> int:
        if not self.pdf_files:
            return 0
        average = statistics.mean(self.pdf_pages) if self.pdf_pages else 1
        return round(average * self.pdf_files)

    def estimated_pages(self) -> int:
        return self.estimated_pdf_pages() + self.by_category["imagens"] + self.whole_document_files

    def multi_page_share(self) -> float:
        total = self.estimated_pages()
        if not total:
            return 0.0
        return (self.estimated_pdf_pages() + self.by_category["imagens"]) / total


# --- survey -----------------------------------------------------------------


def _sample(paths: list[Path], size: int) -> list[Path]:
    if len(paths) <= size:
        return paths
    return random.Random(len(paths)).sample(paths, size)


def _survey_pdfs(paths: list[Path], survey: FolderSurvey) -> list[str]:
    import fitz

    texts: list[str] = []
    for path in _sample(paths, _PDF_SAMPLE):
        try:
            document = fitz.open(path)
        except Exception:
            continue
        try:
            count = document.page_count
            if not count:
                continue
            step = max(1, count // _PDF_PAGES_SAMPLED)
            lengths = []
            for number in range(0, count, step)[:_PDF_PAGES_SAMPLED]:
                text = document[number].get_text()
                lengths.append(len(text.strip()))
                texts.append(text)
            survey.pdf_pages.append(count)
            if statistics.mean(lengths) < MIN_AVG_CHARS_PER_PAGE:
                survey.pdf_scanned += 1
            else:
                survey.native_page_chars.extend(n for n in lengths if n >= MIN_AVG_CHARS_PER_PAGE)
        except Exception:
            continue
        finally:
            document.close()
    return texts


def _survey_text_files(found: dict[str, list[Path]]) -> list[str]:
    from .html_text import html_to_text, looks_like_html
    from .text_decoding import decode_markup

    candidates = found.get("web_dados", []) + found.get("text", [])
    texts = []
    for path in _sample(candidates, _TEXT_SAMPLE):
        try:
            with open(path, "rb") as file:
                data = file.read(_TEXT_BYTES)
        except OSError:
            continue
        text, _ = decode_markup(data)
        if path.suffix.lower() in (".htm", ".html", ".xhtml", ".xht", ".shtml") or looks_like_html(text):
            text = html_to_text(text)
        texts.append(text)
    return texts


def _count_languages(texts: list[str], survey: FolderSurvey) -> None:
    """Conta o idioma de cada texto amostrado, já no código do Tesseract
    ("por", "deu", "chi_sim"…). 2.0.0: pelo detector de qualquer idioma
    (`language_detect`), não mais por palavras frequentes de três idiomas."""
    from .language_detect import detect_languages, tesseract_languages

    for text in texts:
        found = detect_languages(text, max_languages=1)
        if not found:
            continue
        models = tesseract_languages(found, text, limit=1)
        if models:
            survey.language_counts[models[0]] += 1


# --- OCR languages installed --------------------------------------------------


@lru_cache(maxsize=1)
def installed_ocr_languages() -> frozenset[str] | None:
    """Languages Tesseract has data for on this machine, or `None` when it
    cannot be asked (not installed, or it failed) — then nothing is
    filtered out."""
    from . import tools
    from .subprocess_utils import run_hidden

    executable = tools.find("tesseract")
    if not executable:
        return None
    try:
        result = run_hidden([executable, "--list-langs"], timeout=15)
    except Exception:
        return None
    lines = (result.stdout or "").splitlines()
    languages = {line.strip() for line in lines[1:] if line.strip()}
    return frozenset(languages) or None


# --- decisions ---------------------------------------------------------------


def _round_up(value: float, step: int) -> int:
    return int(-(-value // step) * step)

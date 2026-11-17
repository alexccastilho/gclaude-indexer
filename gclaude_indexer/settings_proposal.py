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

`survey_folder` (a bounded walk of a folder, stopping after `_WALK_SECONDS` or
`_WALK_MAX_FILES`) is kept for sampling a folder that is not in the database
yet; the scan's own listing is what the automatic settings read.
"""

from __future__ import annotations

import os
import random
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .file_types import ALWAYS_BLOCKED_EXTENSIONS, CATEGORY_ALL, category_of_extension
from .paths import holds_generated_output

_WALK_SECONDS = 6.0
_WALK_MAX_FILES = 60_000
_PDF_SAMPLE = 12
_PDF_PAGES_SAMPLED = 6
_TEXT_SAMPLE = 16
_TEXT_BYTES = 64 * 1024

# The rule `conversion.py` uses to decide a PDF needs OCR.
_MIN_AVG_CHARS_PER_PAGE = 100

_MULTI_PAGE_CATEGORIES = {"pdf", "imagens", "paginados", "legados"}

# A few hundred of the most frequent function words is enough to tell
# Portuguese, Spanish and English apart on a page of text.
_STOPWORDS = {
    "por": {"de", "da", "do", "das", "dos", "que", "não", "para", "com", "uma", "os", "no", "na",
            "ao", "à", "pelo", "pela", "são", "também", "será", "nos", "às", "seu", "sua", "ou", "em"},
    "spa": {"de", "la", "el", "los", "las", "que", "no", "para", "con", "una", "del", "al", "por",
            "es", "se", "su", "lo", "como", "más", "pero", "sus", "le", "ya", "este", "esta", "y"},
    "eng": {"the", "of", "and", "to", "in", "is", "that", "for", "it", "with", "as", "was", "on",
            "be", "by", "this", "are", "or", "from", "at", "which", "an", "have", "not", "shall"},
}
_WORD = re.compile(r"[a-zà-ÿ]+")


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

    def scanned_share(self) -> float:
        return self.pdf_scanned / len(self.pdf_pages) if self.pdf_pages else 0.0


# --- survey -----------------------------------------------------------------


def _accepted(extension: str, categories: list[str]) -> str | None:
    """The file's category if the project would scan it, else `None`."""
    category = category_of_extension(extension)
    if not categories or CATEGORY_ALL in categories:
        if extension in ALWAYS_BLOCKED_EXTENSIONS:
            return None
        if category == "midia" and "midia" not in categories:
            return None  # "all" nunca cobre áudio e vídeo
        return category or ("text" if CATEGORY_ALL in categories else None)
    return category if category in categories else None


def _walk(folder: Path, categories: list[str], survey: FolderSurvey) -> dict[str, list[Path]]:
    started = time.monotonic()
    found: dict[str, list[Path]] = {}
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        # Mesma regra da varredura: saída gerada (outro projeto, Conjunto)
        # não entra na amostra. A pasta escolhida em si não conta.
        if current != folder and holds_generated_output(entry.name for entry in entries):
            continue
        for entry in entries:
            if time.monotonic() - started > _WALK_SECONDS or survey.files >= _WALK_MAX_FILES:
                survey.partial = True
                survey.seconds = time.monotonic() - started
                return found
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
            except OSError:
                continue
            category = _accepted(os.path.splitext(entry.name)[1].lower(), categories)
            if category is None:
                continue
            survey.files += 1
            survey.by_category[category] += 1
            found.setdefault(category, []).append(Path(entry.path))
    survey.seconds = time.monotonic() - started
    return found


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
            if statistics.mean(lengths) < _MIN_AVG_CHARS_PER_PAGE:
                survey.pdf_scanned += 1
            else:
                survey.native_page_chars.extend(n for n in lengths if n >= _MIN_AVG_CHARS_PER_PAGE)
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
    for text in texts:
        words = _WORD.findall(text.lower())
        if len(words) < 20:
            continue
        scores = {code: sum(w in stop for w in words) for code, stop in _STOPWORDS.items()}
        best = max(scores, key=scores.get)
        if scores[best]:
            survey.language_counts[best] += 1


def survey_folder(folder: Path, categories: list[str]) -> FolderSurvey:
    survey = FolderSurvey()
    found = _walk(folder, categories, survey)
    texts = _survey_pdfs(found.get("pdf", []), survey) + _survey_text_files(found)
    _count_languages(texts, survey)
    return survey


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

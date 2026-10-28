# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Proposing slicing, window and OCR settings from what a folder holds.

The five fields of the "Slicing, windows and OCR" section have no value
that suits every collection. A case file of scanned PDFs, a library of long
native-text compilations and a folder of 100,000 laws saved as HTML pull
them in opposite directions — and real collections mix all of these. This
module looks at the folder the way the pipeline will read it and proposes
values, each with the reason, for the user to apply or not.

It is a quick look, never a full read: the walk stops after
`_WALK_SECONDS` or `_WALK_MAX_FILES`, a handful of PDFs are opened (a few
pages each), and a handful of text files are read for the language. A
folder on Google Drive with 108,000 files is answered in seconds; the
proposal then says it was based on a sample.
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

_WALK_SECONDS = 6.0
_WALK_MAX_FILES = 60_000
_PDF_SAMPLE = 12
_PDF_PAGES_SAMPLED = 6
_TEXT_SAMPLE = 16
_TEXT_BYTES = 64 * 1024

# The rule `conversion.py` uses to decide a PDF needs OCR.
_MIN_AVG_CHARS_PER_PAGE = 100
# Rough ceiling for a window's text, in characters: ~11k tokens, which
# leaves room for the prompt and the answer inside the local engine's
# largest context (16,384) and is subdivided, not lost, on smaller cards.
_WINDOW_CHAR_BUDGET = 40_000
_MIN_WINDOW = 4

_MULTI_PAGE_CATEGORIES = {"pdf", "imagens"}

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
class Reason:
    key: str
    params: dict = field(default_factory=dict)


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


@dataclass
class SettingsProposal:
    pages_per_block: int
    pages_per_window: int
    overlap: int
    chars_per_page: int
    ocr_language: str
    reasons: dict[str, list[Reason]]
    survey: FolderSurvey


# --- survey -----------------------------------------------------------------


def _accepted(extension: str, categories: list[str]) -> str | None:
    """The file's category if the project would scan it, else `None`."""
    category = category_of_extension(extension)
    if not categories or CATEGORY_ALL in categories:
        if extension in ALWAYS_BLOCKED_EXTENSIONS:
            return None
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


def propose(survey: FolderSurvey, installed: frozenset[str] | None = None) -> SettingsProposal:
    reasons: dict[str, list[Reason]] = {}
    multi_share = survey.multi_page_share()
    scanned_share = survey.scanned_share()
    has_pdf = survey.pdf_files > 0
    has_images = survey.by_category["imagens"] > 0
    whole_docs_dominate = multi_share < 0.5

    # pages per block — only PDFs are cut
    if not has_pdf:
        block = 80
        reasons["pages_per_block"] = [Reason("proposal.reason.block_no_pdf")]
    elif scanned_share >= 0.3:
        block = 40
        reasons["pages_per_block"] = [Reason("proposal.reason.block_scanned", {"share": round(scanned_share * 100)})]
    else:
        block = 80
        reasons["pages_per_block"] = [Reason("proposal.reason.block_default", {"value": block})]

    # characters per page
    if whole_docs_dominate:
        chars = 2000
        reasons["chars_per_page"] = [Reason("proposal.reason.chars_whole_docs", {"value": chars})]
    elif not survey.native_page_chars:
        chars = 2000
        reasons["chars_per_page"] = [Reason("proposal.reason.chars_scanned", {"value": chars})]
    else:
        lengths = sorted(survey.native_page_chars)
        p75 = lengths[int(0.75 * (len(lengths) - 1))]
        chars = max(1500, min(4000, _round_up(p75, 500)))
        reasons["chars_per_page"] = [Reason("proposal.reason.chars_pdf", {"value": chars, "max": lengths[-1]})]

    # pages per window
    median_pages = round(statistics.median(survey.pdf_pages)) if survey.pdf_pages else 0
    if whole_docs_dominate:
        window = 16
        reasons["pages_per_window"] = [Reason(
            "proposal.reason.window_whole_docs", {"share": round((1 - multi_share) * 100)},
        )]
    elif median_pages and median_pages <= 4:
        window = 16
        reasons["pages_per_window"] = [Reason("proposal.reason.window_short_pdfs", {"median": median_pages})]
    else:
        window = 12
        reasons["pages_per_window"] = [Reason("proposal.reason.window_long_pdfs", {"median": median_pages})]
    capped = max(_MIN_WINDOW, _WINDOW_CHAR_BUDGET // chars)
    if window > capped:
        window = capped
        reasons["pages_per_window"].append(Reason("proposal.reason.window_capped", {"value": window, "chars": chars}))

    # overlap
    if multi_share < 0.05:
        overlap = 0
        reasons["overlap"] = [Reason("proposal.reason.overlap_zero")]
    else:
        overlap = 2 if window > 6 else 1
        reasons["overlap"] = [Reason("proposal.reason.overlap_multi_page", {"value": overlap})]

    # OCR language
    ranked = [code for code, _ in survey.language_counts.most_common()]
    total = sum(survey.language_counts.values())
    chosen = [code for code in ranked if survey.language_counts[code] / total >= 0.25][:2] if total else []
    missing = [code for code in chosen if installed is not None and code not in installed]
    chosen = [code for code in chosen if code not in missing] or ["por"]
    ocr_language = "+".join(chosen)
    reasons["ocr_language"] = []
    if total:
        reasons["ocr_language"].append(Reason("proposal.reason.ocr_detected", {"languages": chosen}))
    if missing:
        reasons["ocr_language"].append(Reason("proposal.reason.ocr_missing", {"languages": missing}))
    if not (has_images or survey.pdf_scanned):
        reasons["ocr_language"].append(Reason("proposal.reason.ocr_unused"))

    return SettingsProposal(
        pages_per_block=block,
        pages_per_window=window,
        overlap=overlap,
        chars_per_page=chars,
        ocr_language=ocr_language,
        reasons=reasons,
        survey=survey,
    )


def propose_for_folder(folder: Path, categories: list[str]) -> SettingsProposal:
    return propose(survey_folder(folder, categories), installed_ocr_languages())


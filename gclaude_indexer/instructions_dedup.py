# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The user's part of `project_instructions.md` repeating the managed block
.

People who had instructions before the block existed often copied the
collection sections into their own part by hand: the non-negotiable rule,
how to locate an item, the file columns, and counts that froze on the day
they copied them ("12345 pages") while the block kept updating. The block
was then appended below and everything appeared twice.

How a copy is recognized, without any text of a particular project:

1. The reference is what the block can say, taken from the translation
   templates in the three languages (a copy may be in another language
   than the screen), filled with the default file names, plus the project's
   own subject line. Nothing is read from the database.
2. Both sides are normalized: accents and case dropped, every dash, colon,
   bracket and Markdown mark turned into a space, every number into `#`,
   spaces collapsed. "Regra inegociável — nunca" and "regra inegociavel:
   nunca" become the same words, and so do two different counts.
3. The user's part is cut into sections at its Markdown headings. For each
   section, the share of its word trigrams that also occur in the
   reference says how much of it is the block's text. A section is a copy
   when that share is high (80 %), or when its heading is one of the
   block's headings (with or without a number, "## 5. Regra inegociável")
   and at least half of its text is the block's.
4. Lines that carry a number the block recalculates on every run (items,
   files, Planalto pages) are reported wherever they are.
5. "Section 4" style references in the rest of the text that point at a
   section found to be a copy are listed, with what they become if the
   copies are removed: a pointer to the block.
6. Lines of the user's own sections that talk about the generated files
   (`index.md`, `timeline.md`, `review.md`, `normas-citadas.md`), the
   original files or the collection are offered as candidates for the
   project's extra rules, so they show up inside the block. Nothing is
   moved without the person choosing it.

Everything here is pure text in, text out.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from .i18n import AVAILABLE_LANGUAGES, translate

_HEADING_KEYS = (
    "artifact.project_instructions.title",
    "artifact.project_instructions.collection_title",
    "artifact.project_instructions.role_section",
    "artifact.project_instructions.about_section",
    "artifact.project_instructions.rule_section",
    "artifact.project_instructions.locate_section",
    "artifact.project_instructions.columns_section",
    "artifact.project_instructions.extra_rules_section",
)
_BODY_KEYS = (
    "artifact.project_instructions.collection_intro",
    "artifact.project_instructions.access_line",
    "artifact.project_instructions.locate_step1",
    "artifact.project_instructions.locate_step2",
    "artifact.project_instructions.locate_step3",
    "artifact.project_instructions.locate_step4",
    "artifact.project_instructions.columns_index",
    "artifact.project_instructions.columns_index_confidence",
    "artifact.project_instructions.columns_timeline",
    "artifact.project_instructions.struck_text_rule",
    "artifact.project_instructions.legislation_rule",
    "artifact.project_instructions.extra_rules_missing",
)
# Templates with a number recalculated on every run.
_VOLATILE_KEYS = (
    "artifact.project_instructions.access_line",
    "artifact.project_instructions.legislation_rule",
)
_DEFAULTS = {
    "index_file": "index.md", "timeline_file": "timeline.md", "review_file": "review.md",
    "norms": "normas-citadas.md", "prefix": "", "total_items": 1, "total_files": 1, "count": 1,
}

COPY_SHARE = 0.8
HEADING_COPY_SHARE = 0.5

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_NUMBERED_TITLE = re.compile(r"^\s*(\d+)\s*[.)\-:]?\s+(.*)$")
_SECTION_REF = re.compile(r"\b(se[cç][aã]o|section|secci[oó]n)\s+(\d+)\b", re.IGNORECASE)
_ARTIFACT_WORDS = re.compile(
    r"index[-\w<>*]*\.md|timeline[-\w<>*]*\.md|review\.md|normas-citadas\.md", re.IGNORECASE,
)
_ORIGINAL_WORDS = re.compile(
    r"arquivos? origina(l|is)|original files?|archivos? original(es)?|"
    r"no original|in the original|en el original",
    re.IGNORECASE,
)
_COLLECTION_WORDS = re.compile(r"\bacervos?\b|\bcollections?\b|\bcolecci[oó]n(es)?\b", re.IGNORECASE)
_ORDERED_ITEM = re.compile(r"^(\s*)(\d+)([.)])(\s+)")


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()
    plain = re.sub(r"\d[\d.,]*\d|\d", "#", plain)
    plain = re.sub(r"[^\w#]+", " ", plain)
    return " ".join(plain.split())


def _trigrams(text: str) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    if len(words) < 3:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def _title_key(title: str) -> str:
    match = _NUMBERED_TITLE.match(title)
    return normalize(match.group(2) if match else title)


@dataclass
class Reference:
    trigrams: set
    headings: set
    title_prefixes: tuple
    volatile: list            # normalized templates with "#" for the numbers
    block_title: dict         # language -> collection title


def reference(subject: str = "") -> Reference:
    """What the block can say, in the three languages."""
    from .artifacts import DEFAULT_ROLE, SOURCE_OF_TRUTH_RULE

    trigrams: set = set()
    headings: set = set()
    prefixes = []
    volatile = []
    titles = {}
    for language in AVAILABLE_LANGUAGES:
        for key in _HEADING_KEYS:
            heading = translate(language, key)
            headings.add(normalize(heading))
            trigrams |= _trigrams(heading)
        for key in ("artifact.project_instructions.title", "artifact.project_instructions.collection_title"):
            prefixes.append(normalize(translate(language, key)))
        titles[language] = translate(language, "artifact.project_instructions.collection_title")
        for key in _BODY_KEYS:
            trigrams |= _trigrams(translate(language, key, **_DEFAULTS))
        for key in _VOLATILE_KEYS:
            volatile.append(normalize(translate(language, key, **_DEFAULTS)))
    for text in (DEFAULT_ROLE, SOURCE_OF_TRUTH_RULE, subject):
        if text and text.strip():
            trigrams |= _trigrams(text)
    return Reference(trigrams, headings, tuple(prefixes), volatile, titles)


@dataclass
class Section:
    start: int                # first line (the heading; 0 for the preamble)
    end: int                  # one past the last line, subsections included
    level: int                # 0 for the preamble
    title: str
    number: int | None
    share: float = 0.0
    heading_match: bool = False
    copy: bool = False


@dataclass
class Candidate:
    id: int
    line: int
    text: str                 # what moves into the extra rules
    original: str             # the text as it is in the file
    sentence: bool            # only a sentence of the line
    suggested: bool           # checked by default


@dataclass
class DedupReport:
    lines: list[str]
    sections: list[Section] = field(default_factory=list)
    volatile_lines: list[tuple[int, str]] = field(default_factory=list)
    references: list[tuple[int, str]] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def copies(self) -> list[Section]:
        return [section for section in self.sections if section.copy]

    @property
    def has_findings(self) -> bool:
        return bool(self.copies or self.volatile_lines)

    def copy_titles(self) -> list[str]:
        return [
            (f"{section.number}. " if section.number is not None else "") + _plain_title(section.title)
            for section in self.copies
        ]


def _plain_title(title: str) -> str:
    match = _NUMBERED_TITLE.match(title)
    return (match.group(2) if match else title).strip()


def _sections(lines: list[str]) -> list[Section]:
    heads = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match:
            heads.append((index, len(match.group(1)), match.group(2)))
    sections = []
    first = heads[0][0] if heads else len(lines)
    if first > 0:
        sections.append(Section(0, first, 0, "", None))
    for position, (index, level, title) in enumerate(heads):
        end = len(lines)
        for later_index, later_level, _ in heads[position + 1:]:
            if later_level <= level:
                end = later_index
                break
        number_match = _NUMBERED_TITLE.match(title)
        number = int(number_match.group(1)) if number_match else None
        sections.append(Section(index, end, level, title, number))
    return sections


def _own_lines(section: Section, sections: list[Section]) -> range:
    """The section's lines up to its first subsection."""
    stop = section.end
    for other in sections:
        if other.start > section.start and other.start < stop and other.level > section.level:
            stop = other.start
    return range(section.start + (1 if section.level else 0), stop)


def detect(user_text: str, subject: str = "", ref: Reference | None = None) -> DedupReport:
    ref = ref or reference(subject)
    text = user_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    report = DedupReport(lines=lines, fingerprint=hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16])
    report.sections = _sections(lines)

    for section in report.sections:
        own = [lines[i] for i in _own_lines(section, report.sections)]
        body = "\n".join(own)
        grams = _trigrams(body)
        section.share = (len(grams & ref.trigrams) / len(grams)) if grams else 0.0
        key = _title_key(section.title) if section.level else ""
        section.heading_match = bool(key) and (
            key in ref.headings or any(key.startswith(prefix) for prefix in ref.title_prefixes if prefix)
        )
        if section.level == 0:
            continue
        if section.heading_match and (not grams or section.share >= HEADING_COPY_SHARE):
            section.copy = True
        elif grams and len(grams) >= 4 and section.share >= COPY_SHARE:
            section.copy = True

    # A copied heading takes its subsections with it only when they are
    # copies too; a subsection of the user's own stays and keeps its parent.
    for section in report.copies:
        for other in report.sections:
            if section.start < other.start < section.end and not other.copy:
                section.copy = False
                break

    copied = _copied_lines(report)
    for index, line in enumerate(lines):
        if not re.search(r"\d", line):
            continue
        masked = normalize(line)
        if any(_contains_volatile(masked, template) for template in ref.volatile):
            report.volatile_lines.append((index, line))

    removed_numbers = {section.number for section in report.copies if section.number is not None}
    for index, line in enumerate(lines):
        if index in copied:
            continue
        for match in _SECTION_REF.finditer(line):
            if int(match.group(2)) in removed_numbers:
                report.references.append((index, match.group(0)))

    report.candidates = _candidates(lines, report, copied)
    return report


def _contains_volatile(masked_line: str, template: str) -> bool:
    words = template.split()
    for position, word in enumerate(words):
        if word != "#":
            continue
        window = " ".join(words[max(0, position - 4):position + 4])
        if window and window in masked_line:
            return True
    return False


def _copied_lines(report: DedupReport) -> set[int]:
    lines: set[int] = set()
    for section in report.copies:
        lines.update(range(section.start, section.end))
    return lines


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý¿¡])")


def _candidates(lines: list[str], report: DedupReport, copied: set[int]) -> list[Candidate]:
    found: list[Candidate] = []
    table_header: list[str] | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if index in copied or not stripped or _HEADING.match(line):
            table_header = None if not stripped.startswith("|") else table_header
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if table_header is None:
                table_header = cells
                continue
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            row = " ".join(cells)
            if _ARTIFACT_WORDS.search(row) or _ORIGINAL_WORDS.search(row):
                found.append(Candidate(
                    len(found), index, _row_as_rule(cells, table_header), line, False, True,
                ))
            continue
        table_header = None
        list_item = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)
        if list_item:
            content = line[list_item.end():].strip()
            if _mentions(content):
                found.append(Candidate(len(found), index, content, line, False, _strong(content)))
            continue
        for sentence in _SENTENCE.split(stripped):
            if _mentions(sentence):
                whole = sentence.strip() == stripped
                found.append(Candidate(len(found), index, sentence.strip(), sentence.strip(), not whole, _strong(sentence)))
    return found


def _mentions(text: str) -> bool:
    return bool(_ARTIFACT_WORDS.search(text) or _ORIGINAL_WORDS.search(text) or _COLLECTION_WORDS.search(text))


def _strong(text: str) -> bool:
    return bool(_ARTIFACT_WORDS.search(text) or _ORIGINAL_WORDS.search(text))


def _row_as_rule(cells: list[str], header: list[str]) -> str:
    if not cells:
        return ""
    parts = [f"**{cells[0]}**"]
    rest = []
    for position, cell in enumerate(cells[1:], start=1):
        if not cell:
            continue
        label = header[position] if position < len(header) else ""
        rest.append(f"{label}: {cell}" if label else cell)
    return parts[0] + (": " + "; ".join(rest) if rest else "")


def block_pointer(language: str) -> str:
    return translate(
        language, "instructions.dedup.block_pointer",
        title=translate(language, "artifact.project_instructions.collection_title"),
    )


def apply(report: DedupReport, language: str, *, remove_copies: bool, move: set[int]) -> tuple[str, list[str]]:
    """The user's part with the copies removed (and the references to them
    pointed at the block) and the chosen candidates taken out. Returns the
    new text and the rules to add to the project's extra rules."""
    lines = list(report.lines)
    drop: set[int] = _copied_lines(report) if remove_copies else set()

    rules: list[str] = []
    touched_lists: set[int] = set()
    for candidate in report.candidates:
        if candidate.id not in move or candidate.line in drop:
            continue
        rules.append(candidate.text)
        if candidate.sentence:
            lines[candidate.line] = " ".join(lines[candidate.line].replace(candidate.original, "").split())
            if not lines[candidate.line].strip():
                drop.add(candidate.line)
        else:
            drop.add(candidate.line)
            touched_lists.add(candidate.line)

    if remove_copies:
        pointer = block_pointer(language)
        numbers = {section.number for section in report.copies if section.number is not None}

        def point(match: re.Match) -> str:
            return pointer if int(match.group(2)) in numbers else match.group(0)

        for index in range(len(lines)):
            if index not in drop:
                lines[index] = _SECTION_REF.sub(point, lines[index])
        rules = [_SECTION_REF.sub(point, rule) for rule in rules]

    kept: list[str] = []
    renumber_from: set[int] = set()
    for index, line in enumerate(lines):
        if index in drop:
            if index in touched_lists and kept:
                renumber_from.add(len(kept))
            continue
        kept.append(line)
    for position in sorted(renumber_from):
        _renumber_around(kept, position)

    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, rules


def _renumber_around(lines: list[str], position: int) -> None:
    start = min(position, len(lines) - 1)
    while start > 0 and _ORDERED_ITEM.match(lines[start - 1]):
        start -= 1
    if start < len(lines) and not _ORDERED_ITEM.match(lines[start]):
        start += 1
    if start >= len(lines):
        return
    first = _ORDERED_ITEM.match(lines[start])
    if not first:
        return
    number = int(first.group(2))
    index = start
    while index < len(lines):
        match = _ORDERED_ITEM.match(lines[index])
        if not match:
            break
        lines[index] = f"{match.group(1)}{number}{match.group(3)}{match.group(4)}" + lines[index][match.end():]
        number += 1
        index += 1


def is_only_generated(text: str) -> bool:
    """A file with no marks that holds nothing but the block's sections: the
    whole file of a version from before the marks. One section of the
    user's own makes it theirs."""
    report = detect(text)
    real = [section for section in report.sections if section.level]
    if not real:
        return False
    preamble = [section for section in report.sections if not section.level]
    if preamble and "\n".join(report.lines[preamble[0].start:preamble[0].end]).strip():
        return False
    return all(section.copy or section.heading_match for section in real)

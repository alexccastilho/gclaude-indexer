# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""HTML to text that keeps what the formatting means.

HTML used to go into the index as raw markup: `<head>`, CSS and JavaScript
filled the characters allowed per page before the first article, and the
formatting that carries meaning was lost. In legislation the most important
one is strikethrough — on the Planalto site a struck article, paragraph or
item is one that was revoked, suppressed or rewritten, and it stays on the
page next to the text in force. Read as plain text, the two are
indistinguishable.

The output is plain text with a few Markdown conventions, which both the
local model and Claude read without being taught:

- struck text becomes `~~text~~`, one pair per line (Markdown does not
  carry strikethrough across a line break);
- headings become `# `, list items `- `, table cells are joined by ` | `;
- `<sup>o</sup>` / `<sup>a</sup>` become `º` / `ª` ("LEI N<sup>o</sup>").

Strikethrough is recognised in the three forms the Planalto collection
uses — `<strike>`, `<s>` and `style="text-decoration: line-through"` — plus
`<del>` and CSS classes declared in a `<style>` block.

Markup from the 1990s is rarely well formed (FrontPage, unclosed `<p>`,
`</strike>` before `</font>`). The parser is the standard library's
tolerant one, an end tag closes everything opened after its start tag, and
if anything still goes wrong the text is recovered by stripping tags —
never by failing the file.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

STRUCK_MARK = "~~"

_SKIPPED = {"head", "script", "style", "noscript", "template", "title", "object", "iframe", "svg", "math"}
_STRUCK_TAGS = {"s", "strike", "del"}
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr", "basefont", "frame", "isindex", "keygen",
}
_BLOCK = {
    "address", "article", "aside", "blockquote", "body", "caption", "center", "dd",
    "details", "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure",
    "footer", "form", "frameset", "header", "hgroup", "html", "legend", "li", "main",
    "menu", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "tfoot",
    "thead", "tr", "ul",
}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_CELLS = {"td", "th"}
_ORDINALS = {"o": "º", "a": "ª"}

_LINE_THROUGH = re.compile(r"line-through", re.IGNORECASE)
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_CLASS = re.compile(r"\.(-?[_a-zA-Z][\w-]*)\s*$")
_WHITESPACE = re.compile(r"[ \t\r\n\f\v   ]+")
_STRUCK_SPAN = re.compile(r"~~.*?~~")
_TAG = re.compile(r"<[^>]*>")


def struck_css_classes(markup: str) -> set[str]:
    """Class names whose rule in a `<style>` block sets `line-through`."""
    classes: set[str] = set()
    for block in re.findall(r"<style[^>]*>(.*?)</style>", markup, re.IGNORECASE | re.DOTALL):
        for selectors, declarations in _CSS_RULE.findall(block):
            if not _LINE_THROUGH.search(declarations):
                continue
            for selector in selectors.split(","):
                match = _CSS_CLASS.search(selector.strip())
                if match:
                    classes.add(match.group(1).lower())
    return classes


class _TextBuilder(HTMLParser):
    def __init__(self, struck_classes: set[str]):
        super().__init__(convert_charrefs=True)
        self._struck_classes = struck_classes
        # (tag, starts strikethrough, starts a skipped region)
        self._open: list[tuple[str, bool, bool]] = []
        self._struck_depth = 0
        self._skipped_depth = 0
        self._pre_depth = 0
        self._sup_buffer: list[str] | None = None
        self._segments: list[tuple[str, bool]] = []
        self._prefix = ""
        self.lines: list[str] = []

    # -- structure ---------------------------------------------------------

    def _flush(self) -> None:
        line = _render_line(self._segments, preformatted=self._pre_depth > 0)
        self._segments = []
        if line:
            self.lines.append(self._prefix + line)
            self._prefix = ""

    def _starts_strike(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in _STRUCK_TAGS:
            return True
        for name, value in attrs:
            if not value:
                continue
            if name == "style" and _LINE_THROUGH.search(value):
                return True
            if name == "class" and self._struck_classes:
                if any(c.lower() in self._struck_classes for c in value.split()):
                    return True
        return False

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK or tag in _HEADINGS:
            self._flush()
            if tag in _HEADINGS:
                self._prefix = "#" * _HEADINGS[tag] + " "
            elif tag == "li":
                self._prefix = "- "
            elif tag in ("ul", "ol", "table", "tr"):
                self._prefix = ""
        elif tag == "br":
            self._flush()
        elif tag == "hr":
            self._flush()
            self.lines.append("---")
        elif tag in _CELLS:
            if any(text.strip() for text, _ in self._segments):
                self._segments.append((" | ", False))
        elif tag == "sup" and self._sup_buffer is None:
            self._sup_buffer = []

        if tag in _VOID:
            return

        struck = self._starts_strike(tag, attrs)
        skipped = tag in _SKIPPED
        self._open.append((tag, struck, skipped))
        self._struck_depth += struck
        self._skipped_depth += skipped
        if tag == "pre":
            self._pre_depth += 1

    def handle_startendtag(self, tag, attrs):
        # `<br/>`, `<p/>`: never opens anything.
        if tag in _BLOCK or tag in _HEADINGS or tag in ("br", "hr"):
            self.handle_starttag(tag, attrs)
            if tag not in _VOID:
                self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "sup" and self._sup_buffer is not None:
            text = "".join(self._sup_buffer)
            self._sup_buffer = None
            self._emit(_ORDINALS.get(text.strip().lower(), text) if text.strip() else text)

        positions = [i for i, (name, _, _) in enumerate(self._open) if name == tag]
        if not positions:
            return  # stray end tag: browsers ignore it, so do we
        # Flushed before popping, so that the last line of a `<pre>` is
        # still rendered as preformatted.
        if tag in _BLOCK or tag in _HEADINGS:
            self._flush()
        while len(self._open) > positions[-1]:
            name, struck, skipped = self._open.pop()
            self._struck_depth -= struck
            self._skipped_depth -= skipped
            if name == "pre":
                self._pre_depth -= 1

    # -- text ----------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if not text or self._skipped_depth:
            return
        struck = self._struck_depth > 0
        if self._pre_depth:
            first, *rest = text.split("\n")
            self._segments.append((first, struck))
            for piece in rest:
                self._flush()
                self._segments.append((piece, struck))
        else:
            self._segments.append((text, struck))

    def handle_data(self, data):
        if self._skipped_depth:
            return
        if self._sup_buffer is not None:
            self._sup_buffer.append(data)
            return
        self._emit(data)

    def close(self):
        super().close()
        self._flush()


def mark_struck(segments: list[tuple[str, bool]]) -> str:
    """Joins `(text, struck)` runs, wrapping each struck stretch in `~~`.

    Adjacent runs with the same flag are merged first, and the marks hug
    the words — `~~text~~ `, never `~~text ~~`, which Markdown does not
    read as strikethrough. Shared with the DOCX/PPTX/XLSX extractors.
    """
    merged: list[list] = []
    for text, struck in segments:
        if merged and merged[-1][1] == struck:
            merged[-1][0] += text
        else:
            merged.append([text, struck])

    parts: list[str] = []
    for text, struck in merged:
        core = text.strip()
        if struck and core:
            leading = text[: len(text) - len(text.lstrip())]
            trailing = text[len(text.rstrip()):]
            parts.append(f"{leading}{STRUCK_MARK}{core}{STRUCK_MARK}{trailing}")
        else:
            parts.append(text)
    return "".join(parts)


def _render_line(segments: list[tuple[str, bool]], preformatted: bool) -> str:
    if preformatted:
        return mark_struck(segments).replace("\u00a0", " ").rstrip()
    collapsed = [(_WHITESPACE.sub(" ", text), struck) for text, struck in segments]
    return re.sub(r" {2,}", " ", mark_struck(collapsed)).strip()


def _strip_tags(markup: str) -> str:
    """Last resort when the parser itself fails: drop the tags, keep text."""
    markup = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", " ", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<(br|/p|/div|/tr|/li|/h\d)[^>]*>", "\n", markup, flags=re.IGNORECASE)
    text = html.unescape(_TAG.sub(" ", markup))
    lines = (_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def html_to_text(markup: str) -> str:
    """Readable text of an HTML document, with strikethrough kept as `~~`."""
    try:
        builder = _TextBuilder(struck_css_classes(markup))
        builder.feed(markup)
        builder.close()
        return "\n".join(builder.lines)
    except Exception:
        return _strip_tags(markup)


def looks_like_html(text: str) -> bool:
    """Whether an `.xml` file is really XHTML — root element `<html>`."""
    head = re.sub(r"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", "", text[:4096], flags=re.DOTALL | re.IGNORECASE)
    return re.match(r"\s*<html[\s>]", head, re.IGNORECASE) is not None


def without_struck_text(text: str) -> str:
    """`text` with every `~~struck~~` span removed — what is in force."""
    return _STRUCK_SPAN.sub("", text)

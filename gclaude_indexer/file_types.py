# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Supported file categories and their mapping to extensions.

Used by the configuration ("Included extensions" field, section 6) and by
the scan (section 5, step 1) to decide what enters the inventory.
"""

from __future__ import annotations

EXTENSION_CATEGORIES: dict[str, set[str]] = {
    "pdf": {".pdf"},
    "docx": {".docx"},
    "xlsx": {".xlsx"},
    "pptx": {".pptx"},
    "imagens": {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"},
    # "imagens" and "web_dados" are read as plain text (no dedicated extractor) —
    # that's why they only group formats that are already text by nature;
    # markup (html/xml/json) goes into the index literally, with no parsing.
    "text": {".txt", ".md", ".log", ".csv"},
    "web_dados": {".html", ".htm", ".xml", ".json"},
    "email": {".eml", ".msg"},
}

# Note: category keys above ("imagens", "web_dados") are data values shared
# with the i18n keys ("new_project.category.*") and with form/template
# markup outside this module's scope — they are intentionally left
# untranslated here so the UI keeps resolving them. ("text" and CATEGORY_ALL
# below were translated in Task 9d, Phase 14 — narrower exceptions the
# coordinator asked for explicitly, not a reversal of this module's general
# policy toward the rest of the set.)

# Special category (explicit user request): "all" scans any extension that
# is NOT in the blocklist below — i.e. it is not restricted to
# `EXTENSION_CATEGORIES`. It never appears among `EXTENSION_CATEGORIES`
# values because it isn't a fixed set of extensions: it's a rule ("everything
# except binaries/executables"), applied in `scanning.py`.
CATEGORY_ALL = "all"

# Always excluded, even with "all" selected — executable or binary formats
# that never make sense to index as a document (never text/image in a
# collection).
ALWAYS_BLOCKED_EXTENSIONS: set[str] = {
    ".exe", ".dll", ".msi", ".bat", ".cmd", ".com", ".scr", ".sys", ".bin",
    ".so", ".dylib", ".iso", ".vhd", ".vhdx", ".drv", ".ocx", ".cpl", ".vbs",
    ".js", ".jar", ".apk", ".deb", ".rpm", ".ps1", ".sh", ".app", ".lnk",
}


def valid_categories() -> set[str]:
    return set(EXTENSION_CATEGORIES) | {CATEGORY_ALL}


def extensions_for_categories(categories: list[str]) -> set[str]:
    """Converts a list of configured categories (e.g. `["pdf", "imagens"]`)
    into the set of dotted extensions they cover (e.g. `{".pdf", ".jpg", ...}`).
    An unknown category is ignored here — it is validated earlier, in
    `config.py`. Does not cover `CATEGORY_ALL`, which is not a fixed set —
    see `is_extension_allowed()`.
    """
    extensions: set[str] = set()
    for category in categories:
        extensions |= EXTENSION_CATEGORIES.get(category, set())
    return extensions


def is_extension_allowed(extension_with_dot: str, categories: list[str]) -> bool:
    """Decides whether an extension enters the scan, given what the project
    configured in "Included extensions". With `CATEGORY_ALL` selected,
    accepts any extension not in `ALWAYS_BLOCKED_EXTENSIONS` (executable/
    binary); otherwise, only the extensions of the selected categories."""
    extension_with_dot = extension_with_dot.lower()
    if CATEGORY_ALL in categories:
        return extension_with_dot not in ALWAYS_BLOCKED_EXTENSIONS
    return extension_with_dot in extensions_for_categories(categories)


def category_of_extension(extension_with_dot: str) -> str | None:
    """Name of the category (e.g. `"imagens"`) an extension belongs to, or
    `None` if it doesn't match any known category."""
    extension_with_dot = extension_with_dot.lower()
    for category, extensions in EXTENSION_CATEGORIES.items():
        if extension_with_dot in extensions:
            return category
    return None


# Grouping is only for display in the form (section 6): the flat alphabetical
# list of eight checkboxes said nothing about what each label covers or what
# is similar to what. Does not change any scan rule — `EXTENSION_CATEGORIES`
# remains the source of truth.
CATEGORY_FAMILIES: dict[str, tuple[str, ...]] = {
    "documentos": ("pdf", "docx", "xlsx", "pptx"),
    "imagens": ("imagens",),
    "text_data": ("text", "web_dados"),
    "mensagens": ("email",),
}


def categories_by_family() -> list[tuple[str, list[dict]]]:
    """Categories grouped for the form, each with the extensions it covers.
    `CATEGORY_ALL` is deliberately left out: it's a rule ("everything except
    binaries"), not a fixed set, and the template shows it separately."""
    grouped: list[tuple[str, list[dict]]] = []
    for family, categories in CATEGORY_FAMILIES.items():
        items = [
            {"categoria": category, "extensoes": sorted(EXTENSION_CATEGORIES[category])}
            for category in categories
            if category in EXTENSION_CATEGORIES
        ]
        if items:
            grouped.append((family, items))
    return grouped

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Web-layer re-export of the interface internationalization table.

The table itself (`_TRANSLATIONS`, `DEFAULT_LANGUAGE`, `AVAILABLE_LANGUAGES`,
`_REFERENCE_LANGUAGE`, `valid_language()`, `translate()`) moved to
`gclaude_indexer/i18n.py` (Task 11, Phase 14): `artifacts.py` and
`windows_prep.py` — core, not `web/` — need to translate the four output
artifacts and `CLAUDE.md` into the interface's language too, and core code
must never import from `web/`. This module re-exports what it used to
define, so every existing `from .i18n import ...` in the web layer
(`web/app.py` and others) keeps working unchanged.

`LANGUAGE_COOKIE_NAME` stays here, not in core: it is an HTTP concept (the
cookie the web layer persists the user's choice in), not a translation
concept.
"""

from __future__ import annotations

from ..i18n import (
    AVAILABLE_LANGUAGES,
    DEFAULT_LANGUAGE,
    _REFERENCE_LANGUAGE,
    _TRANSLATIONS,
    translate,
    valid_language,
)

__all__ = [
    "AVAILABLE_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "LANGUAGE_COOKIE_NAME",
    "_REFERENCE_LANGUAGE",
    "_TRANSLATIONS",
    "translate",
    "valid_language",
]

LANGUAGE_COOKIE_NAME = "language"

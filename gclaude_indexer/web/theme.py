# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Visual theme (user request), selectable when accessing the system and
persisted in a cookie — no account or database needed.

Four options: two light (`light`, `sepia`) and two dark (`dark`,
`high_contrast`). Each is just a set of `--color-*` tokens in `style.css`;
no layout rule depends on the chosen theme.

The four codes were translated to English (Task 9d, Phase 14, reversing an
earlier decision from Task 9c to keep them in Portuguese as enum-like values
shared with `style.css` (`html[data-theme="..."]` selectors) and the i18n
keys (`theme.light`, `theme.dark`, ...)). The "purely internal token" reading
was the wrong call for a project whose explicit goal is an English codebase
for outside contributors: this module's own first line is exactly the kind
of thing an outside contributor reads first. No stored state depends on the
old values: `valid_theme()` falls back to `DEFAULT_THEME` for anything
unrecognized, so an old `theme` cookie with `"claro"` just resets to the
default — nothing errors.
"""

from __future__ import annotations

DEFAULT_THEME = "light"
AVAILABLE_THEMES: tuple[str, ...] = ("light", "dark", "sepia", "high_contrast")
THEME_COOKIE_NAME = "theme"


def valid_theme(theme: str | None) -> str:
    return theme if theme in AVAILABLE_THEMES else DEFAULT_THEME

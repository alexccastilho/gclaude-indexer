# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Interface layout — the structure, separate from the palette (`theme.py`).

Four identities over the **same templates**: the variation comes from
`data-layout` on `<html>` and the rules in `static/layouts.css`. Duplicating
the templates per layout would multiply the cost of every future fix by
four, and the interface already went through two rounds of fixes in a row.

Orthogonal to the theme: 4 layouts × 4 palettes, chosen in separate
selectors. The four codes were translated to English (Task 9d, Phase 14,
reversing an earlier decision from Task 9c to keep them in Portuguese): they
are enum-like tokens shared with `layouts.css` (`html[data-layout="..."]`
selectors, ~100 occurrences) and with the i18n keys (`layout.standard`,
`layout.technical`, ...) — but they are also the first thing a contributor
reads when opening this module, and the codebase-wide push for English
identifiers outweighs the internal-token argument that justified the earlier
choice. No stored state depends on the old values: `valid_layout()` falls
back to `DEFAULT_LAYOUT` for anything unrecognized, so an old `layout`
cookie with `"padrao"` just resets to the default — nothing errors.
"""

from __future__ import annotations

DEFAULT_LAYOUT = "standard"
AVAILABLE_LAYOUTS: tuple[str, ...] = ("standard", "technical", "editorial", "compact")
LAYOUT_COOKIE_NAME = "layout"


def valid_layout(layout: str | None) -> str:
    return layout if layout in AVAILABLE_LAYOUTS else DEFAULT_LAYOUT

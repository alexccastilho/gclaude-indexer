# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Instruction files the user shares with the system.

`project_instructions.md` and the output folder's `CLAUDE.md` used to be
rewritten from scratch on every run: a `CLAUDE.md` the user already had in
that folder, or a rule they added to the generated file, was gone on the next
update. What the system writes now lives between two marks; everything
outside them belongs to the user and is carried over untouched.

The marks are HTML comments — invisible when the Markdown is rendered — and
fixed in every language, because the next run, possibly in another language,
has to find them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

BEGIN_MARK = (
    "<!-- GCLAUDE-INDEXER:BEGIN · gerado automaticamente / auto-generated / "
    "generado automáticamente — edite fora deste bloco / edit outside this block / "
    "edite fuera de este bloque -->"
)
END_MARK = "<!-- GCLAUDE-INDEXER:END -->"

_BEGIN_PREFIX = "<!-- GCLAUDE-INDEXER:BEGIN"

BACKUP_SUFFIX = ".bak"


def _split(existing: str) -> tuple[str, str] | None:
    """`(before, after)` around the managed block, or `None` with no block.

    A begin mark with no end mark (a hand edit gone wrong) takes the rest of
    the file as the old block: keeping it would leave a second, stale copy of
    the instructions next to the new one.
    """
    start = existing.find(_BEGIN_PREFIX)
    if start < 0:
        return None
    end = existing.find(END_MARK, start)
    after = "" if end < 0 else existing[end + len(END_MARK):]
    return existing[:start], after


def merge_managed(
    existing: str | None,
    generated: str,
    *,
    is_legacy: Callable[[str], bool] = lambda text: False,
    user_text: str = "",
) -> str:
    """The file's new content: the user's text kept, the block replaced.

    `is_legacy` recognizes a file written whole by a version from before the
    marks — that one is entirely ours and is replaced, not kept as the
    user's. `user_text` (instructions the user pasted into the project form)
    goes above the block, once.
    """
    block = f"{BEGIN_MARK}\n{generated.strip()}\n{END_MARK}\n"

    before, after = "", ""
    if existing and existing.strip():
        parts = _split(existing)
        # Only a file with no marks can be a legacy one: the new block carries
        # the same text the legacy check looks for.
        if parts is not None:
            before, after = parts
        elif not is_legacy(existing):
            before = existing

    user = user_text.strip()
    if user and user not in before and user not in after:
        before = user + "\n\n" + before.lstrip("\n")

    before = before.rstrip()
    after = after.strip()
    text = (before + "\n\n" if before else "") + block
    if after:
        text += "\n" + after + "\n"
    return text


def without_managed_block(existing: str) -> str:
    """The file as the user would have it with the system gone."""
    parts = _split(existing)
    if parts is None:
        return existing
    before, after = parts[0].rstrip(), parts[1].strip()
    text = before + ("\n\n" + after if before and after else after)
    return text + "\n" if text else ""


def write_managed(
    path: Path,
    generated: str,
    *,
    is_legacy: Callable[[str], bool] = lambda text: False,
    user_text: str = "",
) -> Path:
    """Merges `generated` into the file at `path` and writes it.

    The first time a file with no marks is touched, a copy goes to
    `<name>.bak` — the only moment the user's own content is restructured,
    and the only one that cannot be undone from the file itself.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing and existing.strip() and _split(existing) is None:
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_text(existing, encoding="utf-8")

    path.write_text(
        merge_managed(existing, generated, is_legacy=is_legacy, user_text=user_text),
        encoding="utf-8",
    )
    return path

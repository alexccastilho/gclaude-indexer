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
    "generado automáticamente · edite fora deste bloco / edit outside this block / "
    "edite fuera de este bloque -->"
)
END_MARK = "<!-- GCLAUDE-INDEXER:END -->"

_BEGIN_PREFIX = "<!-- GCLAUDE-INDEXER:BEGIN"

BACKUP_SUFFIX = ".bak"


def _one_newline_style(text: str) -> str:
    """`\\r\\n` and lone `\\r` as `\\n`. Written in text mode, a `\\r\\n` would
    become `\\r\\r\\n` on disk and read back as two lines."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


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


def has_managed_block(text: str) -> bool:
    return _split(_one_newline_style(text)) is not None


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
    goes above the block **only when nothing is outside the block yet**:
    once the file has the user's own content, that content is the truth and
    is carried over as it is.

    The text from the form arrives with `\\r\\n` (that is what a
    textarea sends) while the file reads back with `\\n`, so "is it already
    there?" compared two spellings of the same text and answered no on every
    regeneration — the real `project_instructions.md` had five copies of the
    user's instructions (82 KB, 1,737 lines) after five "save and generate
    again". Newlines are normalized here, where the file is assembled, and
    the rule above no longer depends on a text comparison at all.
    """
    generated = _one_newline_style(generated)
    block = f"{BEGIN_MARK}\n{generated.strip()}\n{END_MARK}\n"

    before, after = "", ""
    if existing and existing.strip():
        existing = _one_newline_style(existing)
        parts = _split(existing)
        # Only a file with no marks can be a legacy one: the new block carries
        # the same text the legacy check looks for.
        if parts is not None:
            before, after = parts
        elif not is_legacy(existing):
            before = existing

    user = _one_newline_style(user_text).strip()
    if user and not before.strip() and not after.strip():
        before = user + "\n\n"

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

    merged = merge_managed(existing, generated, is_legacy=is_legacy, user_text=user_text)
    # An identical file is left alone (see `artifacts.write_if_changed`).
    if existing is None or _one_newline_style(existing) != merged:
        path.write_text(merged, encoding="utf-8")
    return path


def user_part(path: Path) -> str:
    """What the user owns in the file at `path`: everything outside the
    managed block (a file with no marks is all theirs). Empty when the file
    does not exist or cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return without_managed_block(_one_newline_style(text)).strip()


def generated_part(path: Path) -> str:
    """The text of the managed block of the file at `path`, marks left
    out; empty with no file or no block. Shown read-only on the
    instructions screen, so the person sees what the program adds
    without being able to edit it there."""
    try:
        text = _one_newline_style(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ""
    parts = _split(text)
    if parts is None:
        return ""
    before, after = parts
    block = text[len(before):len(text) - len(after)]
    lines = [line for line in block.splitlines() if not line.startswith((_BEGIN_PREFIX, END_MARK))]
    return "\n".join(lines).strip()


def replace_user_part(path: Path, user_text: str, *, stamp: str, allow_empty: bool = False) -> bool:
    """Puts `user_text` in place of the user's part of the file, keeping the
    managed block as it is.

    The instructions the user keeps in the Claude Project can be edited
    there, so the copy in this file may be older than theirs; the update
    screen asks for the current text and this is what applies it. A pasted
    text that carries a managed block of its own (the whole file pasted
    back) keeps only what is outside it. Nothing changes — and `False` is
    returned — for an empty text or one equal to what is already there.
    Otherwise the previous file is kept as `<name>.<stamp>.bak`, so no
    version of the user's instructions is ever lost, and `True` returns.
    """
    new_user = without_managed_block(_one_newline_style(user_text)).strip()
    if not new_user and not allow_empty:
        return False
    try:
        existing = _one_newline_style(path.read_text(encoding="utf-8")) if path.exists() else ""
    except (OSError, UnicodeDecodeError):
        return False
    if new_user == without_managed_block(existing).strip():
        return False

    parts = _split(existing)
    if parts is None:
        block = ""
    else:
        before, after = parts
        block = existing[len(before):len(existing) - len(after)].strip()
    if existing.strip():
        path.with_name(f"{path.name}.{stamp}{BACKUP_SUFFIX}").write_text(existing, encoding="utf-8")
    text = new_user + "\n" if new_user else ""
    if block:
        text += ("\n" if text else "") + block + "\n"
    path.write_text(text, encoding="utf-8")
    return True

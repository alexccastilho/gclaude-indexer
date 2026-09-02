# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Date/time formatting for display in the interface (explicit user
request): the stored value stays ISO 8601 (standard format, sortable, no
ambiguity — never changes), but the screen always shows the customary
format of the language chosen at the moment of display.
"""

from __future__ import annotations

from datetime import datetime


def _to_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def format_datetime(value: str | datetime | None, language: str) -> str:
    dt = _to_datetime(value)
    if dt is None:
        return "—"
    if language == "en":
        return dt.strftime("%m/%d/%Y %I:%M:%S %p")
    # pt-BR and es-ES: DD/MM/YYYY, 24-hour clock.
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def format_date(value: str | datetime | None, language: str) -> str:
    dt = _to_datetime(value)
    if dt is None:
        return "—"
    if language == "en":
        return dt.strftime("%m/%d/%Y")
    return dt.strftime("%d/%m/%Y")

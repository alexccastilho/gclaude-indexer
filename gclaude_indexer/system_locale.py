# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Detects the Windows UI language to use as the web interface's default
language (user requirement 5: "the system must identify which language the
user is using on Windows, for presenting the processing results, logs,
interface, etc.").

Only the interface's *default* is decided here — a user who ever picks a
language in the selector (`web/i18n.py`) keeps that choice via the
`language` cookie from then on; this module only answers the question for
whoever has not chosen one yet (see `web/i18n.py::DEFAULT_LANGUAGE`,
`web/app.py::render()`).

Detection must never crash the application: an unresponsive, unusual or
non-Windows system simply falls back to `FALLBACK_LANGUAGE` — the same
value used for any Windows language this interface does not ship.
"""

from __future__ import annotations

import ctypes
import locale
import os

# English, not Portuguese: for a published project, whoever runs it on a
# system language we did not translate is better served by English than by
# a Portuguese they may not read at all (user decision, Task 10, Phase 14).
FALLBACK_LANGUAGE = "en"

# Locale codes that need a specific family mapping instead of the generic
# "keep the part before the underscore" rule in `_locale_family()` below.
_FAMILY_OVERRIDES = {
    # The interface only ships Brazilian Portuguese texts (`web/i18n.py`'s
    # `pt` table) — there is no separate European Portuguese translation,
    # and Brazilian Portuguese still reads far closer to a Portugal user
    # than falling back to English would.
    "pt_PT": "pt",
}

_SUPPORTED_FAMILIES = ("pt", "en", "es")

# Explicit override, checked before asking Windows anything. Two reasons it
# exists: a user whose Windows language is not the language they want the
# interface in can force one without touching the code, and the test suite
# can pin a language so its assertions do not depend on the language of the
# machine running them (`tests/conftest.py`). An unrecognised value is
# ignored rather than trusted, so a typo degrades to detection instead of
# breaking the interface.
LANGUAGE_ENV_VAR = "GCLAUDE_INDEXER_LANGUAGE"


def _locale_family(locale_code: str | None) -> str:
    """Reduces a full locale code (`pt_BR`, `en_US`, `es_MX`, ...) to one of
    the families this interface actually translates (`pt`, `en`, `es`).
    Anything else — `None`, an unparsable code, or a language we don't ship
    — falls back to `FALLBACK_LANGUAGE`.

    Kept as a pure function, with no OS calls, separate from
    `detect_ui_language()`: the mapping itself (known code -> right family,
    unknown code -> fallback) is what is worth unit testing directly,
    without mocking Windows APIs to do it.
    """
    if not locale_code:
        return FALLBACK_LANGUAGE
    if locale_code in _FAMILY_OVERRIDES:
        return _FAMILY_OVERRIDES[locale_code]
    family = locale_code.split("_", 1)[0].lower()
    return family if family in _SUPPORTED_FAMILIES else FALLBACK_LANGUAGE


def _detect_windows_locale() -> str | None:
    """Best-effort read of the Windows UI language (e.g. `pt_BR`, `en_US`).

    Returns `None` when nothing usable comes back, instead of raising:
    system locale detection sits at the boundary of the operating system —
    a system that won't answer must fall back to the application default,
    never take the web server down with it.
    """
    try:
        # GetUserDefaultUILanguage() returns the LCID of the language
        # Windows itself displays menus/dialogs in — the "what language is
        # this user's Windows in" the requirement actually asks about, as
        # opposed to GetUserDefaultLocale() (regional/formatting settings,
        # which can differ from the display language).
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        code = locale.windows_locale.get(lcid)
        if code:
            return code
    except (AttributeError, OSError):
        # AttributeError: `ctypes.windll` only exists on Windows — this
        # covers running the test suite (or any future build) on another
        # OS. OSError: the kernel32 call itself failing on an otherwise
        # Windows system.
        pass

    try:
        code, _encoding = locale.getdefaultlocale()
        if code:
            return code
    except ValueError:
        # getdefaultlocale() raises ValueError when the environment
        # advertises a locale string it cannot parse — a misconfigured
        # system, not a defect here.
        pass
    except Exception:  # noqa: BLE001 - last-resort guard at an OS boundary
        # getdefaultlocale() is deprecated, and its failure modes are not
        # fully specified across Windows/Python versions. Requirement 5 is
        # explicit that an unresponsive system must fall back to the
        # default, never crash the app — this catch-all is the final safety
        # net after the specific cases above, at the one boundary (reading
        # the OS's own locale settings) where "specific exception" cannot
        # be guaranteed exhaustive.
        pass

    return None


def detect_ui_language() -> str:
    """Public entry point: the Windows UI language, reduced to one of this
    interface's families (`pt`, `en`, `es`), or `FALLBACK_LANGUAGE` ("en")
    when detection fails or the system's language is not one we ship.
    Never raises.

    `LANGUAGE_ENV_VAR` wins over detection when it holds a supported
    family, so a user can force the interface language and the test suite
    can stay independent of the machine's own Windows language.
    """
    override = os.environ.get(LANGUAGE_ENV_VAR, "").strip().lower()
    if override in _SUPPORTED_FAMILIES:
        return override
    return _locale_family(_detect_windows_locale())

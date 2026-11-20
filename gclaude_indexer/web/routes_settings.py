# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Header preferences (language, theme, layout), the manual and the About
screen with the installation check and the downloaded components."""

from __future__ import annotations

import time
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..install_diagnostics import check_installation
from .i18n import DEFAULT_LANGUAGE, LANGUAGE_COOKIE_NAME, valid_language
from .layout import DEFAULT_LAYOUT, LAYOUT_COOKIE_NAME, valid_layout
from .theme import THEME_COOKIE_NAME, DEFAULT_THEME, valid_theme
from .rendering import _request_language, render


router = APIRouter()


SYSTEM_AUTHOR = "Alex Camacho Castilho"


# --- About (explicit user request) --------------------------------------------


@router.get("/help", response_class=HTMLResponse)
def manual_screen(request: Request):
    """The full user manual, one document per language (same pattern as
    the Claude package guide): flowing text with tables and examples, which
    itemized i18n keys would chop into fragments. Each screen's help modal
    links to its own section here."""
    language = _request_language(request)
    return render(request, "help.html", {"manual_template": f"manual/{language}.html"})


@router.get("/about", response_class=HTMLResponse)
def about_screen(request: Request):
    # `language`: `check_installation()`'s diagnostic
    # text (GPU runtime, hardware-sensor availability) used to be hardcoded
    # Portuguese, shown as-is regardless of the interface's language — see
    # `install_diagnostics.py`'s module docstring.
    language = _request_language(request)
    from .. import components

    # Task 7: the downloaded components, read fresh on every visit (outside
    # `_about_cache`: a removal must show at once). A name in the query
    # string is only echoed when it is a manifest entry.
    removed = request.query_params.get("removed")
    remove_failed = request.query_params.get("remove_failed")
    return render(
        request,
        "about.html",
        {
            "autor": SYSTEM_AUTHOR,
            "diagnostico": _installation_report(language),
            "componentes": components.installed_components(),
            "componente_removido": removed if removed and components.get(removed) else None,
            "componente_nao_removido": remove_failed if remove_failed and components.get(remove_failed) else None,
        },
    )


@router.post("/about/components/remove")
async def remove_component(request: Request):
    """Deletes one downloaded component from this machine's private folder.
    The name travels in the form (it has `/`, "tessdata/script/Latin"), and
    only a manifest entry is ever touched (`components.remove`). Covered by
    `_only_own_pages` like every other POST."""
    from .. import components

    form = await request.form()
    name = str(form.get("name", ""))
    if components.get(name) is None:
        return RedirectResponse("/about", status_code=303)
    outcome = "removed" if components.remove(name) else "remove_failed"
    return RedirectResponse(f"/about?{outcome}={quote(name, safe='')}#components", status_code=303)


# The installation check asks Windows for every tool and the graphics
# driver (about a second); nothing in it changes from one click to the
# next, so the answer is kept for a few minutes.
ABOUT_CACHE_SECONDS = 300.0
_about_cache: dict[str, tuple[float, object]] = {}


def _installation_report(language: str):
    now = time.monotonic()
    cached = _about_cache.get(language)
    if cached is not None and now - cached[0] < ABOUT_CACHE_SECONDS:
        return cached[1]
    report = check_installation(language)
    _about_cache[language] = (now, report)
    return report


# --- preferences: language and theme (user request, selectors in the header) -


def _save_preference(request: Request, cookie_name: str, value: str, *, fetch_answer: bool = False) -> Response:
    """Stores a header preference in its cookie and sends the person back
    to the screen they were on. `fetch_answer`: the screen may change the
    preference in place (`X-Preference-Fetch: 1`) and then only needs the
    cookie, with 204."""
    if fetch_answer and request.headers.get("x-preference-fetch") == "1":
        response = Response(status_code=204)
    else:
        response = RedirectResponse(url=_back_to(request), status_code=303)
    response.set_cookie(cookie_name, value, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


def _back_to(request: Request) -> str:
    referer = request.headers.get("referer")
    if not referer:
        return "/projects"
    # accepts only the path, never redirects to another host (open redirect)
    from urllib.parse import urlparse

    path = urlparse(referer).path or "/projects"
    # "//evil.example/x" is a path to urlparse and a host to the browser.
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/projects"
    return path


@router.post("/preferences/language")
async def choose_language(request: Request):
    form = await request.form()
    language = valid_language(str(form.get("language", DEFAULT_LANGUAGE)))
    return _save_preference(request, LANGUAGE_COOKIE_NAME, language)


@router.post("/preferences/theme")
async def choose_theme(request: Request):
    form = await request.form()
    theme = valid_theme(str(form.get("theme", DEFAULT_THEME)))
    # The screen changes the theme in place, without a reload.
    return _save_preference(request, THEME_COOKIE_NAME, theme, fetch_answer=True)


@router.post("/preferences/layout")
async def choose_layout(request: Request):
    form = await request.form()
    layout = valid_layout(str(form.get("layout", DEFAULT_LAYOUT)))
    return _save_preference(request, LAYOUT_COOKIE_NAME, layout)

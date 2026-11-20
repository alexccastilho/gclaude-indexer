# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Drawing a page: the Jinja templates, the request's language, theme and
layout read from cookies, and the workspace side bar every screen shows."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..catalog import catalog_folder, list_projects
from ..staleness import is_stale as source_is_stale
from .step_state import last_known_status
from .formatting import format_date, format_datetime
from .i18n import AVAILABLE_LANGUAGES, LANGUAGE_COOKIE_NAME, valid_language, translate
from .layout import AVAILABLE_LAYOUTS, LAYOUT_COOKIE_NAME, valid_layout
from ..engine_names import ENGINE_LOCAL
from .theme import THEME_COOKIE_NAME, AVAILABLE_THEMES, valid_theme


WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))


def _static_version() -> str:
    """Short hash of everything in `static/`, appended to each CSS and JS
    link (`?v=`). `StaticFiles` sends no `Cache-Control`, so the browser
    falls back to heuristic caching and may keep an old stylesheet for days
    after an update: new pages drawn with the previous version's CSS. A new
    query string on every change of content makes the browser fetch again."""
    digest = hashlib.sha256()
    for path in sorted((WEB_ROOT / "static").rglob("*")):
        if path.is_file() and path.suffix in (".css", ".js"):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


templates.env.globals["static_version"] = _static_version()
templates.env.globals["ENGINE_LOCAL"] = ENGINE_LOCAL
# Onde o projeto vive. Aqui e não no i18n: um endereço não se traduz, e
# três cópias dele seriam três oportunidades de divergir.
PROJECT_URL = "https://github.com/alexccastilho/gclaude-indexer"


def _request_language(request: Request) -> str:
    """The interface language of this request: the cookie set by the
    header's selector, or the default."""
    return valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))


def render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Replaces `templates.TemplateResponse` in every route: injects `t()`
    (translation — user request: Portuguese, English and Spanish,
    selectable when accessing) and the current theme (light/dark) into
    every context, read from cookies, with no session and no dependency on
    JavaScript on the first page load."""
    language = _request_language(request)
    theme = valid_theme(request.cookies.get(THEME_COOKIE_NAME))
    layout = valid_layout(request.cookies.get(LAYOUT_COOKIE_NAME))
    full_context = dict(context or {})
    full_context.setdefault("t", lambda key, **kw: translate(language, key, **kw))
    full_context.setdefault("datetime", lambda value: format_datetime(value, language))
    full_context.setdefault("date", lambda value: format_date(value, language))
    full_context.setdefault("current_language", language)
    full_context.setdefault("available_languages", AVAILABLE_LANGUAGES)
    full_context.setdefault("current_theme", theme)
    full_context.setdefault("available_themes", AVAILABLE_THEMES)
    full_context.setdefault("current_layout", layout)
    full_context.setdefault("available_layouts", AVAILABLE_LAYOUTS)
    full_context.setdefault("project_url", PROJECT_URL)
    # Em toda tela, e não só na de Execução: um servidor rodando código
    # antigo produz resultado errado em qualquer etapa, e o usuário precisa
    # ver isso onde quer que esteja (ver `staleness.py`).
    full_context.setdefault("source_is_stale", source_is_stale())
    if layout == "workspace":
        full_context.setdefault("ws_projects", _side_bar_projects())
        full_context.setdefault("ws_project_id", _project_id_in_path(request.url.path))
    return templates.TemplateResponse(request, template_name, full_context, status_code=status_code)


# The workspace layout's side bar lists the projects on every
# screen. The catalog may be a shared file on Google Drive, so the list is
# kept a few seconds; the status dots come only from what the Projects
# screen already computed (`last_known_status`), never from a database.
SIDE_BAR_SECONDS = 10.0
_side_bar_cache: dict[str, tuple[float, list[dict]]] = {}
_side_bar_lock = threading.Lock()


def _initials(name: str) -> str:
    words = [word for word in re.split(r"[^\w]+", name) if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def _side_bar_projects() -> list[dict]:
    now = time.monotonic()
    with _side_bar_lock:
        cached = _side_bar_cache.get("list")
    if cached is not None and now - cached[0] < SIDE_BAR_SECONDS:
        return cached[1]
    try:
        folder = catalog_folder()
        items = [
            {
                "id": entry.id, "name": entry.name, "initials": _initials(entry.name),
                "status": last_known_status(entry.resolved_output_folder(folder)),
            }
            for entry in list_projects()
        ]
    except Exception:
        items = []
    with _side_bar_lock:
        _side_bar_cache["list"] = (now, items)
    return items


def _project_id_in_path(path: str) -> int | None:
    match = re.match(r"^/projects/(\d+)(/|$)", path)
    return int(match.group(1)) if match else None


def _zip_response(content: bytes, file_name: str) -> Response:
    """A ZIP as an attachment. The name is the user's free text: quoted in
    RFC 5987 form, with an ASCII fallback, so a `"` cannot break the header
    and an accent or a dash cannot turn the download into a 500."""
    file_name = file_name.replace(" ", "_")
    ascii_name = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in file_name)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"
        },
    )

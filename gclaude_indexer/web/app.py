# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Web interface (section 6): five screens — Projects, New project,
Execution, Update collection and Result — served by FastAPI + Jinja2, with
HTMX for the parts that update themselves. No front-end framework, no JavaScript build: HTML
served by Python itself; the only script is HTMX, vendored in
`static/htmx.min.js` (no network call at runtime).

Security (section 7): the server only listens on 127.0.0.1 (see
`start_server()`), every path input is resolved and validated against the
project folder before any read, and `subprocess` always runs with a list of
arguments.
"""

from __future__ import annotations

import hmac
import itertools
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import MISSING, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fastapi.responses import Response

from ..artifacts import (
    INDEX_FILENAME,
    PROJECT_INSTRUCTIONS_FILENAME,
    REVIEW_FILENAME,
    TIMELINE_FILENAME,
    generate_all_artifacts,
    generate_project_instructions_md,
    pending_items,
    stale_artifacts,
)
from ..catalog import CatalogEntry, find_project, list_projects, register_project
from ..config import ProjectConfig, ConfigError, load_config
from ..db import READER_TIMEOUT_SECONDS, WRITER_TIMEOUT_SECONDS, is_lock_error
from ..install_diagnostics import check_installation
from ..events import list_events, record_event
from ..instructions_dedup import apply as dedup_apply, block_pointer, detect as dedup_detect
from ..managed_block import BACKUP_SUFFIX, generated_part, replace_user_part, user_part
from ..deletion import delete_project
from ..import_items import import_and_consolidate
from ..invalidation import PlanExpired, apply_update_plan
from ..update_plan import SourceFolderUnavailable, UpdatePlan, build_update_plan
from ..cleanup import clear_intermediates, intermediates_size
from ..engine_claude_code import command_for_language, prepare, sync_progress
from .. import claude_package, combined_package
from ..claude_package import generate_claude_project_package
from ..paths import resolve_within
from ..run_control import OperationCancelled, StopSignal
from ..project import load_project, create_project, save_project_config
from ..sets import SetEntry, SetMember, find_set, list_sets, propose_alias, remove_set, save_set
from ..quality import compare_runs, quality_summary
from ..resources import latest_sample
from .. import sensors, sensor_service
from ..sensor_service import read_launch_status
from ..sensors import unavailable_reason
from .. import lexml as lexml_module
from ..fulltext import (
    MATCH_END as FULLTEXT_MATCH_END,
    MATCH_START as FULLTEXT_MATCH_START,
    coverage as fulltext_coverage,
    index_pending as index_fulltext,
    search as fulltext_search,
)
from ..settings_proposal import propose_for_folder
from ..staleness import is_stale as source_is_stale, record_loaded_source
from ..sync import check_sync, mark_synced
from ..file_types import CATEGORY_ALL, categories_by_family
from ..lock import LockManager, check_lock
from .step_state import STEPS, last_known_status, next_pending_step, project_status, step_status
from .background_runs import compute_progress, task_manager
from .readers import reader_pool
from .formatting import format_date, format_datetime
from .i18n import DEFAULT_LANGUAGE, AVAILABLE_LANGUAGES, LANGUAGE_COOKIE_NAME, valid_language, translate
from .layout import DEFAULT_LAYOUT, AVAILABLE_LAYOUTS, LAYOUT_COOKIE_NAME, valid_layout
from ..engine_local import recommended_local_model
from .ollama_models import list_installed_models
from .folder_picker import choose_folder
from .theme import THEME_COOKIE_NAME, DEFAULT_THEME, AVAILABLE_THEMES, valid_theme

WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))

SYSTEM_VERSION = "1.10.4"

# Fase 32: the one thing that lets a page ask for the elevated sensor
# helper. New on every server start, never written to disk, embedded only
# in the Run screen — a page no other origin can read. See
# `request_sensor_elevation` for the whole argument.
SENSOR_REQUEST_TOKEN = secrets.token_urlsafe(32)
# Held while a request for the elevated helper is in flight: `runas` blocks
# until the user answers the UAC prompt, and a second click (or a second
# tab) meanwhile must not open a second prompt behind the first.
_SENSOR_REQUEST_IN_FLIGHT = threading.Lock()

# The port this server was started on; `start_server()` records it. The
# `Host` guard below compares against it, so a server started on another
# port is still only reachable by its own pages.
SERVER_PORT = 8000
SYSTEM_AUTHOR = "Alex Camacho Castilho"
# Onde o projeto vive. Aqui e não no i18n: um endereço não se traduz, e
# três cópias dele seriam três oportunidades de divergir.
PROJECT_URL = "https://github.com/alexccastilho/gclaude-indexer"

# 50 lines covered less than a minute of scanning on a large collection — the
# panel would scroll out before there was time to read it. 200 fits in
# memory with no pagination and covers the follow-along window the user
# actually uses.
LOG_LINES = 200

# Step keys the live log (`_log.html`) knows how to translate — a superset
# of `STEPS`. `import` and `diagnostics` record real
# events (`import_items.py`, `hardware.py`) but are deliberately not part of
# `STEPS`: that tuple drives `next_pending_step`/`step_status`, i.e. the
# step-progress table and the "Run next step"/"Run all steps" buttons, and
# neither `import` (its own separate button) nor `diagnostics` (a check that
# runs inside the classification step, not a step of its own) belongs there.
# Without this set, `_log.html` falls back to showing the raw step key
# instead of a translated label — see `import_items.py`'s module docstring.
LOG_KNOWN_STEPS = set(STEPS) | {"import", "diagnostics", "update"}

# Presentation order of the engines in the form, from the simplest to use to
# the one that demands the most from the user. `CLASSIFICATION_ENGINES`
# (config.py) is a set and has no stable order — it stays the source of
# truth for validation, never for presentation. A test guarantees the two
# sets match.
CLASSIFICATION_ENGINES_ORDER: tuple[str, ...] = ("automatic", "rules", "local", "claude_code")


def render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Replaces `templates.TemplateResponse` in every route: injects `t()`
    (translation — user request: Portuguese, English and Spanish,
    selectable when accessing) and the current theme (light/dark) into
    every context, read from cookies, with no session and no dependency on
    JavaScript on the first page load."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
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
    full_context.setdefault("system_version", SYSTEM_VERSION)
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
        from ..catalog import catalog_folder

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

# Cross-machine database lock (section 11.3): one per project opened in this
# server session, with its own heartbeat. All removed on shutdown.
lock_manager = LockManager()


def _project_busy(output_folder) -> bool:
    """Whether a step of the project is running in the background — with
    no screen open, it still needs the lock."""
    key = LockManager._key(output_folder)
    for entry in list_projects():
        if LockManager._key(entry.output_folder) == key:
            task = task_manager.latest_for_project(entry.id)
            if task is not None and task.running:
                return True
            with _IMPORTS_IN_PROGRESS_LOCK:
                return entry.id in _IMPORTS_IN_PROGRESS
    return False


lock_manager.set_keep_alive(_project_busy)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    reader_pool.close_all()
    lock_manager.close_all()


app = FastAPI(title="GClaude Indexer", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")


# --- only the program's own pages may talk to the program --------------------
#
# The server listens on 127.0.0.1, but every page open in the user's browser
# can send requests there. Without these checks a malicious site could post
# "delete this project with its files", create projects in any folder, or
# make Windows authenticate to its own server by asking this one to look at a
# `\\attacker\share` path. Three checks, cheapest first:
#
# - `Host` must be loopback: a DNS-rebinding page reaches 127.0.0.1 under its
#   own domain name, and is refused here before it can read any answer.
# - `Sec-Fetch-Site` (sent by every current browser): a request another site
#   started is refused — except a plain link with no parameters, so a
#   bookmark or a link in a document still opens the screen.
# - `Origin` on anything that changes state: the classic CSRF check, for a
#   browser that does not send `Sec-Fetch-Site`.
#
# UNC paths are deliberately still accepted from the program's own forms:
# corporate collections live on `\\server\share`, and the danger was never
# the path, it was who chose it.
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal — never ours, which listens on 127.0.0.1
        return host
    return host.rsplit(":", 1)[0]


def _request_is_trusted(request: Request) -> bool:
    host_header = request.headers.get("host", "")
    if _host_name(host_header) not in ALLOWED_HOSTS:
        return False

    site = request.headers.get("sec-fetch-site")
    if site in ("cross-site", "same-site"):
        return (
            request.method in _SAFE_METHODS
            and request.headers.get("sec-fetch-mode") == "navigate"
            and not request.url.query
        )

    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None:
            from urllib.parse import urlparse

            if origin == "null" or urlparse(origin).netloc.lower() != host_header.strip().lower():
                return False
    return True


@app.middleware("http")
async def _only_own_pages(request: Request, call_next):
    if not _request_is_trusted(request):
        return Response(
            "Pedido recusado: ele não veio das telas do GClaude Indexer. / "
            "Request refused: it did not come from GClaude Indexer's own screens. / "
            "Solicitud rechazada: no vino de las pantallas de GClaude Indexer.",
            status_code=403,
            media_type="text/plain; charset=utf-8",
        )
    response = await call_next(request)
    # No page of this app is ever meant to live inside another site's
    # frame. Without this, a site could embed the Run screen invisibly and
    # steer the user's click onto "Read CPU sensors and fans" (or onto
    # "Delete project"): the request would then come from our own page,
    # with every guard satisfied. One header, every page (final review of
    # fase 32); the CSP form is the modern spelling of the same rule.
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    return response


class LockBlockedError(Exception):
    # Carries the translation key and its parameters, not rendered text: the
    # check runs before the request's language is known, and the screen is
    # what renders it (user requirement 3).
    def __init__(self, entry: CatalogEntry, message_key: str, message_params: dict[str, object]):
        self.entry = entry
        self.message_key = message_key
        self.message_params = message_params


class LockAbandonedError(Exception):
    # Carries the translation key and its parameters, not rendered text: the
    # check runs before the request's language is known, and the screen is
    # what renders it (user requirement 3).
    def __init__(self, entry: CatalogEntry, message_key: str, message_params: dict[str, object]):
        self.entry = entry
        self.message_key = message_key
        self.message_params = message_params


class IncompleteSyncError(Exception):
    # Carries the translation key and its parameters, not rendered text: the
    # check runs before the request's language is known, and the screen is
    # what renders it (user requirement 3).
    def __init__(self, entry: CatalogEntry, message_key: str, message_params: dict[str, object]):
        self.entry = entry
        self.message_key = message_key
        self.message_params = message_params


@app.exception_handler(LockBlockedError)
def _handle_lock_blocked(request: Request, exc: LockBlockedError):
    return render(
        request, "lock_blocked.html",
        {"project": exc.entry, "message_key": exc.message_key, "message_params": exc.message_params}, status_code=423,
    )


@app.exception_handler(LockAbandonedError)
def _handle_lock_abandoned(request: Request, exc: LockAbandonedError):
    return render(
        request, "lock_abandoned.html",
        {"project": exc.entry, "message_key": exc.message_key, "message_params": exc.message_params}, status_code=409,
    )


@app.exception_handler(IncompleteSyncError)
def _handle_incomplete_sync(request: Request, exc: IncompleteSyncError):
    return render(
        request, "incomplete_sync.html",
        {"project": exc.entry, "message_key": exc.message_key, "message_params": exc.message_params}, status_code=409,
    )

INTEGER_FIELDS = ("pages_per_block", "pages_per_window", "overlap", "chars_per_page")
TEXT_FIELDS = (
    "name", "subject", "source_folder", "output_folder", "collection_type", "group_mode",
    "group_pattern", "ocr_language", "classification_engine", "local_model", "processing_mode",
    "parallelism", "role_instructions", "extra_rules", "existing_instructions",
)


# --- utilities ---------------------------------------------------------------


@app.exception_handler(sqlite3.OperationalError)
def _handle_database_busy(request: Request, exc: sqlite3.OperationalError):
    """`database is locked` is a moment, not a failure. Before this,
    the Execution screen's three polls answered it with "Internal
    Server Error" every two seconds, which read as the program breaking.

    A poll (htmx sends `HX-Request`) gets 204 No Content: htmx keeps the
    fragment it already shows and asks again on the next tick. A whole page
    gets a short translated explanation with 503, so the browser does not
    cache it. Any other database error is still a real error."""
    if not is_lock_error(exc):
        raise exc
    if request.headers.get("hx-request"):
        return Response(status_code=204)
    return render(request, "database_busy.html", {}, status_code=503)


@contextmanager
def _open_project(project_id: int, timeout: float = WRITER_TIMEOUT_SECONDS):
    """Opens the project for use in this request. The first time, in this
    server session, that this project is touched: checks the incomplete
    sync signal (section 11.4) and the other machine's lock (section 11.3)
    before releasing it — later visits no longer repeat the check, because
    the lock is already ours.

    `timeout`: the Execution screen's polls pass `READER_TIMEOUT_SECONDS`, so
    a busy database costs them a few seconds, not thirty."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    try:
        config, conn = load_project(entry.output_folder, timeout=timeout)
    except ConfigError as exc:
        # No request-scoped language available in this context manager (see
        # `config.py`'s docstring) — `DEFAULT_LANGUAGE`, same as every other
        # caller with no language of its own. This 500 is an internal-error
        # fallback (a project's saved config failed re-validation), not part
        # of the normal form-submission flow that Task 18 fixed.
        details = "; ".join(translate(DEFAULT_LANGUAGE, e.key, **e.params) for e in exc.errors)
        raise HTTPException(status_code=500, detail=f"Configuração do projeto inválida: {details}")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível abrir o projeto: {exc}")

    if not lock_manager.is_open(entry.output_folder):
        sync_result = check_sync(entry.output_folder)
        if not sync_result.ok:
            conn.close()
            raise IncompleteSyncError(entry, sync_result.message_key, sync_result.message_params)

        lock_result = check_lock(entry.output_folder)
        if lock_result.status == "blocked":
            conn.close()
            raise LockBlockedError(entry, lock_result.message_key, lock_result.message_params)
        if lock_result.status == "abandoned":
            conn.close()
            raise LockAbandonedError(entry, lock_result.message_key, lock_result.message_params)

        lock_manager.open(entry.output_folder)
        mark_synced(entry.output_folder)

    lock_manager.begin_use(entry.output_folder)
    try:
        yield entry, config, conn
    finally:
        lock_manager.end_use(entry.output_folder)
        conn.close()


@contextmanager
def _read_project(project_id: int, timeout: float = READER_TIMEOUT_SECONDS):
    """`_open_project` for the screens that only read: the same
    `(entry, config, conn)`, with `conn` the project's read-only connection
    that stays open between requests (see `readers.py`). The first visit of
    the session still goes through `_open_project`, which runs the sync and
    lock checks; anything that cannot use the reader falls back to it."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    reader = reader_pool.acquire(entry.output_folder) if lock_manager.is_open(entry.output_folder) else None
    if reader is None:
        with _open_project(project_id, timeout=timeout) as opened:
            yield opened
        return
    lock_manager.begin_use(entry.output_folder)
    try:
        yield entry, reader.config, reader.conn
    finally:
        lock_manager.end_use(entry.output_folder)
        reader_pool.release(reader)


@app.post("/projects/{project_id}/alive")
def project_alive(project_id: int):
    """A screen of the project is still open: keeps its lock.
    Never takes the lock — that is the next real request's job, with the
    usual check of who else holds it."""
    entry = find_project(project_id)
    if entry is not None:
        lock_manager.touch(entry.output_folder)
    return Response(status_code=204)


def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}min {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}min"


def _config_to_form(data: dict | None = None) -> dict:
    """Values shown in the form: the section 6 defaults, overridden by
    whatever was submitted (to redisplay it on a validation error).
    `name`, `source_folder` and `output_folder` have no `default` on the
    dataclass (they are required) — without this, the displayed value would
    be the `dataclasses.MISSING` sentinel, not an empty string."""
    base = {
        field.name: field.default if field.default is not MISSING else ""
        for field in ProjectConfig.__dataclass_fields__.values()
    }
    base["extensions"] = ["pdf", "docx", "imagens"]
    if data:
        base.update(data)
    # "automatic" is the dataclass default, not the name of an installed
    # model — without this, no <option> of the <select> ends up `selected`
    # and the browser picks the first one. Resolved *after* `update(data)`
    # so an explicit user choice (a real model name, coming from the
    # <select>) always wins; only the "automatic" sentinel (from the
    # default, or resubmitted as-is) falls back to the default.
    if base.get("local_model") in ("", "automatic"):
        base["local_model"] = recommended_local_model()
    return base


# --- screen: Projects ---------------------------------------------------------


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/projects")


@app.get("/projects", response_class=HTMLResponse)
def projects_screen(request: Request):
    from ..catalog import catalog_folder
    from ..settings import configured_shared_catalog_folder

    folder = catalog_folder()
    projects = []
    for e in list_projects():
        # The path as *this* machine sees it: with a shared catalog, the
        # entry was very likely written on a computer whose Drive is
        # mounted under a different letter (section 11.5).
        resolved = e.resolved_output_folder(folder)
        available = e.is_available(folder)
        if available:
            key, variables = project_status(resolved)
        else:
            # Listed, not hidden: a shared catalog legitimately contains
            # projects stored on another computer's local disk, and the
            # honest thing is to show them as out of reach here rather than
            # pretend they do not exist or report them as broken.
            key, variables = "unavailable_here", {"folder": resolved}
        projects.append({
            "id": e.id, "name": e.name, "created_at": e.created_at,
            "status_key": key, "status_vars": variables, "available": available,
        })
    return render(
        request, "projects.html",
        {
            "projects": projects,
            "shared_catalog_folder": configured_shared_catalog_folder(),
            "shared_catalog_active": folder is not None,
        },
    )


@app.post("/projects/shared-catalog", response_class=HTMLResponse)
async def set_shared_catalog(request: Request):
    form = await request.form()
    return await run_in_threadpool(_set_shared_catalog_body, request, form)


def _set_shared_catalog_body(request: Request, form):
    """Points the catalog at a folder on the Drive (or clears it).

    Adopting the machine's existing projects into the shared file is part
    of the same action on purpose: setting the folder and then finding the
    screen still empty on the other computer — because nothing was copied
    until each project happened to be reopened here — would look exactly
    like the bug this fixes.
    """
    from ..catalog import adopt_local_projects
    from ..settings import set_shared_catalog_folder

    set_shared_catalog_folder(str(form.get("shared_catalog_folder", "")))
    try:
        adopt_local_projects()
    except OSError:
        # The folder went away between being chosen and being written to
        # (Drive still starting, a typed path that does not exist). The
        # setting is kept — the screen shows it as not reachable — and the
        # local catalog goes on working.
        pass
    return RedirectResponse("/projects", status_code=303)


# --- screen: New project -------------------------------------------------------


@app.get("/projects/new", response_class=HTMLResponse)
def new_project_screen(request: Request):
    return render(
        request, "new_project.html",
        {
            "values": _config_to_form(),
            "familias": categories_by_family(),
            "category_all": CATEGORY_ALL,
            "engines": CLASSIFICATION_ENGINES_ORDER,
            "local_models": list_installed_models(),
            "default_local_model": recommended_local_model(),
            "errors": [],
        },
    )


@app.post("/projects/new", response_class=HTMLResponse)
async def create_new_project(request: Request):
    form = await request.form()
    return await run_in_threadpool(_create_new_project_body, request, form)


def _create_new_project_body(request: Request, form):

    data: dict = {}
    for field in TEXT_FIELDS:
        if field in form:
            data[field] = str(form[field])
    for field in INTEGER_FIELDS:
        if field in form and str(form[field]).strip():
            try:
                data[field] = int(form[field])
            except ValueError:
                data[field] = form[field]  # let load_config's validation report it
    data["extensions"] = form.getlist("extensions")
    data["review_low_confidence"] = "review_low_confidence" in form

    try:
        config = load_config(data)
    except ConfigError as exc:
        values = _config_to_form(data)
        return render(
            request, "new_project.html",
            {
                "values": values,
                "familias": categories_by_family(),
                "category_all": CATEGORY_ALL,
                "engines": CLASSIFICATION_ENGINES_ORDER,
                "local_models": list_installed_models(),
                "default_local_model": recommended_local_model(),
                "errors": exc.errors,
            },
            status_code=400,
        )

    # A project already in this output folder is not an error to report and
    # walk away from — it is almost always the user trying to *reopen* it,
    # which is the gesture that had no other route. Creating here would
    # INSERT a second configuration row into that project's own database
    # and replace the saved settings with this form's, silently, keeping
    # the processed data so that nothing looked wrong (see `load_project`).
    # So the form stops and offers the thing that was actually meant.
    from ..project import describe_project

    existing = describe_project(config.output_folder)
    if existing is not None:
        return render(
            request, "new_project.html",
            {
                "values": _config_to_form(data),
                "familias": categories_by_family(),
                "category_all": CATEGORY_ALL,
                "engines": CLASSIFICATION_ENGINES_ORDER,
                "local_models": list_installed_models(),
                "default_local_model": recommended_local_model(),
                "errors": [],
                "existing_project": existing,
            },
            status_code=409,
        )

    conn, _ = create_project(config)
    conn.close()
    entry = register_project(config.name, config.output_folder)
    _side_bar_cache.clear()  # The side bar shows it at once
    return RedirectResponse(url=f"/projects/{entry.id}/run", status_code=303)


@app.get("/projects/open", response_class=HTMLResponse)
def open_project_screen(request: Request, folder: str = ""):
    """Reopening a project that this machine's catalog does not list.

    The shared catalog covers "the same Drive on another computer". This
    covers everything else: a reinstall, a reformatted machine, a different
    account, a folder that was moved, a folder someone sent you. In all of
    those the project is intact — the output folder holds `project.db` with
    the configuration, the scanned files, the pages and the classified
    items — and what was missing was a way to say "open that one".

    `folder` arrives pre-filled when the New project form redirects here
    after finding a project already in the chosen output folder: the user
    has picked that folder once and should not have to pick it again.
    """
    from ..project import describe_project

    summary = describe_project(folder) if folder else None
    return render(request, "open_project.html", {"value": folder, "summary": summary, "error": None})


@app.post("/projects/open", response_class=HTMLResponse)
async def open_project(request: Request):
    form = await request.form()
    return await run_in_threadpool(_open_project_body, request, form)


def _open_project_body(request: Request, form):
    """Two steps in one route: inspect, then (on confirmation) adopt.

    The inspection is read-only (`describe_project` opens the database with
    `mode=ro`), so looking at a folder can never be what creates something
    in it. Only the confirmed second pass writes, and all it writes is the
    catalog entry — the project itself is used exactly as it was found.
    """
    from ..project import describe_project

    folder = str(form.get("existing_output_folder", "")).strip()
    confirmed = "confirm" in form

    if not folder:
        return render(
            request, "open_project.html",
            {"value": "", "summary": None, "error": "open_project.error_empty"},
            status_code=400,
        )

    summary = describe_project(folder)
    if summary is None:
        return render(
            request, "open_project.html",
            {"value": folder, "summary": None, "error": "open_project.error_not_found"},
            status_code=400,
        )

    if not confirmed:
        return render(request, "open_project.html", {"value": folder, "summary": summary, "error": None})

    entry = register_project(summary.name or Path(folder).name, folder)
    _side_bar_cache.clear()  # The side bar shows it at once
    return RedirectResponse(url=f"/projects/{entry.id}/run", status_code=303)


@app.post("/select-folder", response_class=HTMLResponse)
async def select_folder(request: Request):
    form = await request.form()
    return await run_in_threadpool(_select_folder_body, request, form)


def _select_folder_body(request: Request, form):
    # `field` is the form's internal DOM id/hook (see `_folder_field.html`,
    # `new_project.html`) — the same string as the input's `name=` (what
    # actually reaches the POST body) since both were unified to the
    # English field name; no separate mapping is needed anymore.
    # The wire key itself was `campo` (Portuguese) until Task 18 —
    # renamed to `field` together with `_folder_field.html`'s Jinja variable
    # and `new_project.html`'s `hx-vals`, all three in the same change.
    field = str(form.get("field", "source_folder"))
    current_value = str(form.get(field, ""))

    # `title`: the native Windows folder picker used to
    # always open with a fixed Portuguese title bar, regardless of the
    # interface's language — this dialog is not a Jinja template, so it was
    # missed by every prior i18n pass.
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    folder = choose_folder(title=translate(language, "new_project.folder_picker_title"), initial=current_value)
    value = folder or current_value

    response = render(
        request, "_folder_field.html", {"field": field, "form_field_name": field, "value": value},
    )
    if field == "source_folder" and folder:
        # The settings proposal panel listens for this and analyses the
        # folder just chosen (see `_settings_proposal.html`).
        response.headers["HX-Trigger"] = "sourceFolderChosen"
    return response


@app.post("/projects/propose-settings", response_class=HTMLResponse)
async def propose_settings(request: Request):
    form = await request.form()
    return await run_in_threadpool(_propose_settings_body, request, form)


def _propose_settings_body(request: Request, form):
    """Looks at the source folder and proposes the five fields of
    "Slicing, windows and OCR" — see `settings_proposal.py`."""
    folder_text = str(form.get("source_folder", "")).strip()
    categories = [str(value) for value in form.getlist("extensions")]
    folder = Path(folder_text) if folder_text else None
    if folder is None or not folder.is_dir():
        return render(request, "_settings_proposal.html", {"proposal": None, "folder": folder_text})

    proposal = propose_for_folder(folder, categories)
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731

    def reason_text(reason) -> str:
        params = dict(reason.params)
        if "languages" in params:
            params["languages"] = ", ".join(t(f"proposal.language.{code}") for code in params["languages"])
        return t(reason.key, **params)

    survey = proposal.survey
    composition = [
        t("proposal.composition_item", count=count, kind=t(f"new_project.category.{category}"))
        for category, count in survey.by_category.most_common()
    ]
    return render(
        request, "_settings_proposal.html",
        {
            "proposal": proposal,
            "folder": folder_text,
            "reasons": {name: [reason_text(r) for r in items] for name, items in proposal.reasons.items()},
            "composition": composition,
            "estimated_pages": survey.estimated_pages(),
        },
    )


# --- cross-machine portability: lock and sync (section 11) -------------------


@app.post("/projects/{project_id}/take-lock")
def take_over_lock_route(project_id: int):
    """Explicit user confirmation to take over an abandoned lock (section
    11.3 — a lock from another machine, unused for more than 10 minutes)."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    reader_pool.close(entry.output_folder)
    lock_manager.take_over(entry.output_folder)
    mark_synced(entry.output_folder)
    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)


@app.post("/projects/{project_id}/continue-anyway")
def continue_anyway_route(project_id: int):
    """Explicit user confirmation to continue despite the incomplete sync
    warning (section 11.4)."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    mark_synced(entry.output_folder)
    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)


# --- screen: Execution ---------------------------------------------------------


@app.get("/projects/{project_id}/run", response_class=HTMLResponse)
def run_screen(request: Request, project_id: int):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _read_project(project_id, timeout=WRITER_TIMEOUT_SECONDS) as (entry, config, conn):
        steps_context = _steps_context(project_id, entry, config, conn, language)
        # Oldest first, newest at the bottom — the order every console and
        # log viewer uses, and the one the screen's "follow" behaviour
        # assumes. It used to be `reversed(...)`, newest at the top, while
        # the JavaScript scrolled to the *bottom* on every refresh: the two
        # halves disagreed, so following the run meant being dragged to the
        # oldest of the visible lines every two seconds.
        events = list_events(conn, language=language, last=LOG_LINES)
        stale = _stale_context(_reports_to_regenerate(conn))
        instructions_dedup = _dedup_notice(conn, config)

    claude_code_status = None
    if config.classification_engine == "claude_code":
        # The only part of this screen that writes, so it alone takes a
        # normal connection (the rest above read through the project's
        # read-only one, 1.9.1).
        with _open_project(project_id) as (entry, config, conn):
            # `prepare()` writes `CLAUDE.md` (idempotent) and must run
            # before the user is told to type the command: `start_all()`
            # skips the classification step for this engine, so nothing
            # else in the running application ever wrote that file — the
            # engine was unusable end to end even though its own tests
            # passed, because only the tests ever called `prepare()`.
            prepare(conn, config, language)
            claude_code_status = sync_progress(conn, config, language)

    return render(
        request, "run.html",
        {
            **steps_context,
            "config": config, "eventos": events,
            "known_steps": LOG_KNOWN_STEPS,
            "claude_code_status": claude_code_status,
            "sensor_token": SENSOR_REQUEST_TOKEN,
            "instructions_dedup": instructions_dedup,
            **stale,
        },
    )


def _reports_to_regenerate(conn):
    """Out-of-date reports, but only once there is nothing left to process.

    Two different questions share the word "pending" and must not share a
    predicate. `_pipeline_has_pending_work` below deliberately ignores
    pending *windows*, so that someone who stops classification part-way
    still sees the update banner. Here the opposite holds: nudging "generate
    the reports" while windows are still waiting for the model would produce
    reports that are incomplete the moment they are written, and stale again
    a minute later. So this one does consult them.

    The nudge is only a nudge. The button itself is always on the Execution
    screen, so a user who deliberately stopped half-way and wants reports
    for what is done can still ask for them.
    """
    if _pipeline_has_pending_work(conn):
        return None
    if conn.execute("SELECT 1 FROM window WHERE status = 'pending' LIMIT 1").fetchone():
        return None
    return stale_artifacts(conn)


def _stale_context(staleness) -> dict:
    """The numbers the two notices interpolate, or an empty dict."""
    if staleness is None:
        return {"stale": None, "stale_numbers": {}}
    return {
        "stale": staleness,
        "stale_numbers": {
            "generated_at": staleness.generated_at,
            "was_files": staleness.recorded.files,
            "was_windows": staleness.recorded.windows_done,
            "was_items": staleness.recorded.items,
            "now_files": staleness.current.files,
            "now_windows": staleness.current.windows_done,
            "now_items": staleness.current.items,
        },
    }


def _pipeline_has_pending_work(conn) -> bool:
    """Whether documents are still waiting to be converted or extracted.

    Used only to silence the update banner, and only for that one case:
    while a file sits in `'discovered'` or `'converted'`, the honest next
    action is to run the steps — `convert()` selects the first,
    `extract_pages()` the second — not to diagnose the folder again. It
    is deliberately *not* "did an update just happen": nothing records
    that, and inferring it from a flag would be one more value derived
    twice.

    Statuses left out on purpose. `'extracted'` is a finished file;
    `'failed'`, `'skipped'` and `'duplicate'` are terminal for this run —
    no step picks them up, so a collection holding only those has no
    pending work and the notice is honest again.

    Pending *windows* are not consulted, though the classification
    engines do select `window.status = 'pending'`. The only transition
    in the codebase is `pending -> 'done'` on success, so a user who
    stops classification part-way — an ordinary thing to do at roughly
    thirty seconds a window, and the Execution screen offers the button
    — would leave windows pending forever and never see the banner
    again for that project. Nor did the clause earn its place: after an
    apply of a pure addition nothing is `'discovered'` or `'converted'`
    and the discarded tail windows are gone, so the predicate was
    already False and the banner returned anyway. Applying the same plan
    twice is prevented by the key-based layout comparison in
    `update_plan._layout_disagrees`, not by this guard.
    """
    return conn.execute(
        "SELECT 1 FROM file WHERE status IN ('discovered', 'converted') LIMIT 1"
    ).fetchone() is not None


@app.get("/projects/{project_id}/update/banner", response_class=HTMLResponse)
def update_banner(request: Request, project_id: int):
    """The "the folder changed" notice on the Execution screen.

    Fetched by HTMX after the page renders, never before it: on a large
    Drive-synced collection the walk takes seconds, and paying them before
    the first pixel would trade one problem for another. An unreachable
    source folder renders nothing — the screen is not the place to shout
    about a disconnected drive, and `SourceFolderUnavailable` never
    becomes a removal proposal.

    `record_warnings=False`: this runs on every open of the Execution
    screen, so it must not be able to write a single row.
    """
    # While an update or a generation runs, the folder is walked by
    # it already; a second walk here would only slow both down.
    with _IMPORTS_IN_PROGRESS_LOCK:
        if project_id in _IMPORTS_IN_PROGRESS:
            return HTMLResponse("")
    with _open_project(project_id) as (entry, config, conn):
        if _pipeline_has_pending_work(conn):
            return HTMLResponse("")
        # A project that never ran sees every document as "new": the first
        # "Run everything" reads them all, so offering an update to someone
        # who has just created the project only confuses them.
        if conn.execute("SELECT 1 FROM file LIMIT 1").fetchone() is None:
            return HTMLResponse("")
        try:
            plan = build_update_plan(conn, config, record_warnings=False)
        except SourceFolderUnavailable:
            return HTMLResponse("")
        if plan.is_empty:
            return HTMLResponse("")
        return render(
            request, "_update_banner.html",
            {"project": entry, "plan": plan, "config": config},
        )


def _current_instructions(config: ProjectConfig) -> str:
    """The user's part of `project_instructions.md`, to fill the field of
    the update screen."""
    return user_part(Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME)


def _dedup_report(config):
    """The user's part of the instructions repeating the managed block
, or `None` when it does not."""
    own = user_part(Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME)
    if not own:
        return None
    report = dedup_detect(own, config.subject)
    return report if report.has_findings else None


def _dedup_kept(conn, fingerprint: str) -> bool:
    """The person chose "keep as it is" for this exact text."""
    try:
        row = conn.execute(
            "SELECT 1 FROM event WHERE message_key = 'log.instructions.dedup_kept'"
            " AND message_params LIKE ? LIMIT 1",
            (f"%{fingerprint}%",),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _dedup_notice(conn, config) -> bool:
    """Whether the Execution and Result screens point to the clean-up."""
    try:
        report = _dedup_report(config)
    except Exception:
        return False
    return report is not None and not _dedup_kept(conn, report.fingerprint)


def _dedup_view(report, language: str) -> dict | None:
    if report is None:
        return None
    pointer = block_pointer(language)
    numbers = {section.number for section in report.copies if section.number is not None}
    return {
        "fingerprint": report.fingerprint,
        "copies": [
            {"title": title, "share": round(section.share * 100)}
            for title, section in zip(report.copy_titles(), report.copies)
        ],
        "volatile": [line.strip() for _index, line in report.volatile_lines],
        "references": [
            {"before": text, "after": pointer}
            for _index, text in report.references
        ] if numbers else [],
        "candidates": [
            {"id": c.id, "text": c.text.replace("**", ""), "sentence": c.sentence, "suggested": c.suggested}
            for c in report.candidates
        ],
    }


def _instructions_context(entry, config, language: str, *, message: str = "", saved: bool = False,
                          user_text: str | None = None, conn=None) -> dict:
    path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
    report = _dedup_report(config)
    return {
        "project": entry, "config": config,
        "user_text": user_part(path) if user_text is None else user_text,
        "generated": generated_part(path),
        "exists": path.exists(),
        "message": message, "saved": saved,
        "dedup": _dedup_view(report, language),
        "dedup_kept": report is not None and conn is not None and _dedup_kept(conn, report.fingerprint),
    }


@app.get("/projects/{project_id}/instructions", response_class=HTMLResponse)
def instructions_screen(request: Request, project_id: int):
    """The person's own instructions, editable at any time.

    Until 1.8.1 the only place to give the program the instructions kept in
    the Claude Project was the update screen; an update confirmed without
    them left no other way. Only the person's part is editable here; the
    section the program generates is shown read-only below it."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (entry, config, conn):
        return render(request, "instructions.html", _instructions_context(entry, config, language, conn=conn))


@app.post("/projects/{project_id}/instructions/dedup", response_class=HTMLResponse)
async def instructions_dedup(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_instructions_dedup_body, request, project_id, form)


def _instructions_dedup_body(request: Request, project_id: int, form):
    """The person's answer to "your part repeats the block":
    `remove` takes the copies out of their part, points the references to
    them at the block and moves the rules they ticked into the project's
    extra rules; `keep` only records the choice. Either way it is logged."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    action = str(form.get("action", ""))
    fingerprint = str(form.get("fingerprint", ""))
    move = {int(value) for value in form.getlist("move") if str(value).isdigit()}
    with _generation_slot(project_id, "instructions.dedup.remove") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        with _open_project(project_id) as (entry, config, conn):
            report = _dedup_report(config)
            if report is None or report.fingerprint != fingerprint:
                return render(request, "instructions.html", _instructions_context(
                    entry, config, language, conn=conn,
                    message=translate(language, "instructions.dedup.stale"),
                ))
            titles = "; ".join(report.copy_titles()) or "-"
            if action != "remove":
                record_event(
                    conn, "instructions", "info", "log.instructions.dedup_kept",
                    {"count": len(report.copies), "sections": titles, "fingerprint": report.fingerprint},
                    language=language,
                )
                return render(request, "instructions.html", _instructions_context(
                    entry, config, language, conn=conn,
                    message=translate(language, "instructions.dedup.kept"), saved=True,
                ))

            new_user, rules = dedup_apply(report, language, remove_copies=True, move=move)
            path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            changed_config = False
            if rules:
                added = "\n".join(f"- {rule}" for rule in rules)
                config.extra_rules = (config.extra_rules.rstrip() + "\n" + added) if config.extra_rules.strip() else added
                changed_config = True
            if not new_user and config.existing_instructions.strip():
                # The form's copy of the instructions would come back as the
                # user's part of an empty file on the next generation.
                config.existing_instructions = ""
                changed_config = True
            if changed_config:
                save_project_config(conn, config)
            replace_user_part(path, new_user, stamp=stamp, allow_empty=True)
            generate_project_instructions_md(conn, config, language)
            backup = path.with_name(f"{path.name}.{stamp}{BACKUP_SUFFIX}")
            record_event(
                conn, "instructions", "info", "log.instructions.dedup_removed",
                {"count": len(report.copies), "sections": titles, "refs": len(report.references),
                 "rules": len(rules), "backup": backup.name if backup.exists() else "-"},
                language=language,
            )
            return render(request, "instructions.html", _instructions_context(
                entry, config, language, conn=conn, saved=True,
                message=translate(
                    language, "instructions.dedup.removed", count=len(report.copies), rules=len(rules),
                    backup=backup.name if backup.exists() else "-",
                ),
            ))


@app.post("/projects/{project_id}/instructions", response_class=HTMLResponse)
async def instructions_save(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_instructions_save_body, request, project_id, form)


def _instructions_save_body(request: Request, project_id: int, form):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    pasted = str(form.get("user_instructions", ""))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with _open_project(project_id) as (entry, config, conn):
        path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
        if replace_user_part(path, pasted, stamp=stamp):
            record_event(
                conn, "update", "info", "log.update.instructions_replaced", {}, language=language,
            )
            backup = path.with_name(f"{path.name}.{stamp}{BACKUP_SUFFIX}")
            message = translate(
                language, "instructions.saved",
                backup=backup.name if backup.exists() else "-",
            )
            return render(request, "instructions.html", _instructions_context(
                entry, config, language, message=message, saved=True, conn=conn,
            ))
        return render(request, "instructions.html", _instructions_context(
            entry, config, language, message=translate(language, "instructions.unchanged"),
            user_text=pasted if pasted.strip() else None,
        ))


@app.get("/projects/{project_id}/update", response_class=HTMLResponse)
def update_screen(request: Request, project_id: int):
    """The confirmation. Read-only: it never writes to the project.

    `record_warnings=False` is what makes that categorical rather than
    merely usual — see `build_update_plan`.
    """
    with _open_project(project_id) as (entry, config, conn):
        try:
            plan = build_update_plan(conn, config, record_warnings=False)
        except SourceFolderUnavailable:
            return render(
                request, "update_project.html",
                {"project": entry, "config": config, "plan": None,
                 "error": "update.source_unavailable"},
                status_code=409,
            )
        return render(
            request, "update_project.html",
            {"project": entry, "config": config, "plan": plan, "error": None,
             "current_instructions": _current_instructions(config)},
        )


@app.post("/projects/{project_id}/update", response_class=HTMLResponse)
async def update_apply(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_update_apply_body, request, project_id, form)


def _update_apply_body(request: Request, project_id: int, form):
    """The checks that answer with a screen run here, in the
    request; the walk of the folder and the invalidation run in the
    background, with Stop. The slot is claimed by `_start_operation`
    before anything is opened or written (fase 33, decision 3)."""
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    current_task = task_manager.latest_for_project(project_id)
    if current_task is not None and current_task.running:
        with _open_project(project_id) as (entry, config, _conn):
            return render(
                request, "update_project.html",
                {"project": entry, "config": config, "plan": None,
                 "error": "update.run_in_progress"},
                status_code=409,
            )

    def work(should_stop):
        return _update_apply_unlocked(request, project_id, form, should_stop)

    run_url = f"/projects/{project_id}/run"
    operation = _start_operation(project_id, "update.confirm", work, run_url)
    return _operation_response(request, operation, project_id, run_url)


def _update_apply_unlocked(request: Request, project_id: int, form, should_stop=None):
    """Applies the plan, then sends the user to the Execution screen.

    The stale-plan check lives in `apply_update_plan`, not here: it is the
    invariant of the invalidation itself, and putting it there keeps it
    testable without a web server and keeps this route from walking the
    folder a third time. The route rebuilds the plan the form refers to,
    hands it over, and turns a refusal into a screen.

    `record_warnings=False` here too, and for a different reason than on
    the GET routes: `apply_update_plan` builds its own plan and records
    the layout warning itself, so leaving it on would log the same
    mismatch twice for one action — and once on a refusal that applied
    nothing at all.
    """
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))

    with _open_project(project_id) as (entry, config, conn):
        # `_open_project`'s lock is the cross-machine one and the running
        # step already holds it, so it protects nothing here. SQLite
        # covers most of the database side, but `_prune_raw_items` is
        # outside it: it streams `raw_items.jsonl` to a temporary file
        # and renames it over the original while `classify_pending` may
        # be appending, so classifications written during the copy are
        # lost, or a stale line survives and is imported against pages
        # that have since moved.
        current_task = task_manager.latest_for_project(project_id)
        if current_task is not None and current_task.running:
            raise _OperationMessage("update.run_in_progress")

        # What the user actually saw. `apply_update_plan` walks the folder
        # itself and refuses when it no longer matches; only the
        # fingerprint of the plan is read, so no third walk here (1.9.0:
        # each walk of a large Drive folder can take half a minute).
        seen = str(form.get("fingerprint", ""))
        try:
            apply_update_plan(
                conn, config, UpdatePlan.witness(seen), language, should_stop=should_stop,
            )
        except SourceFolderUnavailable:
            raise _OperationMessage("update.source_unavailable") from None
        except PlanExpired:
            raise _OperationMessage(
                "update.plan_expired", next_url=f"/projects/{project_id}/update",
            ) from None

        # The instructions as the user has them today in the Claude
        # Project. Their text replaces the user's part of the file; the
        # generated section stays and is refreshed by the next generation.
        pasted = str(form.get("current_instructions", ""))
        if replace_user_part(
            Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME, pasted,
            stamp=datetime.now().strftime("%Y%m%d-%H%M%S"),
        ):
            record_event(
                conn, "update", "info", "log.update.instructions_replaced", {}, language=language,
            )

    return f"/projects/{project_id}/run"


@app.get("/projects/{project_id}/run/log", response_class=HTMLResponse)
def log_fragment(request: Request, project_id: int, since: int | None = None):
    """The live log, whole or incremental.

    Without `since`, the full list — the first load, and what every caller
    before this parameter existed gets.

    With `since`, only the lines recorded after event `since`, as bare
    `<li>` elements for the screen to append. That is what stops the log
    being rebuilt from scratch every two seconds, and it is the difference
    between a panel you can read and one you cannot: replacing the content
    wipes out any text the user had selected (so "select and copy a line"
    was impossible while a run was going) and resets the scroll position
    under them mid-read.

    `language`: without it, the log always showed
    events in `DEFAULT_LANGUAGE`, ignoring the interface's actual language.
    """
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    # Capped either way: a screen left open while a very long step ran must
    # not receive thousands of lines in one response.
    with _open_project(project_id, timeout=READER_TIMEOUT_SECONDS) as (_entry, _config, conn):
        events = list_events(conn, language=language, since=since, last=LOG_LINES)

    if since is None:
        log_context = {"eventos": events, "known_steps": LOG_KNOWN_STEPS}
        return render(request, "_log.html", log_context)

    return render(request, "_log_items.html", {"eventos": events, "known_steps": LOG_KNOWN_STEPS})


@app.get("/projects/{project_id}/run/steps", response_class=HTMLResponse)
def steps_fragment(request: Request, project_id: int):
    """User request: the steps table also refreshes itself during the run
    (before it only changed when a button was clicked), so progress can be
    followed without clicking anything."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))

    def build() -> str:
        with _read_project(project_id) as (entry, config, conn):
            context = _steps_context(project_id, entry, config, conn, language)
        return render(request, "_steps.html", context).body.decode("utf-8")

    return HTMLResponse(_idle_fragment(project_id, "steps", language, build))


# The Execution screen asks for the steps table and the progress box
# every two seconds. With nothing running, the answer cannot change except
# through an action of this server (a step, an update, a generation), and
# on a large project on Google Drive each answer cost about a second of
# reads through the drive, competing with every other screen. While idle,
# the same answer is reused for a while; anything that starts or ends
# changes the key and forces a fresh one.
IDLE_FRAGMENT_SECONDS = 30.0
_idle_fragments: dict[tuple[int, str, str], tuple[tuple, float, str]] = {}
_idle_fragments_lock = threading.Lock()


def _activity_key(project_id: int) -> tuple | None:
    """What would change the screen: `None` while something runs."""
    task = task_manager.latest_for_project(project_id)
    if task is not None and task.running:
        return None
    with _IMPORTS_IN_PROGRESS_LOCK:
        if project_id in _IMPORTS_IN_PROGRESS:
            return None
        operation = _OPERATIONS.get(project_id)
    return (
        id(task), getattr(task, "error", None),
        (operation.id, operation.status) if operation is not None else None,
    )


def _idle_fragment(project_id: int, name: str, language: str, build) -> str:
    key = _activity_key(project_id)
    cache_key = (project_id, name, language)
    now = time.monotonic()
    if key is not None:
        with _idle_fragments_lock:
            cached = _idle_fragments.get(cache_key)
        if cached is not None and cached[0] == key and now - cached[1] < IDLE_FRAGMENT_SECONDS:
            return cached[2]
    html = build()
    with _idle_fragments_lock:
        if key is None:
            _idle_fragments.pop(cache_key, None)
        else:
            _idle_fragments[cache_key] = (key, now, html)
    return html


def _steps_context(project_id: int, entry, config: ProjectConfig, conn, language: str) -> dict:
    steps = step_status(conn, lambda key: _step_running(project_id, key))
    quality = _cached_quality_summary(project_id, conn, config)
    # Completion notice: "every step finished" is not
    # enough — `item` is only populated by "Import and generate reports",
    # which runs separately. Without checking `total_items`, the notice
    # would show up with a score of 0 right after classification, before
    # any item exists to measure.
    show_finished_notice = next_pending_step(steps) is None and quality["total_items"] > 0
    return {
        "project": entry,
        "steps": steps,
        "show_claude_code": config.classification_engine == "claude_code",
        "claude_code_command": command_for_language(language),
        "show_done_notice": show_finished_notice,
        "qualidade": quality,
    }


# The steps table refreshes every two seconds and used to recompute
# the whole quality summary each time (every page, every item). Its inputs
# only change when items, windows, pages or failures do, so it is kept per
# project and recomputed when that cheap signature moves.
_quality_cache: dict[tuple[int, str], tuple[tuple, object]] = {}
_quality_cache_lock = threading.Lock()


def _quality_signature(conn, config: ProjectConfig) -> tuple:
    row = conn.execute(
        """
        SELECT (SELECT MAX(id) FROM item), (SELECT COUNT(*) FROM item),
               (SELECT COUNT(*) FROM window WHERE status = 'done'),
               (SELECT COUNT(*) FROM window WHERE status = 'pending'),
               (SELECT MAX(id) FROM page),
               (SELECT COUNT(*) FROM file WHERE status = 'failed')
        """
    ).fetchone()
    return (tuple(row), config.classification_engine, config.local_model)


def _cached_quality_summary(project_id: int, conn, config: ProjectConfig) -> dict:
    return _cached_by_signature(project_id, "quality", conn, config, lambda: quality_summary(conn, config))


def _cached_by_signature(project_id: int, name: str, conn, config: ProjectConfig, compute):
    """A summary of the project, kept until the cheap signature moves
    (1.9.0: the Result screen of a large project on Google Drive
    took tens of seconds to recompute the quality, the pending items and the run
    comparison on every visit; their inputs had not changed)."""
    signature = _quality_signature(conn, config)
    key = (project_id, name)
    with _quality_cache_lock:
        cached = _quality_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    value = compute()
    with _quality_cache_lock:
        _quality_cache[key] = (signature, value)
    return value


def _step_running(project_id: int, key: str) -> bool:
    task = task_manager.get(project_id, key)
    return task is not None and task.running


@app.post("/projects/{project_id}/run-next", response_class=HTMLResponse)
def run_next_step(request: Request, project_id: int):
    """"Run next step" button (section 6): figures out on its own, from the
    database state, which is the next incomplete step, and starts it in the
    background (the response does not wait for it to finish — the progress
    bar follows along via `run/progress`)."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (entry, config, conn):
        next_step = next_pending_step(step_status(conn, lambda key: _step_running(project_id, key)))
        if next_step is not None:
            task_manager.start_step(project_id, entry.output_folder, config, next_step, language=language)
        context = _steps_context(project_id, entry, config, conn, language)

    return render(request, "_steps.html", context)


@app.post("/projects/{project_id}/run-all", response_class=HTMLResponse)
def run_all(request: Request, project_id: int):
    """"Run everything up to classification" button (section 6) — chains
    the steps in the background, one after another."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (entry, config, conn):
        task_manager.start_all(project_id, entry.output_folder, config, language=language)
        context = _steps_context(project_id, entry, config, conn, language)

    return render(request, "_steps.html", context)


@app.post("/projects/{project_id}/resume", response_class=HTMLResponse)
def resume_run(request: Request, project_id: int):
    """"Continue" in the progress box (fase 34): the same chain as "run
    everything", started at the first pending step — the paused one, which
    is resumable — instead of at the scan."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (entry, config, conn):
        next_step = next_pending_step(step_status(conn, lambda key: _step_running(project_id, key)))
        if next_step is not None:
            task_manager.start_all(
                project_id, entry.output_folder, config, language=language, first_step=next_step
            )
        context = _steps_context(project_id, entry, config, conn, language)

    return render(request, "_steps.html", context)


@app.post("/projects/{project_id}/pause", response_class=HTMLResponse)
def pause_run(request: Request, project_id: int):
    """Single pause/interrupt button (user request): stops whatever is
    currently running for this project. Since every step is resumable,
    "pause" and "continue later" are the same as running it again."""
    task_manager.pause(project_id)
    # Fase 34: the answer is the progress box itself, already saying
    # "stopping" — the button lives there, and the step table it used to
    # redraw looks the same before and after the click (over a minute with
    # no visible change while the model loaded). The box keeps polling every 2 s and
    # turns into "paused — Continue" when the step really stops.
    return render(request, "_progress.html", _progress_context(project_id))


def _progress_context(project_id: int) -> dict:
    """What `_progress.html` needs: shared by the 2 s poll and the pause
    button, so both draw exactly the same box."""
    with _read_project(project_id) as (entry, _config, conn):
        task = task_manager.latest_for_project(project_id)
        progress = compute_progress(entry.output_folder, task)
        if task is None:
            elapsed = None
        elif task.finished_at is not None:
            elapsed = task.finished_at - task.started_at
        else:
            elapsed = time.monotonic() - task.started_at
        progress["tempo_decorrido"] = _format_time(elapsed)
        progress["eta_formatado"] = _format_time(progress.get("eta_segundos"))
        # "Continue" is offered while a step is still pending — also after a
        # pause that landed between two steps, which leaves the last task
        # *finished*, not stopped (final review of fase 34).
        progress["has_pending"] = (
            next_pending_step(step_status(conn, lambda key: _step_running(project_id, key))) is not None
        )
    return {"project": entry, "progresso": progress}


@app.get("/projects/{project_id}/run/progress", response_class=HTMLResponse)
def progress_fragment(request: Request, project_id: int):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    return HTMLResponse(_idle_fragment(
        project_id, "progress", language,
        lambda: render(request, "_progress.html", _progress_context(project_id)).body.decode("utf-8"),
    ))


@app.get("/projects/{project_id}/run/resources")
def resources_json(project_id: int):
    """Plain JSON (not HTML) for the CPU/RAM/GPU chart — read by a small
    browser script (no framework, no build) that draws a canvas with the
    recent history.

    Reads `latest_sample()` (background sampler), not `sample_resources()`
    directly: collecting GPU/clock costs ~6s (`Get-Counter` takes two
    samples per metric to compute a rate), and this screen polls every
    500ms — collecting on the request path would tie up one of the
    browser's 6 same-origin connections for 6s and stall the other polls
    (progress, log, steps)."""
    sample = latest_sample()
    return {
        "cpu_percent": sample.cpu_percent,
        "cpu_name": sample.cpu_name,
        "ram_percent": sample.ram_percent,
        "ram_used_mb": sample.ram_used_mb,
        "ram_total_mb": sample.ram_total_mb,
        "gpu_percent": sample.gpu_percent,
        "gpu_vram_used_mb": sample.gpu_vram_used_mb,
        "gpu_vram_total_mb": sample.gpu_vram_total_mb,
        "gpu_name": sample.gpu_name,
        "clock_cpu_mhz": sample.clock_cpu_mhz,
        "clock_memory_mhz": sample.clock_memory_mhz,
        "clock_gpu_mhz": sample.clock_gpu_mhz,
        "cpu_temp_c": sample.cpu_temp_c,
        "gpu_temp_c": sample.gpu_temp_c,
        "gpu_hotspot_c": sample.gpu_hotspot_c,
        "gpu_fan_rpm": sample.gpu_fan_rpm,
        "cpu_fan_rpm": sample.cpu_fan_rpm,
        "cpu_power_w": sample.cpu_power_w,
        "gpu_power_w": sample.gpu_power_w,
        # Fase 35: the resident model and its share on the card.
        "model_name": sample.model_name,
        "model_size_mb": sample.model_size_mb,
        "model_vram_mb": sample.model_vram_mb,
        "sensors_unavailable_reason": unavailable_reason(),
        # Fase 32: what the last request for the helper came to (`started`,
        # `refused`, `unavailable`, `already_elevated` or nothing), so the
        # screen can say "waiting for Windows" or "refused — click again"
        # instead of a dash while the snapshot has not arrived yet.
        "helper_status": read_launch_status(),
    }


def _sensor_request_allowed(request: Request) -> bool:
    """The four guards of `request_sensor_elevation`. All of them, or 403.

    1. `X-GClaude-Sensor-Token` equals this server run's `SENSOR_REQUEST_TOKEN`
       (constant-time compare). The token is only in the Run screen's HTML;
       the same-origin policy keeps every other origin from reading it.
    2. `Sec-Fetch-Site: same-origin` — set by the browser itself, not by
       the page; a request from another site carries `cross-site`, and an
       old browser that sends nothing is refused rather than trusted.
    3. The token travels in a *custom header*: a cross-origin request with
       one triggers a CORS preflight, and this server answers no preflight.
    4. `Host` is exactly this server's own `127.0.0.1:<port>` or
       `localhost:<port>` — against DNS rebinding, where a name the
       attacker controls is made to resolve to 127.0.0.1 so that the
       browser treats the request as same-origin *with the attacker's site*
       (added at the user's request).
    """
    token = request.headers.get("x-gclaude-sensor-token", "")
    # `isascii()` first (fase 33): Starlette decodes headers as latin-1 and
    # `compare_digest` raises TypeError on non-ASCII str — a malformed
    # request from a raw socket would answer 500 with a traceback in the
    # log instead of the 403 it deserves. The real token is URL-safe ASCII.
    if not token or not token.isascii() or not hmac.compare_digest(token, SENSOR_REQUEST_TOKEN):
        return False
    if request.headers.get("sec-fetch-site") != "same-origin":
        return False
    host = (request.headers.get("host") or "").strip().lower()
    return host in {f"127.0.0.1:{SERVER_PORT}", f"localhost:{SERVER_PORT}"}


@app.post("/sensors/request-elevation")
def request_sensor_elevation(request: Request):
    """Fase 32, option B: the "Read CPU sensors and fans" button.

    This is the one route that may lead to a UAC prompt, and it exists
    against a rule this file has kept since phase 15 (see
    `_request_cpu_sensor_helper`): the server listens on 127.0.0.1 and any
    page open in the user's browser can POST to it, so an unguarded route
    would let any website make the prompt appear — or, on a machine with
    `ConsentPromptBehaviorAdmin = 0`, start the elevated helper outright.
    The user chose a button over the startup-only shortcut knowing this; the price is `_sensor_request_allowed`, four independent
    checks that each alone would already stop the plain CSRF case. The
    command is fixed (the helper, from a folder this server stages), so
    even a bypass could not run anything else elevated.

    Never waits on the prompt: `ShellExecuteW("runas")` blocks until the
    user answers, so the launch runs in a daemon thread and this answers
    202 at once. The screen follows `helper_status` in `/run/resources`.
    """
    if not _sensor_request_allowed(request):
        raise HTTPException(status_code=403)
    if sensors._is_admin() or sensors.read_snapshot() is not None:
        # Already reading the CPU — in-process or through a live helper.
        # A second helper would be a second reader of the same driver.
        return {"outcome": "already"}
    if sys.platform != "win32":
        return {"outcome": "unavailable"}
    if not _SENSOR_REQUEST_IN_FLIGHT.acquire(blocking=False):
        # Windows is still asking about the previous click.
        return Response(content='{"outcome": "pending"}', media_type="application/json", status_code=202)
    # The screen reads the status file every 2 s and takes `refused` as the
    # answer to *this* click — so the previous answer must be gone before
    # the prompt opens, or a "no" from a minute ago re-enables the button
    # while consent.exe is still on screen.
    sensor_service.clear_launch_status()
    pid = os.getpid()

    def ask():
        try:
            sensor_service.request_helper_now(pid)
        except Exception:
            # A thread that dies without writing a status leaves the button
            # on "request sent" forever; `unavailable` lets it recover.
            sensor_service.write_launch_status("unavailable")
        finally:
            _SENSOR_REQUEST_IN_FLIGHT.release()

    try:
        threading.Thread(target=ask, daemon=True).start()
    except Exception:
        _SENSOR_REQUEST_IN_FLIGHT.release()
        raise
    return Response(content='{"outcome": "requested"}', media_type="application/json", status_code=202)


@app.post("/projects/{project_id}/claude-code/recheck", response_class=HTMLResponse)
def recheck_claude_code(request: Request, project_id: int):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (entry, config, conn):
        claude_code_status = sync_progress(conn, config, language)
        steps = step_status(conn, lambda key: _step_running(project_id, key))

    return render(
        request, "_steps.html",
        {"project": entry, "steps": steps, "show_claude_code": True,
         "claude_code_command": command_for_language(language), "claude_code_status": claude_code_status},
    )


# Guards "import and generate" against a second click while the first one is
# still running. Unlike the pipeline steps, this route does its work inside
# the HTTP handler, so it has no `task_manager` entry to check — and each
# extra run would repeat `DELETE FROM item` plus thousands of inserts on the
# same database. Seen live: 4 concurrent runs on a 5230-item project.
_IMPORTS_IN_PROGRESS: set[int] = set()
_IMPORTS_IN_PROGRESS_LOCK = threading.Lock()

# Fase 32: *which* operation holds the slot and since when, so a page loaded
# in the middle of it — an F5, another tab — can show the activity bar with
# the real name and the real elapsed time instead of looking frozen. Guarded
# by the same lock as the set above. The instant is `time.monotonic()`
# (fase 33): wall-clock time can be set back by Windows or by NTP in the
# middle of a generation, and the elapsed time would then go negative or
# jump — nothing reads this value across processes, so the monotonic clock
# is the right one.
_OPERATIONS_IN_PROGRESS: dict[int, tuple[str, float]] = {}


@contextmanager
def _generation_slot(project_id: int, operation_key: str = "run.import_and_generate"):
    """One report generation per project at a time. Yields `False` when
    another one is under way — the caller sends the user to the result
    instead of starting a duplicate: two generations writing and deleting
    the same files at once end in `PermissionError` on Windows, and a
    regeneration during an import would read a half-imported `item` table.
    Shared by "Import and generate reports" and the package option (phase
    31); `_project_busy` reads the same set for the lock keep-alive.

    `operation_key` is the i18n key of the button that started it — what
    `project_activity` reports back to the screen (fase 32)."""
    with _IMPORTS_IN_PROGRESS_LOCK:
        claimed = project_id not in _IMPORTS_IN_PROGRESS
        if claimed:
            _IMPORTS_IN_PROGRESS.add(project_id)
            _OPERATIONS_IN_PROGRESS[project_id] = (operation_key, time.monotonic())
    try:
        yield claimed
    finally:
        if claimed:
            with _IMPORTS_IN_PROGRESS_LOCK:
                _IMPORTS_IN_PROGRESS.discard(project_id)
                _OPERATIONS_IN_PROGRESS.pop(project_id, None)


# --- 1.9.0: long operations in the background, with Stop ---------------------
#
# "Update the collection" and "Import and generate reports" used to run
# inside the HTTP request. Closing the tab, pressing the browser's Stop or
# switching the theme cancelled nothing on the server: the work went on,
# the slot stayed taken ("this project is busy with: Update") and the
# redirect at the end reached nobody. Now the request only starts the work
# in a thread and answers at once; every screen asks `/activity` what is
# running, shows a waiting panel with a Stop button, and goes to the next
# screen when the server says the operation ended.

# How long the starting request waits for the operation before answering.
# A small project finishes inside it and the person goes straight to the
# next screen, without the waiting panel flashing by.
OPERATION_INLINE_WAIT_SECONDS = 2.0
# How long a finished operation stays visible to `/activity`: long enough
# for the screen that started it, polling every couple of seconds, to see
# the end and move on, even after a reload.
OPERATION_FINISHED_TTL_SECONDS = 300.0


@dataclass
class _Operation:
    id: int
    project_id: int
    key: str
    started_at: float
    next_url: str
    stop: StopSignal = field(default_factory=StopSignal)
    status: str = "running"  # running | done | stopped | error
    message_key: str | None = None
    message_params: dict = field(default_factory=dict)
    finished_at: float | None = None


_OPERATIONS: dict[int, _Operation] = {}
_OPERATION_IDS = itertools.count(1)


class _OperationMessage(Exception):
    """An operation that ended without doing its work, for a reason the
    person must read (the folder changed, the source is offline). Carries
    an i18n key and where to send the person afterwards."""

    def __init__(self, key: str, next_url: str | None = None, **params):
        super().__init__(key)
        self.key = key
        self.next_url = next_url
        self.params = params


def _start_operation(project_id: int, key: str, work, next_url: str) -> _Operation | None:
    """Claims the project's slot and runs `work(should_stop)` in a thread.

    `None` when the slot is taken: the caller answers with the busy page.
    `work` may return a URL, which replaces `next_url` (where the screen
    goes when the operation ends well).
    """
    with _IMPORTS_IN_PROGRESS_LOCK:
        if project_id in _IMPORTS_IN_PROGRESS:
            return None
        _IMPORTS_IN_PROGRESS.add(project_id)
        operation = _Operation(
            id=next(_OPERATION_IDS), project_id=project_id, key=key,
            started_at=time.monotonic(), next_url=next_url,
        )
        _OPERATIONS_IN_PROGRESS[project_id] = (key, operation.started_at)
        _OPERATIONS[project_id] = operation

    def run() -> None:
        try:
            target = work(operation.stop.should_stop)
            if target:
                operation.next_url = target
            operation.status = "done"
        except OperationCancelled:
            operation.status = "stopped"
            operation.message_key = "activity.stopped"
        except _OperationMessage as exc:
            operation.status = "error"
            operation.message_key = exc.key
            operation.message_params = exc.params
            if exc.next_url:
                operation.next_url = exc.next_url
        except Exception as exc:  # noqa: BLE001 - shown to the person, not swallowed
            operation.status = "error"
            operation.message_key = "activity.failed"
            operation.message_params = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[operation {key}] {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            operation.finished_at = time.monotonic()
            with _IMPORTS_IN_PROGRESS_LOCK:
                _IMPORTS_IN_PROGRESS.discard(project_id)
                _OPERATIONS_IN_PROGRESS.pop(project_id, None)

    thread = threading.Thread(target=run, name=f"operation-{key}-{project_id}", daemon=True)
    thread.start()
    thread.join(OPERATION_INLINE_WAIT_SECONDS)
    return operation


def _operation_response(request: Request, operation: "_Operation | None", project_id: int, waiting_url: str):
    """Where the starting request sends the person: straight to the next
    screen when the operation already ended well, otherwise to a screen of
    the project, where the waiting panel takes over."""
    if operation is None:
        return _operation_busy_response(request, project_id)
    if operation.status == "done":
        return RedirectResponse(url=operation.next_url, status_code=303)
    separator = "&" if "?" in waiting_url else "?"
    return RedirectResponse(url=f"{waiting_url}{separator}op={operation.id}", status_code=303)


def _operation_view(operation: _Operation, language: str) -> dict:
    now = time.monotonic()
    entry = find_project(operation.project_id)
    message = (
        translate(language, operation.message_key, **operation.message_params)
        if operation.message_key else ""
    )
    end = operation.finished_at if operation.finished_at is not None else now
    return {
        "id": operation.id,
        "project_id": operation.project_id,
        "project_name": entry.name if entry is not None else "",
        "operation": translate(language, operation.key),
        "operation_key": operation.key,
        "status": operation.status,
        "stopping": operation.status == "running" and operation.stop.should_stop(),
        "elapsed_s": max(0, int(end - operation.started_at)),
        "next_url": operation.next_url,
        "message": message,
    }


@app.get("/activity")
def global_activity(request: Request) -> dict:
    """Every operation running now, and the ones that ended in the last
    few minutes, for the waiting panel of any screen. Reads memory
    only: it is asked every couple of seconds while the operation it
    describes holds the database."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    now = time.monotonic()
    with _IMPORTS_IN_PROGRESS_LOCK:
        for project_id, operation in list(_OPERATIONS.items()):
            if (operation.finished_at is not None
                    and now - operation.finished_at > OPERATION_FINISHED_TTL_SECONDS):
                del _OPERATIONS[project_id]
        operations = list(_OPERATIONS.values())
    return {"operations": [_operation_view(op, language) for op in operations]}


@app.post("/projects/{project_id}/operation/stop")
def stop_operation(request: Request, project_id: int) -> dict:
    """The Stop button of the waiting panel and of the busy page. Asks the
    running operation to stop at its next checkpoint; nothing is committed
    after that, so the project stays as it was before the click (or, in a
    report generation, with each file either old or new)."""
    with _IMPORTS_IN_PROGRESS_LOCK:
        operation = _OPERATIONS.get(project_id)
    if operation is None or operation.status != "running":
        return {"stopping": False}
    operation.stop.request_stop()
    return {"stopping": True}


@app.get("/projects/{project_id}/activity")
def project_activity(request: Request, project_id: int) -> dict:
    """What is running for this project right now, for the activity bar
    (fase 32). Reads a dictionary and nothing else — no project open, no
    database — because it is asked *during* the generation it describes
    and must answer in microseconds while that generation holds the
    database.

    `elapsed_s` is measured from the server's own start time: the page
    that asks may have been opened long after the click."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _IMPORTS_IN_PROGRESS_LOCK:
        running = _OPERATIONS_IN_PROGRESS.get(project_id)
    if running is None:
        return {"operation": None, "operation_key": None, "elapsed_s": 0}
    key, started_at = running
    return {
        "operation": translate(language, key),
        "operation_key": key,
        "elapsed_s": max(0, int(time.monotonic() - started_at)),
    }


def _operation_busy_response(request: Request, project_id: int) -> HTMLResponse:
    """409 for a long operation that found the project's slot taken (fase 33).

    Names the operation that holds it, translated — the same text the
    activity bar shows — so the person knows what to wait for. The user
    never starts one of these while a generation runs; this
    page is the safety net for the day someone does, because "delete
    project" during a generation would remove files being written.
    """
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _IMPORTS_IN_PROGRESS_LOCK:
        running = _OPERATIONS_IN_PROGRESS.get(project_id)
    if running is None:
        # The holder let go between our refusal and this read (a window of
        # microseconds): nothing to name, so the normal path — the result
        # screen — instead of a page that says "busy with: ".
        return RedirectResponse(url=f"/projects/{project_id}/result", status_code=303)
    # `project` in the context is what makes `base.html` emit the activity
    # URL — and so the bar this page tells the user to look at.
    return render(
        request, "operation_busy.html",
        {"project": find_project(project_id), "project_id": project_id,
         "operation": translate(language, running[0])},
        status_code=409,
    )


@app.post("/projects/{project_id}/import-and-generate", response_class=HTMLResponse)
def import_and_generate(request: Request, project_id: int):
    """Starts the import and the generation in the background and
    answers at once; the waiting panel follows it and has the Stop button.
    A second click while one is running gets the busy page, as before."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    if find_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")

    def work(should_stop):
        with _open_project(project_id) as (_entry, config, conn):
            import_and_consolidate(conn, config, language=language, should_stop=should_stop)
            generate_all_artifacts(conn, config, language, should_stop=should_stop)

    result_url = f"/projects/{project_id}/result"
    operation = _start_operation(project_id, "run.import_and_generate", work, result_url)
    return _operation_response(request, operation, project_id, _back_to_project(request, project_id))


def _back_to_project(request: Request, project_id: int) -> str:
    """The screen of the project the click came from, to show the waiting
    panel on; the Execution screen when the referrer is not one of them."""
    referer = request.headers.get("referer", "")
    prefix = f"/projects/{project_id}/"
    position = referer.find(prefix)
    if position >= 0:
        path = referer[position:].split("#", 1)[0]
        if path.split("?", 1)[0].rstrip("/").endswith(("/run", "/result")):
            return path
    return f"/projects/{project_id}/run"


# --- screen: Result ---------------------------------------------------------


# File names are fixed in English (Task 11, Phase 14 — see `artifacts.py`
# module docstring); only the title shown on screen follows the interface
# language, via the matching `artifact.*.title` i18n key.
ARTIFACT_TITLE_KEYS = {
    INDEX_FILENAME: "artifact.index.title",
    TIMELINE_FILENAME: "artifact.timeline.title",
    REVIEW_FILENAME: "artifact.review.title",
    PROJECT_INSTRUCTIONS_FILENAME: "artifact.project_instructions.title",
}


# A preview, not the file: a large collection's timeline runs to megabytes,
# and the Result screen used to embed every byte of every report in the page.
PREVIEW_CHARS = 60_000


def _preview(path: Path) -> tuple[str | None, bool]:
    if not path.exists():
        return None, False
    with path.open(encoding="utf-8", errors="replace") as handle:
        content = handle.read(PREVIEW_CHARS + 1)
    if len(content) > PREVIEW_CHARS:
        return content[:PREVIEW_CHARS], True
    return content, False


@app.get("/projects/{project_id}/result", response_class=HTMLResponse)
def result_screen(request: Request, project_id: int):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _read_project(project_id) as (entry, config, conn):
        output_folder = Path(config.output_folder)
        artifacts = []
        for file_name, title_key in ARTIFACT_TITLE_KEYS.items():
            path = resolve_within(output_folder, file_name)
            content, truncated = _preview(path)
            artifacts.append({
                "title": translate(language, title_key), "file_name": file_name,
                "content": content, "truncated": truncated,
            })
        pending = _cached_by_signature(project_id, "pending", conn, config, lambda: pending_items(conn))
        # Read inside the block: `conn` is closed when it exits. On the
        # Result screen the notice shows whenever the numbers differ, with
        # no pending-work condition — whatever is still running, the files
        # on display really do predate the project.
        stale = _stale_context(stale_artifacts(conn))
        quality = _cached_by_signature(
            project_id, "quality", conn, config, lambda: quality_summary(conn, config, pending),
        )
        comparison = [
            dict(row) for row in _cached_by_signature(project_id, "comparison", conn, config, lambda: compare_runs(conn))
        ]
        for row in comparison:
            row["formatted_time"] = _format_time(row["total_seconds"])
        # Fase 31: o que o ZIP leva contra a capacidade do Projeto do
        # Claude, antes do botão de download. Via módulo, não por nome
        # importado: os testes trocam os limites por monkeypatch.
        budget = claude_package.budget(config)
        instructions_dedup = _dedup_notice(conn, config)

    current_task = task_manager.latest_for_project(project_id)
    step_in_progress = current_task is not None and current_task.running

    return render(
        request, "result.html",
        {
            "project": entry, "config": config, "artifacts": artifacts, "pending": pending,
            "budget": budget,
            "rag_threshold": claude_package.RAG_THRESHOLD_TOKENS,
            "tamanho_intermediarios": intermediates_size(entry.output_folder),
            "step_in_progress": step_in_progress,
            "qualidade": quality,
            "comparison": comparison,
            "instructions_dedup": instructions_dedup,
            **stale,
        },
    )


@app.post("/projects/{project_id}/clear-intermediates")
def clear_intermediates_route(request: Request, project_id: int):
    with _generation_slot(project_id, "result.cleanup_button") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        return _clear_intermediates_unlocked(project_id)


def _clear_intermediates_unlocked(project_id: int):
    """Frees the space used by `converted/` and `blocks/` without deleting
    the result. The removal is permanent for this project: `convert()` only
    processes files with status `'discovered'`, and nothing here returns
    already-converted files to that status — running conversion again does
    not regenerate them.

    Pauses steps in progress and releases the lock before deleting: the
    Result screen is reachable while conversion is running, and Windows
    will not delete a file in use — without this, `rmtree` would fail
    silently (`ignore_errors=True`) and the reported freed bytes would lie.
    """
    with _open_project(project_id) as (entry, _config, _conn):
        output_folder = entry.output_folder

    task_manager.pause(project_id)
    reader_pool.close(output_folder)
    lock_manager.close(output_folder)
    clear_intermediates(output_folder)

    return RedirectResponse(f"/projects/{project_id}/result", status_code=303)


# --- screen: Search ------------------------------------------------------------

SEARCH_PAGE_SIZE = 50
# Per click of "Add the missing files": long enough to make real progress,
# short enough that the request never looks frozen.
SEARCH_INDEX_SECONDS = 45


def _snippet_html(snippet: str) -> Markup:
    """Escaped snippet with the matches as `<mark>` and struck text as
    `<del>` — the `~~` marks are what the HTML/DOCX readers left there."""
    text = str(escape(snippet))
    text = text.replace(FULLTEXT_MATCH_START, "<mark>").replace(FULLTEXT_MATCH_END, "</mark>")
    lines = [re.sub(r"~~(.+?)~~", r"<del>\1</del>", line) for line in text.split("\n")]
    return Markup("<br>".join(line for line in lines if line.strip()))


@app.get("/projects/{project_id}/search", response_class=HTMLResponse)
def search_screen(request: Request, project_id: int, q: str = "", p: int = 1, lexml: int = 0):
    page = max(1, p)
    with _open_project(project_id) as (entry, config, conn):
        indexed, extracted = fulltext_coverage(conn)
        hits, total = fulltext_search(conn, q, SEARCH_PAGE_SIZE, (page - 1) * SEARCH_PAGE_SIZE) if q.strip() else ([], 0)
    results = [{"hit": hit, "snippet": _snippet_html(hit.snippet)} for hit in hits]
    # Fase 38: o LexML só com a caixa marcada, e depois de fechar o banco:
    # a consulta à rede pode levar os 10 s do timeout e não precisa segurar
    # o projeto aberto.
    lexml_result = lexml_module.search(q, limit=10) if (lexml and q.strip()) else None
    return render(
        request, "search.html",
        {
            "project": entry, "config": config, "query": q, "results": results, "total": total,
            "page": page, "pages": max(1, -(-total // SEARCH_PAGE_SIZE)),
            "indexed": indexed, "extracted": extracted,
            "lexml": bool(lexml), "lexml_result": lexml_result,
        },
    )


@app.post("/projects/{project_id}/search/index")
async def search_index(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_search_index_body, request, project_id, form)


def _search_index_body(request: Request, project_id: int, form):
    with _generation_slot(project_id, "search.index_missing") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        return _search_index_unlocked(request, project_id, form)


def _search_index_unlocked(request: Request, project_id: int, form):
    """Adds files extracted before the search existed (or left out by an
    interrupted run), a time-boxed batch per click."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (_entry, config, conn):
        index_fulltext(conn, config, language=language, time_budget=SEARCH_INDEX_SECONDS)
    query = str(form.get("q", ""))
    return RedirectResponse(f"/projects/{project_id}/search?q={quote(query)}", status_code=303)


@app.post("/projects/{project_id}/open-file")
async def open_source_file(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_open_source_file_body, project_id, form)


def _open_source_file_body(project_id: int, form):
    """Opens a search result's original file with its usual program. The
    path comes from the project database, never from the request, and must
    resolve inside the source folder."""
    try:
        file_id = int(str(form.get("file_id", "")))
    except ValueError:
        raise HTTPException(status_code=400)
    with _open_project(project_id) as (_entry, config, conn):
        row = conn.execute("SELECT relative_path FROM file WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    try:
        path = resolve_within(Path(config.source_folder), row["relative_path"])
    except ValueError:
        raise HTTPException(status_code=400)
    if not path.is_file():
        raise HTTPException(status_code=404)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 — a document from the project's own source folder
    back = str(form.get("back", ""))
    if not back.startswith(f"/projects/{project_id}/search"):
        back = f"/projects/{project_id}/search"
    return RedirectResponse(back, status_code=303)


@app.post("/projects/{project_id}/open-folder")
def open_folder_in_explorer(project_id: int):
    with _open_project(project_id) as (_entry, config, _conn):
        path = Path(config.output_folder).resolve()
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", str(path)], shell=False)
    return RedirectResponse(url=f"/projects/{project_id}/result", status_code=303)


@app.get("/projects/{project_id}/result/claude-package")
def download_claude_package(request: Request, project_id: int):
    """Zip with the four artifacts + an installation guide for a new Claude
    Project (explicit user request) — in the interface's language at the
    moment of the download."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    with _open_project(project_id) as (_entry, config, _conn):
        content = generate_claude_project_package(config, language)
    return _zip_response(content, f"claude_project_{config.name}.zip")


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


# --- delete project (explicit user request) ----------------------------------


@app.get("/projects/{project_id}/delete", response_class=HTMLResponse)
def confirm_deletion(request: Request, project_id: int):
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")
    return render(request, "delete_project.html", {"project": entry})


@app.post("/projects/{project_id}/delete")
async def delete_project_route(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_delete_project_route_body, request, project_id, form)


def _delete_project_route_body(request: Request, project_id: int, form):
    with _generation_slot(project_id, "delete.confirm") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        return _delete_project_unlocked(request, project_id, form)


def _delete_project_unlocked(request: Request, project_id: int, form):
    entry = find_project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado no catálogo local.")

    delete_files = str(form.get("delete_files", "")) == "all"

    # Releases the lock and closes this session's connection before touching
    # the folder — Windows won't let you delete a file that's open.
    reader_pool.close(entry.output_folder)
    lock_manager.close(entry.output_folder)
    task_manager.pause(project_id)
    delete_project(entry, delete_files)
    _side_bar_cache.clear()  # The side bar shows it at once

    return RedirectResponse(url="/projects", status_code=303)


# --- sets: several collections in one Claude Project (fase 38) ---------------


def _set_or_404(set_id: int) -> SetEntry:
    entry = find_set(set_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Conjunto não encontrado nesta máquina.")
    return entry


def _project_join_reason(e, language: str) -> str:
    """Por que um projeto não pode entrar num conjunto agora: pasta fora do
    ar ou relatórios nunca gerados. Vazio quando pode."""
    from ..catalog import catalog_folder

    folder = catalog_folder()
    resolved = e.resolved_output_folder(folder)
    if not e.is_available(folder):
        return translate(language, "combined.reason_unavailable", folder=resolved)
    if not (Path(resolved) / INDEX_FILENAME).exists():
        return translate(language, "combined.reason_no_artifacts")
    return ""


def _project_choices(language: str, entry: SetEntry) -> list[dict]:
    """Every catalog project, with whether it can join a set and why not.
    Shown disabled rather than hidden: the person sees the project is
    known and learns what to do (generate its reports, or open it on the
    computer that has it)."""
    aliases = {m.project_id: m.alias for m in entry.members}
    choices = []
    for e in list_projects():
        reason = _project_join_reason(e, language)
        choices.append({
            "id": e.id, "name": e.name, "reason": reason, "selected": e.id in aliases,
            "alias": aliases.get(e.id, ""), "proposed": propose_alias(e.name, set()),
        })
    return choices


def _render_set(request: Request, entry: SetEntry, errors: list[str] | None = None,
                status_code: int = 200, notice: str = "", target_folder: str = "") -> HTMLResponse:
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    context = {
        "entry": entry, "choices": _project_choices(language, entry), "errors": errors or [],
        "notice": notice, "target_folder": target_folder, "rag_threshold": claude_package.RAG_THRESHOLD_TOKENS,
    }
    if entry.id:
        context["plan"] = combined_package.plan(entry, language)
    return render(request, "set_edit.html", context, status_code=status_code)


def _set_from_form(form, entry: SetEntry, language: str) -> list[str]:
    """Fills `entry` from the form; returns the problems found. Aliases are
    normalized and made unique by `save_set`; an empty one falls back to
    the project's name, which `propose_alias` turns into a safe prefix."""
    entry.name = str(form.get("name", "")).strip()
    entry.personal_instructions = str(form.get("personal_instructions", ""))
    members = []
    selectable = set()
    for e in list_projects():
        if _project_join_reason(e, language):
            continue
        selectable.add(e.id)
        if str(form.get(f"project_{e.id}", "")) == "1":
            alias = str(form.get(f"alias_{e.id}", "")).strip() or e.name
            members.append(SetMember(project_id=e.id, alias=alias))
    # Um membro fora do ar (Drive de outro computador, pasta renomeada) vem
    # desabilitado na tela e o navegador não o envia. Ele continua no
    # conjunto: a revisão da fase 38 viu o conjunto perder o
    # membro só porque a pessoa corrigiu o texto pessoal. Para tirá-lo, a
    # pasta precisa estar acessível (ou apaga-se o conjunto).
    members += [m for m in entry.members if m.project_id not in selectable]
    entry.members = members
    errors = []
    if not entry.name:
        errors.append(translate(language, "sets.error_name"))
    if len(members) < 2:
        errors.append(translate(language, "sets.error_two_projects"))
    return errors


def _save_set_body(request: Request, form, entry: SetEntry):
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    errors = _set_from_form(form, entry, language)
    if errors:
        return _render_set(request, entry, errors, status_code=400)
    saved = save_set(entry)
    return RedirectResponse(url=f"/sets/{saved.id}", status_code=303)


@app.get("/sets", response_class=HTMLResponse)
def sets_screen(request: Request):
    names = {e.id: e.name for e in list_projects()}
    rows = [
        {
            "entry": entry,
            "members": ", ".join(f"{m.alias} ({names.get(m.project_id, '#' + str(m.project_id))})" for m in entry.members),
        }
        for entry in list_sets()
    ]
    return render(request, "sets.html", {"sets": rows})


@app.get("/sets/new", response_class=HTMLResponse)
def new_set_form(request: Request):
    return _render_set(request, SetEntry(id=0, name=""))


@app.post("/sets/new", response_class=HTMLResponse)
async def create_set(request: Request):
    form = await request.form()
    return await run_in_threadpool(_save_set_body, request, form, SetEntry(id=0, name=""))


@app.get("/sets/{set_id}", response_class=HTMLResponse)
def set_screen(request: Request, set_id: int, written: int = 0, folder: str = ""):
    entry = _set_or_404(set_id)
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    notice = translate(language, "sets.written", count=written, folder=folder) if written and folder else ""
    return _render_set(request, entry, notice=notice, target_folder=folder)


@app.post("/sets/{set_id}", response_class=HTMLResponse)
async def update_set(request: Request, set_id: int):
    form = await request.form()
    return await run_in_threadpool(_save_set_body, request, form, _set_or_404(set_id))


@app.post("/sets/{set_id}/delete")
def delete_set(set_id: int):
    """Only the set is removed. The projects, their folders and any
    combined folder already written stay as they are."""
    _set_or_404(set_id)
    remove_set(set_id)
    return RedirectResponse(url="/sets", status_code=303)


@app.get("/sets/{set_id}/package")
def download_set_package(request: Request, set_id: int):
    entry = _set_or_404(set_id)
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    return _zip_response(combined_package.generate_zip(entry, language), f"claude_project_{entry.name}.zip")


@app.post("/sets/{set_id}/write-folder", response_class=HTMLResponse)
async def write_set_folder(request: Request, set_id: int):
    form = await request.form()
    return await run_in_threadpool(_write_set_folder_body, request, set_id, form)


def _write_set_folder_body(request: Request, set_id: int, form):
    entry = _set_or_404(set_id)
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    folder = str(form.get("target_folder", "")).strip()
    if not folder:
        return _render_set(request, entry, [translate(language, "sets.write_folder_missing")], status_code=400)
    try:
        written = combined_package.write_folder(entry, Path(folder), language)
    except combined_package.ProtectedFolderError:
        error = translate(language, "sets.write_protected", folder=folder)
        return _render_set(request, entry, [error], status_code=400, target_folder=folder)
    except OSError as exc:
        error = translate(language, "sets.write_error", folder=folder, detail=str(exc))
        return _render_set(request, entry, [error], status_code=400, target_folder=folder)
    return RedirectResponse(url=f"/sets/{entry.id}?written={len(written)}&folder={quote(folder)}", status_code=303)


# --- About (explicit user request) --------------------------------------------


@app.get("/help", response_class=HTMLResponse)
def manual_screen(request: Request):
    """The full user manual, one document per language (same pattern as
    the Claude package guide): flowing text with tables and examples, which
    itemized i18n keys would chop into fragments. Each screen's help modal
    links to its own section here."""
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    return render(request, "help.html", {"manual_template": f"manual/{language}.html"})


@app.get("/about", response_class=HTMLResponse)
def about_screen(request: Request):
    # `language`: `check_installation()`'s diagnostic
    # text (GPU runtime, hardware-sensor availability) used to be hardcoded
    # Portuguese, shown as-is regardless of the interface's language — see
    # `install_diagnostics.py`'s module docstring.
    language = valid_language(request.cookies.get(LANGUAGE_COOKIE_NAME))
    return render(
        request, "about.html", {"autor": SYSTEM_AUTHOR, "diagnostico": _installation_report(language)}
    )


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


@app.post("/preferences/language")
async def choose_language(request: Request):
    form = await request.form()
    language = valid_language(str(form.get("language", DEFAULT_LANGUAGE)))
    response = RedirectResponse(url=_back_to(request), status_code=303)
    response.set_cookie(LANGUAGE_COOKIE_NAME, language, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.post("/preferences/theme")
async def choose_theme(request: Request):
    form = await request.form()
    theme = valid_theme(str(form.get("theme", DEFAULT_THEME)))
    # The screen changes the theme in place, without a reload, and
    # only needs the cookie back.
    if request.headers.get("x-preference-fetch") == "1":
        response = Response(status_code=204)
    else:
        response = RedirectResponse(url=_back_to(request), status_code=303)
    response.set_cookie(THEME_COOKIE_NAME, theme, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.post("/preferences/layout")
async def choose_layout(request: Request):
    form = await request.form()
    layout = valid_layout(str(form.get("layout", DEFAULT_LAYOUT)))
    # The screen changes the layout in place, without a reload, and
    # only needs the cookie back.
    if request.headers.get("x-preference-fetch") == "1":
        response = Response(status_code=204)
    else:
        response = RedirectResponse(url=_back_to(request), status_code=303)
    response.set_cookie(LAYOUT_COOKIE_NAME, layout, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


def _validate_host(host: str) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(f"o servidor só pode escutar em 127.0.0.1 (seção 7): recusado {host!r}")


def _request_cpu_sensor_helper() -> str:
    """Asks for the elevated CPU-sensor helper when this run opted into it.

    Deliberately here and not behind an HTTP route. The server listens on
    127.0.0.1, and any page in the user's browser can POST to a loopback
    address; an endpoint that raised a UAC prompt would hand every web page
    the ability to make one appear — and on a machine configured to elevate
    administrators without a dialog (`ConsentPromptBehaviorAdmin = 0`) it
    would not even be a prompt, it would just be an elevated process. The
    decision is taken once, at startup, by the shortcut the user chose to
    double-click. The one exception to "never by a request" is
    `request_sensor_elevation` (fase 32), which exists only behind the
    four guards of `_sensor_request_allowed` plus the frame-denying
    headers of `_only_own_pages`; nothing else may call the helper.

    Returns the outcome code and never raises: whatever happens, the server
    starts.
    """
    from ..sensor_service import start_elevated_helper

    try:
        outcome = start_elevated_helper()
    except Exception:
        outcome = "unavailable"
    if outcome != "not_requested":
        # `run_server.py` redirects stdout to `servidor.log`, which is where
        # a refusal has to be findable later. It is not shown on screen: a
        # user who clicked "No" made a choice and does not need it reported
        # back at them as a problem.
        print(f"[sensors] elevated CPU sensor helper: {outcome}")
    return outcome


@app.get("/api/version")
def api_version() -> dict:
    """The version this server is running: a newly installed copy
    asks before starting, to replace a server left over from the previous
    version instead of deferring to it."""
    return {"version": SYSTEM_VERSION}


def _running_version(host: str, port: int) -> str | None:
    """The version answering on the port, or `None` when it does not say —
    a version older than 1.5.8 (no `/api/version`) or not this program."""
    import json as _json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/version", timeout=3) as response:
            return str(_json.loads(response.read().decode("utf-8")).get("version") or "") or None
    except Exception:
        return None


def _program_process(pid: int):
    """The root of this program's process tree that `pid` belongs to, or
    `None` — whatever else holds the port is never touched.

    The venv's `pythonw.exe` is only a launcher: the server holding the
    port is the base Python it starts as a child (seen on a real machine).
    So the process itself or one of its first ancestors must run from the
    venv, and that ancestor is what is returned, to stop the whole tree."""
    try:
        import psutil

        from ..paths import machine_local_folder

        venv = os.path.normcase(os.path.abspath(str(machine_local_folder() / "venv")))
        process = psutil.Process(pid)
        for _ in range(3):
            if process is None:
                break
            exe = os.path.normcase(os.path.abspath(process.exe()))
            if exe.startswith(venv + os.sep):
                return process
            process = process.parent()
    except Exception:
        return None
    return None


def stop_outdated_server(host: str, port: int, pid: int | None, wait_seconds: float = 15.0) -> bool:
    """Stops a server of another version still holding the port.

    Installing an update did not stop the running server: opening the
    program again found the port taken, deferred to it, and showed the old
    version. Only a process started from this program's venv is stopped,
    with its children (OCR and conversion workers). Returns `True` when the
    port is free afterwards."""
    import time as _time

    from ..sensor_service import server_listening

    if pid is None or pid == os.getpid():
        return False
    process = _program_process(pid)
    if process is None or process.pid == os.getpid():
        return False
    try:
        import psutil

        family = [process] + process.children(recursive=True)
        # Never this new server, nor the launcher that started it: the old
        # server's tree must not contain either.
        own_line = {os.getpid()} | {parent.pid for parent in psutil.Process().parents()}
        if any(member.pid in own_line for member in family):
            return False
        for member in family:
            try:
                member.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(family, timeout=5)
    except Exception:
        return False
    deadline = _time.monotonic() + wait_seconds
    while _time.monotonic() < deadline:
        if not server_listening(host, port):
            return True
        _time.sleep(0.3)
    return not server_listening(host, port)


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Starts the server. Only listens on 127.0.0.1 — never 0.0.0.0
    (section 7)."""
    import uvicorn

    from .. import no_window, tools

    # Process-wide, before anything can start a subprocess: every command
    # this server or its libraries run — Tesseract through `pytesseract`,
    # Ghostscript, `ollama`, WMI queries — must never flash a console
    # window over the user's desktop (see `no_window.py`).
    no_window.install()

    # The operation slot starts empty (fase 33). Both structures live in
    # memory, so a fresh process already has them empty — but the server
    # that is starting is the owner of the slot and must not inherit
    # anything from a reloaded module, a test, or a future on-disk record:
    # a stale entry would refuse every long operation of that project
    # with "another operation is in progress" until the next restart.
    with _IMPORTS_IN_PROGRESS_LOCK:
        _IMPORTS_IN_PROGRESS.clear()
        _OPERATIONS_IN_PROGRESS.clear()

    # Also before anything runs: a fresh install's `PATH` change often has
    # not reached Explorer yet, and every process it started — this one
    # included — still carries the environment from before the install.
    # That is the reboot the user should not have needed (see `tools.py`).
    tools.ensure_on_path()

    # The OCR language, in this machine's own folder when
    # Tesseract's needs administrator rights (see `ocr_languages.py`).
    from .. import ocr_languages
    from ..config import ProjectConfig

    ocr_languages.ensure_in_background(
        ProjectConfig.__dataclass_fields__["ocr_language"].default, tools.find("tesseract")
    )

    # A impressão digital do código que este processo carregou. Comparada
    # a cada tela: editar um arquivo não muda um servidor já rodando, e sem
    # isso nada avisa que os dois estão fora de sincronia.
    record_loaded_source()

    _validate_host(host)
    global SERVER_PORT
    SERVER_PORT = int(port)

    # The system may already be open. That is the ordinary case for the
    # second shortcut — "GClaude Indexer (CPU sensor)" — which someone
    # clicks precisely because the first one is running and shows no CPU
    # temperature.
    #
    # What used to happen: this process asked for the helper, bound to
    # port 8000, lost to the server already there, and died with
    # "[Errno 10048] ... only one usage of each socket address". The
    # helper's lifetime is tied to the process whose handle it waits on,
    # so it died with it — and the server actually serving the pages had
    # never been told anything. Three of those errors sat in the log of a
    # machine where the user saw "not measured" and no explanation.
    from ..sensor_service import (
        clear_launch_status,
        elevation_requested,
        pid_listening_on,
        server_listening,
        start_elevated_helper,
        write_launch_status,
    )

    if server_listening(host, port) and _running_version(host, port) != SYSTEM_VERSION:
        outdated_pid = pid_listening_on(port)
        if stop_outdated_server(host, port, outdated_pid):
            print(f"[server] stopped the previous version (pid {outdated_pid}); starting {SYSTEM_VERSION}.")

    if server_listening(host, port):
        existing_pid = pid_listening_on(port)

        if not elevation_requested():
            print(f"[server] already running on {host}:{port} — nothing to start.")
            return

        if existing_pid is None:
            # Without the running server's pid there is nothing for the
            # helper to outlive, and starting one anyway would raise a UAC
            # prompt for a reader that dies seconds later.
            write_launch_status("unavailable")
            print(
                f"[sensors] the system is already open on {host}:{port}, but its process "
                "could not be identified. Close the system completely and open it again "
                'through the "CPU sensor" shortcut.'
            )
            return

        try:
            outcome = start_elevated_helper(parent_pid=existing_pid)
        except Exception:
            outcome = "unavailable"
        print(f"[sensors] elevated CPU sensor helper for pid {existing_pid}: {outcome}")
        return

    # Fase 32: from here on this process owns the sensor-helper status.
    # Whatever the last session left in the file is about a server that no
    # longer exists; kept, it made this one's screen say "the reader did
    # not answer" before anyone had asked for a reader. Not done in the
    # branch above: there the status belongs to the server already running.
    clear_launch_status()

    # Numa thread, e nunca antes do `uvicorn.run`.
    #
    # `start_elevated_helper()` chama `ShellExecuteW` com o verbo "runas",
    # que **bloqueia até o usuário responder ao prompt do Windows**. Feita
    # em linha, essa chamada segurava a subida inteira do servidor: o
    # prompt costuma aparecer atrás da janela do navegador ou apenas
    # piscando na barra de tarefas, e enquanto não fosse respondido a porta
    # 8000 nem começava a escutar. Encontrado com quatro `consent.exe`
    # empilhados e o servidor parado atrás deles.
    #
    # `daemon=True` para que uma resposta que nunca vem não impeça o
    # processo de encerrar.
    import threading

    threading.Thread(target=_request_cpu_sensor_helper, daemon=True).start()

    uvicorn.run(app, host=host, port=port)

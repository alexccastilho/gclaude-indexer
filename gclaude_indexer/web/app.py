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

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ..artifacts import (
    forget_form_instructions, generate_project_instructions_md, pending_items, stale_artifacts,
)
from ..catalog import catalog_folder, list_projects
from ..config import EXTRA_RULES_MAX_LENGTH, ConfigError, ProjectConfig, default_value, extra_rules_errors
from ..db import is_lock_error
from ..install_diagnostics import check_installation
from ..events import record_event
from ..instructions_dedup import apply as dedup_apply, block_pointer
from ..managed_block import BACKUP_SUFFIX, generated_part, replace_user_part, user_part
from ..invalidation import PlanExpired, apply_update_plan
from ..update_plan import SCREEN_READ_DEADLINE_SECONDS, SourceFolderUnavailable, UpdatePlan, build_update_plan
from ..cleanup import clear_intermediates, intermediates_size
from .. import claude_package, combined_package
from ..claude_package import generate_claude_project_package
from ..output_names import INDEX_FILENAME, PROJECT_INSTRUCTIONS_FILENAME, REVIEW_FILENAME, TIMELINE_FILENAME
from ..paths import resolve_within
from ..project import save_project_config
from ..sets import SetEntry, SetMember, find_set, list_sets, propose_alias, remove_set, save_set
from ..quality import compare_runs, quality_summary
from .. import lexml as lexml_module
from ..fulltext import (
    MATCH_END as FULLTEXT_MATCH_END,
    MATCH_START as FULLTEXT_MATCH_START,
    coverage as fulltext_coverage,
    index_pending as index_fulltext,
    search as fulltext_search,
)
from ..staleness import record_loaded_source
from .i18n import DEFAULT_LANGUAGE, LANGUAGE_COOKIE_NAME, valid_language, translate
from .layout import DEFAULT_LAYOUT, LAYOUT_COOKIE_NAME, valid_layout
from ..engine_local import _CONTEXT_FIELD_LIMIT as EXTRA_RULES_PROMPT_LIMIT
from .theme import THEME_COOKIE_NAME, DEFAULT_THEME, valid_theme
from . import routes_projects, routes_relocation, routes_run, state
from .caches import _cached_by_signature
from .formatting import _format_time
from .notices import _dedup_kept, _dedup_notice, _dedup_report, _pipeline_has_pending_work, _stale_context
from .operations import _OperationMessage, _operation_busy_response, _operation_response, _start_operation
from .project_access import (
    IncompleteSyncError, LockAbandonedError, LockBlockedError, RelocationBusyError, RelocationNeededError,
    _open_project, _project_or_404, _read_project,
)
from .rendering import WEB_ROOT, _request_language, _zip_response, render, templates
from .routes_relocation import _render_relocation
from .state import (
    _OPERATIONS_IN_PROGRESS, _SLOTS_LOCK, _generation_slot, _operation_in_progress, _release_all_projects,
    _release_project, _step_in_progress,
)


SYSTEM_VERSION = "2.1.0"
# Every page shows it (`base.html`, About); the build reads the line above.
templates.env.globals["system_version"] = SYSTEM_VERSION
SYSTEM_AUTHOR = "Alex Camacho Castilho"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    _release_all_projects()


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


@app.exception_handler(RelocationNeededError)
def _handle_relocation_needed(request: Request, exc: RelocationNeededError):
    return _render_relocation(request, exc.entry, exc.source_folder, status_code=409)


@app.exception_handler(RelocationBusyError)
def _handle_relocation_busy(request: Request, exc: RelocationBusyError):
    # Mesma resposta de um banco ocupado: a sondagem guarda o que já mostra
    # e pergunta de novo; uma página inteira explica e pede para esperar.
    if request.headers.get("hx-request"):
        return Response(status_code=204)
    return render(request, "database_busy.html", {}, status_code=503)


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


app.include_router(routes_projects.router)
app.include_router(routes_relocation.router)
app.include_router(routes_run.router)


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
    if _operation_in_progress(project_id):
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
            plan = build_update_plan(
                conn, config, record_warnings=False, read_deadline=SCREEN_READ_DEADLINE_SECONDS,
            )
        except SourceFolderUnavailable:
            return HTMLResponse("")
        if plan.is_empty:  # com não conferidos, não está vazio: o aviso aparece
            return HTMLResponse("")
        return render(
            request, "_update_banner.html",
            {"project": entry, "plan": plan, "config": config},
        )


def _current_instructions(config: ProjectConfig) -> str:
    """The user's part of `project_instructions.md`, to fill the field of
    the update screen."""
    return user_part(Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME)


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
                          user_text: str | None = None, conn=None, extra_rules: str | None = None) -> dict:
    path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
    report = _dedup_report(config)
    return {
        "project": entry, "config": config,
        "user_text": user_part(path) if user_text is None else user_text,
        "generated": generated_part(path),
        "exists": path.exists(),
        "message": message, "saved": saved,
        "extra_rules": config.extra_rules if extra_rules is None else extra_rules,
        "extra_rules_limit": EXTRA_RULES_MAX_LENGTH,
        "extra_rules_prompt_limit": EXTRA_RULES_PROMPT_LIMIT,
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
    language = _request_language(request)
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
    language = _request_language(request)
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
            saved_rules = config.extra_rules
            if rules:
                added = "\n".join(f"- {rule}" for rule in rules)
                config.extra_rules = (config.extra_rules.rstrip() + "\n" + added) if config.extra_rules.strip() else added
                changed_config = True
            if forget_form_instructions(config, new_user):
                changed_config = True
            if changed_config:
                try:
                    save_project_config(conn, config)
                except ConfigError as exc:
                    # As regras movidas passariam do teto: nada muda, nem a
                    # parte do usuário (que ainda não foi tocada).
                    return render(request, "instructions.html", _instructions_context(
                        entry, config, language, conn=conn, extra_rules=saved_rules,
                        message="; ".join(translate(language, e.key, **e.params) for e in exc.errors),
                    ), status_code=422)
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
    language = _request_language(request)
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


@app.post("/projects/{project_id}/instructions/extra-rules", response_class=HTMLResponse)
async def instructions_extra_rules_save(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_instructions_extra_rules_body, request, project_id, form)


def _instructions_extra_rules_body(request: Request, project_id: int, form):
    language = _request_language(request)
    text = str(form.get("extra_rules", "")).replace("\r\n", "\n").strip()
    with _open_project(project_id) as (entry, config, conn):
        if extra_rules_errors(text):
            return render(
                request, "instructions.html",
                _instructions_context(
                    entry, config, language, conn=conn, extra_rules=text,
                    message=translate(
                        language, "instructions.extra_rules.too_long",
                        size=len(text), limit=EXTRA_RULES_MAX_LENGTH,
                    ),
                ),
                status_code=422,
            )
        if text != config.extra_rules.strip():
            config.extra_rules = text
            save_project_config(conn, config)
            # Reescreve a seção gerada agora, para a tela já mostrar as
            # regras no bloco e o arquivo não esperar a próxima geração.
            if (Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME).exists():
                generate_project_instructions_md(conn, config, language)
        return render(request, "instructions.html", _instructions_context(
            entry, config, language, conn=conn, saved=True,
            message=translate(language, "instructions.extra_rules.saved"),
        ))


@app.get("/projects/{project_id}/update", response_class=HTMLResponse)
def update_screen(request: Request, project_id: int):
    """The confirmation. Read-only: it never writes to the project.

    `record_warnings=False` is what makes that categorical rather than
    merely usual — see `build_update_plan`.
    """
    with _open_project(project_id) as (entry, config, conn):
        try:
            plan = build_update_plan(
                conn, config, record_warnings=False, read_deadline=SCREEN_READ_DEADLINE_SECONDS,
            )
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
    entry = _project_or_404(project_id)
    if _step_in_progress(project_id):
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
    language = _request_language(request)

    with _open_project(project_id) as (entry, config, conn):
        # `_open_project`'s lock is the cross-machine one and the running
        # step already holds it, so it protects nothing here. SQLite
        # covers most of the database side, but `_prune_raw_items` is
        # outside it: it streams `raw_items.jsonl` to a temporary file
        # and renames it over the original while `classify_pending` may
        # be appending, so classifications written during the copy are
        # lost, or a stale line survives and is imported against pages
        # that have since moved.
        if _step_in_progress(project_id):
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
    language = _request_language(request)
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

    step_in_progress = _step_in_progress(project_id)

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

    _release_project(output_folder, project_id)
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
    language = _request_language(request)
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
    language = _request_language(request)
    with _open_project(project_id) as (_entry, config, _conn):
        content = generate_claude_project_package(config, language)
    return _zip_response(content, f"claude_project_{config.name}.zip")


# --- sets: several collections in one Claude Project (fase 38) ---------------


def _set_or_404(set_id: int) -> SetEntry:
    entry = find_set(set_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Conjunto não encontrado nesta máquina.")
    return entry


def _project_join_reason(e, language: str) -> str:
    """Por que um projeto não pode entrar num conjunto agora: pasta fora do
    ar ou relatórios nunca gerados. Vazio quando pode."""
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
    language = _request_language(request)
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
    language = _request_language(request)
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
    language = _request_language(request)
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
    language = _request_language(request)
    return _zip_response(combined_package.generate_zip(entry, language), f"claude_project_{entry.name}.zip")


@app.post("/sets/{set_id}/write-folder", response_class=HTMLResponse)
async def write_set_folder(request: Request, set_id: int):
    form = await request.form()
    return await run_in_threadpool(_write_set_folder_body, request, set_id, form)


def _write_set_folder_body(request: Request, set_id: int, form):
    entry = _set_or_404(set_id)
    language = _request_language(request)
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
    language = _request_language(request)
    return render(request, "help.html", {"manual_template": f"manual/{language}.html"})


@app.get("/about", response_class=HTMLResponse)
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


@app.post("/about/components/remove")
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


@app.post("/preferences/language")
async def choose_language(request: Request):
    form = await request.form()
    language = valid_language(str(form.get("language", DEFAULT_LANGUAGE)))
    return _save_preference(request, LANGUAGE_COOKIE_NAME, language)


@app.post("/preferences/theme")
async def choose_theme(request: Request):
    form = await request.form()
    theme = valid_theme(str(form.get("theme", DEFAULT_THEME)))
    # The screen changes the theme in place, without a reload.
    return _save_preference(request, THEME_COOKIE_NAME, theme, fetch_answer=True)


@app.post("/preferences/layout")
async def choose_layout(request: Request):
    form = await request.form()
    layout = valid_layout(str(form.get("layout", DEFAULT_LAYOUT)))
    return _save_preference(request, LAYOUT_COOKIE_NAME, layout)


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
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not server_listening(host, port):
            return True
        time.sleep(0.3)
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

    # The operation slot starts empty (fase 33). It lives in memory, so a
    # fresh process already has it empty — but the server
    # that is starting is the owner of the slot and must not inherit
    # anything from a reloaded module, a test, or a future on-disk record:
    # a stale entry would refuse every long operation of that project
    # with "another operation is in progress" until the next restart.
    with _SLOTS_LOCK:
        _OPERATIONS_IN_PROGRESS.clear()

    # Also before anything runs: a fresh install's `PATH` change often has
    # not reached Explorer yet, and every process it started — this one
    # included — still carries the environment from before the install.
    # That is the reboot the user should not have needed (see `tools.py`).
    tools.ensure_on_path()

    # The OCR language, in this machine's own folder when
    # Tesseract's needs administrator rights (see `ocr_languages.py`).
    from .. import ocr_languages

    ocr_languages.ensure_in_background(
        default_value("ocr_language"), tools.find("tesseract")
    )

    # A impressão digital do código que este processo carregou. Comparada
    # a cada tela: editar um arquivo não muda um servidor já rodando, e sem
    # isso nada avisa que os dois estão fora de sincronia.
    record_loaded_source()

    _validate_host(host)
    state.SERVER_PORT = int(port)

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
    threading.Thread(target=_request_cpu_sensor_helper, daemon=True).start()

    uvicorn.run(app, host=host, port=port)

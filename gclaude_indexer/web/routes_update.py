# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Updating the collection: the "the folder changed" banner, the
confirmation screen and applying the plan in the background."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from ..config import ProjectConfig
from ..events import record_event
from ..managed_block import replace_user_part, user_part
from ..invalidation import PlanExpired, apply_update_plan
from ..update_plan import SCREEN_READ_DEADLINE_SECONDS, SourceFolderUnavailable, UpdatePlan, build_update_plan
from ..output_names import PROJECT_INSTRUCTIONS_FILENAME
from .notices import _pipeline_has_pending_work
from .operations import _OperationMessage, _operation_response, _start_operation
from .project_access import _open_project, _project_or_404
from .rendering import _request_language, render
from .state import _operation_in_progress, _step_in_progress


router = APIRouter()


@router.get("/projects/{project_id}/update/banner", response_class=HTMLResponse)
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


@router.get("/projects/{project_id}/update", response_class=HTMLResponse)
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


@router.post("/projects/{project_id}/update", response_class=HTMLResponse)
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

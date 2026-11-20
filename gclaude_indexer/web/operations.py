# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Long operations in the background, with Stop (1.9.0): the work runs in a
thread holding the project's slot, and every screen follows it through
`/activity`."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..catalog import find_project
from ..run_control import OperationCancelled, StopSignal
from .i18n import translate
from .rendering import _request_language, render
from .state import _SLOTS_LOCK, _claim_slot_locked, _operation_holding, _release_slot


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
    with _SLOTS_LOCK:
        started_at = time.monotonic()
        if not _claim_slot_locked(project_id, key, started_at):
            return None
        operation = _Operation(
            id=next(_OPERATION_IDS), project_id=project_id, key=key,
            started_at=started_at, next_url=next_url,
        )
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
            _release_slot(project_id)

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
        "stoppable": True,
    }


def _slot_view(project_id: int, key: str, started_at: float, language: str) -> dict:
    """An operation holding the project's slot through `_generation_slot`
    (clearing intermediates, search indexing, dedup, deletion): it runs
    inside its own request, is not in `_OPERATIONS` and cannot be stopped,
    but the waiting panel of every other screen still has to see it. The id
    is negative so it never meets one from `_OPERATION_IDS`; it disappears
    from `/activity` when the slot is released."""
    entry = find_project(project_id)
    return {
        "id": -project_id,
        "project_id": project_id,
        "project_name": entry.name if entry is not None else "",
        "operation": translate(language, key),
        "operation_key": key,
        "status": "running",
        "stopping": False,
        "elapsed_s": max(0, int(time.monotonic() - started_at)),
        "next_url": f"/projects/{project_id}/run",
        "message": "",
        "stoppable": False,
    }


def _operation_busy_response(request: Request, project_id: int) -> HTMLResponse:
    """409 for a long operation that found the project's slot taken (fase 33).

    Names the operation that holds it, translated — the same text the
    activity bar shows — so the person knows what to wait for. The user
    never starts one of these while a generation runs; this
    page is the safety net for the day someone does, because "delete
    project" during a generation would remove files being written.
    """
    language = _request_language(request)
    running = _operation_holding(project_id)
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

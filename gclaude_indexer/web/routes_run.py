# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Execution screen: steps, log and progress fragments, the step buttons,
the resource chart and sensors, and the activity of long operations."""

from __future__ import annotations

import hmac
import os
import secrets
import sys
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ..artifacts import generate_all_artifacts
from ..config import ProjectConfig
from ..db import READER_TIMEOUT_SECONDS, WRITER_TIMEOUT_SECONDS
from ..events import list_events
from ..import_items import import_and_consolidate
from ..windows_prep import cleanup_legacy_window_files
from ..paths import suggest_output_folder
from ..resources import latest_sample
from .. import sensors, sensor_service
from ..sensor_service import read_launch_status
from ..sensors import unavailable_reason
from ..pipeline import LOG_STEPS
from .step_state import next_pending_step, step_status
from .background_runs import compute_progress, task_manager
from .i18n import translate
from . import project_access, state
from .caches import _cached_quality_summary, _idle_fragment
from .formatting import _format_time
from .notices import _dedup_notice, _reports_to_regenerate, _stale_context
from .operations import (
    OPERATION_FINISHED_TTL_SECONDS, _OPERATIONS, _back_to_project, _operation_busy_response, _operation_response,
    _operation_view, _slot_view, _start_operation,
)
from .project_access import _open_project, _project_or_404, _read_project
from .rendering import _request_language, render
from .state import _SLOTS_LOCK, _operation_holding


router = APIRouter()


# Fase 32: the one thing that lets a page ask for the elevated sensor
# helper. New on every server start, never written to disk, embedded only
# in the Run screen — a page no other origin can read. See
# `request_sensor_elevation` for the whole argument.
SENSOR_REQUEST_TOKEN = secrets.token_urlsafe(32)
# Held while a request for the elevated helper is in flight: `runas` blocks
# until the user answers the UAC prompt, and a second click (or a second
# tab) meanwhile must not open a second prompt behind the first.
_SENSOR_REQUEST_IN_FLIGHT = threading.Lock()

# 50 lines covered less than a minute of scanning on a large collection — the
# panel would scroll out before there was time to read it. 200 fits in
# memory with no pagination and covers the follow-along window the user
# actually uses.
LOG_LINES = 200


# --- screen: Execution ---------------------------------------------------------


@router.get("/projects/{project_id}/run", response_class=HTMLResponse)
def run_screen(request: Request, project_id: int):
    language = _request_language(request)
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
        relocation_banner = None
        if project_access._relocation_due(config):
            relocation_banner = {"destination": suggest_output_folder(config.source_folder) or ""}

    return render(
        request, "run.html",
        {
            **steps_context,
            "config": config, "eventos": events,
            "known_steps": LOG_STEPS,
            "sensor_token": SENSOR_REQUEST_TOKEN,
            "instructions_dedup": instructions_dedup,
            "relocation_banner": relocation_banner,
            **stale,
        },
    )


@router.get("/projects/{project_id}/run/log", response_class=HTMLResponse)
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
    language = _request_language(request)
    # Capped either way: a screen left open while a very long step ran must
    # not receive thousands of lines in one response.
    with _open_project(project_id, timeout=READER_TIMEOUT_SECONDS) as (_entry, _config, conn):
        events = list_events(conn, language=language, since=since, last=LOG_LINES)

    if since is None:
        log_context = {"eventos": events, "known_steps": LOG_STEPS}
        return render(request, "_log.html", log_context)

    return render(request, "_log_items.html", {"eventos": events, "known_steps": LOG_STEPS})


@router.get("/projects/{project_id}/run/steps", response_class=HTMLResponse)
def steps_fragment(request: Request, project_id: int):
    """User request: the steps table also refreshes itself during the run
    (before it only changed when a button was clicked), so progress can be
    followed without clicking anything."""
    language = _request_language(request)

    def build() -> str:
        with _read_project(project_id) as (entry, config, conn):
            context = _steps_context(project_id, entry, config, conn, language)
        return render(request, "_steps.html", context).body.decode("utf-8")

    return HTMLResponse(_idle_fragment(project_id, "steps", language, build))


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
        "show_done_notice": show_finished_notice,
        "qualidade": quality,
    }


def _step_running(project_id: int, key: str) -> bool:
    task = task_manager.get(project_id, key)
    return task is not None and task.running


def _start_from_next_step(request: Request, project_id: int, *, chain: bool):
    """Starts the first pending step (only it, or the chain from it) and
    answers with the steps table. With a long operation holding the
    project's slot (import, update, clearing, deletion...), nothing starts:
    the busy answer, the same check the other routes make."""
    if state._operation_in_progress(project_id):
        return _operation_busy_response(request, project_id)
    language = _request_language(request)
    with _open_project(project_id) as (entry, config, conn):
        next_step = next_pending_step(step_status(conn, lambda key: _step_running(project_id, key)))
        if next_step is not None:
            if chain:
                task_manager.start_all(project_id, entry.output_folder, language=language, first_step=next_step)
            else:
                task_manager.start_step(project_id, entry.output_folder, next_step, language=language)
        context = _steps_context(project_id, entry, config, conn, language)

    return render(request, "_steps.html", context)


@router.post("/projects/{project_id}/run-next", response_class=HTMLResponse)
def run_next_step(request: Request, project_id: int):
    """"Run next step" button (section 6): figures out on its own, from the
    database state, which is the next incomplete step, and starts it in the
    background (the response does not wait for it to finish — the progress
    bar follows along via `run/progress`)."""
    return _start_from_next_step(request, project_id, chain=False)


@router.post("/projects/{project_id}/run-all", response_class=HTMLResponse)
def run_all(request: Request, project_id: int):
    """"Run everything up to classification" button (section 6) — chains
    the steps in the background, one after another."""
    if state._operation_in_progress(project_id):
        return _operation_busy_response(request, project_id)
    language = _request_language(request)
    with _open_project(project_id) as (entry, config, conn):
        task_manager.start_all(project_id, entry.output_folder, language=language)
        context = _steps_context(project_id, entry, config, conn, language)

    return render(request, "_steps.html", context)


@router.post("/projects/{project_id}/resume", response_class=HTMLResponse)
def resume_run(request: Request, project_id: int):
    """"Continue" in the progress box (fase 34): the same chain as "run
    everything", started at the first pending step — the paused one, which
    is resumable — instead of at the scan."""
    return _start_from_next_step(request, project_id, chain=True)


@router.post("/projects/{project_id}/pause", response_class=HTMLResponse)
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


@router.get("/projects/{project_id}/run/progress", response_class=HTMLResponse)
def progress_fragment(request: Request, project_id: int):
    language = _request_language(request)
    return HTMLResponse(_idle_fragment(
        project_id, "progress", language,
        lambda: render(request, "_progress.html", _progress_context(project_id)).body.decode("utf-8"),
    ))


@router.get("/projects/{project_id}/run/resources")
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
    return host in {f"127.0.0.1:{state.SERVER_PORT}", f"localhost:{state.SERVER_PORT}"}


@router.post("/sensors/request-elevation")
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


@router.get("/activity")
def global_activity(request: Request) -> dict:
    """Every operation running now, and the ones that ended in the last
    few minutes, for the waiting panel of any screen. Reads memory
    only: it is asked every couple of seconds while the operation it
    describes holds the database."""
    language = _request_language(request)
    now = time.monotonic()
    with _SLOTS_LOCK:
        for project_id, operation in list(_OPERATIONS.items()):
            if (operation.finished_at is not None
                    and now - operation.finished_at > OPERATION_FINISHED_TTL_SECONDS):
                del _OPERATIONS[project_id]
        operations = list(_OPERATIONS.values())
        slots = dict(state._OPERATIONS_IN_PROGRESS)
    views = [_operation_view(op, language) for op in operations]
    # The slot taken by `_generation_slot` has no entry in `_OPERATIONS`.
    started_here = {op.project_id for op in operations if op.status == "running"}
    views += [
        _slot_view(project_id, key, started_at, language)
        for project_id, (key, started_at) in slots.items() if project_id not in started_here
    ]
    return {"operations": views}


@router.post("/projects/{project_id}/operation/stop")
def stop_operation(request: Request, project_id: int) -> dict:
    """The Stop button of the waiting panel and of the busy page. Asks the
    running operation to stop at its next checkpoint; nothing is committed
    after that, so the project stays as it was before the click (or, in a
    report generation, with each file either old or new)."""
    with _SLOTS_LOCK:
        operation = _OPERATIONS.get(project_id)
    if operation is None or operation.status != "running":
        return {"stopping": False}
    operation.stop.request_stop()
    return {"stopping": True}


@router.get("/projects/{project_id}/activity")
def project_activity(request: Request, project_id: int) -> dict:
    """What is running for this project right now, for the activity bar
    (fase 32). Reads a dictionary and nothing else — no project open, no
    database — because it is asked *during* the generation it describes
    and must answer in microseconds while that generation holds the
    database.

    `elapsed_s` is measured from the server's own start time: the page
    that asks may have been opened long after the click."""
    language = _request_language(request)
    running = _operation_holding(project_id)
    if running is None:
        return {"operation": None, "operation_key": None, "elapsed_s": 0}
    key, started_at = running
    return {
        "operation": translate(language, key),
        "operation_key": key,
        "elapsed_s": max(0, int(time.monotonic() - started_at)),
    }


@router.post("/projects/{project_id}/import-and-generate", response_class=HTMLResponse)
def import_and_generate(request: Request, project_id: int):
    """Starts the import and the generation in the background and
    answers at once; the waiting panel follows it and has the Stop button.
    A second click while one is running gets the busy page, as before."""
    language = _request_language(request)
    _project_or_404(project_id)

    def work(should_stop):
        with _open_project(project_id) as (_entry, config, conn):
            import_and_consolidate(conn, config, language=language, should_stop=should_stop)
            generate_all_artifacts(conn, config, language, should_stop=should_stop)
            # Sobras do motor manual do Claude Code (removido na 2.0.0): aqui,
            # em segundo plano e com Parar, e não ao abrir o projeto, porque
            # numa pasta do Drive são milhares de remoções.
            cleanup_legacy_window_files(config.output_folder, should_stop=should_stop)

    result_url = f"/projects/{project_id}/result"
    operation = _start_operation(project_id, "run.import_and_generate", work, result_url)
    return _operation_response(request, operation, project_id, _back_to_project(request, project_id))

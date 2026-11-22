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
import sqlite3
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from ..config import default_value
from ..db import is_lock_error
from ..staleness import record_loaded_source
from . import (
    routes_instructions, routes_projects, routes_relocation, routes_result, routes_run, routes_sets,
    routes_settings, routes_update, state,
)
from .project_access import (
    IncompleteSyncError, LockAbandonedError, LockBlockedError, RelocationBusyError, RelocationNeededError,
)
from .rendering import WEB_ROOT, render, templates
from .routes_relocation import _render_relocation
from .state import _OPERATIONS_IN_PROGRESS, _SLOTS_LOCK, _release_all_projects


SYSTEM_VERSION = "2.1.2"
# The About page shows it (`about.html`); the build reads the line above.
templates.env.globals["system_version"] = SYSTEM_VERSION


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
app.include_router(routes_update.router)
app.include_router(routes_instructions.router)
app.include_router(routes_result.router)
app.include_router(routes_sets.router)
app.include_router(routes_settings.router)


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

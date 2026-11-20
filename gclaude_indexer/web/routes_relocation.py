# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The lock between machines and the output folder that lives inside the
source (2.0.0): keeping the lock, taking over an abandoned one,
continuing past an incomplete sync, and moving the folder out."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..catalog import CatalogEntry, find_project
from .. import relocation
from ..paths import suggest_output_folder
from ..run_control import OperationCancelled
from ..project import describe_project
from ..sync import check_sync, mark_synced
from ..lock import check_lock, create_lock
from .operations import _OperationMessage, _operation_busy_response, _operation_response, _start_operation
from .project_access import _after_relocation, _project_or_404, _settle_relocation
from .rendering import render
from .state import _operation_in_progress, _release_project, _step_in_progress, lock_manager


router = APIRouter()


@router.post("/projects/{project_id}/alive")
def project_alive(project_id: int):
    """A screen of the project is still open: keeps its lock.
    Never takes the lock — that is the next real request's job, with the
    usual check of who else holds it."""
    entry = find_project(project_id)
    if entry is not None:
        lock_manager.touch(entry.output_folder)
    return Response(status_code=204)


# --- cross-machine portability: lock and sync (section 11) -------------------


@router.post("/projects/{project_id}/take-lock")
def take_over_lock_route(project_id: int):
    """Explicit user confirmation to take over an abandoned lock (section
    11.3 — a lock from another machine, unused for more than 10 minutes)."""
    entry = _project_or_404(project_id)
    _release_project(entry.output_folder, keep_lock_file=True)
    lock_manager.take_over(entry.output_folder)
    mark_synced(entry.output_folder)
    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)


@router.post("/projects/{project_id}/continue-anyway")
def continue_anyway_route(project_id: int):
    """Explicit user confirmation to continue despite the incomplete sync
    warning (section 11.4)."""
    entry = _project_or_404(project_id)
    mark_synced(entry.output_folder)
    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)


def _render_relocation(
    request: Request, entry: CatalogEntry, source_folder: str, *,
    error_key: str = "", error_params: dict | None = None, status_code: int = 200,
) -> HTMLResponse:
    """A tela de interrupção (molde `lock_abandoned.html`): o que muda, para
    onde, os avisos e os botões Mover agora / Adiar."""
    plan = None
    plan_error_key, plan_error_params = "", {}
    try:
        plan = relocation.build_plan(source_folder, entry.output_folder)
    except relocation.RelocationError as exc:
        plan_error_key, plan_error_params = exc.key, exc.params
    except OSError as exc:
        plan_error_key, plan_error_params = "relocation.error.failed", {"error": str(exc)}
    destination = plan.new if plan is not None else (suggest_output_folder(source_folder) or "")
    return render(
        request, "relocation.html",
        {
            "project": entry,
            "source_folder": source_folder,
            "destination": destination,
            "plan": plan,
            "plan_size": relocation.megabytes(plan.total_bytes) if plan is not None else "",
            "plan_error_key": plan_error_key,
            "plan_error_params": plan_error_params,
            "error_key": error_key,
            "error_params": error_params or {},
            "postponed": relocation.is_postponed(entry.output_folder),
        },
        status_code=status_code,
    )


def _relocation_source(entry: CatalogEntry) -> str | None:
    """A origem gravada no projeto, lida sem abrir o banco para escrita
    (`describe_project` não cria nada)."""
    summary = describe_project(entry.output_folder)
    return summary.source_folder if summary is not None else None


@router.get("/projects/{project_id}/relocate", response_class=HTMLResponse)
def relocation_screen(request: Request, project_id: int):
    entry = _project_or_404(project_id)
    entry = _settle_relocation(project_id, entry)
    source = _relocation_source(entry)
    if source is None or not relocation.output_inside_source(source, entry.output_folder):
        return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)
    return _render_relocation(request, entry, source)


@router.post("/projects/{project_id}/relocate/postpone")
def postpone_relocation_route(project_id: int):
    """"Adiar", sem prazo: guardado nesta máquina. A tela de interrupção não
    volta; a Execução mostra o aviso a cada abertura até a mudança."""
    entry = _project_or_404(project_id)
    relocation.postpone(entry.output_folder)
    return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)


@router.post("/projects/{project_id}/relocate")
def relocate_route(request: Request, project_id: int):
    """"Mover agora". O pedido traz só o id: a origem vem do banco e o
    destino é calculado aqui (`paths.suggest_output_folder`), nunca do
    formulário. A proteção contra outro site é a mesma das outras rotas
    que mudam algo (`_only_own_pages`)."""
    entry = _project_or_404(project_id)
    entry = _settle_relocation(project_id, entry)
    source = _relocation_source(entry)
    if source is None or not relocation.output_inside_source(source, entry.output_folder):
        return RedirectResponse(url=f"/projects/{project_id}/run", status_code=303)

    def refuse(key: str, **params) -> HTMLResponse:
        return _render_relocation(request, entry, source, error_key=key, error_params=params, status_code=409)

    if _step_in_progress(project_id):
        return refuse("relocation.error.step_running")
    if _operation_in_progress(project_id):
        return _operation_busy_response(request, project_id)
    if not check_sync(entry.output_folder).ok:
        return refuse("relocation.error.sync")
    lock_result = check_lock(entry.output_folder)
    if lock_result.status in ("blocked", "abandoned"):
        return refuse("relocation.error.other_machine", machine=lock_result.message_params.get("machine", ""))
    try:
        plan = relocation.build_plan(source, entry.output_folder)
    except relocation.RelocationError as exc:
        return refuse(exc.key, **exc.params)
    except OSError as exc:
        return refuse("relocation.error.failed", error=str(exc))

    old = entry.output_folder
    run_url = f"/projects/{project_id}/run"

    def work(should_stop):
        try:
            with relocation.flying(old, plan.new):
                # Nenhuma conexão nossa pode ficar aberta: o Windows não
                # deixa mudar de nome um arquivo aberto. A trava continua
                # no arquivo (desta máquina) e vai junto com a pasta.
                _release_project(old, keep_lock_file=True)
                create_lock(old)
                relocation.execute(plan, should_stop=should_stop, on_finalize=_after_relocation)
        except relocation.RelocationCancelled:
            raise OperationCancelled()
        except relocation.RelocationError as exc:
            raise _OperationMessage(exc.key, next_url=f"/projects/{project_id}/relocate", **exc.params)
        return run_url

    operation = _start_operation(project_id, "relocation.move", work, next_url=run_url)
    return _operation_response(request, operation, project_id, waiting_url="/projects")

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Projects screen, New project and Open project forms, shared catalog and
deleting a project."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..catalog import catalog_folder, list_projects, register_project
from ..config import FORM_FIELDS, ConfigError, config_from_input, defaults, field_kind
from ..deletion import delete_project
from .. import relocation
from ..output_names import PROJECT_DB_SIDECARS
from ..paths import (
    check_new_project_folders, ensure_writable_folder, suggest_output_folder,
    PROJECT_DB_NAME as _PROJECT_DB_NAME,
)
from ..config import ConfigErrorMessage
from ..project import describe_project, create_project
from ..file_types import CATEGORY_ALL, EXTENSION_CATEGORIES, MEDIA_CATEGORY, categories_by_family, normalize_categories
from .step_state import project_status
from .i18n import translate
from ..local_models import LOCAL_MODEL_PROFILES, default_local_profile
from ..engine_names import ENGINE_AUTOMATIC, ENGINE_LOCAL, ENGINE_RULES
from ..ollama_models import list_installed_models
from .folder_picker import choose_folder
from .operations import _operation_busy_response
from .project_access import _project_or_404
from .rendering import _request_language, _side_bar_cache, render
from .state import _generation_slot, _release_project


router = APIRouter()


# Presentation order of the engines in the form, from the simplest to use to
# the one that demands the most from the user. `CLASSIFICATION_ENGINES`
# (config.py) is a set and has no stable order — it stays the source of
# truth for validation, never for presentation. A test guarantees the two
# sets match.
CLASSIFICATION_ENGINES_ORDER: tuple[str, ...] = (ENGINE_AUTOMATIC, ENGINE_RULES, ENGINE_LOCAL)


def _config_to_form(data: dict | None = None) -> dict:
    """Values shown in the form: the section 6 defaults, overridden by
    whatever was submitted (to redisplay it on a validation error).
    `name`, `source_folder` and `output_folder` have no default (they are
    required): they start empty."""
    base = {name: "" for name in FORM_FIELDS} | defaults()
    if data:
        base.update(data)
    # "automatic" is the dataclass default, not the name of an installed
    # model — without this, no <option> of the <select> ends up `selected`
    # and the browser picks the first one. Resolved *after* `update(data)`
    # so an explicit user choice (a real model name, coming from the
    # <select>) always wins; only the "automatic" sentinel (from the
    # default, or resubmitted as-is) falls back to the default.
    if base.get("local_model") in ("", "automatic"):
        base["local_model"] = default_local_profile()
    return base


# --- screen: Projects ---------------------------------------------------------


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/projects")


@router.get("/projects", response_class=HTMLResponse)
def projects_screen(request: Request):
    from ..settings import configured_shared_catalog_folder

    folder = catalog_folder()
    projects = []
    for e in list_projects():
        # The path as *this* machine sees it: with a shared catalog, the
        # entry was very likely written on a computer whose Drive is
        # mounted under a different letter (section 11.5).
        resolved = e.resolved_output_folder(folder)
        available = e.is_available(folder)
        if available and (relocation.in_flight(resolved) or relocation.pending_for(resolved)):
            # A pasta está mudando de lugar (ou a mudança parou no meio):
            # ler o banco agora poderia achá-lo do outro lado.
            key, variables = "unavailable", {}
        elif available:
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


@router.post("/projects/shared-catalog", response_class=HTMLResponse)
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


@router.get("/projects/new", response_class=HTMLResponse)
def new_project_screen(request: Request):
    return render(request, "new_project.html", _new_project_context(_config_to_form()))


def _new_project_context(values: dict, errors: list | None = None, **extra) -> dict:
    """What `new_project.html` needs, the same on the first visit and on
    every answer that shows the form again."""
    return {
        "values": values,
        "familias": categories_by_family(),
        "category_all": CATEGORY_ALL,
        "media_extensions": sorted(EXTENSION_CATEGORIES[MEDIA_CATEGORY]),
        "engines": CLASSIFICATION_ENGINES_ORDER,
        "local_models": list_installed_models(),
        "default_local_model": default_local_profile(),
        "local_model_profiles": LOCAL_MODEL_PROFILES,
        "errors": errors if errors is not None else [],
        **extra,
    }


@router.post("/projects/new", response_class=HTMLResponse)
async def create_new_project(request: Request):
    form = await request.form()
    return await run_in_threadpool(_create_new_project_body, request, form)


def _create_new_project_body(request: Request, form):

    data: dict = {}
    for name in FORM_FIELDS:
        kind = field_kind(name)
        if kind is list:
            data[name] = [str(value) for value in form.getlist(name)]
        elif kind is bool:
            data[name] = name in form  # caixa de seleção: só vem quando marcada
        elif name in form:
            data[name] = str(form[name])
    # "TODOS" já cobre as categorias específicas (menos áudio e vídeo,
    # que só entram marcando `midia`): o servidor garante a regra que o
    # formulário só garante em JavaScript.
    data["extensions"] = normalize_categories(data["extensions"])

    # Saída em branco (o campo deixou de ser `required`, ou o POST veio sem
    # ele): o servidor calcula a mesma sugestão `<origem>-AI` que a tela
    # mostra, em vez de reprovar ou de deixar a decisão para o navegador.
    if not str(data.get("output_folder", "")).strip():
        suggestion = suggest_output_folder(str(data.get("source_folder", "")))
        if suggestion:
            data["output_folder"] = suggestion

    # Reexibido junto com o formulário, para uma saída editada não ser
    # trocada por sugestão depois de um erro.
    values = _config_to_form(data)
    values["output_touched"] = str(form.get("output_touched", ""))

    def _refuse(errors: list) -> HTMLResponse:
        return render(request, "new_project.html", _new_project_context(values, errors), status_code=400)

    try:
        config = config_from_input(data)
    except ConfigError as exc:
        return _refuse(exc.errors)

    # As regras de pasta valem só aqui, na criação (não em `_validate`, que
    # roda a cada abertura e não pode trancar projetos antigos). Vêm antes
    # de `describe_project` e de qualquer `mkdir`: nada é criado se a
    # origem e a saída não passarem.
    folder_errors = check_new_project_folders(config.source_folder, config.output_folder)
    if folder_errors:
        return _refuse(folder_errors)

    # A project already in this output folder is not an error to report and
    # walk away from — it is almost always the user trying to *reopen* it,
    # which is the gesture that had no other route. Creating here would
    # INSERT a second configuration row into that project's own database
    # and replace the saved settings with this form's, silently, keeping
    # the processed data so that nothing looked wrong (see `load_project`).
    # So the form stops and offers the thing that was actually meant.
    existing = describe_project(config.output_folder)
    if existing is not None:
        return render(
            request, "new_project.html", _new_project_context(values, existing_project=existing),
            status_code=409,
        )

    # Cria a pasta e prova que dá para gravar nela antes do banco: sem
    # permissão, unidade ausente ou nome inválido viram uma mensagem na
    # tela, não um 500.
    try:
        created_folder = ensure_writable_folder(config.output_folder)
    except OSError:
        return _refuse([ConfigErrorMessage("config_error.output_not_writable", {"path": config.output_folder})])

    try:
        conn, _ = create_project(config)
    except (OSError, sqlite3.Error):
        _undo_created_output_folder(config.output_folder, created_folder)
        return _refuse([ConfigErrorMessage("config_error.output_not_writable", {"path": config.output_folder})])
    conn.close()
    entry = register_project(config.name, config.output_folder)
    _side_bar_cache.clear()  # The side bar shows it at once
    return RedirectResponse(url=f"/projects/{entry.id}/run", status_code=303)


def _undo_created_output_folder(folder: str, created: bool) -> None:
    """Se a criação do banco falhou depois de a pasta ter sido criada por
    nós, não deixa uma pasta órfã para trás: tira o banco pela metade e a
    pasta, mas só se ela ficar vazia (nunca apaga o que não é nosso)."""
    if not created:
        return
    base = Path(folder)
    for name in (_PROJECT_DB_NAME, *PROJECT_DB_SIDECARS):
        try:
            (base / name).unlink()
        except OSError:
            pass
    try:
        base.rmdir()
    except OSError:
        pass


@router.get("/projects/open", response_class=HTMLResponse)
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
    summary = describe_project(folder) if folder else None
    return render(request, "open_project.html", {"value": folder, "summary": summary, "error": None})


@router.post("/projects/open", response_class=HTMLResponse)
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


@router.post("/select-folder", response_class=HTMLResponse)
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
    language = _request_language(request)
    folder = choose_folder(title=translate(language, "new_project.folder_picker_title"), initial=current_value)
    value = folder or current_value

    # `output_touched` não vazio = a pessoa já mexeu na saída. Escolher a
    # saída pelo Procurar também conta como mexer.
    touched = bool(str(form.get("output_touched", "")).strip()) or field == "output_folder"
    context = {
        "field": field, "form_field_name": field, "value": value,
        "touched": "1" if touched else "",
    }
    if field == "source_folder" and folder and not touched:
        # Procurar não dispara `input` no campo: sem isto a saída só seria
        # preenchida a quem digitasse a origem. A sugestão chega por um swap
        # fora de banda do campo de saída.
        suggestion = suggest_output_folder(folder)
        if suggestion:
            context["output_suggestion"] = suggestion
    return render(request, "_folder_field.html", context)


@router.post("/projects/suggest-output", response_class=HTMLResponse)
async def suggest_output(request: Request):
    form = await request.form()
    return await run_in_threadpool(_suggest_output_body, request, form)


def _suggest_output_body(request: Request, form):
    """Sugestão de saída para uma origem digitada. Só calcula e devolve o
    campo: não cria pasta nenhuma. Sem sugestão, ou com a saída já editada
    pela pessoa, responde 204 e a tela fica como está."""
    if str(form.get("output_touched", "")).strip():
        return Response(status_code=204)
    suggestion = suggest_output_folder(str(form.get("source_folder", "")))
    if not suggestion:
        return Response(status_code=204)
    return render(
        request, "_folder_field.html",
        {"field": "output_folder", "form_field_name": "output_folder", "value": suggestion, "touched": ""},
    )


# --- delete project (explicit user request) ----------------------------------


@router.get("/projects/{project_id}/delete", response_class=HTMLResponse)
def confirm_deletion(request: Request, project_id: int):
    entry = _project_or_404(project_id)
    return render(request, "delete_project.html", {"project": entry})


@router.post("/projects/{project_id}/delete")
async def delete_project_route(request: Request, project_id: int):
    form = await request.form()
    return await run_in_threadpool(_delete_project_route_body, request, project_id, form)


def _delete_project_route_body(request: Request, project_id: int, form):
    with _generation_slot(project_id, "delete.confirm") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        return _delete_project_unlocked(request, project_id, form)


def _delete_project_unlocked(request: Request, project_id: int, form):
    entry = _project_or_404(project_id)

    delete_files = str(form.get("delete_files", "")) == "all"

    # Releases the lock and closes this session's connection before touching
    # the folder — Windows won't let you delete a file that's open.
    _release_project(entry.output_folder, project_id)
    delete_project(entry, delete_files)
    _side_bar_cache.clear()  # The side bar shows it at once

    return RedirectResponse(url="/projects", status_code=303)

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Sets: several collections in one Claude Project (fase 38)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from ..catalog import catalog_folder, find_member, list_projects
from .. import claude_package, combined_package
from ..output_names import INDEX_FILENAME
from ..sets import SetEntry, SetMember, find_set, list_sets, propose_alias, remove_set, save_set
from .i18n import translate
from .rendering import _request_language, _zip_response, render


router = APIRouter()


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


def _members_by_current_id(entry: SetEntry) -> dict[int, SetMember]:
    """Each member under the id its project has in the catalog now
    (`find_member`): the recorded id may belong to another project by now.
    A member whose project is gone is left out."""
    current = {}
    for member in entry.members:
        project = find_member(member.project_id, member.project_created_at)
        if project is not None:
            current[project.id] = member
    return current


def _project_choices(language: str, entry: SetEntry) -> list[dict]:
    """Every catalog project, with whether it can join a set and why not.
    Shown disabled rather than hidden: the person sees the project is
    known and learns what to do (generate its reports, or open it on the
    computer that has it)."""
    aliases = {project_id: m.alias for project_id, m in _members_by_current_id(entry).items()}
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
            members.append(SetMember(project_id=e.id, alias=alias, project_created_at=e.created_at))
    # Um membro fora do ar (Drive de outro computador, pasta renomeada) vem
    # desabilitado na tela e o navegador não o envia. Ele continua no
    # conjunto: a revisão da fase 38 viu o conjunto perder o
    # membro só porque a pessoa corrigiu o texto pessoal. Para tirá-lo, a
    # pasta precisa estar acessível (ou apaga-se o conjunto).
    current = {id(m): project_id for project_id, m in _members_by_current_id(entry).items()}
    members += [m for m in entry.members if current.get(id(m)) not in selectable]
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


@router.get("/sets", response_class=HTMLResponse)
def sets_screen(request: Request):
    def name(member: SetMember) -> str:
        project = find_member(member.project_id, member.project_created_at)
        return project.name if project is not None else f"#{member.project_id}"

    rows = [
        {"entry": entry, "members": ", ".join(f"{m.alias} ({name(m)})" for m in entry.members)}
        for entry in list_sets()
    ]
    return render(request, "sets.html", {"sets": rows})


@router.get("/sets/new", response_class=HTMLResponse)
def new_set_form(request: Request):
    return _render_set(request, SetEntry(id=0, name=""))


@router.post("/sets/new", response_class=HTMLResponse)
async def create_set(request: Request):
    form = await request.form()
    return await run_in_threadpool(_save_set_body, request, form, SetEntry(id=0, name=""))


@router.get("/sets/{set_id}", response_class=HTMLResponse)
def set_screen(request: Request, set_id: int, written: int = 0, folder: str = ""):
    entry = _set_or_404(set_id)
    language = _request_language(request)
    notice = translate(language, "sets.written", count=written, folder=folder) if written and folder else ""
    return _render_set(request, entry, notice=notice, target_folder=folder)


@router.post("/sets/{set_id}", response_class=HTMLResponse)
async def update_set(request: Request, set_id: int):
    form = await request.form()
    return await run_in_threadpool(_save_set_body, request, form, _set_or_404(set_id))


@router.post("/sets/{set_id}/delete")
def delete_set(set_id: int):
    """Only the set is removed. The projects, their folders and any
    combined folder already written stay as they are."""
    _set_or_404(set_id)
    remove_set(set_id)
    return RedirectResponse(url="/sets", status_code=303)


@router.get("/sets/{set_id}/package")
def download_set_package(request: Request, set_id: int):
    entry = _set_or_404(set_id)
    language = _request_language(request)
    return _zip_response(combined_package.generate_zip(entry, language), f"claude_project_{entry.name}.zip")


@router.post("/sets/{set_id}/write-folder", response_class=HTMLResponse)
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

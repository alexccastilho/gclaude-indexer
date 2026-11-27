# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Result screen, the Claude package, clearing intermediates, full-text
search and opening the files and folders of a project."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from ..artifacts import pending_items, stale_artifacts
from ..cleanup import clear_intermediates, intermediates_size
from .. import claude_package
from ..claude_package import generate_claude_project_package
from ..output_names import INDEX_FILENAME, PROJECT_INSTRUCTIONS_FILENAME, REVIEW_FILENAME, TIMELINE_FILENAME
from ..paths import resolve_within
from ..quality import compare_runs, quality_summary
from .. import lexml as lexml_module
from ..fulltext import (
    MATCH_END as FULLTEXT_MATCH_END,
    MATCH_START as FULLTEXT_MATCH_START,
    coverage as fulltext_coverage,
    index_pending as index_fulltext,
    search as fulltext_search,
)
from .i18n import translate
from .caches import _cached_by_signature
from .formatting import _format_time
from .notices import _dedup_notice, _stale_context
from .operations import _operation_busy_response, _step_busy_response
from .project_access import _open_project, _read_project
from .rendering import _request_language, _zip_response, render
from .state import StepStillRunning, _generation_slot, _release_project, _step_in_progress


router = APIRouter()


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


@router.get("/projects/{project_id}/result", response_class=HTMLResponse)
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
            dict(row) for row in _cached_by_signature(project_id, "comparison", conn, config, lambda: compare_runs(conn, quality))
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


@router.post("/projects/{project_id}/clear-intermediates")
def clear_intermediates_route(request: Request, project_id: int):
    with _generation_slot(project_id, "result.cleanup_button") as claimed:
        if not claimed:
            return _operation_busy_response(request, project_id)
        return _clear_intermediates_unlocked(request, project_id)


def _clear_intermediates_unlocked(request: Request, project_id: int):
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

    try:
        _release_project(output_folder, project_id)
    except StepStillRunning:
        return _step_busy_response(request, project_id, "run.step_busy.stopping")
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


@router.get("/projects/{project_id}/search", response_class=HTMLResponse)
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


@router.post("/projects/{project_id}/search/index")
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


@router.post("/projects/{project_id}/open-file")
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


@router.post("/projects/{project_id}/open-folder")
def open_folder_in_explorer(project_id: int):
    with _open_project(project_id) as (_entry, config, _conn):
        path = Path(config.output_folder).resolve()
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", str(path)], shell=False)
    return RedirectResponse(url=f"/projects/{project_id}/result", status_code=303)


@router.get("/projects/{project_id}/result/claude-package")
def download_claude_package(request: Request, project_id: int):
    """Zip with the four artifacts + an installation guide for a new Claude
    Project (explicit user request) — in the interface's language at the
    moment of the download."""
    language = _request_language(request)
    with _open_project(project_id) as (_entry, config, _conn):
        content = generate_claude_project_package(config, language)
    return _zip_response(content, f"claude_project_{config.name}.zip")

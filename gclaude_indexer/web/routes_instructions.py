# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The person's own instructions and the project's extra rules, editable at
any time, and the clean-up of a part that repeats the managed block."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from ..artifacts import forget_form_instructions, generate_project_instructions_md
from ..config import EXTRA_RULES_MAX_LENGTH, ConfigError, extra_rules_errors
from ..events import record_event
from ..instructions_dedup import apply as dedup_apply, block_pointer
from ..managed_block import BACKUP_SUFFIX, generated_part, replace_user_part, user_part
from ..output_names import PROJECT_INSTRUCTIONS_FILENAME
from ..project import save_project_config
from .i18n import translate
from ..engine_local import _CONTEXT_FIELD_LIMIT as EXTRA_RULES_PROMPT_LIMIT
from .notices import _dedup_kept, _dedup_report
from .operations import _operation_busy_response
from .project_access import _open_project
from .rendering import _request_language, render
from .state import _generation_slot


router = APIRouter()


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


@router.get("/projects/{project_id}/instructions", response_class=HTMLResponse)
def instructions_screen(request: Request, project_id: int):
    """The person's own instructions, editable at any time.

    Until 1.8.1 the only place to give the program the instructions kept in
    the Claude Project was the update screen; an update confirmed without
    them left no other way. Only the person's part is editable here; the
    section the program generates is shown read-only below it."""
    language = _request_language(request)
    with _open_project(project_id) as (entry, config, conn):
        return render(request, "instructions.html", _instructions_context(entry, config, language, conn=conn))


@router.post("/projects/{project_id}/instructions/dedup", response_class=HTMLResponse)
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


@router.post("/projects/{project_id}/instructions", response_class=HTMLResponse)
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


@router.post("/projects/{project_id}/instructions/extra-rules", response_class=HTMLResponse)
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

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Picks and runs the right classification engine according to
`config.classification_engine` and `config.review_low_confidence` (spec
section 6, form fields) — the link between the form and the engines from
phases 5 and 8. `automatic` picks `local` if the hardware allows a model,
otherwise `rules`.

NOTE: `config.classification_engine` now speaks the same English vocabulary
as `classification.VALID_ENGINES` — "rules", "local", "claude_code" — plus
the "automatic" sentinel, which is resolved right here and never itself
written to `item.engine`. Both `config.py`'s `CLASSIFICATION_ENGINES` and
this module used to keep the old Portuguese literals ("automatico"/"regras")
on purpose, matching each other while `classification.py`'s vocabulary was
translated first; that left `run.engine` (fed by `config.classification_engine`)
and `item.engine` (fed by the engines' own output) speaking two different
languages, so `quality.compare_runs` could never match one against
the other. Both sides now use the same English literals.
"""

from __future__ import annotations

import sqlite3

from .config import ProjectConfig
from .hardware import diagnose, choose_model
from .engine_local import LocalEngine, classify_pending as classify_pending_local, model_to_use
from .engine_rules import RulesEngine, load_rules, classify_pending as classify_pending_rules
from .review import classify_with_review


def resolve_effective_engine(
    conn: sqlite3.Connection, config: ProjectConfig, language: str | None = None
) -> str:
    if config.classification_engine != "automatic":
        return config.classification_engine
    diagnostics = diagnose(conn, language=language)
    choice = choose_model(conn, diagnostics, model_to_use(conn, config), language=language)
    return "rules" if choice.use_rules_engine else "local"


def _instantiate_engine(conn: sqlite3.Connection, config: ProjectConfig, engine_name: str):
    if engine_name == "local":
        return LocalEngine(model=model_to_use(conn, config))
    return RulesEngine(load_rules())


def run_classification(
    conn: sqlite3.Connection, config: ProjectConfig, should_stop=None, language: str | None = None
) -> tuple[str, object]:
    """Runs step 6 for the synchronous engines (`regras`/`local`, with or
    without review mode). `claude_code` does not go through here — it is
    handled separately by the interface (asynchronous execution). Returns
    `(motor_usado, resultado)`."""
    effective_engine = resolve_effective_engine(conn, config, language=language)

    if config.review_low_confidence and effective_engine != "rules":
        second_engine = _instantiate_engine(conn, config, effective_engine)
        result = classify_with_review(
            conn, config, second_engine, effective_engine, should_stop=should_stop, language=language
        )
        return f"rules + revisão ({effective_engine})", result

    if effective_engine == "local":
        result = classify_pending_local(
            conn, config, local_engine=LocalEngine(model=model_to_use(conn, config)),
            should_stop=should_stop, language=language,
        )
        return "local", result

    result = classify_pending_rules(conn, config, should_stop=should_stop, language=language)
    return "rules", result

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Picks and runs the right classification engine according to
`config.classification_engine` (spec section 6, form field) — the link
between the form and the engines from phases 5 and 8. `automatic` picks `local` if the hardware allows a model,
otherwise `rules`.

NOTE: `config.classification_engine` now speaks the same English vocabulary
as `classification.VALID_ENGINES` — "rules", "local" — plus
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
from dataclasses import dataclass

from .config import ProjectConfig
from .engine_names import ENGINE_AUTOMATIC, ENGINE_LOCAL, ENGINE_RULES
from .hardware import diagnose, choose_model
from .engine_local import classify_pending as classify_pending_local
from .local_models import model_to_use
from .engine_rules import classify_pending as classify_pending_rules


@dataclass(frozen=True)
class EngineDecision:
    """The engine a classification step runs, and the model when it is the
    local one. Decided once per step run (`decide_engine`, called by
    `pipeline.begin_step`), which records it in `run.engine`/`run.model`
    and hands the same decision to `run_classification`, so the row can no longer name an engine or a model
    other than the one that ran (Ollama could come up or go down between two
    separate resolutions)."""

    engine: str
    model: str | None = None


def decide_engine(
    conn: sqlite3.Connection, config: ProjectConfig, language: str | None = None
) -> EngineDecision:
    """The one place where the project's choice becomes the engine that runs.

    `automatic` asks the hardware (`diagnose` + `choose_model`, which log
    the diagnostics) whether the local model fits. The per-window fallback
    of the local engine to the rules one while Ollama is down is a different
    decision, taken inside `engine_local.classify_pending`."""
    if config.classification_engine != ENGINE_AUTOMATIC:
        engine = config.classification_engine
        return EngineDecision(engine, model_to_use(config) if engine == ENGINE_LOCAL else None)
    model = model_to_use(config)
    diagnostics = diagnose(conn, language=language)
    choice = choose_model(conn, diagnostics, model, language=language)
    if choice.use_rules_engine:
        return EngineDecision(ENGINE_RULES)
    return EngineDecision(ENGINE_LOCAL, model)


def resolve_effective_engine(
    conn: sqlite3.Connection, config: ProjectConfig, language: str | None = None
) -> str:
    return decide_engine(conn, config, language=language).engine


def run_classification(
    conn: sqlite3.Connection, config: ProjectConfig, *, should_stop=None, language: str | None = None,
    decision: EngineDecision | None = None,
) -> tuple[str, object]:
    """Runs step 6 (`rules`/`local`). Returns `(engine_used, result)`.

    `decision`: the engine already decided for this run
    (`pipeline.begin_step` decides it before the step, to record it);
    without one it is decided here."""
    if decision is None:
        decision = decide_engine(conn, config, language=language)

    if decision.engine == ENGINE_LOCAL:
        # 2.1.0: the engine is built by `classify_pending` itself, from the
        # project. Built here, it used to lose `config` (no Subject, Collection
        # type, Role or Extra rules ever reached the prompt of a run started
        # from the interface) and `processing_mode` ("cpu" still loaded the
        # whole model on the card).
        result = classify_pending_local(
            conn, config, should_stop=should_stop, language=language, model=decision.model
        )
        return ENGINE_LOCAL, result

    result = classify_pending_rules(conn, config, should_stop=should_stop, language=language)
    return ENGINE_RULES, result

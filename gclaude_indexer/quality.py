# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Quality summary of a run, to compare engines and models.

Everything comes from what the pipeline already records — `item.confidence`,
type, date, file status and page gaps. There is no new data model: the goal
is to let the same collection run with different engines and compare the
numbers side by side.

**About the score:** it is a synthesis of the measurements below, useful to
compare runs of the same collection against each other. It measures the
engine's *declared self-confidence* and how much it filled in the fields —
it does not measure actual correctness, which would require a hand-checked
answer key. An engine can score well here and still classify something
wrong.
"""

from __future__ import annotations

from datetime import datetime

from .config import ProjectConfig

_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.2}

# Column name cannot be a `?` SQL parameter, so the two `_count_nulls`
# helpers below (in `quality_summary` and `_engine_quality`) build the query
# with string interpolation. Today both are only ever called with literals
# from this file, so there is no injection — but "column name" is exactly
# the kind of thing that stops being a literal the day someone wires a
# request parameter into it. This allowlist is what keeps that safe: any
# name outside it raises instead of reaching the query.
_NULLABLE_COLUMNS = frozenset({"type", "date", "summary"})

# Below this share of dated items, the collection is treated as one whose
# documents simply do not carry dates, and `date` stops counting towards
# the fill rate.
#
# The reason is a measurement, not a preference. A real collection of
# postgraduate course material scored 60/100 with 99.3% high-confidence
# items: `date` was empty on all 1445 of them, and empty was the *correct*
# answer — lecture notes are not dated documents. The formula charged 15 of
# the 30 fill-rate points for that, so the score punished the engine for
# being right, and 100 was unreachable no matter how good the
# classification got.
#
# 5% rather than 0: a collection with a handful of dated items among
# thousands is still an undated collection, and one stray date the model
# invented must not switch a whole collection into being graded on a field
# it does not have.
_DATED_COLLECTION_THRESHOLD = 0.05


def _fill_rate(total: int, missing_type: int, missing_date: int) -> tuple[float, bool]:
    """`(fill_rate, date_counted)` — how completely the fields are filled.

    `type` always counts: any collection has document types, and a missing
    one is a real gap in the index.

    `date` counts only when this collection turns out to have dates at all
    (see `_DATED_COLLECTION_THRESHOLD`). When it does not, the rate is
    measured on `type` alone, and the flag tells the screen to say so —
    a score that silently changes what it measures would be worse than the
    one it replaces.
    """
    if total <= 0:
        return 0.0, False

    dated = total - missing_date
    date_counted = (dated / total) >= _DATED_COLLECTION_THRESHOLD
    if date_counted:
        return 1 - ((missing_type + missing_date) / (2 * total)), True
    return 1 - (missing_type / total), False


def quality_summary(conn, config: ProjectConfig) -> dict:
    total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]

    confidence = {"high": 0, "medium": 0, "low": 0}
    for level, count in conn.execute(
        "SELECT confidence, COUNT(*) FROM item GROUP BY confidence"
    ):
        if level in confidence:
            confidence[level] = count

    def _count_nulls(column: str) -> int:
        if column not in _NULLABLE_COLUMNS:
            raise ValueError(f"column not allowed: {column!r}")
        return conn.execute(
            f"SELECT COUNT(*) FROM item WHERE {column} IS NULL OR TRIM({column}) = ''"
        ).fetchone()[0]

    missing_type = _count_nulls("type")
    missing_date = _count_nulls("date")
    missing_summary = _count_nulls("summary")

    failed_files = conn.execute(
        "SELECT COUNT(*) FROM file WHERE status = 'failed'"
    ).fetchone()[0]
    windows_pending = conn.execute(
        "SELECT COUNT(*) FROM window WHERE status = 'pending'"
    ).fetchone()[0]

    from .artifacts import pending_items

    gaps = len(pending_items(conn).get("gaps", {}) or {})

    # Cobertura: quantas das páginas extraídas estão dentro de alguma peça.
    #
    # É a medida que faltava, e a que mais importa para o uso real deste
    # sistema — o índice existe para levar alguém ao PDF certo, na página
    # certa, e uma página que não aparece em peça nenhuma é informação que
    # ninguém mais encontra. Medido num laudo de 31 páginas: quatro modelos
    # devolveram de 0 a 3 peças cobrindo 9,7% das páginas, TODAS com
    # confiança "high" e todos os campos preenchidos. Pela fórmula anterior
    # aquilo pontuava perto de 100 — a nota não olhava para o buraco.
    total_pages = conn.execute("SELECT COUNT(*) FROM page").fetchone()[0]
    covered_pages = conn.execute(
        """
        SELECT COUNT(*) FROM page
        WHERE EXISTS (
            SELECT 1 FROM item
            WHERE page.number BETWEEN item.start_order AND item.end_order
        )
        """
    ).fetchone()[0]
    coverage = (covered_pages / total_pages) if total_pages else 0.0

    confidence_weight = 0.0
    fill_rate = 0.0
    date_counted = False
    penalty = 0.0
    if total_items == 0:
        score = 0
    else:
        confidence_weight = sum(_WEIGHTS[n] * q for n, q in confidence.items()) / total_items
        fill_rate, date_counted = _fill_rate(total_items, missing_type, missing_date)
        penalty = 0.1 if (windows_pending or failed_files) else 0.0
        # Pesos: cobertura 40, confiança 35, preenchimento 25. A cobertura
        # é a maior fatia porque é a única cujo fracasso não tem conserto a
        # jusante — um tipo vazio se reclassifica, uma página ausente do
        # índice simplesmente não é encontrada por quem consulta.
        score = int(
            round(
                max(0.0, min(1.0,
                    0.40 * coverage + 0.35 * confidence_weight + 0.25 * fill_rate - penalty)) * 100
            )
        )

    return {
        "engine": config.classification_engine,
        "model": config.local_model,
        "total_items": total_items,
        "confidence": confidence,
        "missing_type": missing_type,
        "missing_date": missing_date,
        "missing_summary": missing_summary,
        "failed_files": failed_files,
        "windows_pending": windows_pending,
        "gaps": gaps,
        "score": score,
        # The score broken into its parts. A single number the user cannot
        # take apart is a number they cannot act on: the review that led
        # here needed a database query to find out that one empty field
        # accounted for 30 of the 40 missing points.
        "coverage_pct": round(coverage * 100, 1),
        "pages_total": total_pages,
        "pages_covered": covered_pages,
        "coverage_points": round(0.40 * coverage * 100, 1) if total_items else 0.0,
        "confidence_points": round(0.35 * confidence_weight * 100, 1) if total_items else 0.0,
        "fill_points": round(0.25 * fill_rate * 100, 1) if total_items else 0.0,
        "penalty_points": round(-penalty * 100, 1) if total_items else 0.0,
        "date_counted": date_counted if total_items else False,
    }


# --- Phase 13 Task 15: benchmark (time + quality side by side) -------------
#
# `quality_summary` above answers "how good" for the *current* run. What was
# missing for the user's original request — "I want to compare different
# models, both in time and in quality" — was time. The `execucao` table
# (Task 15, `db.py`) records the start/end of each step; the two functions
# below read that table.
#
# Important limitation, and why we're careful with `None` instead of making
# up a zero: `peca` (Task 9) is always recalculated from scratch on every
# import (`import_items.py: _write_items` does `DELETE FROM item` before
# rewriting) — it only reflects the last imported classification, and
# `peca.motor` only stores "rules"/"local"/"claude_code" (never the model
# name, see `classification.py: VALID_ENGINES`). That's why filtering by
# `motor` alone is not enough: two different (engine, model) groups can
# share the same `motor` (e.g. "local" with different models), and
# filtering by `motor` alone would attribute one's score to the other. The
# score and confidence distribution below only exist for the (engine,
# model) group of the last successful 'classification' run (`execucao.ok =
# 1`, largest `terminado_em`) — it is the only one that can match what is
# currently in `peca`; for every other group the score comes back `None`,
# never a number computed over data that no longer belongs to that
# engine/model.


def run_history(conn) -> list[dict]:
    """One row per step run recorded in `execucao`, most recent first. Raw
    data behind `compare_runs` — useful for auditing/debugging without
    depending on the grouping."""
    rows = conn.execute(
        """
        SELECT step, engine, model, parallelism, started_at, finished_at, items, ok
        FROM run
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _last_classification_run(conn) -> tuple[str | None, str | None] | None:
    """`(engine, model)` of the last successful 'classification' run, or
    `None` if there is none. It is the only (engine, model) that can match
    the current content of `peca` — see the note above `compare_runs`."""
    row = conn.execute(
        """
        SELECT engine, model
        FROM run
        WHERE step = 'classification' AND ok = 1 AND finished_at IS NOT NULL
        ORDER BY finished_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return row["engine"], row["model"]


def _engine_quality(conn, engine: str | None) -> tuple[int | None, dict | None]:
    """Score and confidence distribution of the items currently recorded for
    this engine — `None` (not zero) when `peca` has none, which usually
    means the last import came from a different engine."""
    total = conn.execute("SELECT COUNT(*) FROM item WHERE engine = ?", (engine,)).fetchone()[0]
    if not total:
        return None, None

    confidence = {"high": 0, "medium": 0, "low": 0}
    for level, count in conn.execute(
        "SELECT confidence, COUNT(*) FROM item WHERE engine = ? GROUP BY confidence", (engine,)
    ):
        if level in confidence:
            confidence[level] = count

    def _count_nulls(column: str) -> int:
        if column not in _NULLABLE_COLUMNS:
            raise ValueError(f"column not allowed: {column!r}")
        return conn.execute(
            f"SELECT COUNT(*) FROM item WHERE engine = ? AND ({column} IS NULL OR TRIM({column}) = '')",
            (engine,),
        ).fetchone()[0]

    missing_type = _count_nulls("type")
    missing_date = _count_nulls("date")

    confidence_weight = sum(_WEIGHTS[n] * q for n, q in confidence.items()) / total
    # Same rule as `quality_summary`, so a run's score and the same run's
    # row in the benchmark can never disagree.
    fill_rate, _date_counted = _fill_rate(total, missing_type, missing_date)
    score = int(round(max(0.0, min(1.0, 0.7 * confidence_weight + 0.3 * fill_rate)) * 100))
    return score, confidence


def compare_runs(conn) -> list[dict]:
    """Groups classification runs by (engine, model) and returns, for each
    one: total time, items per minute, quality score and confidence
    distribution — the basis for answering "is model X worth the extra time
    over Y?".

    Only considers the 'classification' step: it is the only one whose
    engine/model varies from run to run, which is why it is the one that
    answers the benchmark question, unlike scan/conversion/extraction/
    windowing, which run the same way no matter which engine was chosen.

    Honesty (warnings the screen needs to repeat, not just this function):
    time is only comparable on the same collection and the same machine;
    the score measures self-confidence and field completion, not
    correctness; and when the parallelism mode changed between runs of the
    same group, the times are not comparable to each other — hence
    `mixed_parallelism` below.
    """
    run_rows = conn.execute(
        """
        SELECT engine, model, parallelism, started_at, finished_at, items
        FROM run
        WHERE step = 'classification' AND ok = 1 AND finished_at IS NOT NULL
        """
    ).fetchall()

    groups: dict[tuple, dict] = {}
    for row in run_rows:
        key = (row["engine"], row["model"])
        group = groups.setdefault(
            key,
            {"engine": row["engine"], "model": row["model"], "total_seconds": 0.0,
             "total_items": 0, "parallelism_modes": set()},
        )
        try:
            start = datetime.fromisoformat(row["started_at"])
            end = datetime.fromisoformat(row["finished_at"])
            group["total_seconds"] += max(0.0, (end - start).total_seconds())
        except (TypeError, ValueError):
            pass  # corrupted/incomplete record — does not block the comparison
        group["total_items"] += row["items"] or 0
        group["parallelism_modes"].add(row["parallelism"])

    last_run = _last_classification_run(conn)

    result = []
    for group in groups.values():
        total_seconds = group["total_seconds"]
        total_items = group["total_items"]
        items_per_minute = (
            round(total_items / (total_seconds / 60), 2) if total_seconds > 0 else None
        )

        modes = group["parallelism_modes"]
        mixed_parallelism = len(modes) > 1
        parallelism = None if mixed_parallelism else next(iter(modes), None)

        # Only the (engine, model) group of the last successful
        # classification run can match what is currently recorded in
        # `peca` — `peca.motor` never stores the model name, so filtering
        # by `motor` alone would attribute one model's score to another
        # (C2, final Phase 13 review).
        if last_run is not None and (group["engine"], group["model"]) == last_run:
            score, confidence = _engine_quality(conn, group["engine"])
        else:
            score, confidence = None, None

        result.append({
            "engine": group["engine"],
            "model": group["model"],
            "total_seconds": round(total_seconds, 1),
            "items_per_minute": items_per_minute,
            "score": score,
            "confidence": confidence,
            "parallelism": parallelism,
            "mixed_parallelism": mixed_parallelism,
        })

    result.sort(key=lambda row: (row["engine"] or "", row["model"] or ""))
    return result

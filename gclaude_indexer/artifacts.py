# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Generation of the four output artifacts (spec section 5, step 8):
`index.md`, `timeline.md`, `review.md` and `project_instructions.md`.

Each file is rewritten from scratch on every run — deterministic from the
database's current state, so regenerating is always safe.

File names are fixed in English regardless of the interface language (Task
11, Phase 14): a name that changed with the language would break scripts,
links and the system's own re-reads of these files. What follows the
language is the *content* — headings, table headers and labels, translated
through `translate()` (moved to core in this same task, see `i18n.py`).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .classification import reference_number
from .config import ProjectConfig
from .i18n import translate

# Kept in Portuguese on purpose: this is default *content* written into
# `project_instructions.md` for the collection's own Claude Project, not UI
# text — it is not covered by the i18n layer and changing its wording would
# be a content change, not a rename. (Task 11, Phase 14: the file's own
# headings and labels now follow the interface language — see
# `generate_project_instructions_md()` below — but this default role prose
# and `SOURCE_OF_TRUTH_RULE` stay out of scope, same as this comment
# predates.)
DEFAULT_ROLE = (
    "Você é um assistente de pesquisa que ajuda a localizar e resumir peças "
    "deste acervo. Responda com base no índice e na cronologia para "
    "encontrar a peça certa, mas siga sempre a regra inegociável abaixo "
    "antes de citar qualquer valor, data ou conteúdo de tabela."
)

SOURCE_OF_TRUTH_RULE = (
    "**Valor, data e conteúdo de tabela citados numa resposta sempre vêm da "
    "leitura do arquivo original — nunca do índice.** O índice e a "
    "cronologia foram gerados por OCR e por um motor de classificação "
    "automática; ambos podem errar. Servem só para localizar a peça certa "
    "pela referência (`f. N` ou `p. N`) e pelo nome do arquivo de origem. "
    "Antes de citar um número, uma data ou o conteúdo de uma tabela, abra o "
    "arquivo original na pasta de origem, na referência indicada, e "
    "confirme o valor ali."
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _items(conn):
    return conn.execute("SELECT * FROM item ORDER BY group_key, start_order").fetchall()


def _cell(value) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


# Fixed, English, independent of the interface language — see module
# docstring. Shared with `web/app.py` (Result screen listing/preview) and
# `claude_package.py` (Claude Project zip) so the four names live in one
# place.
INDEX_FILENAME = "index.md"
TIMELINE_FILENAME = "timeline.md"
REVIEW_FILENAME = "review.md"
PROJECT_INSTRUCTIONS_FILENAME = "project_instructions.md"


# --- index.md ---------------------------------------------------------


def generate_index_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    items = _items(conn)
    by_group: dict[str, list] = {}
    for item in items:
        by_group.setdefault(item["group_key"], []).append(item)

    lines = [
        f"# {t('artifact.index.title')} — {config.name}",
        "",
        t("artifact.index.generated", timestamp=_now_iso(), count=len(items)),
    ]

    if not items:
        lines += ["", t("artifact.index.empty")]
    else:
        header = (
            f"| {t('artifact.index.table_range')} | {t('artifact.index.table_type')} | "
            f"{t('artifact.index.table_date')} | {t('artifact.index.table_author')} | "
            f"{t('artifact.index.table_confidence')} | {t('artifact.index.table_source')} | "
            f"{t('artifact.index.table_summary')} |"
        )
        for group in sorted(by_group):
            lines += ["", f"## {group}", "", header, "|---|---|---|---|---|---|---|"]
            for item in by_group[group]:
                span = f"{item['start_ref']} – {item['end_ref']}"
                lines.append(
                    "| "
                    + " | ".join(
                        _cell(v)
                        for v in (
                            span,
                            item["type"],
                            item["date"],
                            item["author"],
                            item["confidence"],
                            item["files"],
                            item["summary"],
                        )
                    )
                    + " |"
                )

    path = Path(config.output_folder) / INDEX_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- timeline.md -------------------------------------------------------


def generate_timeline_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    items = [p for p in _items(conn) if p["date"]]
    items.sort(key=lambda p: (p["date"], p["group_key"], p["start_order"]))

    lines = [
        f"# {t('artifact.timeline.title')} — {config.name}",
        "",
        t("artifact.timeline.generated", timestamp=_now_iso(), count=len(items)),
    ]

    if not items:
        lines += ["", t("artifact.timeline.empty")]
    else:
        header = (
            f"| {t('artifact.timeline.table_date')} | {t('artifact.timeline.table_type')} | "
            f"{t('artifact.timeline.table_reference')} | {t('artifact.timeline.table_group')} | "
            f"{t('artifact.timeline.table_source')} | {t('artifact.timeline.table_summary')} |"
        )
        lines += ["", header, "|---|---|---|---|---|---|"]
        for item in items:
            span = f"{item['start_ref']} – {item['end_ref']}"
            lines.append(
                "| "
                + " | ".join(
                    _cell(v)
                    for v in (
                        item["date"], item["type"], span, item["group_key"], item["files"], item["summary"],
                    )
                )
                + " |"
            )

    path = Path(config.output_folder) / TIMELINE_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- review.md --------------------------------------------------------


def _group_ranges(numbers: list[int]) -> list[tuple[int, int]]:
    numbers = sorted(numbers)
    ranges = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))
    return ranges


def _gaps_by_group(conn) -> dict[str, list[tuple[int, int]]]:
    groups = [
        row["group_key"]
        for row in conn.execute(
            "SELECT DISTINCT group_key FROM file WHERE group_key IS NOT NULL AND status = 'extracted'"
        ).fetchall()
    ]

    gaps = {}
    for group in groups:
        pages = conn.execute(
            """
            SELECT page.reference FROM page
            JOIN file ON file.id = page.file_id
            WHERE file.group_key = ?
            """,
            (group,),
        ).fetchall()
        page_orders = sorted({reference_number(p["reference"]) for p in pages})
        if not page_orders:
            continue

        items = conn.execute(
            "SELECT start_order, end_order FROM item WHERE group_key = ?", (group,)
        ).fetchall()
        covered: set[int] = set()
        for item in items:
            covered.update(range(item["start_order"], item["end_order"] + 1))

        missing = sorted(set(page_orders) - covered)
        if missing:
            gaps[group] = _group_ranges(missing)

    return gaps


def generate_review_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    file_counts = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM file GROUP BY status").fetchall()
    }
    window_counts = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM window GROUP BY status").fetchall()
    }
    total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    total_low_confidence_items = conn.execute(
        "SELECT COUNT(*) FROM item WHERE confidence = 'low'"
    ).fetchone()[0]

    failures = conn.execute(
        "SELECT name, relative_path, error FROM file WHERE status = 'failed' ORDER BY relative_path"
    ).fetchall()

    error_events = conn.execute(
        "SELECT step, message, created_at FROM event WHERE level = 'error' ORDER BY id DESC LIMIT 50"
    ).fetchall()

    gaps = _gaps_by_group(conn)

    lines = [
        f"# {t('artifact.review.title')} — {config.name}", "", t("artifact.review.generated", timestamp=_now_iso()),
        "", f"## {t('artifact.review.file_coverage')}",
    ]
    # Statuses are the fixed database/domain codes (`file.status`), not
    # translatable prose — left as-is, same reasoning as the JSON contract
    # keys in `CLAUDE.md` (see `windows_prep.py`).
    for status in ("discovered", "converted", "extracted", "failed", "skipped"):
        lines.append(f"- {status}: {file_counts.get(status, 0)}")

    lines += ["", f"## {t('artifact.review.windows_section')}"]
    lines.append(f"- {t('artifact.review.windows_pending')}: {window_counts.get('pending', 0)}")
    lines.append(f"- {t('artifact.review.windows_done')}: {window_counts.get('done', 0)}")

    lines += ["", f"## {t('artifact.review.items_section')}"]
    lines.append(f"- {t('artifact.review.items_total')}: {total_items}")
    lines.append(f"- {t('artifact.review.items_low_confidence')}: {total_low_confidence_items}")

    lines += ["", f"## {t('artifact.review.gaps_section')}"]
    if not gaps:
        lines.append(t("artifact.review.gaps_none"))
    else:
        for group in sorted(gaps):
            ranges = ", ".join(
                f"{a}-{b}" if a != b else str(a) for a, b in gaps[group]
            )
            lines.append(f"- **{group}**: {t('artifact.review.gaps_missing')} {ranges}")

    lines += ["", f"## {t('artifact.review.failures_section')}"]
    if not failures:
        lines.append(t("artifact.review.failures_none"))
    else:
        for failure in failures:
            lines.append(f"- `{failure['relative_path']}`: {failure['error']}")

    lines += ["", f"## {t('artifact.review.errors_section')}"]
    if not error_events:
        lines.append(t("artifact.review.errors_none"))
    else:
        for event in error_events:
            lines.append(f"- [{event['created_at']}] ({event['step']}) {event['message']}")

    path = Path(config.output_folder) / REVIEW_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- project_instructions.md ------------------------------------------------


def generate_project_instructions_md(conn, config: ProjectConfig, language: str) -> Path:
    t = lambda key, **kw: translate(language, key, **kw)  # noqa: E731
    total_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    total_files = conn.execute(
        "SELECT COUNT(*) FROM file WHERE status IN ('converted', 'extracted')"
    ).fetchone()[0]

    role = config.role_instructions.strip() or DEFAULT_ROLE
    extra_rules = config.extra_rules.strip() or t("artifact.project_instructions.extra_rules_missing")

    lines = [
        f"# {t('artifact.project_instructions.title')} — {config.name}",
        "",
        f"## {t('artifact.project_instructions.role_section')}",
        "",
        role,
        "",
        f"## {t('artifact.project_instructions.about_section')}",
        "",
        config.subject.strip() or t("artifact.project_instructions.subject_missing"),
        "",
        t(
            "artifact.project_instructions.access_line",
            index_file=INDEX_FILENAME, timeline_file=TIMELINE_FILENAME, review_file=REVIEW_FILENAME,
            total_items=total_items, total_files=total_files,
        ),
        "",
        f"## {t('artifact.project_instructions.rule_section')}",
        "",
        SOURCE_OF_TRUTH_RULE,
        "",
        f"## {t('artifact.project_instructions.locate_section')}",
        "",
        "1. " + t(
            "artifact.project_instructions.locate_step1",
            index_file=INDEX_FILENAME, timeline_file=TIMELINE_FILENAME,
        ),
        "2. " + t("artifact.project_instructions.locate_step2"),
        "3. " + t("artifact.project_instructions.locate_step3"),
        "4. " + t("artifact.project_instructions.locate_step4"),
        "",
        f"## {t('artifact.project_instructions.extra_rules_section')}",
        "",
        extra_rules,
    ]

    path = Path(config.output_folder) / PROJECT_INSTRUCTIONS_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def pending_items(conn) -> dict:
    """Summary of what is still missing, for the Result screen (spec section 6)."""
    failures = conn.execute(
        "SELECT name, relative_path, error FROM file WHERE status = 'failed' ORDER BY relative_path"
    ).fetchall()
    windows_pending = conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0]
    return {
        "gaps": _gaps_by_group(conn),
        "failures": [dict(failure) for failure in failures],
        "windows_pending": windows_pending,
    }


def generate_all_artifacts(conn, config: ProjectConfig, language: str) -> dict[str, Path]:
    return {
        "index": generate_index_md(conn, config, language),
        "timeline": generate_timeline_md(conn, config, language),
        "review": generate_review_md(conn, config, language),
        "project_instructions": generate_project_instructions_md(conn, config, language),
    }

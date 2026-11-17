# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Janela, sobreposição, caracteres por página e idioma do OCR, decididos
sozinhos depois da varredura.

Antes da 2.0.0 estes valores eram campos do formulário (com um painel que
propunha números). Nenhum valor serve a todo acervo, mas pedir à pessoa que
escolha "páginas por janela" é pedir o que ela não tem como saber. Agora o
programa olha o que a varredura achou e grava os valores nas mesmas chaves da
configuração, com o motivo num evento.

Quando resolver sai do estado do banco, sem marcador próprio:

- sem páginas e sem janelas: tudo (janela, sobreposição, caracteres, idioma);
- com páginas e sem janelas: só janela e sobreposição (o texto já foi lido
  com os limites antigos, e o idioma do OCR já foi usado);
- com janelas: nunca. Mudar janela ou sobreposição num projeto com janelas
  descartaria os grupos (`log.update.layout_mismatch`).

Lê o inventário da tabela `file` (arquivos ignorados, `status = 'skipped'`,
não contam); só abre uma amostra de PDFs e de textos, como a antiga proposta.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import ProjectConfig
from .events import record_event
from .file_types import category_of_extension
from .i18n import nested
from .settings_proposal import (
    FolderSurvey,
    _count_languages,
    _round_up,
    _survey_pdfs,
    _survey_text_files,
    installed_ocr_languages,
)

SCOPE_ALL = "all"
SCOPE_WINDOWS = "windows"

WINDOW_LOCAL = 8
WINDOW_RULES = 16
MIN_CHARS = 1500
MAX_CHARS = 4000
# Abaixo desta fatia de páginas de PDF e imagem o acervo é, na prática, de
# documentos inteiros e a sobreposição só repete páginas: não há peça partida
# na borda de duas janelas.
_MULTI_PAGE_SHARE_FOR_OVERLAP = 0.05
_MULTI_PAGE_CATEGORIES = ("pdf", "imagens")


@dataclass
class AutoSettings:
    scope: str
    pages_per_window: int
    overlap: int
    engine: str
    chars_per_page: int | None = None  # None: nada a amostrar, o valor em vigor ficou
    ocr_language: str | None = None
    reasons: dict[str, str] = field(default_factory=dict)


# --- estado do banco ----------------------------------------------------------


def resolution_scope(conn: sqlite3.Connection) -> str | None:
    """O que ainda pode ser resolvido neste projeto, ou `None` (com janelas)."""
    if conn.execute("SELECT 1 FROM window LIMIT 1").fetchone() is not None:
        return None
    if conn.execute("SELECT 1 FROM page LIMIT 1").fetchone() is not None:
        return SCOPE_WINDOWS
    return SCOPE_ALL


def _inventory(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """`(caminho relativo, categoria)` dos arquivos que entram no índice.
    Extensão sem categoria (regra "todos") é lida como texto."""
    rows = conn.execute(
        "SELECT relative_path, extension FROM file WHERE status != 'skipped'"
    ).fetchall()
    return [
        (row["relative_path"], category_of_extension("." + (row["extension"] or "")) or "text")
        for row in rows
    ]


# --- regras -------------------------------------------------------------------


def window_for_engine(engine: str) -> int:
    return WINDOW_LOCAL if engine == "local" else WINDOW_RULES


def overlap_for(window: int, multi_page_share: float) -> int:
    if multi_page_share < _MULTI_PAGE_SHARE_FOR_OVERLAP:
        return 0
    return 2 if window >= 8 else 1


def chars_from_page_lengths(lengths: list[int]) -> int | None:
    """Percentil 75 do texto das páginas, arredondado a 500, entre 1500 e
    4000. `None` sem nenhuma página com texto."""
    if not lengths:
        return None
    ordered = sorted(lengths)
    p75 = ordered[int(0.75 * (len(ordered) - 1))]
    return max(MIN_CHARS, min(MAX_CHARS, _round_up(p75, 500)))


def _effective_engine(conn: sqlite3.Connection, config: ProjectConfig, language: str | None) -> str:
    """O motor que a classificação escolheria agora. Se não der para
    descobrir (Ollama fora do ar na varredura, por exemplo), vale o motor
    configurado: `automatic` conta como local só com modelo instalado."""
    try:
        from .orchestrator import resolve_effective_engine

        return resolve_effective_engine(conn, config, language=language)
    except Exception:
        if config.classification_engine in ("local", "rules"):
            return config.classification_engine
        try:
            from .web.ollama_models import list_installed_models

            return "local" if list_installed_models() else "rules"
        except Exception:
            return "rules"


def _language_from_survey(survey: FolderSurvey) -> str | None:
    """Idioma do OCR pela detecção atual (palavras frequentes). A detecção
    por documento é da Tarefa 12; aqui só o último recurso do acervo."""
    counts: Counter = survey.language_counts
    total = sum(counts.values())
    if not total:
        return None
    ranked = [code for code, _ in counts.most_common() if counts[code] / total >= 0.25][:2]
    installed = installed_ocr_languages()
    ranked = [code for code in ranked if installed is None or code in installed]
    return "+".join(ranked) if ranked else None


# --- resolução ----------------------------------------------------------------


def _page_share(conn: sqlite3.Connection) -> float | None:
    """Fatia das páginas que vem de PDF e imagem, contada nas páginas já
    gravadas. `None` sem nenhuma página."""
    rows = conn.execute(
        "SELECT f.extension AS extension, COUNT(*) AS pages FROM page p JOIN file f ON f.id = p.file_id"
        " WHERE f.status != 'skipped' GROUP BY f.extension"
    ).fetchall()
    total = sum(row["pages"] for row in rows)
    if not total:
        return None
    multi = sum(
        row["pages"] for row in rows
        if category_of_extension("." + (row["extension"] or "")) in _MULTI_PAGE_CATEGORIES
    )
    return multi / total


def decide(
    conn: sqlite3.Connection, config: ProjectConfig, scope: str, engine: str
) -> AutoSettings | None:
    inventory = _inventory(conn)
    if not inventory:
        return None  # nada achado na varredura: sem base para decidir

    # Antes de ler qualquer página, a fatia de PDF e imagem sai de uma amostra
    # de PDFs (quantas páginas costumam ter); com as páginas gravadas, é
    # contada.
    survey = FolderSurvey()
    survey.by_category.update(category for _path, category in inventory)
    share: float | None = None
    if scope == SCOPE_ALL:
        source = Path(config.source_folder)
        found: dict[str, list[Path]] = {}
        for relative_path, category in inventory:
            found.setdefault(category, []).append(source / relative_path)
        try:
            texts = _survey_pdfs(found.get("pdf", []), survey) + _survey_text_files(found)
            _count_languages(texts, survey)
            share = survey.multi_page_share()
        except Exception:
            survey = None  # amostra falhou: janela e sobreposição bastam
    else:
        share = _page_share(conn)
    if share is None:  # sem amostra nem páginas: pelo número de arquivos
        multi = sum(1 for _path, category in inventory if category in _MULTI_PAGE_CATEGORIES)
        share = multi / len(inventory)

    window = window_for_engine(engine)
    overlap = overlap_for(window, share)
    decision = AutoSettings(scope=scope, pages_per_window=window, overlap=overlap, engine=engine)
    decision.reasons["window"] = "auto.reason.window_local" if engine == "local" else "auto.reason.window_rules"
    decision.reasons["overlap"] = (
        "auto.reason.overlap_zero" if overlap == 0 else "auto.reason.overlap_repeat"
    )
    if scope != SCOPE_ALL or survey is None:
        return decision

    chars = chars_from_page_lengths(survey.native_page_chars)
    if chars is not None:
        decision.chars_per_page = chars
        decision.reasons["chars_per_page"] = "auto.reason.chars_pdf"
    language = _language_from_survey(survey)
    if language is not None:
        decision.ocr_language = language
        decision.reasons["ocr_language"] = "auto.reason.ocr_detected"
    return decision


def _save(conn: sqlite3.Connection, values: dict) -> None:
    """Grava só estas chaves na primeira linha de `project` (a que
    `load_project` lê). Relê o JSON do banco: a configuração em memória pode
    ter minutos de idade (a varredura de um Drive grande é longa) e outra
    tela pode ter gravado outra chave nesse intervalo."""
    row = conn.execute("SELECT id, config_json FROM project ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return
    data = json.loads(row["config_json"])
    data.update(values)
    conn.execute(
        "UPDATE project SET config_json = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), row["id"])
    )
    conn.commit()


def resolve_auto_settings(
    conn: sqlite3.Connection, config: ProjectConfig, language: str | None = None, engine: str | None = None
) -> AutoSettings | None:
    """Resolve e grava o que o estado do banco permite. Devolve a decisão
    (para os testes e para quem queira mostrá-la) ou `None` quando nada foi
    mudado. Só o banco muda: a `config` recebida fica como está, e a etapa
    seguinte recarrega a configuração dele (`TaskManager.start_step`)."""
    scope = resolution_scope(conn)
    if scope is None:
        return None
    decision = decide(conn, config, scope, engine or _effective_engine(conn, config, language))
    if decision is None:
        return None

    values = {"pages_per_window": decision.pages_per_window, "overlap": decision.overlap}
    if decision.chars_per_page is not None:
        values["chars_per_page"] = decision.chars_per_page
    if decision.ocr_language is not None:
        values["ocr_language"] = decision.ocr_language
    _save(conn, values)

    record_event(
        conn, "scan", "info", "log.settings.window",
        {
            "value": decision.pages_per_window, "overlap": decision.overlap,
            "window_reason": nested(decision.reasons["window"]),
            "overlap_reason": nested(decision.reasons["overlap"], value=decision.overlap),
        },
        language=language,
    )
    if decision.chars_per_page is not None:
        record_event(
            conn, "scan", "info", "log.settings.chars_per_page",
            {"value": decision.chars_per_page, "reason": nested(decision.reasons["chars_per_page"])},
            language=language,
        )
    if decision.ocr_language is not None:
        record_event(
            conn, "scan", "info", "log.settings.ocr_language",
            {"value": decision.ocr_language, "reason": nested(decision.reasons["ocr_language"])},
            language=language,
        )
    return decision

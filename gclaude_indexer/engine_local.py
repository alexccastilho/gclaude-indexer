# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""`local` engine (spec section 5, step 6) — open model served by Ollama at
`http://127.0.0.1:11434`. No account, no API key, no external network: the
host is fixed to loopback and never comes from external configuration. A
connection failure falls back to the `rules` engine, with a warning — it
never brings the run down.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from .classification import (
    STOP_CLASSIFYING, WindowItems, WindowPage, WindowRunCounts, ClassifiedItem, classify_windows,
    page_order, starts_new_document, normalize_type,
    FALLBACK_SUMMARY_CHARS, SUMMARY_CHAR_LIMIT, coverage_items, item_for_pages,
)
from .config import ProjectConfig
from .engine_names import ENGINE_LOCAL
from .file_types import PAGED_CATEGORIES, category_of_extension
from .events import record_event
from .i18n import nested
from .item_normalize import BLANK_PAGE_TYPE
from .engine_rules import RulesEngine, load_rules
from .gpu_budget import server_environment
from .html_text import STRUCK_MARK
from . import fulltext, hardware, local_models, ollama_backend, ollama_models
from .ollama_backend import OLLAMA_SERVE_LOG_NAME
from .subprocess_utils import start_in_background
from . import language_detect, planalto
from .file_status import WINDOW_PENDING
from . import raw_items
from .paths import machine_local_folder
from .tools import find as find_tool

# Was 120. A full window in the per-page mode answers ~1,800
# tokens; on a 6 GB laptop card running hot (84 °C) that took
# 40 s on average and past 120 s on the heavy ones, which then timed out,
# restarted Ollama and started the same window over. This is a hang
# detector, not a pace target.
GENERATION_TIMEOUT_S = 300
PING_TIMEOUT_S = 5
# Explicit user request: when Ollama does not respond, try to restart the
# server on our own before giving up and falling back to the 'rules' engine.
OLLAMA_RESTART_ATTEMPTS = 3
WAIT_BETWEEN_ATTEMPTS_S = 4.0


class OllamaConnectionError(Exception):
    """Ollama did not respond on 127.0.0.1:11434 — reason to fall back to
    the `rules` engine, never to bring the run down."""


class ModelAnswerError(Exception):
    """Ollama is up and answered, but with an error about *this* prompt,
e.g. "prediction aborted, token repeat limit reached" when the
    model loops on garbled text. Not an outage: restarting Ollama or sending
    the same window again gets the same answer. The window is split instead
    (`_classify_in_parts`)."""


# Words every "prompt too long" error from Ollama carries. Strings found in
# the 0.40.13 binary: "the input length exceeds the context length", "input
# exceeds maximum context length and cannot be truncated further", "exceeds
# the model's maximum context length", and the one measured here
# with `truncate: false` at `num_ctx` 4096 — HTTP 400, `request
# (10289 tokens) exceeds the available context size (4096 tokens), try
# increasing it`. Any other error about the prompt stays a
# `ModelAnswerError`.
_PROMPT_TOO_LONG_MARKERS = ("exceed", "context")
_PROMPT_TOKENS_IN_ERROR = re.compile(r"\((\d+) tokens\)")


class PromptTooLongError(ModelAnswerError):
    """Ollama refused the prompt because it does not fit `num_ctx` (fase 36:
    the request carries `truncate: false`, so a window that does not fit is
    refused instead of cut to half in silence). `tokens` is the prompt's
    real size when the error text says it (0.40.13 does), else 0. Handled
    inside `_classify_pages`: the context grows, then the window splits —
    never `_classify_in_parts` straight away."""

    def __init__(self, message: str):
        super().__init__(message)
        found = _PROMPT_TOKENS_IN_ERROR.search(message or "")
        self.tokens = int(found.group(1)) if found else 0


def _try_restart_ollama(
    conn: sqlite3.Connection, local_engine: "LocalEngine", language: str | None = None
) -> bool:
    """Explicit user request: before giving up on the 'local' engine because
    Ollama is not responding, check why and try to restart the server on our
    own, up to `OLLAMA_RESTART_ATTEMPTS` times. Returns `True` if Ollama
    started responding again."""
    ollama_path = find_tool("ollama")
    if not ollama_path:
        record_event(conn, "classification", "warning", "log.local_engine.ollama_binary_missing", language=language)
        return False

    record_event(
        conn, "classification", "warning", "log.local_engine.restarting",
        {"url": local_engine.url_base, "path": ollama_path, "attempts": OLLAMA_RESTART_ATTEMPTS},
        language=language,
    )

    for attempt in range(1, OLLAMA_RESTART_ATTEMPTS + 1):
        try:
            # With the VRAM settings applied: Ollama reads them once, at
            # server startup, so a server we bring up ourselves is the one
            # chance to set them from here (`install.ps1` writes the same
            # values as user environment variables, for the server Windows
            # starts on its own).
            start_in_background(
                [ollama_path, "serve"], env=server_environment(),
                log_path=machine_local_folder() / OLLAMA_SERVE_LOG_NAME,
            )
        except OSError as exc:
            record_event(
                conn, "classification", "warning", "log.local_engine.restart_attempt_failed_to_start",
                {"attempt": attempt, "total": OLLAMA_RESTART_ATTEMPTS, "error": str(exc)},
                language=language,
            )
            continue

        time.sleep(WAIT_BETWEEN_ATTEMPTS_S)

        if local_engine.is_available():
            record_event(
                conn, "classification", "info", "log.local_engine.restart_succeeded",
                {"attempt": attempt, "total": OLLAMA_RESTART_ATTEMPTS}, language=language,
            )
            return True

        record_event(
            conn, "classification", "warning", "log.local_engine.restart_attempt_timed_out",
            {"attempt": attempt, "total": OLLAMA_RESTART_ATTEMPTS}, language=language,
        )

    record_event(
        conn, "classification", "warning", "log.local_engine.restart_gave_up",
        {"attempts": OLLAMA_RESTART_ATTEMPTS}, language=language,
    )
    return False


def _num_gpu_for(processing_mode: str) -> int:
    """Value of Ollama's `options.num_gpu` according to the processing mode
    chosen by the user in the project (the "Processamento" field, explicit
    request): -1 uses as much GPU as possible and overflows the rest to RAM
    (default and "gpu" mode); 0 forces CPU/RAM, even with a GPU available.

    `-1` is the *starting point*, not the final value: on the GPU path
    `LocalEngine` replaces it with a measured layer count when it can read
    the card and the model (see `gpu_budget.py`), because `-1` leaves the
    decision to Ollama's deliberately conservative scheduler and measurably
    leaves VRAM unused.
    """
    return 0 if processing_mode == "cpu" else -1


# Characters per token, for sizing the context window. Deliberately low
# (real ratios for Portuguese prose run nearer 4): overestimating the token
# count costs a slightly larger context, while underestimating it silently
# truncates the window and the model classifies a document whose end it
# never saw.
_CHARS_PER_TOKEN = 3.0

# Piso da calibração. Uma razão abaixo disto não descreve texto nenhum —
# é resposta corrompida ou telemetria absurda — e aceitá-la infla o
# contexto de todas as janelas seguintes, já que ele só cresce.
_CHARS_PER_TOKEN_FLOOR = 1.2

# Folga para reconhecer a assinatura do truncamento. O Ollama 0.34 corta o
# prompt em exatamente metade do `num_ctx`, medido em 1026/2048,
# 1538/3072 e 2050/4096 — sempre dois tokens acima da metade exata. 64 é
# folga larga para uma assinatura que vem com erro de 2.
_TRUNCATION_TOLERANCE = 64

# Fase 36: with `truncate: false` a current Ollama refuses an oversize
# prompt, so a server that still cuts is an old one — and on it the
# signature alone is treated as a failed attempt. To keep an honest prompt
# that merely lands near `num_ctx / 2` from paying a whole attempt, the
# signature only counts when the calibrated estimate of the prompt is at
# least this many times what the model read: a real cut leaves the read
# part at half the prompt or less, so the ratio is ≥ 1.4 even with the
# estimate 30% optimistic, while an honest prompt sits between 0.8 and 1.3.
_TRUNCATION_RATIO = 1.35

# Room for the model's own answer on top of the prompt.
#
# 1024 was sized for the ranges mode, whose reply is a handful of items. The
# per-page mode answers with one object per page — nine fields each — and on
# an 8-page window that runs past this budget. When it does, the JSON is cut
# off mid-object and every page after the cut disappears from the answer.
#
# Measured on the 31-page report, and the correlation is the whole story:
#
#   granite4.2:8b   0 windows short of pages -> 100% of items typed
#   qwen3:8b        2 windows short          ->  50% typed
#   qwen3.5:4b      4 windows short          ->  16% typed
#
# It reads like the smaller models being worse at the task. They were being
# cut off. `_response_tokens_for` sizes the budget by what is actually being
# asked for.
_RESPONSE_TOKENS = 1024

# Per page, in the per-page mode: nine short fields plus JSON punctuation,
# with room for a two-sentence `detail`. Measured at 90-130 tokens on real
# answers; 220 leaves the margin that matters, since running out truncates
# and losing a page is the one outcome this system must not have.
_RESPONSE_TOKENS_PER_PAGE = 220


def _response_tokens_for(page_count: int = 0) -> int:
    """Tokens to reserve for the answer: one budget per page described,
    never below `_RESPONSE_TOKENS`."""
    return max(_RESPONSE_TOKENS, page_count * _RESPONSE_TOKENS_PER_PAGE)

# Context sizes are rounded up to a multiple of this — a stable value
# across windows of slightly different lengths means Ollama keeps one
# loaded model instead of reloading it whenever the prompt grows by a
# sentence.
_CONTEXT_GRANULARITY = 1024

# Ollama's own default when `num_ctx` is not sent. A prompt longer than
# this is silently truncated, which is why the context is now computed and
# sent explicitly instead of left out.
_OLLAMA_DEFAULT_CONTEXT = 4096


def _looks_truncated(generation: "Generation", estimated_prompt_tokens: int = 0) -> bool:
    """Se o Ollama cortou este prompt. Com `estimated_prompt_tokens` (a
    estimativa calibrada do prompt enviado), a assinatura só vale quando a
    estimativa é ≥ `_TRUNCATION_RATIO` vezes o lido — ver a constante.

    Comportamento observado, não documentado: quando o prompt não cabe, o
    Ollama o trunca para metade do contexto pedido. É comportamento interno
    e pode mudar de versão — por isso ele NUNCA decide sozinho se a janela
    falhou (esse critério é o número de linhas devolvidas, em
    `_classify_pages`). Serve para escolher o próximo `num_ctx` e para
    descartar uma calibração que ensinaria a razão errada.
    """
    if not generation.context or not generation.prompt_tokens:
        return False
    if abs(generation.prompt_tokens - generation.context / 2) > _TRUNCATION_TOLERANCE:
        return False
    if estimated_prompt_tokens > 0:
        return estimated_prompt_tokens >= _TRUNCATION_RATIO * generation.prompt_tokens
    return True


def context_tokens_for(
    prompt: str,
    model_limit: int = 0,
    page_count: int = 0,
    chars_per_token: float = _CHARS_PER_TOKEN,
) -> int:
    """Context size to request for `prompt`.

    Never below Ollama's own default, so this can only ever widen the
    window, never narrow it; never above what the model itself supports,
    when that is known.

    `page_count` is the number of pages the answer has to describe, in the
    per-page mode — the reply grows with it, and a budget that does not
    grow along truncates the answer (see `_RESPONSE_TOKENS_PER_PAGE`).
    """
    estimated = int(len(prompt) / chars_per_token) + _response_tokens_for(page_count)
    rounded = -(-estimated // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
    wanted = max(_OLLAMA_DEFAULT_CONTEXT, rounded)
    if model_limit and model_limit > 0:
        wanted = min(wanted, model_limit)
    return wanted


@dataclass
class Generation:
    """O que uma chamada ao Ollama devolveu, com a telemetria junto.

    `prompt_tokens` é `prompt_eval_count`: quantos tokens do prompt o
    modelo realmente leu, contados pelo tokenizador dele. Quando é menor
    que o prompt enviado, o prompt foi cortado — e essa é a única forma de
    saber, já que o Ollama trunca em silêncio e a versão 0.34 não expõe
    endpoint de tokenização.
    """

    text: str
    prompt_tokens: int = 0
    response_tokens: int = 0
    context: int = 0


@dataclass
class LocalEngine:
    model: str
    # A factory, not a plain default: a dataclass default is bound when the
    # class is defined, and the test suite replaces `OLLAMA_BASE_URL` with a
    # closed port so that no test ever reaches the Ollama of the machine it
    # runs on (fase 37). In production the two are the same value.
    url_base: str = field(default_factory=lambda: ollama_models.OLLAMA_BASE_URL)
    timeout: int = GENERATION_TIMEOUT_S
    num_gpu: int = -1
    # Explicit context size. `None` means "let Ollama use its default",
    # which is 4096 tokens and silently truncates a longer window —
    # `plan_gpu_use()` computes a real value from the prompt on the first
    # call.
    num_ctx: int | None = None
    # The project, so the prompt can say what this collection *is*. Kept
    # optional: `LocalEngine` is constructed directly in several tests, and
    # a missing config simply means the prompt has no context block — the
    # exact behaviour this class had before `build_context` existed.
    config: "ProjectConfig | None" = None
    # 2.1.0: the per-page answer is constrained by a JSON Schema (`format`
    # with a schema, not just "json"): exactly one object per page, `n` an
    # integer within the window, booleans that are booleans. The model can
    # no longer copy the page into `n`, close the JSON early or skip pages,
    # the failures that used to cost a second request or a split window.
    structured_output: bool = True
    # Warnings from the last call to `classify()` — pages the model's answer
    # left out. `classify_pending`
    # reads this right after calling `classify()` to record an event; it is
    # not part of the common `ClassificationEngine` interface (only
    # `LocalEngine` exposes it). Each entry is (i18n key, params) — Task 12
    # — rendered by `_log_rejection_warnings`, not pre-rendered
    # text, so the final log event follows the interface's language.
    last_window_warnings: list[tuple[str, dict]] = field(default_factory=list)
    # Fase 36: what happened to the last window's context — raised to fit
    # it whole, or split by size before/after asking — as (i18n key,
    # params), at `info` level. Same contract as `last_window_warnings`;
    # `classify_pending` turns them into events and counts them.
    last_window_notes: list[tuple[str, dict]] = field(default_factory=list)
    # Filled by `plan_gpu_use()` on the first window and reused after that:
    # the measurement costs two HTTP calls plus a performance counter read,
    # and neither the card's capacity nor the model changes during a run.
    gpu_plan: dict | None = field(default=None, repr=False)
    _planned: bool = field(default=False, repr=False)
    # A razão caracteres/token deste acervo, aprendida durante a corrida.
    # `_CHARS_PER_TOKEN` é só a semente da primeira janela, quando ainda não
    # há medição. Guardamos o MÍNIMO observado, e não a média, pela mesma
    # assimetria que justificava a constante: superestimar custa um pouco de
    # VRAM, subestimar custa a janela inteira.
    _chars_per_token: float = field(default=_CHARS_PER_TOKEN, repr=False)
    # Maior `num_ctx` que a placa (ou a RAM, sem placa) comporta com o
    # modelo inteiro. Medido uma vez por corrida (`gpu_budget.
    # measure_context_ceiling`); `ceiling_details` é o que entrou na conta,
    # para o log.
    context_ceiling: int = field(default=0, repr=False)
    ceiling_details: dict = field(default_factory=dict, repr=False)
    # 2.0.0: de onde sai o texto inteiro de uma página (o índice de busca
    # guarda o que a janela cortou). Preenchido por `classify_pending`; sem
    # ele o motor se comporta como antes.
    page_text: "Callable[[WindowPage], str] | None" = field(default=None, repr=False)
    # Contadores da segunda tentativa (ver `_second_attempts`): pedidos
    # normais, pedidos extras e o que cada tipo de segunda tentativa tratou.
    # O teto de pedidos extras é `EXTRA_REQUEST_SHARE` dos normais.
    base_requests: int = field(default=0, repr=False)
    extra_requests: int = field(default=0, repr=False)
    second_missing: int = field(default=0, repr=False)
    second_untyped: int = field(default=0, repr=False)
    second_capped: int = field(default=0, repr=False)
    # Páginas que já tiveram a sua tentativa extra (no máximo uma por
    # página, mesmo que ela apareça em duas janelas sobrepostas).
    _retried: set = field(default_factory=set, repr=False)
    _window_pages: list = field(default_factory=list, repr=False)
    # O último pedido foi recusado por tamanho: reler a página com vizinhas
    # só aumentaria o prompt que já não coube.
    _last_refused: bool = field(default=False, repr=False)

    def _measure_ceiling(self) -> int:
        """O maior contexto que ainda cabe na placa com o modelo inteiro.

        Uma janela que precise de mais que isto é subdividida, e não
        empurrada para a RAM: um acervo grande tem centenas de janelas, e
        uma janela seis vezes mais lenta multiplicada por algumas centenas
        custa horas.

        Fase 36: calculado da VRAM livre e do custo do KV por token, em vez
        da lista fixa que parava em 16384. Numa rodada num acervo grande
        (RX 6000 (12 GB)) o teto fixo deixava gigabytes da placa parados enquanto
        parte dos pedidos era cortada pelo Ollama; a mesma conta dá 131072
        nessa placa, e as janelas de 20 a 26 mil tokens cabem inteiras. Em modo "cpu" o teto vem
        da RAM (`use_gpu=False`).
        """
        if self.context_ceiling:
            return self.context_ceiling
        from . import gpu_budget

        try:
            teto, detalhes = gpu_budget.measure_context_ceiling(
                self.model, self.url_base, use_gpu=self.num_gpu != 0
            )
        except Exception:
            teto, detalhes = _OLLAMA_DEFAULT_CONTEXT, {"source": "none", "reason": "erro"}
        self.context_ceiling = int(teto) or _OLLAMA_DEFAULT_CONTEXT
        self.ceiling_details = dict(detalhes or {})
        return self.context_ceiling

    def _calibrate(self, prompt: str, generation: "Generation") -> None:
        """Aprende a razão caracteres/token com o que o modelo acabou de ler.

        Só vale para a chamada íntegra: num prompt truncado,
        `prompt_eval_count` conta o pedaço que sobrou, e a razão calculada
        sobre o prompt inteiro sairia otimista — exatamente o erro que se
        quer corrigir.
        """
        if not generation.prompt_tokens or _looks_truncated(generation):
            return
        observada = len(prompt) / generation.prompt_tokens
        self._chars_per_token = max(
            _CHARS_PER_TOKEN_FLOOR, min(self._chars_per_token, observada)
        )

    def plan_gpu_use(self, prompt: str, page_count: int = 0, minimum: int = 0) -> dict | None:
        """Replaces `num_gpu = -1` with a measured layer count.

        Runs on the first window and again whenever a later window needs
        more context than the one measured so far. Returns the details of
        the decision (for the log) or `None` when nothing could be measured
        and the previous behaviour stands.

        It used to run exactly once, sizing the whole run by the first
        window. A denser window further in then overflowed the context the
        first one had asked for, Ollama truncated the answer, the JSON came
        back unclosed and the parser got zero rows — the window reached the
        index with no classification at all, in a noticeable share of the
        windows of a large run.

        The context only ever grows. A `num_ctx` that oscillates makes
        Ollama reload the model between windows, which is what the single
        measurement was avoiding in the first place.

        In "cpu" mode (`num_gpu == 0`) the layer count is never measured —
        that is the user asking for the CPU on purpose — but `num_ctx` is
        still sized here (fase 36): until then this path returned before
        setting it, the request went out without `num_ctx`, and Ollama's
        4096 default cut every full window in silence. The ceiling on
        that path comes from the RAM (`measure_context_ceiling(use_gpu=
        False)`).
        """
        context = context_tokens_for(
            prompt, page_count=page_count, chars_per_token=self._chars_per_token
        )
        context = max(context, minimum)
        teto = self._measure_ceiling()
        if teto:
            context = min(context, teto)
        if self.num_gpu == 0:
            if context > (self.num_ctx or 0):
                self.num_ctx = context
            return self.gpu_plan
        if self._planned and context <= (self.num_ctx or 0):
            return self.gpu_plan
        self._planned = True

        try:
            from .gpu_budget import plan

            layers, details = plan(self.model, self.url_base, context)
        except Exception:
            # A measurement that fails must cost nothing: the run carries
            # on with `-1`, exactly as it did before this existed.
            return None

        self.num_ctx = context
        if layers is not None:
            self.num_gpu = layers
        details["context_ceiling"] = teto
        self.gpu_plan = details
        return details

    def classify_per_page(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        """Uma linha por página, agrupadas em peças pelo código.

        A cobertura sai garantida por construção: `_group_pages_into_items`
        percorre as páginas da janela, não as linhas que o modelo devolveu,
        então uma página que ele esqueceu entra no índice de qualquer
        forma — com o que se souber dela.
        """
        self.last_window_warnings = []
        self.last_window_notes = []
        self._window_pages = list(pages)
        return self._classify_pages(pages)

    def _classify_pages(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        """A janela inteira primeiro; o contexto sobe até ela caber; só
        então ela é dividida.

        Fase 36, numa rodada num acervo grande: parte dos pedidos eram
        janelas de 20–26 mil tokens num `num_ctx` de 16384. O Ollama as cortava pela
        metade em silêncio, o modelo respondia sobre meia janela, a guarda
        `linhas < páginas` dividia — e cada uma tinha pago ~70 s por uma
        tentativa que não podia dar certo. Agora: (1) se a estimativa
        calibrada já passa do teto, a janela é dividida antes de qualquer
        pedido; (2) o pedido leva `truncate: false`, e a recusa do Ollama
        (ou, num servidor antigo, a assinatura do corte) é falha da
        tentativa, nunca resposta aceita; (3) a falha sobe o `num_ctx` até
        o necessário e repete a janela inteira; (4) só quando nem o teto
        basta ela é dividida. O gatilho final continua `linhas < páginas`.
        """
        prompt = _build_page_prompt(pages, self.config)
        total = len(pages)
        teto = self._measure_ceiling()
        precisa = context_tokens_for(prompt, page_count=total, chars_per_token=self._chars_per_token)
        if teto and precisa > teto and total > 1:
            self.last_window_notes.append((
                "log.local_engine.window_split_for_size",
                {"pages": total, "needed": precisa, "ceiling": teto},
            ))
            meio = total // 2
            return self._classify_pages(pages[:meio]) + self._classify_pages(pages[meio:])

        self.plan_gpu_use(prompt, page_count=total)
        rows, alvo = self._attempt(prompt, total)

        # `alvo` above the ceiling is an exact count (the server said how
        # many tokens the prompt has): no context this machine allows holds
        # the window, and raising `num_ctx` to the ceiling would only reload
        # the model to receive the same refusal — and leave a "context
        # raised" note with nothing read (revisão da fase 36). A guess
        # (`_context_needed`) never exceeds the ceiling, so it still raises.
        if len(rows) < total and alvo > (self.num_ctx or 0) and not (teto and alvo > teto):
            self.plan_gpu_use(prompt, page_count=total, minimum=alvo)
            self.last_window_notes.append((
                "log.local_engine.window_context_raised", {"context": self.num_ctx},
            ))
            novas, _alvo = self._attempt(prompt, total)
            if len(novas) > len(rows):
                rows = novas

        # Ainda faltando e há o que dividir: duas janelas menores cabem
        # onde uma não coube. As PEÇAS são concatenadas, e não as linhas —
        # cada metade numera as suas páginas de 1 a N.
        if len(rows) < total and total > 1:
            if teto and alvo >= teto:
                self.last_window_notes.append((
                    "log.local_engine.window_split_for_size",
                    {"pages": total, "needed": alvo, "ceiling": teto},
                ))
            meio = total // 2
            return self._classify_pages(pages[:meio]) + self._classify_pages(pages[meio:])

        rows = self._second_attempts(pages, rows)
        faltantes = max(0, len(pages) - len(_rows_by_index(rows, len(pages))))
        if faltantes:
            # Não é motivo para recusar nada — o agrupamento cobre a página
            # de qualquer modo. É registrado porque distingue um modelo que
            # respondeu sobre tudo de um que respondeu sobre metade.
            self.last_window_warnings.append((
                "log.local_engine.pages_missing_from_answer",
                {"missing": faltantes, "total": len(pages)},
            ))
        return _group_pages_into_items(pages, rows)

    def _extra_allowed(self) -> bool:
        """Se mais um pedido extra cabe no teto de `EXTRA_REQUEST_SHARE`
        dos pedidos normais já feitos nesta execução. Contado em pedidos,
        não em páginas: é o que custa tempo."""
        return (self.extra_requests + 1) <= EXTRA_REQUEST_SHARE * self.base_requests

    def _second_attempts(self, pages: list[WindowPage], rows: list[dict]) -> list[dict]:
        """A segunda tentativa, na mesma passada (2.0.0; substitui a antiga
        revisão da confiança baixa, que era uma segunda passada inteira).

        Duas situações, cada uma com no máximo um pedido extra por trecho e
        uma tentativa extra por página:

        1. página sem resposta depois de tudo (`_classify_pages` já subiu o
           contexto e dividiu o trecho): novo pedido só com elas e uma
           página vizinha de cada lado, com uma nota de que a anterior
           não trouxe resposta;
        2. página que abre uma peça respondida sem tipo: novo pedido com o
           texto inteiro dela (o índice de busca guarda o que o limite de
           caracteres cortou), se esse texto for maior que o da janela.

        O teto é de `EXTRA_REQUEST_SHARE` de pedidos a mais por execução; o
        que não coube fica contado (`second_capped`) e entra como estava."""
        por_indice = _rows_by_index(rows, len(pages))
        if len(por_indice) < len(pages):
            por_indice = self._retry_missing(pages, por_indice)
        if self.page_text is not None:
            por_indice = self._retry_untyped(pages, por_indice)
        return [dict(row, n=indice + 1) for indice, row in sorted(por_indice.items())]

    def _retry_key(self, page: WindowPage) -> tuple:
        return (page.file_id, page.reference, page.file_name)

    def _retry_missing(self, pages: list[WindowPage], por_indice: dict[int, dict]) -> dict[int, dict]:
        janela = self._window_pages or pages
        posicao = {id(page): lugar for lugar, page in enumerate(janela)}
        faltantes = [
            indice for indice in range(len(pages))
            if indice not in por_indice and self._retry_key(pages[indice]) not in self._retried
        ]
        if not faltantes or self._last_refused or any(id(pages[i]) not in posicao for i in faltantes):
            return por_indice
        if not self._extra_allowed():
            self.second_capped += len(faltantes)
            return por_indice

        lugares: set[int] = set()
        for indice in faltantes:
            centro = posicao[id(pages[indice])]
            lugares.update(lugar for lugar in (centro - 1, centro, centro + 1) if 0 <= lugar < len(janela))
        escolhidas = [janela[lugar] for lugar in sorted(lugares)]
        for indice in faltantes:
            self._retried.add(self._retry_key(pages[indice]))
        prompt = _build_page_prompt(
            escolhidas, self.config, note=_RETRY_MISSING_NOTE.format(count=len(escolhidas))
        )
        novas = self._extra_attempt(prompt, escolhidas)
        if novas is None:
            return por_indice
        self.second_missing += len(faltantes)
        por_novas = _rows_by_index(novas, len(escolhidas))
        lugar_na_nova = {id(page): numero for numero, page in enumerate(escolhidas)}
        for indice in faltantes:
            linha = por_novas.get(lugar_na_nova[id(pages[indice])])
            if linha:
                por_indice[indice] = linha
        return por_indice

    def _retry_untyped(self, pages: list[WindowPage], por_indice: dict[int, dict]) -> dict[int, dict]:
        linhas = [dict(row, n=indice + 1) for indice, row in sorted(por_indice.items())]
        ordem_para_indice = {page_order(page): indice for indice, page in enumerate(pages)}
        candidatas: list[tuple[int, str]] = []
        for item in _group_pages_into_items(pages, linhas):
            indice = ordem_para_indice.get(item.start_order)
            if indice is None or indice not in por_indice or normalize_type(item.type):
                continue
            page = pages[indice]
            if self._retry_key(page) in self._retried:
                continue
            try:
                inteiro = (self.page_text(page) or "").strip()
            except Exception:
                inteiro = ""
            # Sem texto a mais do que a janela já tinha, o mesmo pedido daria
            # a mesma resposta: não gasta o teto.
            if len(inteiro) <= len(page.text.strip()) * 1.1:
                continue
            candidatas.append((indice, inteiro[:_FULL_PAGE_CHARS]))
        if not candidatas:
            return por_indice
        if not self._extra_allowed():
            self.second_capped += len(candidatas)
            return por_indice

        escolhidas: list[tuple[int, str]] = []
        tamanho = 0
        for indice, texto in candidatas:
            if escolhidas and tamanho + len(texto) > _RETRY_PROMPT_CHARS:
                break
            escolhidas.append((indice, texto))
            tamanho += len(texto)
        paginas = [replace(pages[indice], text=texto) for indice, texto in escolhidas]
        for indice, _texto in escolhidas:
            self._retried.add(self._retry_key(pages[indice]))
        prompt = _build_page_prompt(
            paginas, self.config, note=_RETRY_UNTYPED_NOTE.format(count=len(paginas))
        )
        novas = self._extra_attempt(prompt, paginas)
        if novas is None:
            return por_indice
        self.second_untyped += len(escolhidas)
        por_novas = _rows_by_index(novas, len(paginas))
        for posicao, (indice, _texto) in enumerate(escolhidas):
            linha = por_novas.get(posicao)
            if linha and normalize_type(linha.get("type")):
                # Só o que a leitura inteira trouxe de novo substitui; o
                # sinal de continuação continua sendo o da primeira leitura.
                por_indice[indice] = dict(linha, continues=por_indice[indice].get("continues", False))
        return por_indice

    def _extra_attempt(self, prompt: str, pages: list[WindowPage]) -> list[dict] | None:
        """Um pedido extra. `None` quando ele não cabe no contexto que esta
        máquina permite ou o servidor falha: a segunda tentativa nunca
        derruba o trecho, ele segue com o que tinha."""
        teto = self._measure_ceiling()
        precisa = context_tokens_for(prompt, page_count=len(pages), chars_per_token=self._chars_per_token)
        if teto and precisa > teto:
            self.second_capped += len(pages)
            return None
        self.plan_gpu_use(prompt, page_count=len(pages))
        try:
            linhas, _alvo = self._attempt(prompt, len(pages), extra=True)
        except ModelAnswerError:
            return None
        return linhas

    def _attempt(self, prompt: str, page_count: int, extra: bool = False) -> tuple[list[dict], int]:
        """Uma tentativa da janela: `(linhas, contexto que ela pediria)`.

        O segundo valor é 0 quando a resposta cobriu todas as páginas. Uma
        recusa por tamanho (`PromptTooLongError`) ou a assinatura do corte
        num servidor antigo valem como zero linhas — a resposta a um prompt
        cortado nunca é aceita, mesmo com o número certo de linhas. A
        calibração só aprende com uma chamada íntegra.
        """
        teto = self._measure_ceiling()
        if extra:
            self.extra_requests += 1
        else:
            self.base_requests += 1
        try:
            schema = _page_schema(page_count) if self.structured_output else None
            generation = self._generate(prompt, schema)
        except PromptTooLongError as exc:
            self._last_refused = True
            if exc.tokens:
                # Exact: returned uncapped, so that a count above the ceiling
                # is recognisable as "does not fit at all" by the caller.
                alvo = exc.tokens + _response_tokens_for(page_count)
                return [], -(-alvo // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
            alvo = (self.num_ctx or _OLLAMA_DEFAULT_CONTEXT) * 2
            alvo = -(-alvo // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
            return [], min(alvo, teto) if teto else alvo

        self._last_refused = False
        estimativa = int(len(prompt) / self._chars_per_token)
        if _looks_truncated(generation, estimativa):
            return [], self._context_needed(generation, page_count)
        self._calibrate(prompt, generation)
        rows = _pages_json(generation.text)
        if len(rows) < page_count:
            return rows, self._context_needed(generation, page_count)
        return rows, 0

    def _context_needed(self, generation: "Generation", page_count: int) -> int:
        """O contexto que esta janela pedia, lido da tentativa que falhou.

        Quando o prompt foi cortado não dá para saber de quanto ele
        precisava — `prompt_eval_count` conta só o pedaço lido. Dobrar o
        contexto é o passo que cobre a maior janela deste acervo numa
        tentativa só: 4096 vira 8192, e a janela de 5091 tokens cabe.
        """
        if _looks_truncated(generation):
            alvo = generation.context * 2
        else:
            alvo = generation.prompt_tokens + _response_tokens_for(page_count)
        alvo = -(-alvo // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
        teto = self._measure_ceiling()
        return min(alvo, teto) if teto else alvo

    def is_available(self) -> bool:
        request = urllib.request.Request(f"{self.url_base}/api/version", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=PING_TIMEOUT_S) as response:
                response.read()
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def classify(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        return self.classify_per_page(pages)

    def _generate(self, prompt: str, schema: dict | None = None) -> Generation:
        options: dict = {
            "temperature": 0,
            # How many of the model's layers run on the GPU. `-1` asks
            # Ollama to decide, which is what this used to send always;
            # `plan_gpu_use()` normally replaces it with a measured count
            # that fills the card instead of leaving VRAM idle behind
            # Ollama's own margin. `0` forces CPU/RAM when the project asks
            # for "cpu" processing, and is never overridden.
            "num_gpu": self.num_gpu,
        }
        if self.num_ctx:
            # Sent explicitly because Ollama's default (4096) is smaller
            # than a full window of this project's default settings (16
            # pages x 2000 characters), and a prompt over the limit is
            # truncated silently — the model would classify a window whose
            # end it never received.
            options["num_ctx"] = self.num_ctx

        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": schema or "json",
                # Turns off the "thinking" channel for models that have it
                # (e.g. qwen3, qwen3.5): without this, those models dump the
                # whole answer into `thinking` and return an empty
                # `response` — the engine only read `response`, so every
                # window silently turned into 0 items (Defect 3, Phase 13;
                # confirmed by running the real prompt against qwen3.5:9b).
                # Top-level Ollama field, not under `options`; models without
                # this capability (e.g. gemma4:e4b) ignore it with no effect.
                "think": False,
                # Fase 36: a prompt that does not fit `num_ctx` comes back as
                # an HTTP 400 (`PromptTooLongError`) instead of being cut to
                # half in silence — measured on 0.40.13. An older server
                # that ignores the field cuts as before, and the cut is then
                # caught by its signature (`_looks_truncated`).
                "truncate": False,
                "options": options,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url_base}/api/generate", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # An HTTP error with Ollama's own JSON body is the model refusing
            # this prompt, not the server being down.
            try:
                message = json.loads(exc.read().decode("utf-8", "replace")).get("error")
            except Exception:
                message = None
            if message and exc.code < 503:
                lowered = str(message).lower()
                if all(marker in lowered for marker in _PROMPT_TOO_LONG_MARKERS):
                    raise PromptTooLongError(str(message)) from exc
                raise ModelAnswerError(str(message)) from exc
            raise OllamaConnectionError(f"{self.url_base}: {exc}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise OllamaConnectionError(f"{self.url_base}: {exc}") from exc
        # Second safety net for the same "thinking" problem above: if for
        # some reason (model ignores `think`, old Ollama version) the text
        # still comes back in `thinking` with an empty `response`, use it
        # instead of treating the answer as empty.
        return Generation(
            text=data.get("response") or data.get("thinking") or "",
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            response_tokens=int(data.get("eval_count") or 0),
            context=int(options.get("num_ctx") or 0),
        )


# Caps on what goes into the prompt from the project's free-text fields.
# These are the user's own words, but they share the context window with
# the pages being classified: a very long instruction would push out the
# document it is supposed to help read.
_CONTEXT_FIELD_LIMIT = 700


def _clip(text: str, limit: int = _CONTEXT_FIELD_LIMIT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_context(config: ProjectConfig | None) -> str:
    """The "what am I looking at" block of the prompt, from the project form.

    This is the fix for the largest defect found in the quality review: the
    Subject, Collection type, Role instructions and Extra rules fields were
    collected on the New project form, stored, and then used **only** to
    write `instrucoes-do-projeto.md` — an artifact produced *after*
    classification. No engine ever showed them to the model.

    What that cost is measurable. A collection of teaching material
    classified by a prompt whose only worked examples were
    "OFÍCIO, MEMORANDO, PARECER" came back with almost no item typed at
    all, because those examples describe an administrative case file and
    the documents were lecture notes. The model was not failing — it was
    answering the question it had been asked.

    The user's free text is presented as **context for recognising the
    documents**, never as the task: `extra_rules` in that same collection
    said "all current legislation must be observed, as well as case law" —
    an instruction for the later research use of the index, not something
    the classifier should try to carry out. The framing below keeps the job
    unchanged and uses the text only for what it genuinely tells us: what
    this collection is about.

    Returns `""` when there is nothing to say, which leaves the prompt
    exactly as it was before this existed.
    """
    if config is None:
        return ""

    # 2.1.0: only what the user wrote. The two lines the program wrote on
    # its own, the collection profile taken from the files ("arquivos: pdf
    # (15); termos frequentes nos títulos: …") and the collection type
    # ("processo/dossiê: peças numeradas por folha…"), are gone. Until 2.1.0
    # a run started from the interface never sent this block at all (the
    # engine was built without `config`), and when it started to, measured
    # with ornith-1.5:9b against both answer keys: no context 73.7% / 100%
    # F1 (real case file / demo), collection type only 68.8% / 93.0%,
    # profile only 50.0% / 84.0%, both 60.6% / 94.1%. The model took a case file's
    # documents for one long process and merged them. The per-page prompt,
    # the one in use, sends none of this block (see `_build_page_prompt`).
    lines: list[str] = []
    subject = _clip(getattr(config, "subject", "") or "")
    if subject:
        lines.append(f"- Assunto do acervo: {subject}")

    role = _clip(getattr(config, "role_instructions", "") or "")
    if role:
        lines.append(f"- Papel definido para este acervo: {role}")

    rules = _clip(getattr(config, "extra_rules", "") or "")
    if rules:
        lines.append(f"- Observações do responsável pelo acervo: {rules}")

    if not lines:
        return ""

    return (
        "\nContexto deste acervo (serve para você reconhecer e nomear os "
        "documentos; NÃO é a sua tarefa, que continua sendo identificar as "
        "peças do texto abaixo):\n" + "\n".join(lines) + "\n"
    )


# Só entra no prompt quando alguma página tem o marcador: um acervo de PDFs
# não paga os tokens de uma regra que nunca se aplica a ele.
_STRUCK_TEXT_NOTE = (
    "\nTexto entre ~~ e ~~ estava tachado no original: é dispositivo "
    "revogado, suprimido ou substituído. Ele continua fazendo parte da "
    "peça, mas não o use como data, tipo ou resumo do que está em vigor.\n"
)


# 2.0.0: idioma por documento. O prompt continua em português (ver
# `_PAGE_PROMPT`), mas o tipo e o resumo de cada peça saem no idioma do próprio
# documento: um contrato em alemão é indexado em alemão, como quem procura
# nele o procuraria. O idioma é detectado aqui, página a página, a cada
# janela: um `.pst` mistura mensagens em idiomas diferentes, e a janela
# carrega as que tiver. Com mais de um idioma, vale o da maior parte.
# Projetos antigos não são reescritos: só o que for classificado de agora em
# diante segue esta regra.
_PAGE_FIELDS = '"subject", "type" e "detail"'


def _language_note(pages: list[WindowPage], fields: str) -> str:
    languages, main = language_detect.majority_language([page.text for page in pages])
    # Português é o idioma do próprio prompt: a janela em português fica com
    # o prompt de sempre (sem ~70 tokens a mais em todo acervo que já existia).
    if main is None or main == "pt":
        return ""
    name = language_detect.language_name(main)
    others = [language_detect.language_name(code) for code in languages[1:3]]
    line = f"\nIdioma do texto desta janela: {name}"
    if others:
        line += f" na maior parte; também aparece {', '.join(others)}"
    return (
        line + ".\n"
        f"Escreva {fields} em {name}, o idioma do documento, mesmo que estas "
        "instruções estejam em português; quando a janela misturar idiomas, "
        f"use o da maior parte ({name}). Nomes, números e citações ficam como "
        "estão no texto. O tipo vai em MAIÚSCULAS só se a escrita do idioma "
        "tiver maiúsculas.\n"
    )


def _prompt_context(
    pages: list[WindowPage], config: ProjectConfig | None, fields: str,
    note: str = "",
) -> str:
    context = build_context(config) + note
    if any(STRUCK_MARK in page.text for page in pages):
        context += _STRUCK_TEXT_NOTE
    context += _language_note(pages, fields)
    return context


# --- modo "uma linha por página" -------------------------------------------
#
# Por que o prompt é por página.
#
# O prompt anterior (o modo de faixas, removido) pedia FAIXAS: "devolva as
# peças, cada uma de ref_start a ref_end". Isso obrigava o modelo a fazer contabilidade — enumerar intervalos
# que, somados, cubram exatamente as páginas da janela, sem buraco e sem
# sobreposição. Medido em dois benchmarks sobre um relatório de 31 páginas:
#
#   janelas de 16 páginas, 5 modelos: cobertura de 0% a 9,7%
#   janelas de 8 páginas, com o prompt já exigindo cobertura total
#     explicitamente: qwen3.5:4b e gemma4:e4b cobriram 22,6% cada
#
# Cinco modelos de três famílias, o mesmo buraco, e o número idêntico entre
# modelos diferentes é o que fecha o diagnóstico: não é falta de capacidade
# de um modelo, é a tarefa que está mal colocada. Um modelo pequeno lê bem
# uma página; o que ele não faz de forma confiável é fechar a aritmética de
# um particionamento.
#
# Aqui a pergunta muda: para CADA página listada, diga o que há nela. Uma
# linha por página, nenhuma faixa a calcular. A cobertura passa a ser
# garantida por construção — se o modelo responde sobre a página, ela está
# no índice — e o agrupamento em peças vira trabalho do código, que sabe
# somar. O modelo só informa se a página continua o assunto da anterior.
# 2.0.0: a segunda tentativa de página (ver `LocalEngine._second_attempts`).
# No máximo 15% de pedidos extras sobre os normais da execução.
EXTRA_REQUEST_SHARE = 0.15
# Texto inteiro de uma página: o bastante para ler um tipo que estava depois
# do corte de `chars_per_page`, sem estourar o contexto do pedido extra.
_FULL_PAGE_CHARS = 6000
_RETRY_PROMPT_CHARS = 24000
_RETRY_MISSING_NOTE = (
    "\nO pedido anterior não trouxe resposta para algumas destas {count} páginas; esta é uma segunda "
    "leitura. As páginas vizinhas estão aqui só como contexto, mas todas precisam da sua linha.\n"
)
_RETRY_UNTYPED_NOTE = (
    "\nEstas {count} páginas vêm COM O TEXTO INTEIRO (antes elas foram lidas cortadas). Releia cada uma "
    "e preencha o \"type\" se o texto permitir reconhecer o documento.\n"
)

# NOTE (do not translate): this prompt is sent verbatim to the local model,
# and the project owner's collections are in Portuguese. Translating it would
# change classification behavior — it's a behavior knob, not code — so it
# stays in Portuguese on purpose.
_PAGE_PROMPT = """\
Você é um indexador de um acervo documental.
{context}
Abaixo estão {count} páginas de um trecho do acervo, NUMERADAS de 1 a \
{count}.

Para CADA uma das {count} páginas, devolva um objeto. Exatamente {count} \
objetos, na mesma ordem. Responda SOMENTE com um objeto JSON neste formato:

{{"pages": [
  {{"n": <o NÚMERO da página, de 1 a {count} — apenas o número, nada mais>,
   "subject": "<o assunto desta página: o exame, o documento, a seção ou o tema tratado nela>",
   "type": "<tipo em MAIÚSCULAS adequado a este acervo, ou null>",
   "date": "<AAAA-MM-DD, se a página trouxer uma data, senão null>",
   "author": "<autor/responsável, se a página disser, senão null>",
   "detail": "<uma ou duas frases dizendo o que exatamente está nesta página: nomes, números, exames, artigos, temas>",
   "continues": <true se esta página continua o MESMO assunto da anterior, false se começa um assunto novo>}}
]}}

Regras:
- "n" é só o número inteiro da página (1, 2, 3...). NUNCA copie o texto da \
página para dentro de "n", nem de nenhum campo que não seja "detail".
- Uma linha para cada página, sempre. Página em branco, ilegível ou sem \
conteúdo relevante também recebe a sua linha, com "subject" dizendo isso.
- "detail" é o que será lido para decidir abrir esta página: seja \
específico, cite o que está escrito ali, e use no máximo duas frases. \
Evite "continuação do texto" ou "informações diversas".
- "continues": a página 1 é sempre false. Use true quando a página é \
continuação direta do mesmo documento, exame ou seção da anterior.
- Nunca copie a página inteira. O JSON tem de ser curto.

Páginas:
{text}
"""


def _build_page_prompt(
    pages: list[WindowPage], config: ProjectConfig | None = None, note: str = ""
) -> str:
    """As páginas numeradas de 1 a N.

    O número é o que o modelo devolve para identificar a página, em vez da
    referência citável. Pedir a referência de volta ("copiada exatamente
    como aparece") foi medido e falhou por completo: `qwen3.5:4b` copiou o
    texto INTEIRO da página para dentro do campo `ref`, o JSON estourou
    antes de fechar e o parser recebeu zero linhas — 0% de tipo e uma peça
    por página. Um inteiro pequeno não tem como ser confundido com o
    conteúdo, e o código já sabe qual referência corresponde a cada
    posição.
    """
    blocks = [
        f"--- Página {numero} ({page.reference}, {page.file_name}) ---\n{page.text}"
        for numero, page in enumerate(pages, start=1)
    ]
    # 2.1.0: no project block here (`config` is not handed to the context).
    # Until 2.1.0 a run started from the interface never sent it anyway (the
    # engine was built without `config`); once it could, it was measured with
    # ornith-1.5:9b against both answer keys and every line of it made the
    # model cut the documents worse. With the Subject filled in: F1 73.7% ->
    # 50.0% on a real 83-page case file (15 -> 11 of 16 document starts,
    # 1 -> 3 merged documents) and 100% -> 96.5% on the demo, even though
    # the type got better on the real file (73% -> 91%). Finding the document
    # comes first. The Subject still goes into the instructions written for
    # Claude, which is what its hint on the form promises.
    del config
    return _PAGE_PROMPT.format(
        context=_prompt_context(pages, None, _PAGE_FIELDS, note), count=len(pages),
        text="\n\n".join(blocks),
    )


def _page_schema(count: int) -> dict:
    """The JSON Schema of `_PAGE_PROMPT`'s answer for a window of `count`
    pages, handed to Ollama as `format` (structured outputs): decoding is
    constrained to it, so the answer always parses, has exactly `count`
    rows and `n` is a page number. The prompt still explains every field;
    the schema only makes the shape impossible to get wrong."""
    text_or_null = {"type": ["string", "null"]}
    row = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "minimum": 1, "maximum": count},
            "subject": {"type": "string"},
            "type": text_or_null,
            "date": text_or_null,
            "author": text_or_null,
            "detail": {"type": "string"},
            "continues": {"type": "boolean"},
            # No `has_table`/`has_image` (2.1.0): extraction already sets
            # them per page (`find_tables`, the image count) and the
            # grouping ORs them in; asking the model too cost ~45
            # characters of answer per page.
        },
        "required": ["n", "subject", "type", "date", "author", "detail", "continues"],
    }
    return {
        "type": "object",
        "properties": {"pages": {"type": "array", "items": row, "minItems": count, "maxItems": count}},
        "required": ["pages"],
    }


def _pages_json(response_text: str) -> list[dict]:
    """As linhas devolvidas pelo modelo, ou `[]`."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("pages") or data.get("items")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


# Palavras curtas demais para distinguir um assunto de outro.
_SUBJECT_NOISE = frozenset({"de", "do", "da", "e", "com", "para", "em", "a", "o", "-", "–", "—"})


def _gap_between(previous: WindowPage, page: WindowPage) -> bool:
    """Se há página de fora entre as duas (só com a posição conhecida das
    duas)."""
    return bool(previous.order and page.order and page.order != previous.order + 1)


def _subject_key(subject: object) -> str:
    """Forma comparável de um assunto: minúsculas, sem pontuação nem
    palavras vazias. Duas páginas da mesma seção escrita com pontuação
    diferente têm de casar."""
    if not isinstance(subject, str):
        return ""
    limpo = "".join(c if c.isalnum() or c.isspace() else " " for c in subject.lower())
    palavras = [p for p in limpo.split() if p not in _SUBJECT_NOISE]
    return " ".join(palavras)


def _same_topic_start(a: str, b: str, palavras: int = 2) -> bool:
    """Se dois assuntos começam pelas mesmas palavras significativas.

    É o que separa "Instalações elétricas bloco A" de "Instalações elétricas
    bloco B" (mesmo documento, redação diferente) de "Fundação" e "Cobertura"
    (documentos diferentes).
    """
    if not a or not b:
        return False
    if language_detect.is_unspaced(a) and language_detect.is_unspaced(b):
        # Sem espaço entre as palavras (chinês, japonês…), "as duas primeiras
        # palavras" seriam o assunto inteiro: valem os primeiros caracteres.
        prefixo = 2 * palavras
        return a.replace(" ", "")[:prefixo] == b.replace(" ", "")[:prefixo]
    return a.split()[:palavras] == b.split()[:palavras]


def _rows_by_index(rows: list[dict], total: int) -> dict[int, dict]:
    """Posição da página (de 0) → linha do modelo. Casa pelo número `n`;
    quem não trouxer um `n` utilizável entra pela posição na resposta."""
    por_indice: dict[int, dict] = {}
    sem_numero: list[dict] = []
    for row in rows:
        numero = row.get("n")
        if isinstance(numero, str) and numero.strip().isdigit():
            numero = int(numero.strip())
        if isinstance(numero, int) and not isinstance(numero, bool) and 1 <= numero <= total:
            por_indice.setdefault(numero - 1, row)
        else:
            sem_numero.append(row)

    for posicao, row in enumerate(sem_numero):
        por_indice.setdefault(posicao, row)
    return por_indice


# Tipos que nomeiam uma parte de um documento, não um documento (ver
# `_group_pages_into_items`), já como `_subject_key` os deixa.
_SECTION_TYPE_WORDS = frozenset({
    "seção", "secao", "subseção", "subsecao", "capítulo", "capitulo", "item", "tópico", "topico", "parte",
})


def _answer_text(row: dict, key: str) -> str | None:
    """A field of the model's answer for one page, as stripped text, or
    `None` when it is missing or empty."""
    return str(row[key]).strip() if row.get(key) else None


def _group_pages_into_items(pages: list[WindowPage], rows: list[dict]) -> list[ClassifiedItem]:
    """Junta as linhas por página em peças, agrupando páginas seguidas do
    mesmo assunto.

    O código faz a aritmética que o modelo erra: casa cada linha com a
    página pela referência, percorre as páginas NA ORDEM DA JANELA (não na
    ordem em que o modelo respondeu) e fecha uma peça sempre que o assunto
    muda. Uma página sobre a qual o modelo não disse nada não é perdida —
    ela entra como continuação da peça em curso, ou abre uma peça própria
    com o que se souber dela.
    """
    # Casa cada linha com a sua página pelo número (1..N). Quem não trouxer
    # um "n" utilizável entra pela posição na resposta, que é a ordem
    # pedida — e uma linha que não casar com página nenhuma é simplesmente
    # ignorada, nunca some com a página dela.
    por_indice = _rows_by_index(rows, len(pages))

    itens: list[ClassifiedItem] = []
    atual: list[tuple[WindowPage, dict]] = []

    def fechar():
        if not atual:
            return
        dados = atual[0][1]
        detalhes = [str(d.get("detail") or d.get("subject") or "").strip() for _p, d in atual]
        detalhes = [d for d in detalhes if d]
        # Sem detalhe nenhum vindo do modelo, o texto da própria página
        # ainda leva a busca ao lugar certo.
        if not detalhes:
            bruto = " ".join(" ".join(p.text.split()) for p, _d in atual).strip()
            detalhes = [bruto[:_FALLBACK_SUMMARY_CHARS]] if bruto else []
        resumo = " ".join(dict.fromkeys(detalhes))[:SUMMARY_CHAR_LIMIT] or None

        assunto = str(dados.get("subject") or "").strip()
        if assunto and resumo and not resumo.lower().startswith(assunto.lower()[:20]):
            resumo = f"{assunto}: {resumo}"[:SUMMARY_CHAR_LIMIT]

        # Três casos, não dois. Uma página sobre a qual o modelo não disse
        # NADA entra no índice pelo agrupamento — essa garantia é o que
        # impede a perda — mas não pode chegar ao relatório com a mesma
        # confiança de uma linha que ele respondeu pela metade. Sem isso,
        # centenas de peças cegas saíam como `medium`, o resumo da etapa 6
        # fechava em `baixa=0` e a nota de qualidade ficava alta demais.
        respondida = any(linha for _pagina, linha in atual)
        if dados.get("type") and dados.get("detail"):
            confianca = "high"
        elif respondida:
            confianca = "medium"
        else:
            confianca = "low"
        paginas = [p for p, _d in atual]
        itens.append(item_for_pages(
            paginas, engine=ENGINE_LOCAL, confidence=confianca,
            type_=_answer_text(dados, "type"), date=_answer_text(dados, "date"),
            author=_answer_text(dados, "author"), summary=resumo,
            has_table=any(bool(d.get("has_table")) or p.has_table for p, d in atual),
            has_image=any(bool(d.get("has_image")) or bool(p.image_count) for p, d in atual),
        ))
        atual.clear()

    anterior_assunto = None
    anterior_tipo = ""
    for indice, page in enumerate(pages):
        dados = por_indice.get(indice, {})
        assunto = _subject_key(dados.get("subject"))
        tipo = _subject_key(dados.get("type"))

        # O agrupamento é decidido pelo ASSUNTO, não pelo `continues` que o
        # modelo devolve. Medido: `qwen3.5:4b` identificou impecavelmente os
        # oito seções de uma janela (fundação, estrutura, cobertura,
        # instalações, esquadrias, pintura e outras) e marcou
        # `continues: true` em todos, porque entendeu "continua o mesmo
        # relatório" e não "o mesmo assunto". A pergunta era ambígua e a
        # resposta, previsível: comparar dois rótulos é trabalho de código.
        #
        # `continues` continua servindo para o caso em que o assunto muda de
        # redação sem mudar de documento ("Instalações elétricas, bloco A" /
        # "Instalações elétricas, bloco B"): aí ele desempata, desde que o começo
        # do assunto coincida.
        if not atual or starts_new_document(atual[-1][0], page) or _gap_between(atual[-1][0], page):
            # Um arquivo de documento inteiro (HTML, DOCX, TXT…) é sempre
            # uma peça: duas leis seguidas têm o mesmo "assunto" para o
            # modelo e seriam juntadas. Uma página que ficou de fora do
            # pedido (a página em branco, que não vai ao modelo) também
            # separa: a peça não pode cobrir a página que ela não tem.
            continua = False
        elif assunto and anterior_assunto:
            # 2.1.0: `continues` também junta quando o TIPO é o mesmo da
            # página anterior, no mesmo arquivo. Medido num processo real
            # (83 páginas): o relatório de 29 páginas saía em ~25 peças de uma
            # página, todas do mesmo tipo e com `continues`
            # verdadeiro, porque o assunto de cada página é o parágrafo que
            # ela traz. Seções de tipos diferentes continuam separadas.
            # Medido com gabarito: no processo real, ornith-1.5:9b foi de 57
            # para 22 peças (16 documentos) e de 9 para 11 documentos exatos,
            # sem fusão nova (qwen3.5:4b ganhou uma fusão e perdeu um início
            # de documento); no acervo de demonstração, F1 de 96,5% para
            # 100% (ornith) e de 57,6% para 87,5% (qwen3.5:4b).
            # Não vale quando o tipo nomeia uma parte do documento ("SEÇÃO",
            # "CAPÍTULO"): aí o próprio modelo disse que cada página é uma
            # seção, e seções de assuntos diferentes ficam separadas.
            mesmo_tipo = (
                bool(tipo) and tipo == anterior_tipo and tipo.split()[0] not in _SECTION_TYPE_WORDS
                and page.file_name == atual[-1][0].file_name
            )
            continua = assunto == anterior_assunto or (
                bool(dados.get("continues")) and (_same_topic_start(assunto, anterior_assunto) or mesmo_tipo)
            )
        else:
            # Sem assunto de um dos lados, só o sinal do modelo resta.
            continua = bool(dados.get("continues"))

        if atual and not continua:
            fechar()
        atual.append((page, dados))
        if assunto:
            anterior_assunto = assunto
        anterior_tipo = tipo
    fechar()
    return itens

@dataclass
class LocalClassificationResult(WindowRunCounts):
    windows_via_rules_fallback: int = 0
    windows_skipped: int = 0
    windows_structured: int = 0
    # Fase 36: windows whose context had to grow past the run's initial
    # value, and windows split in two because they did not fit the ceiling.
    windows_context_raised: int = 0
    windows_split_for_size: int = 0
    # 2.0.0: páginas em branco que nem foram ao modelo, e a segunda
    # tentativa (páginas sem resposta, páginas sem tipo, pedidos extras e
    # normais, o que o teto de 15% deixou de fora).
    blank_pages: int = 0
    second_missing: int = 0
    second_untyped: int = 0
    extra_requests: int = 0
    base_requests: int = 0
    second_capped: int = 0


def _log_window_notes(
    conn: sqlite3.Connection,
    local_engine: "LocalEngine",
    window_key: str,
    language: str | None = None,
    writer=None,
) -> tuple[int, int]:
    """Logs (at `info` level) what happened to the last window's context
    (`LocalEngine.last_window_notes`, fase 36) and returns `(raised,
    split)` — how many notes of each kind — for the step's summary. Same
    shape as `_log_rejection_warnings`: the reason travels as a nested
    key so the event is retranslated on a later read.

    Why it is logged at all: the windows the Ollama cut in a large run
    left no trace in the project log — the only record was the server's
    own log, which the user never sees. A window that needed more context
    than the run started with, or that had to be split, is the fact that
    explains a slower stretch of the run.
    """
    raised = split = 0
    for note_key, note_params in getattr(local_engine, "last_window_notes", None) or []:
        if note_key.endswith("window_context_raised"):
            raised += 1
        elif note_key.endswith("window_split_for_size"):
            split += 1
        params = {"window": window_key, "reason": nested(note_key, **note_params)}
        if writer is not None:
            writer.add(lambda c, params=params: record_event(
                c, "classification", "info", "log.local_engine.window_note",
                params, language=language, commit=False,
            ))
            continue
        record_event(conn, "classification", "info", "log.local_engine.window_note", params, language=language)
    return raised, split


def _log_rejection_warnings(
    conn: sqlite3.Connection, local_engine: LocalEngine, window_key: str, language: str | None = None,
    writer=None,
) -> None:
    """Logs (at `aviso` level) every warning from the last call to
    `local_engine.classify()` (`last_window_warnings`) — a loss the window
    survived must not be silent.

    `reason` is `nested(warning_key, **warning_params)` (Task 12, Phase
    14), not pre-translated text — it stays retranslatable along with the
    rest of the event on a later read (`list_events`), see `nested()`'s
    docstring in `i18n.py`."""
    for warning_key, warning_params in local_engine.last_window_warnings:
        params = {"window": window_key, "reason": nested(warning_key, **warning_params)}
        if writer is not None:
            # Joins the window's batch instead of a commit of its own.
            writer.add(lambda c, params=params: record_event(
                c, "classification", "warning", "log.local_engine.window_rejection",
                params, language=language, commit=False,
            ))
            continue
        record_event(
            conn, "classification", "warning", "log.local_engine.window_rejection",
            params, language=language,
        )


_FALLBACK_SUMMARY_CHARS = FALLBACK_SUMMARY_CHARS

# Resumo da peça de uma página sem texto e sem imagem (tipo
# `item_normalize.BLANK_PAGE_TYPE`). É o que o acervo traz de
# verdade (a folha em branco de um volume encadernado): conhecida pelo código,
# não precisa de pedido ao modelo e sai com confiança alta.
BLANK_PAGE_SUMMARY = "Página em branco: sem texto e sem imagem."


def is_blank_page(page: WindowPage) -> bool:
    """Página de documento paginado (PDF, imagem, formatos convertidos) sem
    texto e sem imagem. As mensagens de e-mail (`.mbox`, Outlook) e os
    trechos de transcrição são uma página cada e ficam de fora de propósito:
    uma mensagem vazia é uma mensagem, não uma folha em branco; e um arquivo
    de documento inteiro (TXT, DOCX…) vazio continua pelo caminho de sempre."""
    if page.text.strip() or page.image_count:
        return False
    return category_of_extension(Path(page.file_name).suffix) in PAGED_CATEGORIES


# 2.1.4: página que só tem o rodapé (ou cabeçalho) repetido do documento. Os
# processos do órgão têm milhares de folhas vazias com só "Para verificar as
# assinaturas... código NNNNNNNN." e um ícone; o modelo lia uma a uma (18.414
# páginas, ~69 h de classificação). Entra na regra o texto inteiro da página,
# curto, igual em pelo menos `FOOTER_MIN_SHARE` das páginas de um arquivo de
# `FOOTER_MIN_PAGES` páginas ou mais. Slides com títulos curtos e diferentes,
# ou um título igual em poucas páginas, seguem para o modelo.
FOOTER_MAX_CHARS = 200
FOOTER_MIN_PAGES = 20
FOOTER_MIN_SHARE = 0.3
FOOTER_PAGE_SUMMARY = "Página sem texto próprio: só o rodapé ou cabeçalho que se repete no documento."

# file_id → (textos de rodapé, menor número de imagens de uma página do arquivo)
FooterTexts = dict[int, tuple[frozenset[str], int]]


def _footer_key(text: str) -> str:
    return " ".join(text.split())


def repeated_footer_texts(conn: sqlite3.Connection) -> FooterTexts:
    """Os textos de rodapé de cada arquivo, uma leitura por classificação.
    Arquivo com OCR falho fica de fora: a folha escaneada cujo OCR não saiu
    pode ter conteúdo, e o rodapé nativo seria o único texto dela."""
    totals: dict[int, tuple[int, int]] = {}
    for file_id, pages, fewest_images in conn.execute(
        """
        SELECT page.file_id, COUNT(*), MIN(page.image_count)
        FROM page JOIN file ON file.id = page.file_id
        WHERE COALESCE(file.ocr_failed, 0) = 0
        GROUP BY page.file_id
        HAVING COUNT(*) >= ?
        """,
        (FOOTER_MIN_PAGES,),
    ):
        totals[file_id] = (pages, fewest_images or 0)
    counts: dict[int, dict[str, int]] = {}
    for file_id, text in conn.execute(
        "SELECT file_id, text FROM page WHERE length(text) <= ? AND trim(text) != ''",
        (FOOTER_MAX_CHARS * 2,),
    ):
        if file_id not in totals:
            continue
        key = _footer_key(text or "")
        if key and len(key) <= FOOTER_MAX_CHARS:
            per_file = counts.setdefault(file_id, {})
            per_file[key] = per_file.get(key, 0) + 1
    found: FooterTexts = {}
    for file_id, per_file in counts.items():
        pages, fewest_images = totals[file_id]
        texts = frozenset(key for key, count in per_file.items() if count >= FOOTER_MIN_SHARE * pages)
        if texts:
            found[file_id] = (texts, fewest_images)
    return found


def is_footer_only_page(page: WindowPage, footers: FooterTexts | None) -> bool:
    """Página cujo texto inteiro é o rodapé repetido do arquivo, sem imagem
    além das que toda página dele tem (o ícone do rodapé)."""
    if not footers or page.file_id not in footers:
        return False
    texts, fewest_images = footers[page.file_id]
    if page.image_count > fewest_images:
        return False
    if category_of_extension(Path(page.file_name).suffix) not in PAGED_CATEGORIES:
        return False
    return _footer_key(page.text) in texts


def split_blank_pages(
    pages: list[WindowPage], footers: FooterTexts | None = None,
) -> tuple[list[ClassifiedItem], list[WindowPage]]:
    """`(peças das páginas em branco, páginas que seguem para o modelo)`.
    Páginas em branco seguidas do mesmo arquivo e do mesmo tipo (sem nada;
    só o rodapé) são uma peça só."""
    def kind(page: WindowPage) -> str | None:
        if is_blank_page(page):
            return BLANK_PAGE_SUMMARY
        if is_footer_only_page(page, footers):
            return FOOTER_PAGE_SUMMARY
        return None

    kinds = [kind(page) for page in pages]
    blank = [(page, summary) for page, summary in zip(pages, kinds) if summary]
    if not blank:
        return [], pages
    blocks: list[list[tuple[WindowPage, str]]] = [[blank[0]]]
    for previous, current in zip(blank, blank[1:]):
        (before, before_kind), (page, page_kind) = previous, current
        if (
            page.file_name == before.file_name and page_kind == before_kind
            and page_order(page) == page_order(before) + 1
        ):
            blocks[-1].append(current)
        else:
            blocks.append([current])
    items: list[ClassifiedItem] = []
    for block in blocks:
        items.append(item_for_pages(
            [page for page, _ in block], engine=ENGINE_LOCAL, confidence="high", type_=BLANK_PAGE_TYPE,
            summary=block[0][1], has_table=False, has_image=False,
        ))
    return items, [page for page, summary in zip(pages, kinds) if not summary]


def _coverage_items(pages: list[WindowPage]) -> list[ClassifiedItem]:
    """Peças de cobertura do motor local (`classification.coverage_items`)."""
    return coverage_items(pages, ENGINE_LOCAL)


def _log_gpu_plan(
    conn: sqlite3.Connection, local_engine: LocalEngine, language: str | None = None
) -> bool:
    """Records how the GPU is being used for this run. Returns `True` once
    it has logged, so the caller stops asking.

    The user asked to be able to see that the card is actually being filled
    before anything spills into RAM — a number that is otherwise invisible:
    Ollama does not report it, and the Run screen's VRAM gauge shows the
    result without ever explaining the decision behind it.
    """
    plan = local_engine.gpu_plan
    if plan is None:
        return False

    # The one message that changes what the user should *do*. Everything
    # else here is information; this is the case where no setting will
    # help, because the weights are simply larger than the card — and the
    # difference is not subtle: on the collection that prompted this work,
    # a 9.1 GB model on an 8 GB card ran with 17% of itself on the GPU.
    if plan.get("model_fits_card") is False:
        record_event(
            conn, "classification", "warning", "log.local_engine.model_too_big_for_gpu",
            {
                "model": plan.get("model", ""),
                "model_mb": plan.get("model_mb", 0),
                "vram_mb": plan.get("vram_total_mb", 0),
            },
            language=language,
        )

    if plan.get("layers_on_gpu") is None:
        record_event(
            conn, "classification", "info", "log.local_engine.gpu_plan_unavailable",
            {"model": plan.get("model", ""), "context": plan.get("context_tokens", 0)},
            language=language,
        )
        return True

    record_event(
        conn, "classification", "info", "log.local_engine.gpu_plan",
        {
            "model": plan.get("model", ""),
            "layers": plan.get("layers_on_gpu", 0),
            "layers_total": plan.get("layers_total", 0),
            "free_vram": plan.get("free_vram_mb") or 0,
            "context": plan.get("context_tokens", 0),
            "ceiling": plan.get("context_ceiling", 0),
        },
        language=language,
    )
    return True


def _log_backend(conn: sqlite3.Connection, language: str | None = None) -> None:
    """Records which backend the server is on (fase 36) — once per run,
    after the first window, because the scheduler's "parallel requests"
    warning is only written when the model loads. Read-only over the
    server logs (`ollama_backend.read_backend`); nothing found means an
    event saying so, never an exception."""
    try:
        info = ollama_backend.read_backend()
    except Exception:
        info = None
    if info is None:
        record_event(conn, "classification", "info", "log.local_engine.backend_unknown", language=language)
        return

    if info.parallel_pinned_family:
        note = nested("log.local_engine.backend_parallel_pinned", family=info.parallel_pinned_family)
    else:
        note = nested("log.local_engine.backend_no_note")
    if ollama_backend.prefers_flash_attention_off(info):
        tuning = nested("log.local_engine.backend_flash_attention_off")
    else:
        tuning = nested("log.local_engine.backend_tuning_default")
    record_event(
        conn, "classification", "info", "log.local_engine.backend",
        {"device": info.device, "library": info.library, "total": info.total, "note": note, "tuning": tuning},
        language=language,
    )
    # "AMD driver is too old" with the card on Vulkan means two different
    # things. RX 5000/6000: Ollama's ROCm needs the driver's `amdhip64_7.dll`,
    # which AMD does not ship for them on Windows (measured here: only
    # `amdhip64_6.dll`, in the October 2026 driver) — nothing the user does today
    # reaches ROCm, Vulkan is the path. Any other AMD card (RX 7000, W7000):
    # the same line, but a current Adrenalin with HIP 7 does bring ROCm —
    # telling that user "no update changes this" would be false and would
    # contradict the installer (revisão da fase 36).
    if info.amd_driver_old and info.library.lower() == "vulkan":
        # 2.1.4: sem HIP 7 não há o que fazer, então é informação; o aviso
        # aparecia como problema a cada classificação. O driver antigo de uma
        # RX 7000 tem conserto (atualizar) e segue como aviso.
        if ollama_backend.prefers_flash_attention_off(info):
            key, level = "log.local_engine.backend_amd_no_hip7", "info"
        else:
            key, level = "log.local_engine.backend_amd_driver_old", "warning"
        record_event(conn, "classification", level, key, {"device": info.device}, language=language)


MODEL_RETRY_SECONDS = 60.0
def _prepare_second_attempts(conn: sqlite3.Connection, local_engine) -> None:
    """Dá ao motor de onde ler o texto inteiro de uma página (o índice de
    busca). Um motor que não tem esse campo (um dublê de teste, outro motor)
    segue como antes. O perfil do acervo não vai mais ao prompt (2.1.0, ver
    `build_context`)."""

    try:
        if getattr(local_engine, "page_text", None) is None:
            local_engine.page_text = lambda page: fulltext.page_text(conn, page.file_id, page.reference)
    except Exception:
        pass


def _classify_in_parts(engine: "LocalEngine", pages: list[WindowPage]) -> list[ClassifiedItem]:
    """The window in halves, and each half in halves again, until the page
    the model cannot read is alone. That page gets no item from the
    model; the coverage guarantee in `classify_pending` indexes it by file
    name. Connection errors are not caught here: an outage in the middle is
    handled by the caller like any other."""
    if not pages:
        return []
    try:
        return engine.classify(pages)
    except ModelAnswerError:
        if len(pages) == 1:
            return []
        middle = len(pages) // 2
        return _classify_in_parts(engine, pages[:middle]) + _classify_in_parts(engine, pages[middle:])


MODEL_MAX_OUTAGES = 10
WINDOW_MAX_ATTEMPTS = 3


def _has_dedicated_gpu() -> bool:
    """A graphics card Ollama runs on (NVIDIA through `nvidia-smi`, or an
    AMD card reported by Windows). Integrated graphics do not count."""
    if hardware.detect_nvidia_gpu() is not None:
        return True
    gpu = hardware.detect_wmi_gpu()
    vendor = (gpu.vendor if gpu else "").lower()
    return gpu is not None and ("amd" in vendor or "advanced micro" in vendor) and gpu.vram_mb >= 2048


def _mentions_fallback(jsonl_path: Path) -> bool:
    """Whether the file has the `"fallback"` key anywhere, by a byte search.

    Almost every classification finds none (the model was up last time),
    and parsing every line of a file of gigabytes to learn that took
    seconds. Inside a JSON string a quote is escaped, so the quoted key
    only appears as a key (or as a whole string value, which just means
    the full pass below runs, as before)."""
    needle = b'"' + raw_items.FALLBACK.encode("ascii") + b'"'
    tail = b""
    with open(jsonl_path, "rb") as file:
        while True:
            block = file.read(1 << 20)
            if not block:
                return False
            if needle in tail + block[: len(needle) - 1] or needle in block:
                return True
            tail = block[-(len(needle) - 1):]


def _fallback_only_windows(jsonl_path: Path) -> set:
    """Keys of the windows whose every line in `raw_items.jsonl` carries
    `"fallback": true`. One pass, holding only keys."""
    if not jsonl_path.exists() or not _mentions_fallback(jsonl_path):
        return set()
    marked: set = set()
    unmarked: set = set()
    for _, text in raw_items.iter_lines(jsonl_path):
        data = raw_items.parse(text)
        if data is None:
            continue
        window_key = data.get(raw_items.WINDOW)
        (marked if data.get(raw_items.FALLBACK) else unmarked).add(window_key)
    return marked - unmarked


def drop_fallback_lines_of_pending_windows(conn, jsonl_path: Path) -> int:
    """Finishes a requeue the process did not: windows already `pending`
    whose fallback lines are still in `raw_items.jsonl` (the crash between
    the commit and the prune in `requeue_fallback_windows`). Their lines go;
    the windows stay as they are. Returns how many windows.

    `requeue_fallback_windows` itself only runs with the model up or a
    graphics card; without both, the run classified those windows with the
    Rules engine again and their lines ended up in the file twice."""
    candidates = sorted(_fallback_only_windows(jsonl_path))
    pending: set = set()
    for start in range(0, len(candidates), 500):
        chunk = candidates[start:start + 500]
        pending.update(
            row[0] for row in conn.execute(
                f"SELECT key FROM window WHERE status = ? AND key IN ({','.join('?' * len(chunk))})",
                (WINDOW_PENDING, *chunk),
            )
        )
    if not pending:
        return 0
    raw_items.prune(
        jsonl_path, lambda line: line.get(raw_items.WINDOW) in pending, temporary_suffix=".requeue.tmp"
    )
    return len(pending)


def requeue_fallback_windows(conn, jsonl_path: Path) -> int:
    """Windows the Rules engine classified only because the model
    was down (their lines carry `"fallback": true`) go back to 'pending',
    and their lines leave `raw_items.jsonl`. Returns how many.

    The database is committed before the file is pruned (`raw_items.
    prune`, which swaps in a complete new file): a crash between the two
    leaves the windows pending with their old lines still in the file,
    which the next call removes. The other way round left them done with
    no lines, and nothing would ever classify them again. A window with
    any line not marked is left alone.

    Two passes over the file, holding only window keys: on a large
    collection it has gigabytes, and this runs at every classification."""
    to_requeue = _fallback_only_windows(jsonl_path)
    if not to_requeue:
        return 0
    keys = sorted(to_requeue)
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        conn.execute(
            f"UPDATE window SET status = ? WHERE key IN ({','.join('?' * len(chunk))})", (WINDOW_PENDING, *chunk)
        )
    conn.commit()
    raw_items.prune(
        jsonl_path, lambda line: line.get(raw_items.WINDOW) in to_requeue, temporary_suffix=".requeue.tmp"
    )
    return len(to_requeue)


def classify_pending(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    local_engine: LocalEngine | None = None,
    should_stop=None,
    language: str | None = None,
    model: str | None = None,
) -> LocalClassificationResult:
    """Classifies every `pending` window with the `local` engine.

    With a graphics card, a model that stops responding is waited
    for (and restarted) and the run carries on from the same window; the
    Rules engine is never used. Without one, the window falls back to the
    `rules` engine, marked so the next run gives it back to the model.

    `model`: the model already decided for the run (`orchestrator.
    decide_engine`); without it, the project's."""
    result = LocalClassificationResult()

    if local_engine is None:
        local_engine = LocalEngine(
            model=model or local_models.model_to_use(config), num_gpu=_num_gpu_for(config.processing_mode),
            config=config,
        )

    _prepare_second_attempts(conn, local_engine)
    footers = repeated_footer_texts(conn)

    rules_fallback_engine = RulesEngine(load_rules())
    # 1.5.12, explicit request: with a graphics card the model is the only
    # engine. Losing it means waiting for it to come back and carrying on
    # from the same window, never the Rules engine (one slow window once
    # sent thousands of windows to Rules in a few minutes, with no word in
    # the log). Without a card the old fallback stays, now marked so the
    # next run gives those windows back to the model.
    model_required = config.processing_mode != "cpu" and _has_dedicated_gpu()
    ollama_available = local_engine.is_available()

    if not ollama_available:
        ollama_available = _try_restart_ollama(conn, local_engine, language=language)

    jsonl_path = raw_items.path_in(config.output_folder)
    if ollama_available or model_required:
        # What the Rules engine stood in for last time goes back to the model.
        requeued = requeue_fallback_windows(conn, jsonl_path)
        if requeued:
            record_event(
                conn, "classification", "info", "log.local_engine.fallback_requeued",
                {"windows": requeued}, language=language,
            )
    else:
        # The model stays down and the Rules engine will stand in again:
        # nothing goes back to the queue, but a requeue cut short leaves
        # pending windows whose old lines would be written a second time.
        drop_fallback_lines_of_pending_windows(conn, jsonl_path)
    model_retry_at = 0.0 if model_required else time.monotonic() + MODEL_RETRY_SECONDS
    outages = 0
    gpu_plan_logged = False
    backend_logged = False

    def wait_until(moment: float) -> bool:
        """Sleeps until `moment`; `False` if asked to stop meanwhile."""
        while time.monotonic() < moment:
            if should_stop is not None and should_stop():
                return False
            time.sleep(min(1.0, max(0.0, moment - time.monotonic())))
        return True

    def classify_window(window, pages, writer):
        """The window's items, or `None` (skipped: stays pending), or
        `STOP_CLASSIFYING` (asked to stop while waiting for the model)."""
        nonlocal ollama_available, model_retry_at, outages, gpu_plan_logged, backend_logged
        # Planalto acts are read from their own structure
        # (`planalto.py`); only the other pages go to the model. A
        # window made only of acts never waits for the model.
        # A página em branco (sem texto e sem imagem) não vai ao modelo:
        # vira "PÁGINA EM BRANCO" com confiança alta.
        blank_items, pages_to_read = split_blank_pages(pages, footers)
        result.blank_pages += sum(item.end_order - item.start_order + 1 for item in blank_items)
        structured_items, model_pages = planalto.split(pages_to_read)
        result.windows_structured += 1 if structured_items else 0

        items = None if model_pages else []
        via_fallback = False
        failures_here = 0
        while items is None:
            if not ollama_available and (
                model_required or (outages < MODEL_MAX_OUTAGES and time.monotonic() >= model_retry_at)
            ):
                if not wait_until(model_retry_at):
                    return STOP_CLASSIFYING
                writer.flush()  # the events below commit on their own
                ollama_available = local_engine.is_available() or _try_restart_ollama(
                    conn, local_engine, language=language
                )
                if ollama_available:
                    if outages:
                        record_event(conn, "classification", "info",
                                     "log.local_engine.model_resumed", language=language)
                else:
                    outages += 1
                    model_retry_at = time.monotonic() + MODEL_RETRY_SECONDS
                    if model_required:
                        if outages == 1 or outages % 10 == 0:
                            record_event(
                                conn, "classification", "warning", "log.local_engine.model_waiting",
                                {"seconds": int(MODEL_RETRY_SECONDS), "outages": outages},
                                language=language,
                            )
                        continue
                    if outages >= MODEL_MAX_OUTAGES:
                        record_event(
                            conn, "classification", "warning", "log.local_engine.model_given_up",
                            {"seconds": int(MODEL_RETRY_SECONDS), "outages": outages,
                             "max": MODEL_MAX_OUTAGES},
                            language=language,
                        )

            if ollama_available:
                try:
                    items = local_engine.classify(model_pages)
                    outages = 0
                    if not gpu_plan_logged:
                        # Commits on its own: the batch goes first, so a
                        # later replay never writes these ops twice.
                        writer.flush()
                        gpu_plan_logged = _log_gpu_plan(conn, local_engine, language=language)
                    if not backend_logged:
                        writer.flush()
                        _log_backend(conn, language=language)
                        backend_logged = True
                    _log_rejection_warnings(
                        conn, local_engine, window["key"], language=language, writer=writer
                    )
                    raised, split = _log_window_notes(
                        conn, local_engine, window["key"], language=language, writer=writer
                    )
                    result.windows_context_raised += raised
                    result.windows_split_for_size += split
                    break
                except ModelAnswerError as exc:
                    writer.flush()  # these events commit on their own
                    record_event(
                        conn, "classification", "warning", "log.local_engine.window_split",
                        {"window": window["key"], "error": str(exc)}, language=language,
                    )
                    items = _classify_in_parts(local_engine, model_pages)
                    break
                except OllamaConnectionError as exc:
                    writer.flush()  # these events commit on their own
                    failures_here += 1
                    record_event(
                        conn, "classification", "warning", "log.local_engine.connection_lost",
                        {"error": str(exc)}, language=language,
                    )
                    if failures_here >= WINDOW_MAX_ATTEMPTS:
                        # The model answers other windows but not this
                        # one: it stays pending for the next run instead
                        # of holding up the rest.
                        record_event(
                            conn, "classification", "error", "log.local_engine.window_skipped",
                            {"window": window["key"], "attempts": failures_here},
                            language=language,
                        )
                        result.windows_skipped += 1
                        break
                    # A server that still answers is busy, not dead:
                    # the same window is sent again with no restart.
                    if local_engine.is_available():
                        continue
                    ollama_available = False
                    model_retry_at = 0.0 if model_required else time.monotonic()
                    if not model_required:
                        ollama_available = _try_restart_ollama(conn, local_engine, language=language)
                        if ollama_available:
                            continue
                        outages += 1
                        model_retry_at = time.monotonic() + MODEL_RETRY_SECONDS
                        record_event(
                            conn, "classification", "warning",
                            "log.local_engine.model_paused" if outages < MODEL_MAX_OUTAGES
                            else "log.local_engine.model_given_up",
                            {"seconds": int(MODEL_RETRY_SECONDS), "outages": outages,
                             "max": MODEL_MAX_OUTAGES},
                            language=language,
                        )
                    continue

            if not model_required:
                items = rules_fallback_engine.classify(model_pages)
                result.windows_via_rules_fallback += 1
                via_fallback = True

        if items is None:
            return None  # skipped: the window stays pending
        return WindowItems(
            blank_items + structured_items + items,
            # So the next run gives it back to the model.
            {raw_items.FALLBACK: True} if via_fallback else {},
        )

    # The window's events and its "done" go in one batch (`BatchWriter`)
    # instead of 2–4 commits per window. The coverage fill is done by the
    # loop, and not inside `classify`, so it also holds when the window
    # failed and fell back to the rules engine.
    def run_pass() -> None:
        classify_windows(
            conn, config, classify_window, result,
            invalid_item_event=lambda item, window_key, errors: (
                "log.local_engine.invalid_item",
                {"engine": item.engine, "window": window_key, "errors": "; ".join(errors)},
            ),
            coverage=("log.local_engine.coverage_filled", _coverage_items),
            should_stop=should_stop, language=language,
        )

    run_pass()
    # 2.1.4: a janela que o modelo deixou de responder 3 vezes seguidas
    # (Ollama no ar, mas lento por alguns minutos) ganha uma volta extra no
    # fim, quando ele costuma já ter voltado. Antes ela ficava pendente até
    # alguém rodar a classificação de novo, e o índice saía com o buraco.
    skipped = result.windows_skipped
    if skipped and not (should_stop is not None and should_stop()):
        record_event(
            conn, "classification", "info", "log.local_engine.skipped_retry", {"count": skipped},
            language=language,
        )
        run_pass()

    if result.windows_context_raised or result.windows_split_for_size:
        # Fase 36: the context story of the step, once — the per-window
        # notes say which, this says how many and against which ceiling.
        record_event(
            conn, "classification", "info", "log.local_engine.context_summary",
            {
                "raised": result.windows_context_raised, "split": result.windows_split_for_size,
                "ceiling": int(getattr(local_engine, "context_ceiling", 0) or 0),
            },
            language=language,
        )

    result.base_requests = int(getattr(local_engine, "base_requests", 0) or 0)
    result.extra_requests = int(getattr(local_engine, "extra_requests", 0) or 0)
    result.second_missing = int(getattr(local_engine, "second_missing", 0) or 0)
    result.second_untyped = int(getattr(local_engine, "second_untyped", 0) or 0)
    result.second_capped = int(getattr(local_engine, "second_capped", 0) or 0)
    if result.blank_pages or result.extra_requests or result.second_capped:
        record_event(
            conn, "classification", "info", "log.local_engine.second_pass_summary",
            {
                "blank": result.blank_pages, "missing": result.second_missing,
                "untyped": result.second_untyped, "extra": result.extra_requests,
                "base": result.base_requests, "capped": result.second_capped,
            },
            language=language,
        )

    record_event(
        conn,
        "classification",
        "info",
        "log.local_engine.summary",
        {
            "windows": result.windows_processed, "fallback": result.windows_via_rules_fallback,
            "items": result.items_generated, "high": result.high_confidence,
            "medium": result.medium_confidence, "low": result.low_confidence,
            "invalid": result.invalid_items,
        },
        language=language,
    )

    return result

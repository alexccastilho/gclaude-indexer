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
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .classification import WindowPage, ClassifiedItem, load_window_pages, reference_number, item_to_dict, validate_item
from .config import ProjectConfig
from .events import record_event
from .i18n import nested
from .import_items import RAW_ITEMS_FILE_NAME
from .engine_rules import RulesEngine, load_rules
from .gpu_budget import server_environment
from .subprocess_utils import start_in_background
from .tools import find as find_tool

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
GENERATION_TIMEOUT_S = 120
PING_TIMEOUT_S = 5
# Explicit user request: when Ollama does not respond, try to restart the
# server on our own before giving up and falling back to the 'rules' engine.
OLLAMA_RESTART_ATTEMPTS = 3
WAIT_BETWEEN_ATTEMPTS_S = 4.0

# By explicit user decision, the 'local' engine always uses this model, on
# any machine — the hardware table from section 10.2 (phase 7) still exists
# for diagnostics/reporting, but no longer decides the model used here. Only
# a manual choice in `modelo_local` (form) overrides this.
DEFAULT_LOCAL_MODEL = "gemma4:e4b"

# NOTE (do not translate): this prompt is sent verbatim to the local model,
# and the project owner's collections are in Portuguese. Translating it would
# change classification behavior — it's a behavior knob, not code — so it
# stays in Portuguese on purpose.
_PROMPT = """\
Você é um classificador de peças de um acervo documental.
{context}
Abaixo está o \
texto de uma janela: um trecho contínuo de páginas, cada uma rotulada por \
sua referência citável (ex. "f. 12" ou "p. 5") e pelo nome do arquivo de \
origem.

Identifique as peças (documentos individuais) contidas neste texto. Uma \
peça pode ocupar uma ou mais páginas consecutivas. Responda SOMENTE com um \
objeto JSON, sem nenhum texto fora dele, neste formato exato:

{{"items": [
  {{"ref_start": "<referência que aparece literalmente no texto>",
   "ref_end": "<referência que aparece literalmente no texto>",
   "type": "<tipo do documento em MAIÚSCULAS, adequado a este acervo, ou null>",
   "date": "<AAAA-MM-DD ou null>",
   "author": "<autor ou null>",
   "summary": "<frase curta ou null>",
   "has_table": true ou false,
   "has_image": true ou false,
   "confidence": "high", "medium" ou "low"}}
]}}

Regras:
- ref_inicial e ref_final têm que ser referências que aparecem literalmente \
no texto abaixo — nunca invente uma.
- data só em ISO (AAAA-MM-DD); sem data clara no texto, use null.
- confianca "low" quando você não tiver certeza do tipo ou dos limites \
da peça; nunca finja certeza.
- Não copie o texto inteiro no resumo — uma frase basta.
- COBERTURA TOTAL, esta é a regra mais importante: TODA página listada \
abaixo tem de estar dentro de exatamente uma peça. Some as faixas que você \
devolver — elas precisam cobrir da primeira à última página, sem buraco e \
sem sobreposição. Uma página que não aparece em nenhuma peça é informação \
PERDIDA para quem for consultar este índice depois. Se um trecho for \
irrelevante ou você não souber nomeá-lo, devolva-o mesmo assim como uma \
peça com "type": null e um resumo do que há ali — nunca o omita.
- UMA PEÇA POR UNIDADE DE ASSUNTO. Uma peça é o menor trecho que alguém \
procuraria inteiro: um documento, um exame, um capítulo, uma seção com \
título próprio. Páginas seguidas que continuam o MESMO assunto formam uma \
peça só; um assunto novo começa uma peça nova. Os dois extremos são \
igualmente errados: fatiar um assunto contínuo em peças de uma ou duas \
páginas, e juntar assuntos distintos numa peça gigante que obriga a ler \
tudo para achar qualquer coisa.
- O "summary" é o que será lido para decidir se vale abrir esta página. \
Escreva-o para responder "o que exatamente está aqui": cite os nomes, \
números, exames, artigos ou temas que aparecem no trecho. Um resumo \
genérico ("continuação do texto", "informações diversas") torna a peça \
inútil no índice.
- Preencha "type" sempre que o documento permitir reconhecê-lo, usando os \
tipos que fazem sentido para ESTE acervo (veja o contexto acima, quando \
houver). Use null apenas quando o trecho realmente não permitir dizer o \
que é.

Texto da janela:
{text}
"""


class OllamaConnectionError(Exception):
    """Ollama did not respond on 127.0.0.1:11434 — reason to fall back to
    the `rules` engine, never to bring the run down."""


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
            start_in_background([ollama_path, "serve"], env=server_environment())
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


def model_to_use(conn: sqlite3.Connection | None, config: ProjectConfig) -> str:
    """Model the 'local' engine will use.

    The user's choice in the form wins; `DEFAULT_LOCAL_MODEL` is just the
    default. This function used to ignore `config.local_model` and always
    return the default — the selector on the screen was decorative. It
    started to matter when the user asked to compare the quality of
    different models, which is impossible if every run uses the same one.
    """
    chosen = (config.local_model or "").strip()
    if chosen and chosen != "automatic":
        return chosen
    return DEFAULT_LOCAL_MODEL


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
    """Tokens to reserve for the answer. `page_count` of 0 means the ranges
    mode, whose reply does not grow with the window."""
    if page_count <= 0:
        return _RESPONSE_TOKENS
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


def context_tokens_for(prompt: str, model_limit: int = 0, page_count: int = 0) -> int:
    """Context size to request for `prompt`.

    Never below Ollama's own default, so this can only ever widen the
    window, never narrow it; never above what the model itself supports,
    when that is known.

    `page_count` is the number of pages the answer has to describe, in the
    per-page mode — the reply grows with it, and a budget that does not
    grow along truncates the answer (see `_RESPONSE_TOKENS_PER_PAGE`).
    """
    estimated = int(len(prompt) / _CHARS_PER_TOKEN) + _response_tokens_for(page_count)
    rounded = -(-estimated // _CONTEXT_GRANULARITY) * _CONTEXT_GRANULARITY
    wanted = max(_OLLAMA_DEFAULT_CONTEXT, rounded)
    if model_limit and model_limit > 0:
        wanted = min(wanted, model_limit)
    return wanted


@dataclass
class LocalEngine:
    model: str
    url_base: str = OLLAMA_BASE_URL
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
    # "uma linha por página" em vez de "enumere as faixas". Ver
    # `_PAGE_PROMPT`: modelos pequenos leem bem uma página e erram a
    # aritmética de um particionamento, e a cobertura do índice é o
    # requisito que não admite erro.
    per_page: bool = True
    # Warnings from the last call to `classify()` — items rejected because of
    # an unrecognized reference (Defect 3, Phase 13). `classify_pending`
    # reads this right after calling `classify()` to record an event; it is
    # not part of the common `ClassificationEngine` interface (only
    # `LocalEngine` exposes it). Each entry is (i18n key, params) — Task 12
    # (Phase 14) — rendered by `_log_rejection_warnings`, not pre-rendered
    # text, so the final log event follows the interface's language.
    last_window_warnings: list[tuple[str, dict]] = field(default_factory=list)
    # Filled by `plan_gpu_use()` on the first window and reused after that:
    # the measurement costs two HTTP calls plus a performance counter read,
    # and neither the card's capacity nor the model changes during a run.
    gpu_plan: dict | None = field(default=None, repr=False)
    _planned: bool = field(default=False, repr=False)

    def plan_gpu_use(self, prompt: str, page_count: int = 0) -> dict | None:
        """Replaces `num_gpu = -1` with a measured layer count.

        Called once per run, with the first window's prompt as the sample
        for how wide the context has to be. Returns the details of the
        decision (for the log) or `None` when nothing could be measured and
        the previous behaviour stands.

        Never runs in "cpu" mode (`num_gpu == 0`): that is the user asking
        for the CPU on purpose, and no measurement overrides it.
        """
        if self._planned or self.num_gpu == 0:
            return self.gpu_plan
        self._planned = True

        try:
            from .gpu_budget import plan

            context = context_tokens_for(prompt, page_count=page_count)
            layers, details = plan(self.model, self.url_base, context)
        except Exception:
            # A measurement that fails must cost nothing: the run carries
            # on with `-1`, exactly as it did before this existed.
            return None

        self.num_ctx = context
        if layers is not None:
            self.num_gpu = layers
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
        prompt = _build_page_prompt(pages, self.config)
        self.plan_gpu_use(prompt, page_count=len(pages))
        rows = _pages_json(self._generate(prompt))

        faltantes = max(0, len(pages) - len(rows))
        if faltantes:
            # Não é motivo para recusar nada — o agrupamento cobre a página
            # de qualquer modo. É registrado porque distingue um modelo que
            # respondeu sobre tudo de um que respondeu sobre metade.
            self.last_window_warnings.append((
                "log.local_engine.pages_missing_from_answer",
                {"missing": faltantes, "total": len(pages)},
            ))
        return _group_pages_into_items(pages, rows)

    def is_available(self) -> bool:
        request = urllib.request.Request(f"{self.url_base}/api/version", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=PING_TIMEOUT_S) as response:
                response.read()
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def classify(self, pages: list[WindowPage]) -> list[ClassifiedItem]:
        if self.per_page:
            return self.classify_per_page(pages)
        prompt = _build_prompt(pages, self.config)
        self.plan_gpu_use(prompt)
        response_text = self._generate(prompt)
        raw_items = _extract_items_json(response_text)
        reference_map = _reference_map(pages)

        items: list[ClassifiedItem] = []
        warnings: list[tuple[str, dict]] = []
        for raw in raw_items:
            item = _dict_to_item(raw, pages, reference_map)
            if item is None:
                reason = _reference_rejection_reason(raw, reference_map)
                if reason:
                    warnings.append(reason)
                continue
            items.append(item)

        if raw_items and len(warnings) == len(raw_items):
            warnings.append((
                "log.local_engine.all_items_rejected",
                {"model": self.model, "count": len(raw_items)},
            ))

        self.last_window_warnings = warnings
        return items

    def _generate(self, prompt: str) -> str:
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
                "format": "json",
                # Turns off the "thinking" channel for models that have it
                # (e.g. qwen3, qwen3.5): without this, those models dump the
                # whole answer into `thinking` and return an empty
                # `response` — the engine only read `response`, so every
                # window silently turned into 0 items (Defect 3, Phase 13;
                # confirmed by running the real prompt against qwen3.5:9b).
                # Top-level Ollama field, not under `options`; models without
                # this capability (e.g. gemma4:e4b) ignore it with no effect.
                "think": False,
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
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise OllamaConnectionError(f"{self.url_base}: {exc}") from exc
        # Second safety net for the same "thinking" problem above: if for
        # some reason (model ignores `think`, old Ollama version) the text
        # still comes back in `thinking` with an empty `response`, use it
        # instead of treating the answer as empty.
        return data.get("response") or data.get("thinking") or ""


# How each `collection_type` reads in the prompt. The stored values are
# internal keys, and handing "processo" to the model as-is says less than
# the sentence it stands for.
_COLLECTION_TYPE_TEXT = {
    "processo": "processo/dossiê: peças numeradas por folha, em ordem cronológica de juntada",
    "biblioteca": "biblioteca/acervo bibliográfico: obras e documentos independentes entre si",
}

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

    What that cost is measurable. A real collection of postgraduate course
    material was classified by a prompt whose only worked examples were
    "OFÍCIO, MEMORANDO, PARECER": 1432 of 1445 items came back with no type
    at all, because those examples describe an administrative case file and
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

    lines: list[str] = []
    subject = _clip(getattr(config, "subject", "") or "")
    if subject:
        lines.append(f"- Assunto do acervo: {subject}")

    collection_type = getattr(config, "collection_type", "") or ""
    description = _COLLECTION_TYPE_TEXT.get(collection_type)
    if description:
        lines.append(f"- Natureza do acervo: {description}")

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


def _build_prompt(pages: list[WindowPage], config: ProjectConfig | None = None) -> str:
    blocks = [f"--- {page.reference} ({page.file_name}) ---\n{page.text}" for page in pages]
    return _PROMPT.format(context=build_context(config), text="\n\n".join(blocks))


def _extract_items_json(response_text: str) -> list[dict]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


_ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHEET_PREFIX_REGEX = re.compile(r"^fl\.?")

# The reference at the start of what the model returned, ignoring anything
# it appended. Each page is presented as `--- f. 2 (Arquivo.pdf) ---`, and
# a model that copies the whole label back — `"ref_start": "f. 2
# (Arquivo.pdf)"` — has identified the page correctly and written it in a
# form that exact-string matching rejects. Measured: with the improved
# prompt, `qwen3:8b` returned one item spanning f. 2 to f. 16 (the whole
# document, exactly as asked) and every single one was discarded for this,
# leaving a window with zero items and no visible reason.
_REFERENCE_HEAD_REGEX = re.compile(r"^\s*((?:f|fl|p|pag|pág)\.?\s*\d+)", re.IGNORECASE)


def _normalize_reference(reference: str) -> str:
    """Comparison key tolerant of case, spacing, the alternate abbreviation
    'fl.' (folha) for 'f.', and anything the model appended after the
    reference itself.

    The model may return 'F. 1', 'f.1' or 'fl. 1' for the same 'f. 1'
    reference in the window, and comparing by exact string equality used to
    silently discard the whole item (Defect 3, Phase 13). It may also
    return 'f. 1 (Contrato.pdf)', echoing the label the page was presented
    under — also a correct identification, and also discarded.

    Never merges different prefixes: 'f. 1' and 'p. 1' remain distinct
    references, on purpose.
    """
    head = _REFERENCE_HEAD_REGEX.match(reference or "")
    text = head.group(1) if head else (reference or "")
    text = re.sub(r"\s+", "", text.strip().lower())
    return _SHEET_PREFIX_REGEX.sub("f.", text)


# --- modo "uma linha por página" -------------------------------------------
#
# Por que existe um segundo prompt.
#
# O prompt principal pede FAIXAS: "devolva as peças, cada uma de ref_start a
# ref_end". Isso obriga o modelo a fazer contabilidade — enumerar intervalos
# que, somados, cubram exatamente as páginas da janela, sem buraco e sem
# sobreposição. Medido em dois benchmarks sobre um laudo de 31 páginas:
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
_PAGE_PROMPT = """\
Você é um indexador de um acervo documental.
{context}
Abaixo estão {count} páginas de um trecho do acervo, NUMERADAS de 1 a \
{count}.

Para CADA uma das {count} páginas, devolva um objeto. Exatamente {count} \
objetos, na mesma ordem. Responda SOMENTE com um objeto JSON neste formato:

{{"pages": [
  {{"n": <o NÚMERO da página, de 1 a {count} — apenas o número, nada mais>,
   "subject": "<o assunto desta página: o exame, o documento, a seção ou o \
tema tratado nela>",
   "type": "<tipo em MAIÚSCULAS adequado a este acervo, ou null>",
   "date": "<AAAA-MM-DD, se a página trouxer uma data, senão null>",
   "author": "<autor/responsável, se a página disser, senão null>",
   "detail": "<uma ou duas frases dizendo o que exatamente está nesta \
página: nomes, números, exames, artigos, temas>",
   "continues": <true se esta página continua o MESMO assunto da anterior, \
false se começa um assunto novo>,
   "has_table": <true ou false>,
   "has_image": <true ou false>}}
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


def _build_page_prompt(pages: list[WindowPage], config: ProjectConfig | None = None) -> str:
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
    return _PAGE_PROMPT.format(
        context=build_context(config), count=len(pages), text="\n\n".join(blocks)
    )


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


def _subject_key(subject: object) -> str:
    """Forma comparável de um assunto: minúsculas, sem pontuação nem
    palavras vazias. Duas páginas do mesmo exame escrito com pontuação
    diferente têm de casar."""
    if not isinstance(subject, str):
        return ""
    limpo = "".join(c if c.isalnum() or c.isspace() else " " for c in subject.lower())
    palavras = [p for p in limpo.split() if p not in _SUBJECT_NOISE]
    return " ".join(palavras)


def _same_topic_start(a: str, b: str, palavras: int = 2) -> bool:
    """Se dois assuntos começam pelas mesmas palavras significativas.

    É o que separa "Hemograma série vermelha" de "Hemograma série branca"
    (mesmo documento, redação diferente) de "Hemograma" e "Ferritina"
    (documentos diferentes).
    """
    return bool(a) and bool(b) and a.split()[:palavras] == b.split()[:palavras]


def _group_pages_into_items(
    pages: list[WindowPage], rows: list[dict], model_engine: str = "local"
) -> list[ClassifiedItem]:
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
    por_indice: dict[int, dict] = {}
    sem_numero: list[dict] = []
    for row in rows:
        numero = row.get("n")
        if isinstance(numero, str) and numero.strip().isdigit():
            numero = int(numero.strip())
        if isinstance(numero, int) and not isinstance(numero, bool) and 1 <= numero <= len(pages):
            por_indice.setdefault(numero - 1, row)
        else:
            sem_numero.append(row)

    for posicao, row in enumerate(sem_numero):
        por_indice.setdefault(posicao, row)

    itens: list[ClassifiedItem] = []
    atual: list[tuple[WindowPage, dict]] = []

    def fechar():
        if not atual:
            return
        primeira, dados = atual[0][0], atual[0][1]
        ultima = atual[-1][0]
        detalhes = [str(d.get("detail") or d.get("subject") or "").strip() for _p, d in atual]
        detalhes = [d for d in detalhes if d]
        # Sem detalhe nenhum vindo do modelo, o texto da própria página
        # ainda leva a busca ao lugar certo.
        if not detalhes:
            bruto = " ".join(" ".join(p.text.split()) for p, _d in atual).strip()
            detalhes = [bruto[:_FALLBACK_SUMMARY_CHARS]] if bruto else []
        resumo = " ".join(dict.fromkeys(detalhes))[:_SUMMARY_CHAR_LIMIT] or None

        assunto = str(dados.get("subject") or "").strip()
        if assunto and resumo and not resumo.lower().startswith(assunto.lower()[:20]):
            resumo = f"{assunto}: {resumo}"[:_SUMMARY_CHAR_LIMIT]

        confianca = "high" if dados.get("type") and dados.get("detail") else "medium"
        itens.append(ClassifiedItem(
            start_ref=primeira.reference,
            end_ref=ultima.reference,
            start_order=reference_number(primeira.reference),
            end_order=reference_number(ultima.reference),
            type=str(dados["type"]).strip() if dados.get("type") else None,
            date=str(dados["date"]).strip() if dados.get("date") else None,
            author=str(dados["author"]).strip() if dados.get("author") else None,
            summary=resumo,
            has_table=any(bool(d.get("has_table")) or p.has_table for p, d in atual),
            has_image=any(bool(d.get("has_image")) or bool(p.image_count) for p, d in atual),
            engine=model_engine,
            confidence=confianca,
            files=sorted({p.file_name for p, _d in atual}),
        ))
        atual.clear()

    anterior_assunto = None
    for indice, page in enumerate(pages):
        dados = por_indice.get(indice, {})
        assunto = _subject_key(dados.get("subject"))

        # O agrupamento é decidido pelo ASSUNTO, não pelo `continues` que o
        # modelo devolve. Medido: `qwen3.5:4b` identificou impecavelmente os
        # oito exames de uma janela — Hemograma, Ferritina, Metabolismo do
        # Ferro, Vitamina B-12, Protrombina, Ureia, Creatinina — e marcou
        # `continues: true` em todos, porque entendeu "continua o mesmo
        # laudo" e não "o mesmo assunto". A pergunta era ambígua e a
        # resposta, previsível: comparar dois rótulos é trabalho de código.
        #
        # `continues` continua servindo para o caso em que o assunto muda de
        # redação sem mudar de documento ("Hemograma — série vermelha" /
        # "Hemograma — série branca"): aí ele desempata, desde que o começo
        # do assunto coincida.
        if not atual:
            continua = False
        elif assunto and anterior_assunto:
            continua = assunto == anterior_assunto or (
                bool(dados.get("continues")) and _same_topic_start(assunto, anterior_assunto)
            )
        else:
            # Sem assunto de um dos lados, só o sinal do modelo resta.
            continua = bool(dados.get("continues"))

        if atual and not continua:
            fechar()
        atual.append((page, dados))
        if assunto:
            anterior_assunto = assunto
    fechar()
    return itens

def _reference_map(pages: list[WindowPage]) -> dict[str, tuple[str, int]]:
    """Normalized reference -> (original reference in the window, numeric
    order). Uses `setdefault` so that, in the rare case where two window
    references collide after normalization, the first one (lower order)
    wins."""
    reference_map: dict[str, tuple[str, int]] = {}
    for page in pages:
        reference_map.setdefault(
            _normalize_reference(page.reference), (page.reference, reference_number(page.reference))
        )
    return reference_map


def _reference_rejection_reason(
    raw: dict, reference_map: dict[str, tuple[str, int]]
) -> tuple[str, dict] | None:
    """(i18n key, params) for a raw item rejected because of an unrecognized
    reference in the window — logging only (`_dict_to_item` is what
    actually decides whether the item is accepted). Returns `None` when the
    item was not rejected because of the reference (missing fields, or valid
    references out of order)."""
    start_ref = raw.get("ref_start")
    end_ref = raw.get("ref_end")
    if not isinstance(start_ref, str) or not isinstance(end_ref, str):
        return None
    if _normalize_reference(start_ref) in reference_map and _normalize_reference(end_ref) in reference_map:
        return None

    expected = ", ".join(sorted({ref for ref, _ in reference_map.values()}))
    return (
        "log.local_engine.reference_rejected",
        {"start": repr(start_ref), "end": repr(end_ref), "expected": expected},
    )


def _dict_to_item(
    raw: dict, pages: list[WindowPage], reference_map: dict[str, tuple[str, int]] | None = None
) -> ClassifiedItem | None:
    """Converts the raw item returned by the model, rejecting a reference
    that does not actually exist in the window (hallucination) — same spirit
    as section 7's validation, applied right at the engine's output. The
    comparison is tolerant of case, spacing and the 'fl.' abbreviation (see
    `_normalize_reference`) — without this, a model returning 'F. 1'
    instead of 'f. 1' had the whole item discarded, even though the
    reference existed."""
    raw_start_ref = raw.get("ref_start")
    raw_end_ref = raw.get("ref_end")
    if not isinstance(raw_start_ref, str) or not isinstance(raw_end_ref, str):
        return None

    reference_map = reference_map if reference_map is not None else _reference_map(pages)
    start_key = _normalize_reference(raw_start_ref)
    end_key = _normalize_reference(raw_end_ref)
    if start_key not in reference_map or end_key not in reference_map:
        return None

    start_ref, start_order = reference_map[start_key]
    end_ref, end_order = reference_map[end_key]
    if start_order > end_order:
        return None

    item_pages = [p for p in pages if start_order <= reference_number(p.reference) <= end_order]
    files = list(dict.fromkeys(p.file_name for p in item_pages))

    type_ = raw.get("type")
    if not isinstance(type_, str):
        type_ = None

    date_value = raw.get("date")
    if not (isinstance(date_value, str) and _ISO_DATE_REGEX.match(date_value)):
        date_value = None
    else:
        try:
            date.fromisoformat(date_value)
        except ValueError:
            date_value = None

    author = raw.get("author") if isinstance(raw.get("author"), str) else None
    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else None

    confidence = raw.get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"  # engine did not report it properly -> treat with suspicion

    return ClassifiedItem(
        start_ref=start_ref,
        end_ref=end_ref,
        start_order=start_order,
        end_order=end_order,
        type=type_,
        date=date_value,
        author=author,
        summary=summary,
        has_table=bool(raw.get("has_table")) or any(p.has_table for p in item_pages),
        has_image=bool(raw.get("has_image")) or any(p.image_count > 0 for p in item_pages),
        engine="local",
        confidence=confidence,
        files=files,
    )


@dataclass
class LocalClassificationResult:
    windows_processed: int = 0
    windows_via_rules_fallback: int = 0
    items_generated: int = 0
    invalid_items: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0


def _log_rejection_warnings(
    conn: sqlite3.Connection, local_engine: LocalEngine, window_key: str, language: str | None = None
) -> None:
    """Logs (at `aviso` level) every item rejected because of an unrecognized
    reference in the last call to `local_engine.classify()` — before, that
    discard was silent: the real run with qwen3.5:9b ended with 0 items and
    no clue in the log (Defect 3, Phase 13).

    `reason` is `nested(warning_key, **warning_params)` (Task 12, Phase
    14), not pre-translated text — it stays retranslatable along with the
    rest of the event on a later read (`list_events`), see `nested()`'s
    docstring in `i18n.py`."""
    for warning_key, warning_params in local_engine.last_window_warnings:
        record_event(
            conn, "classification", "warning", "log.local_engine.window_rejection",
            {"window": window_key, "reason": nested(warning_key, **warning_params)}, language=language,
        )


# Quantos caracteres do texto da página entram no resumo de emergência de
# uma peça de cobertura. O bastante para alguém reconhecer o que há ali e
# decidir abrir a página; curto o bastante para o índice continuar sendo um
# índice, e não uma cópia do acervo.
_FALLBACK_SUMMARY_CHARS = 300

# Teto do resumo de uma peça. O índice inteiro precisa caber no contexto de
# um projeto do Claude, e é a soma destes resumos que o ocupa — um resumo
# sem limite transformaria o índice numa segunda cópia do acervo, que é
# exatamente o que ele existe para evitar.
_SUMMARY_CHAR_LIMIT = 600


def _uncovered_pages(pages: list[WindowPage], items: list[ClassifiedItem]) -> list[WindowPage]:
    """Páginas da janela que nenhuma peça cobre, na ordem em que aparecem."""
    coberto: set[int] = set()
    for item in items:
        for numero in range(item.start_order, item.end_order + 1):
            coberto.add(numero)
    faltando = []
    for page in pages:
        numero = reference_number(page.reference)
        if numero not in coberto:
            faltando.append(page)
    return faltando


def _coverage_items(pages: list[WindowPage]) -> list[ClassifiedItem]:
    """Peças de cobertura para páginas que o modelo deixou de fora.

    Existe por causa do requisito central deste sistema: o índice é lido
    para encontrar *em que PDF e em que página* está uma informação, e uma
    página ausente do índice é informação que ninguém mais encontra. Um
    prompt pode pedir cobertura total; só o código pode garanti-la.

    Medido no benchmark que motivou isto: sobre um laudo de 31 páginas,
    três modelos diferentes (`gemma4:e4b`, `qwen3:8b`, `qwen3.5:9b`)
    devolveram de 0 a 3 peças cobrindo no máximo 9,7% das páginas — todas
    com confiança "high". Não é um modelo ruim; é o que acontece quando se
    pede agrupamento sem exigir cobertura.

    Estas peças são deliberadamente honestas sobre o que são: confiança
    "low", tipo nulo, e um resumo tirado do início da própria página. Elas
    não fingem uma classificação que não houve — garantem que a página
    exista no índice, com sua referência e seu arquivo, para que a busca
    chegue nela.

    Páginas consecutivas são agrupadas numa peça só, para não inchar o
    índice com uma linha por página quando um bloco inteiro ficou de fora.
    """
    if not pages:
        return []

    blocos: list[list[WindowPage]] = [[pages[0]]]
    for anterior, page in zip(pages, pages[1:]):
        if reference_number(page.reference) == reference_number(anterior.reference) + 1:
            blocos[-1].append(page)
        else:
            blocos.append([page])

    itens: list[ClassifiedItem] = []
    for bloco in blocos:
        texto = " ".join(" ".join(p.text.split()) for p in bloco).strip()
        resumo = texto[:_FALLBACK_SUMMARY_CHARS].rstrip()
        if len(texto) > _FALLBACK_SUMMARY_CHARS:
            resumo += "…"
        itens.append(ClassifiedItem(
            start_ref=bloco[0].reference,
            end_ref=bloco[-1].reference,
            start_order=reference_number(bloco[0].reference),
            end_order=reference_number(bloco[-1].reference),
            type=None,
            date=None,
            author=None,
            summary=resumo or None,
            has_table=any(p.has_table for p in bloco),
            has_image=any(p.image_count for p in bloco),
            engine="local",
            confidence="low",
            files=sorted({p.file_name for p in bloco}),
        ))
    return itens


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
        },
        language=language,
    )
    return True


def classify_pending(
    conn: sqlite3.Connection,
    config: ProjectConfig,
    local_engine: LocalEngine | None = None,
    should_stop=None,
    language: str | None = None,
) -> LocalClassificationResult:
    """Classifies every `pending` window with the `local` engine. If Ollama
    does not respond — at the start or partway through the run — falls back
    to the `rules` engine for the remaining windows, with a warning, without
    bringing anything down."""
    result = LocalClassificationResult()

    if local_engine is None:
        local_engine = LocalEngine(
            model=model_to_use(conn, config), num_gpu=_num_gpu_for(config.processing_mode),
            config=config,
        )

    rules_fallback_engine = RulesEngine(load_rules())
    ollama_available = local_engine.is_available()

    if not ollama_available:
        ollama_available = _try_restart_ollama(conn, local_engine, language=language)

    jsonl_path = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    pending_windows = conn.execute("SELECT * FROM window WHERE status = 'pending' ORDER BY id").fetchall()
    gpu_plan_logged = False

    with open(jsonl_path, "a", encoding="utf-8") as jsonl_file:
        for window in pending_windows:
            if should_stop is not None and should_stop():
                break

            pages = load_window_pages(conn, window)

            items = []
            if ollama_available:
                try:
                    items = local_engine.classify(pages)
                    if not gpu_plan_logged:
                        gpu_plan_logged = _log_gpu_plan(conn, local_engine, language=language)
                    _log_rejection_warnings(conn, local_engine, window["key"], language=language)
                except OllamaConnectionError as exc:
                    record_event(
                        conn, "classification", "warning", "log.local_engine.connection_lost",
                        {"error": str(exc)}, language=language,
                    )
                    ollama_available = _try_restart_ollama(conn, local_engine, language=language)
                    if ollama_available:
                        try:
                            items = local_engine.classify(pages)
                            _log_rejection_warnings(conn, local_engine, window["key"], language=language)
                        except OllamaConnectionError:
                            ollama_available = False

            if not ollama_available:
                items = rules_fallback_engine.classify(pages)
                result.windows_via_rules_fallback += 1

            # Garantia de cobertura (requisito central: nada pode faltar do
            # índice). Feita aqui, e não dentro de `classify`, para valer
            # também quando a janela falhou e caiu no motor de regras.
            faltando = _uncovered_pages(pages, items)
            if faltando:
                items = items + _coverage_items(faltando)
                record_event(
                    conn, "classification", "warning", "log.local_engine.coverage_filled",
                    {"window": window["key"], "pages": len(faltando)}, language=language,
                )

            for item in items:
                item_dict = item_to_dict(item, window["key"], window["group_key"])
                errors = validate_item(item_dict)
                if errors:
                    result.invalid_items += 1
                    record_event(
                        conn, "classification", "error", "log.local_engine.invalid_item",
                        {"engine": item.engine, "window": window["key"], "errors": "; ".join(errors)},
                        language=language,
                    )
                    continue

                jsonl_file.write(json.dumps(item_dict, ensure_ascii=False) + "\n")
                result.items_generated += 1
                if item.confidence == "high":
                    result.high_confidence += 1
                elif item.confidence == "medium":
                    result.medium_confidence += 1
                else:
                    result.low_confidence += 1

            conn.execute("UPDATE window SET status = 'done' WHERE id = ?", (window["id"],))
            conn.commit()
            result.windows_processed += 1

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

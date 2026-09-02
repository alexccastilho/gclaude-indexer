# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Filling the GPU before spilling into RAM (explicit user request).

`options.num_gpu = -1` reads as "use as much GPU as possible", and it is
what this project sent to Ollama until now. It does not do what the name
suggests. `-1` hands the decision to Ollama's own scheduler, which is
deliberately conservative: it sizes the KV cache for
`OLLAMA_NUM_PARALLEL` concurrent requests (4 by default on the versions
this runs against — four times the cache this single-threaded classifier
will ever use), keeps a safety margin on top, and rounds *down* to a whole
number of layers. On a card with several GB free, the measured result is
exactly what was reported: a model split between GPU and RAM with VRAM left
unused, running at CPU speed for the layers that spilled.

Two independent things fix that, and this module does both:

1. **Server settings** (`server_environment()`). `num_gpu` is a per-request
   option, but the sizes that decide how much fits are per-*server*
   environment variables, read once by `ollama serve` at startup. One
   loaded model, one parallel slot, flash attention on and a quantised KV
   cache typically free enough VRAM for several more layers, with no effect
   on output — the cache holds attention state, not the answer.

2. **An explicit layer count** (`layers_that_fit()`). Rather than asking
   for "as many as fit" and accepting the scheduler's margin, this measures
   what is actually free on the card right now, models the memory the run
   will need, and asks for a specific number of layers. When everything
   fits, that number is every layer — the whole model on the GPU, nothing
   in RAM.

Both degrade to today's behaviour, never to a worse one. Any missing piece
— no GPU, Ollama not answering, a model whose metadata we cannot read —
returns `None` from `layers_that_fit()` and the caller sends `-1` exactly
as before. An estimate is only ever used to ask for *fewer* layers than
"everything"; it can never make a model that fits refuse to load.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

MB = 1024 * 1024

# Room left on the card for what this model does not account for: the
# compute graph, the display itself, the compositor, and whatever else the
# desktop is drawing. Deliberately generous — the cost of overestimating it
# is a couple of layers in RAM, the cost of underestimating it is an
# out-of-memory failure mid-run, which is the one outcome this must never
# cause.
SAFETY_MARGIN_MB = 640

# Bytes per KV cache element, by `OLLAMA_KV_CACHE_TYPE`.
_KV_ELEMENT_BYTES = {"f16": 2, "q8_0": 1, "q4_0": 0.5}

# What `ollama serve` is started with. Read once by the server at startup —
# setting them per request has no effect.
SERVER_ENVIRONMENT = {
    # One model resident at a time. The default lets a second model stay
    # loaded, holding VRAM this run cannot use.
    "OLLAMA_MAX_LOADED_MODELS": "1",
    # One request at a time, which is what this classifier does: windows are
    # sent one after another. The default (4) sizes the KV cache for four
    # concurrent requests, so three quarters of it is reserved for
    # concurrency that never happens — the single largest source of VRAM
    # left on the table here.
    "OLLAMA_NUM_PARALLEL": "1",
    # Halves the KV cache again, with no measurable effect on
    # classification: the cache holds attention state between tokens, not
    # the produced text.
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    # Ollama's own extra reserve on top of everything above. This module
    # already keeps `SAFETY_MARGIN_MB` out of the budget it computes;
    # leaving Ollama's default reserve on top of ours would subtract the
    # same margin twice.
    "OLLAMA_GPU_OVERHEAD": "0",
    # Keeps the model resident between windows. Without it Ollama unloads
    # after five idle minutes and the next window pays the full load again
    # — on a long collection that is minutes of reloading, and it also
    # makes VRAM usage look like it drops to zero for no reason.
    "OLLAMA_KEEP_ALIVE": "30m",
}


@dataclass
class ModelShape:
    """What a model needs, in the terms the fit calculation uses."""

    total_bytes: int          # size of the weights on disk
    layer_count: int          # transformer blocks (`block_count`)
    embedding_length: int = 0
    head_count: int = 0
    head_count_kv: int = 0
    context_length: int = 0   # what the model itself supports

    @property
    def bytes_per_layer(self) -> float:
        """Weights divided over the layers, plus one for the embedding and
        output tensors, which Ollama also places on the GPU and which are
        roughly a layer's worth on the models used here."""
        divisor = max(1, self.layer_count + 1)
        return self.total_bytes / divisor

    def kv_bytes_per_token(self, cache_element_bytes: float) -> float:
        """KV cache for one token, across every layer.

        `2 *` because both keys and values are cached. Falls back to 0 when
        the metadata needed is missing — the caller then works with weights
        alone, which underestimates rather than overestimates what fits,
        and `SAFETY_MARGIN_MB` absorbs it.
        """
        if not (self.embedding_length and self.head_count and self.head_count_kv):
            return 0.0
        head_dimension = self.embedding_length / self.head_count
        return 2 * self.layer_count * self.head_count_kv * head_dimension * cache_element_bytes


def server_environment(base: dict | None = None) -> dict:
    """`base` (default: the current environment) plus the server settings.

    A value the user already set by hand wins: someone who exported
    `OLLAMA_NUM_PARALLEL` on their own machine meant it, and this is not
    the place to overrule them.
    """
    import os

    environment = dict(os.environ if base is None else base)
    for name, value in SERVER_ENVIRONMENT.items():
        environment.setdefault(name, value)
    return environment


def _get_json(url: str, payload: dict | None = None, timeout: float = 5.0) -> dict | None:
    """A GET/POST against Ollama that never raises. `None` on any failure."""
    try:
        if payload is None:
            request = urllib.request.Request(url, method="GET")
        else:
            request = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json"},
            )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


# Sub-model prefixes that appear alongside the language model's own keys in
# `model_info`. A multimodal model publishes `gemma4.block_count = 42` for
# the text model *and* `gemma4.audio.block_count = 12` for its audio tower —
# and the audio one comes first in the mapping. Matching by suffix alone
# picked up the wrong number (measured on `gemma4:e4b`: 12 layers instead of
# 42), which then made every byte-per-layer figure wrong by more than
# threefold.
_SUB_MODEL_SEGMENTS = (".audio.", ".vision.", ".clip.", ".mm.", ".projector.")


def _suffix_value(model_info: dict, suffix: str) -> int:
    """Reads the language model's `model_info` entry named `suffix`.

    Ollama prefixes every architectural key with the architecture itself
    (`gemma4.block_count`, `qwen35.block_count`, ...), so a lookup by full
    name would have to know the architecture of every model the user might
    pick. The architecture is read from `general.architecture` when it is
    there and used to build the exact key; failing that, the suffix match
    is kept but keys belonging to a vision or audio tower are skipped.
    """
    def usable(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    architecture = model_info.get("general.architecture")
    if isinstance(architecture, str) and architecture:
        exact = model_info.get(f"{architecture}.{suffix}")
        if usable(exact):
            return int(exact)

    for key, value in model_info.items():
        if not key.endswith(suffix) or not usable(value):
            continue
        if any(segment in key for segment in _SUB_MODEL_SEGMENTS):
            continue
        return int(value)
    return 0


def describe_model(model: str, url_base: str) -> ModelShape | None:
    """Reads `model`'s shape from Ollama. `None` when it cannot be read."""
    shown = _get_json(f"{url_base}/api/show", {"model": model})
    if not isinstance(shown, dict):
        return None
    model_info = shown.get("model_info")
    if not isinstance(model_info, dict):
        return None

    layer_count = _suffix_value(model_info, "block_count")
    if layer_count <= 0:
        return None

    total_bytes = _model_size_bytes(model, url_base)
    if total_bytes <= 0:
        return None

    head_count = _suffix_value(model_info, "attention.head_count")
    # `head_count_kv` absent (or published as null, as `qwen3.5:9b` does)
    # means the model is not using grouped-query attention: every attention
    # head has its own key/value pair, so the count is the head count. Left
    # at 0 it would silently zero the whole KV cache estimate.
    head_count_kv = _suffix_value(model_info, "attention.head_count_kv") or head_count

    return ModelShape(
        total_bytes=total_bytes,
        layer_count=layer_count,
        embedding_length=_suffix_value(model_info, "embedding_length"),
        head_count=head_count,
        head_count_kv=head_count_kv,
        context_length=_suffix_value(model_info, "context_length"),
    )


def _model_size_bytes(model: str, url_base: str) -> int:
    """The model's size on disk, from `/api/tags`.

    Matched by exact name first, then by the name without its tag: the user
    may have configured `gemma4:e4b` while the listing shows
    `gemma4:e4b` — or, after a pull by digest, only the bare family name.
    """
    listing = _get_json(f"{url_base}/api/tags")
    if not isinstance(listing, dict):
        return 0
    models = listing.get("models")
    if not isinstance(models, list):
        return 0

    wanted = model.strip()
    wanted_family = wanted.split(":", 1)[0]
    fallback = 0
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        size = entry.get("size")
        if not isinstance(size, (int, float)) or isinstance(size, bool) or size <= 0:
            continue
        if name == wanted:
            return int(size)
        if not fallback and name.split(":", 1)[0] == wanted_family:
            fallback = int(size)
    return fallback


def layers_that_fit(
    shape: ModelShape,
    free_vram_mb: int | None,
    context_tokens: int,
    cache_type: str = "q8_0",
    margin_mb: int = SAFETY_MARGIN_MB,
) -> int | None:
    """How many layers to put on the GPU, or `None` to let Ollama decide.

    Returns the model's full layer count (`layer_count + 1`, the value
    Ollama uses for "everything, including the output tensors") whenever
    everything fits — which is the common case on a machine that was sized
    for its model, and the one where the old `-1` was already correct.
    Returns a smaller number only when the model genuinely does not fit,
    and that number is deliberately larger than what Ollama's own default
    margin would have chosen.

    `None` — meaning "keep the previous behaviour" — whenever anything
    needed is missing or implausible, **and whenever the model does not fit
    whole**. That second case is a correction to this module's original
    design, and it was measured rather than reasoned:

        VRAM available   4712 MB
        this module asked for 18 of 43 layers
        Ollama had been placing 3108 MB of the model on the card
        after the change it placed 1849 MB

    In other words, the estimate replaced Ollama's own split with a *worse*
    one and slowed the run down — the opposite of what it exists for. The
    per-layer cost here is a division of the file size by the layer count,
    which is a rough figure; Ollama knows each tensor's real size. So the
    rule is now asymmetric on purpose: this module overrides `-1` only when
    it can say with certainty that **everything** fits, which is a claim
    the rough model is good enough to make. When the model has to be split,
    the scheduler that knows the true sizes decides, exactly as before.

    The VRAM actually freed for the GPU comes from `SERVER_ENVIRONMENT`
    (one parallel slot instead of four, a quantised KV cache, flash
    attention) — those enlarge the space Ollama has to work with, without
    second-guessing how it uses it.
    """
    if free_vram_mb is None or free_vram_mb <= 0 or shape.layer_count <= 0:
        return None

    budget_bytes = (free_vram_mb - margin_mb) * MB
    if budget_bytes <= 0:
        # Less free VRAM than the margin: there is no honest budget to
        # divide, and forcing layers onto a card this full is how a run
        # dies mid-collection. Ollama's own conservative split is the right
        # answer here.
        return None

    element_bytes = _KV_ELEMENT_BYTES.get(cache_type, 2)
    kv_per_token = shape.kv_bytes_per_token(element_bytes)
    kv_per_layer = (kv_per_token / shape.layer_count) * max(1, context_tokens) if kv_per_token else 0.0
    cost_per_layer = shape.bytes_per_layer + kv_per_layer
    if cost_per_layer <= 0:
        return None

    fitting = int(budget_bytes // cost_per_layer)

    # `layer_count + 1` is Ollama's own way of saying "every layer plus the
    # output tensors". Anything short of that is a split, and a split is
    # the scheduler's call, not ours — see the docstring.
    everything = shape.layer_count + 1
    return everything if fitting >= everything else None


def loaded_model_vram_mb(model: str, url_base: str) -> int:
    """VRAM currently held by `model` itself, in MB. 0 if it is not loaded.

    Needed because of a mistake this code made on its own first
    measurement: with the model already resident, the card's *free* VRAM
    excludes the very model we are about to size. Budgeting from that
    number asks for fewer layers than fit, Ollama reloads with that smaller
    split, less VRAM is then free, and the next run asks for fewer still —
    a ratchet that would quietly push a model off the GPU it was fitting on
    perfectly well. Measured here: 5.0 GB free with nothing loaded, 1.6 GB
    with `gemma4:e4b` resident, and the plan dropped from 19 layers to 4.
    """
    running = _get_json(f"{url_base}/api/ps")
    if not isinstance(running, dict):
        return 0
    wanted = model.strip()
    family = wanted.split(":", 1)[0]
    for entry in running.get("models") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if name != wanted and name.split(":", 1)[0] != family:
            continue
        in_vram = entry.get("size_vram")
        if isinstance(in_vram, (int, float)) and not isinstance(in_vram, bool):
            return max(0, int(in_vram) // MB)
    return 0


def free_vram_mb(model: str | None = None, url_base: str = "") -> int | None:
    """VRAM available to this run, in MB, or `None` when unmeasurable.

    Reads the same counters the Run screen's GPU box already shows, so a
    user comparing the two never sees two different numbers for the same
    card — plus whatever `model` is already holding, which is space this
    run gets to reuse rather than compete with (see
    `loaded_model_vram_mb`).
    """
    try:
        from .windows_counters import vram_total_mb, vram_used_mb

        total = vram_total_mb()
        used = vram_used_mb()
    except Exception:
        return None
    if total is None or total <= 0:
        return None
    if used is None:
        used = 0

    free = max(0, int(total) - int(used))
    if model and url_base:
        try:
            free += loaded_model_vram_mb(model, url_base)
        except Exception:
            pass  # a measurement that fails must not shrink the budget
    return min(free, int(total))


def plan(model: str, url_base: str, context_tokens: int) -> tuple[int | None, dict]:
    """`(num_gpu, details)` for one classification run.

    `num_gpu` is `None` when the caller should keep sending `-1`.
    `details` carries what went into the decision, for the log event that
    tells the user how their card is being used — this is the number they
    asked to be able to see.
    """
    details: dict = {"model": model, "context_tokens": context_tokens}

    free_mb = free_vram_mb(model, url_base)
    details["free_vram_mb"] = free_mb

    shape = describe_model(model, url_base)
    if shape is None:
        details["reason"] = "sem_metadados"
        return None, details

    details["layers_total"] = shape.layer_count + 1
    details["model_mb"] = shape.total_bytes // MB
    cache_type = SERVER_ENVIRONMENT["OLLAMA_KV_CACHE_TYPE"]
    layers = layers_that_fit(shape, free_mb, context_tokens, cache_type=cache_type)

    # Whether the weights alone could ever fit, ignoring the context. This
    # is what tells a user that no amount of tuning will put this model on
    # this card — the answer is a smaller model, and the run has no other
    # way to find that out. Measured on the collection that prompted this
    # work: an 8 GB RX 5700 XT running a 9.1 GB model, 17% of it on the
    # card and the rest on the CPU, at roughly a minute per window.
    try:
        from .windows_counters import vram_total_mb

        total_mb = vram_total_mb()
    except Exception:
        total_mb = None
    if total_mb:
        details["vram_total_mb"] = int(total_mb)
        details["model_fits_card"] = (shape.total_bytes // MB) <= (int(total_mb) - SAFETY_MARGIN_MB)

    if layers is None:
        details["reason"] = "sem_vram_medida" if free_mb is None else "sem_orcamento"
        return None, details

    details["layers_on_gpu"] = layers
    details["fully_on_gpu"] = layers >= shape.layer_count + 1
    return layers, details

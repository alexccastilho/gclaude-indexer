# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Local Ollama: where it answers, the default model, and what it has.

The base of everything that talks to Ollama — the engine, the hardware
diagnosis, the About screen, the project form — so it depends on nothing
of theirs. The address is fixed loopback, never external configuration
(section 7). Everything reads `OLLAMA_BASE_URL` through this module at
call time: the test suite points it at a closed port (fase 37).

A connection failure returns an empty answer: the New project screen must
still open with Ollama stopped.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# By explicit user decision, the 'local' engine always uses this model, on
# any machine — the hardware table from section 10.2 (phase 7) still exists
# for diagnostics/reporting, but no longer decides the model used here. Only
# a manual choice in `modelo_local` (form) overrides this.
#
# Version 1.0.1 moved the default from `gemma4:e4b` to `qwen3.5:4b`, on the
# benchmark this project ran over the same windows of a 31-page document,
# every model fully resident on an 8 GB card:
#
#   qwen3.5:4b     3.0 GB   100% of types filled    30.8 s/window
#   gemma4:e4b     3.1 GB    79.5%                  38.5 s/window
#   qwen3.5:9b     5.3 GB    79.5%                  86.2 s/window
#   qwen3:8b       5.4 GB   100%                   108.8 s/window
#   granite4.2:8b  5.7 GB   100%                   116.9 s/window
#
# `qwen3.5:4b` wins on both axes at once — best quality, fastest — and it is
# also the smallest download by far: `gemma4:e4b` pulls ~9.6 GB from Ollama
# even though only ~3.1 GB is resident, so the switch cuts the first-run
# download roughly threefold and fits a 6 GB card as comfortably as an 8 GB
# one. `gemma4:e4b` remains selectable in the form for comparison; it is no
# longer downloaded by the installer.
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"


def installed_models(timeout_s: float = 2.0) -> list[dict] | None:
    """The `models` entries of Ollama's `/api/tags`, or `None` on any
    failure (Ollama stopped, unexpected response, timed out) — never raises."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TimeoutError):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None
    return [model for model in models if isinstance(model, dict)]


def list_installed_models(timeout_s: float = 2.0) -> list[str]:
    """Names of the models downloaded in local Ollama, alphabetically;
    `[]` when Ollama does not answer."""
    names = {
        model["name"]
        for model in installed_models(timeout_s) or []
        if isinstance(model.get("name"), str) and model["name"]
    }
    return sorted(names)


def model_downloaded_on_disk(name: str) -> bool:
    """`True` when the model's manifest is in the local store.

    The answer to "is this model downloaded" and the answer to "is Ollama
    running" are different questions, and `list_installed_models` can only
    answer the first by asking the second: it talks to the server, and a
    stopped server gives back an empty list that is indistinguishable from
    an empty machine.

    That cost a real user an afternoon. The model was downloaded — 3.2 GB
    of it, sitting in the store — the server was simply not up, and the
    About screen reported "missing" and offered to download it again.

    Ollama lays the store out as
    `models/manifests/<registry>/<namespace>/<model>/<tag>`, with
    `library` as the namespace for official models and `latest` as the
    implied tag. The registry is walked rather than named, so a model
    pulled from somewhere other than registry.ollama.ai still counts.
    """
    root = os.environ.get("OLLAMA_MODELS") or (Path.home() / ".ollama" / "models")
    manifests = Path(root) / "manifests"
    if not manifests.is_dir():
        return False

    reference, _, tag = name.partition(":")
    tag = tag or "latest"
    if "/" in reference:
        namespace, _, model = reference.rpartition("/")
    else:
        namespace, model = "library", reference

    try:
        for registry in manifests.iterdir():
            if (registry / namespace / model / tag).is_file():
                return True
    except OSError:
        return False
    return False

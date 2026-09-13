# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Models installed in Ollama on this machine, for the project form.

The address comes from `engine_local.OLLAMA_BASE_URL` — fixed loopback,
never from external configuration (section 7). A connection failure
returns an empty list: the New project screen must still open with Ollama
stopped.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from ..engine_local import DEFAULT_LOCAL_MODEL, OLLAMA_BASE_URL

__all__ = ["DEFAULT_LOCAL_MODEL", "list_installed_models", "model_downloaded_on_disk"]


def list_installed_models(timeout_s: float = 2.0) -> list[str]:
    """Names of the models downloaded in local Ollama, alphabetically.

    Returns `[]` on any failure (Ollama stopped, unexpected response, timed
    out) — never raises.
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TimeoutError):
        return []

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []

    names = {
        model["name"]
        for model in models
        if isinstance(model, dict) and isinstance(model.get("name"), str) and model["name"]
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

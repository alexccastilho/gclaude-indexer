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
import urllib.error
import urllib.request

from ..engine_local import DEFAULT_LOCAL_MODEL, OLLAMA_BASE_URL

__all__ = ["DEFAULT_LOCAL_MODEL", "list_installed_models"]


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

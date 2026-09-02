# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Loading and validation of the project configuration (spec section 6).

`ConfigError.errors` carries `(key, params)` pairs — translation keys plus
their format parameters, not rendered text — resolved to screen text by
whoever *displays* them (`web/app.py`, via `i18n.translate`), not by
whoever *raises* them (Task 18, Phase 14). Before this, `_validate()` built
plain Portuguese sentences directly (`f"{field} inválido: ..."`), which
`new_project.html` then showed verbatim under an otherwise-translated "Fix
before continuing" box, regardless of the interface's language. Keys, not
rendered text, because this module has no request-scoped language of its
own to render with — `load_config()`/`_validate()` run from CLI-style
callers too (see the tests), not only from a web request that has already
resolved a `language` cookie; only the display layer knows which of the
three to use. Same reasoning `events.py` documents for `record_event`
(Task 12) — this is that same pattern applied to validation errors.
`i18n.py` is core, not `web/`, so importing it here does not invert the
core → web dependency direction."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .parallelism import MODES as PARALLELISM_MODES
from .file_types import valid_categories
from .i18n import translate, DEFAULT_LANGUAGE

COLLECTION_TYPES = {"processo", "biblioteca"}
GROUP_MODES = {"subfolder", "name_pattern", "all_together"}
CLASSIFICATION_ENGINES = {"automatic", "rules", "local", "claude_code"}
# Explicit user request: an option to force CPU/RAM even with a GPU
# available, in addition to the automatic default (uses the GPU to the
# max, overflows to RAM). Only affects the 'local' engine — see
# `engine_local.py:_num_gpu_for`.
PROCESSING_MODES = {"automatic", "gpu", "cpu"}


@dataclass
class ConfigErrorMessage:
    """One validation problem: a `config_error.*` translation key plus its
    format parameters — not rendered text (see this module's docstring)."""

    key: str
    params: dict[str, object] = field(default_factory=dict)


class ConfigError(Exception):
    """Invalid project configuration. `errors` carries `ConfigErrorMessage`
    entries (key + params), rendered by the caller in its own language —
    see this module's docstring."""

    def __init__(self, errors: list[ConfigErrorMessage]):
        self.errors = errors
        # `str(exc)` is for logs/tracebacks, not the screen — rendered in
        # `DEFAULT_LANGUAGE` since there is no request-scoped language here.
        super().__init__(
            "; ".join(translate(DEFAULT_LANGUAGE, error.key, **error.params) for error in errors)
        )


@dataclass
class ProjectConfig:
    name: str
    source_folder: str
    output_folder: str
    subject: str = ""
    collection_type: str = "processo"
    group_mode: str = "subfolder"
    group_pattern: str = ""
    extensions: list[str] = field(default_factory=lambda: ["pdf", "docx", "imagens"])
    pages_per_block: int = 80
    pages_per_window: int = 16
    overlap: int = 2
    chars_per_page: int = 2000
    ocr_language: str = "por"
    classification_engine: str = "automatic"
    local_model: str = "automatic"
    processing_mode: str = "automatic"
    parallelism: str = "automatic"
    review_low_confidence: bool = False
    role_instructions: str = ""
    extra_rules: str = ""


def _validate(config: ProjectConfig) -> list[ConfigErrorMessage]:
    errors: list[ConfigErrorMessage] = []

    if not config.name or not config.name.strip():
        errors.append(ConfigErrorMessage("config_error.name_required"))

    if not config.source_folder or not config.source_folder.strip():
        errors.append(ConfigErrorMessage("config_error.source_folder_required"))
    else:
        folder = Path(config.source_folder)
        if not folder.exists():
            errors.append(
                ConfigErrorMessage("config_error.source_folder_not_found", {"path": config.source_folder})
            )
        elif not folder.is_dir():
            errors.append(
                ConfigErrorMessage(
                    "config_error.source_folder_not_a_directory", {"path": config.source_folder}
                )
            )

    if not config.output_folder or not config.output_folder.strip():
        errors.append(ConfigErrorMessage("config_error.output_folder_required"))

    if config.collection_type not in COLLECTION_TYPES:
        errors.append(
            ConfigErrorMessage(
                "config_error.collection_type_invalid",
                {"value": config.collection_type, "options": sorted(COLLECTION_TYPES)},
            )
        )

    if config.group_mode not in GROUP_MODES:
        errors.append(
            ConfigErrorMessage(
                "config_error.group_mode_invalid",
                {"value": config.group_mode, "options": sorted(GROUP_MODES)},
            )
        )

    if not config.extensions:
        errors.append(ConfigErrorMessage("config_error.extensions_empty"))
    else:
        unknown = set(config.extensions) - valid_categories()
        if unknown:
            errors.append(
                ConfigErrorMessage(
                    "config_error.extensions_unknown_category",
                    {"unknown": sorted(unknown), "options": sorted(valid_categories())},
                )
            )

    if config.group_mode == "name_pattern" and not config.group_pattern.strip():
        errors.append(ConfigErrorMessage("config_error.group_pattern_required"))

    if config.pages_per_block <= 0:
        errors.append(ConfigErrorMessage("config_error.pages_per_block_positive"))

    if config.pages_per_window <= 0:
        errors.append(ConfigErrorMessage("config_error.pages_per_window_positive"))

    if config.overlap < 0 or (
        config.pages_per_window > 0 and config.overlap >= config.pages_per_window
    ):
        errors.append(ConfigErrorMessage("config_error.overlap_invalid"))

    if config.chars_per_page <= 0:
        errors.append(ConfigErrorMessage("config_error.chars_per_page_positive"))

    if config.classification_engine not in CLASSIFICATION_ENGINES:
        errors.append(
            ConfigErrorMessage(
                "config_error.classification_engine_invalid",
                {"value": config.classification_engine, "options": sorted(CLASSIFICATION_ENGINES)},
            )
        )

    if config.processing_mode not in PROCESSING_MODES:
        errors.append(
            ConfigErrorMessage(
                "config_error.processing_mode_invalid",
                {"value": config.processing_mode, "options": sorted(PROCESSING_MODES)},
            )
        )

    if config.parallelism not in PARALLELISM_MODES:
        errors.append(
            ConfigErrorMessage(
                "config_error.parallelism_invalid",
                {"value": config.parallelism, "options": sorted(PARALLELISM_MODES)},
            )
        )

    return errors


def load_config(data: dict) -> ProjectConfig:
    """Merges `data` with section 6's defaults, validates and returns the configuration.

    Raises `ConfigError` with the full list of problems found.
    """
    valid_fields = ProjectConfig.__dataclass_fields__.keys()
    unknown_fields = set(data) - set(valid_fields)
    if unknown_fields:
        raise ConfigError(
            [ConfigErrorMessage("config_error.unknown_field", {"field": c}) for c in sorted(unknown_fields)]
        )

    try:
        config = ProjectConfig(**data)
    except TypeError as exc:
        # `str(exc)` is Python's own dataclass-constructor error text — always
        # in English regardless of the interface's language (it names a
        # keyword argument, not user-facing prose) — wrapped as the `detail`
        # parameter of a translated key rather than left as a bare string.
        raise ConfigError([ConfigErrorMessage("config_error.type_error", {"detail": str(exc)})])

    errors = _validate(config)
    if errors:
        raise ConfigError(errors)

    return config


def config_to_json(config: ProjectConfig) -> str:
    return json.dumps(asdict(config), ensure_ascii=False)

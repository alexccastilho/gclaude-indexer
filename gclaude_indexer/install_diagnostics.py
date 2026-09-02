# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Installation diagnostics (Phase 13, Task 13): checks whether the
system's external dependencies are present on this machine.

Exists for two consumers: the "About" screen (shows the user what is
missing and how to fix it, with no need to open a terminal) and
`install.ps1` (decides what to offer to install). Neither can hang because
of this — that's why every check is isolated and `check_installation()`
**never raises**, even if `tools.find`, Ollama or PowerShell fail in
unexpected ways.

Does not reimplement detection that already exists in another module: GPU
comes from `hardware.py` (`Win32_VideoController`/`nvidia-smi`), the models
installed in Ollama come from `web.ollama_models.list_installed_models`,
and the presence of the sensor DLLs comes from `sensors.dll_path`/
`unavailable_reason`.
"""

from __future__ import annotations

import shutil

from .hardware import _detect_nvidia_gpu, _detect_wmi_gpu
from .engine_local import DEFAULT_LOCAL_MODEL
from .i18n import DEFAULT_LANGUAGE, translate
from .sensors import DLL_NAME, dll_path, unavailable_reason
from .tools import find as find_tool
from .subprocess_utils import run_hidden
from .web.ollama_models import list_installed_models

_TESSERACT_COMMAND = (
    "winget install --id UB-Mannheim.TesseractOCR -e --silent "
    "--accept-package-agreements --accept-source-agreements"
)
_GHOSTSCRIPT_COMMAND = (
    "winget install --id ArtifexSoftware.GhostScript -e --silent "
    "--accept-package-agreements --accept-source-agreements"
)
_OLLAMA_COMMAND = (
    "winget install --id Ollama.Ollama -e --silent "
    "--accept-package-agreements --accept-source-agreements"
)
# `_TESSDATA_PT_COMMAND`/`_HARDWARE_SENSOR_DLLS_COMMAND` used to be fixed
# Portuguese sentences, always shown as-is regardless of the interface's
# language — the "About" screen's "How to resolve" column (Task 18, Phase
# 14). They are prose instructions, not a literal command to paste into a
# terminal like the three `winget install ...` above (which stay
# untranslated on purpose: a command is not prose, and "winget" itself is
# not a word to translate) — so each is now a thin wrapper around a
# `translate()` call, resolved per request in `_diagnose_tesseract`/
# `_diagnose_hardware_sensors` below.


def _tessdata_pt_command(language: str) -> str:
    return translate(language, "diagnostics.command.tessdata_pt")


def _hardware_sensor_dlls_command(language: str) -> str:
    return translate(language, "diagnostics.command.hardware_sensors")


def _version_via_flag(binary: str, flag: str = "--version") -> str | None:
    """First line of `binary --version` (or `flag`), or `None` on any
    failure — never raises."""
    try:
        result = run_hidden([binary, flag], timeout=10)
    except Exception:
        return None
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    return output.splitlines()[0].strip()


def _entry(key, present, version, required, install_command=None) -> dict:
    return {
        "key": key,
        "present": bool(present),
        "version": version,
        "required": bool(required),
        "install_command": None if present else install_command,
    }


def _diagnose_python() -> dict:
    import sys

    version = ".".join(str(part) for part in sys.version_info[:3])
    return _entry("python", True, version, True)


def _diagnose_tesseract(language: str) -> tuple[dict, dict]:
    try:
        path = find_tool("tesseract")
    except Exception:
        path = None
    present = bool(path)
    version = _version_via_flag(path, "--version") if present else None

    tessdata_pt = False
    if present:
        try:
            result = run_hidden([path, "--list-langs"], timeout=10)
            output = (result.stdout or "") + (result.stderr or "")
            tessdata_pt = any(line.strip() == "por" for line in output.splitlines())
        except Exception:
            tessdata_pt = False

    tesseract_item = _entry("tesseract", present, version, True, _TESSERACT_COMMAND)
    tessdata_item = _entry(
        "tessdata_pt", tessdata_pt, "por" if tessdata_pt else None, True, _tessdata_pt_command(language)
    )
    return tesseract_item, tessdata_item


def _diagnose_ghostscript() -> dict:
    path = None
    for name in ("gswin64c", "gswin32c", "gs"):
        try:
            found = find_tool(name)
        except Exception:
            found = None
        if found:
            path = found
            break
    present = bool(path)
    version = _version_via_flag(path, "--version") if present else None
    return _entry("ghostscript", present, version, True, _GHOSTSCRIPT_COMMAND)


def _diagnose_ollama() -> tuple[dict, dict]:
    try:
        path = find_tool("ollama")
    except Exception:
        path = None
    present = bool(path)
    version = _version_via_flag(path, "--version") if present else None
    ollama_item = _entry("ollama", present, version, False, _OLLAMA_COMMAND)

    try:
        models = list_installed_models()
    except Exception:
        models = []
    model_ok = DEFAULT_LOCAL_MODEL in models
    model_item = _entry(
        "default_model",
        model_ok,
        DEFAULT_LOCAL_MODEL if model_ok else None,
        False,
        f"ollama pull {DEFAULT_LOCAL_MODEL}",
    )
    return ollama_item, model_item


def _detect_gpu_for_diagnostics():
    try:
        return _detect_nvidia_gpu() or _detect_wmi_gpu()
    except Exception:
        return None


# `sensors.unavailable_reason()` return codes -> the i18n keys that already
# translate them for `run.html`'s JS dictionary (`SENSOR_REASON_TEXTS`) —
# reused here so the About screen's "Version" column stops showing the raw
# code (e.g. `sem_privilegio`) verbatim, in any language (Task 18, Phase 14).
_SENSOR_REASON_KEYS = {
    "sem_dll": "resources.sensors.no_dll",
    "sem_pythonnet": "resources.sensors.no_pythonnet",
    "sem_dependencia": "resources.sensors.no_dependency",
    "sem_privilegio": "resources.sensors.no_privilege",
    "helper_sem_resposta": "resources.sensors.helper_no_answer",
}


def _diagnose_gpu_runtime(language: str) -> dict:
    """What the GPU runtime needs, which on every supported vendor is the
    vendor's own driver and nothing else.

    Until Phase 15, Task 2 this singled out AMD RDNA1 (RX 5300-5700) as
    "needs `HSA_OVERRIDE_GFX_VERSION=10.3.0`" and offered the command to set
    it. That was measured and found to be false: on Windows with Ollama
    0.33.2 an RX 5700 XT is driven by the Vulkan backend
    (`llama_prepare_model_devices: using device Vulkan0`), ROCm is never
    attempted, and the variable is inert. `install.ps1` now *removes* that
    variable rather than writing it — so leaving this screen recommending it
    would have had the product's two halves contradict each other, and would
    have talked the user into undoing what the installer had just done.

    There is nothing to put in its place: the honest answer for every
    detected GPU is that a current driver is enough. Whether the GPU is
    actually being used is a measurement, not a diagnosis, and it belongs
    where it now lives — the end-of-install check that loads a model and
    reads the PROCESSOR column of `ollama ps`."""
    gpu = _detect_gpu_for_diagnostics()

    if gpu is None:
        return _entry("gpu_runtime", True, translate(language, "diagnostics.gpu_runtime.no_gpu"), False)

    version = translate(language, "diagnostics.gpu_runtime.driver_sufficient", name=gpu.name)
    return _entry("gpu_runtime", True, version, False)


def _diagnose_hardware_sensors(language: str) -> dict:
    try:
        present = dll_path().is_file()
    except Exception:
        present = False
    reason = None
    if present:
        try:
            reason = unavailable_reason()
        except Exception:
            reason = None

    if present and reason is None:
        version = DLL_NAME
    elif reason is not None:
        version = translate(language, _SENSOR_REASON_KEYS.get(reason, reason))
    else:
        version = None

    return _entry("hardware_sensors", present, version, False, _hardware_sensor_dlls_command(language))


def check_installation(language: str | None = None) -> list[dict]:
    """One item per external dependency of this machine.

    Never raises: every check is isolated in a `try/except` and degrades to
    `present=False` when something fails in an unexpected way — the
    "About" screen and the installer need to keep working even if the
    diagnostics themselves stumble.

    `language` (Task 18, Phase 14): falls back to `DEFAULT_LANGUAGE` when
    `None` — same convention as `record_event`/`ConfigError` for a caller
    with no request-scoped language of its own (`install.ps1`'s own
    diagnostics, run outside any HTTP request, is one such caller).
    """
    language = language or DEFAULT_LANGUAGE
    items: list[dict] = []
    try:
        items.append(_diagnose_python())
    except Exception:
        items.append(_entry("python", False, None, True))

    try:
        tesseract_item, tessdata_item = _diagnose_tesseract(language)
        items.append(tesseract_item)
        items.append(tessdata_item)
    except Exception:
        items.append(_entry("tesseract", False, None, True, _TESSERACT_COMMAND))
        items.append(_entry("tessdata_pt", False, None, True, _tessdata_pt_command(language)))

    try:
        items.append(_diagnose_ghostscript())
    except Exception:
        items.append(_entry("ghostscript", False, None, True, _GHOSTSCRIPT_COMMAND))

    try:
        ollama_item, model_item = _diagnose_ollama()
        items.append(ollama_item)
        items.append(model_item)
    except Exception:
        items.append(_entry("ollama", False, None, False, _OLLAMA_COMMAND))
        items.append(_entry("default_model", False, None, False, f"ollama pull {DEFAULT_LOCAL_MODEL}"))

    try:
        items.append(_diagnose_gpu_runtime(language))
    except Exception:
        items.append(_entry("gpu_runtime", True, None, False))

    try:
        items.append(_diagnose_hardware_sensors(language))
    except Exception:
        items.append(_entry("hardware_sensors", False, None, False, _hardware_sensor_dlls_command(language)))

    return items

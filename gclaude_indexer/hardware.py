# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Hardware diagnostics (spec section 10.1) and local model choice (section 10.2).

Reads GPU/VRAM (via `nvidia-smi`, with `Win32_VideoController` through WMI as
a fallback to detect AMD/Intel), system memory, free space on the destination
disk, and whether Tesseract, Ghostscript and Ollama are present. Everything is
read without opening a console window (see `subprocess_utils.run_hidden`).
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import windows_counters
from .events import record_event
from .engine_local import DEFAULT_LOCAL_MODEL, OLLAMA_BASE_URL
from .i18n import nested
from .paths import machine_local_folder
from .tools import find as find_tool
from .subprocess_utils import run_hidden

GB_MB = 1024

# Default local model (`DEFAULT_LOCAL_MODEL`, in `engine_local.py` — the one
# source of truth for the name). Phase 13 Task 8 let the user pick a
# different model through the form (`config.local_model`); from then on
# `choose_model`, below, decides whether the hardware can handle the model
# that *will actually be used* — no longer always this default. Ollama
# detects the GPU on its own and uses as much VRAM as fits, spilling the
# rest into RAM — that's why the hardware check looks at combined VRAM+RAM,
# not VRAM alone.

# Approximate download size of the default model (gemma4:e4b, ~9.6 GB), used
# to require double that much free space before downloading (section 10.2)
# and to estimate the minimum combined memory (VRAM + RAM) needed to load it.
# This is only a calibration for that specific model — for any other,
# `choose_model` first tries the real size via Ollama's `/api/tags`
# (`_real_model_size_mb`) and only falls back to this estimate when Ollama
# does not respond or the model has not been downloaded yet.
ESTIMATED_MODEL_SIZE_MB = 9_600
MEMORY_MARGIN = 1.2  # 20% margin over the model size (context/OS)
_MODEL_SIZE_TIMEOUT_S = 2.0


@dataclass
class GpuInfo:
    name: str
    vendor: str
    vram_mb: int


@dataclass
class HardwareDiagnostic:
    gpu: GpuInfo | None
    ram_mb: int
    free_space_mb: int
    checked_folder: str
    tesseract_present: bool
    tesseract_path: str | None
    ghostscript_present: bool
    ghostscript_path: str | None
    ollama_present: bool
    ollama_path: str | None


@dataclass
class ModelChoice:
    model: str | None
    reason: str
    use_rules_engine: bool


def _detect_nvidia_gpu() -> GpuInfo | None:
    path = find_tool("nvidia-smi")
    if not path:
        return None
    try:
        result = run_hidden(
            [path, "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None

    first_line = result.stdout.strip().splitlines()[0]
    name, _, memory = first_line.partition(",")
    digits = "".join(c for c in memory if c.isdigit())
    if not digits:
        return None
    return GpuInfo(name=name.strip(), vendor="NVIDIA", vram_mb=int(digits))


def _detect_wmi_gpu() -> GpuInfo | None:
    """Fallback with no `nvidia-smi`, via WMI (also detects AMD/Intel).

    `Win32_VideoController.AdapterRAM` is an old (32-bit) field and saturates
    at 4095 MB on recent cards — that's why the VRAM reported here prefers
    `windows_counters.vram_total_mb()` (reads the registry, a 64-bit QWORD)
    and only falls back to `AdapterRAM` when that returns `None` (counter
    unavailable). This feeds both the diagnostic text and `choose_model`, so
    the wrong value is not just cosmetic.
    """
    if sys.platform != "win32":
        return None
    command = [
        "powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,AdapterCompatibility | ConvertTo-Json -Compress",
    ]
    try:
        result = run_hidden(command, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        data = [data]
    if not data:
        return None

    first = data[0] or {}
    vram_mb = windows_counters.vram_total_mb()
    if vram_mb is None:
        vram_bytes = first.get("AdapterRAM") or 0
        vram_mb = int(vram_bytes) // (1024 * 1024) if vram_bytes else 0
    return GpuInfo(
        name=first.get("Name") or "unknown",
        vendor=first.get("AdapterCompatibility") or "unknown",
        vram_mb=vram_mb,
    )


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _total_memory_mb() -> int:
    if sys.platform != "win32":
        return 0
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullTotalPhys // (1024 * 1024)


def _free_space_mb(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(folder)
    return usage.free // (1024 * 1024)


def _check_presence(binary_names: tuple[str, ...]) -> tuple[bool, str | None]:
    for name in binary_names:
        path = find_tool(name)
        if path:
            return True, path
    return False, None


def diagnose(conn, space_folder: Path | None = None, language: str | None = None) -> HardwareDiagnostic:
    space_folder = space_folder or machine_local_folder()

    gpu = _detect_nvidia_gpu() or _detect_wmi_gpu()
    ram = _total_memory_mb()
    free_space = _free_space_mb(space_folder)
    tesseract_ok, tesseract_path = _check_presence(("tesseract",))
    ghostscript_ok, ghostscript_path = _check_presence(("gswin64c", "gswin32c", "gs"))
    ollama_ok, ollama_path = _check_presence(("ollama",))

    diagnostic = HardwareDiagnostic(
        gpu=gpu,
        ram_mb=ram,
        free_space_mb=free_space,
        checked_folder=str(space_folder),
        tesseract_present=tesseract_ok,
        tesseract_path=tesseract_path,
        ghostscript_present=ghostscript_ok,
        ghostscript_path=ghostscript_path,
        ollama_present=ollama_ok,
        ollama_path=ollama_path,
    )

    if gpu:
        prefix = "" if gpu.name.upper().startswith(gpu.vendor.upper()) else f"{gpu.vendor} "
        gpu_text = f"{prefix}{gpu.name} ({gpu.vram_mb} MB VRAM)"
    else:
        gpu_text = nested("log.hardware.no_gpu")

    # `nested(...)` (Task 12, Phase 14), not a pre-translated string: these
    # yes/no labels must stay retranslatable along with the rest of the
    # event on a later read (`list_events`, different language) — see that
    # function's docstring in `i18n.py`.
    yes = nested("log.common.yes")
    no = nested("log.common.no")
    record_event(
        conn,
        "diagnostics",
        "info",
        "log.hardware.diagnose",
        {
            "gpu": gpu_text, "ram": ram, "free_space": free_space, "folder": str(space_folder),
            "tesseract": yes if tesseract_ok else no,
            "ghostscript": yes if ghostscript_ok else no,
            "ollama": yes if ollama_ok else no,
        },
        language=language,
    )

    return diagnostic


def _real_model_size_mb(model_name: str, timeout_s: float = _MODEL_SIZE_TIMEOUT_S) -> int | None:
    """Model size on disk, according to Ollama's `/api/tags` (`size` field,
    in bytes). Returns `None` when Ollama does not respond or the model has
    not been downloaded on this machine yet — in those cases the caller
    falls back to `ESTIMATED_MODEL_SIZE_MB`."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None

    for model in models:
        if isinstance(model, dict) and model.get("name") == model_name:
            size_bytes = model.get("size")
            if isinstance(size_bytes, (int, float)) and size_bytes > 0:
                return int(size_bytes) // (1024 * 1024)
    return None


def choose_model(
    conn, diagnostic: HardwareDiagnostic, model: str = DEFAULT_LOCAL_MODEL, language: str | None = None
) -> ModelChoice:
    """Decides whether the hardware can run `model` on the `local` engine
    (combined VRAM+RAM, since Ollama uses as much GPU as fits and spills the
    rest into RAM on its own — this is not a table of VRAM tiers).

    `model` is the name that will actually be used (`engine_local.model_to_use`,
    which respects `config.local_model`) — before this fix the function
    always reported `DEFAULT_LOCAL_MODEL`, even when the user had chosen a
    different model in the form, so the log named a model that was not the
    one that would run.

    The size used in the memory/disk math comes from Ollama's `/api/tags`
    when available (`_real_model_size_mb`); it only falls back to
    `ESTIMATED_MODEL_SIZE_MB` (calibrated for `gemma4:e4b`, ~9.6 GB) when
    Ollama does not respond or the model has not been downloaded yet — and
    the recorded reason makes clear which of the two was used.
    """
    # `reason` (below) keeps its own Portuguese text unchanged — it is
    # `ModelChoice.reason`, a return value the caller (and this module's
    # tests) can inspect directly, not a log message; only the separate
    # `record_event` calls below are the "log messages" Task 12 (Phase 14)
    # covers. `log_size_source` is the log's own version of the same
    # fragment, as a `nested(...)` marker (not pre-translated text) so it
    # stays retranslatable along with the rest of the event — see
    # `nested()`'s docstring in `i18n.py`.
    real_size_mb = _real_model_size_mb(model)
    if real_size_mb is not None:
        model_size_mb = real_size_mb
        size_source = "tamanho real"
        log_size_source = nested("log.hardware.real_size")
    else:
        model_size_mb = ESTIMATED_MODEL_SIZE_MB
        size_source = "tamanho estimado (calibrado para gemma4:e4b; Ollama não informou o tamanho real)"
        log_size_source = nested("log.hardware.estimated_size")

    vram = diagnostic.gpu.vram_mb if diagnostic.gpu else 0
    combined_memory = vram + diagnostic.ram_mb
    required_memory = int(model_size_mb * MEMORY_MARGIN)
    margin_percent = int((MEMORY_MARGIN - 1) * 100)

    if combined_memory < required_memory:
        reason = (
            f"Memória insuficiente para '{model}': são necessários pelo menos "
            f"{required_memory} MB somando VRAM e RAM ({size_source} do modelo, "
            f"{model_size_mb} MB, com {margin_percent}% de folga), e esta "
            f"máquina tem {combined_memory} MB (VRAM: {vram} MB + RAM: {diagnostic.ram_mb} MB). "
            f"Usando o motor 'regras' — determinístico, sem custo e sem depender de instalar "
            f"modelo nenhum."
        )
        choice = ModelChoice(model=None, reason=reason, use_rules_engine=True)
        record_event(
            conn, "diagnostics", "warning", "log.hardware.insufficient_memory",
            {
                "model": model, "required": required_memory, "size_source": log_size_source,
                "model_size": model_size_mb, "margin_percent": margin_percent,
                "combined": combined_memory, "vram": vram, "ram": diagnostic.ram_mb,
            },
            language=language,
        )
        return choice

    required_space = model_size_mb * 2
    if diagnostic.free_space_mb < required_space:
        reason = (
            f"Memória suficiente para '{model}', mas faltou espaço em disco: são "
            f"necessários {required_space} MB livres (o dobro do {size_source} do "
            f"modelo, {model_size_mb} MB), e só há {diagnostic.free_space_mb} MB "
            f"disponíveis em {diagnostic.checked_folder}. Usando o motor 'regras' até "
            f"haver espaço suficiente."
        )
        choice = ModelChoice(model=None, reason=reason, use_rules_engine=True)
        record_event(
            conn, "diagnostics", "warning", "log.hardware.insufficient_disk_space",
            {
                "model": model, "required": required_space, "size_source": log_size_source,
                "model_size": model_size_mb, "available": diagnostic.free_space_mb,
                "folder": diagnostic.checked_folder,
            },
            language=language,
        )
        return choice

    reason = (
        f"Modelo '{model}' escolhido ({size_source}: {model_size_mb} MB): usa o máximo de "
        f"GPU possível (VRAM detectada: {vram} MB) e transborda o resto para a RAM "
        f"({diagnostic.ram_mb} MB disponíveis); espaço livre: {diagnostic.free_space_mb} MB."
    )
    choice = ModelChoice(model=model, reason=reason, use_rules_engine=False)
    record_event(
        conn, "diagnostics", "info", "log.hardware.model_chosen",
        {
            "model": model, "size_source": log_size_source, "model_size": model_size_mb,
            "vram": vram, "ram": diagnostic.ram_mb, "free_space": diagnostic.free_space_mb,
        },
        language=language,
    )
    return choice

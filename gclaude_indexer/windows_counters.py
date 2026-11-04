# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Machine telemetry via Windows Performance Counters.

Chosen instead of `nvidia-smi` because it works with **any** GPU that has a
WDDM driver — AMD, Intel and NVIDIA — with no vendor SDK. This is what fixed
the screen saying "no NVIDIA GPU detected" on a machine with a Radeon running
the local model at 100% GPU.

Counters are referenced by **numeric index**, never by name: names are
translated according to the Windows display language (on this machine the
CPU frequency one is "Informações do Processador(_Total)\\Frequência do
Processador"), and code that depends on the name breaks on any machine with
another language installed.

Every function returns `None` when the data is not available — never `0`,
which would be indistinguishable from "idle", and never an exception,
because the Run screen polls this every 500ms.
"""

from __future__ import annotations

import functools
import subprocess
import time

from .subprocess_utils import run_hidden

# Counter indexes (universal, independent of Windows display language):
#   1740 = GPU Engine / Utilization Percentage
#   1752 = GPU Adapter Memory / Dedicated Usage
# The localized name is resolved by PowerShell itself from the index.
_PS_GPU_USAGE = (
    "$ErrorActionPreference='Stop';"
    "$c=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage').CounterSamples;"
    "[math]::Round((($c | Measure-Object CookedValue -Sum).Sum),1)"
)

_PS_VRAM = (
    "$ErrorActionPreference='Stop';"
    "$c=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples;"
    "[math]::Round((($c | Measure-Object CookedValue -Sum).Sum)/1MB,0)"
)

# `Get-ChildItem` on `$base` itself needs `-ErrorAction SilentlyContinue`
# even with `$ErrorActionPreference='Stop'` set globally: one of the video
# class's subkeys (`Properties`) denies access, and without the
# SilentlyContinue that single error becomes terminating and aborts the
# whole pipeline — even after already having found the right value in
# `0000`.
#
# Sums (does not take the largest) because `gpu_usage_percent()`/
# `vram_used_mb()` sum every engine/adapter across every GPU. On a machine
# with an integrated + a dedicated GPU (the common laptop case), taking only
# the largest total left "used" and "total" inconsistent — it could even
# show used greater than total.
# Fase 34: one line per video controller *present* —
# `name;qwMemorySize;AdapterRAM`. Up to 1.7.1 the query walked every subkey
# of the display class in the registry and summed `qwMemorySize`; the
# registry keeps the key of a card that was removed (on one desktop:
# `0000` = "AMD Radeon RX 5700 XT", 8176 MB, replaced by the RX 6700 XT in
# `0001`, 12272 MB), so the total came out as 20448 MB for a 12 GB card and
# the classification's "free VRAM" carried the same 8176 MB too many. The
# path now starts from `Win32_VideoController` (present devices only) and
# follows `PNPDeviceID` → `Enum\<id>\Driver` → that class subkey, so a
# removed card never counts and a machine without a GPU yields no line.
# Measured on the same desktop: exactly one line, 12868124672 bytes = 12272 MB.
# Per adapter, not all-or-nothing (final review): with
# `$ErrorActionPreference='Stop'` one odd adapter — a driver that stores
# `qwMemorySize` as REG_BINARY (`byte[]`, seen on older iGPU drivers) — used
# to abort the whole script, and a laptop with such an iGPU beside a real
# card ended with no line at all. Each adapter is tried on its own, the
# binary form is decoded, and `-LiteralPath` keeps `[`/`]` in a device id
# from being read as wildcards.
_PS_PRESENT_ADAPTERS = (
    "$ErrorActionPreference='Stop';"
    "$base='HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\';"
    "Get-CimInstance Win32_VideoController | ForEach-Object {"
    "  try {"
    "    $id=$_.PNPDeviceID; if(-not $id){return};"
    "    $enum=Get-ItemProperty -LiteralPath ('HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\'+$id) -ErrorAction Stop;"
    "    $drv=$enum.Driver; if(-not $drv){return};"
    "    $p=Get-ItemProperty -LiteralPath ($base+$drv) -ErrorAction Stop;"
    "    $v=$p.'HardwareInformation.qwMemorySize';"
    "    if($v -is [byte[]]){ if($v.Length -ge 8){$v=[BitConverter]::ToInt64($v,0)} else {$v=0} };"
    "    '{0};{1};{2}' -f $_.Name,[int64]$v,[int64]$_.AdapterRAM"
    "  } catch { }"
    "}"
)

_TIMEOUT_S = 6

# Phase 13 added three `powershell.exe` calls per Run screen sample (GPU
# usage, VRAM and CPU clock), none of them cached — each one costs seconds
# (measured: ~6.4s for the whole sample). The screen asks for a sample every
# 500ms; without a cache the requests pile up until they occupy all 6
# connections the browser allows per origin, and the progress/log polls
# (competing for the same connections) stall along with them.
#
# Time-based cache (not `lru_cache`, which never expires) with the same
# pattern as `sensors.py` (`_last_reading` + timestamp): each value fetched
# via PowerShell is reused for `_CACHE_TTL_S`. `memory_clock_mhz` and
# `vram_total_mb`, below, still use a real `lru_cache` — they do not change
# while running.
_CACHE_TTL_S = 1.0

_cache: dict[str, tuple[float, object]] = {}


def _with_cache(key: str, compute):
    entry = _cache.get(key)
    if entry is not None and (time.monotonic() - entry[0]) < _CACHE_TTL_S:
        return entry[1]
    # The timestamp is taken **after** `compute()` returns, not before: the
    # PowerShell call here costs seconds (much more than the "tens of
    # milliseconds" of the pattern in `sensors.py`, which this cache was
    # copied from). Taking the timestamp before would make the item's age,
    # at the moment it is written, already start at "seconds ago" — bigger
    # than the validity window itself, i.e. the cache would never hit (bug
    # measured: an immediate second call still took ~3s instead of coming
    # from the cache).
    value = compute()
    _cache[key] = (time.monotonic(), value)
    return value


def _query(command: str) -> str | None:
    """Runs a hidden PowerShell command and returns the first line, or
    `None` on any failure."""
    try:
        result = run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0].strip()


def _query_lines(command: str) -> list[str] | None:
    """Every non-empty stdout line of a hidden PowerShell command, or
    `None` on any failure. An empty list is a successful answer that found
    nothing (a machine without a video controller)."""
    try:
        result = run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def gpu_usage_percent() -> float | None:
    """Summed usage of the GPU engines, as a percentage.

    The sum can go above 100 when several engines (3D, Copy, Compute) work
    at the same time — the value is capped at 100 to fit the chart scale.

    Cached for `_CACHE_TTL_S`: queries PowerShell, costs seconds.
    """
    return _with_cache("gpu_usage_percent", _gpu_usage_percent_uncached)


def _gpu_usage_percent_uncached() -> float | None:
    raw = _query(_PS_GPU_USAGE)
    if raw is None:
        return None
    try:
        return min(100.0, max(0.0, float(raw.replace(",", "."))))
    except ValueError:
        return None


def vram_used_mb() -> int | None:
    """Cached for `_CACHE_TTL_S`: queries PowerShell, costs seconds."""
    return _with_cache("vram_used_mb", _vram_used_mb_uncached)


def _vram_used_mb_uncached() -> int | None:
    raw = _query(_PS_VRAM)
    if raw is None:
        return None
    try:
        return max(0, int(float(raw.replace(",", "."))))
    except ValueError:
        return None


def _parse_adapters(lines: list[str]) -> list[tuple[str, int]]:
    """`(name, MB)` per line of `_PS_PRESENT_ADAPTERS`. The 64-bit registry
    value is preferred; `AdapterRAM` (32-bit, saturates at 4095 MB — this
    machine reports 4 GB for a 12 GB card) only stands in when the driver
    key has no `qwMemorySize`. Lines that do not parse are skipped, never
    raised: this feeds a screen polled every 500 ms."""
    adapters: list[tuple[str, int]] = []
    for line in lines:
        # From the right: the name itself may contain ";" (final review).
        parts = line.rsplit(";", 2)
        if len(parts) != 3 or not parts[0].strip():
            continue
        try:
            qword, adapter_ram = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        size = qword if qword > 0 else adapter_ram
        if size > 0:
            adapters.append((parts[0].strip(), size // (1024 * 1024)))
    return adapters


def present_adapters() -> list[tuple[str, int]]:
    """The video controllers present right now, `(name, VRAM in MB)`.
    Measured on every call (no cache across processes): the card can be
    swapped between two runs of the program, and the answer must follow."""
    lines = _query_lines(_PS_PRESENT_ADAPTERS)
    return _parse_adapters(lines) if lines else []


def vram_total_mb() -> int | None:
    """VRAM in MB of the largest GPU *present*, or `None` when unknown.

    The largest, not the sum (final review of fase 34): a model runs on one
    card. On a laptop with a 2 GB integrated GPU beside a 6 GB dedicated
    one the sum (8 GB) recommended the large model and asked
    `gpu_budget.layers_that_fit` for layers the dedicated card does not
    have. `vram_used_mb()` still sums every adapter's dedicated usage, so
    on such a machine the integrated GPU's few hundred MB make the budget
    slightly *more* conservative — the safe direction.
    """
    adapters = present_adapters()
    if not adapters:
        return None
    return max(size for _name, size in adapters)


def available() -> bool:
    """Whether the GPU counters respond on this machine."""
    return gpu_usage_percent() is not None


# The CPU frequency counter has a name **localized** by the Windows display
# language (on this machine: "Informações do Processador(_Total)\Frequência
# do Processador"; in English it would be "Processor Information(_Total)\
# Processor Frequency", which does not exist here). That is why the name is
# discovered at run time via `Get-Counter -ListSet *`, rather than written
# literally.
# Final review of fase 34: the counter *set* name is localized by the
# Windows display language, and the lookup above this line used to match
# only "Processor Information" and "Informações do Processador" — on a
# Spanish Windows ("Información del procesador") the CPU clock was never
# measured. The WMI performance class exposes the same counter under a
# name that is never translated; `Win32_Processor.CurrentClockSpeed` is
# the fallback (both read 3600 on a B550 board).
_PS_CPU_CLOCK = (
    "$ErrorActionPreference='Stop';"
    "$f=(Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter \"Name='_Total'\" "
    "-ErrorAction SilentlyContinue).ProcessorFrequency;"
    "if(-not $f){$f=(Get-CimInstance Win32_Processor | Select-Object -First 1).CurrentClockSpeed};"
    "if(-not $f){throw 'sem frequencia'};"
    "[int]$f"
)

_PS_MEMORY_CLOCK = (
    "$ErrorActionPreference='Stop';"
    "(Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1 -ExpandProperty ConfiguredClockSpeed)"
)


def clock_cpu_mhz() -> int | None:
    """Current CPU frequency, from a WMI class whose name is the same in
    every Windows language (see `_PS_CPU_CLOCK`).

    Cached for `_CACHE_TTL_S`: queries PowerShell, costs seconds.
    """
    return _with_cache("clock_cpu_mhz", _clock_cpu_mhz_uncached)


def _clock_cpu_mhz_uncached() -> int | None:
    raw = _query(_PS_CPU_CLOCK)
    if raw is None:
        return None
    try:
        return max(0, int(float(raw.replace(",", "."))))
    except ValueError:
        return None


@functools.lru_cache(maxsize=1)
def memory_clock_mhz() -> int | None:
    """Configured memory frequency. Does not change while running, so it is
    queried only once (WMI costs ~0.5s per call)."""
    raw = _query(_PS_MEMORY_CLOCK)
    if raw is None:
        return None
    try:
        return max(0, int(float(raw.replace(",", "."))))
    except ValueError:
        return None


def clock_gpu_mhz() -> int | None:
    """GPU core frequency.

    Windows exposes this through **neither** a Performance Counter nor WMI
    for any vendor. Stays `None` here and is filled in by the sensors module
 when LibreHardwareMonitor is available. Exists as a function so
    the UI has a single place to query.
    """
    return None

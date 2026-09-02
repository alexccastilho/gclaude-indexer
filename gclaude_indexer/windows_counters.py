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
_PS_VRAM_TOTAL = (
    "$ErrorActionPreference='Stop';"
    "$base='HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}';"
    "$soma=0;"
    "Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {"
    "  $p=Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue;"
    "  $v=$p.'HardwareInformation.qwMemorySize';"
    "  if($v){$soma+=$v}"
    "};"
    "if($soma -le 0){throw 'sem qwMemorySize'};"
    "[math]::Round($soma/1MB,0)"
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


def vram_total_mb() -> int | None:
    """Total VRAM in MB, summing every GPU on the machine.

    Read from the registry (`HardwareInformation.qwMemorySize`, a 64-bit
    QWORD) and not from `Win32_VideoController.AdapterRAM`, which is a
    32-bit field and saturates at 4095 MB — on this machine it reports 4 GB
    for an 8 GB card. Sums the value across every key (every GPU), consistent
    with `gpu_usage_percent()`/`vram_used_mb()`, which also sum every
    engine/adapter — on a machine with an integrated + a dedicated GPU,
    taking only the largest would leave the total smaller than the summed
    usage.
    """
    raw = _query(_PS_VRAM_TOTAL)
    if raw is None:
        return None
    try:
        return max(0, int(float(raw.replace(",", "."))))
    except ValueError:
        return None


def available() -> bool:
    """Whether the GPU counters respond on this machine."""
    return gpu_usage_percent() is not None


# The CPU frequency counter has a name **localized** by the Windows display
# language (on this machine: "Informações do Processador(_Total)\Frequência
# do Processador"; in English it would be "Processor Information(_Total)\
# Processor Frequency", which does not exist here). That is why the name is
# discovered at run time via `Get-Counter -ListSet *`, rather than written
# literally.
_PS_CPU_CLOCK = (
    "$ErrorActionPreference='Stop';"
    "$n=(Get-Counter -ListSet * | Where-Object {$_.CounterSetName -match 'Processor Information|Informações do Processador'} | "
    "Select-Object -First 1 -ExpandProperty Paths | Where-Object {$_ -match 'Frequ'} | Select-Object -First 1);"
    "if(-not $n){throw 'sem contador'};"
    "$p=$n -replace '\\(\\*\\)','(_Total)';"
    "[math]::Round((Get-Counter $p).CounterSamples[0].CookedValue,0)"
)

_PS_MEMORY_CLOCK = (
    "$ErrorActionPreference='Stop';"
    "(Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1 -ExpandProperty ConfiguredClockSpeed)"
)


def clock_cpu_mhz() -> int | None:
    """Current CPU frequency. The counter has a localized name, which is why
    it is discovered at run time instead of written literally.

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
    (Task 3) when LibreHardwareMonitor is available. Exists as a function so
    the UI has a single place to query.
    """
    return None

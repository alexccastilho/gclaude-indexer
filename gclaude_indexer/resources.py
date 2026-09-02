# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""CPU, RAM and GPU usage sampling — for the live chart on the Run screen
(explicit user request). Reuses the `nvidia-smi` already used by the phase 7
diagnostics; CPU/RAM come from `psutil` (the de facto standard library for
this, with no compiler required on Windows).
"""

from __future__ import annotations

import functools
import platform
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from .windows_counters import (
    clock_cpu_mhz,
    clock_gpu_mhz,
    memory_clock_mhz,
    gpu_usage_percent,
    vram_total_mb,
    vram_used_mb,
)
from .hardware import _detect_nvidia_gpu, _detect_wmi_gpu
from .sensors import read_sensors
from .subprocess_utils import run_hidden
from .tools import find as find_tool


@dataclass
class ResourceSample:
    cpu_percent: float
    cpu_name: str
    ram_percent: float
    ram_used_mb: int
    ram_total_mb: int
    gpu_percent: float | None
    gpu_vram_used_mb: int | None
    gpu_vram_total_mb: int | None
    gpu_name: str | None
    clock_cpu_mhz: int | None = None
    clock_memory_mhz: int | None = None
    clock_gpu_mhz: int | None = None
    cpu_temp_c: float | None = None
    gpu_temp_c: float | None = None
    gpu_hotspot_c: float | None = None
    gpu_fan_rpm: int | None = None
    cpu_power_w: float | None = None
    gpu_power_w: float | None = None


def _sample_cpu_ram() -> tuple[float, float, int, int]:
    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    return cpu, memory.percent, int(memory.used / (1024 * 1024)), int(memory.total / (1024 * 1024))


def _sample_nvidia_gpu(path: str) -> tuple[float | None, int | None, int | None]:
    try:
        result = run_hidden(
            [path, "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None, None
    if result.returncode != 0 or not result.stdout.strip():
        return None, None, None

    parts = result.stdout.strip().splitlines()[0].split(",")
    try:
        utilization = float(parts[0].strip())
        used = int(float(parts[1].strip()))
        total = int(float(parts[2].strip()))
        return utilization, used, total
    except (ValueError, IndexError):
        return None, None, None


def _sample_gpu() -> tuple[float | None, int | None, int | None]:
    """GPU usage and VRAM. Prefers `nvidia-smi` when it exists (gives the
    total VRAM precisely); otherwise uses the Performance Counters, which
    work with any vendor. `None` means "not measured" — never 0."""
    path = find_tool("nvidia-smi")
    if path:
        sample = _sample_nvidia_gpu(path)
        if sample != (None, None, None):
            return sample

    usage = gpu_usage_percent()
    if usage is None:
        return None, None, None
    return usage, vram_used_mb(), _vram_total_mb()


@functools.lru_cache(maxsize=1)
def _vram_total_mb() -> int | None:
    """Total VRAM, cached (does not change while running).

    Prefers the registry (`HardwareInformation.qwMemorySize`, a 64-bit
    QWORD): `Win32_VideoController.AdapterRAM`, used by the phase 7 hardware
    diagnostics, is a 32-bit field and saturates at 4095 MB — on an 8 GB card
    it would lie "4095". Only falls back to AdapterRAM (via `hardware.py`) if
    the registry does not respond, and to `None` as a last resort."""
    total = vram_total_mb()
    if total is not None:
        return total

    gpu = _detect_nvidia_gpu() or _detect_wmi_gpu()
    return getattr(gpu, "vram_mb", None) if gpu else None


@functools.lru_cache(maxsize=1)
def _cpu_name() -> str:
    """Commercial processor name — does not change while running, so it is
    looked up only once (WMI is slow: ~0.5-1s per call)."""
    if sys.platform == "win32":
        try:
            result = run_hidden(
                ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                timeout=10,
            )
            name = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
            if name:
                return name
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass
    return platform.processor() or platform.machine() or "unknown"


@functools.lru_cache(maxsize=1)
def _gpu_name() -> str | None:
    """Commercial GPU name (same detection as the phase 7 hardware
    diagnostics), cached for the same reason as `_cpu_name`. `None` = no GPU
    detected — the caller shows something like "No GPU"."""
    gpu = _detect_nvidia_gpu() or _detect_wmi_gpu()
    return gpu.name if gpu else None


# Collecting only makes sense while someone is looking at the Run screen.
# Without this, opening the screen once left a powershell.exe collecting
# every 2s for the rest of the server process's life.
SECONDS_UNTIL_HIBERNATE = 30


def sample_resources() -> ResourceSample:
    cpu, ram_percent, ram_used, ram_total = _sample_cpu_ram()
    gpu_percent, gpu_used, gpu_total = _sample_gpu()
    sensors = read_sensors()
    # GPU clock preferably comes from the sensors (LibreHardwareMonitor);
    # `windows_counters.clock_gpu_mhz()` today always returns `None` (Task 2
    # — no native Windows API exposes this), but the fallback stays here for
    # the day it gets some source.
    gpu_clock = sensors["clock_gpu_mhz"]
    if gpu_clock is None:
        gpu_clock = clock_gpu_mhz()
    return ResourceSample(
        cpu_percent=cpu,
        cpu_name=_cpu_name(),
        ram_percent=ram_percent,
        ram_used_mb=ram_used,
        ram_total_mb=ram_total,
        gpu_percent=gpu_percent,
        gpu_vram_used_mb=gpu_used,
        gpu_vram_total_mb=gpu_total,
        gpu_name=_gpu_name(),
        clock_cpu_mhz=clock_cpu_mhz(),
        clock_memory_mhz=memory_clock_mhz(),
        clock_gpu_mhz=gpu_clock,
        cpu_temp_c=sensors["cpu_temp_c"],
        gpu_temp_c=sensors["gpu_temp_c"],
        gpu_hotspot_c=sensors["gpu_hotspot_c"],
        gpu_fan_rpm=sensors["gpu_fan_rpm"],
        cpu_power_w=sensors["cpu_potencia_w"],
        gpu_power_w=sensors["gpu_potencia_w"],
    )


def _sample_cpu_ram_fast() -> tuple[float, float, int, int]:
    """Like `_sample_cpu_ram`, but without `psutil.cpu_percent`'s 0.1s
    interval — used only for the partial sample (`latest_sample()` before the
    first full collection), which must not block even for an instant.
    `interval=None` compares against the previous call and can return 0.0 on
    the very first call of the process; acceptable here because it is just a
    placeholder until the real collection (which uses the accurate variant)
    finishes, a few seconds later."""
    import psutil

    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    return cpu, memory.percent, int(memory.used / (1024 * 1024)), int(memory.total / (1024 * 1024))


def _partial_sample() -> ResourceSample:
    """Sample used before the first full collection finishes: only the fast
    fields (CPU/RAM, via `psutil`) are real; the ones that depend on
    PowerShell/sensors (which cost seconds) come back as `None` instead of
    blocking or lying about a value."""
    cpu, ram_percent, ram_used, ram_total = _sample_cpu_ram_fast()
    return ResourceSample(
        cpu_percent=cpu,
        cpu_name=_cpu_name(),
        ram_percent=ram_percent,
        ram_used_mb=ram_used,
        ram_total_mb=ram_total,
        gpu_percent=None,
        gpu_vram_used_mb=None,
        gpu_vram_total_mb=None,
        gpu_name=_gpu_name(),
        clock_cpu_mhz=None,
        clock_memory_mhz=None,
        clock_gpu_mhz=None,
        cpu_temp_c=None,
        gpu_temp_c=None,
        gpu_hotspot_c=None,
        gpu_fan_rpm=None,
        cpu_power_w=None,
        gpu_power_w=None,
    )


class ContinuousSampler:
    """Collects telemetry on its own thread and keeps the latest sample.

    Exists because `Get-Counter` costs ~2s per metric (it collects two
    samples to compute a rate), and the Run screen wants a reading every
    500ms. With the collection on the request path, every `GET
    /run/resources` held one of the 6 connections the browser allows per
    origin for 6.4s — and the HTMX polls (progress bar, live log, step table)
    queued up behind it.

    Here the collection happens off the request path: the endpoint returns
    the last known value in microseconds, and the data is at most
    `interval_s` old.

    The thread hibernates on its own after `SECONDS_UNTIL_HIBERNATE` with no
    one calling `latest_sample()` — without this, opening the Run screen once
    left a `powershell.exe` collecting every `INTERVAL_S` for the rest of the
    server process's life, even with no one looking at the screen. The next
    call to `latest_sample()` restarts the thread (the same lazy-start as
    always); the last known sample stays available, hibernating or not.
    """

    INTERVAL_S = 2.0

    def __init__(self, interval_s: float | None = None) -> None:
        if interval_s is not None:
            self.INTERVAL_S = interval_s
        self._lock = threading.Lock()
        self._latest: ResourceSample | None = None
        self._thread: threading.Thread | None = None
        self._last_read: float | None = None
        # `Event` instead of plain `time.sleep()`: lets `stop()` (only for
        # tests — the thread is a daemon and disappears with the process in
        # production) wake the thread immediately, without waiting out the
        # whole interval.
        self._stop = threading.Event()

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is None:
                self._stop.clear()
                thread = threading.Thread(target=self._loop, name="resource-sampler", daemon=True)
                self._thread = thread
                thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sample = sample_resources()
            except Exception:
                # A collection that fails must not crash the server nor
                # clear the last known good sample — just retry next cycle.
                pass
            else:
                with self._lock:
                    self._latest = sample
            if self._stop.wait(self.INTERVAL_S):
                break
            with self._lock:
                last_read = self._last_read
            if last_read is not None and (time.monotonic() - last_read) > SECONDS_UNTIL_HIBERNATE:
                break
        # Marks the thread as stopped (under the lock, to not race with a
        # concurrent `_ensure_thread()`) so that the next read restarts it —
        # without this the hibernated thread would stay stuck as "active"
        # forever.
        with self._lock:
            if self._thread is threading.current_thread():
                self._thread = None

    def latest_sample(self) -> ResourceSample:
        """Never blocks: records the time of this read, starts the thread on
        demand (first call, or restart after hibernating) and returns the
        last collected sample, or a partial sample (CPU/RAM only) if the
        collection has not finished even once yet."""
        with self._lock:
            self._last_read = time.monotonic()
        self._ensure_thread()
        with self._lock:
            latest = self._latest
        if latest is not None:
            return latest
        return _partial_sample()

    def _active(self) -> bool:
        """Only for tests/diagnostics: whether the thread exists and is running."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def stop(self) -> None:
        """Only for tests: signals the thread to stop and waits up to
        `INTERVAL_S` plus a margin for the loop to notice and exit. Never
        called in production — the thread is a daemon and disappears with
        the process."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.INTERVAL_S + 5)


_sampler = ContinuousSampler()


def latest_sample() -> ResourceSample:
    """Last known sample, for the `/run/resources` endpoint — never
    collects on the spot, so it never takes the ~6s `sample_resources()` can
    cost."""
    return _sampler.latest_sample()


def _sampler_active() -> bool:
    """Only for tests/diagnostics: whether the module-level sampler thread
    (`_sampler`) exists and is running right now."""
    return _sampler._active()

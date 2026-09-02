# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""GPU temperature, power and clock via LibreHardwareMonitor.

No native Windows API exposes this data: `MSAcpi_ThermalZoneTemperature`
fails on most desktops, and the Performance Counters have no thermal
sensors. The alternative is `LibreHardwareMonitorLib.dll` (MPL-2.0), read
through `pythonnet`.

This brings two dependencies the rest of the project avoids — a third-party
binary and administrator privilege (the library loads a kernel driver to
talk to the sensors). That is why everything is isolated here, with explicit
degradation: missing any piece, the readings become `None` and the UI says
they are not available. **Never return 0 in place of unknown** — zero
degrees is a measurement, "don't know" is not.
"""

from __future__ import annotations

import ctypes
import functools
import json
import os
import threading
import time
from pathlib import Path

from .paths import machine_local_folder

DLL_NAME = "LibreHardwareMonitorLib.dll"

# Phase 15, Task 3 — the elevated sensor helper's drop box.
#
# CPU temperature and power need ring 0, which this process does not have
# and should not ask for: elevating the whole server would put uvicorn,
# every document parser, Ghostscript, Tesseract and the Ollama client on an
# administrator token just to read five numbers. Instead
# `sensor_service.py` runs *only the reading* elevated, in a separate
# process, and publishes the result here; this module reads that file when
# its own in-process reading is blocked by privilege.
#
# A plain JSON file, not a pipe or a socket: the payload is five numbers
# refreshed every couple of seconds, the two processes belong to the same
# user on the same machine, and the folder is that user's own
# `%LOCALAPPDATA%`. Nothing crosses a trust boundary downward — the
# elevated side only *writes*, never parses anything the unprivileged side
# produced, so no input from a lower-privileged process reaches ring 0.
SNAPSHOT_FILE_NAME = "sensor_snapshot.json"

# How old a snapshot may be and still be shown. The helper rewrites it
# every `sensor_service.POLL_INTERVAL_S` (2s); this is generous enough to
# survive a slow cycle and short enough that a dead helper stops feeding
# the screen within a few seconds instead of freezing a stale temperature
# on it forever.
SNAPSHOT_MAX_AGE_S = 15.0

# .NET Framework BCL shims that LibreHardwareMonitorLib requires at load
# time (transitive dependencies of `System.Memory` etc., not included in the
# minimal release zip). All official Microsoft ones, downloaded from
# nuget.org into `machine_local_folder() / "lib"`. Loaded one at a time,
# each ignoring its own absence — if a specific shim is not present on this
# machine, we carry on without it; only the missing main DLL prevents the
# reading.
_SHIMS = (
    "System.Memory",
    "System.Buffers",
    "System.Runtime.CompilerServices.Unsafe",
    "System.Numerics.Vectors",
    "System.Threading.AccessControl",
)

# `gpu_hotspot_c` e `gpu_fan_rpm` (pedido explícito do usuário): numa placa
# moderna o ponto quente é dezenas de graus acima da temperatura de núcleo —
# medido nesta máquina, 99 °C de hotspot contra 73 °C de núcleo — e é ele
# que dita o quanto a placa reduz o clock. A rotação da ventoinha é o outro
# lado da mesma informação: diz se a refrigeração ainda tem folga.
KEYS = (
    "cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "clock_gpu_mhz",
    "gpu_hotspot_c", "gpu_fan_rpm",
)

_EMPTY = {key: None for key in KEYS}

# `read_sensors()` calls `Update()` on every component, which costs tens of
# milliseconds (measured: see the Task 3 report). The Run screen polls this
# every 500ms, so a short-lived cached reading avoids redoing the full
# `Update()` on every screen refresh without leaving the values visibly
# stale.
#
# Final Phase 13 review (item b): this cache had been flagged as
# "precautionary, remeasure later" — the measurement confirms the opposite
# of removing it. `_state()` is `functools.lru_cache(maxsize=1)`, so the
# LibreHardwareMonitor `Computer` object is **one, shared** across every
# call, and `Computer.Update()` (a .NET library, via pythonnet) **is not
# thread-safe**. Without this cache, two concurrent HTTP requests (the
# screen itself makes overlapping polls when a sample is late) would call
# `Update()` on the same object at the same time. The cache reduces the real
# call frequency, but on its own it does not *prevent* concurrency — two
# threads can still land together in the window where the cache expired.
# That is why access to the cache-miss path (recompute) is guarded by
# `_lock` right below: only one thread at a time may be inside
# `_read_sensors_uncached()`.
_CACHE_TTL_S = 2.0

_last_reading: dict | None = None
_last_reading_time: float = 0.0
_lock = threading.Lock()


def dll_path():
    return machine_local_folder() / "lib" / DLL_NAME


def snapshot_path() -> Path:
    """Where the elevated helper publishes its reading."""
    return machine_local_folder() / SNAPSHOT_FILE_NAME


def write_snapshot(reading: dict) -> None:
    """Publishes `reading` for the unprivileged server to pick up.

    Called only by `sensor_service.py`, in the elevated process. Written to
    a temporary file and renamed over the target (`os.replace` is atomic on
    Windows for same-volume paths), so a reader never sees half a file.
    """
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "written_at": time.time(),
        # Whose snapshot this is. Only used by `clear_snapshot()`, so that a
        # second helper (the user opened the CPU-sensor shortcut twice; the
        # second server fails to bind the port and takes its own helper down
        # with it) cannot delete the reading the first one is still
        # publishing.
        "pid": os.getpid(),
        "reading": {key: reading.get(key) for key in KEYS},
    }
    # `time.time()`, not `time.monotonic()`: the two clocks have no common
    # origin across processes, and freshness is compared in the *other*
    # process.
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def clear_snapshot() -> None:
    """Removes the reading *this process* published.

    The helper calls this on its way out, so the screen falls back to the
    unprivileged reading immediately instead of waiting
    `SNAPSHOT_MAX_AGE_S` for the file to go stale. A file another process
    owns is left alone: a second helper going down must not blank out the
    one still running.
    """
    path = snapshot_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or payload.get("pid") != os.getpid():
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def read_snapshot() -> dict | None:
    """The elevated helper's last reading, or `None`.

    `None` covers every way this can fail to be a usable reading — no file,
    unreadable file, malformed JSON, unexpected keys, non-numeric values, or
    simply too old. **Never raises**, like everything else in this module:
    the sensor path must never be able to take the Run screen down.

    Values are type-checked rather than trusted: the file lives in the
    user's own profile, but a reading is displayed to a human as a
    measurement, and "0" written by something other than the helper would
    be indistinguishable from a real one. Booleans are rejected explicitly
    because `isinstance(True, int)` is true in Python.
    """
    try:
        raw = snapshot_path().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    written_at = payload.get("written_at")
    if not isinstance(written_at, (int, float)) or isinstance(written_at, bool):
        return None
    age = time.time() - float(written_at)
    if age < 0 or age > SNAPSHOT_MAX_AGE_S:
        return None

    reading = payload.get("reading")
    if not isinstance(reading, dict) or set(reading) != set(KEYS):
        return None
    for value in reading.values():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
    return dict(reading)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _import_library():
    """Loads the DLL via pythonnet. Returns the `Hardware` module or `None`.

    Split into its own function so the test can substitute it without
    touching a real import.
    """
    if not dll_path().is_file():
        return None
    try:
        import clr  # noqa: F401  (pythonnet)
    except ImportError:
        return None

    lib_folder = machine_local_folder() / "lib"
    for shim_name in _SHIMS:
        shim_path = lib_folder / f"{shim_name}.dll"
        if not shim_path.is_file():
            continue
        try:
            clr.AddReference(str(shim_path))
        except Exception:
            pass  # Shim missing or incompatible: carry on without it.

    try:
        clr.AddReference(str(dll_path()))
        from LibreHardwareMonitor import Hardware  # type: ignore

        return Hardware
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def _state() -> tuple[object | None, str | None]:
    """`(computer, reason)`. `computer` is the already-open LHM object, or
    `None`; `reason` is the i18n key for why not, or `None` if all is well."""
    if not dll_path().is_file():
        return None, "sem_dll"
    try:
        import clr  # noqa: F401
    except ImportError:
        return None, "sem_pythonnet"

    try:
        Hardware = _import_library()
        if Hardware is None:
            return None, "sem_dll"
        computer = Hardware.Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        # Disabled on purpose: enabling memory requires the RAMSPDToolkit
        # dependency (third-party, outside what was authorized) just to read
        # module SPD — since nobody asked for it. The memory clock already
        # comes from WMI in `windows_counters.clock_memoria_mhz()`.
        computer.IsMemoryEnabled = False
        computer.Open()
    except Exception as error:
        # A .NET assembly `FileNotFoundException` indicates a missing
        # runtime dependency, not lack of privilege — we tell them apart so
        # we don't send the user to "run as administrator" when the real
        # problem is a missing shim DLL.
        type_name = type(error).__name__
        if "FileNotFoundException" in type_name or "FileNotFoundException" in str(error):
            return None, "sem_dependencia"
        return None, "sem_privilegio"

    if not _is_admin():
        # The library opens, but without elevation the sensors come back empty.
        return computer, "sem_privilegio"
    return computer, None


def _helper_launch_status() -> str | None:
    """What happened last time the elevated helper was asked for.

    Imported lazily: `sensor_service` imports this module at the top, and
    the reverse import only happens inside this function, so there is no
    cycle at import time.
    """
    try:
        from .sensor_service import read_launch_status

        return read_launch_status()
    except Exception:
        return None


def unavailable_reason() -> str | None:
    reason = _state()[1]
    if reason == "sem_privilegio":
        if read_snapshot() is not None:
            # The elevated helper is running and publishing: this process
            # still has no privilege, but the reading *is* available, and
            # the screen must not go on telling the user to do something
            # they have already done.
            return None
        if _helper_launch_status() == "started":
            # The helper was launched and is not publishing. Telling the
            # user to "open through the CPU sensor shortcut" here would be
            # advice they already followed — this is the state that used to
            # look identical to never having tried, and it is what made the
            # sensors "not open" with no visible reason after an install on
            # a second machine.
            return "helper_sem_resposta"
    return reason


def _snapshot_if_privilege_is_the_only_problem() -> dict | None:
    """The helper's reading, but only when lack of privilege is what stops
    us reading it ourselves.

    Deliberately not consulted for `sem_dll`, `sem_pythonnet` or
    `sem_dependencia`: those are missing files, and the helper runs on this
    same machine off the same folder, so it cannot have what we lack. The
    helper exists to solve exactly one problem — ring 0 — and this keeps
    the two paths from quietly covering for each other.
    """
    try:
        reason = _state()[1]
    except Exception:
        return None
    if reason != "sem_privilegio":
        return None
    return read_snapshot()


def sensors_available() -> bool:
    """Whether sensor reading is available in this run.

    Written as a function, not a module-level `property`: `property` only
    behaves as a descriptor inside a class — at module level it is just an
    inert `property` object, never called automatically.
    """
    return _state()[1] is None


def _read_sensors_uncached() -> dict:
    try:
        computer, reason = _state()
    except Exception:
        return dict(_EMPTY)
    if computer is None:
        return dict(_EMPTY)

    reading = dict(_EMPTY)
    try:
        for component in computer.Hardware:
            component.Update()
            kind = str(component.HardwareType)
            for sensor in component.Sensors:
                if sensor.Value is None:
                    continue
                sensor_type = str(sensor.SensorType)
                value = float(sensor.Value)
                if sensor_type == "Temperature":
                    nome = str(sensor.Name)
                    if "Cpu" in kind and reading["cpu_temp_c"] is None:
                        reading["cpu_temp_c"] = round(value, 1)
                    elif "Gpu" in kind and "Hot Spot" in nome:
                        # Casado pelo nome, não pela ordem: a placa expõe
                        # várias temperaturas (núcleo, memória, VRM, ponto
                        # quente) e só o nome as distingue.
                        if reading["gpu_hotspot_c"] is None:
                            reading["gpu_hotspot_c"] = round(value, 1)
                    elif "Gpu" in kind and "Core" in nome and reading["gpu_temp_c"] is None:
                        reading["gpu_temp_c"] = round(value, 1)
                    elif "Gpu" in kind and reading["gpu_temp_c"] is None:
                        reading["gpu_temp_c"] = round(value, 1)
                elif sensor_type == "Power":
                    if "Cpu" in kind and reading["cpu_potencia_w"] is None:
                        reading["cpu_potencia_w"] = round(value, 1)
                    elif "Gpu" in kind and reading["gpu_potencia_w"] is None:
                        reading["gpu_potencia_w"] = round(value, 1)
                elif sensor_type == "Clock" and "Gpu" in kind and "Core" in str(sensor.Name):
                    reading["clock_gpu_mhz"] = int(value)
                elif sensor_type == "Fan" and "Gpu" in kind and reading["gpu_fan_rpm"] is None:
                    reading["gpu_fan_rpm"] = int(value)
    except Exception:
        return dict(_EMPTY)

    # Without administrator privilege the kernel driver does not load and
    # the library returns EVERY sensor with value 0.0 — indistinguishable
    # from a real measurement. If nothing came back different from zero,
    # this is not an idle machine: it is the absence of a reading.
    if all(v in (None, 0, 0.0) for v in reading.values()):
        return dict(_EMPTY)

    # The check above only covers total degradation. On mixed hardware (e.g.
    # a CPU whose temperature/power sensors require the kernel driver, but a
    # GPU whose sensors work through another path with no elevation needed —
    # confirmed on this machine: AMD Ryzen CPU with `Tctl/Tdie` and `Power
    # Package` always 0.0 without admin, while the AMD Radeon GPU reads
    # normally) a partial reading is possible, with some fields genuinely
    # measured and others stuck at 0.0 for the same reason. A temperature or
    # power sensor that returns exactly 0.0 is never a real measurement of
    # working hardware — it is the driver's default value when it failed to
    # load. That is why the filter is per key, not only global.
    for key in ("cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "gpu_hotspot_c"):
        if reading[key] in (0, 0.0):
            reading[key] = None
    return reading


def read_sensors() -> dict:
    """Current sensor reading. Keys always present; values `None` when not
    measured. **Never raises.**

    Cached for `_CACHE_TTL_S` (2s): the `Update()` of every component costs
    tens of milliseconds (measured on this machine, see the Task 3 report),
    and the Run screen polls this every 500ms — without a cache that would be
    2 to 4 full `Update()` calls a second for nothing.
    """
    global _last_reading, _last_reading_time

    # The elevated helper's reading wins when it exists, and it is a strict
    # superset: an administrator process reads the GPU as well as the CPU,
    # so there is nothing to merge from the local path — and skipping the
    # local path also avoids two processes calling `Update()` on the same
    # kernel driver every couple of seconds for the same numbers.
    #
    # The helper itself never lands here: it *is* elevated, so its own
    # `_state()` reason is `None` and `_snapshot_if_privilege_is_the_only_problem`
    # returns `None` — no process ever reads back the snapshot it wrote.
    published = _snapshot_if_privilege_is_the_only_problem()
    if published is not None:
        return published

    now = time.monotonic()
    if _last_reading is not None and (now - _last_reading_time) < _CACHE_TTL_S:
        return dict(_last_reading)

    with _lock:
        # Another thread may have refreshed the cache while we waited for
        # the lock — recheck so we don't do one extra `Update()`.
        now = time.monotonic()
        if _last_reading is not None and (now - _last_reading_time) < _CACHE_TTL_S:
            return dict(_last_reading)

        reading = _read_sensors_uncached()
        _last_reading = reading
        _last_reading_time = now
        return dict(reading)

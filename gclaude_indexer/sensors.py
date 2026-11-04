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
# medido numa RX 6700 XT, 99 °C de hotspot contra 73 °C de núcleo — e é ele
# que dita o quanto a placa reduz o clock. A rotação da ventoinha é o outro
# lado da mesma informação: diz se a refrigeração ainda tem folga.
KEYS = (
    "cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "clock_gpu_mhz",
    "gpu_hotspot_c", "gpu_fan_rpm",
    # CPU fan, from Dell's thermal interface (`dell_thermal.py`).
    "cpu_fan_rpm",
    # Fase 34: VRAM in use and total, from the library (`GPU Memory
    # Used/Total`, type `SmallData`, in MB; `D3D Dedicated Memory
    # Used/Total` for an integrated Intel GPU, which has no other pair).
    # Measured on a 12 GB card: about 8.9 of 12 GB with the model loaded, and
    # filled **without** elevation — see `_MEMORY_KEYS`.
    "gpu_vram_usada_mb",
    "gpu_vram_total_mb",
)

# The memory pair comes through the vendor's user-mode interface, not the
# kernel driver: it is filled even when every other sensor reads 0.0 for
# lack of privilege. It must stay out of the "everything zero = no
# privilege" rule below, or an unprivileged reading would pass as real
# and the screen would show 0 °C as a measurement.
_MEMORY_KEYS = ("gpu_vram_usada_mb", "gpu_vram_total_mb")
# Preferred name first; the `D3D` pair is the fallback.
_VRAM_USED_NAMES = ("GPU Memory Used", "D3D Dedicated Memory Used")
_VRAM_TOTAL_NAMES = ("GPU Memory Total", "D3D Dedicated Memory Total")

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
    # A subset of the keys is accepted (final review of fase 34): an
    # elevated helper from the previous version still running publishes
    # fewer keys, and rejecting it would blank the CPU temperature until
    # that helper is restarted. Unknown keys are still refused.
    if not isinstance(reading, dict) or not set(reading) <= set(KEYS):
        return None
    for value in reading.values():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
    return {key: reading.get(key) for key in KEYS}


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

    Hardware = _import_library()
    if Hardware is None:
        return None, "sem_dll"
    try:
        computer = _open_computer(Hardware, with_motherboard=True)
    except Exception as error:
        # A .NET assembly `FileNotFoundException` indicates a missing
        # runtime dependency, not lack of privilege — we tell them apart so
        # we don't send the user to "run as administrator" when the real
        # problem is a missing shim DLL.
        type_name = type(error).__name__
        if "FileNotFoundException" in type_name or "FileNotFoundException" in str(error):
            return None, "sem_dependencia"
        # Enabling the motherboard is what makes `Open()` probe the SuperIO
        # over I/O ports (fase 32). If that is what blew up, the GPU must
        # not disappear with it: try once more the way 1.6.1 opened the
        # library, without the board — the fan stays "not measured", the
        # rest of the screen stays alive (final review of fase 32).
        try:
            computer = _open_computer(Hardware, with_motherboard=False)
        except Exception:
            return None, "sem_privilegio"

    if not _is_admin():
        # The library opens, but without elevation the sensors come back empty.
        return computer, "sem_privilegio"
    return computer, None


def _open_computer(Hardware, *, with_motherboard: bool):
    """A `Computer` with the components this app reads, already `Open()`ed.
    Raises whatever the library raises; `_state()` decides what it means."""
    computer = Hardware.Computer()
    computer.IsCpuEnabled = True
    computer.IsGpuEnabled = True
    # Fase 32: a ventoinha da CPU não é um sensor da CPU — é um header do
    # SuperIO da placa-mãe (por exemplo, num
    # Nuvoton NCT6798D a CPU é o `Fan #2`, em `/fan/1`, invisível com
    # esta opção desligada). Só se lê com o driver (ring 0); sem
    # privilégio a placa aparece vazia e nada muda.
    computer.IsMotherboardEnabled = with_motherboard
    # Disabled on purpose: enabling memory requires the RAMSPDToolkit
    # dependency (third-party, outside what was authorized) just to read
    # module SPD — since nobody asked for it. The memory clock already
    # comes from WMI in `windows_counters.clock_memoria_mhz()`.
    computer.IsMemoryEnabled = False
    computer.Open()
    return computer


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


def _read_sensors_uncached() -> dict:
    return _with_dell_thermal(_read_library_sensors())


def _with_dell_thermal(reading: dict) -> dict:
    """Fills what LibreHardwareMonitor left empty from Dell's own
    thermal interface — fans, which on a laptop belong to the embedded
    controller and are invisible to both the library and the GPU driver,
    and the CPU temperature, which the library only reads through the
    PawnIO driver. Only an administrator may ask, so only the elevated
    helper does; anywhere else every value stays as it was."""
    if not _is_admin():
        return reading
    try:
        from . import dell_thermal

        dell = dell_thermal.read()
    except Exception:
        return reading
    merged = dict(reading)
    for key in ("cpu_fan_rpm", "gpu_fan_rpm", "cpu_temp_c", "gpu_temp_c"):
        if merged.get(key) is None and dell.get(key) is not None:
            merged[key] = dell[key]
    return merged


def cpu_fan_from_superio(sensors_of_chip, chip_identifier: str) -> int | None:
    """Which of the SuperIO's fan headers is the CPU fan, and what it reads.

    Pure function over the chip's sensor list, so it is testable without
    .NET. The chips do not know what is plugged into each header, and the
    library only names the headers on boards it has a profile for:

    * A sensor the library named "CPU …" is it — 0 RPM included, because a
      named header that reads 0 is a fan that stopped (or a pump header
      reporting through it), which is information.
    * Otherwise the chip's fixed CPU header: Nuvoton (`/nct…`) puts
      CPUFANIN at index 1 (confirmed: `Fan #2` = 1.276 RPM on
      an NCT6798D while the board's other spinning header was `Fan #6`);
      ITE, Fintek and Winbond at index 0. A guessed header that reads 0 is
      **not** reported: on a guess, 0 means "nothing plugged here", and a
      wrong number on the screen is worse than no number.
    * Never "the first header that spins": that would label a chassis fan
      as the CPU's.
    """
    fans = []
    for sensor in sensors_of_chip:
        if str(sensor.SensorType) != "Fan" or sensor.Value is None:
            continue
        fans.append((str(sensor.Name), str(sensor.Identifier), float(sensor.Value)))
    for name, _identifier, value in fans:
        if "cpu" in name.casefold():
            return int(value)
    target = 1 if "/nct" in chip_identifier.lower() else 0
    for _name, identifier, value in fans:
        if identifier.rstrip("/").endswith(f"/fan/{target}") and value > 0:
            return int(value)
    return None


def _memory_pair(memory: dict[str, float]) -> tuple[int, int] | None:
    """`(used, total)` in MB from one GPU's `SmallData` sensors, by name
    (`GPU Memory *` first, the `D3D Dedicated` pair as fallback), or `None`
    when the component has no usable total."""
    values = []
    for names in (_VRAM_USED_NAMES, _VRAM_TOTAL_NAMES):
        found = next((int(memory[name]) for name in names if name in memory and memory[name] > 0), None)
        values.append(found)
    used, total = values
    if total is None:
        return None
    return (used if used is not None else 0, total)


def _read_library_sensors() -> dict:
    try:
        computer, reason = _state()
    except Exception:
        return dict(_EMPTY)
    if computer is None:
        return dict(_EMPTY)

    reading = dict(_EMPTY)
    # Final review: the memory pair of *every* GPU is collected and the one
    # with the largest total wins — the library lists an AMD integrated GPU
    # before an NVIDIA dedicated one, and "first GPU wins" showed 300 / 512
    # MB while the model held 6 GB of the dedicated card.
    memory_pairs: list[tuple[int, int]] = []
    try:
        for component in computer.Hardware:
            # Per component, not around the whole loop (fase 32): a
            # motherboard whose SuperIO refuses to answer used to zero the
            # GPU reading along with it. Each component fails alone.
            try:
                component.Update()
            except Exception:
                continue
            kind = str(component.HardwareType)
            if "Motherboard" in kind:
                if reason == "sem_privilegio":
                    # Without the driver every SuperIO header reads 0.0 —
                    # including one the board names "CPU Fan", which the
                    # rule below would (rightly, when elevated) take as a
                    # real 0 and the screen would call "stopped" on a fan
                    # that is spinning. The fan of an unprivileged process
                    # comes from the elevated helper's snapshot or not at
                    # all (final review of fase 32).
                    continue
                # The fans hang off the SuperIO, a *sub*-hardware of the
                # board, and the board's own `Update()` does not reach it.
                for chip in component.SubHardware:
                    try:
                        # Only a SuperIO decides (fase 33): the fixed-header
                        # rule in `cpu_fan_from_superio` is about Nuvoton,
                        # ITE, Fintek and Winbond chips. Another sub-hardware
                        # of the board — an embedded controller with a header
                        # it calls "CPU Optional" — is not the CPU fan, and a
                        # 0 there would read as "stopped".
                        if "SuperIO" not in str(chip.HardwareType):
                            continue
                        chip.Update()
                        if reading["cpu_fan_rpm"] is None:
                            reading["cpu_fan_rpm"] = cpu_fan_from_superio(chip.Sensors, str(chip.Identifier))
                    except Exception:
                        continue
                continue
            memory: dict[str, float] = {}
            for sensor in component.Sensors:
                if sensor.Value is None:
                    continue
                sensor_type = str(sensor.SensorType)
                value = float(sensor.Value)
                if sensor_type == "SmallData" and "Gpu" in kind:
                    memory[str(sensor.Name)] = value
                    continue
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
                    # 0 stays 0: an RX 6700 XT has read 0 RPM
                    # with fan control at 0 % at 54 °C — zero-RPM mode, a
                    # measurement. The screen labels it "stopped".
                    reading["gpu_fan_rpm"] = int(value)
            if memory:
                pair = _memory_pair(memory)
                if pair is not None:
                    memory_pairs.append(pair)
        if memory_pairs:
            reading["gpu_vram_usada_mb"], reading["gpu_vram_total_mb"] = max(memory_pairs, key=lambda p: p[1])
    except Exception:
        return dict(_EMPTY)

    # Without administrator privilege the kernel driver does not load and
    # the library returns EVERY sensor with value 0.0 — indistinguishable
    # from a real measurement. If nothing came back different from zero,
    # this is not an idle machine: it is the absence of a reading.
    if all(v in (None, 0, 0.0) for k, v in reading.items() if k not in _MEMORY_KEYS):
        # Fase 34: the memory pair is kept — it is real even then.
        return {key: (reading[key] if key in _MEMORY_KEYS else None) for key in KEYS}

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
    tens of milliseconds (measured on a desktop with a dedicated GPU),
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

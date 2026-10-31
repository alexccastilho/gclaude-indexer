# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fan speeds (and CPU/GPU temperatures) from Dell's own thermal interface.

On a laptop the fans belong to the embedded controller, not to the CPU or
the graphics driver: LibreHardwareMonitor finds no fan, and `nvidia-smi`
answers `N/A`. Dell's gaming laptops (Alienware, G series) expose them
through the WMI class `AWCCWmiMethodFunction` in `root\\wmi` — the
interface Alienware Command Center uses, and that Linux drives in
`alienware-wmi-wmax.c`.

Only the read operations of `Thermal_Information` are ever called here.
`Thermal_Control`, which sets fan modes, is never touched. The class only
answers an administrator, so this runs in the elevated sensor helper
(`sensor_service.py`), next to LibreHardwareMonitor.

Measured on a Dell G15 5511 (31/10/2026): 2 fans (0x32 = CPU, 0x33 = GPU)
at 2101 and 2387 RPM, 2 temperatures (0x01 = CPU 73 °C, 0x06 = GPU 58 °C),
with no third-party driver installed.

**Never raises**: on any other machine the class does not exist and every
reading is `None`; it stops asking after a few spaced attempts.
"""

from __future__ import annotations

import threading
import time

# `Thermal_Information` operations (low byte of the argument; the next byte
# is the operation's own argument).
_OP_SYSTEM_DESCRIPTION = 0x02
_OP_RESOURCE_ID = 0x03
_OP_TEMPERATURE = 0x04
_OP_FAN_RPM = 0x05

# Resource ids with a known meaning.
_FAN_CPU = 0x32
_FAN_GPU = 0x33
_TEMP_CPU = 0x01
_TEMP_GPU = 0x06

# The firmware answers an invalid request with all bits set (or nearly).
_INVALID_FLOOR = 0xFFFFFFF0

# A failed read is tried again after this long, up to this many times in a
# row (1.5.11): about five minutes for Dell's service to come up.
_RETRY_SECONDS = 30.0
_MAX_FAILURES = 10

KEYS = ("cpu_fan_rpm", "gpu_fan_rpm", "cpu_temp_c", "gpu_temp_c")


def _empty() -> dict:
    return {key: None for key in KEYS}


def _pack(operation: int, argument: int = 0) -> int:
    return (operation & 0xFF) | ((argument & 0xFF) << 8)


class DellThermal:
    """One open handle to the WMI object, with the resource ids read once.

    `invoke(arg) -> int` is the only thing that talks to the firmware, so a
    test can drive the protocol without WMI."""

    def __init__(self, invoke=None, clock=time.monotonic):
        self._given_invoke = invoke
        self._invoke = invoke
        self._fans: list[int] | None = None
        self._temps: list[int] | None = None
        self._broken = False
        self._failures = 0
        self._retry_at = 0.0
        self._clock = clock
        self._lock = threading.Lock()

    def _call(self, operation: int, argument: int = 0) -> int | None:
        value = int(self._invoke(_pack(operation, argument))) & 0xFFFFFFFF
        return None if value >= _INVALID_FLOOR else value

    def _discover(self) -> None:
        description = self._call(_OP_SYSTEM_DESCRIPTION)
        if description is None:
            raise RuntimeError("no system description")
        fan_count = description & 0xFF
        temp_count = (description >> 8) & 0xFF
        fans, temps = [], []
        for index in range(fan_count + temp_count):
            resource = self._call(_OP_RESOURCE_ID, index)
            if resource is None:
                continue
            (fans if index < fan_count else temps).append(resource & 0xFF)
        self._fans, self._temps = fans, temps

    def read(self) -> dict:
        reading = _empty()
        with self._lock:
            if self._broken or self._clock() < self._retry_at:
                return reading
            try:
                if self._invoke is None:
                    self._invoke = _wmi_invoker()
                if self._fans is None:
                    self._discover()
                for fan in self._fans:
                    rpm = self._call(_OP_FAN_RPM, fan)
                    if rpm is None or rpm > 20000:
                        continue
                    if fan == _FAN_CPU:
                        reading["cpu_fan_rpm"] = rpm
                    elif fan == _FAN_GPU:
                        reading["gpu_fan_rpm"] = rpm
                for sensor in self._temps:
                    value = self._call(_OP_TEMPERATURE, sensor)
                    # 0 is never a real temperature of working hardware.
                    if value is None or not 0 < value < 150:
                        continue
                    if sensor == _TEMP_CPU:
                        reading["cpu_temp_c"] = float(value)
                    elif sensor == _TEMP_GPU:
                        reading["gpu_temp_c"] = float(value)
            except Exception:
                # Not a Dell, not elevated, or not ready yet. 1.5.11: tried
                # again later instead of given up at once — right after a
                # restart the helper starts before Dell's WMI provider
                # answers, and the first failure used to leave the fans
                # empty for the whole session (31/10/2026). A machine
                # without the interface stops being asked after a few
                # spaced attempts.
                self._failures += 1
                self._invoke = self._given_invoke
                self._fans = self._temps = None
                if self._failures >= _MAX_FAILURES:
                    self._broken = True
                else:
                    self._retry_at = self._clock() + _RETRY_SECONDS
                return _empty()
            self._failures = 0
        return reading


def _wmi_invoker():
    """`invoke(arg) -> argr` through .NET `System.Management` (pythonnet is
    already loaded for LibreHardwareMonitor in the same process)."""
    import clr  # noqa: F401  (pythonnet)

    clr.AddReference("System.Management")
    from System import UInt32  # type: ignore
    from System.Management import ManagementObjectSearcher  # type: ignore

    searcher = ManagementObjectSearcher("root\\wmi", "SELECT * FROM AWCCWmiMethodFunction")
    instance = None
    for found in searcher.Get():
        instance = found
        break
    if instance is None:
        raise RuntimeError("AWCCWmiMethodFunction not present")

    def invoke(argument: int) -> int:
        params = instance.GetMethodParameters("Thermal_Information")
        params["arg2"] = UInt32(argument)
        result = instance.InvokeMethod("Thermal_Information", params, None)
        return int(result["argr"])

    return invoke


_shared = DellThermal()


def read() -> dict:
    """Current reading; every value `None` when unavailable."""
    return _shared.read()

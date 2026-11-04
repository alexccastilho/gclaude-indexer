# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Which backend Ollama is really running on, and why not a better one.

Ollama picks CUDA, ROCm, Vulkan or the CPU on its own and says so only in
its server log — never in the API. The user asked (fase 36) to know, on
any machine, what the card is being driven by and why a faster path is
not in use. Measured on an RX 6700 XT with Ollama 0.40.13: the
bundled ROCm 7.1 refuses the card because the AMD driver ships
`amdhip64_6.dll` and not `amdhip64_7.dll` ("AMD driver is too old"), so
the card runs on Vulkan; and the scheduler pins the `qwen35` family to one
request at a time ("model architecture does not currently support
parallel requests"). Both facts change what the user should expect, and
neither was visible in the project log.

Everything here is read-only over log files: the one this program writes
when it starts the server (`ollama-serve.log`) and the one the Ollama tray
application writes (`%LOCALAPPDATA%\\Ollama\\server.log`). The most recent
discovery block across them is the server that is up now.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import machine_local_folder

OLLAMA_SERVE_LOG_NAME = "ollama-serve.log"

# One line per device, written at server start — the last one in a file is
# the server that is up (a tray restart appends a new block to the same
# file). Format on 0.40.13:
#   time=… level=INFO source=types.go:32 msg="inference compute" id=0
#   library=Vulkan … description="AMD Radeon RX 6700 XT" … total="12.0 GiB"
_DISCOVERY = re.compile(r'msg="inference compute".*?\blibrary=(?P<library>\S+)')
_TIME = re.compile(r"\btime=(?P<time>\S+)")
_DESCRIPTION = re.compile(r'\bdescription="(?P<description>[^"]*)"')
_TOTAL = re.compile(r'\btotal="(?P<total>[^"]*)"')
_AMD_DRIVER_OLD = "AMD driver is too old"
# Written when a model of a family the scheduler serializes is loaded —
# after discovery, once per load. Listed in `server/sched.go`:
# mllama, qwen3vl, qwen3vlmoe, qwen35, qwen35moe, qwen3next, lfm2, lfm2moe,
# nemotron_h, nemotron_h_moe, nemotron_h_omni. The log line is the truth;
# the list is only context.
_PARALLEL_PINNED = re.compile(
    r'msg="model architecture does not currently support parallel requests"\s+architecture=(?P<family>\S+)'
)
# Vulkan has no cooperative-matrix path on RDNA1/RDNA2, and the runner does
# not print the `matrix cores` line in these logs (looked for it in three
# server starts), so the card's name is the rule: RX 5000 and RX 6000. No
# literal space after "Radeon": some drivers expose "AMD Radeon(TM) RX 6600"
# (revisão da fase 36 — the rule would have stayed silent on that name).
_VULKAN_NO_MATRIX_CORES = re.compile(r"Radeon.*\bRX\s*[56]\d{3}", re.I)


@dataclass
class BackendInfo:
    library: str                 # CUDA, ROCm, Vulkan, CPU, ...
    device: str                  # the card's name as the log prints it
    total: str                   # its memory as the log prints it ("12.0 GiB")
    seen_at: str                 # the `time=` of the discovery line
    amd_driver_old: bool = False
    parallel_pinned_family: str | None = None


def parse_backend_log(text: str) -> BackendInfo | None:
    """The last discovery block of a server log, or `None` without one.

    `amd_driver_old` is any "AMD driver is too old" line in the text (it is
    printed just before discovery, and only by a server with an AMD card);
    `parallel_pinned_family` comes from the last pin warning *after* the
    discovery line, since it belongs to a model load of that server.
    """
    lines = text.splitlines()
    discovery_index = None
    for index in range(len(lines) - 1, -1, -1):
        if _DISCOVERY.search(lines[index]):
            discovery_index = index
            break
    if discovery_index is None:
        return None

    line = lines[discovery_index]
    library = _DISCOVERY.search(line).group("library")
    description = _DESCRIPTION.search(line)
    total = _TOTAL.search(line)
    time = _TIME.search(line)
    family = None
    for later in lines[discovery_index + 1:]:
        pinned = _PARALLEL_PINNED.search(later)
        if pinned:
            family = pinned.group("family")
    return BackendInfo(
        library=library,
        device=description.group("description") if description else "",
        total=total.group("total") if total else "",
        seen_at=time.group("time") if time else "",
        amd_driver_old=any(_AMD_DRIVER_OLD in earlier for earlier in lines),
        parallel_pinned_family=family,
    )


def backend_log_paths() -> list[Path]:
    """Where a server's log can be: ours first, then the tray app's."""
    paths = [machine_local_folder() / OLLAMA_SERVE_LOG_NAME]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(Path(local) / "Ollama" / "server.log")
    return paths


def read_backend(paths: list[Path] | None = None, tail_bytes: int = 262144) -> BackendInfo | None:
    """The backend of the server up now: the most recent discovery block
    across `paths` (default `backend_log_paths()`), reading only the last
    `tail_bytes` of each file — `server.log` sits next to a multi-megabyte
    `app.log`, and a discovery block is a few hundred bytes. A file that
    does not open is skipped. Never raises.
    """
    best: BackendInfo | None = None
    for path in (backend_log_paths() if paths is None else paths):
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - tail_bytes))
                text = handle.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        try:
            info = parse_backend_log(text)
        except Exception:
            info = None
        if info is None:
            continue
        if best is None or info.seen_at > best.seen_at:
            best = info
    return best


def prefers_flash_attention_off(info: BackendInfo | None) -> bool:
    """Vulkan on an AMD RX 5000/6000: measured on the RX 6700 XT with
    qwen3.5:9b, flash attention halved prompt reading (373
    against 735 tokens/s on the same windows; generation −5%; a window
    23–28% longer), and the KV cache type made no difference (FA on with
    f16: 374 tokens/s). RX 7000 (WMMA), NVIDIA and Intel were not measured
    and keep Ollama's defaults."""
    if info is None or info.library.lower() != "vulkan":
        return False
    return bool(_VULKAN_NO_MATRIX_CORES.search(info.device or ""))

# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""How many workers to use in the CPU-bound steps.

Conversion (with OCR) and extraction used to process one file at a time, and
`ocrmypdf` was called with no `--jobs` — on an 8 physical-core machine, OCR
of a whole collection used just one. This is where the system's biggest
time gain lives.

**Physical** cores, not logical: OCR and PDF rendering saturate the
execution unit, and counting hyperthreads leads to contention rather than
gain.
"""

from __future__ import annotations

# Mode values were translated to English (Task 9d, Phase 14, reversing an
# earlier decision from Task 9c to keep them in Portuguese because they are
# stored verbatim in `ProjectConfig.parallelism`, and therefore in existing
# project databases). Precedent: `classification.py`'s engine literals went
# through the exact same move (see `orchestrator.py`'s docstring) — keeping
# `run.engine` (fed by config) and `item.engine` (fed by the engines) in two
# different languages made `quality.compare_runs` unable to match one against
# the other, which is exactly the failure mode a stale project's stored
# `parallelism` value would otherwise reproduce here. No compatibility shim:
# the user authorized discarding pre-existing project state along with this
# rename, so an old project's `"automatico"` simply falls through the
# `mode not in MODES` branch below the same way an unknown value always did.
MODES = ("economy", "automatic", "maximum")
DEFAULT_MODE = "automatic"


def _physical_cores() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or 1
    except Exception:
        import os
        return max(1, (os.cpu_count() or 2) // 2)


def workers_for(mode: str) -> int:
    physical = max(1, _physical_cores())
    if mode == "economy":
        return 1
    if mode == "maximum":
        return physical
    # automatic (and any unknown value): leaves one core free so the UI
    # keeps responding while the collection is processed.
    return max(1, physical - 1)

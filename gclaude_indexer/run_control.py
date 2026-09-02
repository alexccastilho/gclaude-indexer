# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Cooperative pause/interrupt control for the steps.

Every long step (scan, conversion, extraction, windowing, classification)
accepts an optional `should_stop` — a no-argument function that returns
`True` once the user has asked to stop. It is checked between one item and
the next in each step's main loop. Since every step is already resumable
(it saves what it processed so far and picks up exactly there next time —
spec section 2, acceptance criterion 3), stopping midway never loses work
nor corrupts state: "pause" and "resume later" are the same thing as
running the step again.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class StopSignal:
    """One per (project, step) running in this server session — triggered
    by the interface's "Pause" button, checked by the step's loop."""

    _event: threading.Event = field(default_factory=threading.Event)

    def request_stop(self) -> None:
        self._event.set()

    def should_stop(self) -> bool:
        return self._event.is_set()

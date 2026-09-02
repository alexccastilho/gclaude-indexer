# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Estimating how long a step still has to run.

The first version of this was two lines inside `compute_progress`: divide
the items finished by the seconds elapsed, divide what remains by that
rate. It is the obvious formula and it was wrong in three separate ways,
each of which the user could see on screen.

**It counted the wrong thing.** "Items" for the conversion step means
files, and files are not comparable units of work: a 900-page scanned PDF
and a 3 KB text note both count as one. A collection whose big documents
happen to come first (or last, alphabetically — the step processes in path
order) produced an estimate that was wrong by a factor, not by a margin.
This module weights progress by the bytes actually being processed, which
is the closest cheap proxy for the work in every step that touches files —
OCR, Ghostscript, hashing and text extraction all scale with the size of
the document, not with the number of them.

**It averaged over the wrong window.** Dividing the total by the whole
elapsed time includes the startup: spawning the process pool, Windows'
`spawn` cost per worker, Ollama loading a model into VRAM. Those seconds
are real but they are not repeated, and folding them into the average
inflates every later estimate. Worse, an average over the whole run cannot
*react*: when the collection moves from small text files into scanned PDFs
and the true pace drops fivefold, an all-time average takes as long as the
run itself to notice. The estimate here is an exponentially weighted
moving average, so recent pace dominates and the number moves up or down
as the work actually changes — which is what was asked for.

**It jumped.** Each poll recomputed from scratch, so a single slow file
made the remaining time leap. The value that reaches the screen is
smoothed, enough to stop the flicker and not so much that it lags behind a
genuine change of pace.

Everything degrades to "no estimate" rather than to a bad one: too few
samples, no elapsed time, a stalled step, or weights that could not be read
all return `None`, and the screen simply shows elapsed time without a
prediction. A missing estimate is honest; a confident wrong one is not.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

# Memory of the rate average, in seconds. A sample this old still counts,
# at 1/e of its original weight. Chosen to span several files on a slow
# step without being so long that the estimate ignores a real change of
# pace: with the Run screen polling every 2s, this is roughly the last 20
# samples that matter.
TIME_CONSTANT_S = 45.0

# How much of the newly computed estimate reaches the screen each poll.
# 0.35 settles a jumpy value within a few seconds while still following a
# genuine slowdown rather than averaging it away.
DISPLAY_SMOOTHING = 0.35

# Below this, an estimate is a guess dressed up as a number.
MIN_ELAPSED_S = 4.0
MIN_PROGRESS_FRACTION = 0.005

# A step that has produced nothing for this long is not "slow", it is
# stalled — or it is doing something the weights cannot see (a single huge
# PDF in OCR). Either way the last rate no longer describes it, and no
# estimate is better than one that counts down towards a moment that will
# not arrive.
STALL_TIMEOUT_S = 180.0


@dataclass
class ProgressEstimator:
    """Turns a series of (time, work done) observations into a remaining
    time, in seconds.

    One instance per running step, held by its `StepTask`. Stateful on
    purpose: the whole point is that each estimate knows what the previous
    ones saw.
    """

    started_at: float = field(default_factory=time.monotonic)
    rate: float | None = None            # weighted units per second
    last_time: float | None = None
    last_done: float | None = None
    last_progress_time: float | None = None
    displayed_eta: float | None = None

    def observe(self, done: float, total: float, now: float | None = None) -> float | None:
        """Records progress and returns the seconds remaining, or `None`.

        `done` and `total` are in whatever unit the caller measures work in
        — bytes for the file steps, windows for classification. They only
        have to be consistent with each other across calls.
        """
        now = time.monotonic() if now is None else now

        if total <= 0 or done >= total:
            return None

        if self.last_time is None:
            self.last_time, self.last_done = now, done
            self.last_progress_time = now
            return None

        elapsed_since_last = now - self.last_time
        if elapsed_since_last <= 0:
            return self.displayed_eta

        advanced = done - self.last_done
        self.last_time, self.last_done = now, done

        if advanced > 0:
            # O intervalo é medido desde o último PROGRESSO, não desde a
            # última leitura. Esta linha era o defeito mais caro deste
            # módulo: a tela consulta a cada 2s, mas uma janela de
            # classificação leva dezenas de segundos, então a maioria das
            # leituras não vê avanço nenhum. Medindo contra a leitura
            # anterior, o avanço de uma janela aparecia como tendo levado
            # 2s em vez de 13s, e a taxa saía 6,5x otimista.
            #
            # Medido no acervo real: 124 janelas em 1628s (13,1s por
            # janela, 40 minutos restantes) e a tela anunciava 7 minutos —
            # uma previsão que encolhia enquanto a execução crescia.
            intervalo = now - (self.last_progress_time or self.started_at)
            self.last_progress_time = now
            if intervalo <= 0:
                return self.displayed_eta
            instant_rate = advanced / intervalo
            # Pondera por *tempo*, não por número de amostras: um intervalo
            # de oito segundos deve envelhecer a média quatro vezes mais
            # que um de dois.
            weight = 1.0 - math.exp(-intervalo / TIME_CONSTANT_S)
            self.rate = instant_rate if self.rate is None else (
                weight * instant_rate + (1.0 - weight) * self.rate
            )
        elif self.last_progress_time is not None and (now - self.last_progress_time) > STALL_TIMEOUT_S:
            # Nothing finished for minutes. Drop the estimate rather than
            # keep counting down from a rate that no longer applies.
            self.rate = None
            self.displayed_eta = None
            return None

        total_elapsed = now - self.started_at
        if total_elapsed < MIN_ELAPSED_S or done < total * MIN_PROGRESS_FRACTION:
            return None
        if not self.rate or self.rate <= 0:
            return None

        # A média desde o início da etapa, como âncora da média móvel.
        #
        # As duas medem coisas diferentes e ambas são necessárias: a média
        # móvel reage a uma mudança real de ritmo, e a média global é
        # imune ao ruído de amostragem que produziu o defeito acima. Quando
        # discordam muito, é quase sempre a móvel que está errada — ela
        # enxerga poucos eventos, a global enxerga todos.
        #
        # A mistura é deliberadamente assimétrica: quanto mais a etapa já
        # rodou, mais a global manda. Numa etapa recém-começada a global
        # ainda carrega o custo de arranque (carregar o modelo na VRAM,
        # abrir o pool de processos) e a móvel descreve melhor o regime; ao
        # fim de meia hora, a global É o regime.
        global_rate = done / total_elapsed if total_elapsed > 0 else 0.0
        if global_rate > 0:
            peso_global = min(0.8, total_elapsed / (total_elapsed + TIME_CONSTANT_S * 4))
            rate = peso_global * global_rate + (1.0 - peso_global) * self.rate
        else:
            rate = self.rate

        raw_eta = (total - done) / rate
        self.displayed_eta = (
            raw_eta if self.displayed_eta is None
            else DISPLAY_SMOOTHING * raw_eta + (1.0 - DISPLAY_SMOOTHING) * self.displayed_eta
        )
        return self.displayed_eta

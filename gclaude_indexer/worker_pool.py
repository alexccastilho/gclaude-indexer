# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""A process pool that cannot freeze a step (1.5.5).

What happened on 31/10/2026, 145,000 files in a Google Drive folder: the
Drive client stopped answering eight file opens at once. The eight workers
sat in those calls forever. The step then met a locked database, left its
`with ProcessPoolExecutor(...)` block, and `shutdown(wait=True)` waited for
those eight workers, which never came back. The step hung with its
transaction open, and every screen got "Internal Server Error".

This pool keeps four promises the plain executor does not:

* **No unbounded wait.** Every file has a deadline that grows with its size.
  A file past its deadline gets its worker processes killed and the pool
  rebuilt; the others in flight go back to the queue, unpenalised.
* **A file is not condemned for one stall.** It is tried again in the new
  pool. Only a second stall, while other files are completing (so the
  system is healthy and the file is the problem), marks it timed out.
* **A sick system stops the step instead of failing the collection.** When
  restarts keep coming with nothing completing in between (the drive is
  gone, not the file), the pool raises `PoolStalledError` and leaves every
  remaining file untouched for the next run.
* **Leaving never waits.** Whatever the exit (done, paused, error), the
  workers are killed and the executor shut down with `wait=False`.

Submission is bounded to one file per worker, so a file's clock starts when
it really starts. It also keeps the memory of a 145,000-file queue in the
main process, not pickled into the executor's queue.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, wait
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any

OK = "ok"
ERROR = "error"
TIMED_OUT = "timed_out"
CRASHED = "crashed"

BASE_DEADLINE_SECONDS = 600.0
DEADLINE_SECONDS_PER_MB = 120.0
MAX_DEADLINE_SECONDS = 6 * 3600.0


def deadline_for_size(size_bytes: int | None) -> float:
    """Ten minutes, plus two per megabyte, capped at six hours.

    The per-megabyte part covers OCR, which is the slow path and grows with
    the scan. A 20 KB web page that takes ten minutes is not slow, it is
    stuck. A 100 MB scanned PDF gets three and a half hours."""
    megabytes = max(0, size_bytes or 0) / (1024 * 1024)
    return min(MAX_DEADLINE_SECONDS, BASE_DEADLINE_SECONDS + DEADLINE_SECONDS_PER_MB * megabytes)


@dataclass
class Outcome:
    item: Any
    kind: str  # OK, ERROR, TIMED_OUT or CRASHED
    value: Any = None


class PoolStalledError(RuntimeError):
    """Restarts kept coming with nothing completing in between. Carries the
    file that was in flight when the pool gave up, for the message."""

    def __init__(self, item: Any):
        super().__init__("worker pool stalled")
        self.item = item


class DaemonThreadExecutor:
    """Runs each task on a daemon thread of this same process (1.5.6).

    For the paths that never used worker processes: economy mode
    (parallelism 1) and a single file. There a Drive hang froze the step's
    own thread, which nothing can unfreeze. A thread cannot be killed
    either, but it can be *abandoned*: the step stops waiting for it and
    moves on, and being a daemon it never holds up the server's exit. Same
    process, so OCR keeps running in-process exactly as before.

    Concurrency is bounded by whoever submits (`ResilientPool` keeps at
    most `workers` tasks in flight), so one thread per task is enough."""

    def __init__(self, max_workers: int = 1, initializer: Callable[[], None] | None = None):
        self._initializer = initializer

    def submit(self, fn, *args, **kwargs) -> Future:
        future: Future = Future()

        def runner() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                if self._initializer is not None:
                    self._initializer()
                result = fn(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

        threading.Thread(target=runner, daemon=True, name="gclaude-guarded-call").start()
        return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        pass  # nothing to release: each thread ends with its task, or is abandoned


class CallTimedOut(Exception):
    """`call_with_deadline` gave up waiting; the call may still be running,
    abandoned, on its daemon thread."""


def call_with_deadline(fn: Callable[..., Any], *args, deadline: float) -> Any:
    """`fn(*args)`, but never waits more than `deadline` seconds for it.

    For the scan, whose single-file calls (`stat`, hash, a folder listing)
    are exactly the ones a frozen Google Drive never answers. Exceptions
    from `fn` propagate unchanged."""
    future = DaemonThreadExecutor().submit(fn, *args)
    try:
        return future.result(timeout=deadline)
    except FutureTimeoutError:
        raise CallTimedOut(deadline) from None


class StepStalledError(RuntimeError):
    """What a step raises after `PoolStalledError`, with the message already
    translated: it becomes the error the Execution screen shows."""


class ResilientPool:
    def __init__(
        self,
        executor_factory: Callable[[], Any],
        workers: int,
        *,
        deadline_for: Callable[[Any], float],
        should_stop: Callable[[], bool] | None = None,
        on_restart: Callable[[str, Any], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        max_attempts: int = 2,
        max_unhealthy_restarts: int = 3,
        poll_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._factory = executor_factory
        self._workers = max(1, workers)
        self._deadline_for = deadline_for
        self._should_stop = should_stop or (lambda: False)
        self._on_restart = on_restart or (lambda reason, item: None)
        self._on_idle = on_idle or (lambda: None)
        self._max_attempts = max_attempts
        self._max_unhealthy = max_unhealthy_restarts
        self._poll = poll_seconds
        self._clock = clock
        self._executor = None

    def __enter__(self) -> ResilientPool:
        return self

    def __exit__(self, *exc_info) -> bool:
        self._discard_executor()
        return False

    def run(self, items: Iterable[Any], submit: Callable[[Any, Any], Future]) -> Iterator[Outcome]:
        """Yields one `Outcome` per item, in completion order. `submit` is
        `(executor, item) -> Future`."""
        queue: deque[tuple[int, Any]] = deque(enumerate(items))
        stalls: dict[int, int] = {}
        crashes: dict[int, int] = {}
        in_flight: dict[Future, tuple[int, Any, float]] = {}
        completed_since_restart = 0
        unhealthy_restarts = 0
        stopping = False
        self._executor = self._factory()

        while queue or in_flight:
            if not stopping and self._should_stop():
                # Pause: no new file starts. The ones running finish (or
                # meet their deadline), so their work is not thrown away.
                stopping = True
                queue.clear()

            pool_broken = False
            while not stopping and queue and len(in_flight) < self._workers:
                index, item = queue.popleft()
                try:
                    future = submit(self._executor, item)
                except (BrokenProcessPool, RuntimeError):
                    queue.appendleft((index, item))
                    pool_broken = True
                    break
                in_flight[future] = (index, item, self._clock())

            if not in_flight and not pool_broken:
                break

            lost: list[tuple[int, Any]] = []
            if in_flight:
                done, _ = wait(list(in_flight), timeout=self._poll, return_when=FIRST_COMPLETED)
                for future in done:
                    index, item, _started = in_flight.pop(future)
                    try:
                        value = future.result()
                    except CancelledError:
                        if not stopping:
                            queue.appendleft((index, item))
                        continue
                    except BrokenProcessPool:
                        lost.append((index, item))
                        pool_broken = True
                        continue
                    except Exception as exc:
                        completed_since_restart += 1
                        yield Outcome(item, ERROR, exc)
                        continue
                    completed_since_restart += 1
                    yield Outcome(item, OK, value)

            if pool_broken:
                # The executor is dead: everything still in flight died with it.
                lost.extend((index, item) for index, item, _started in in_flight.values())
                in_flight.clear()
                healthy = completed_since_restart > 0
                unhealthy_restarts = 0 if healthy else unhealthy_restarts + 1
                completed_since_restart = 0
                self._on_restart("broken", lost[0][1] if lost else None)
                giving_up = unhealthy_restarts >= self._max_unhealthy
                retry: list[tuple[int, Any]] = []
                for index, item in lost:
                    crashes[index] = crashes.get(index, 0) + 1
                    if giving_up or stopping or crashes[index] >= self._max_attempts:
                        # Left untouched by the caller: a crash says nothing
                        # about which file caused it, so none is failed.
                        yield Outcome(item, CRASHED)
                    else:
                        retry.append((index, item))
                if giving_up:
                    for _index, item in queue:
                        yield Outcome(item, CRASHED)
                    queue.clear()
                    break
                queue.extendleft(reversed(retry))
                self._restart_executor()
                continue

            now = self._clock()
            expired = {
                future for future, (_index, item, started) in in_flight.items()
                if now - started > self._deadline_for(item)
            }
            if expired:
                victims = list(in_flight.items())
                in_flight.clear()
                healthy = completed_since_restart > 0
                unhealthy_restarts = 0 if healthy else unhealthy_restarts + 1
                completed_since_restart = 0
                if stopping:
                    break  # paused: nothing will be retried, so nothing to announce
                first_expired = next(item for future, (_i, item, _s) in victims if future in expired)
                self._on_restart("stalled", first_expired)
                if unhealthy_restarts >= self._max_unhealthy:
                    raise PoolStalledError(first_expired)
                retry = []
                for future, (index, item, _started) in victims:
                    if future in expired:
                        stalls[index] = stalls.get(index, 0) + 1
                        if healthy and stalls[index] >= self._max_attempts:
                            yield Outcome(item, TIMED_OUT, self._deadline_for(item))
                        else:
                            # To the back of the queue: the others run first,
                            # and their completing is what tells a stuck file
                            # from a stuck drive — with one worker (economy
                            # mode) the stuck file would otherwise always be
                            # alone in flight, and look like the drive.
                            queue.append((index, item))
                        continue
                    retry.append((index, item))
                queue.extendleft(reversed(retry))
                self._restart_executor()
                continue

            self._on_idle()

    def _restart_executor(self) -> None:
        self._discard_executor()
        self._executor = self._factory()

    def _discard_executor(self) -> None:
        executor, self._executor = self._executor, None
        if executor is None:
            return
        # A worker stuck in a kernel call (a file open the Drive client never
        # answers) ignores everything except being killed. `_processes` is
        # private but stable since 3.8; anything without it (a thread pool
        # in the tests) simply has nothing to kill.
        processes = getattr(executor, "_processes", None) or {}
        for process in list(processes.values()):
            try:
                process.kill()
            except Exception:
                pass
        shutdown = getattr(executor, "shutdown", None)
        if shutdown is not None:
            try:
                shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

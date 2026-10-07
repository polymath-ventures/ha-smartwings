"""Virtual time for the harness: jump the event loop's clock instead of sleeping.

``install`` replaces ``loop.time`` on the running loop with real time plus an offset.
Everything that schedules through the loop (``asyncio.sleep``, ``call_later``,
``asyncio.timeout``, zigpy's request timeouts, Home Assistant's timers) reads that clock,
so a quirk's sleeps, zigpy's retries and the motor model all share one timeline. Real time
still flows underneath, so thread-bound work behaves normally; time only jumps when a
test calls ``advance`` or ``run``, and never while executor work is outstanding.

Executor jobs started by the operation ``run`` awaits hold virtual time until they
finish; jobs started elsewhere (unrelated background work) do not. Known limits, accepted
because harness callers always pass a coroutine straight into ``run``:

* hand ``run`` a coroutine, not an executor future created before the call, or the
  future's thread work is not tracked;
* a background task spawned inside ``run`` stays tracked after ``run`` returns.

Limit: work on a thread that is not an executor job (aiosqlite's own thread) is only
noticed when its result lands, so do lifecycle work that waits on the database (startup,
shutdown) in real time, as ``ZhaHarness`` does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
import math
from typing import Any

from homeassistant.util.async_ import get_scheduled_timer_handles

# Upper bound on how many idle event-loop cycles one settle may take.
_SETTLE_CYCLES = 50
# Real seconds to wait when work is pending on a thread, before looking again.
_THREAD_POLL_S = 0.005
# Set inside run()'s task: executor jobs started there (and in tasks it spawns) are the
# operation's own work, which virtual time must wait for.
_IN_RUN: ContextVar[bool] = ContextVar("virtual_clock_in_run", default=False)


class VirtualClock:
    """Real time plus an offset that tests advance on demand."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Wrap the loop; call install() to take over its clock."""
        self._loop = loop
        self._real_time = loop.time
        self._offset = 0.0
        self._installed = False
        self._saved_slow_callback_duration = loop.slow_callback_duration
        self._real_run_in_executor = loop.run_in_executor
        self._executor_jobs: set[asyncio.Future[Any]] = set()

    def install(self) -> None:
        """Make the loop read this clock and report run()'s executor jobs to it."""
        self._loop.time = self.time  # type: ignore[method-assign]
        self._loop.run_in_executor = self._tracked_run_in_executor  # type: ignore[method-assign]
        # A jump makes callbacks look slow; that is the point, not a problem.
        self._loop.slow_callback_duration = math.inf
        self._installed = True

    def uninstall(self) -> None:
        """Give the loop its real clock back; harmless if never installed."""
        if not self._installed:
            return
        del self._loop.time
        del self._loop.run_in_executor
        self._loop.slow_callback_duration = self._saved_slow_callback_duration
        self._installed = False

    def time(self) -> float:
        """Return the loop's current virtual time."""
        return self._real_time() + self._offset

    async def advance(self, seconds: float) -> None:
        """Run everything due in the next ``seconds`` of virtual time, in order."""
        target = self.time() + seconds
        while True:
            await self._settle()
            if self._executor_jobs:
                await asyncio.sleep(_THREAD_POLL_S)
                continue
            due = self._next_due()
            if due is None or due > target:
                break
            self._jump_to(due)
        self._jump_to(target)
        await self._settle()

    async def run(
        self, awaitable: Awaitable[Any], *, limit: float = 3600.0
    ) -> tuple[Any, float]:
        """Await ``awaitable`` in virtual time; return its result and the virtual time taken.

        Raises TimeoutError, cancelling the awaitable, if it is not done ``limit`` virtual
        seconds after the start.
        """
        token = _IN_RUN.set(True)
        try:
            task = asyncio.ensure_future(awaitable)
        finally:
            _IN_RUN.reset(token)
        start = self.time()
        deadline = start + limit
        while not task.done():
            await self._settle()
            if task.done():
                break
            if self.time() > deadline:
                task.cancel()
                raise TimeoutError(f"still running after {limit} virtual seconds")
            if self._executor_jobs:
                await asyncio.sleep(_THREAD_POLL_S)
                continue
            due = self._next_due()
            if due is None:
                # Waiting on a non-executor thread: let real time pass, don't jump.
                await asyncio.sleep(_THREAD_POLL_S)
            elif due > deadline:
                self._jump_to(deadline)
                await self._settle()
                if not task.done():
                    task.cancel()
                    raise TimeoutError(f"still running after {limit} virtual seconds")
            else:
                self._jump_to(due)
        elapsed = self.time() - start
        if elapsed > limit:
            raise TimeoutError(
                f"finished after {elapsed:.3f} virtual seconds, over {limit}"
            )
        return task.result(), elapsed

    def _tracked_run_in_executor(
        self, executor: Any, func: Callable[..., Any], *args: Any
    ) -> asyncio.Future[Any]:
        future = self._real_run_in_executor(executor, func, *args)
        if _IN_RUN.get():
            self._executor_jobs.add(future)
            future.add_done_callback(self._executor_jobs.discard)
        return future

    def _jump_to(self, when: float) -> None:
        now = self.time()
        if when > now:
            self._offset += when - now

    def _next_due(self) -> float | None:
        handles = [
            h for h in get_scheduled_timer_handles(self._loop) if not h.cancelled()
        ]
        return min((h.when() for h in handles), default=None)

    async def _settle(self) -> None:
        """Let every ready callback run until the loop has nothing immediate to do."""
        for _ in range(_SETTLE_CYCLES):
            await asyncio.sleep(0)
            if not self._loop._ready:  # type: ignore[attr-defined]
                break

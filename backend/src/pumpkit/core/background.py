"""
Work a request starts and doesn't wait for, run as tasks in the backend's own process (ADR 0026).

Nothing outside the process records a task: a restart loses those in flight, so whatever a task
works on must show the User how to start it again. Each task opens its own database session,
since the request's closes when the request ends.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

from pumpkit.core.errors import report_background_exception


class TaskRegistry:
    """The tasks running now, kept so none is garbage collected mid-run and tests can await them."""

    def __init__(self) -> None:
        self._running: set[asyncio.Task[None]] = set()

    async def start(self, name: str, work: Coroutine[Any, Any, None]) -> None:
        """Run `work` on its own, past the end of the request that starts it."""
        task = asyncio.create_task(work, name=name)
        self._running.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            report_background_exception(task.get_name(), error)

    async def wait(self) -> None:
        """Until every task has finished, those started meanwhile included."""
        while self._running:
            await asyncio.gather(*self._running, return_exceptions=True)

    async def cancel(self) -> None:
        """Stop every task and wait for each to unwind, as the process does on shutdown."""
        for task in self._running:
            task.cancel()
        await self.wait()


_tasks = TaskRegistry()


def get_background_tasks() -> TaskRegistry:
    """FastAPI dependency for the process's tasks; tests override it."""
    return _tasks

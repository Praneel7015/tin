"""One lifecycle for the two workers hosted by the switchboard process."""

from __future__ import annotations

import asyncio

from temporalio.worker import Worker


class WorkerGroup:
    """Runs the workers together and shuts them down exactly once.

    Shutdown is idempotent: the deploy drain (on SIGTERM) and the application
    lifespan both request it, and the second request only waits for the first.
    """

    def __init__(self, *workers: Worker) -> None:
        self.workers = workers
        self._tasks: list[asyncio.Task[None]] | None = None
        self._shutdown: asyncio.Task[None] | None = None

    async def run(self) -> None:
        tasks = [asyncio.create_task(worker.run()) for worker in self.workers]
        self._tasks = tasks
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.shutdown()
            await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown is not None and self._shutdown.done()

    async def shutdown(self) -> None:
        if self._shutdown is None:
            self._shutdown = asyncio.create_task(self._stop(), name="temporal-worker-shutdown")
        # A cancelled caller must not cancel the drain that other callers await.
        await asyncio.shield(self._shutdown)

    async def _stop(self) -> None:
        if self._tasks is None:
            return  # never started, so there is nothing to drain
        await asyncio.gather(
            *(self._stop_one(w, t) for w, t in zip(self.workers, self._tasks, strict=True))
        )

    @staticmethod
    async def _stop_one(worker: Worker, run_task: asyncio.Task[None]) -> None:
        if run_task.done():
            return  # already finished, including a worker that failed to start
        # Worker.shutdown() waits for a completion event that a worker failing before
        # it starts polling never sets; its run task finishing is enough in that case.
        stop = asyncio.create_task(worker.shutdown())
        await asyncio.wait({stop, run_task}, return_when=asyncio.FIRST_COMPLETED)
        if not stop.done():
            stop.cancel()
        await asyncio.gather(stop, return_exceptions=True)

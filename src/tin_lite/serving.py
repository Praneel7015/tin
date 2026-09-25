"""Serve HTTP while the Temporal worker drains on shutdown.

Activities running in the worker call back into this same process (the Codex relay
under /internal/codex-api). If uvicorn stopped first, a deploy would cut off every
in-flight model call. On the first SIGTERM/SIGINT this server therefore keeps
accepting requests, asks the worker to stop polling and finish its activities
(bounded by the worker's graceful timeout), and only then lets uvicorn begin its
own HTTP shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from types import FrameType

import uvicorn

logger = logging.getLogger(__name__)

Drain = Callable[[], Awaitable[None]]


class DrainingServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, *, drain: Drain, drain_timeout: float) -> None:
        super().__init__(config)
        self._drain = drain
        self._drain_timeout = drain_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._drain_requested = False

    async def serve(self, sockets=None) -> None:  # type: ignore[no-untyped-def]
        self._loop = asyncio.get_running_loop()
        await super().serve(sockets)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        # Runs as a synchronous signal handler, so it only schedules work on the loop.
        if self._drain_requested and not self.should_exit:
            self._captured_signals.append(sig)
            if sig == signal.SIGINT:
                # An operator's second Ctrl-C stops waiting for the drain.
                logger.warning("Second interrupt during worker drain; stopping HTTP now")
                self.should_exit = True
            # Repeated SIGTERMs (systemd and the `uv run` parent both send one) are
            # absorbed; systemd's TimeoutStopSec is the hard bound.
            return
        if self._drain_requested or self._loop is None or self._loop.is_closed():
            super().handle_exit(sig, frame)
            return
        self._drain_requested = True
        self._captured_signals.append(sig)
        self._loop.call_soon_threadsafe(self._start_drain)

    def _start_drain(self) -> None:
        self._drain_task = asyncio.create_task(self._drain_then_exit(), name="worker-drain")

    async def _drain_then_exit(self) -> None:
        logger.info("Draining the Temporal worker before stopping HTTP")
        try:
            await asyncio.wait_for(self._drain(), timeout=self._drain_timeout)
        except TimeoutError:
            logger.error("Worker drain exceeded %ss; stopping HTTP anyway", self._drain_timeout)
        except Exception:
            logger.exception("Worker drain failed; stopping HTTP anyway")
        else:
            logger.info("Worker drained; stopping HTTP")
        finally:
            self.should_exit = True

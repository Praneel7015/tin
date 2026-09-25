from __future__ import annotations

import asyncio
import signal

import httpx
import pytest
import uvicorn

from tin_lite.serving import DrainingServer
from tin_lite.worker_group import WorkerGroup


async def _ok_app(scope, receive, send):  # type: ignore[no-untyped-def]
    assert scope["type"] == "http"
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _server(drain, *, drain_timeout: float = 5) -> DrainingServer:  # type: ignore[no-untyped-def]
    config = uvicorn.Config(_ok_app, host="127.0.0.1", port=0, lifespan="off", log_level="error")
    return DrainingServer(config, drain=drain, drain_timeout=drain_timeout)


@pytest.mark.asyncio
async def test_exit_handler_waits_for_worker_shutdown_before_http_exit():
    release = asyncio.Event()
    seen: list[bool] = []
    server: DrainingServer

    async def drain() -> None:
        seen.append(server.should_exit)
        await release.wait()
        seen.append(server.should_exit)

    server = _server(drain)
    server._loop = asyncio.get_running_loop()
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit is False
    await asyncio.sleep(0.01)
    assert server._drain_task is not None and not server._drain_task.done()
    # The second SIGTERM (systemd and `uv run` both deliver one) does not cut the drain.
    server.handle_exit(signal.SIGTERM, None)
    await asyncio.sleep(0.01)
    assert server.should_exit is False
    release.set()
    await server._drain_task
    assert seen == [False, False]
    assert server.should_exit is True
    assert server.force_exit is False


@pytest.mark.asyncio
async def test_second_interrupt_stops_waiting_and_timeout_still_exits():
    server = _server(lambda: asyncio.Event().wait())
    server._loop = asyncio.get_running_loop()
    server.handle_exit(signal.SIGINT, None)
    await asyncio.sleep(0.01)
    assert server.should_exit is False
    server.handle_exit(signal.SIGINT, None)
    assert server.should_exit is True
    server._drain_task.cancel()

    timed = _server(lambda: asyncio.Event().wait(), drain_timeout=0.05)
    timed._loop = asyncio.get_running_loop()
    timed.handle_exit(signal.SIGTERM, None)
    await asyncio.sleep(0.01)
    await asyncio.wait_for(timed._drain_task, 2)
    assert timed.should_exit is True


@pytest.mark.asyncio
async def test_http_keeps_serving_while_worker_drains():
    release = asyncio.Event()
    drained = asyncio.Event()

    async def drain() -> None:
        drained.set()
        await release.wait()

    server = _server(drain)
    serving = asyncio.create_task(server.serve())
    for _ in range(500):  # uvicorn exposes no startup event
        if server.started:
            break
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    server.handle_exit(signal.SIGTERM, None)
    # Signals delivered for real are re-raised after serve(); this one was simulated.
    server._captured_signals.clear()
    await asyncio.wait_for(drained.wait(), 2)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://127.0.0.1:{port}/")
    assert response.status_code == 200 and response.text == "ok"
    assert not serving.done()
    release.set()
    await asyncio.wait_for(serving, 5)


class _FakeWorker:
    def __init__(self, *, fail_on_start: bool = False) -> None:
        self.fail_on_start = fail_on_start
        self.stop = asyncio.Event()
        self.shutdowns = 0

    async def run(self) -> None:
        if self.fail_on_start:
            raise RuntimeError("namespace check failed")
        await self.stop.wait()
        await asyncio.sleep(0.02)  # activities finishing

    async def shutdown(self) -> None:
        self.shutdowns += 1
        self.stop.set()
        if self.fail_on_start:
            await asyncio.Event().wait()  # a never-started Temporal worker never completes


@pytest.mark.asyncio
async def test_worker_group_shutdown_is_idempotent_for_drain_then_lifespan():
    worker = _FakeWorker()
    group = WorkerGroup(worker)  # type: ignore[arg-type]
    running = asyncio.create_task(group.run())
    await asyncio.sleep(0)
    await asyncio.gather(group.shutdown(), group.shutdown())
    assert group.is_shutdown
    await group.shutdown()  # the lifespan's later call returns at once
    await asyncio.wait_for(running, 1)
    assert worker.shutdowns == 1


@pytest.mark.asyncio
async def test_worker_group_shutdown_does_not_hang_on_unstarted_workers():
    await asyncio.wait_for(WorkerGroup(_FakeWorker()).shutdown(), 1)  # type: ignore[arg-type]
    healthy, broken = _FakeWorker(), _FakeWorker(fail_on_start=True)
    with pytest.raises(RuntimeError, match="namespace check failed"):
        await asyncio.wait_for(WorkerGroup(healthy, broken).run(), 1)  # type: ignore[arg-type]
    assert healthy.shutdowns == 1

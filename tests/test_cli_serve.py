import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tin_lite import cli, serving


def test_serve_bounds_connection_drain_without_logging_oauth_urls(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "tin_lite.main", SimpleNamespace(app=app))
    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(worker_graceful_shutdown_seconds=300)
    )
    started = []
    monkeypatch.setattr(serving.DrainingServer, "run", lambda self: started.append(self))
    monkeypatch.setattr("sys.argv", ["tin-lite", "serve"])
    cli.main()

    (server,) = started
    assert server.config.app is app
    assert server.config.host == "0.0.0.0"  # noqa: S104
    assert server.config.port == 8000
    assert server.config.access_log is False
    assert server.config.timeout_graceful_shutdown == 20
    assert server._drain_timeout == 360

    asyncio.run(server._drain())  # before startup there is no worker to drain
    app.state.runtime = SimpleNamespace(worker=SimpleNamespace(shutdown=AsyncMock()))
    asyncio.run(server._drain())
    app.state.runtime.worker.shutdown.assert_awaited_once()

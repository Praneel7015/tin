"""Trusted, fixed read-only program. No agent or user-authored code runs in this image."""

import asyncio
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/opt/tin-collection")
from tin_lite.connection_collection import CollectionError
from tin_lite.linkedin_session import read_page

# A search page answers within 90 seconds; a paced engagement read takes up to five minutes.
SECONDS = {"search": 90, "linkedin_posts": 300, "linkedin_reactions": 300}


async def engagement(packet):
    import httpx

    from tin_lite.linkedin_engagement import read_posts, read_reactions

    async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        if packet["kind"] == "linkedin_posts":
            return await read_posts(
                packet["session"],
                packet["actor"],
                client=client,
                now=datetime.now(UTC),
                window_days=packet["window_days"],
                limit=packet["limit"],
            )
        return await read_reactions(
            packet["session"],
            packet["actor"],
            client=client,
            activity_urn=packet["activity_urn"],
            thread_urn=packet["thread_urn"],
            start=packet["start"],
        )


signal.alarm(45)
request = Path("/run/tin-collection/request.json")
result = {"error": "cloud_failed"}
try:
    raw = request.read_bytes()
    request.unlink()
    if len(raw) > 200_000:
        raise ValueError
    packet = json.loads(raw)
    kind = packet.get("kind", "search")
    if kind not in SECONDS or not time.time() < packet["expires_at"] <= time.time() + SECONDS[kind]:
        raise ValueError
    budget = int(packet["expires_at"] - time.time())
    # A paced engagement read is cut off well before its sandbox is.
    signal.alarm(max(1, min(45, budget)) if kind == "search" else max(1, min(260, budget - 20)))
    if kind == "search":
        result = asyncio.run(
            read_page(
                packet["session"],
                packet["source"],
                packet["keywords"],
                packet["page"],
                document=packet.get("document") is True,
            )
        )
    else:
        result = asyncio.run(engagement(packet))
except CollectionError as exc:
    result = {"error": exc.code}
except Exception:
    result = {"error": "cloud_failed"}
finally:
    request.unlink(missing_ok=True)
    destination = Path("/run/tin-collection/result.json")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(result, stream, separators=(",", ":"))

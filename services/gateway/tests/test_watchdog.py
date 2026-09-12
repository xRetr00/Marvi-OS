"""The request timer, and the long polls it must not call slow."""

from __future__ import annotations

import time

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from marvi_gateway import watchdog


def test_a_long_poll_waiting_is_not_a_slow_request(monkeypatch, caplog) -> None:
    """`/agents?after=` waits by design; it filled errors.log every 25 seconds."""
    monkeypatch.setattr(watchdog, "SLOW_REQUEST", 0.05)
    app = FastAPI()
    watchdog.slow_requests(app)

    @app.get("/feed")
    def feed(after: int | None = Query(default=None)) -> dict:
        time.sleep(0.1)
        return {"after": after}

    client = TestClient(app)
    with caplog.at_level("WARNING"):
        client.get("/feed", params={"after": 3})
        assert not [r for r in caplog.records if "took" in r.getMessage()]
        client.get("/feed")
        assert [r for r in caplog.records if "/feed took" in r.getMessage()]

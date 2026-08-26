"""Stable Marvi health facade for the vendored runtime status ledger."""

from __future__ import annotations

from typing import Any

from ._vendor import activate


def snapshot() -> dict[str, Any]:
    activate(managed=True)
    from gateway.status import read_runtime_status, resolve_gateway_liveness

    runtime = read_runtime_status()
    live = resolve_gateway_liveness(runtime=runtime, use_cache=False)
    return {
        "service": "marvi-messaging",
        "running": live.running,
        "pid": live.pid,
        "source": live.source,
        "probe_error": live.probe_error,
        "runtime": runtime,
    }

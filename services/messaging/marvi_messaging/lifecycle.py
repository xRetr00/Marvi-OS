"""Marvi-owned lifecycle API over the bundled messaging engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ._engine import activate


@dataclass(frozen=True)
class GatewayRunOptions:
    replace: bool = False
    verbosity: int | None = 0
    external_supervisor: bool = False


def run_gateway(options: GatewayRunOptions) -> int:
    """Run messaging until the reusable gateway completes graceful teardown."""
    if options.external_supervisor:
        import os
        os.environ["MARVI_MESSAGING_EXTERNAL_SUPERVISOR"] = "1"
    activate(managed=True)

    from gateway.run import _exit_after_graceful_shutdown, start_gateway

    try:
        success = asyncio.run(
            start_gateway(replace=options.replace, verbosity=options.verbosity)
        )
        exit_code = 0 if success else 1
    except KeyboardInterrupt:
        exit_code = 0
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)

    # The engine has already saved sessions, stopped adapters/schedulers, and
    # released resources. Reuse its wedge-proof finalization primitive.
    _exit_after_graceful_shutdown(exit_code)
    return exit_code  # reachable only in tests that stub the hard-exit helper


def request_shutdown() -> bool:
    """Ask the active messaging process to perform a planned graceful stop."""
    activate(managed=True)
    from gateway.status import resolve_gateway_liveness, terminate_pid, write_planned_stop_marker

    live = resolve_gateway_liveness(use_cache=False)
    if not live.running or live.pid is None:
        return False
    write_planned_stop_marker(live.pid)
    terminate_pid(live.pid, force=False)
    return True

"""Composio's telemetry, which nobody asked for and nothing turned off.

Every SDK method is wrapped in a tracer that posts one event per call to
`telemetry.composio.dev`. In `providers.log` for one ordinary afternoon that
is a POST roughly twice a second, all day, from a machine whose whole point is
that it runs here. On an exception the event carries `traceback.format_exc()`
-- the stack of a failure inside Marvi, sent to a third party.
"""

from __future__ import annotations

import contextvars
import threading
import types

from marvi_gateway.accounts import _quiet


def sdk_shaped_like_composio() -> types.ModuleType:
    """The parts of the SDK `_quiet` reaches for, and nothing else."""
    module = types.ModuleType("composio")
    module.core = types.ModuleType("composio.core")
    module.core.models = types.ModuleType("composio.core.models")
    base = types.ModuleType("composio.core.models.base")
    telemetry = types.ModuleType("composio.core.models._telemetry")

    sent: list[object] = []

    def push_event(event: object) -> None:
        sent.append(event)

    telemetry.push_event = push_event
    telemetry.sent = sent
    base.allow_tracking = contextvars.ContextVar("allow_tracking", default=True)
    base.push_event = push_event
    module.core.models.base = base
    module.core.models._telemetry = telemetry
    return module


def test_the_supported_switch_is_set() -> None:
    module = sdk_shaped_like_composio()
    _quiet(module)
    assert module.core.models.base.allow_tracking.get() is False


def test_a_fresh_thread_still_sends_nothing() -> None:
    """The switch alone is not enough, which is why there is a second half.

    `allow_tracking` is a `ContextVar`, and a new thread starts from a fresh
    context where the default is `True` again. Measured before this:

        after _quiet   : False
        inside a task  : False
        in a new thread: True

    Marvi reaches accounts from her own threads -- the Mind, the schedules --
    not only from request handlers, so the queue is stopped as well.
    """
    module = sdk_shaped_like_composio()
    _quiet(module)

    tracking: list[bool] = []

    def worker() -> None:
        tracking.append(module.core.models.base.allow_tracking.get())
        module.core.models.base.push_event(("metric", {"functionName": "anything"}))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert tracking == [True], "the ContextVar no longer resets in a thread; check the second half"
    assert module.core.models._telemetry.sent == [], "an event left the machine"


def test_quieting_twice_does_not_stack_stubs() -> None:
    # `_quiet` runs on every client build, and replacing an already-replaced
    # function with a wrapper of itself is how a no-op grows a stack.
    module = sdk_shaped_like_composio()
    _quiet(module)
    once = module.core.models._telemetry.push_event
    _quiet(module)
    assert module.core.models._telemetry.push_event is once


def test_an_sdk_that_moved_things_still_leaves_a_working_client() -> None:
    # Turning telemetry off must never be the reason accounts stop working.
    # A module with none of these attributes is what a future release looks
    # like from here.
    _quiet(types.ModuleType("composio"))

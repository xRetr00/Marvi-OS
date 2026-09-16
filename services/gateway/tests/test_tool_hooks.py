"""Plugins can watch every tool call, and cannot break one by watching badly."""

from __future__ import annotations

import pytest

from marvi_gateway import plugins
from marvi_gateway.tools import ToolRegistry, ToolSpec


def _registry_with_hooks(*handlers):
    context = plugins.PluginContext(plugin="watcher")
    for event, handler in handlers:
        context.register_hook(event, handler)
    loaded = plugins.LoadedPlugin("watcher", plugins.Manifest(name="watcher"), context, None)
    registry = ToolRegistry()
    registry.register(ToolSpec("double", "Double a number for the test.", {"n": int}, False, lambda n: n * 2))
    registry.register(ToolSpec("boom", "Always fails for the test.", {}, False, lambda: 1 / 0))
    assert plugins.bridge_hooks(registry, loaded) == len(handlers)
    return registry


def test_pre_and_post_see_the_call_and_its_result() -> None:
    seen: list[tuple] = []
    registry = _registry_with_hooks(
        ("pre_tool_call", lambda **kw: seen.append(("pre", kw["tool_name"], kw["args"]))),
        ("post_tool_call", lambda **kw: seen.append(("post", kw["result"], kw["error"]))),
    )
    assert registry.execute(registry.get("double"), {"n": 4}) == 8
    assert seen == [("pre", "double", {"n": 4}), ("post", 8, "")]


def test_a_failing_tool_still_reports_to_post() -> None:
    seen: list[str] = []
    registry = _registry_with_hooks(("post_tool_call", lambda **kw: seen.append(kw["error"])))
    with pytest.raises(ZeroDivisionError):
        registry.execute(registry.get("boom"), {})
    assert seen and seen[0].startswith("ZeroDivisionError")


def test_a_broken_watcher_does_not_break_the_tool() -> None:
    """A `post_tool_call` watcher is exactly that; it cannot fail a call.

    A broken `pre_tool_call` is the opposite case and refuses the call instead
    -- a guardrail that crashed has not consented. See `test_hooks.py`.
    """

    def broken(**_kw):
        raise RuntimeError("hook bug")

    registry = _registry_with_hooks(("post_tool_call", broken))
    assert registry.execute(registry.get("double"), {"n": 1}) == 2


def test_unknown_events_are_refused_by_the_router() -> None:
    with pytest.raises(ValueError):
        ToolRegistry().add_hook("on_everything", lambda **_: None)


def test_every_call_records_what_it_cost_the_context() -> None:
    """M6 starts with measuring: which tools produce the big results."""
    from marvi_gateway.tools import _result_size

    assert _result_size(None) == 0
    assert _result_size("twelve chars") == 12
    assert _result_size({"files": ["a", "b"]}) == len('{"files": ["a", "b"]}')
    # Anything that will not serialise is still measured, never an exception.
    assert _result_size(object()) > 0

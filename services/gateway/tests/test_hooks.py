"""What a plugin may watch, and the one thing the user can let it refuse."""

from __future__ import annotations

import pytest

from marvi_gateway import hooks, plugins
from marvi_gateway.tools import ToolBlockedError, ToolRegistry, ToolSpec


@pytest.fixture(autouse=True)
def clean_shared(monkeypatch):
    monkeypatch.delenv(hooks.GUARDS_SETTING, raising=False)
    hooks.shared.clear()
    yield
    hooks.shared.clear()


def _registry(*handlers, plugin: str = "guard"):
    context = plugins.PluginContext(plugin=plugin)
    for event, handler in handlers:
        context.register_hook(event, handler)
    loaded = plugins.LoadedPlugin(plugin, plugins.Manifest(name=plugin), context, None)
    registry = ToolRegistry()
    registry.register(
        ToolSpec("touch", "Touch a path for the test.", {"path": str}, False, lambda path: path)
    )
    assert plugins.bridge_hooks(registry, loaded) == len(handlers)
    return registry


def _finance_guard(**kw):
    if "Finance" in str(kw["args"].get("path", "")):
        return {"action": "block", "message": "Finance is off limits."}
    return None


# -- the grant ----------------------------------------------------------------


def test_an_installed_plugin_watches_and_does_not_refuse(caplog) -> None:
    """The default. Installing a plugin does not hand it a veto."""
    registry = _registry(("pre_tool_call", _finance_guard))

    with caplog.at_level("WARNING"):
        assert registry.execute(registry.get("touch"), {"path": "D:/Finance/ledger.xlsx"}) == (
            "D:/Finance/ledger.xlsx"
        )

    # And the author is told once why their block did nothing.
    said = " ".join(record.getMessage() for record in caplog.records)
    assert "not allowed to" in said


def test_a_granted_plugin_refuses(monkeypatch) -> None:
    monkeypatch.setenv(hooks.GUARDS_SETTING, "guard")
    registry = _registry(("pre_tool_call", _finance_guard))

    with pytest.raises(ToolBlockedError, match="off limits"):
        registry.execute(registry.get("touch"), {"path": "D:/Finance/ledger.xlsx"})
    # Still only what it refused: everything else runs.
    assert registry.execute(registry.get("touch"), {"path": "D:/Notes/todo.md"}) == "D:/Notes/todo.md"


def test_the_grant_names_the_plugin(monkeypatch) -> None:
    monkeypatch.setenv(hooks.GUARDS_SETTING, "somebody_else")
    registry = _registry(("pre_tool_call", _finance_guard))
    assert registry.execute(registry.get("touch"), {"path": "D:/Finance/x"}) == "D:/Finance/x"

    monkeypatch.setenv(hooks.GUARDS_SETTING, "a, guard ,b")  # spaces and a list
    assert hooks.may_block("guard") is True
    monkeypatch.setenv(hooks.GUARDS_SETTING, "*")
    assert hooks.may_block("anything") is True
    monkeypatch.delenv(hooks.GUARDS_SETTING)
    assert hooks.may_block("guard") is False


# -- failure containment ------------------------------------------------------


def test_a_granted_hook_that_crashes_refuses_rather_than_consents(monkeypatch) -> None:
    """A guardrail that failed has not approved anything."""

    def broken(**_kw):
        raise RuntimeError("hook bug")

    monkeypatch.setenv(hooks.GUARDS_SETTING, "guard")
    registry = _registry(("pre_tool_call", broken))
    with pytest.raises(ToolBlockedError, match="RuntimeError"):
        registry.execute(registry.get("touch"), {"path": "x"})


def test_an_ungranted_hook_that_crashes_is_only_logged() -> None:
    def broken(**_kw):
        raise RuntimeError("hook bug")

    registry = _registry(("pre_tool_call", broken))
    assert registry.execute(registry.get("touch"), {"path": "x"}) == "x"


def test_a_watcher_that_crashes_does_not_break_the_call() -> None:
    def broken(**_kw):
        raise RuntimeError("hook bug")

    registry = _registry(("post_tool_call", broken))
    assert registry.execute(registry.get("touch"), {"path": "x"}) == "x"


# -- the shape of the contract ------------------------------------------------


def test_only_tool_calls_can_be_refused(monkeypatch) -> None:
    monkeypatch.setenv(hooks.GUARDS_SETTING, "*")
    hooks.shared.register("pre_turn", lambda **_kw: {"action": "block", "message": "no"})
    assert hooks.shared.veto("pre_turn", surface="chat", text="hi", thread_id="t") == ""
    with pytest.raises(ValueError):
        hooks.shared.register("pre_turn", lambda **_kw: None, guard=True)


def test_the_events_a_plugin_may_register_for() -> None:
    assert set(hooks.EVENTS) <= set(plugins.HOOKS)
    with pytest.raises(ValueError):
        hooks.shared.register("on_anything", lambda **_kw: None)
    with pytest.raises(ValueError):
        ToolRegistry().add_hook("pre_turn", lambda **_kw: None)  # not the router's event


def test_a_memory_write_and_a_confirmation_reach_their_watchers(tmp_path) -> None:
    from marvi_gateway.memory import MemoryStore
    from marvi_gateway.runtime import RuntimeStore

    seen: list[tuple] = []
    hooks.shared.register(
        "on_memory_write", lambda **kw: seen.append(("memory", kw["subject"], kw["trusted"]))
    )
    hooks.shared.register(
        "on_confirmation", lambda **kw: seen.append(("confirm", kw["tool"], kw["state"]))
    )

    MemoryStore(tmp_path / "memory.db").remember("Shereef", "Prefers tea.")
    RuntimeStore().issue_confirmation("send_email", {"to": "x@y.z"}, "Send an email", "to x@y.z")

    assert seen == [("memory", "Shereef", True), ("confirm", "send_email", "issued")]


def test_a_turn_raises_pre_and_post_however_it_ends(tmp_path) -> None:
    from marvi_gateway.chat import Chat, ChatStore

    seen: list[tuple] = []
    hooks.shared.register("pre_turn", lambda **kw: seen.append(("pre", kw["surface"], kw["text"])))
    hooks.shared.register("post_turn", lambda **kw: seen.append(("post", kw["error"] != "")))

    talk = Chat(store=ChatStore(tmp_path / "chat.db"))
    list(talk.send_stream("hello"))  # no provider configured: the turn ends in an error

    assert seen == [("pre", "chat", "hello"), ("post", True)]

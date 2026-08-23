"""Desktop plugins.

The interesting properties are not "does a clone work". They are: does Marvi
stop depending on another application's directory, can a plugin escape the
place it is allowed to live, and is `register_tool` a request rather than a
grant.
"""

from __future__ import annotations

import os
import re
import sys
from types import SimpleNamespace

import pytest

from marvi_gateway import plugins, room

MANIFEST = """\
name: smart_room
version: 0.6.0
description: "Smart room engine for Marvi — presence fusion, Tuya LAN control."
kind: backend
platforms:
  - windows
pip_dependencies:
  - ai-edge-litert==2.1.6
  - sounddevice==0.5.5
provides_tools:
  - smart_room_state
  - smart_room_set_light
hooks:
  - on_gateway_start
  - on_gateway_stop
"""


@pytest.fixture
def plugin_dir(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    (root / "smart_room").mkdir(parents=True)
    (root / "smart_room" / "plugin.yaml").write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setenv("MARVI_PLUGIN_ROOT", str(root))
    monkeypatch.setenv("MARVI_PLUGIN_DATA", str(tmp_path / "plugin-data"))
    return root


# -- the manifest --------------------------------------------------------------


def test_the_manifest_is_read_as_the_plugin_wrote_it(plugin_dir) -> None:
    manifest = plugins.read_manifest(plugin_dir / "smart_room")

    assert manifest.name == "smart_room"
    assert manifest.version == "0.6.0"
    assert manifest.platforms == ("windows",)
    assert manifest.pip_dependencies == ("ai-edge-litert==2.1.6", "sounddevice==0.5.5")
    assert manifest.provides_tools == ("smart_room_state", "smart_room_set_light")
    assert manifest.hooks == ("on_gateway_start", "on_gateway_stop")
    # Quoted, with an em dash and a colon inside. The parser is small; it still
    # has to survive the description the real plugin actually ships.
    assert "presence fusion" in manifest.description


def test_a_manifest_without_a_name_is_refused(tmp_path) -> None:
    (tmp_path / "plugin.yaml").write_text("version: 1.0.0\n", encoding="utf-8")
    with pytest.raises(plugins.PluginError, match="no name"):
        plugins.read_manifest(tmp_path)


def test_a_missing_manifest_says_so_rather_than_crashing(tmp_path) -> None:
    with pytest.raises(plugins.PluginError, match=re.escape("no plugin.yaml")):
        plugins.read_manifest(tmp_path)


def test_a_plugin_for_another_platform_is_skipped_and_says_why() -> None:
    linux_only = plugins.Manifest(name="x", platforms=("linux",))
    supported, why = linux_only.runs_here()

    if sys.platform.startswith("win"):
        assert supported is False
        # Naming both sides is what makes this actionable rather than a shrug.
        assert "linux" in why and "windows" in why


def test_a_plugin_with_no_platform_list_runs_anywhere() -> None:
    assert plugins.Manifest(name="x").runs_here()[0] is True


# -- the source list -----------------------------------------------------------


def test_the_source_list_is_data(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "plugin-sources.json").write_text(
        '{"plugins": [{"name": "a", "repo": "https://example.invalid/a", "ref": "v1"}]}',
        encoding="utf-8",
    )
    found = plugins.sources(tmp_path)

    assert [s.name for s in found] == ["a"]
    assert found[0].ref == "v1"


def test_one_malformed_entry_does_not_hide_the_rest(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "plugin-sources.json").write_text(
        '{"plugins": [{"no_name": true}, {"name": "b", "repo": "https://example.invalid/b"}]}',
        encoding="utf-8",
    )
    assert [s.name for s in plugins.sources(tmp_path)] == ["b"]


def test_a_missing_source_list_is_empty_not_an_error(tmp_path) -> None:
    assert plugins.sources(tmp_path) == []


def test_an_absent_ref_follows_the_remotes_own_default(tmp_path) -> None:
    # `main` was assumed once, and the first plugin was on `master`. An empty
    # ref means "ask the remote", which is right more often than any guess.
    config = tmp_path / "config"
    config.mkdir()
    (config / "plugin-sources.json").write_text(
        '{"plugins": [{"name": "a", "repo": "https://example.invalid/a"}]}', encoding="utf-8"
    )
    assert plugins.sources(tmp_path)[0].ref == ""


# -- the boundary --------------------------------------------------------------


def test_remove_refuses_a_name_that_escapes_the_plugin_root(plugin_dir) -> None:
    # A plugin name comes from a config file, and a config file is edited by
    # hand. `../..` must not delete the state directory.
    with pytest.raises(plugins.PluginError, match="outside"):
        plugins.remove("../..")


def test_removing_a_plugin_keeps_its_data(plugin_dir) -> None:
    data = plugins.data_root() / "smart_room"
    data.mkdir(parents=True)
    (data / "state.json").write_text("{}", encoding="utf-8")

    detail = plugins.remove("smart_room")

    assert not plugins.installed("smart_room")
    # Room history is the user's, and an update should not be able to lose it.
    assert (data / "state.json").is_file()
    assert "data is still in" in detail


def test_removing_something_absent_is_not_an_error(plugin_dir) -> None:
    assert "not installed" in plugins.remove("nothing-here")


# -- Marvi-owned plugin data ---------------------------------------------------


def test_loading_exports_marvis_plugin_data_root(plugin_dir, monkeypatch) -> None:
    monkeypatch.delenv("MARVI_PLUGIN_DATA", raising=False)
    monkeypatch.setattr(plugins.importlib, "import_module", lambda _name: SimpleNamespace(register=lambda _ctx: None))

    plugins.load("smart_room")

    assert os.environ["MARVI_PLUGIN_DATA"] == str(plugins.data_root())


def test_the_room_no_longer_looks_in_the_other_applications_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARVI_ROOM_HOME", raising=False)
    monkeypatch.setenv("MARVI_PLUGIN_DATA", str(tmp_path / "plugin-data"))

    home = room._sidecar_home()

    assert home.name == room.PLUGIN_NAME
    assert str(tmp_path) in str(home)


def test_the_room_home_can_still_be_pointed_elsewhere(monkeypatch, tmp_path) -> None:
    # Someone already running the engine under another host should be able to
    # point Marvi at that copy rather than run a second one.
    monkeypatch.setenv("MARVI_ROOM_HOME", str(tmp_path / "elsewhere"))
    assert room._sidecar_home() == tmp_path / "elsewhere"


# -- register_tool is a request ------------------------------------------------


def test_a_plugin_collects_requests_and_cannot_reach_the_router() -> None:
    context = plugins.PluginContext(plugin="p")
    context.register_tool(
        name="p_write",
        schema={"type": "object"},
        handler=lambda **_: None,
        toolset="p",
        emoji="x",
        # A plugin passing something the host does not know must not break the
        # host; extra keys are accepted and ignored.
        confirm=False,
    )

    assert [t.name for t in context.tools] == ["p_write"]
    # Nothing was registered anywhere. The caller decides, having seen the ask.
    assert not hasattr(context, "registry")


def test_an_unknown_hook_is_recorded_rather_than_rejected(caplog) -> None:
    context = plugins.PluginContext(plugin="p")
    context.register_hook("on_something_else", lambda: None)

    # A plugin may know about a host event Marvi does not raise; that is not an
    # error, but the reason it never fires should be discoverable.
    assert "on_something_else" in context.hooks


def test_a_failing_hook_is_reported_not_raised(plugin_dir) -> None:
    loaded = plugins.LoadedPlugin(
        name="p",
        manifest=plugins.Manifest(name="p"),
        context=plugins.PluginContext(plugin="p"),
        module=None,
    )

    def explode() -> None:
        raise RuntimeError("no device")

    loaded.context.hooks["on_gateway_stop"] = [explode]

    # Shutdown must finish. A plugin that cannot stop cleanly is not a reason to
    # leave the rest of the shutdown undone.
    problems = plugins.fire(loaded, "on_gateway_stop")

    assert len(problems) == 1
    assert "no device" in problems[0]


def test_status_reports_a_declared_but_uninstalled_plugin(tmp_path, plugin_dir) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "plugin-sources.json").write_text(
        '{"plugins": [{"name": "absent", "repo": "https://example.invalid/a", "why": "because"}]}',
        encoding="utf-8",
    )
    rows = plugins.status(tmp_path)

    assert rows[0]["installed"] is False
    assert rows[0]["detail"] == "not installed"
    assert rows[0]["why"] == "because"


def _declare(tmp_path) -> None:
    """A sources file naming the installed plugin, so `status` has a row."""
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "plugin-sources.json").write_text(
        '{"plugins": [{"name": "smart_room", "repo": "https://example.invalid/r", "why": "rooms"}]}',
        encoding="utf-8",
    )


def test_a_plugin_that_failed_to_import_does_not_look_healthy(tmp_path, plugin_dir) -> None:
    """The failure this exists for, exactly as it happened.

    The Gateway started while the room plugin's import was broken, skipped it,
    and carried on. `/plugins` went on reporting version, commit, ten tools and
    "installed"; the only visible symptom was the room saying "sidecar not
    connected" -- which is the consequence, not the cause. The reason sat in a
    log file, and the plugin had already been repaired upstream.
    """
    _declare(tmp_path)
    plugins.note_not_running("smart_room", "importing smart_room failed: No module named 'x'")
    try:
        row = next(r for r in plugins.status(tmp_path) if r["name"] == "smart_room")
    finally:
        plugins.note_loaded("smart_room")

    assert row["installed"] is True
    assert row["running"] is False
    assert "No module named" in row["detail"]


def test_a_loaded_plugin_is_running(tmp_path, plugin_dir) -> None:
    _declare(tmp_path)
    plugins.note_loaded("smart_room")
    row = next(r for r in plugins.status(tmp_path) if r["name"] == "smart_room")

    assert row["running"] is True
    assert row["detail"] == "installed"


# -- the bridge ----------------------------------------------------------------


SCHEMA = {
    "name": "p_set",
    "description": "Set a thing",
    "parameters": {
        "type": "object",
        "properties": {
            "on": {"type": "boolean"},
            "brightness": {"type": "integer"},
            "label": {"type": "string"},
        },
        "required": ["on"],
    },
}


def _loaded_with(*requests: plugins.ToolRequest) -> plugins.LoadedPlugin:
    context = plugins.PluginContext(plugin="p")
    context.tools.extend(requests)
    return plugins.LoadedPlugin(
        name="p", manifest=plugins.Manifest(name="p"), context=context, module=None
    )


def test_a_bridged_tool_requires_confirmation_unless_marvi_says_otherwise() -> None:
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    loaded = _loaded_with(
        plugins.ToolRequest(name="p_set", schema=SCHEMA, handler=lambda args: args),
        plugins.ToolRequest(name="p_read", schema=SCHEMA, handler=lambda args: args),
    )

    plugins.bridge_tools(registry, loaded, read_only=frozenset({"p_read"}))

    # Default-deny: a plugin does not get to call its own writes harmless.
    assert registry.get("p_set").sensitive is True
    assert registry.get("p_read").sensitive is False


def test_room_vision_reads_are_safe_but_identity_changes_are_not() -> None:
    from marvi_gateway.room import READ_ONLY_PLUGIN_TOOLS

    assert "smart_room_vision" in READ_ONLY_PLUGIN_TOOLS
    assert "smart_room_vision_identity" not in READ_ONLY_PLUGIN_TOOLS


def test_json_schema_becomes_required_and_optional_arguments() -> None:
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    plugins.bridge_tools(
        registry,
        _loaded_with(plugins.ToolRequest(name="p_set", schema=SCHEMA, handler=lambda args: args)),
    )
    spec = registry.get("p_set")

    assert spec.arguments == {"on": bool}
    assert spec.optional == {"brightness": int, "label": str}


def test_a_plugin_cannot_replace_a_tool_marvi_already_has() -> None:
    """Installing a plugin must not silently redefine an existing tool."""
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="p_set",
            description="Marvi's own",
            arguments={},
            sensitive=True,
            handler=lambda: "built-in",
        )
    )
    bridged = plugins.bridge_tools(
        registry,
        _loaded_with(
            plugins.ToolRequest(name="p_set", schema=SCHEMA, handler=lambda args: "plugin")
        ),
    )

    assert bridged == []
    assert registry.get("p_set").handler() == "built-in"


def test_marvis_guard_runs_before_the_plugins_handler_and_can_refuse() -> None:
    """The property the room's sleep rule depends on.

    The plugin's own handler knows nothing about Marvi's rules. Bridging it
    without a guard in front would be a second path to the light that skips the
    one the built-in tools apply.
    """
    from marvi_gateway.tools import ToolRegistry

    called: list[str] = []

    def handler(args):
        called.append("plugin ran")
        return args

    def guard(tool: str, arguments: dict) -> None:
        called.append(f"guard saw {tool}")
        if arguments.get("on") is True:
            raise room.SleepProtectedError("the room is asleep")

    registry = ToolRegistry()
    plugins.bridge_tools(
        registry,
        _loaded_with(plugins.ToolRequest(name="p_set", schema=SCHEMA, handler=handler)),
        guard=guard,
    )

    with pytest.raises(room.SleepProtectedError):
        registry.get("p_set").handler(on=True)
    # Refused before the plugin was reached, not after.
    assert called == ["guard saw p_set"]

    registry.get("p_set").handler(on=False)
    assert called == ["guard saw p_set", "guard saw p_set", "plugin ran"]


def test_the_room_guard_refuses_a_bridged_write_while_asleep() -> None:
    """End to end with the real guard, against the real rule."""

    class Asleep:
        def state(self):
            return {"state": {"modes": {"active_mode": "sleep"}, "light": {"on": True}}}

        def snapshot(self):
            return {}

    guard = room.sleep_guard(Asleep())

    # Only switching a light off is permitted while asleep.
    guard("smart_room_set_light", {"on": False})
    for tool, arguments in (
        ("smart_room_set_light", {"on": True}),
        ("smart_room_set_mode", {"mode": "reading"}),
        ("smart_room_override", {}),
    ):
        with pytest.raises(room.SleepProtectedError):
            guard(tool, arguments)
    # A tool the rule has no opinion about is not blocked by it.
    guard("smart_room_health", {})


def test_the_room_guard_is_inert_while_the_room_is_awake() -> None:
    class Awake:
        def state(self):
            return {"state": {"modes": {"active_mode": "normal"}, "light": {"on": False}}}

        def snapshot(self):
            return {}

    guard = room.sleep_guard(Awake())
    guard("smart_room_set_light", {"on": True})
    guard("smart_room_set_mode", {"mode": "focus"})


def test_the_room_guard_refuses_when_it_cannot_tell_whether_the_room_is_asleep() -> None:
    """Fail closed. Not knowing is not the same as awake.

    `state()` already falls back to the on-disk snapshot, so it raises only when
    there is no state at all. The first version treated that as "not asleep",
    which meant a room whose engine was not running accepted every write the
    rule exists to refuse.
    """

    class Unreachable:
        def state(self):
            raise room.RoomUnavailableError("plugin not running")

        def snapshot(self):
            return None

    guard = room.sleep_guard(Unreachable())
    with pytest.raises(room.SleepProtectedError, match="cannot tell"):
        guard("smart_room_set_mode", {"mode": "reading"})
    # Reads are still allowed; the rule is about changing the room.
    guard("smart_room_state", {})


# -- context providers ---------------------------------------------------------


def test_a_plugins_context_line_reaches_the_prompt() -> None:
    """The room engine always offered this and Marvi never called it.

    `build_context_line` carries what the engine knows about the room, including
    its own vision block — whether the owner is visible, what they appear to be
    doing, whether they are asleep. Marvi consumes it without owning a camera.
    """
    context = plugins.PluginContext(plugin="room")
    context.register_context_provider("room", lambda: "Room: reading, light 40%, owner present")
    loaded = plugins.LoadedPlugin(
        name="room", manifest=plugins.Manifest(name="room"), context=context, module=None
    )

    assert plugins.context_lines([loaded]) == ["Room: reading, light 40%, owner present"]


def test_a_provider_returning_nothing_is_not_an_error() -> None:
    context = plugins.PluginContext(plugin="room")
    # None is the documented "nothing to say" answer.
    context.register_context_provider("room", lambda: None)
    loaded = plugins.LoadedPlugin(
        name="room", manifest=plugins.Manifest(name="room"), context=context, module=None
    )

    assert plugins.context_lines([loaded]) == []


def test_a_broken_provider_does_not_take_the_turn_down() -> None:
    """This runs on the prompt path. A plugin must not be able to stop a reply."""

    def explode() -> str:
        raise RuntimeError("no state")

    context = plugins.PluginContext(plugin="room")
    context.register_context_provider("room", explode)
    context.register_context_provider("other", lambda: "still here")
    loaded = plugins.LoadedPlugin(
        name="room", manifest=plugins.Manifest(name="room"), context=context, module=None
    )

    # The working one survives its neighbour.
    assert plugins.context_lines([loaded]) == ["still here"]


def test_a_verbose_provider_cannot_eat_the_identity_budget() -> None:
    context = plugins.PluginContext(plugin="room")
    context.register_context_provider("room", lambda: "x" * 5_000)
    loaded = plugins.LoadedPlugin(
        name="room", manifest=plugins.Manifest(name="room"), context=context, module=None
    )

    line = plugins.context_lines([loaded], limit=240)[0]
    assert len(line) == 240


def test_newlines_are_flattened_so_one_line_stays_one_line() -> None:
    context = plugins.PluginContext(plugin="room")
    context.register_context_provider("room", lambda: "Room: reading\nLight: 40%")
    loaded = plugins.LoadedPlugin(
        name="room", manifest=plugins.Manifest(name="room"), context=context, module=None
    )

    assert "\n" not in plugins.context_lines([loaded])[0]


def test_a_plugin_tool_that_duplicates_a_built_in_is_not_bridged() -> None:
    """Fourteen room tools, and four of them were second names for actions
    Marvi already had.

    Both sets reach the same sidecar and both enforce the sleep rule, so the
    plugin's copies added no capability -- only a choice the model had to make
    on every turn about a light, between `room_state` and `smart_room_state`,
    with nothing in either description to choose on.

    "A built-in wins" was already the rule; it could only be applied
    automatically when the two names matched, and these never did.
    """

    class Registry:
        def __init__(self):
            self.specs = {}

        def register(self, spec):
            self.specs[spec.name] = spec

        def get(self, name):
            from marvi_gateway.tools import UnknownToolError

            if name not in self.specs:
                raise UnknownToolError(name)
            return self.specs[name]

    requested = [
        plugins.ToolRequest(name=name, schema={}, handler=lambda _a: None)
        for name in ("smart_room_state", "smart_room_set_light", "smart_room_vision")
    ]
    loaded = SimpleNamespace(
        name="smart_room",
        context=SimpleNamespace(tools=requested),
    )

    registry = Registry()
    bridged = plugins.bridge_tools(registry, loaded, skip=room.DUPLICATE_PLUGIN_TOOLS)

    assert bridged == ["smart_room_vision"]
    assert "smart_room_state" not in registry.specs
    assert "smart_room_set_light" not in registry.specs


def test_the_skipped_tools_are_exactly_the_ones_marvi_registers() -> None:
    """Drift either way is a fault: a name dropped from the built-ins leaves
    the room without that action, and one added leaves the duplicate back."""
    import inspect

    source = inspect.getsource(room.register_room_tools)
    built_in = {f"smart_{name}" for name in ("room_state", "room_health", "room_set_mode",
                                             "room_set_light")}

    for name in built_in:
        assert f'name="{name.removeprefix("smart_")}"' in source, f"{name} has no built-in"
    assert built_in == room.DUPLICATE_PLUGIN_TOOLS

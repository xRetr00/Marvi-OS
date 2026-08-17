"""Desktop plugins.

The interesting properties are not "does a clone work". They are: does Marvi
stop depending on another application's directory, can a plugin escape the
place it is allowed to live, and is `register_tool` a request rather than a
grant.
"""

from __future__ import annotations

import re
import sys

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


# -- the host shim -------------------------------------------------------------


def test_the_shim_points_at_marvis_own_data_not_another_applications(plugin_dir, monkeypatch) -> None:
    """The whole reason this module exists.

    The room read its state and RPC token out of `%LOCALAPPDATA%\\Hermes`, so
    Marvi could only talk to a room another application had started.
    """
    monkeypatch.delitem(sys.modules, "hermes_constants", raising=False)
    plugins._install_hermes_shim()

    import hermes_constants

    home = hermes_constants.get_hermes_home()
    assert str(plugins.data_root()) == home
    assert "Hermes" not in home


def test_the_room_no_longer_looks_in_the_other_applications_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARVI_ROOM_HOME", raising=False)
    monkeypatch.setenv("MARVI_PLUGIN_DATA", str(tmp_path / "plugin-data"))

    home = room._sidecar_home()

    assert home.name == room.PLUGIN_NAME
    assert "Hermes" not in str(home)
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

"""The setup system.

A download that half-worked is worse than one that failed, because something
later will trust it. Most of these tests are about that: nothing is moved into
place unverified, an interruption resumes rather than restarts, and a repeat run
costs nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from marvi_gateway.setup import catalog, installer

BODY = b"x" * 5000
DIGEST = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A repo with a catalog, and an install root nothing else touches."""
    monkeypatch.setenv("MARVI_INSTALL_ROOT", str(tmp_path / "install"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "components.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "components": [
                    {
                        "name": "thing",
                        "kind": "model",
                        "title": "A thing",
                        "why": "Needed for the test.",
                        "needed_for": ["testing"],
                        "source": {"type": "url", "base_url": "https://example.test/files"},
                        "install_to": "models/thing",
                        "files": {"weights.bin": [len(BODY), DIGEST]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def serving(body: bytes = BODY, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(dict(request.headers))
        start = 0
        rng = request.headers.get("range")
        if rng and rng.startswith("bytes="):
            start = int(rng.removeprefix("bytes=").split("-")[0])
            if start >= len(body):
                return httpx.Response(416)
            return httpx.Response(206, content=body[start:])
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def thing(root: Path) -> catalog.Component:
    found = catalog.get(root, "thing")
    assert found is not None
    return found


# -- the catalog ---------------------------------------------------------------


def test_components_are_data_not_code(root) -> None:
    names = {c.name for c in catalog.load(root)}

    # Adding a component is an entry in a JSON file, not a code change.
    assert "thing" in names


def test_a_malformed_entry_does_not_hide_the_rest(root) -> None:
    path = root / "config" / "components.json"
    manifest = json.loads(path.read_text())
    manifest["components"].append({"no_name_field": True})
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert {c.name for c in catalog.load(root)} == {"thing"}


def test_a_missing_catalog_is_empty_not_an_explosion(tmp_path) -> None:
    assert catalog.load(tmp_path) == []


def test_components_can_be_selected_by_capability(root) -> None:
    assert [c.name for c in catalog.for_capability(root, "testing")] == ["thing"]


def test_the_size_is_known_before_downloading(root) -> None:
    # A first run that downloads gigabytes without saying so is a bad first run.
    assert thing(root).bytes_total == len(BODY)
    assert installer.plan([thing(root)])["bytes_total"] == len(BODY)


# -- installing -----------------------------------------------------------------


def test_a_verified_download_lands_in_place(root) -> None:
    outcome = installer.install(thing(root), root, http=serving())

    assert outcome.ok
    assert outcome.bytes_fetched == len(BODY)
    assert (thing(root).target() / "weights.bin").read_bytes() == BODY


def test_a_repeat_run_costs_nothing_and_says_so(root) -> None:
    installer.install(thing(root), root, http=serving())
    again = installer.install(thing(root), root, http=serving())

    # This is what makes `marvi setup` safe to run whenever, which is what makes
    # people actually run it.
    assert again.skipped is True
    assert again.bytes_fetched == 0
    assert again.detail == "already installed"


def test_force_downloads_again(root) -> None:
    installer.install(thing(root), root, http=serving())
    forced = installer.install(thing(root), root, http=serving(), force=True)

    assert forced.bytes_fetched == len(BODY)


def test_a_wrong_hash_is_never_moved_into_place(root) -> None:
    outcome = installer.install(thing(root), root, http=serving(body=b"y" * 5000))

    # A file that failed its check must not sit where something else will trust
    # it. The failure surfaces here, not hours later in another subsystem.
    assert outcome.ok is False
    assert "hash mismatch" in outcome.detail
    assert not (thing(root).target() / "weights.bin").exists()


def test_a_truncated_download_is_caught_by_size(root) -> None:
    outcome = installer.install(thing(root), root, http=serving(body=BODY[:100]))

    assert outcome.ok is False
    assert "wrong size" in outcome.detail


def test_an_http_error_is_reported_not_swallowed(root) -> None:
    outcome = installer.install(thing(root), root, http=serving(status=404))

    assert outcome.ok is False
    assert "404" in outcome.detail


def test_nothing_is_left_where_it_could_be_trusted(root) -> None:
    installer.install(thing(root), root, http=serving(status=500))
    target = thing(root).target()

    # Not even a zero-byte file with the right name.
    assert not (target / "weights.bin").exists()


# -- resuming --------------------------------------------------------------------


def test_an_interrupted_download_resumes(root) -> None:
    target = thing(root).target()
    target.mkdir(parents=True, exist_ok=True)
    # Simulate an interruption: the first 2000 bytes are already on disk.
    (target / "weights.bin.part").write_bytes(BODY[:2000])

    seen: list[dict] = []
    outcome = installer.install(thing(root), root, http=serving(seen=seen))

    assert outcome.ok
    # Model weights are gigabytes on a home connection; restarting from zero is
    # the difference between an annoyance and giving up.
    assert seen[0].get("range") == "bytes=2000-"
    assert outcome.bytes_fetched == len(BODY) - 2000
    assert (target / "weights.bin").read_bytes() == BODY


def test_a_part_longer_than_the_file_starts_over(root) -> None:
    target = thing(root).target()
    target.mkdir(parents=True, exist_ok=True)
    (target / "weights.bin.part").write_bytes(b"z" * (len(BODY) + 500))

    outcome = installer.install(thing(root), root, http=serving())

    # What is on disk is not a prefix of the real file, so resuming would splice
    # two different files together and pass neither check.
    assert outcome.ok
    assert (target / "weights.bin").read_bytes() == BODY


def test_a_server_that_ignores_range_still_works(root) -> None:
    target = thing(root).target()
    target.mkdir(parents=True, exist_ok=True)
    (target / "weights.bin.part").write_bytes(BODY[:2000])

    def ignores_range(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)  # full body despite the header

    outcome = installer.install(
        thing(root), root, http=httpx.Client(transport=httpx.MockTransport(ignores_range))
    )

    # Appending a full body onto a prefix would corrupt it silently.
    assert outcome.ok
    assert (target / "weights.bin").read_bytes() == BODY


# -- removing ---------------------------------------------------------------------


def test_remove_takes_it_away(root) -> None:
    installer.install(thing(root), root, http=serving())
    outcome = installer.remove(thing(root))

    assert outcome.ok
    assert not thing(root).target().exists()


def test_removing_what_is_not_there_is_fine(root) -> None:
    outcome = installer.remove(thing(root))

    assert outcome.ok
    assert outcome.skipped is True


def test_remove_refuses_to_leave_the_install_root(root, tmp_path) -> None:
    import dataclasses

    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    escaping = dataclasses.replace(thing(root), install_to="../../somewhere-else")

    outcome = installer.remove(escaping)

    # A manifest should never point outside the tree Marvi owns, and if one
    # does, deleting it is the wrong response.
    assert outcome.ok is False
    assert "outside" in outcome.detail
    assert outside.exists()


# -- before starting ----------------------------------------------------------------


def test_a_full_disk_is_refused_before_the_first_byte(root, monkeypatch) -> None:
    import shutil

    monkeypatch.setattr(
        installer.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 100, 10)
    )
    enough, detail = installer.disk_space_for([thing(root)])

    # Better than filling the disk halfway through and breaking more than this.
    assert enough is False
    assert "free" in detail


def test_disk_space_is_not_a_problem_when_nothing_is_missing(root) -> None:
    installer.install(thing(root), root, http=serving())

    enough, detail = installer.disk_space_for([thing(root)])
    assert enough is True
    assert detail == "nothing to download"


def test_the_plan_separates_missing_from_present(root) -> None:
    plan = installer.plan([thing(root)])
    assert [entry["name"] for entry in plan["install"]] == ["thing"]

    installer.install(thing(root), root, http=serving())
    assert installer.plan([thing(root)])["already_installed"] == ["thing"]


# -- the real manifest ----------------------------------------------------------------


def test_the_shipped_catalog_loads_and_is_complete() -> None:
    repo = Path(__file__).resolve().parents[3]
    components = catalog.load(repo)
    names = {c.name for c in components}

    assert {"voice-stt", "voice-tts"} <= names
    assert {
        "tts-cute-python",
        "tts-cute-model",
        "tts-voxtream-python",
        "tts-voxtream-model",
    } <= names
    for component in components:
        assert component.title, component.name
        # Someone is being asked to spend disk and time; say what for.
        assert component.why or component.kind == "python", component.name


def test_optional_tts_environments_do_not_borrow_the_shared_venv(tmp_path) -> None:
    from marvi_gateway.setup.installer import state_of

    (tmp_path / ".venv").mkdir()
    component = catalog.Component(
        name="isolated-tts",
        kind="python",
        title="Isolated TTS",
        why="keeps incompatible Torch pins apart",
        project="services/isolated-tts",
        extra={"isolated": True},
    )

    assert state_of(component, tmp_path)["installed"] is False
    (tmp_path / "services" / "isolated-tts" / ".venv").mkdir(parents=True)
    assert state_of(component, tmp_path)["installed"] is True


def test_the_voice_models_carry_real_hashes() -> None:
    repo = Path(__file__).resolve().parents[3]
    stt = catalog.get(repo, "voice-stt")

    assert stt is not None
    assert stt.files
    for spec in stt.files:
        assert len(spec.sha256) == 64, spec.path
        assert spec.size > 0, spec.path


def test_the_huggingface_url_pins_a_revision() -> None:
    repo = Path(__file__).resolve().parents[3]
    stt = catalog.get(repo, "voice-stt")
    url = stt.url_for(stt.files[0])

    # An unpinned download is a different model tomorrow.
    assert stt.revision in url
    assert url.startswith("https://huggingface.co/")


# -- the CLI ---------------------------------------------------------------------


def test_the_cli_finds_the_checkout_it_lives_in() -> None:
    from marvi_gateway import cli

    # It has to work from any working directory, since it is often run from
    # wherever the user happened to be standing.
    assert (cli.repo_root() / "config" / "components.json").exists()


def test_every_command_is_reachable() -> None:
    from marvi_gateway import cli

    parser = cli.build_parser()
    for argv in (
        ["doctor"],
        ["doctor", "--fix"],
        ["diagnostics"],
        ["setup", "--dry-run"],
        ["setup", "voice", "-y"],
        ["models", "list"],
        ["models", "verify", "voice-stt"],
        ["logs", "errors", "-n", "5"],
        ["providers"],
        ["crashes"],
    ):
        assert parser.parse_args(argv).handler is not None


def test_setup_dry_run_downloads_nothing(root, capsys, monkeypatch) -> None:
    from marvi_gateway import cli

    monkeypatch.setattr(cli, "repo_root", lambda: root)

    assert cli.main(["setup", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "Dry run" in printed
    assert not thing(root).target().exists()


def test_setup_says_what_it_would_cost_before_asking(root, capsys, monkeypatch) -> None:
    from marvi_gateway import cli

    monkeypatch.setattr(cli, "repo_root", lambda: root)
    cli.main(["setup", "--dry-run"])

    # Someone is being asked to spend disk and bandwidth.
    printed = capsys.readouterr().out
    assert "Total download" in printed
    assert "Needed for the test." in printed


def test_declining_the_prompt_installs_nothing(root, monkeypatch) -> None:
    from marvi_gateway import cli

    monkeypatch.setattr(cli, "repo_root", lambda: root)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert cli.main(["setup"]) == 0
    assert not thing(root).target().exists()


def test_an_unknown_component_is_refused(root, monkeypatch, capsys) -> None:
    from marvi_gateway import cli

    monkeypatch.setattr(cli, "repo_root", lambda: root)

    assert cli.main(["models", "verify", "nonexistent"]) == 1
    assert "unknown component" in capsys.readouterr().err


def test_the_cli_runs_with_no_gateway_process(root, monkeypatch, capsys) -> None:
    from marvi_gateway import cli

    monkeypatch.setattr(cli, "repo_root", lambda: root)

    # The whole reason the CLI exists: the desktop app cannot fix the desktop
    # app, and neither can an endpoint on a Gateway that will not start.
    assert cli.main(["models", "list"]) in (0, 1)
    assert "thing" in capsys.readouterr().out

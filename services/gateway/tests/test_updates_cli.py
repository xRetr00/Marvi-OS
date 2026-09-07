from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def packaged(root: Path) -> tuple[Path, Path]:
    bootstrap = root / "state" / "bin" / "marvi-bootstrap.exe"
    desktop = root / "apps" / "desktop" / "dist" / "win-unpacked" / "Marvi-OS.exe"
    bootstrap.parent.mkdir(parents=True)
    desktop.parent.mkdir(parents=True)
    (root / ".git").mkdir()
    bootstrap.write_bytes(b"bootstrap")
    desktop.write_bytes(b"desktop")
    return bootstrap, desktop


def available() -> dict[str, object]:
    return {
        "channel": "release",
        "available": True,
        "upToDate": False,
        "current": "11111111aaaaaaaa",
        "target": "22222222bbbbbbbb",
        "targetRef": "v1.2.3",
        "behindBy": 2,
        "commits": [{"sha": "22222222bbbbbbbb", "summary": "Ship terminal updates"}],
        "error": None,
    }


def test_update_command_is_reachable() -> None:
    from marvi_gateway import cli

    parser = cli.build_parser()
    assert parser.parse_args(["update"]).handler is cli.cmd_update
    assert parser.parse_args(["update", "--check"]).check is True


def test_check_reports_without_launching(tmp_path, monkeypatch, capsys) -> None:
    from marvi_gateway import cli, updates

    bootstrap, desktop = packaged(tmp_path)
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(updates, "bootstrap_path", lambda: bootstrap)
    monkeypatch.setattr(updates, "desktop_path", lambda _root: desktop)
    monkeypatch.setattr(updates, "channel", lambda: "release")
    monkeypatch.setattr(updates, "check", lambda *_args: available())
    launched: list[tuple[Path, Path]] = []
    monkeypatch.setattr(updates, "launch", lambda *args: launched.append(args))

    assert cli.main(["update", "--check"]) == 0
    assert launched == []
    printed = capsys.readouterr().out
    assert "v1.2.3" in printed
    assert "Ship terminal updates" in printed


def test_yes_hands_the_request_to_the_packaged_desktop(tmp_path, monkeypatch, capsys) -> None:
    from marvi_gateway import cli, updates

    bootstrap, desktop = packaged(tmp_path)
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(updates, "bootstrap_path", lambda: bootstrap)
    monkeypatch.setattr(updates, "desktop_path", lambda _root: desktop)
    monkeypatch.setattr(updates, "channel", lambda: "release")
    monkeypatch.setattr(updates, "check", lambda *_args: available())
    launched: list[tuple[Path, Path]] = []
    monkeypatch.setattr(updates, "launch", lambda *args: launched.append(args))

    assert cli.main(["update", "--yes"]) == 0
    assert launched == [(desktop, tmp_path)]
    assert "Update started" in capsys.readouterr().out


def test_up_to_date_never_launches(tmp_path, monkeypatch, capsys) -> None:
    from marvi_gateway import cli, updates

    bootstrap, desktop = packaged(tmp_path)
    result = available() | {"available": False, "upToDate": True}
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(updates, "bootstrap_path", lambda: bootstrap)
    monkeypatch.setattr(updates, "desktop_path", lambda _root: desktop)
    monkeypatch.setattr(updates, "check", lambda *_args: result)
    monkeypatch.setattr(updates, "launch", lambda *_args: (_ for _ in ()).throw(AssertionError()))

    assert cli.main(["update", "--yes"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_bootstrap_check_uses_the_shared_contract(tmp_path, monkeypatch) -> None:
    from marvi_gateway import updates

    seen: dict[str, object] = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return SimpleNamespace(stdout='{"available": false, "upToDate": true}', stderr="")

    monkeypatch.setattr(updates.subprocess, "run", run)
    bootstrap = tmp_path / "marvi-bootstrap.exe"
    result = updates.check(bootstrap, tmp_path, "nightly")

    assert result["upToDate"] is True
    assert seen["argv"] == [
        str(bootstrap),
        "check",
        "--install-root",
        str(tmp_path),
        "--channel",
        "nightly",
    ]


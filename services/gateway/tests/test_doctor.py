"""Doctor.

The point of Doctor is that three different failures must produce three
different, correct, actionable answers — because the bug that started this phase
was three failures producing one identical symptom. So most of these tests break
something specific and assert that the finding names it.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from marvi_gateway import doctor
from marvi_gateway.app import create_app
from marvi_gateway.tools import ToolRegistry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(tmp_path / "providers.env"))
    monkeypatch.setenv("MARVI_IDENTITY_DIR", str(tmp_path / "identity"))
    monkeypatch.setenv("MARVI_TOKEN_STORE", str(tmp_path / "tokens.bin"))
    monkeypatch.setenv("MARVI_JOURNAL_DB", str(tmp_path / "journal.sqlite3"))
    monkeypatch.setenv("MARVI_CHAT_DB", str(tmp_path / "chat.sqlite3"))
    return tmp_path


# -- every finding has to be actionable ---------------------------------------


def test_a_failing_check_always_says_how_to_fix_it(isolated) -> None:
    findings = doctor.run_checks()

    for finding in findings:
        if finding.status == "ok":
            continue
        # "Something is wrong" is not a Doctor. Every finding carries a remedy,
        # and a manual one carries instructions specific enough to follow.
        assert finding.remedy.kind != "none", finding.check
        assert finding.remedy.action, finding.check
        if finding.remedy.kind == "manual":
            assert len(finding.remedy.how) > 20, finding.check


def test_findings_are_ordered_worst_first(isolated) -> None:
    order = [doctor.SEVERITY[f.status] for f in doctor.run_checks()]

    assert order == sorted(order)


def test_a_check_that_raises_becomes_a_finding(isolated, monkeypatch) -> None:
    def check_git() -> doctor.Finding:
        raise RuntimeError("the check itself is broken")

    monkeypatch.setattr(doctor, "check_git", check_git)
    findings = {f.check: f for f in doctor.run_checks()}

    # Doctor failing is not an acceptable answer to "why is Marvi broken": the
    # broken check becomes one finding and the rest of the sweep still runs.
    assert findings["git"].status == "warn"
    assert "the check itself is broken" in findings["git"].detail
    assert len(findings) > 5


# -- the three original failures, told apart ----------------------------------


def test_a_missing_uv_is_named_with_the_install_command(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MARVI_UV_PATH", "")
    monkeypatch.setattr(doctor.Path, "exists", lambda _self: False)

    finding = doctor.check_uv()

    assert finding.status == "fail"
    assert finding.remedy.kind == "manual"
    # This was the actual first failure of the phase; it gets the command.
    assert "astral.sh/uv" in finding.remedy.how


def test_uv_outside_the_path_is_still_found(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "uv.exe"
    fake.write_text("")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MARVI_UV_PATH", str(fake))

    # A GUI-launched app does not inherit the PATH a terminal has.
    assert doctor.check_uv().status == "ok"


def test_no_provider_configured_is_a_failure_not_a_warning(isolated, monkeypatch) -> None:
    monkeypatch.setattr(doctor, "configured_profiles", lambda: [])
    finding = doctor.check_providers()

    assert finding.status == "fail"
    assert "Providers page" in finding.remedy.how


def test_configured_but_unreachable_is_its_own_finding(isolated, monkeypatch) -> None:
    class Fake:
        name = "ollama"

    monkeypatch.setattr(doctor, "configured_profiles", lambda: [Fake()])
    monkeypatch.setattr(
        "marvi_gateway.providers.ProviderClient.reachable", lambda self, p, timeout=0.6: False
    )
    finding = doctor.check_provider_reachable()

    # "Configured" and "answering" are different states, and conflating them is
    # how the voice path ends up handed a dead local server.
    assert finding.status == "fail"
    assert "listening" in finding.remedy.how


def test_a_dead_port_is_reported_without_hanging(isolated) -> None:
    finding = doctor.check_livekit(port=59999)

    assert finding.status == "warn"
    assert "59999" in finding.detail


# -- self-healing, and the line it does not cross -----------------------------


def test_an_automatic_remedy_runs_without_asking(isolated, monkeypatch) -> None:
    ran: list[str] = []
    findings = [
        doctor.Finding(
            "made up", "storage", "fail", "gone",
            doctor.Remedy(kind="automatic", action="recreate", run=lambda: ran.append("x") or "done"),
        )
    ]
    applied = doctor.heal(findings)

    assert ran == ["x"]
    assert applied[0]["ok"] is True


def test_a_confirm_remedy_waits_to_be_asked(isolated) -> None:
    ran: list[str] = []
    findings = [
        doctor.Finding(
            "expensive", "storage", "fail", "missing",
            doctor.Remedy(kind="confirm", action="download 4GB", run=lambda: ran.append("x") or "done"),
        )
    ]

    # Anything that spends money, takes real time, or touches another process
    # is a decision, not a repair.
    assert doctor.heal(findings) == []
    assert ran == []
    assert len(doctor.heal(findings, include_confirmed=True)) == 1


def test_a_manual_remedy_is_never_executed(isolated) -> None:
    ran: list[str] = []
    findings = [
        doctor.Finding(
            "permission", "permissions", "fail", "denied",
            doctor.Remedy(
                kind="manual", action="grant it", how="Settings",
                run=lambda: ran.append("x") or "done",
            ),
        )
    ]

    # Even with a runnable attached and everything confirmed, manual means
    # Marvi genuinely cannot — that is the whole category.
    doctor.heal(findings, include_confirmed=True)
    assert ran == []


def test_a_remedy_that_fails_is_reported_not_swallowed(isolated) -> None:
    def broken() -> str:
        raise OSError("still read-only")

    findings = [
        doctor.Finding(
            "storage", "storage", "fail", "unwritable",
            doctor.Remedy(kind="automatic", action="create", run=broken),
        )
    ]
    applied = doctor.heal(findings)

    assert applied[0]["ok"] is False
    assert "still read-only" in applied[0]["outcome"]


def test_a_missing_log_directory_heals_itself(isolated) -> None:
    target = isolated / "logs"
    if target.exists():
        for child in target.iterdir():
            child.unlink()
        target.rmdir()

    doctor.heal(doctor.run_checks())

    assert target.exists()


def test_a_corrupt_database_is_moved_aside_not_deleted(isolated) -> None:
    path = isolated / "journal.sqlite3"
    path.write_bytes(b"this is not a database")
    finding = doctor.check_database("journal", path)

    assert finding.status == "fail"
    assert finding.remedy.kind == "confirm"

    doctor.heal([finding], include_confirmed=True)

    # Losing data to a repair is worse than the corruption that prompted it.
    assert not path.exists()
    assert list(isolated.glob("journal.sqlite3.broken-*"))


def test_a_healthy_database_is_left_alone(isolated) -> None:
    path = isolated / "chat.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.commit()
    connection.close()

    assert doctor.check_database("chat", path).status == "ok"


# -- diagnostics ---------------------------------------------------------------


def test_diagnostics_is_one_pasteable_block(isolated) -> None:
    text = doctor.diagnostics()

    assert "# Marvi OS diagnostics" in text
    assert "## Findings" in text
    assert "errors.log" in text


def test_diagnostics_contains_no_secret(isolated, monkeypatch) -> None:
    import logging

    from marvi_gateway import logs

    monkeypatch.setenv("OPENAI_API_KEY", "sk-diagnostics-leak-check-1")
    logs.shutdown()
    logs.configure(isolated / "logs", console=False)
    logs.redactor().refresh()
    logging.getLogger("marvi_gateway.providers.client").error(
        "boom with sk-diagnostics-leak-check-1"
    )
    import time

    time.sleep(0.3)
    text = doctor.diagnostics()
    logs.shutdown()

    # This block is meant to be pasted into a bug report by someone who will
    # not read it first.
    assert "sk-diagnostics-leak-check-1" not in text


# -- the API -------------------------------------------------------------------


def test_the_endpoint_reports_and_heals(isolated) -> None:
    with TestClient(create_app(tools=ToolRegistry())) as client:
        report = client.get("/doctor").json()
        assert "summary" in report
        assert report["healthy"] == (report["summary"]["fail"] == 0)

        healed = client.post("/doctor/heal", json={}).json()
        # The report must reflect the repair, not the state that prompted it.
        assert "report" in healed
        assert healed["report"]["summary"]["fail"] <= report["summary"]["fail"]


def test_every_finding_serialises_for_the_page(isolated) -> None:
    with TestClient(create_app(tools=ToolRegistry())) as client:
        for finding in client.get("/doctor").json()["findings"]:
            assert set(finding) >= {"check", "area", "status", "detail", "remedy"}
            assert set(finding["remedy"]) >= {"kind", "action", "how", "runnable"}

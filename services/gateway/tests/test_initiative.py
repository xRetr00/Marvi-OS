"""Scheduled initiative.

The scheduler itself is APScheduler's problem; these tests cover the parts
Marvi owns — that a bad tick does not kill the schedule, that pausing stops
decisions without stopping observation, and that ingested items become journal
events exactly once.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.initiative import Initiative
from marvi_gateway.journal import EventJournal
from marvi_gateway.memory import MemoryStore
from marvi_gateway.mind import Mind
from marvi_gateway.policy import DEFAULT_QUIET_START, InitiativeSettings
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry


class FakeIngest:
    def __init__(self, items=None, boom=False):
        self.items = items or []
        self.boom = boom
        self.polls = 0

    def poll(self):
        self.polls += 1
        if self.boom:
            raise RuntimeError("composio down")
        return {"ingested": list(self.items), "skipped": 0, "errors": []}


@pytest.fixture
def parts(tmp_path):
    journal = EventJournal(tmp_path / "journal.sqlite3")
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    mind = Mind(journal, memory=memory)
    yield journal, memory, mind
    memory.close()
    journal.close()


def test_ingested_items_become_journal_events(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, ingest=FakeIngest(["Email: hi", "Event: Standup"]),
                            memory=memory)
    initiative.run_ingest()

    kinds = {e["kind"] for e in journal.pending()}
    assert kinds == {"email", "calendar"}
    assert all(e["trusted"] is False for e in journal.pending())


def test_the_same_ingested_item_is_journalled_once(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, ingest=FakeIngest(["Email: hi"]), memory=memory)
    initiative.run_ingest()
    initiative.run_ingest()

    assert journal.count_pending() == 1


def test_a_failing_job_is_recorded_and_does_not_propagate(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, ingest=FakeIngest(boom=True), memory=memory)

    initiative._guard("ingest", initiative.run_ingest)()  # must not raise

    assert "composio down" in initiative.last_errors["ingest"]
    assert "ingest" not in initiative.last_runs


def test_a_recovered_job_clears_its_error(parts) -> None:
    journal, memory, mind = parts
    ingest = FakeIngest(boom=True)
    initiative = Initiative(mind, journal, ingest=ingest, memory=memory)
    initiative._guard("ingest", initiative.run_ingest)()
    ingest.boom = False
    initiative._guard("ingest", initiative.run_ingest)()

    assert initiative.last_errors == {}
    assert "ingest" in initiative.last_runs


def test_pausing_stops_decisions_but_not_observation(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, ingest=FakeIngest(["Email: hi"]), memory=memory)
    initiative.set_paused(True)

    initiative.run_ingest()
    result = initiative.run_mind()

    # The event was still observed; it just did not become an interruption.
    assert journal.recent()[0]["summary"] == "Email: hi"
    assert result["surfaced"] == []
    assert mind.why()[0]["rule"] == "initiative-paused"


def test_unpausing_shows_what_was_missed(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, ingest=FakeIngest(["Email: hi"]), memory=memory)
    initiative.set_paused(True)
    initiative.run_ingest()
    initiative.set_paused(False)

    # Nothing was decided while paused, so the event is still pending.
    assert journal.count_pending() == 1
    assert initiative.run_mind()["considered"] == 1


def test_reflection_output_is_journalled_as_trusted(parts) -> None:
    journal, memory, mind = parts
    for _ in range(3):
        memory.remember("Coffee at nine", "", kind="episodic")
    Initiative(mind, journal, memory=memory).run_reflect()

    event = journal.pending()[0]
    assert event["source"] == "memory"
    assert event["trusted"] is True


def test_scheduled_reflection_uses_the_auxiliary_memory_seam(parts) -> None:
    journal, memory, mind = parts
    for _ in range(3):
        memory.remember("Coffee at nine", "", kind="episodic")
    seen = []

    def summarise(groups):
        seen.extend(groups)
        return [("Coffee at nine", "Coffee is part of the morning routine.")]

    Initiative(
        mind, journal, memory=memory, memory_summarise=summarise
    ).run_reflect()

    assert seen == [{"subject": "Coffee at nine", "count": 3}]
    assert memory.search("morning routine")[0]["source"] == "reflection"


def test_unknown_presence_does_not_break_the_turn(parts) -> None:
    journal, memory, mind = parts

    def broken_room():
        raise RuntimeError("sidecar unreachable")

    journal.append("room", "alarm_started", "Alarm", trusted=True)
    result = Initiative(mind, journal, memory=memory, room_state=broken_room).run_mind()

    assert result["considered"] == 1


def test_status_reports_what_the_user_needs_to_see(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, memory=memory)
    journal.append("room", "mode_changed", "focus", trusted=True)
    status = initiative.status()

    assert status["paused"] is False
    assert status["running"] is False
    assert status["pending_events"] == 1
    assert status["settings"]["daily_token_budget"] > 0


def test_the_scheduler_starts_and_stops_cleanly(parts) -> None:
    journal, memory, mind = parts
    initiative = Initiative(mind, journal, memory=memory)
    try:
        assert initiative.start() is True
        assert initiative.start() is False  # already running
        assert initiative.status()["running"] is True
    finally:
        initiative.stop()
    assert initiative.status()["running"] is False


# -- routing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiative_endpoints_expose_pause_and_the_decision_log(tmp_path) -> None:
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=ToolRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        status = await c.get("/initiative")
        paused = await c.put("/initiative", json={"paused": True})
        decisions = await c.get("/mind/decisions")

    assert status.status_code == 200
    assert paused.json()["paused"] is True
    assert decisions.status_code == 200
    assert isinstance(decisions.json()["decisions"], list)


# -- every proactivity knob must be reachable ---------------------------------


def test_quiet_hours_and_budget_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_QUIET_START", "21")
    monkeypatch.setenv("MARVI_DAILY_TOKEN_BUDGET", "12345")
    settings = InitiativeSettings.from_env()

    # A quiet-hours window buried in a constant is a setting nobody can reach.
    assert settings.quiet_start == 21
    assert settings.daily_token_budget == 12345


def test_a_bad_setting_falls_back_instead_of_silencing_marvi(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_QUIET_START", "not a number")
    monkeypatch.setenv("MARVI_DAILY_TOKEN_BUDGET", "-5")
    settings = InitiativeSettings.from_env()

    # A typo must not be able to switch proactivity off by accident.
    assert settings.quiet_start == DEFAULT_QUIET_START
    assert settings.daily_token_budget == 0  # clamped, not negative


def test_settings_are_editable_from_the_control_center(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(tmp_path / "providers.env"))
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        body = client.put(
            "/initiative", json={"quiet_start": 22, "daily_token_budget": 9999}
        ).json()

        assert body["settings"]["quiet_start"] == 22
        assert body["settings"]["daily_token_budget"] == 9999
        # Saved the same way provider settings are, so a restart keeps them.
        assert client.get("/initiative").json()["settings"]["quiet_start"] == 22


def test_pausing_still_works_on_its_own(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(tmp_path / "providers.env"))
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        assert client.put("/initiative", json={"paused": True}).json()["paused"] is True

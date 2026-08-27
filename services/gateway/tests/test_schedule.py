"""User-scheduled reminders.

The interesting properties are the refusals and the one exemption: what Marvi
will not let a schedule do, and why an alarm the user set is allowed to be
louder than something Marvi thought of.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.policy import InitiativeSettings, WorldState, evaluate
from marvi_gateway.schedule import (
    MINIMUM_INTERVAL_MINUTES,
    CronAgentExecutor,
    ScheduleError,
    Scheduler,
    ScheduleStore,
    parse_when,
    register_schedule_tools,
)


@pytest.fixture
def store(tmp_path):
    store = ScheduleStore(tmp_path / "schedules.sqlite3")
    yield store
    store.close()


def test_a_reminder_survives_a_restart(tmp_path) -> None:
    """A reminder is the user's data, not scheduler state."""
    path = tmp_path / "schedules.sqlite3"
    first = ScheduleStore(path)
    first.add("wake up", "remind", "cron", "0 7 * * *", "Time to get up")
    first.close()

    second = ScheduleStore(path)
    try:
        found = second.list()
        assert [s.name for s in found] == ["wake up"]
        assert found[0].expression == "0 7 * * *"
        assert found[0].message == "Time to get up"
    finally:
        second.close()


def test_a_schedule_cannot_invent_a_new_capability(store) -> None:
    # The refusal that stops a reminder becoming a way to run commands.
    with pytest.raises(ScheduleError, match="unknown action"):
        store.add("sneaky", "run_shell", "cron", "0 7 * * *")
    with pytest.raises(ScheduleError, match="unknown action"):
        store.add("sneaky", "", "cron", "0 7 * * *")


def test_a_schedule_cannot_become_a_stream(store) -> None:
    with pytest.raises(ScheduleError, match="shortest interval"):
        store.add("chatty", "remind", "interval", "1")
    # At the limit is fine.
    assert store.add("hourly", "remind", "interval", str(MINIMUM_INTERVAL_MINUTES))


def test_a_malformed_cron_is_refused_with_the_shape_it_wanted(store) -> None:
    with pytest.raises(ScheduleError, match="five fields"):
        store.add("bad", "remind", "cron", "0 7 *")


def test_a_schedule_needs_a_name_so_it_can_be_cancelled(store) -> None:
    with pytest.raises(ScheduleError, match="name"):
        store.add("   ", "remind", "cron", "0 7 * * *")


def test_enable_disable_and_remove(store) -> None:
    made = store.add("call mum", "remind", "cron", "0 18 * * 0")

    assert store.set_enabled(made.id, False).enabled is False
    assert store.list(include_disabled=False) == []
    assert store.set_enabled(made.id, True).enabled is True
    assert store.remove(made.id) is True
    assert store.remove(made.id) is False


def test_firing_writes_to_the_journal_and_does_not_speak(store, tmp_path) -> None:
    """A reminder becomes an event the mind decides about, not a speech call."""
    from marvi_gateway.journal import EventJournal

    journal = EventJournal(tmp_path / "journal.sqlite3")
    made = store.add("wake up", "remind", "cron", "0 7 * * *", "Time to get up")
    scheduler = Scheduler(store, journal=journal)

    try:
        assert scheduler.fire(made.id)["ok"] is True

        events = journal.recent(limit=10)
        assert len(events) == 1
        assert events[0]["source"] == "schedule"
        assert events[0]["kind"] == "reminder"
        assert events[0]["summary"] == "Time to get up"
        assert store.get(made.id).last_run is not None
    finally:
        journal.close()


def test_a_disabled_schedule_does_not_fire(store, tmp_path) -> None:
    from marvi_gateway.journal import EventJournal

    journal = EventJournal(tmp_path / "journal.sqlite3")
    made = store.add("off", "remind", "cron", "0 7 * * *", "nope")
    store.set_enabled(made.id, False)

    try:
        assert Scheduler(store, journal=journal).fire(made.id)["skipped"] is True
        assert journal.recent(limit=10) == []
    finally:
        journal.close()


def test_a_failing_schedule_is_recorded_against_itself_not_raised(store) -> None:
    made = store.add("needs a journal", "remind", "cron", "0 7 * * *")
    # No journal wired: the failure belongs to this schedule, and the scheduler
    # must keep running the others.
    outcome = Scheduler(store, journal=None).fire(made.id)

    assert outcome["ok"] is False
    assert store.get(made.id).last_error


def test_firing_something_that_no_longer_exists_is_not_a_crash(store) -> None:
    assert Scheduler(store).fire(9999)["ok"] is False


def test_an_unbuildable_schedule_does_not_take_the_scheduler_down(store) -> None:
    """A cron with five fields can still be nonsense APScheduler refuses."""
    good = store.add("fine", "remind", "interval", "60")
    store._db.execute(
        "UPDATE schedules SET expression = ? WHERE id = ?", ("99 99 99 99 99", good.id)
    )
    store.add("also fine", "remind", "interval", "30")
    store._db.commit()

    scheduler = Scheduler(store)
    try:
        # One is skipped and blamed; the other still runs.
        assert scheduler.start() == 1
        assert "invalid schedule" in (store.get(good.id).last_error or "")
    finally:
        scheduler.stop()


# -- the exemption -------------------------------------------------------------


def _world(**changes):
    base = {
        "now": datetime(2026, 8, 18, 2, 0, tzinfo=UTC),  # inside quiet hours
        "present": True,
        "conversation_active": False,
        "tokens_today": 0,
        "last_surfaced": None,
    }
    base.update(changes)
    return WorldState(**base)


def test_an_insistent_alarm_is_not_downgraded_by_quiet_hours() -> None:
    """An alarm that appears silently on a screen is not an alarm."""
    verdict = evaluate(
        {"source": "schedule", "kind": "insistent_reminder", "trusted": True},
        _world(),
        InitiativeSettings(),
        wanted="speak",
    )

    assert verdict.surface == "speak"
    assert verdict.rule == "allowed"


def test_an_ordinary_schedule_is_still_quiet_at_three_in_the_morning() -> None:
    """The correction to the first version, which exempted every schedule.

    Asking for an hourly mail check is not asking to be woken by it.
    """
    verdict = evaluate(
        {"source": "schedule", "kind": "reminder", "trusted": True},
        _world(),
        InitiativeSettings(),
        wanted="speak",
    )

    assert verdict.surface != "speak"
    assert verdict.rule == "quiet-hours"


def test_marvis_own_idea_is_still_downgraded_at_the_same_moment() -> None:
    """The control for the exemption above.

    `vision:visitor_report`, not `accounts:email`: email is capped at Island by
    its own ceiling, so quiet hours never gets a say and the test would pass
    without proving anything.
    """
    verdict = evaluate(
        {"source": "vision", "kind": "visitor_report", "trusted": True},
        _world(),
        InitiativeSettings(),
        wanted="speak",
    )

    assert verdict.surface != "speak"
    assert verdict.rule == "quiet-hours"


def test_an_insistent_reminder_reaches_an_empty_room() -> None:
    # "Remember your keys" is most useful on the way out.
    verdict = evaluate(
        {"source": "schedule", "kind": "insistent_reminder", "trusted": True},
        _world(present=False, now=datetime(2026, 8, 18, 12, 0, tzinfo=UTC)),
        InitiativeSettings(),
        wanted="speak",
    )

    assert verdict.surface == "speak"


def test_an_insistent_reminder_still_will_not_talk_over_a_conversation() -> None:
    """The exemption is narrow. It is not a licence to interrupt."""
    verdict = evaluate(
        {"source": "schedule", "kind": "insistent_reminder", "trusted": True},
        _world(conversation_active=True),
        InitiativeSettings(),
        wanted="speak",
    )

    assert verdict.surface != "speak"
    assert verdict.rule == "conversation-active"


# -- the tools -----------------------------------------------------------------


def test_a_spoken_time_becomes_a_cron_expression(store) -> None:
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    register_schedule_tools(registry, Scheduler(store))

    made = registry.get("schedule_add").handler(name="wake up", when="07:30")

    # "07:30" is what a person says; cron wants "30 7 * * *".
    assert made["expression"] == "30 7 * * *"
    assert made["kind"] == "cron"

    every = registry.get("schedule_add").handler(
        name="mail", when="60", action="check_accounts"
    )
    assert every["kind"] == "interval"


def test_setting_a_schedule_requires_confirmation(store) -> None:
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    register_schedule_tools(registry, Scheduler(store))

    # A standing instruction that will act again later is worth agreeing to
    # once, rather than discovering at seven in the morning.
    assert registry.get("schedule_add").sensitive is True
    assert registry.get("schedule_remove").sensitive is True
    assert registry.get("schedule_list").sensitive is False


# -- full cron jobs -----------------------------------------------------------


def test_hermes_schedule_forms_are_supported() -> None:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

    assert parse_when("30m", now)[0] == "once"
    assert parse_when("every 2h", now)[:2] == ("interval", "120")
    assert parse_when("0 9 * * 1-5", now)[:2] == ("cron", "0 9 * * 1-5")
    assert parse_when("2026-08-27T09:00:00+00:00", now)[0] == "once"


def test_agent_controls_and_run_history_survive_restart(tmp_path) -> None:
    path = tmp_path / "schedules.sqlite3"
    first = ScheduleStore(path)
    made = first.add(
        name="briefing",
        when="every 2h",
        mode="agent",
        prompt="Summarise the newest account events.",
        provider="openrouter",
        model="small-model",
        effort="low",
        tool_names=["memory_recall", "web_search"],
        delivery="local",
        repeat_count=3,
    )
    first.execution_finish(
        first.execution_start(made.id, "test"),
        success=True,
        result={
            "output": "Nothing urgent.",
            "provider": "openrouter",
            "model": "small-model",
            "tokens": 17,
            "tools_used": ["memory_recall"],
            "delivery_status": "saved_local",
        },
    )
    first.close()

    second = ScheduleStore(path)
    try:
        found = second.get(made.id)
        assert found.mode == "agent"
        assert found.provider == "openrouter"
        assert found.model == "small-model"
        assert found.effort == "low"
        assert found.tool_names == ("memory_recall", "web_search")
        assert found.repeat_count == 3
        assert found.completed_runs == 1
        assert found.last_output == "Nothing urgent."
        assert second.executions(made.id)[0]["tools_used"] == ["memory_recall"]
    finally:
        second.close()


def test_agent_executor_honours_model_and_tool_allowlist(tmp_path) -> None:
    from marvi_gateway.providers.base import Usage
    from marvi_gateway.providers.client import Completion

    class Client:
        def __init__(self) -> None:
            self.calls = []

        def call_with_fallback(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return Completion(
                text="Done.", usage=Usage(input=4, output=2), provider="chosen",
                model="pinned", tool_calls=[],
            )

    client = Client()
    executor = CronAgentExecutor(
        client,
        lambda: [
            {"name": "web_search", "parameters": {}},
            {"name": "terminal_run", "parameters": {}},
        ],
        lambda _name, _arguments: {"status": "executed", "result": {}},
    )
    job = ScheduleStore(tmp_path / "agent.sqlite3")
    try:
        made = job.add(
            name="search", when="30m", mode="agent", prompt="Find the release notes",
            provider="openrouter", model="pinned", effort="high",
            tool_names=["web_search"],
        )
        result = executor(made)
    finally:
        job.close()

    assert result["output"] == "Done."
    assert client.calls[0][1]["preferred"] == "openrouter"
    assert client.calls[0][1]["model"] == "pinned"
    assert client.calls[0][1]["effort"] == "high"
    assert [tool["name"] for tool in client.calls[0][1]["tools"]] == ["web_search"]


def test_unconnected_messaging_target_fails_visibly(store) -> None:
    made = store.add("future DM", "remind", "interval", "60", delivery="telegram:me")
    scheduler = Scheduler(store, journal=object())
    # Use an agent job so the journal stub is irrelevant and delivery is the
    # only failure under test.
    store.update(made.id, {"mode": "agent", "prompt": "say hello"})
    scheduler.executor = lambda _job: {"output": "hello"}

    outcome = scheduler.fire(made.id)

    assert outcome["ok"] is False
    assert "messaging adapter" in (store.get(made.id).last_error or "")


def test_cronjob_tool_exposes_management_and_is_conditionally_sensitive(store) -> None:
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    register_schedule_tools(registry, Scheduler(store))
    spec = registry.get("cronjob")

    assert spec.is_sensitive({"action": "list"}) is False
    assert spec.is_sensitive({"action": "create"}) is True
    made = spec.handler(
        action="create", name="digest", when="every 1h", prompt="Write a digest",
        provider="openrouter", model="small", tool_names=["web_search"],
    )
    assert made["mode"] == "agent"
    assert spec.handler(action="runs", id=made["id"]) == {"executions": []}

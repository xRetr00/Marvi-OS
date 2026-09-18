"""The board: cards that outlive the process that made them."""

from __future__ import annotations

import threading

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.jobs import JobsStore, register_job_tools
from marvi_gateway.tools import ToolRegistry


def test_a_card_moves_through_its_states(tmp_path) -> None:
    store = JobsStore(tmp_path / "jobs.db")
    card = store.add("Fix the failing test", assignee="harvi", mode="fix")

    assert card["status"] == "todo" and card["assignee"] == "harvi"

    run = store.start_run(card["id"])
    assert store.get(card["id"])["status"] == "running"

    store.set_status(card["id"], "blocked", reason="needs_input")
    blocked = store.get(card["id"])
    assert blocked["status"] == "blocked" and blocked["reason"] == "needs_input"

    store.finish_run(run, "completed", "changed a - b to a + b", tokens=14_740)
    done = store.get(card["id"])
    assert done["status"] == "done"
    assert done["runs"][0]["summary"].startswith("changed")
    assert done["runs"][0]["tokens"] == 14_740
    # Every transition is kept, so a card can say what happened to it.
    assert {event["kind"] for event in done["events"]} >= {"created", "running", "blocked", "done"}


def test_a_restart_corrects_a_card_that_says_it_is_running(tmp_path) -> None:
    """The acceptance from the phase file, and the reason cards are a table."""
    store = JobsStore(tmp_path / "jobs.db")
    card = store.add("A long job")
    store.start_run(card["id"])
    store.close()

    reopened = JobsStore(tmp_path / "jobs.db")
    assert reopened.recover() == 1

    after = reopened.get(card["id"])
    assert after["status"] == "failed" and after["reason"] == "restart"
    assert after["runs"][0]["exit_reason"] == "restart"
    # Said plainly rather than left spinning.
    assert any("restarted" in event["detail"] for event in after["events"])


def test_an_owner_comment_on_a_live_card_is_a_steer(tmp_path) -> None:
    store = JobsStore(tmp_path / "jobs.db")
    card = store.add("Rename the thing")
    store.start_run(card["id"])

    commented = store.comment(card["id"], "call it `board`, not `kanban`")
    assert commented["steered"] is True
    # The runner collects it once and it is not resent.
    assert store.unsent_steers(card["id"]) == ["call it `board`, not `kanban`"]
    assert store.unsent_steers(card["id"]) == []

    store.finish_run(store.start_run(card["id"]), "completed", "done")
    after = store.comment(card["id"], "thanks")
    assert after["steered"] is False  # nothing is running to steer


def test_the_board_groups_by_state_and_bumps_a_revision(tmp_path) -> None:
    store = JobsStore(tmp_path / "jobs.db")
    first = store.revision
    store.add("One")
    store.add("Two", assignee="jarvi")

    board = store.board()
    assert len(board["columns"]["todo"]) == 2
    assert board["revision"] > first


def test_the_long_poll_waits_for_a_change_and_then_answers(tmp_path) -> None:
    store = JobsStore(tmp_path / "jobs.db")
    seen: list[int] = []

    waiter = threading.Thread(target=lambda: seen.append(store.wait(store.revision, timeout=5)))
    waiter.start()
    store.add("Something happened")
    waiter.join(timeout=6)

    assert seen and seen[0] > 0


def test_the_tools_read_and_move_the_board(tmp_path) -> None:
    store = JobsStore(tmp_path / "jobs.db")
    registry = ToolRegistry()
    register_job_tools(registry, store)

    made = registry.execute(registry.get("job_add"), {"title": "Buy milk"})
    board = registry.execute(registry.get("jobs_board"), {})
    assert board["todo"][0]["title"] == "Buy milk"

    moved = registry.execute(
        registry.get("job_update"), {"job": made["id"], "status": "done", "note": "got it"}
    )
    assert moved["status"] == "done"
    assert registry.execute(registry.get("job_update"), {"job": "nope"})["error"]


@pytest.mark.asyncio
async def test_the_endpoints_serve_the_board(monkeypatch, tmp_path) -> None:
    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        made = await client.post("/jobs", json={"title": "From the window", "assignee": "owner"})
        assert made.status_code == 200
        card = made.json()

        listed = await client.get("/jobs")
        assert any(one["id"] == card["id"] for one in listed.json()["columns"]["todo"])

        moved = await client.patch(f"/jobs/{card['id']}", json={"status": "running"})
        assert moved.json()["status"] == "running"

        said = await client.post(f"/jobs/{card['id']}/comments", json={"body": "hurry up"})
        assert said.json()["steered"] is True

        missing = await client.get("/jobs/nope")
        assert missing.status_code == 404

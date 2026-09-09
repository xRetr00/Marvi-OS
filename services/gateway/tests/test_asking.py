"""Questions Marvi puts on screen, and what happens when nobody answers one.

Asking on screen is only better than asking aloud if the unanswered case is
handled. A box that can be closed and forgotten is a worse question than a
spoken one, because a spoken one at least gets heard.
"""

from __future__ import annotations

import time

import pytest

from marvi_gateway import asking
from marvi_gateway.asking import Asking, register_asking_tools
from marvi_gateway.tools import ToolRegistry


@pytest.fixture
def store(tmp_path) -> Asking:
    return Asking(tmp_path / "asking.json")


def test_a_question_starts_on_screen_and_says_so_in_words(store) -> None:
    one = store.ask("How do you spell your surname?", about="name", placeholder="Surname")
    assert one.waiting
    # In words, not a code: the model reads this.
    assert store.status(one.id)["state"] == "still on screen, not answered yet"
    assert store.status()["on_screen_now"][0]["id"] == one.id


def test_the_same_question_is_not_asked_twice_at_once(store) -> None:
    """Two boxes for one answer is worse than no box."""
    store.ask("What is your surname?", about="name")
    with pytest.raises(ValueError, match="already on screen"):
        store.ask("What is your surname?", about="name")
    with pytest.raises(ValueError, match="already on screen"):
        store.ask("Different words, same subject", about="name")


def test_closing_the_box_is_a_question_marvi_still_owes_them(store) -> None:
    """The whole point. A closed box is not an answer.

    Without this, `ask_on_screen` is strictly worse than asking out loud: the
    same interruption and no answer, and Marvi never learns she did not get one.
    """
    one = store.ask("What should I call you?", about="name")
    assert store.owed_aloud() == []

    store.settle(one.id, asking.DISMISSED)
    assert [o.id for o in store.owed_aloud()] == [one.id]
    assert store.status(one.id)["state"] == "closed without answering"


def test_leaving_it_alone_counts_the_same_as_closing_it(store) -> None:
    one = store.ask("What is your work address?", about="work")
    later = time.time() + asking.IGNORED_AFTER + 1
    assert one.stale(later)
    assert [o.id for o in store.owed_aloud(later)] == [one.id]


def test_asked_twice_is_the_end_of_it(store) -> None:
    """One box, one spoken follow-up, then stop.

    A question that keeps coming back is more annoying than one never asked,
    which is the thing asking on screen was supposed to improve on.
    """
    one = store.ask("What should I call you?", about="name")
    store.settle(one.id, asking.DISMISSED)
    store.mark_asked_aloud(one.id)

    assert store.owed_aloud() == []
    store.give_up(one.id)
    assert "do not ask again" in store.status(one.id)["state"]


def test_declining_is_permanent_and_blocks_the_subject_not_the_words(store) -> None:
    one = store.ask("What do you do for work?", about="work")
    store.settle(one.id, asking.DECLINED)
    with pytest.raises(ValueError, match="not to be asked"):
        store.ask("Where do you work these days?", about="work")


def test_an_answer_is_readable_and_the_question_settles(store) -> None:
    one = store.ask("How do you spell it?", about="name")
    store.settle(one.id, asking.ANSWERED, "  Shereef   Ibrahim  ")
    said = store.status(one.id)
    assert said["answer"] == "Shereef Ibrahim"  # whitespace normalised
    assert said["state"] == "answered"
    assert not said["waiting"]
    assert store.owed_aloud() == []


def test_it_survives_a_restart(store, tmp_path) -> None:
    """The commonest way to not answer is to walk away; the second is to reboot."""
    one = store.ask("What is your surname?", about="name")
    store.settle(one.id, asking.DISMISSED)

    again = Asking(tmp_path / "asking.json")
    assert [o.id for o in again.owed_aloud()] == [one.id]


def test_the_tools_tell_the_model_not_to_wait(store) -> None:
    registry = ToolRegistry()
    register_asking_tools(registry, store)

    ask = registry.get("ask_on_screen")
    assert "not available yet" in ask.description
    assert "ask_secret" in ask.description, "it must point at the tool for secrets"
    answer = ask.handler(question="What is your surname?", about="name")
    assert "do not wait" in answer["detail"].lower()

    status = registry.get("ask_on_screen_status")
    assert status.handler(question_id=answer["id"])["waiting"] is True
    assert status.handler(question_id="nope")["found"] is False


@pytest.mark.asyncio
async def test_the_desktop_can_settle_a_question_and_needs_the_token(store, monkeypatch) -> None:
    """The box is drawn by the desktop, so the desktop is what reports back."""
    import httpx
    from fastapi import FastAPI

    from marvi_gateway.asking import asking_router

    monkeypatch.setenv("MARVI_LOCAL_TOKEN", "asking-fixture")
    one = store.ask("How do you spell your surname?", about="name")
    audited: list = []

    app = FastAPI()
    app.include_router(asking_router(store, lambda *a: audited.append(a)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/asking")).status_code == 403

        client.headers["x-marvi-local"] = "asking-fixture"
        waiting = (await client.get("/asking")).json()
        assert [q["id"] for q in waiting["waiting"]] == [one.id]

        bad = await client.post(f"/asking/{one.id}", json={"state": "nonsense"})
        assert bad.status_code == 422

        gone = await client.post("/asking/nope", json={"state": "dismissed"})
        assert gone.status_code == 404

        answered = await client.post(
            f"/asking/{one.id}", json={"state": "answered", "answer": "Ibrahim"}
        )
        assert answered.status_code == 200
        assert answered.json()["state"] == "answered"

    assert store.status(one.id)["answer"] == "Ibrahim"
    # The answer is the user's own words and must not reach the audit line.
    assert audited and "Ibrahim" not in str(audited)

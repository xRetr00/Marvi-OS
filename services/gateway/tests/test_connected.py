"""Which accounts answer, said in the prompt rather than discovered by failing.

Six were connected on the owner's machine -- GitHub, Gmail, Google Calendar,
Drive, Notion, YouTube -- one expired and one disconnected, and none of it
reached the request. The tools were always there; whether Gmail answers depends
on a connection made in a settings page, and the recorded failure is Marvi
telling the owner he had no connected accounts.
"""

from __future__ import annotations

from marvi_gateway import connected


def test_nothing_connected_says_nothing() -> None:
    # A block that always appears is a block that costs tokens on machines
    # where it has nothing to report.
    assert connected.describe([]) == ""
    assert connected.describe([{"toolkit": "", "connected": True}]) == ""


def test_the_working_ones_are_named() -> None:
    block = connected.describe(
        [{"toolkit": "gmail", "connected": True}, {"toolkit": "github", "connected": True}]
    )
    assert "github, gmail" in block
    assert "answer right now" in block


def test_a_broken_connector_is_named_as_needing_the_user() -> None:
    """Worse than never set up: the tool is right there and fails.

    She cannot reconnect it herself, so the only useful thing she can do is
    say which one and where.
    """
    block = connected.describe(
        [{"toolkit": "gmail", "connected": True}, {"toolkit": "reddit", "connected": False}]
    )
    assert "reddit" in block
    assert "reconnecting in Settings" in block
    assert "gmail" in block.split("not working")[0], "a working account was listed as broken"


def test_one_working_connection_beats_a_stale_one() -> None:
    """Two connections to the same toolkit, one dead: the toolkit works."""
    block = connected.describe(
        [
            {"toolkit": "gmail", "connected": False},
            {"toolkit": "gmail", "connected": True},
        ]
    )
    assert "answer right now: gmail" in block
    assert "not working" not in block


def test_everything_broken_says_so_plainly() -> None:
    block = connected.describe([{"toolkit": "slack", "connected": False}])
    assert "slack" in block
    assert "will not answer" in block


def test_the_block_stays_short() -> None:
    """Paid on every turn, so it is names and one word of state each."""
    rows = [{"toolkit": f"toolkit{index}", "connected": True} for index in range(40)]
    block = connected.describe(rows)
    assert len(block) < 700, "the account list grew into a page"
    assert block.count("\n") <= 2

"""A source that stops talking, noticed rather than believed.

Every feeder fails the same way: not with an error, but by going quiet. The
last reading stands there looking current forever, which is indistinguishable
from good news. OwnTracks stopped because Tailscale went offline on the phone,
and Marvi reported `home: true` from a geofence dated 24 August for thirteen
days, on a page that said "Phone: HOME" in confident capitals.
"""

from __future__ import annotations

from marvi_gateway.quiet_feeds import BY_ID, Quiet, Watcher


def test_a_live_feed_says_nothing() -> None:
    assert Watcher().look({"phone": 60.0, "camera": 2.0}) == []


def test_a_phone_that_stopped_for_days_is_noticed() -> None:
    found = Watcher().look({"phone": 13 * 86400.0})
    assert [one.feed.id for one in found] == ["phone"]
    said = found[0].sentence("Shereef")
    assert "13 days" in said
    # The actionable half. "Your phone stopped reporting" is a fact; "check
    # Tailscale" is something a person can do about it.
    assert "Tailscale" in said


def test_never_heard_from_is_not_the_same_as_stopped() -> None:
    """A camera that was never configured has not gone quiet -- it was never
    there, and warning about it hourly would be noise about a choice."""
    assert Watcher().look({"camera": None, "phone": None}) == []


def test_it_says_it_once() -> None:
    watcher = Watcher()
    assert watcher.look({"phone": 7 * 3600.0})
    assert watcher.look({"phone": 8 * 3600.0}) == [], "repeated itself an hour later"


def test_much_worse_is_worth_mentioning_again() -> None:
    watcher = Watcher()
    watcher.look({"phone": 7 * 3600.0})
    assert watcher.look({"phone": 20 * 3600.0}), "never mentioned it getting worse"


def test_coming_back_resets_it() -> None:
    watcher = Watcher()
    watcher.look({"phone": 7 * 3600.0})
    watcher.look({"phone": 30.0})
    assert watcher.look({"phone": 7 * 3600.0}), "the next outage was not news"


def test_each_feed_keeps_its_own_patience() -> None:
    # A phone reports on movement and may be still for hours; a camera should
    # never be quiet for a minute. One threshold for both is wrong twice.
    assert BY_ID["phone"].quiet_seconds > BY_ID["camera"].quiet_seconds
    watcher = Watcher()
    found = watcher.look({"phone": 20 * 60.0, "camera": 20 * 60.0})
    assert [one.feed.id for one in found] == ["camera"]


def test_the_sentence_scales_its_units() -> None:
    assert "minutes" in Quiet(BY_ID["camera"], 20 * 60.0).sentence()
    assert "hours" in Quiet(BY_ID["phone"], 9 * 3600.0).sentence()
    assert "days" in Quiet(BY_ID["phone"], 5 * 86400.0).sentence()

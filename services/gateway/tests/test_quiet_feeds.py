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


# -- 16 September: eight false alarms in a day ----------------------------------


def test_a_sensor_that_sees_nobody_is_not_a_sensor_that_stopped() -> None:
    """mmWave stamps when it sees somebody and misses a person sitting still;
    Bluetooth stamps the phone's last advert and a sleeping phone stops. Both
    read as dead feeds through an evening at the desk."""
    from types import SimpleNamespace

    from marvi_gateway import quiet_feeds

    signals = [
        SimpleNamespace(source="mmwave", age=3_000.0),
        SimpleNamespace(source="bluetooth", age=20_000.0),
        SimpleNamespace(source="camera", age=1.0),
        SimpleNamespace(source="phone", age=30_000.0),
    ]
    state = {
        "devices": {
            "tuya_he20": {"online": True, "last_poll": _now_iso()},
            "esp32": {"online": True, "last_seen": _now_iso()},
        }
    }
    ages = quiet_feeds.ages_from(signals, state)
    assert ages["mmwave"] < 60 and ages["bluetooth"] < 60
    assert ages["phone"] == 30_000.0, "the phone's own timestamp is the right one"
    assert [q.feed.id for q in quiet_feeds.Watcher().look(ages)] == ["phone"]


def test_a_sensor_whose_device_really_stopped_is_still_reported() -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from marvi_gateway import quiet_feeds

    long_ago = (datetime.now(UTC) - timedelta(hours=4)).isoformat()
    ages = quiet_feeds.ages_from(
        [SimpleNamespace(source="mmwave", age=10.0)],
        {"devices": {"tuya_he20": {"online": False, "last_poll": long_ago}}},
    )
    assert ages["mmwave"] > 3 * 3600


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()

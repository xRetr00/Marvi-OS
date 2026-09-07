"""The machine noticing its own condition.

Every other feeder watches the world *through* the machine. This one watches
the machine, which is the gap behind "your computer finally has a mind" being
true of everything except the computer.
"""

from __future__ import annotations

from marvi_gateway import voicing
from marvi_gateway.machine import DISK_CRITICAL_GB, DISK_LOW_GB, Machine


def _disks(monkeypatch, free_gb: float, roots=("D:/",)) -> None:
    import shutil

    class _Usage:
        free = free_gb * 1e9

    monkeypatch.setattr("marvi_gateway.machine._drives", lambda: list(roots))
    monkeypatch.setattr(shutil, "disk_usage", lambda _root: _Usage)


def _quiet(monkeypatch) -> None:
    """Only the disks talk, so a test machine's own battery cannot change it."""
    monkeypatch.setattr(Machine, "_look_at_power", lambda _self: [])
    monkeypatch.setattr(Machine, "_look_at_memory", lambda _self: [])
    monkeypatch.setattr(Machine, "_look_at_network", lambda _self: [])


def test_a_healthy_machine_says_nothing(monkeypatch) -> None:
    _quiet(monkeypatch)
    _disks(monkeypatch, 500.0)
    assert Machine().look() == []


def test_a_filling_disk_is_noticed_once(monkeypatch) -> None:
    """Once, not every five minutes forever.

    A disk that has been full for a week is not news. The threshold crossing
    is the event; the state afterwards is not.
    """
    _quiet(monkeypatch)
    _disks(monkeypatch, DISK_LOW_GB - 1)
    machine = Machine()

    first = machine.look()
    assert [r.kind for r in first] == ["disk_low"]
    assert machine.look() == [], "said it twice"


def test_getting_worse_is_news_again(monkeypatch) -> None:
    _quiet(monkeypatch)
    _disks(monkeypatch, DISK_LOW_GB - 1)
    machine = Machine()
    machine.look()

    _disks(monkeypatch, DISK_CRITICAL_GB - 1)
    assert [r.kind for r in machine.look()] == ["disk_critical"]


def test_hovering_on_the_line_does_not_chatter(monkeypatch) -> None:
    # Without the recovery margin, a disk sitting exactly on the threshold
    # alternates between warning and clear forever.
    _quiet(monkeypatch)
    machine = Machine()
    _disks(monkeypatch, DISK_LOW_GB - 0.1)
    assert machine.look()
    for free in (DISK_LOW_GB + 0.5, DISK_LOW_GB - 0.1, DISK_LOW_GB + 1.0):
        _disks(monkeypatch, free)
        assert machine.look() == [], f"chattered at {free}GB"


def test_recovering_properly_rearms_it(monkeypatch) -> None:
    _quiet(monkeypatch)
    machine = Machine()
    _disks(monkeypatch, DISK_LOW_GB - 1)
    assert machine.look()
    _disks(monkeypatch, 500.0)
    assert machine.look() == []
    _disks(monkeypatch, DISK_LOW_GB - 1)
    assert [r.kind for r in machine.look()] == ["disk_low"], "never warned again"


def test_one_broken_sensor_does_not_blind_the_rest(monkeypatch) -> None:
    def _explode(_self):
        raise OSError("sensor gone")

    monkeypatch.setattr(Machine, "_look_at_power", _explode)
    monkeypatch.setattr(Machine, "_look_at_memory", lambda _self: [])
    monkeypatch.setattr(Machine, "_look_at_network", lambda _self: [])
    _disks(monkeypatch, DISK_LOW_GB - 1)
    assert [r.kind for r in Machine().look()] == ["disk_low"]


def test_she_says_it_like_a_person() -> None:
    event = {
        "source": "machine", "kind": "disk_low", "trusted": True,
        "summary": "D: has 16GB free",
        "payload": {"drive": "D", "free_gb": 16.3, "level": "low"},
        "at": 0.0,
    }
    line = voicing.spoken(event, "Shereef")
    assert "16.3" in line and "D" in line
    assert "disk_low" not in line, "read the event kind aloud"


def test_it_does_not_re_announce_a_standing_condition_after_a_restart(monkeypatch, tmp_path) -> None:
    """The Gateway restarts often -- eighteen times in two days -- and each
    restart built a fresh watcher that had never reported anything.

        start 09:33 -> "D: has 16GB free" 09:38
        start 18:51 -> "D: has 16GB free" 18:56
        start 03:10 -> "D: has 16GB free" 03:15

    Exactly five minutes after each, because a full disk is still full.
    """
    _quiet(monkeypatch)
    _disks(monkeypatch, DISK_LOW_GB - 1)
    path = tmp_path / "machine.json"

    first = Machine(path)
    assert [r.kind for r in first.look()] == ["disk_low"]

    # A restart: a new watcher, the same still-full disk.
    again = Machine(path)
    assert again.look() == [], "announced the same full disk after a restart"


def test_a_worse_reading_survives_a_restart(monkeypatch, tmp_path) -> None:
    _quiet(monkeypatch)
    path = tmp_path / "machine.json"
    _disks(monkeypatch, DISK_LOW_GB - 1)
    Machine(path).look()

    _disks(monkeypatch, DISK_CRITICAL_GB - 1)
    assert [r.kind for r in Machine(path).look()] == ["disk_critical"]


def test_memory_pressure_during_a_game_is_not_news(monkeypatch, tmp_path) -> None:
    """It is the game. Complaining about it is complaining about the thing she
    just stood aside for -- and it reached the room as "memory at 92%" a minute
    after FC 26 started."""
    import sys
    import types

    monkeypatch.setattr(Machine, "_look_at_disks", lambda _s: [])
    monkeypatch.setattr(Machine, "_look_at_power", lambda _s: [])
    monkeypatch.setattr(Machine, "_look_at_network", lambda _s: [])
    # The real memory watcher, against a machine that is genuinely tight.
    fake = types.ModuleType("psutil")
    fake.virtual_memory = lambda: types.SimpleNamespace(percent=96.0)
    fake.sensors_battery = lambda: None
    monkeypatch.setitem(sys.modules, "psutil", fake)

    machine = Machine(tmp_path / "m.json")
    assert machine.look(busy_with="FC 26") == [], "complained about the game's own memory"

    # And once the game closes it is not announced as new either: it was
    # already true, and nobody wants to hear about it a second time.
    assert machine.look() == []


def test_memory_pressure_with_nothing_running_is_worth_saying(monkeypatch, tmp_path) -> None:
    import sys
    import types

    monkeypatch.setattr(Machine, "_look_at_disks", lambda _s: [])
    monkeypatch.setattr(Machine, "_look_at_power", lambda _s: [])
    monkeypatch.setattr(Machine, "_look_at_network", lambda _s: [])
    fake = types.ModuleType("psutil")
    fake.virtual_memory = lambda: types.SimpleNamespace(percent=96.0)
    fake.sensors_battery = lambda: None
    monkeypatch.setitem(sys.modules, "psutil", fake)

    # Nothing has the machine, so something has run away and that is news.
    assert [r.kind for r in Machine(tmp_path / "m.json").look()] == ["memory_tight"]

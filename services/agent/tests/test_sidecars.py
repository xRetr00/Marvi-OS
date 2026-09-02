"""Sidecars are closed on shutdown, on switch, and never left holding VRAM.

Marvi runs up to four isolated model runtimes now. Each is a `uv run` wrapper
around a Python process holding a model on a 12 GB card, and the ways a worker
ends are not all polite -- the commonest one, the parent watchdog, calls
`os._exit(0)` and runs no handler at all.

These pin the guarantees rather than the mechanism: something closes every
sidecar, closing twice is harmless, and one that will not die does not keep the
others alive.
"""

from __future__ import annotations

import pytest

from marvi_agent import sidecars


class Sidecar:
    def __init__(self, stubborn: bool = False) -> None:
        self.closed = 0
        self.stubborn = stubborn

    def close(self) -> None:
        self.closed += 1
        if self.stubborn:
            raise RuntimeError("this one will not go")


@pytest.fixture(autouse=True)
def _empty():
    sidecars.close_all()
    yield
    sidecars.close_all()


def test_a_tracked_sidecar_is_closed_on_shutdown() -> None:
    one = Sidecar()
    sidecars.track(one)
    assert sidecars.count() == 1
    sidecars.close_all()
    assert one.closed == 1
    assert sidecars.count() == 0


def test_closing_twice_closes_once() -> None:
    """`close_all` runs from `atexit` and from the parent watchdog both."""
    one = Sidecar()
    sidecars.track(one)
    sidecars.close_all()
    sidecars.close_all()
    assert one.closed == 1


def test_a_sidecar_that_closed_itself_is_not_closed_again() -> None:
    one = Sidecar()
    sidecars.track(one)
    sidecars.forget(one)
    sidecars.close_all()
    assert one.closed == 0


def test_tracking_the_same_one_twice_registers_it_once() -> None:
    one = Sidecar()
    sidecars.track(one)
    sidecars.track(one)
    assert sidecars.count() == 1


def test_one_that_will_not_die_does_not_keep_the_others_alive() -> None:
    stubborn, ordinary = Sidecar(stubborn=True), Sidecar()
    sidecars.track(stubborn)
    sidecars.track(ordinary)
    sidecars.close_all()
    assert ordinary.closed == 1
    assert sidecars.count() == 0


def test_kill_tree_ignores_a_process_that_already_exited() -> None:
    class Gone:
        def poll(self) -> int:
            return 0

    # No exception, no taskkill: a finished process is not a leak.
    sidecars.kill_tree(Gone())  # type: ignore[arg-type]
    sidecars.kill_tree(None)


def test_switching_tts_engine_closes_the_one_being_replaced(monkeypatch) -> None:
    """A sidecar left behind holds its model until the machine restarts.

    The cache is keyed by engine and voice, so a switch does not overwrite the
    old entry -- it adds one, and the key nothing looks up again is a process
    nothing can stop.
    """
    from marvi_agent import voice_models

    started: list[voice_models._SidecarEngine] = []

    def build(cls, engine: str, voice: str):
        made = object.__new__(voice_models._SidecarEngine)
        made.engine, made.voice = engine, voice
        made._process = None
        made.closed = False
        started.append(made)
        return made

    monkeypatch.setattr(voice_models._SidecarEngine, "__new__", build)
    monkeypatch.setattr(
        voice_models._SidecarEngine,
        "close",
        lambda self: setattr(self, "closed", True),
    )
    voice_models._SIDECARS.clear()

    first = voice_models._SidecarEngine.shared("cutetts-distill", "cute-reference")
    second = voice_models._SidecarEngine.shared("voxtream2", "english-male")

    assert first is not second
    assert first.closed is True, "the replaced engine kept its model in VRAM"
    assert len(voice_models._SIDECARS) == 1


def test_asking_for_the_same_engine_twice_reuses_the_open_one(monkeypatch) -> None:
    from marvi_agent import voice_models

    voice_models._SIDECARS.clear()
    monkeypatch.setattr(
        voice_models._SidecarEngine, "__init__", lambda self, engine, voice: None
    )
    monkeypatch.setattr(voice_models._SidecarEngine, "close", lambda self: None)

    first = voice_models._SidecarEngine.shared("cutetts-distill", "cute-reference")
    second = voice_models._SidecarEngine.shared("cutetts-distill", "cute-reference")

    assert first is second, "a second request started a second copy of the model"
